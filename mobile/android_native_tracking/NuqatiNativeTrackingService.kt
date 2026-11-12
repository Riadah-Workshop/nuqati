package com.example.nuqati_driver

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.*
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.Priority
import com.google.android.gms.location.FusedLocationProviderClient
import org.json.JSONObject
import kotlin.math.*

/** Offline-first experimental native engine. Never uploads location or contacts the network.
 *  Data is kept separate from the legacy Flutter SQLite database until migration is verified.
 */
class NuqatiNativeTrackingService : Service(), LocationListener {
    companion object {
        const val ACTION_START = "com.example.nuqati_driver.NATIVE_START"
        const val ACTION_STOP = "com.example.nuqati_driver.NATIVE_STOP"
        const val ACTION_PRIVACY = "com.example.nuqati_driver.NATIVE_PRIVACY"
        const val CHANNEL = "nuqati_native_tracking"
        const val ALERT_CHANNEL = "nuqati_native_safety"
        const val PREFS = "nuqati_native_policy"
        const val GPS_SAMPLE_INTERVAL_MS = 2000L
        const val TRIP_END_DELAY_MS = 240000L
    }
    private lateinit var manager: LocationManager
    private lateinit var db: NativeStore
    private lateinit var notifications: NotificationManager
    private var tracking = false
    private lateinit var fusedClient: FusedLocationProviderClient
    private var fusedCallback: LocationCallback? = null
    private var providerMode = "none"
    private var callbackCount = 0L
    // Fused registration success does not guarantee location callbacks (notably indoors).
    // Keep a platform GPS listener available if fused goes silent, without restarting trips.
    private val locationHandler = Handler(Looper.getMainLooper())
    private var watchdog: Runnable? = null
    private var gpsFallbackActive = false
    private var locationStartedMs = 0L
    private var lastGapReportedAtMs = 0L
    private var gpsGapOpen = false
    private var lastRecoveryAtMs = 0L
    private var screenReceiverRegistered = false
    private var screenOffSinceMs = 0L
    private var lastWatchdogTickElapsedMs = 0L
    private var lastCallbackElapsedMs = 0L
    private var lastCallbackWallMs = 0L
    private var lastFusedDeliveryLogElapsedMs = 0L
    private var lastFusedAvailability: Boolean? = null
    private var watchdogChecks = 0L
    private fun trace(event: String, durationMs: Long = 0L) {
        // Durable local diagnostics: survives Flutter suspension and app restarts.
        try { db.saveGap(event, System.currentTimeMillis(), durationMs, providerMode) } catch (_: Exception) { }
        diagnostic(event)
        android.util.Log.i("NuqatiGPSWatchdog", event + " provider=" + providerMode + " trip=" + tripId)
    }
    private fun permissionsSummary(): String {
        val fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
        val enabled = try { manager.isProviderEnabled(LocationManager.GPS_PROVIDER) } catch (_: Exception) { false }
        val power = getSystemService(POWER_SERVICE) as PowerManager
        return "fine=" + fine + "_gps=" + enabled + "_wake=" + (wakeLock?.isHeld == true) +
            "_interactive=" + power.isInteractive + "_power_save=" + power.isPowerSaveMode
    }
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_OFF -> {
                    screenOffSinceMs = SystemClock.elapsedRealtime()
                    trace("screen_off_tracking=" + tracking + "_" + permissionsSummary())
                }
                Intent.ACTION_SCREEN_ON -> {
                    val offDuration = if (screenOffSinceMs > 0L) SystemClock.elapsedRealtime() - screenOffSinceMs else 0L
                    trace("screen_on_tracking=" + tracking + "_callback_age_ms=" +
                        (if (lastCallbackElapsedMs > 0L) SystemClock.elapsedRealtime() - lastCallbackElapsedMs else -1L) +
                        "_" + permissionsSummary(), offDuration)
                    screenOffSinceMs = 0L
                }
            }
        }
    }
    private var tripId: Long? = null
    // A short, monotonic-time movement window is less sensitive to one weak GPS fix.
    // Native Android remains the sole trip detector; the Flutter legacy monitor is untouched.
    private val movementWindow = java.util.ArrayDeque<Location>()
    private var consecutivePretripStillFixes = 0
    private var lastOrderedFixNanos = 0L
    private var stationarySince = 0L
    private var stationaryAnchor: Location? = null
    private var stationaryFixes = 0
    private var lastStationaryFixMs = 0L
    private var resumeMovementFirst: Location? = null
    private fun publishStationaryCountdown() {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
            .putLong("stationary_since_ms", if (tripId != null) stationarySince else 0L)
            .putInt("stationary_fix_count", if (tripId != null) stationaryFixes else 0)
            .putLong("last_stationary_fix_ms", if (tripId != null) lastStationaryFixMs else 0L).apply()
    }
    private fun elapsedBetweenMs(a: Location, b: Location): Long =
        (b.elapsedRealtimeNanos - a.elapsedRealtimeNanos) / 1_000_000L

    /** Confirm a real route, not merely one speed value or a jump in coordinates.
     *  Three valid motion points, >=6 s, >=18 m net, directional consistency.
     *  This typically starts a trip after 6-12 s of driving, depending on GPS delivery.
     */
    private fun confirmsTripStart(fix: Location, reportedKmh: Float, derivedKmh: Float): Boolean {
        val speedQuality = Build.VERSION.SDK_INT < 26 || !fix.hasSpeedAccuracy() ||
            fix.speedAccuracyMetersPerSecond <= 2.5f
        val measuredMotion = fix.hasSpeed() && reportedKmh >= 8f &&
            fix.accuracy <= 25f && speedQuality
        // Some phones report GPS speed=0 despite sustained movement. Permit a
        // guarded position-based fallback only with high-quality consecutive fixes.
        val derivedMotion = (!fix.hasSpeed() || reportedKmh <= 3f) && derivedKmh >= 10f &&
            fix.accuracy <= 12f && (previousCandidate?.accuracy ?: 100f) <= 12f
        if (!measuredMotion && !derivedMotion) {
            // Do not restart detection because of ONE zero-speed reading.
            // Two consecutive reliable stopped fixes clear the candidate window.
            if (fix.hasSpeed() && reportedKmh < 5f && fix.accuracy <= 25f) {
                consecutivePretripStillFixes++
                if (consecutivePretripStillFixes >= 2) movementWindow.clear()
            }
            diagnostic(if (fix.accuracy > 25f) "start_waiting_for_accuracy" else "start_waiting_for_motion")
            return false
        }
        consecutivePretripStillFixes = 0
        val last = movementWindow.peekLast()
        if (last != null && elapsedBetweenMs(last, fix) !in 700L..13000L) movementWindow.clear()
        movementWindow.addLast(Location(fix))
        while (movementWindow.size > 5) movementWindow.removeFirst()
        while (movementWindow.size > 1 &&
            elapsedBetweenMs(movementWindow.peekFirst()!!, fix) > 20000L) movementWindow.removeFirst()
        if (movementWindow.size < 3) {
            diagnostic("start_confirming_movement_samples=" + movementWindow.size)
            return false
        }
        val samples = movementWindow.toList()
        val elapsed = elapsedBetweenMs(samples.first(), samples.last())
        if (elapsed < 6000L) { diagnostic("start_confirming_6_seconds"); return false }
        var pathMeters = 0f
        var substantialSegments = 0
        var measuredEvidence = 0
        for (i in samples.indices) {
            val sample = samples[i]
            if (sample.hasSpeed() && sample.speed * 3.6f >= 8f && sample.accuracy <= 25f &&
                (Build.VERSION.SDK_INT < 26 || !sample.hasSpeedAccuracy() || sample.speedAccuracyMetersPerSecond <= 2.5f)) {
                measuredEvidence++
            }
            if (i == 0) continue
            val prior = samples[i-1]
            val dtMs = elapsedBetweenMs(prior, sample)
            if (dtMs !in 700L..13000L) { diagnostic("start_inconsistent_timestamp"); return false }
            val step = prior.distanceTo(sample)
            val mps = max(if (prior.hasSpeed()) prior.speed else 0f, if (sample.hasSpeed()) sample.speed else 0f)
            val plausibleMax = max(25f, mps * (dtMs / 1000f) * 1.8f + 15f)
            if (step > plausibleMax) { diagnostic("start_inconsistent_displacement"); return false }
            if (step >= 4f) substantialSegments++
            pathMeters += step
        }
        val netMeters = samples.first().distanceTo(samples.last())
        val directional = pathMeters > 0f && netMeters / pathMeters >= 0.65f
        // Missing / stuck-zero GPS speed: require MORE observed displacement
        // than the ordinary Doppler-speed path to guard against indoor drift.
        val fallbackOnly = measuredEvidence == 0 && samples.all {
            it.accuracy <= 12f && (!it.hasSpeed() || it.speed * 3.6f <= 3f)
        } && netMeters >= 25f && pathMeters >= 28f
        val confirmed = (measuredEvidence >= 2 || fallbackOnly) &&
            substantialSegments >= 2 && netMeters >= 18f &&
            pathMeters >= 20f && directional
        diagnostic(if (confirmed) "start_motion_confirmed" else
            "start_check_route_net=" + netMeters.toInt() + "_samples=" + samples.size)
        return confirmed
    }

    private fun resetStationaryState() {
        stationarySince = 0L
        stationaryAnchor = null
        stationaryFixes = 0
        lastStationaryFixMs = 0L
        resumeMovementFirst = null
        publishStationaryCountdown()
    }

    /** A GPS speed spike on its own must NEVER cancel the trip-end countdown.
     *  Only sustained, spatially supported movement is allowed to resume driving.
     */
    private fun updateStationaryState(fix: Location, speedKmh: Float, now: Long) {
        if (fix.accuracy > 35f) return
        if (speedKmh < 4.5f) {
            if (stationarySince == 0L) {
                stationarySince = now
                stationaryAnchor = Location(fix)
                stationaryFixes = 0
                publishStationaryCountdown()
                diagnostic("stop_countdown_started")
            }
            stationaryFixes++
            lastStationaryFixMs = now
            publishStationaryCountdown()
            resumeMovementFirst = null
            return
        }
        if (stationarySince == 0L) return
        if (speedKmh < 6f || fix.accuracy > 25f ||
            (Build.VERSION.SDK_INT >= 26 && fix.hasSpeedAccuracy() && fix.speedAccuracyMetersPerSecond > 2.5f)) return
        val anchor = stationaryAnchor ?: Location(fix).also { stationaryAnchor = it }
        val first = resumeMovementFirst
        if (first == null || elapsedBetweenMs(first, fix) !in 700L..20000L) {
            resumeMovementFirst = Location(fix)
            return
        }
        // Two moving fixes and a significant net departure from the stop position.
        // Jitter that happens around a parked vehicle does not reset the countdown.
        val departed = anchor.distanceTo(fix) >= 30f
        val progressed = first.distanceTo(fix) >= 12f
        val dt = elapsedBetweenMs(first, fix) / 1000f
        val maxStep = max(25f, max(first.speed, if(fix.hasSpeed()) fix.speed else 0f) * dt * 1.8f + 15f)
        if (departed && progressed && first.distanceTo(fix) <= maxStep) {
            resetStationaryState()
            diagnostic("stop_countdown_cancelled_confirmed_driving")
        }
    }

    private fun finishNativeTrip(now: Long, reason: String) {
        val id = tripId ?: return
        db.endTrip(id, now)
        closeSpeedingSessions(now)
        notifyTripCompleted(id)
        tripId = null
        previousEvent = null
        previousPreviousEvent = null
        lastAlert.clear()
        movementWindow.clear()
        consecutivePretripStillFixes = 0
        resetStationaryState()
        diagnostic(reason)
        switchSamplingIfNeeded()
    }

    private var previousCandidate: Location? = null
    private var lastFixSeenMs = 0L
    private var latestSpeedKmh = 0f
    private fun diagnostic(reason: String) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("gps_state", reason).putLong("gps_state_at", System.currentTimeMillis()).apply()
    }
    private var lastRejectedReason = "none"
    private var previousEvent: Location? = null
    private var previousPreviousEvent: Location? = null
    private var lastCornerDiagnosticAtMs = 0L
    private var lastSavedMs = 0L
    private val lastAlert = mutableMapOf<String, Long>()
    private var speedingStartedMs: Long? = null
    private var aggressiveStartedMs: Long? = null
    private var speedingPeakKmh = 0.0
    private var aggressivePeakKmh = 0.0
    private var speedingTripId: Long? = null
    private fun closeSpeedingSessions(now: Long, capturedAt: Long = now) {
        val id = speedingTripId
        val version = lastPolicy.optString("policy_version", "offline")
        if (id != null) {
            speedingStartedMs?.let { db.saveEvent(id, "speeding_session", ((now-it).coerceAtLeast(0L)/1000.0), capturedAt, version) }
            aggressiveStartedMs?.let { db.saveEvent(id, "excessive_speeding_session", ((now-it).coerceAtLeast(0L)/1000.0), capturedAt, version) }
        }
        speedingStartedMs = null
        aggressiveStartedMs = null
        speedingTripId = null
        speedingPeakKmh = 0.0
        aggressivePeakKmh = 0.0
    }
    private var lastPolicy: JSONObject = JSONObject()
    private val geofenceState = mutableMapOf<String, Boolean>()
    private var activeInterval = false
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        db = NativeStore(this)
        manager = getSystemService(LOCATION_SERVICE) as LocationManager
        fusedClient = LocationServices.getFusedLocationProviderClient(this)
        notifications = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            notifications.createNotificationChannel(NotificationChannel(CHANNEL, "Nuqati GPS recording", NotificationManager.IMPORTANCE_LOW))
            notifications.createNotificationChannel(NotificationChannel(ALERT_CHANNEL, "Nuqati safety alerts", NotificationManager.IMPORTANCE_HIGH))
        }
        trace("service_created_" + permissionsSummary())
        lastPolicy = loadPolicy()
        tripId = db.activeTrip()
        if(tripId!=null){
            val owner=getSharedPreferences(PREFS, MODE_PRIVATE)
            if(!db.isOwnedBy(tripId!!,owner.getInt("owner_driver",0),owner.getInt("owner_company",0))){
                trace("previous_account_trip_quarantined")
                tripId=null
            }
        }
        // Only prune disposable diagnostics; never touch trips, fixes or events.
        pruneDiagnosticsIfDue()
        prefs.edit().putBoolean("last_acceleration_valid", false)
            .putFloat("last_acceleration_ms2", 0f).apply()
        // Restore countdown after Android recreates the foreground service.
        stationarySince = if (tripId != null) getSharedPreferences(PREFS, MODE_PRIVATE).getLong("stationary_since_ms", 0L) else 0L
        if (stationarySince > 0L) {
            stationaryFixes = getSharedPreferences(PREFS, MODE_PRIVATE).getInt("stationary_fix_count", 0)
            lastStationaryFixMs = getSharedPreferences(PREFS, MODE_PRIVATE).getLong("last_stationary_fix_ms", 0L)
        }
        val screenFilter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
        }
        registerReceiver(screenReceiver, screenFilter)
        screenReceiverRegistered = true
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        trace("service_command=" + (intent?.action ?: "null_restart") + "_flags=" + flags)
        when (intent?.action) {
            ACTION_PRIVACY, ACTION_STOP -> {
                // Privacy must not terminate a trip. STOP remains an explicit lifecycle action.
                if (intent.action == ACTION_PRIVACY && (tripId != null || db.activeTrip() != null)) {
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putBoolean("privacy", false).apply()
                    trace("privacy_blocked_active_trip")
                    return START_STICKY
                }
                stopLocation()
                if (intent.action == ACTION_PRIVACY) { tripId = null; resetStationaryState() }
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                if (getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean("privacy", false)) {
                    stopSelf(); return START_NOT_STICKY
                }
                startForeground(2340, notification("Nuqati is recording GPS locally"))
                startLocation()
                return START_STICKY
            }
        }
    }
    private fun pruneDiagnosticsIfDue() {
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        val now = System.currentTimeMillis()
        if (now - prefs.getLong("last_diagnostics_prune_ms", 0L) < 6L * 3600_000L) return
        try {
            db.pruneDiagnostics(now - 30L * 24L * 3600_000L)
            prefs.edit().putLong("last_diagnostics_prune_ms", now).apply()
        } catch (e: Exception) { diagnostic("diagnostics_prune_failed=" + e.javaClass.simpleName) }
    }
    private fun notification(message: String): Notification = Notification.Builder(this, CHANNEL)
        .setContentTitle("Nuqati Driver")
        .setContentText(message)
        .setSmallIcon(android.R.drawable.ic_menu_mylocation)
        .setOngoing(true).build()

    private fun startLocation() {
        if (tracking) return
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            diagnostic("fine_location_permission_missing"); return
        }
        val power = getSystemService(POWER_SERVICE) as PowerManager
        if (wakeLock?.isHeld != true) {
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Nuqati:NativeGPS")
            wakeLock?.setReferenceCounted(false)
            // Keep the CPU available for callbacks throughout an active tracking session.
            // Released explicitly on stop/privacy/service destruction.
            wakeLock?.acquire()
        }
        // The old GPS_PROVIDER-only subscription registered successfully indoors
        // but delivered zero callbacks. Use Google's fused provider as the primary
        // continuous source; retain the platform GPS provider as a fallback.
        // Continuous navigation-grade location request. Disable batching explicitly:
        // a successful registration alone does not mean callbacks are being delivered.
        // Two-second GPS sampling for both trip discovery and active trips.
        val requestedIntervalMs = GPS_SAMPLE_INTERVAL_MS
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, requestedIntervalMs)
            .setMinUpdateIntervalMillis(GPS_SAMPLE_INTERVAL_MS)
            .setMinUpdateDistanceMeters(0f)
            .setMaxUpdateDelayMillis(0L)
            .setWaitForAccurateLocation(false)
            .build()
        trace("fused_request_config_priority=high_interval_ms=2000_min_ms=2000_max_delay_ms=0_distance_m=0_wait_accurate=false")
        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                if (result.locations.isEmpty()) {
                    trace("fused_callback_empty_" + permissionsSummary())
                    return
                }
                // Persist source/callback delivery even when every fix is rejected later.
                val newest = result.locations.last()
                val ageMs = System.currentTimeMillis() - newest.time
                val accuracyM = if (newest.hasAccuracy()) newest.accuracy else -1f
                val previous = lastCallbackElapsedMs
                val gapMs = if (previous > 0L) SystemClock.elapsedRealtime() - previous else -1L
                if (previous == 0L || gapMs >= 20000L || !((getSystemService(POWER_SERVICE) as PowerManager).isInteractive)) {
                    // Throttle normal screen-off logs to one entry per 30 seconds.
                    val nowElapsed = SystemClock.elapsedRealtime()
                    if (previous == 0L || gapMs >= 20000L || nowElapsed - lastFusedDeliveryLogElapsedMs >= 30000L) {
                        lastFusedDeliveryLogElapsedMs = nowElapsed
                        trace("fused_callback_received_count=" + result.locations.size +
                            "_gap_ms=" + gapMs + "_fix_age_ms=" + ageMs +
                            "_accuracy_m=" + accuracyM + "_" + permissionsSummary())
                    }
                }
                for (fix in result.locations) onLocationChanged(fix)
            }
            override fun onLocationAvailability(availability: com.google.android.gms.location.LocationAvailability) {
                val available = availability.isLocationAvailable
                if (lastFusedAvailability != available) {
                    lastFusedAvailability = available
                    trace("fused_location_availability=" + available + "_" + permissionsSummary())
                }
            }
        }
        fusedCallback = callback
        tracking = true
        locationStartedMs = System.currentTimeMillis()
        lastWatchdogTickElapsedMs = SystemClock.elapsedRealtime()
        trace("location_start_" + permissionsSummary())
        scheduleLocationWatchdog()
        providerMode = "fused_pending"
        diagnostic("fused_listener_registering")
        try {
            fusedClient.requestLocationUpdates(request, callback, Looper.getMainLooper())
                .addOnSuccessListener {
                    if (tracking && fusedCallback === callback) {
                        providerMode = "fused"
                        trace("fused_listener_registered_request_accepted_" + permissionsSummary())
                    }
                }
                .addOnFailureListener { error ->
                    if (tracking && fusedCallback === callback) {
                        fusedClient.removeLocationUpdates(callback)
                        fusedCallback = null
                        tracking = false
                        trace("fused_failed:" + error.javaClass.simpleName + "_" + (error.message ?: "unknown"))
                        startGpsFallback()
                    }
                }
        } catch (e: Exception) {
            fusedCallback = null
            tracking = false
            trace("fused_exception:" + (e.message ?: e.javaClass.simpleName))
            startGpsFallback()
        }
        activeInterval = tripId != null
    }
    private fun scheduleLocationWatchdog() {
        watchdog?.let { locationHandler.removeCallbacks(it) }
        val task = object : Runnable {
            override fun run() {
                if (!tracking && !gpsFallbackActive) return
                val elapsed = SystemClock.elapsedRealtime()
                val now = System.currentTimeMillis()
                val tickDelay = elapsed - lastWatchdogTickElapsedMs
                lastWatchdogTickElapsedMs = elapsed
                watchdogChecks++
                val callbackAge = if (lastCallbackElapsedMs > 0L)
                    elapsed - lastCallbackElapsedMs else now - locationStartedMs
                // This event distinguishes CPU/service suspension from GPS provider silence.
                if (tickDelay > 45000L) trace("watchdog_tick_delayed_ms=" + tickDelay, tickDelay)
                if (watchdogChecks % 4L == 0L) {
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                        .putLong("gps_watchdog_last_tick_ms", now)
                        .putLong("gps_watchdog_callback_age_ms", callbackAge)
                        .putLong("gps_watchdog_checks", watchdogChecks)
                        .apply()
                    trace("watchdog_alive_age_ms=" + callbackAge + "_" + permissionsSummary())
                }
                // If the phone loses GPS indoors AFTER several confirmed stationary
                // fixes, finish after four minutes of confirmed stopping. GPS loss while
                // driving is never interpreted as a completed trip.
                if (tripId != null && stationarySince > 0L && stationaryFixes >= 3 &&
                    now - stationarySince >= TRIP_END_DELAY_MS &&
                    now - lastStationaryFixMs >= 60000L && callbackAge >= 60000L) {
                    trace("trip_end_confirmed_stationary_then_gps_gap")
                    finishNativeTrip(now, "native_trip_ended_stationary_gps_gap")
                    return
                }
                if (callbackAge >= 25000L) {
                    if (!gpsGapOpen) {
                        gpsGapOpen = true
                        lastGapReportedAtMs = now
                        trace("gps_gap_started_age_ms=" + callbackAge + "_" + permissionsSummary(), callbackAge)
                    }
                    if (!gpsFallbackActive) {
                        trace("fused_silent_starting_gps_fallback_age_ms=" + callbackAge)
                        startGpsFallback()
                    } else if (callbackAge >= 45000L && now - lastRecoveryAtMs >= 60000L) {
                        lastRecoveryAtMs = now
                        trace("gps_listener_recovery_age_ms=" + callbackAge + "_" + permissionsSummary(), callbackAge)
                        stopLocation()
                        startLocation()
                        return
                    }
                }
                locationHandler.postDelayed(this, 15000L)
            }
        }
        watchdog = task
        locationHandler.postDelayed(task, 15000L)
    }
    private fun startGpsFallback() {
        if (gpsFallbackActive) return
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            diagnostic("gps_fallback_permission_missing"); return
        }
        if (!manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
            diagnostic("gps_fallback_provider_disabled"); return
        }
        try {
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER,
                GPS_SAMPLE_INTERVAL_MS, 0f, this, Looper.getMainLooper())
            gpsFallbackActive = true
            tracking = true
            providerMode = if (fusedCallback != null) "fused_plus_gps" else "gps_fallback"
            diagnostic("gps_fallback_registered")
        } catch (e: Exception) {
            diagnostic("gps_fallback_failed:" + (e.message ?: e.javaClass.simpleName))
        }
    }
    private fun stopLocation() {
        watchdog?.let { locationHandler.removeCallbacks(it) }
        watchdog = null
        fusedCallback?.let { fusedClient.removeLocationUpdates(it) }
        fusedCallback = null
        try { manager.removeUpdates(this) } catch (_: Exception) { }
        gpsFallbackActive = false
        tracking = false
        providerMode = "none"
        if (wakeLock?.isHeld == true) wakeLock?.release()
        wakeLock = null
    }
    private fun switchSamplingIfNeeded() {
        val shouldActive = tripId != null
        activeInterval = shouldActive
        // The two-second interval is identical before and during a trip. Keep the
        // fused listener alive during trip transitions to avoid dropping callbacks.
    }
    override fun onLocationChanged(location: Location) {
        val now = System.currentTimeMillis()
        lastFixSeenMs = now
        lastCallbackElapsedMs = SystemClock.elapsedRealtime()
        lastCallbackWallMs = now
        if (gpsGapOpen) {
            db.saveGap("gap_ended", now, now - lastGapReportedAtMs, providerMode)
            gpsGapOpen = false
            trace("gps_gap_ended_callback_provider=" + (location.provider ?: "unknown"), now - lastGapReportedAtMs)
        }
        callbackCount++
        // Retain up to 100k raw fixes and 5k gap diagnostics during long-running services.
        if (callbackCount % 9000L == 0L) pruneDiagnosticsIfDue()
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
            .putLong("last_gps_callback_ms", now)
            .putLong("gps_callback_count", callbackCount)
            .putString("gps_provider_mode", providerMode)
            .putString("last_callback_provider", location.provider ?: "unknown")
            .putFloat("last_callback_accuracy_m", if (location.hasAccuracy()) location.accuracy else -1f)
            .apply()
        // Refresh only when a different policy version/content was committed by Flutter.
        val cached = loadPolicy()
        if (cached.toString() != lastPolicy.toString()) lastPolicy = cached
        val ageMs = (SystemClock.elapsedRealtimeNanos() - location.elapsedRealtimeNanos) / 1_000_000L
        if (!location.hasAccuracy() || location.accuracy <= 0 || location.accuracy > 50f ||
            ageMs !in 0L..15000L) {
            lastRejectedReason = "invalid_accuracy_or_age"
            diagnostic(lastRejectedReason)
            return
        }
        // Fused and fallback GPS can deliver the same fix or interleave out of order.
        // Wall-clock timestamps cannot safely be used to compare these two providers.
        if (location.elapsedRealtimeNanos <= lastOrderedFixNanos) {
            lastRejectedReason = "duplicate_or_out_of_order_fix"
            diagnostic(lastRejectedReason)
            return
        }
        val prior = previousCandidate
        val dt = if (prior == null) 0L else elapsedBetweenMs(prior, location)
        val displacement = if (prior != null && dt in 1000L..12000L) prior.distanceTo(location) else 0f
        val reportedKmh = if (location.hasSpeed()) location.speed.coerceAtLeast(0f) * 3.6f else 0f
        val priorSpeedMs = if (prior?.hasSpeed() == true) prior.speed else 0f
        if (prior != null && dt in 1000L..12000L && prior.accuracy <= 30f && location.accuracy <= 30f) {
            val maxPlausible = max(35f, max(priorSpeedMs, if (location.hasSpeed()) location.speed else 0f) * dt / 1000f * 1.8f + 25f)
            if (displacement > maxPlausible) {
                lastRejectedReason = "gps_position_jump_rejected"
                diagnostic(lastRejectedReason)
                // Keep the earlier anchor so one jump cannot become the next baseline.
                return
            }
        }
        val derivedKmh = if (prior != null && dt in 1000L..12000L &&
            prior.accuracy <= 12f && location.accuracy <= 12f && displacement >= 5f &&
            displacement <= 45f * dt / 1000f) displacement * 3600f / dt.toFloat() else 0f
        val speedKmh = if (location.hasSpeed() && reportedKmh >= 3f) reportedKmh
            else if (derivedKmh >= 8f) derivedKmh else reportedKmh
        if (speedKmh > 180f) { lastRejectedReason = "implausible_speed"; diagnostic(lastRejectedReason); return }
        lastOrderedFixNanos = location.elapsedRealtimeNanos
        latestSpeedKmh = speedKmh
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putFloat("last_speed_kmh", speedKmh).putFloat("last_accuracy_m", location.accuracy).putLong("last_accepted_fix_ms", now).apply()
        // The start gate needs previousCandidate from the preceding fix.
        if (tripId == null) {
            val confirmed = confirmsTripStart(location, reportedKmh, derivedKmh)
            if (confirmed) {
                val owner = getSharedPreferences(PREFS, MODE_PRIVATE)
                val driver = owner.getInt("owner_driver", 0)
                val company = owner.getInt("owner_company", 0)
                val vehicle = owner.getInt("owner_vehicle", 0)
                if (driver <= 0 || company <= 0 || vehicle <= 0) {
                    trace("trip_start_blocked_unverified_owner")
                } else {
                    // Preserve the first seconds of verified travel in the trip
                    // instead of discarding them during motion confirmation.
                    val confirmedFixes = movementWindow.toList()
                    val firstFix = confirmedFixes.first()
                    val startedAt = now - elapsedBetweenMs(firstFix, location)
                    val newId = db.startTrip(startedAt, driver, company, vehicle)
                    for (initial in confirmedFixes.dropLast(1)) db.saveFix(newId, initial)
                    tripId = newId
                    movementWindow.clear()
                    consecutivePretripStillFixes = 0
                    resetStationaryState()
                    previousEvent = null
                    previousPreviousEvent = null
                    lastAlert.clear()
                    diagnostic("native_trip_started")
                    trace("trip_start_confirmed_route")
                    switchSamplingIfNeeded()
                }
            }
        }
        previousCandidate = Location(location)
        // Persist valid pre-trip points for diagnostics; only the active-trip fixes
        // are transferred into the existing Flutter/backend trip and event queues.
        db.saveRawFix(location, now)
        val id = tripId ?: return
        updateStationaryState(location, speedKmh, now)
        // Require multiple stationary fixes and a recent stationary reading. An
        // isolated high-speed spike neither resets nor restarts this countdown.
        if (stationarySince > 0L && now - stationarySince >= TRIP_END_DELAY_MS &&
            stationaryFixes >= 3 && now - lastStationaryFixMs <= 90000L) {
            finishNativeTrip(now, "native_trip_ended_confirmed_stationary")
            return
        }
        val accelerationMs2 = validatedAcceleration(location, previousEvent)
        // Publish the same quality-gated value used for local events and backend GPS.
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
            .putFloat("last_acceleration_ms2", (accelerationMs2 ?: 0.0).toFloat())
            .putBoolean("last_acceleration_valid", accelerationMs2 != null)
            .putLong("last_acceleration_at_ms", now).apply()
        if (now - lastSavedMs >= 800) {
            db.saveFix(id, location, accelerationMs2)
            lastSavedMs = now
        }
        evaluateGeofence(location, now)
        evaluateSafety(id, location, now, accelerationMs2)
    }
    private fun insideGeofence(zone: JSONObject, latitude: Double, longitude: Double): Boolean {
        if (zone.optString("shape", "circle") == "circle") {
            val lat = zone.optDouble("latitude", Double.NaN)
            val lon = zone.optDouble("longitude", Double.NaN)
            val radius = zone.optDouble("radius_m", 0.0)
            if (!lat.isFinite() || !lon.isFinite() || radius <= 0.0) return false
            val distance = FloatArray(1)
            Location.distanceBetween(latitude, longitude, lat, lon, distance)
            return distance[0].toDouble() <= radius
        }
        val points=zone.optJSONArray("polygon_points") ?: return false
        if (points.length()<3) return false
        var inside=false
        var j=points.length()-1
        for (i in 0 until points.length()) {
            val a=points.optJSONArray(i) ?: continue
            val b=points.optJSONArray(j) ?: continue
            val y1=a.optDouble(0);val x1=a.optDouble(1)
            val y2=b.optDouble(0);val x2=b.optDouble(1)
            if ((y1>latitude)!=(y2>latitude) && longitude < x1+(latitude-y1)*(x2-x1)/(y2-y1)) inside=!inside
            j=i
        }
        return inside
    }
    private fun evaluateGeofence(fix: Location, now: Long) {
        if (fix.accuracy <= 0f || fix.accuracy > 20f) return
        val zones = lastPolicy.optJSONArray("geofence_speed_zones") ?: return
        for (i in 0 until zones.length()) {
            val zone = zones.optJSONObject(i) ?: continue
            val id = zone.optString("id")
            if (id.isEmpty()) continue
            // Evaluate the true shape; polygons must never be treated as circles.
            val previous = geofenceState[id]
            val inside = insideGeofence(zone,fix.latitude,fix.longitude)
            if (previous != null && previous != inside) {
                val name = zone.optString("name", "Geofence").take(60)
                val language = getSharedPreferences(PREFS, MODE_PRIVATE).getString("language", "en")
                val message = if (language == "ur") (if (inside) "علاقے میں داخلہ: " else "علاقے سے خروج: ") + name
                  else if (language == "ar")
                    (if (inside) "دخول منطقة: " else "خروج من منطقة: ") + name
                  else (if (inside) "Entered: " else "Exited: ") + name
                if (getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean("alerts_enabled", true) &&
                    (Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)) {
                    try {
                        notifications.notify((id.hashCode() and 0x3fffffff) + (if (inside) 1 else 2),
                            Notification.Builder(this, ALERT_CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_map)
                                .setContentTitle(if (language == "ar") "نقاطي - المنطقة الجغرافية" else if (language == "ur") "نقاطی - جغرافیائی علاقہ" else "Nuqati geofence").setContentText(message).setAutoCancel(true).build())
                    } catch (e: Exception) { diagnostic("geofence_notification_failed=" + e.javaClass.simpleName) }
                }
                trace("geofence_" + (if (inside) "entry" else "exit") + "_zone=" + id)
            }
            geofenceState[id] = inside
        }
    }
    private fun threshold(name: String, default: Double): Double = lastPolicy.optDouble(name, default).takeIf { it.isFinite() && it > 0 } ?: default
    private fun enabled(name: String): Boolean = lastPolicy.optJSONObject("enabled")?.optBoolean(name, true) ?: true

    /** GPS speed delta is only trusted when BOTH consecutive measurements are accurate.
     *  A null measurement means unavailable, not a recorded acceleration of zero.
     */
    private fun validatedAcceleration(fix: Location, prev: Location?): Double? {
        if (prev == null || !fix.hasSpeed() || !prev.hasSpeed() ||
            fix.accuracy > 15f || prev.accuracy > 15f ||
            (Build.VERSION.SDK_INT >= 26 &&
                ((fix.hasSpeedAccuracy() && fix.speedAccuracyMetersPerSecond > 2.5f) ||
                 (prev.hasSpeedAccuracy() && prev.speedAccuracyMetersPerSecond > 2.5f)))) return null
        val elapsedMs = elapsedBetweenMs(prev, fix)
        if (elapsedMs !in 700L..12000L) return null
        val result = (fix.speed - prev.speed).toDouble() / (elapsedMs / 1000.0)
        return result.takeIf { it.isFinite() && abs(it) <= 12.0 }
    }

    /** Course-from-position fallback only for three accurate points with real movement;
     *  this is NOT a stationary-jitter or a single-GPS-spike corner detector.
     */
    private fun routeCornerAngle(before: Location?, prev: Location, fix: Location): Pair<Double, Double>? {
        if (before == null || before.accuracy > 10f || prev.accuracy > 10f || fix.accuracy > 10f) return null
        val dt1 = elapsedBetweenMs(before, prev)
        val dt2 = elapsedBetweenMs(prev, fix)
        if (dt1 !in 700L..8000L || dt2 !in 700L..8000L) return null
        val firstMetres = before.distanceTo(prev)
        val secondMetres = prev.distanceTo(fix)
        val positionalUncertainty = max(before.accuracy, max(prev.accuracy, fix.accuracy))
        if (firstMetres < max(6f, positionalUncertainty * 2f) ||
            secondMetres < max(6f, positionalUncertainty * 2f)) return null
        val speed1 = max(if (before.hasSpeed()) before.speed else 0f, prev.speed)
        val speed2 = max(prev.speed, fix.speed)
        if (firstMetres > max(16f, speed1 * dt1 / 1000f * 1.8f + 10f) ||
            secondMetres > max(16f, speed2 * dt2 / 1000f * 1.8f + 10f)) return null
        val oldHeading = before.bearingTo(prev).toDouble()
        val newHeading = prev.bearingTo(fix).toDouble()
        val angle = abs((newHeading - oldHeading + 540.0) % 360.0 - 180.0)
        return Pair(angle, (dt1 + dt2) / 2000.0)
    }

    private fun evaluateSafety(id: Long, fix: Location, now: Long, accelerationMs2: Double?) {
        // Local event detection and the GPS queue share the same acceleration input.
        if (fix.accuracy > 15f || !fix.hasSpeed() ||
            (Build.VERSION.SDK_INT >= 26 && fix.hasSpeedAccuracy() && fix.speedAccuracyMetersPerSecond > 2.5f)) return
        val prev = previousEvent
        val before = previousPreviousEvent
        previousPreviousEvent = prev?.let { Location(it) }
        previousEvent = Location(fix)
        if (prev == null || elapsedBetweenMs(prev, fix) !in 700L..12000L || !prev.hasSpeed()) return
        val dt = elapsedBetweenMs(prev, fix) / 1000.0
        val speed = fix.speed * 3.6
        val speedLimit = threshold("speeding_kmh", 100.0)
        val brakeLimit = threshold("harsh_brake_ms2", 3.0)
        val accelLimit = threshold("harsh_accel_ms2", 3.0)
        val severeBrake = threshold("aggressive_brake_ms2", brakeLimit * 1.5)
        val severeAccel = threshold("aggressive_accel_ms2", accelLimit * 1.5)
        val speedMargin = threshold("excessive_speed_margin_kmh", 20.0)
        val phase4 = lastPolicy.optJSONObject("phase4")
        val cornerLimit = (phase4?.optDouble("cornering_ms2", 3.5) ?: 3.5).takeIf { it.isFinite() && it > 0 } ?: 3.5
        val minimumCorneringKmh = (phase4?.optDouble("min_cornering_speed_kmh", 20.0) ?: 20.0).takeIf { it.isFinite() && it > 0 } ?: 20.0
        val policyVersion = lastPolicy.optString("policy_version", "offline")
        // Speeding is a continuous session, not an alert every GPS fix. Do not
        // create both normal and excessive penalties on the very first fix.
        if (speedingTripId != null && speedingTripId != id) closeSpeedingSessions(now, prev.time)
        if (enabled("speeding") && speed > speedLimit) {
            val isNewEpisode = speedingStartedMs == null
            val severeNow = enabled("excessive_speeding") && speed > speedLimit + speedMargin
            if (isNewEpisode) {
                speedingStartedMs = now
                speedingTripId = id
                val kind = if (severeNow) "excessive_speeding" else "speeding"
                db.saveEvent(id, kind, speed, fix.time, policyVersion)
                notifySafety(kind)
            }
            speedingPeakKmh = maxOf(speedingPeakKmh, speed)
            if (severeNow) {
                if (aggressiveStartedMs == null) {
                    aggressiveStartedMs = now
                    // Escalation from an earlier ordinary-speeding incident remains
                    // distinct, but never duplicate an initially excessive incident.
                    if (!isNewEpisode) {
                        db.saveEvent(id, "excessive_speeding", speed, fix.time, policyVersion)
                        notifySafety("excessive_speeding")
                    }
                }
                aggressivePeakKmh = maxOf(aggressivePeakKmh, speed)
            } else if (aggressiveStartedMs != null && speed < speedLimit + speedMargin - 3.0) {
                db.saveEvent(id, "excessive_speeding_session", (now-aggressiveStartedMs!!).coerceAtLeast(0L)/1000.0, fix.time, policyVersion)
                aggressiveStartedMs = null
                aggressivePeakKmh = 0.0
            }
        } else if (speedingStartedMs != null && speed < speedLimit - 3.0) {
            closeSpeedingSessions(now, fix.time)
        }
        if (enabled("harsh_braking") && accelerationMs2 != null && accelerationMs2 <= -brakeLimit) {
            event(id, if (enabled("excessive_harsh_braking") && accelerationMs2 <= -severeBrake) "excessive_harsh_braking" else "harsh_braking", -accelerationMs2, now, fix.time)
        }
        if (enabled("harsh_acceleration") && accelerationMs2 != null && accelerationMs2 >= accelLimit) {
            event(id, if (enabled("excessive_harsh_acceleration") && accelerationMs2 >= severeAccel) "excessive_harsh_acceleration" else "harsh_acceleration", accelerationMs2, now, fix.time)
        }
        val verifiedCornerMotion = prev.speed * 3.6 >= minimumCorneringKmh * 0.7 &&
            prev.distanceTo(fix) >= 5f &&
            prev.distanceTo(fix) <= max(20f, max(prev.speed, fix.speed) * dt.toFloat() * 1.8f + 10f)
        if (enabled("harsh_cornering") && speed >= minimumCorneringKmh && verifiedCornerMotion) {
            val bearingAngle = if (fix.hasBearing() && prev.hasBearing() &&
                (Build.VERSION.SDK_INT < 26 ||
                    ((!fix.hasBearingAccuracy() || fix.bearingAccuracyDegrees <= 20f) &&
                     (!prev.hasBearingAccuracy() || prev.bearingAccuracyDegrees <= 20f))))
                abs((fix.bearing - prev.bearing + 540f) % 360f - 180f).toDouble() else null
            val route = routeCornerAngle(before, prev, fix)
            val bearingLateral = if (bearingAngle != null) fix.speed * Math.toRadians(bearingAngle) / dt else 0.0
            val routeLateral = if (route != null) fix.speed * Math.toRadians(route.first) / route.second else 0.0
            val bearingQualified = bearingAngle != null && bearingAngle / dt >= 18.0 && bearingLateral >= cornerLimit
            val routeQualified = route != null && route.first / route.second >= 18.0 && routeLateral >= cornerLimit
            if (bearingQualified || routeQualified) {
                event(id, "harsh_cornering", if (bearingQualified) bearingLateral else routeLateral, now, fix.time)
                diagnostic("cornering_qualified_source=" + (if (bearingQualified) "gps_bearing" else "verified_route"))
            } else if (now - lastCornerDiagnosticAtMs >= 30000L) {
                lastCornerDiagnosticAtMs = now
                diagnostic("cornering_waiting_bearing=" + (bearingAngle != null) +
                    "_route=" + (route != null) + "_min_speed_met=true")
            }
        }
    }
    private fun event(id: Long, kind: String, value: Double, now: Long, capturedAt: Long) {
        val group = kind.removePrefix("excessive_")
        // Severity variants of one braking/acceleration episode share a cooldown.
        if (now - (lastAlert[group] ?: 0L) < 12000) return
        lastAlert[group] = now
        val policyVersion = lastPolicy.optString("policy_version", "offline")
        db.saveEvent(id, kind, value, capturedAt, policyVersion)
        notifySafety(kind)
    }
    private fun notifySafety(kind: String) {
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        if (!prefs.getBoolean("alerts_enabled", true)) {
            diagnostic("safety_notification_skipped_user_preference"); return
        }
        if ((Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) ||
            (Build.VERSION.SDK_INT >= 24 && !notifications.areNotificationsEnabled()) ||
            (Build.VERSION.SDK_INT >= 26 &&
                notifications.getNotificationChannel(ALERT_CHANNEL)?.importance == NotificationManager.IMPORTANCE_NONE)) {
            diagnostic("safety_notification_skipped_permission_or_channel"); return
        }
        val group = kind.removePrefix("excessive_")
        val language = getSharedPreferences(PREFS, MODE_PRIVATE).getString("language", "en")
        val label = if (kind == "excessive_speeding") when (language) {
            "ar" -> "تجاوز سرعة شديد، يرجى تخفيف السرعة فوراً"
            "ur" -> "انتہائی تیز رفتاری، فوراً رفتار کم کریں"
            else -> "Aggressive speeding. Reduce speed immediately."
        } else if (language == "ur") when (group) {
            "speeding" -> "رفتار زیادہ ہے، رفتار کم کریں"
            "harsh_braking" -> "اچانک بریک لگائی گئی"
            "harsh_acceleration" -> "تیز ایکسلریشن کا پتہ چلا"
            else -> "تیز موڑ کا پتہ چلا"
        } else if (language == "ar") when (group) {
            "speeding" -> "تجاوز السرعة، يرجى التخفيف"
            "harsh_braking" -> "تم رصد فرملة حادة"
            "harsh_acceleration" -> "تم رصد تسارع حاد"
            else -> "تم رصد انعطاف حاد"
        } else when (group) {
            "speeding" -> "Speeding detected. Slow down."
            "harsh_braking" -> "Harsh braking detected."
            "harsh_acceleration" -> "Harsh acceleration detected."
            else -> "Harsh cornering detected."
        }
        try {
            notifications.notify(2350 + group.hashCode().ushr(1) % 100, Notification.Builder(this, ALERT_CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle(if(language=="ar") "تنبيه سلامة نقاطي" else if(language=="ur") "نقاطی حفاظتی انتباہ" else "Nuqati safety alert")
                .setContentText(label)
                .setAutoCancel(true).build())
            diagnostic("safety_notification_posted_kind=" + kind)
        } catch (e: Exception) {
            // Never allow blocked notifications to stop local SQLite safety capture.
            diagnostic("safety_notification_failed=" + e.javaClass.simpleName)
        }
    }
    private fun notifyTripCompleted(id: Long) {
        // Runs in the native foreground service, including when Flutter is suspended.
        try {
            val openApp = packageManager.getLaunchIntentForPackage(packageName)
            val pending = openApp?.let {
                PendingIntent.getActivity(this, 2401, it,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            }
            val builder = Notification.Builder(this, ALERT_CHANNEL)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle(when (getSharedPreferences(PREFS, MODE_PRIVATE).getString("language", "en")) { "ar" -> "نقاطي - انتهت الرحلة"; "ur" -> "نقاطی - سفر مکمل"; else -> "Nuqati - Trip completed" })
                .setContentText(when (getSharedPreferences(PREFS, MODE_PRIVATE).getString("language", "en")) { "ar" -> "انتهت رحلتك. افتح نقاطي لمراجعة تقييم القيادة."; "ur" -> "آپ کا سفر مکمل ہو گیا۔ ڈرائیونگ اسکور دیکھنے کے لیے نقاطی کھولیں۔"; else -> "Your trip has ended. Open Nuqati to review your driving score." })
                .setAutoCancel(true)
            if (pending != null) builder.setContentIntent(pending)
            notifications.notify(2401, builder.build())
            diagnostic("trip_completed_notification_sent=" + id)
        } catch (e: Exception) { diagnostic("trip_completed_notification_failed=" + e.javaClass.simpleName) }
    }

    private fun loadPolicy(): JSONObject = try {
        JSONObject(getSharedPreferences(PREFS, MODE_PRIVATE).getString("policy", "{}") ?: "{}")
    } catch (_: Exception) { JSONObject() }
    override fun onDestroy() {
        trace("service_destroyed_" + permissionsSummary())
        stopLocation()
        if (screenReceiverRegistered) {
            try { unregisterReceiver(screenReceiver) } catch (_: Exception) { }
            screenReceiverRegistered = false
        }
        db.close()
        super.onDestroy()
    }
}

internal class NativeStore(context: Context) : SQLiteOpenHelper(context, "nuqati_native_tracking.db", null, 5) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE trips(id INTEGER PRIMARY KEY, started_ms INTEGER NOT NULL, ended_ms INTEGER, distance_m REAL NOT NULL DEFAULT 0, driver_id INTEGER, company_id INTEGER, vehicle_id INTEGER)")
        db.execSQL("CREATE TABLE fixes(id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, at_ms INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL NOT NULL, speed_ms REAL NOT NULL, acceleration_ms2 REAL NOT NULL DEFAULT 0, acceleration_valid INTEGER NOT NULL DEFAULT 0, gps_age_seconds REAL)")
        db.execSQL("CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, at_ms INTEGER NOT NULL, kind TEXT NOT NULL, value REAL NOT NULL, policy_version TEXT NOT NULL)")
        db.execSQL("CREATE INDEX idx_fixes_trip ON fixes(trip_id,at_ms)")
        db.execSQL("CREATE INDEX idx_events_trip ON events(trip_id,at_ms)")
        createDiagnosticsTables(db)
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if(oldVersion<2)db.execSQL("ALTER TABLE trips ADD COLUMN distance_m REAL NOT NULL DEFAULT 0")
        if(oldVersion<3)createDiagnosticsTables(db)
        if(oldVersion<4){
            db.execSQL("ALTER TABLE trips ADD COLUMN driver_id INTEGER")
            db.execSQL("ALTER TABLE trips ADD COLUMN company_id INTEGER")
            db.execSQL("ALTER TABLE trips ADD COLUMN vehicle_id INTEGER")
        }
        if (oldVersion < 5) {
            // Non-destructive upgrade: old rows remain valid with unknown acceleration.
            db.execSQL("ALTER TABLE fixes ADD COLUMN acceleration_ms2 REAL NOT NULL DEFAULT 0")
            db.execSQL("ALTER TABLE fixes ADD COLUMN acceleration_valid INTEGER NOT NULL DEFAULT 0")
            // Null is intentional: historical v4 fixes have no trustworthy GPS age.
            db.execSQL("ALTER TABLE fixes ADD COLUMN gps_age_seconds REAL")
            db.execSQL("CREATE INDEX IF NOT EXISTS idx_gps_gaps_at ON gps_gaps(at_ms)")
        }
    }
    private fun createDiagnosticsTables(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS raw_fixes(id INTEGER PRIMARY KEY AUTOINCREMENT, at_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL NOT NULL, speed_ms REAL NOT NULL, provider TEXT NOT NULL)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_raw_fixes_at ON raw_fixes(at_ms)")
        db.execSQL("CREATE TABLE IF NOT EXISTS gps_gaps(id INTEGER PRIMARY KEY AUTOINCREMENT, at_ms INTEGER NOT NULL, event TEXT NOT NULL, duration_ms INTEGER NOT NULL, provider TEXT NOT NULL)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_gps_gaps_at ON gps_gaps(at_ms)")
    }
    fun pruneDiagnostics(olderThanMs: Long) {
        // Diagnostic-only retention. The upload-critical trips/fixes/events tables
        // and all their existing records are never altered here.
        val database = writableDatabase
        database.beginTransaction()
        try {
            database.delete("raw_fixes", "received_ms < ?", arrayOf(olderThanMs.toString()))
            database.delete("gps_gaps", "at_ms < ?", arrayOf(olderThanMs.toString()))
            database.execSQL("DELETE FROM raw_fixes WHERE id <= (SELECT id FROM raw_fixes ORDER BY id DESC LIMIT 1 OFFSET 99999)")
            database.execSQL("DELETE FROM gps_gaps WHERE id <= (SELECT id FROM gps_gaps ORDER BY id DESC LIMIT 1 OFFSET 4999)")
            database.setTransactionSuccessful()
        } finally { database.endTransaction() }
    }
    fun saveRawFix(loc: Location, receivedMs: Long) {
        val cv = android.content.ContentValues().apply {
            put("at_ms", loc.time); put("received_ms", receivedMs)
            put("lat", loc.latitude); put("lon", loc.longitude)
            put("accuracy", loc.accuracy); put("speed_ms", if(loc.hasSpeed())loc.speed else 0f)
            put("provider", loc.provider ?: "unknown")
        }
        writableDatabase.insertOrThrow("raw_fixes", null, cv)
    }
    fun saveGap(event: String, at: Long, duration: Long, provider: String) {
        val cv = android.content.ContentValues().apply {
            put("at_ms", at); put("event", event)
            put("duration_ms", duration.coerceAtLeast(0L)); put("provider", provider)
        }
        writableDatabase.insertOrThrow("gps_gaps", null, cv)
    }
    fun isOwnedBy(id: Long, driver: Int, company: Int): Boolean = readableDatabase.rawQuery(
        "SELECT 1 FROM trips WHERE id=? AND driver_id=? AND company_id=?",arrayOf(id.toString(),driver.toString(),company.toString())
    ).use { it.moveToFirst() }
    fun activeTrip(): Long? = readableDatabase.rawQuery("SELECT id FROM trips WHERE ended_ms IS NULL ORDER BY id DESC LIMIT 1", null).use { if (it.moveToFirst()) it.getLong(0) else null }
    fun startTrip(at: Long, driver: Int, company: Int, vehicle: Int): Long {
        require(driver>0 && company>0 && vehicle>0) { "Verified recording owner required" }
        val cv = android.content.ContentValues().apply {
            put("started_ms", at); put("driver_id",driver); put("company_id",company); put("vehicle_id",vehicle)
        }
        return writableDatabase.insertOrThrow("trips", null, cv)
    }
    fun endTrip(id: Long, at: Long) { writableDatabase.execSQL("UPDATE trips SET ended_ms=? WHERE id=? AND ended_ms IS NULL", arrayOf(at,id)) }
    fun saveFix(id: Long, loc: Location, accelerationMs2: Double? = null) { val cv = android.content.ContentValues().apply {
        put("trip_id", id); put("at_ms", loc.time); put("lat", loc.latitude); put("lon", loc.longitude)
        put("accuracy", loc.accuracy); put("speed_ms", if (loc.hasSpeed()) loc.speed else 0f)
        put("acceleration_ms2", accelerationMs2 ?: 0.0)
        put("acceleration_valid", if (accelerationMs2 != null) 1 else 0)
        put("gps_age_seconds", ((SystemClock.elapsedRealtimeNanos() - loc.elapsedRealtimeNanos) / 1_000_000_000.0).coerceAtLeast(0.0))
    }
        val database=writableDatabase
        database.beginTransaction()
        try {
            if(loc.accuracy<=35f) {
                database.rawQuery("SELECT lat,lon,at_ms,accuracy FROM fixes WHERE trip_id=? ORDER BY id DESC LIMIT 1",arrayOf(id.toString())).use { c ->
                    if(c.moveToFirst() && c.getDouble(3)<=35.0) {
                        val prior=Location("native").apply {latitude=c.getDouble(0);longitude=c.getDouble(1)}
                        val dt=loc.time-c.getLong(2)
                        val step=prior.distanceTo(loc)
                        if(dt in 500L..15000L && step<=((if(loc.hasSpeed())loc.speed else 0f)*dt/1000f+25f).coerceAtLeast(25f))
                            database.execSQL("UPDATE trips SET distance_m=distance_m+? WHERE id=?",arrayOf<Any>(step.toDouble(), id))
                    }
                }
            }
            database.insertOrThrow("fixes", null, cv)
            database.setTransactionSuccessful()
        } finally {database.endTransaction()}
    }
    fun saveEvent(id: Long, kind: String, value: Double, at: Long, version: String) { val cv = android.content.ContentValues().apply {
        put("trip_id", id); put("at_ms", at); put("kind", kind); put("value", value); put("policy_version", version)
    }; writableDatabase.insertOrThrow("events", null, cv) }
}
