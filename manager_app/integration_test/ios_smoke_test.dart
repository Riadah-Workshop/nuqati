// Starts the real manager app on an iOS simulator (CI: .github/workflows/ci-ios.yml) and checks that plugins are registered and that
// the app reaches its sign-in screen. Nothing here needs a network or an account.
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nuqati_manager/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('plugins are registered', (tester) async {
    const secure = FlutterSecureStorage();
    await secure.write(key: 'nuqati_ios_smoke', value: 'ok');
    expect(await secure.read(key: 'nuqati_ios_smoke'), 'ok');
    await secure.delete(key: 'nuqati_ios_smoke');
  });

  testWidgets('the app starts and shows the sign-in screen', (tester) async {
    app.main();
    for (var i = 0; i < 40 && find.text('Company Admin Sign In').evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 500));
    }
    expect(find.text('Company Admin Sign In'), findsOneWidget);
  });
}
