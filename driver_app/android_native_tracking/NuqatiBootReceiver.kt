package com.example.nuqati_driver

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat

/** Best-effort restart: never records before a verified driver/vehicle assignment. */
class NuqatiBootReceiver : BroadcastReceiver() {
 override fun onReceive(context: Context, intent: Intent) {
  if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != "android.intent.action.MY_PACKAGE_REPLACED") return
  val prefs=context.getSharedPreferences(NuqatiNativeTrackingService.PREFS,Context.MODE_PRIVATE)
  if (prefs.getInt("owner_driver",0)<=0 || prefs.getInt("owner_company",0)<=0 ||
      prefs.getInt("owner_vehicle",0)<=0 || prefs.getBoolean("privacy",false)) return
  if (ContextCompat.checkSelfPermission(context,Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED ||
      (Build.VERSION.SDK_INT>=29 && ContextCompat.checkSelfPermission(context,Manifest.permission.ACCESS_BACKGROUND_LOCATION)!=PackageManager.PERMISSION_GRANTED)) {
   Log.w("NuqatiBoot", "Background location permission missing; cannot safely restart tracking")
   return
  }
  try {
   val service=Intent(context,NuqatiNativeTrackingService::class.java).apply { action=NuqatiNativeTrackingService.ACTION_START }
   ContextCompat.startForegroundService(context,service)
  } catch(e:Exception) {
   // Android 14+/OEM restrictions can block boot-started location foreground services.
   Log.w("NuqatiBoot","System prevented auto restart; user must open Nuqati",e)
  }
 }
}
