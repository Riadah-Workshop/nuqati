import UIKit
import Flutter

// Flutter 3.41+ starts iOS apps with the UIScene lifecycle: the Flutter engine is created by the scene, so there is no window or
// FlutterViewController here yet, and plugins and platform channels must be registered in didInitializeImplicitFlutterEngine.
// (Installing the recorder from didFinishLaunching by looking for the window's root view controller silently does nothing under
// UIScene, and every call on the "nuqati/native_tracking" channel then fails.) ops/ios/prepare_ios_project.py refuses a generated project that does not
// use this structure, and the iOS CI job proves the channel answers on a simulator.
@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    NuqatiIOSNativeTracking.shared.install(messenger: engineBridge.applicationRegistrar.messenger())
  }
}
