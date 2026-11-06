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
    private var tripId: Long? = null
    private var movementSince = 0L
    private var stationarySince = 0L
    private var firstMovement: Location? = null
    private var previousEvent: Location? = null
    private var lastSavedMs = 0L
    private val lastAlert = mutableMapOf<String, Long>()
    private var lastPolicy: JSONObject = JSONObject()
    private var activeInterval = false

    override fun onCreate() {
        super.onCreate()
        db = NativeStore(this)
        manager = getSystemService(LOCATION_SERVICE) as LocationManager
        notifications = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            notifications.createNotificationChannel(NotificationChannel(CHANNEL, "Nuqati GPS recording", NotificationManager.IMPORTANCE_LOW))
            notifications.createNotificationChannel(NotificationChannel(ALERT_CHANNEL, "Nuqati safety alerts", NotificationManager.IMPORTANCE_HIGH))
        }
        lastPolicy = loadPolicy()
        tripId = db.activeTrip()
    }
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PRIVACY, ACTION_STOP -> {
                stopLocation()
                if (intent.action == ACTION_PRIVACY) { tripId?.let { db.endTrip(it, System.currentTimeMillis()) }; tripId = null }
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
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) return
        if (!manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) return
        try {
            // One native GPS listener. Android location callbacks remain independent of Flutter UI.
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, if (tripId == null) 3000L else 1000L, 0f, this, Looper.getMainLooper())
            tracking = true
            activeInterval = tripId != null
        } catch (_: SecurityException) { tracking = false }
    }
    private fun stopLocation() {
        if (tracking) manager.removeUpdates(this)
        tracking = false
    }
    private fun switchSamplingIfNeeded() {
        val shouldActive = tripId != null
        if (shouldActive != activeInterval) { stopLocation(); startLocation() }
    }
    override fun onLocationChanged(location: Location) {
        val now = System.currentTimeMillis()
        if (!location.hasAccuracy() || location.accuracy <= 0 || location.accuracy > 50f ||
            now - location.time > 15000 || location.time - now > 5000) return
        val speed = if (location.hasSpeed()) location.speed.coerceAtLeast(0f) else 0f
        val speedKmh = speed * 3.6
        if (speedKmh > 180) return
        val validMovement = location.accuracy <= 35f && location.hasSpeed() && speedKmh >= 7
        if (tripId == null) {
            if (validMovement) {
                if (movementSince == 0L) { movementSince = now; firstMovement = Location(location) }
                val displacement = firstMovement?.distanceTo(location) ?: 0f
                if (now - movementSince >= 10000 && displacement >= 25f) {
                    val id = db.startTrip(now)
                    tripId = id
                    movementSince = 0L
                    firstMovement = null
                    stationarySince = 0L
                    previousEvent = null
                    switchSamplingIfNeeded()
                }
            } else if (speedKmh < 3 || location.accuracy > 35f) {
                // Do not create a trip from isolated GPS jumps.
                if (movementSince != 0L && now - movementSince > 20000) { movementSince = 0L; firstMovement = null }
            }
        }
        val id = tripId ?: return
        if (location.accuracy <= 35f) {
            if (speedKmh < 5) {
                if (stationarySince == 0L) stationarySince = now
                if (now - stationarySince >= 180000) {
                    db.endTrip(id, now)
                    tripId = null
                    previousEvent = null
                    stationarySince = 0L
                    switchSamplingIfNeeded()
                    return
                }
            } else stationarySince = 0L
        }
        if (now - lastSavedMs >= 800) {
            db.saveFix(id, location)
            lastSavedMs = now
        }
        evaluateSafety(id, location, now)
    }
    private fun threshold(name: String, default: Double): Double = lastPolicy.optDouble(name, default).takeIf { it.isFinite() && it > 0 } ?: default
    private fun enabled(name: String): Boolean = lastPolicy.optJSONObject("enabled")?.optBoolean(name, true) ?: true
    private fun evaluateSafety(id: Long, fix: Location, now: Long) {
        // GPS-only acceleration and heading estimates require quality gating to avoid false events.
        if (fix.accuracy > 15f || !fix.hasSpeed() || (Build.VERSION.SDK_INT >= 26 && fix.hasSpeedAccuracy() && fix.speedAccuracyMetersPerSecond > 2.5f)) return
        val prev = previousEvent
        previousEvent = Location(fix)
        if (prev == null || now - prev.time !in 700L..12000L || !prev.hasSpeed()) return
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
        if (enabled("speeding") && speed > speedLimit) {
            event(id, if (speed > speedLimit + speedMargin) "excessive_speeding" else "speeding", speed, now)
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
        if (now - (lastAlert[group] ?: 0L) < 12000) return
        lastAlert[group] = now
        val policyVersion = lastPolicy.optString("policy_version", "offline")
        db.saveEvent(id, kind, value, now, policyVersion)
        val language = getSharedPreferences(PREFS, MODE_PRIVATE).getString("language", "en")
        val label = if (language == "ar") when (group) {
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
            .setContentTitle("Nuqati safety alert")
            .setContentText(label)
            .setAutoCancel(true).build())
    }
    private fun loadPolicy(): JSONObject = try {
        JSONObject(getSharedPreferences(PREFS, MODE_PRIVATE).getString("policy", "{}") ?: "{}")
    } catch (_: Exception) { JSONObject() }
    override fun onDestroy() { stopLocation(); db.close(); super.onDestroy() }
}

internal class NativeStore(context: Context) : SQLiteOpenHelper(context, "nuqati_native_tracking.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE trips(id INTEGER PRIMARY KEY, started_ms INTEGER NOT NULL, ended_ms INTEGER)")
        db.execSQL("CREATE TABLE fixes(id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, at_ms INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL NOT NULL, speed_ms REAL NOT NULL)")
        db.execSQL("CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, at_ms INTEGER NOT NULL, kind TEXT NOT NULL, value REAL NOT NULL, policy_version TEXT NOT NULL)")
        db.execSQL("CREATE INDEX idx_fixes_trip ON fixes(trip_id,at_ms)")
        db.execSQL("CREATE INDEX idx_events_trip ON events(trip_id,at_ms)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    fun activeTrip(): Long? = readableDatabase.rawQuery("SELECT id FROM trips WHERE ended_ms IS NULL ORDER BY id DESC LIMIT 1", null).use { if (it.moveToFirst()) it.getLong(0) else null }
    fun startTrip(at: Long): Long { val cv = android.content.ContentValues().apply { put("started_ms", at) }; return writableDatabase.insertOrThrow("trips", null, cv) }
    fun endTrip(id: Long, at: Long) { writableDatabase.execSQL("UPDATE trips SET ended_ms=? WHERE id=? AND ended_ms IS NULL", arrayOf(at,id)) }
    fun saveFix(id: Long, loc: Location) { val cv = android.content.ContentValues().apply {
        put("trip_id", id); put("at_ms", loc.time); put("lat", loc.latitude); put("lon", loc.longitude)
        put("accuracy", loc.accuracy); put("speed_ms", if (loc.hasSpeed()) loc.speed else 0f)
    }; writableDatabase.insertOrThrow("fixes", null, cv) }
    fun saveEvent(id: Long, kind: String, value: Double, at: Long, version: String) { val cv = android.content.ContentValues().apply {
        put("trip_id", id); put("at_ms", at); put("kind", kind); put("value", value); put("policy_version", version)
    }; writableDatabase.insertOrThrow("events", null, cv) }
}
