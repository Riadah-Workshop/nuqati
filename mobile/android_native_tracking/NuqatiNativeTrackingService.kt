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
    private var movementSince = 0L
    private var stationarySince = 0L
    private fun publishStationaryCountdown() {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit()
            .putLong("stationary_since_ms", if (tripId != null) stationarySince else 0L).apply()
    }
    private var firstMovement: Location? = null
    private var previousCandidate: Location? = null
    private var lastFixSeenMs = 0L
    private var latestSpeedKmh = 0f
    private fun diagnostic(reason: String) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("gps_state", reason).putLong("gps_state_at", System.currentTimeMillis()).apply()
    }
    private var lastRejectedReason = "none"
    private var previousEvent: Location? = null
    private var lastSavedMs = 0L
    private val lastAlert = mutableMapOf<String, Long>()
    private var speedingStartedMs: Long? = null
    private var aggressiveStartedMs: Long? = null
    private var speedingPeakKmh = 0.0
    private var aggressivePeakKmh = 0.0
    private var speedingTripId: Long? = null
    private fun closeSpeedingSessions(now: Long) {
        val id = speedingTripId
        val version = lastPolicy.optString("policy_version", "offline")
        if (id != null) {
            speedingStartedMs?.let { db.saveEvent(id, "speeding_session", ((now-it).coerceAtLeast(0L)/1000.0), now, version) }
            aggressiveStartedMs?.let { db.saveEvent(id, "excessive_speeding_session", ((now-it).coerceAtLeast(0L)/1000.0), now, version) }
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
        // Restore countdown after Android recreates the foreground service.
        stationarySince = if (tripId != null) getSharedPreferences(PREFS, MODE_PRIVATE).getLong("stationary_since_ms", 0L) else 0L
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
                stopLocation()
                if (intent.action == ACTION_PRIVACY) { tripId?.let { closeSpeedingSessions(System.currentTimeMillis()); db.endTrip(it, System.currentTimeMillis()) }; tripId = null; stationarySince = 0L; publishStationaryCountdown() }
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
        // The 5-second target balances screen-off continuity and battery usage.
        val requestedIntervalMs = 5000L
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, requestedIntervalMs)
            .setMinUpdateIntervalMillis(1000L)
            .setMinUpdateDistanceMeters(0f)
            .setMaxUpdateDelayMillis(0L)
            .setWaitForAccurateLocation(false)
            .build()
        trace("fused_request_config_priority=high_interval_ms=5000_min_ms=1000_max_delay_ms=0_distance_m=0_wait_accurate=false")
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
                if (tripId == null) 3000L else 1000L, 0f, this, Looper.getMainLooper())
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
        if (shouldActive != activeInterval) { stopLocation(); startLocation() }
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
        if (!location.hasAccuracy() || location.accuracy <= 0 || location.accuracy > 50f ||
            now - location.time > 15000 || location.time - now > 5000) {
            lastRejectedReason = "invalid_accuracy_or_age"
            diagnostic(lastRejectedReason)
            return
        }
        val prior = previousCandidate
        val dt = if (prior == null) 0L else location.time - prior.time
        val displacement = if (prior != null && dt in 1000L..12000L) prior.distanceTo(location) else 0f
        // Displacement fallback only with consecutive accurate fixes; never infer speed from a single jump.
        val derivedKmh = if (prior != null && dt in 1000L..12000L &&
            prior.accuracy <= 20f && location.accuracy <= 20f && displacement >= 8f &&
            displacement <= 45f * dt / 1000f) displacement * 3600f / dt.toFloat() else 0f
        val gpsKmh = if (location.hasSpeed()) location.speed.coerceAtLeast(0f) * 3.6f else 0f
        val speedKmh = if (location.hasSpeed() && gpsKmh > 0f) gpsKmh else derivedKmh
        if (speedKmh > 180f) { lastRejectedReason = "implausible_speed"; diagnostic(lastRejectedReason); return }
        latestSpeedKmh = speedKmh
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putFloat("last_speed_kmh", speedKmh).putFloat("last_accuracy_m", location.accuracy).putLong("last_accepted_fix_ms", now).apply()
        previousCandidate = Location(location)
        // Persist every accepted location, including pre-trip fixes, independently
        // of Flutter and dashboard connectivity. Trip fixes remain unchanged.
        db.saveRawFix(location, now)
        val validMovement = location.accuracy <= 35f && speedKmh >= 5f &&
            (location.hasSpeed() || derivedKmh >= 5f)
        if (tripId == null) {
            if (validMovement) {
                if (movementSince == 0L) { movementSince = now; firstMovement = Location(location) }
                val travel = firstMovement?.distanceTo(location) ?: 0f
                if (now - movementSince >= 8000L && travel >= 20f) {
                    val owner=getSharedPreferences(PREFS, MODE_PRIVATE)
                    val driver=owner.getInt("owner_driver",0)
                    val company=owner.getInt("owner_company",0)
                    val vehicle=owner.getInt("owner_vehicle",0)
                    if(driver<=0||company<=0||vehicle<=0){trace("trip_start_blocked_unverified_owner");return}
                    tripId = db.startTrip(now,driver,company,vehicle)
                    movementSince = 0L
                    firstMovement = null
                    stationarySince = 0L
                    publishStationaryCountdown()
                    previousEvent = null
                    lastRejectedReason = "none"
                    diagnostic("native_trip_started")
                    switchSamplingIfNeeded()
                } else lastRejectedReason = "confirming_movement"
            } else {
                lastRejectedReason = "waiting_for_reliable_movement"
                // Brief weak fixes must not erase valid movement evidence.
                if (movementSince != 0L && now - movementSince > 20000L) {
                    movementSince = 0L; firstMovement = null
                }
            }
        }
        if (tripId == null) diagnostic(lastRejectedReason)
        val id = tripId ?: return
        if (location.accuracy <= 35f) {
            if (speedKmh < 3f) {
                if (stationarySince == 0L) { stationarySince = now; publishStationaryCountdown() }
                if (now - stationarySince >= 180000) {
                    db.endTrip(id, now)
                    closeSpeedingSessions(now)
                    notifyTripCompleted(id)
                    tripId = null
                    previousEvent = null
                    stationarySince = 0L
                    publishStationaryCountdown()
                    switchSamplingIfNeeded()
                    return
                }
            } else if (stationarySince != 0L) { stationarySince = 0L; publishStationaryCountdown() }
        }
        if (now - lastSavedMs >= 800) {
            db.saveFix(id, location)
            lastSavedMs = now
        }
        evaluateGeofence(location, now)
        evaluateSafety(id, location, now)
    }
    private fun evaluateGeofence(fix: Location, now: Long) {
        if (fix.accuracy <= 0f || fix.accuracy > 20f) return
        val zones = lastPolicy.optJSONArray("geofence_speed_zones") ?: return
        for (i in 0 until zones.length()) {
            val zone = zones.optJSONObject(i) ?: continue
            val id = zone.optString("id")
            if (id.isEmpty()) continue
            val lat = zone.optDouble("latitude", Double.NaN)
            val lon = zone.optDouble("longitude", Double.NaN)
            val radius = zone.optDouble("radius_m", 0.0)
            if (!lat.isFinite() || !lon.isFinite() || radius <= 0) continue
            val results = FloatArray(1)
            Location.distanceBetween(fix.latitude, fix.longitude, lat, lon, results)
            // Hysteresis reduces false repeated crossing alerts near the border.
            val previous = geofenceState[id]
            val inside = if (previous == true) results[0].toDouble() <= radius + 10.0 else results[0].toDouble() <= max(0.0, radius - 10.0)
            if (previous != null && previous != inside) {
                val name = zone.optString("name", "Geofence").take(60)
                val language = getSharedPreferences(PREFS, MODE_PRIVATE).getString("language", "en")
                val message = if (language == "ur") (if (inside) "علاقے میں داخلہ: " else "علاقے سے خروج: ") + name
                  else if (language == "ar")
                    (if (inside) "دخول منطقة: " else "خروج من منطقة: ") + name
                  else (if (inside) "Entered: " else "Exited: ") + name
                try {
                    notifications.notify((id.hashCode() and 0x3fffffff) + (if (inside) 1 else 2),
                        Notification.Builder(this, ALERT_CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_map)
                            .setContentTitle(if (language == "ar") "نقاطي - المنطقة الجغرافية" else if (language == "ur") "نقاطی - جغرافیائی علاقہ" else "Nuqati geofence").setContentText(message).setAutoCancel(true).build())
                } catch (_: Exception) { }
                trace("geofence_" + (if (inside) "entry" else "exit") + "_zone=" + id)
            }
            geofenceState[id] = inside
        }
    }
    private fun threshold(name: String, default: Double): Double = lastPolicy.optDouble(name, default).takeIf { it.isFinite() && it > 0 } ?: default
    private fun enabled(name: String): Boolean = lastPolicy.optJSONObject("enabled")?.optBoolean(name, true) ?: true
    private fun evaluateSafety(id: Long, fix: Location, now: Long) {
        // GPS-only acceleration and heading estimates require quality gating to avoid false events.
        if (fix.accuracy > 15f || !fix.hasSpeed() || (Build.VERSION.SDK_INT >= 26 && fix.hasSpeedAccuracy() && fix.speedAccuracyMetersPerSecond > 2.5f)) return
        val prev = previousEvent
        previousEvent = Location(fix)
        if (prev == null || fix.time - prev.time !in 700L..12000L || !prev.hasSpeed()) return
        val dt = (fix.time - prev.time) / 1000.0
        if (dt <= 0.7 || dt > 12) return
        val speed = fix.speed * 3.6
        val acceleration = (fix.speed - prev.speed) / dt
        val speedLimit = threshold("speeding_kmh", 100.0)
        val brakeLimit = threshold("harsh_brake_ms2", 3.0)
        val accelLimit = threshold("harsh_accel_ms2", 3.0)
        val severeBrake = threshold("aggressive_brake_ms2", brakeLimit * 1.5)
        val severeAccel = threshold("aggressive_accel_ms2", accelLimit * 1.5)
        val speedMargin = threshold("excessive_speed_margin_kmh", 20.0)
        val phase4 = lastPolicy.optJSONObject("phase4")
        val cornerLimit = phase4?.optDouble("cornering_ms2", 3.5) ?: 3.5
        // A speeding violation is a continuous session, not an alert every 12 seconds.
        // Hysteresis (3 km/h) avoids GPS jitter repeatedly reopening a session.
        if (speedingTripId != null && speedingTripId != id) closeSpeedingSessions(now)
        if (enabled("speeding") && speed > speedLimit) {
            if (speedingStartedMs == null) {
                speedingStartedMs = now
                speedingTripId = id
                notifySafety("speeding")
            }
            speedingPeakKmh = maxOf(speedingPeakKmh, speed)
            if (enabled("excessive_speeding") && speed > speedLimit + speedMargin) {
                if (aggressiveStartedMs == null) {
                    aggressiveStartedMs = now
                    notifySafety("excessive_speeding")
                }
                aggressivePeakKmh = maxOf(aggressivePeakKmh, speed)
            } else if (aggressiveStartedMs != null && speed < speedLimit + speedMargin - 3.0) {
                db.saveEvent(id, "excessive_speeding_session", (now-aggressiveStartedMs!!).coerceAtLeast(0L)/1000.0, now, lastPolicy.optString("policy_version", "offline"))
                aggressiveStartedMs = null
                aggressivePeakKmh = 0.0
            }
        } else if (speedingStartedMs != null && speed < speedLimit - 3.0) {
            closeSpeedingSessions(now)
        }
        if (enabled("harsh_braking") && acceleration <= -brakeLimit) {
            event(id, if (acceleration <= -severeBrake) "excessive_harsh_braking" else "harsh_braking", -acceleration, now)
        }
        if (enabled("harsh_acceleration") && acceleration >= accelLimit) {
            event(id, if (acceleration >= severeAccel) "excessive_harsh_acceleration" else "harsh_acceleration", acceleration, now)
        }
        if (enabled("harsh_cornering") && speed >= 20 && fix.hasBearing() && prev.hasBearing()) {
            val angle = abs((fix.bearing - prev.bearing + 540) % 360 - 180)
            val lateral = fix.speed * Math.toRadians(angle.toDouble()) / dt
            if (lateral >= cornerLimit && angle / dt >= 18) event(id, "harsh_cornering", lateral, now)
        }
    }
    private fun event(id: Long, kind: String, value: Double, now: Long) {
        val group = kind.removePrefix("excessive_")
        if (now - (lastAlert[kind] ?: 0L) < 12000) return
        lastAlert[kind] = now
        val policyVersion = lastPolicy.optString("policy_version", "offline")
        db.saveEvent(id, kind, value, now, policyVersion)
        notifySafety(kind)
    }
    private fun notifySafety(kind: String) {
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
        notifications.notify(2350 + group.hashCode().ushr(1) % 100, Notification.Builder(this, ALERT_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle(if(language=="ar") "تنبيه سلامة نقاطي" else if(language=="ur") "نقاطی حفاظتی انتباہ" else "Nuqati safety alert")
            .setContentText(label)
            .setAutoCancel(true).build())
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

internal class NativeStore(context: Context) : SQLiteOpenHelper(context, "nuqati_native_tracking.db", null, 4) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE trips(id INTEGER PRIMARY KEY, started_ms INTEGER NOT NULL, ended_ms INTEGER, distance_m REAL NOT NULL DEFAULT 0, driver_id INTEGER, company_id INTEGER, vehicle_id INTEGER)")
        db.execSQL("CREATE TABLE fixes(id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, at_ms INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL NOT NULL, speed_ms REAL NOT NULL)")
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
    }
    private fun createDiagnosticsTables(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE IF NOT EXISTS raw_fixes(id INTEGER PRIMARY KEY AUTOINCREMENT, at_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL NOT NULL, speed_ms REAL NOT NULL, provider TEXT NOT NULL)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_raw_fixes_at ON raw_fixes(at_ms)")
        db.execSQL("CREATE TABLE IF NOT EXISTS gps_gaps(id INTEGER PRIMARY KEY AUTOINCREMENT, at_ms INTEGER NOT NULL, event TEXT NOT NULL, duration_ms INTEGER NOT NULL, provider TEXT NOT NULL)")
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
    fun saveFix(id: Long, loc: Location) { val cv = android.content.ContentValues().apply {
        put("trip_id", id); put("at_ms", loc.time); put("lat", loc.latitude); put("lon", loc.longitude)
        put("accuracy", loc.accuracy); put("speed_ms", if (loc.hasSpeed()) loc.speed else 0f)
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
