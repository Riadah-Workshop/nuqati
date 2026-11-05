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
