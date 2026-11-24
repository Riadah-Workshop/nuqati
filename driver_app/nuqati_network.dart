// Nuqati Driver HTTPS failover. The backup is opt-in at build time and must
// resolve to the SAME production API/database. Never bypass Android VPN routes.
import 'dart:async';
import 'dart:io';
import 'package:http/http.dart' as http;

const String _backupBase = String.fromEnvironment('NUQATI_FALLBACK_API');
DateTime? _preferBackupUntil;

Uri? nuqatiBackupFor(Uri original) {
  if (_backupBase.trim().isEmpty || original.scheme != 'https') return null;
  final backup = Uri.tryParse(_backupBase.trim());
  if (backup == null || backup.scheme != 'https' || backup.host.isEmpty ||
      backup.userInfo.isNotEmpty || backup.hasQuery || backup.hasFragment ||
      (backup.path.isNotEmpty && backup.path != '/') ||
      backup.host == original.host ||
      // Tokens and location data must not be sent to an unrelated hostname.
      !(backup.host == 'al-riadah.sa' || backup.host.endsWith('.al-riadah.sa'))) {
    return null;
  }
  return original.replace(host: backup.host, port: backup.hasPort ? backup.port : 443);
}

bool _networkFailure(Object e) =>
    e is SocketException || e is TimeoutException ||
    e is HandshakeException || e is http.ClientException || e is HttpException;

// Replaying an arbitrary POST after a lost response can duplicate operations.
// Restrict automatic POST failover to established idempotent/receipt-based paths.
bool _canRetryPost(Uri uri) {
  final path = uri.path;
  return path == '/api/v1/mobile/tracking-heartbeat' ||
      path == '/api/v1/auth/driver-refresh' ||
      path == '/api/v1/mobile/trips/start' ||
      (path.startsWith('/api/v1/mobile/trips/') &&
          (path.endsWith('/sample') || path.endsWith('/safety-event') ||
           path.endsWith('/finish'))) ||
      path == '/api/v1/mobile/privacy-evidence' ||
      path == '/api/v1/mobile/notification-evidence' ||
      path == '/api/v1/mobile/lifecycle-event' ||
      path == '/api/v1/mobile/diagnostics';
}

Future<http.Response> _send(
  Uri uri, {required bool post, Map<String, String>? headers, Object? body,
  Duration timeout = const Duration(seconds: 10),
}) async {
  Future<http.Response> execute(Uri target) =>
      (post ? http.post(target, headers: headers, body: body) :
              http.get(target, headers: headers)).timeout(timeout);
  final backup = nuqatiBackupFor(uri);
  final retryAllowed = !post || _canRetryPost(uri);
  if (backup == null || !retryAllowed) return execute(uri);
  final preferBackup = _preferBackupUntil?.isAfter(DateTime.now()) ?? false;
  final first = preferBackup ? backup : uri;
  final second = preferBackup ? uri : backup;
  http.Response response;
  try {
    response = await execute(first);
  } catch (error) {
    if (!_networkFailure(error)) rethrow;
    // The primary network path failed. Make only one attempt on the backup.
    final recovered = await execute(second);
    if (recovered.statusCode < 500) {
      _preferBackupUntil = second == backup
          ? DateTime.now().add(const Duration(minutes: 2)) : null;
    }
    return recovered;
  }
  if (response.statusCode != 502 && response.statusCode != 503 &&
      response.statusCode != 504) return response;
  // Do not discard the known HTTP response when the alternative is also down.
  try {
    final recovered = await execute(second);
    if (recovered.statusCode < 500) {
      _preferBackupUntil = second == backup
          ? DateTime.now().add(const Duration(minutes: 2)) : null;
    }
    return recovered;
  } catch (_) {
    return response;
  }
}

Future<http.Response> nuqatiHttpGet(Uri uri, {Map<String, String>? headers,
  Duration timeout = const Duration(seconds: 10)}) =>
    _send(uri, post: false, headers: headers, timeout: timeout);

Future<http.Response> nuqatiHttpPost(Uri uri, {Map<String, String>? headers,
  Object? body, Duration timeout = const Duration(seconds: 10)}) =>
    _send(uri, post: true, headers: headers, body: body, timeout: timeout);
