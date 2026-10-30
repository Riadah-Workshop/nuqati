package com.example.nuqati_driver

import android.content.Context
import android.hardware.camera2.CameraManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel

class MainActivity: FlutterActivity() {
  private var availability: CameraManager.AvailabilityCallback? = null
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
          manager.registerAvailabilityCallback(callback,android.os.Handler(mainLooper))
        }
        override fun onCancel(arguments: Any?) {
          val manager=getSystemService(Context.CAMERA_SERVICE) as CameraManager
          availability?.let { manager.unregisterAvailabilityCallback(it) }
          availability=null
        }
      })
  }
  override fun onDestroy() {
    val manager=getSystemService(Context.CAMERA_SERVICE) as CameraManager
    availability?.let { manager.unregisterAvailabilityCallback(it) }
    availability=null
    super.onDestroy()
  }
}
