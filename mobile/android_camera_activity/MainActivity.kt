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
            "setPolicy" -> {
              val raw=call.argument<String>("policy") ?: throw IllegalArgumentException("Missing policy")
              val policy=JSONObject(raw)
              if(!policy.has("company_id") || !policy.has("policy_version") ||
                  !policy.has("speeding_kmh") || !policy.has("harsh_brake_ms2") || !policy.has("harsh_accel_ms2"))
                throw IllegalArgumentException("Invalid policy fields")
              prefs.edit().putString("policy",raw).apply()
              result.success(true)
            }
            "clearPolicy" -> { prefs.edit().remove("policy").apply(); result.success(true) }
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
              store.close()
              result.success(mapOf("active_trip_id" to trip,"fixes" to fixes,"events" to events,"privacy" to prefs.getBoolean("privacy",false)))
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
