package com.example.nuqati_driver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.camera2.CameraManager
import android.os.Build
import android.os.Handler
import android.os.PowerManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import android.content.pm.PackageManager
import android.Manifest

class MainActivity: FlutterActivity() {
  private var availability: CameraManager.AvailabilityCallback? = null
  private var screenReceiver: BroadcastReceiver? = null
  private fun saveScreenState(locked: Boolean) {
    try {
      val file=getDatabasePath("nuqati_screen_state.json")
      file.parentFile?.mkdirs()
      val state=if(locked) "locked" else "unlocked"
      file.writeText("{\"state\":\"$state\",\"at_ms\":${System.currentTimeMillis()}}")
    } catch (_: Exception) { }
  }
  override fun onCreate(savedInstanceState: android.os.Bundle?) {
    super.onCreate(savedInstanceState)
    val power=getSystemService(Context.POWER_SERVICE) as PowerManager
    saveScreenState(!power.isInteractive)
    val receiver=object: BroadcastReceiver() {
      override fun onReceive(context: Context?, intent: Intent?) {
        when(intent?.action) {
          Intent.ACTION_SCREEN_OFF -> saveScreenState(true)
          Intent.ACTION_SCREEN_ON -> saveScreenState(false)
        }
      }
    }
    screenReceiver=receiver
    val filter=IntentFilter().apply { addAction(Intent.ACTION_SCREEN_OFF);addAction(Intent.ACTION_SCREEN_ON) }
    if(Build.VERSION.SDK_INT>=33)registerReceiver(receiver,filter,Context.RECEIVER_NOT_EXPORTED)
    else registerReceiver(receiver,filter)
  }
  override fun configureFlutterEngine(engine: FlutterEngine) {
    super.configureFlutterEngine(engine)
    MethodChannel(engine.dartExecutor.binaryMessenger, "nuqati/native_tracking")
      .setMethodCallHandler { call, result ->
        try {
          val prefs=getSharedPreferences(NuqatiNativeTrackingService.PREFS,Context.MODE_PRIVATE)
          when(call.method) {
            "setRecordingOwner" -> {
              val driver=call.argument<Int>("driver_id") ?: 0
              val company=call.argument<Int>("company_id") ?: 0
              val vehicle=call.argument<Int>("vehicle_id") ?: 0
              if(driver<=0||company<=0||vehicle<=0)throw IllegalArgumentException("Verified driver and vehicle required")
              val oldDriver=prefs.getInt("owner_driver",0)
              val oldCompany=prefs.getInt("owner_company",0)
              if(oldDriver>0 && (oldDriver!=driver || oldCompany!=company))
                throw IllegalStateException("Another driver is signed in. Sign out first.")
              if(!prefs.edit().putInt("owner_driver",driver).putInt("owner_company",company).putInt("owner_vehicle",vehicle).commit())throw IllegalStateException("Owner not persisted")
              result.success(true)
            }
            "clearRecordingOwner" -> { prefs.edit().remove("owner_driver").remove("owner_company").remove("owner_vehicle").commit(); result.success(true) }
            "setPolicy" -> {
              val raw=call.argument<String>("policy") ?: throw IllegalArgumentException("Missing policy")
              val policy=JSONObject(raw)
              if(!policy.has("company_id") || !policy.has("policy_version") ||
                  !policy.has("speeding_kmh") || !policy.has("harsh_brake_ms2") || !policy.has("harsh_accel_ms2"))
                throw IllegalArgumentException("Invalid policy fields")
              val version=policy.getString("policy_version")
              val company=policy.get("company_id").toString()
              val old=runCatching { JSONObject(prefs.getString("policy", "{}") ?: "{}") }.getOrDefault(JSONObject())
              val unchanged=old.optString("policy_version")==version && old.optString("company_id")==company &&
                  old.toString()==policy.toString()
              if(!unchanged && !prefs.edit().putString("policy",raw).commit())
                throw IllegalStateException("Policy could not be persisted")
              // A running service reads the persisted policy on its next location callback.
              result.success(mapOf("changed" to !unchanged,"version" to version,"saved" to true))
            }
            "setLanguage" -> { val lang=call.argument<String>("language") ?: "en"; prefs.edit().putString("language",if(lang in listOf("ar","ur","en")) lang else "en").apply(); result.success(true) }
            "setAlertsEnabled" -> {
              val enabled=call.argument<Boolean>("enabled") ?: true
              if(!prefs.edit().putBoolean("alerts_enabled",enabled).commit())
                throw IllegalStateException("Safety notification preference could not be saved")
              result.success(true)
            }
            "isPowerSaveMode" -> { val power=getSystemService(Context.POWER_SERVICE) as PowerManager; result.success(power.isPowerSaveMode) }
            "openPowerSaveSettings" -> { startActivity(Intent(android.provider.Settings.ACTION_BATTERY_SAVER_SETTINGS)); result.success(true) }
            "clearPolicy" -> { prefs.edit().remove("policy").commit(); result.success(true) }
            "start" -> {
              if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED)
                throw SecurityException("Fine location permission required")
              if(prefs.getBoolean("privacy",false)) throw IllegalStateException("Privacy Mode enabled")
              val intent=Intent(this,NuqatiNativeTrackingService::class.java).apply { action=NuqatiNativeTrackingService.ACTION_START }
              androidx.core.content.ContextCompat.startForegroundService(this,intent)
              result.success(true)
            }
            "stop" -> {
              startService(Intent(this,NuqatiNativeTrackingService::class.java).apply { action=NuqatiNativeTrackingService.ACTION_STOP })
              result.success(true)
            }
            "privacyOn" -> {
              if(NativeStore(this).activeTrip()!=null)
                throw IllegalStateException("Privacy Mode cannot be enabled during an active trip")
              prefs.edit().putBoolean("privacy",true).apply()
              startService(Intent(this,NuqatiNativeTrackingService::class.java).apply { action=NuqatiNativeTrackingService.ACTION_PRIVACY })
              result.success(true)
            }
            "privacyOff" -> { prefs.edit().putBoolean("privacy",false).apply(); result.success(true) }
            "status" -> {
              val store=NativeStore(this)
              val trip=store.activeTrip()
              val db=store.readableDatabase
              val fixes=db.rawQuery("SELECT COUNT(*) FROM fixes",null).use { if(it.moveToFirst()) it.getInt(0) else 0 }
              val events=db.rawQuery("SELECT COUNT(*) FROM events",null).use { if(it.moveToFirst()) it.getInt(0) else 0 }
              val lastFix=db.rawQuery("SELECT MAX(at_ms) FROM fixes",null).use { if(it.moveToFirst()&&!it.isNull(0)) it.getLong(0) else null }
              val distance=if(trip!=null) db.rawQuery("SELECT distance_m FROM trips WHERE id=?",arrayOf(trip.toString())).use {if(it.moveToFirst())it.getDouble(0) else 0.0} else 0.0
              store.close()
              result.success(mapOf("active_trip_id" to trip,"stationary_since_ms" to (if (trip != null) prefs.getLong("stationary_since_ms",0L) else 0L),"trip_end_delay_s" to (NuqatiNativeTrackingService.TRIP_END_DELAY_MS/1000L),"fixes" to fixes,"events" to events,"last_fix_ms" to lastFix,"distance_m" to distance,"policy_version" to runCatching { JSONObject(prefs.getString("policy", "{}") ?: "{}").optString("policy_version") }.getOrDefault(""),"privacy" to prefs.getBoolean("privacy",false),"gps_state" to (prefs.getString("gps_state","unknown") ?: "unknown"),"gps_state_at" to prefs.getLong("gps_state_at",0L),"last_gps_callback_ms" to prefs.getLong("last_gps_callback_ms",0L),"last_accepted_fix_ms" to prefs.getLong("last_accepted_fix_ms",0L),"last_speed_kmh" to prefs.getFloat("last_speed_kmh",0f).toDouble(),"last_acceleration_ms2" to prefs.getFloat("last_acceleration_ms2",0f).toDouble(),"last_acceleration_valid" to prefs.getBoolean("last_acceleration_valid",false),"last_acceleration_at_ms" to prefs.getLong("last_acceleration_at_ms",0L),"alerts_enabled" to prefs.getBoolean("alerts_enabled",true),"last_accuracy_m" to prefs.getFloat("last_accuracy_m",0f).toDouble(),"gps_callback_count" to prefs.getLong("gps_callback_count",0L),"gps_provider_mode" to (prefs.getString("gps_provider_mode","none") ?: "none"),"last_callback_accuracy_m" to prefs.getFloat("last_callback_accuracy_m",-1f).toDouble(),"last_callback_provider" to (prefs.getString("last_callback_provider","unknown") ?: "unknown")))
            }
            else -> result.notImplemented()
          }
        } catch(e:Exception) { result.error("NATIVE_TRACKING",e.message,null) }
      }
    EventChannel(engine.dartExecutor.binaryMessenger, "nuqati/camera_activity")
      .setStreamHandler(object: EventChannel.StreamHandler {
        override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
          val manager=getSystemService(Context.CAMERA_SERVICE) as CameraManager
          val unavailable=mutableSetOf<String>()
          val callback=object: CameraManager.AvailabilityCallback() {
            override fun onCameraAvailable(id: String) { unavailable.remove(id); events?.success(unavailable.isNotEmpty()) }
            override fun onCameraUnavailable(id: String) { unavailable.add(id); events?.success(true) }
          }
          availability=callback
          manager.registerAvailabilityCallback(callback,Handler(mainLooper))
        }
        override fun onCancel(arguments: Any?) {
          val manager=getSystemService(Context.CAMERA_SERVICE) as CameraManager
          availability?.let { manager.unregisterAvailabilityCallback(it) }
          availability=null
        }
      })
  }
  override fun onDestroy() {
    screenReceiver?.let { unregisterReceiver(it) }
    screenReceiver=null
    val manager=getSystemService(Context.CAMERA_SERVICE) as CameraManager
    availability?.let { manager.unregisterAvailabilityCallback(it) }
    availability=null
    super.onDestroy()
  }
}
