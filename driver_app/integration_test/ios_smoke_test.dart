// Starts the real driver app on an iOS simulator (CI: .github/workflows/ci-ios.yml) and checks what a successful compile cannot:
// that plugins are registered, that the native CoreLocation recorder answers on its channel, that the permission_handler macros are
// compiled in and that the app reaches its sign-in screen. Nothing here needs a network, a location or an account.
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nuqati_driver/main.dart' as app;
import 'package:permission_handler/permission_handler.dart' as ph;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('plugins are registered (the app delegate registers them under UIScene)', (tester) async {
    const secure = FlutterSecureStorage();
    await secure.write(key: 'nuqati_ios_smoke', value: 'ok');
    expect(await secure.read(key: 'nuqati_ios_smoke'), 'ok');
    await secure.delete(key: 'nuqati_ios_smoke');
  });

  testWidgets('permission_handler has the location permission compiled in (Podfile macros)', (tester) async {
    // Without PERMISSION_LOCATION=1 the plugin answers every request with "denied" and a "not applicable" service status.
    expect(await ph.Permission.locationAlways.serviceStatus, isNot(ph.ServiceStatus.notApplicable));
  });

  testWidgets('the native CoreLocation recorder answers on the nuqati/native_tracking channel', (tester) async {
    const channel = MethodChannel('nuqati/native_tracking');
    expect(await channel.invokeMethod<bool>('isPowerSaveMode'), isA<bool>());
    final status = await channel.invokeMapMethod<String, dynamic>('status');
    expect(status, isNotNull);
    expect(status!.containsKey('gps_state'), isTrue);
    final records = await channel.invokeMapMethod<String, dynamic>('getRecords', {'after_fix_id': 0, 'after_event_id': 0});
    expect(records, isNotNull);
    expect(records!['trips'], isA<List>());
    expect(records['fixes'], isA<List>());
    expect(records['events'], isA<List>());
  });

  testWidgets('the app starts and shows the sign-in screen', (tester) async {
    app.main();
    // Start-up does asynchronous work (database, services); wait for the screen without waiting for the app's timers to go idle.
    for (var i = 0; i < 40 && find.text('Iqama / Saudi ID number').evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.text('Iqama / Saudi ID number'), findsOneWidget);
  });
}
