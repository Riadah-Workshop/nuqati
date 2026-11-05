import 'package:geolocator_android/geolocator_android.dart';
import 'dart:async';
import 'dart:math' as math;
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'dart:typed_data';
import 'dart:ui';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart' as ph;
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as path;
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// Phase 1B diagnostics: local-only, bounded log. No credentials or GPS coordinates.
Future<File> nuqatiDiagnosticFile() async => File(path.join(await getDatabasesPath(), 'nuqati_diagnostics.txt'));
Future<void> nuqatiLog(String event, [Object? error, StackTrace? stack]) async {
 try {
  final f=await nuqatiDiagnosticFile();
  if(await f.exists() && await f.length()>180000) {
   final content=await f.readAsString();
   await f.writeAsString(content.substring(content.length-90000));
  }
  final safeError=(error?.toString()??'').replaceAll(RegExp(r'Bearer\s+[^\s]+',caseSensitive:false),'Bearer [REDACTED]');
  final trace=stack?.toString().split('\n').take(8).join(' | ')??'';
  await f.writeAsString('${DateTime.now().toUtc().toIso8601String()} $event $safeError $trace\n',mode:FileMode.append,flush:true);
 }catch(_){ }
}
Future<String> nuqatiReadDiagnostics() async {
 try {final f=await nuqatiDiagnosticFile();return await f.exists()?await f.readAsString():'No diagnostic events recorded yet.';}
 catch(e){return 'Unable to read diagnostics: $e';}
}


// Periodically transmit a bounded, location-free diagnostic tail. IDs deduplicate retries.
Future<void> nuqatiUploadDiagnostics() async {
 try {
  final token=await const FlutterSecureStorage().read(key:'nuqati_driver_access_token');
  if(token==null||token.isEmpty)return;
  final f=await nuqatiDiagnosticFile();if(!await f.exists())return;
  final lines=(await f.readAsLines()).where((l)=>l.length>25).toList();
  final events=<Map<String,dynamic>>[];
  for(final line in lines.length>100?lines.sublist(lines.length-100):lines){
   final space=line.indexOf(' ');if(space<1)continue;
   final at=DateTime.tryParse(line.substring(0,space));if(at==null)continue;
   final raw=line.substring(space+1);
   final code=RegExp(r'^[A-Z][A-Z0-9_]*').firstMatch(raw)?.group(0)??'APP_LOG';
   final severity=code.contains('CRASH')||code.contains('UNHANDLED')?'CRASH':
     code.contains('FAILED')||code.contains('ERROR')?'ERROR':
     code.contains('BLOCKED')||code.contains('REJECT')||code.contains('DEFERRED')?'WARNING':'INFO';
   final category=code.contains('GPS')||code.contains('MONITOR')?'GPS':
     code.contains('TRIP')||code.contains('AUTO_START')||code.contains('MOTION')?'TRIP':
     code.contains('PERMISSION')?'PERMISSION':code.contains('SYNC')||code.contains('UPLOAD')?'SYNC':'APP';
   // Upload only known structured codes. Never upload arbitrary exception strings,
   // location coordinates, identifiers, authentication data, or stack traces.
   final structured=raw.substring(code.length).trim();
   final detail=(code=='MOTION_GATE'||code=='SYNC_DEFERRED'||code=='GPS_WATCHDOG_STALE_FIX')
      ?structured.substring(0,math.min(200,structured.length)):'';
   events.add({'event_id':sha256.convert(utf8.encode(line)).toString(),
    'occurred_at':at.toUtc().toIso8601String(),'severity':severity,
    'category':category,'code':code,'detail':detail});
  }
  if(events.isEmpty)return;
  await http.post(Uri.parse('$api/api/v1/mobile/diagnostics'),
   headers:{'Authorization':'Bearer $token','Content-Type':'application/json'},
   body:jsonEncode({'events':events})).timeout(const Duration(seconds:15));
 }catch(_){/* Offline diagnostics remain locally available for retry. */}
}

const api = String.fromEnvironment('NUQATI_API', defaultValue:'https://staging-nuqati.al-riadah.sa');
const navy=Color(0xff0b1c30), lime=Color(0xffa8d941), blue=Color(0xff17334d);
Future<void> main() async {
 WidgetsFlutterBinding.ensureInitialized();
 FlutterError.onError=(details){FlutterError.presentError(details);nuqatiLog('FLUTTER_ERROR',details.exception,details.stack);};
 PlatformDispatcher.instance.onError=(error,stack){nuqatiLog('UNHANDLED_PLATFORM_ERROR',error,stack);return false;};
 try {
  final db=await openTrackingDatabase();
  await nuqatiLog('TRACKING_DB_SCHEMA_READY');
  // Do not close/delete the database; the foreground service shares it via sqflite.
  await configureTrackingService();
  await initializeViolationAlerts();
  await nuqatiLog('UI service configured');
 }
 catch(e,s){await nuqatiLog('SERVICE_CONFIG_FAILED',e,s);}
 runApp(const MaterialApp(debugShowCheckedModeBanner:false,home:DriverApp()));
}

// Phase 1B: the Android foreground service owns GPS capture and durable delivery.
// Samples are written to SQLite BEFORE attempting HTTP upload.
Future<Database> openTrackingDatabase() async {
 final dbPath=path.join(await getDatabasesPath(),'nuqati_gps_queue_v1.db');
 return openDatabase(dbPath,version:6,onCreate:(db,_)async {
   await db.execute('CREATE TABLE gps_queue (sample_id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL, captured_at TEXT NOT NULL, payload TEXT NOT NULL)');
   await db.execute('CREATE TABLE local_trips (local_id INTEGER PRIMARY KEY, remote_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT)');
   await db.execute('CREATE TABLE maintenance_notices (notice_key TEXT PRIMARY KEY, created_at TEXT NOT NULL)');
   await db.execute('CREATE TABLE privacy_evidence_queue (event_id TEXT PRIMARY KEY, privacy_enabled INTEGER NOT NULL, selected_at TEXT NOT NULL)');
   await db.execute('CREATE TABLE notification_evidence_queue (event_id TEXT PRIMARY KEY, notifications_enabled INTEGER NOT NULL, selected_at TEXT NOT NULL)');
   await db.execute('CREATE TABLE safety_live_events (event_id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL, event_type TEXT NOT NULL, recorded_at TEXT NOT NULL)');
   await db.execute('CREATE TABLE IF NOT EXISTS local_score_history (trip_id INTEGER PRIMARY KEY, ended_at TEXT NOT NULL, points INTEGER NOT NULL, event_count INTEGER NOT NULL)');
   await db.execute('CREATE TABLE IF NOT EXISTS local_daily_score_notices (local_day TEXT PRIMARY KEY, sent_at TEXT NOT NULL)');
 },onUpgrade:(db,oldVersion,newVersion)async {
   if(oldVersion<2)await db.execute('CREATE TABLE IF NOT EXISTS local_trips (local_id INTEGER PRIMARY KEY, remote_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT)');
   if(oldVersion<3)await db.execute('CREATE TABLE IF NOT EXISTS maintenance_notices (notice_key TEXT PRIMARY KEY, created_at TEXT NOT NULL)');
   if(oldVersion<4)await db.execute('CREATE TABLE IF NOT EXISTS privacy_evidence_queue (event_id TEXT PRIMARY KEY, privacy_enabled INTEGER NOT NULL, selected_at TEXT NOT NULL)');
   if(oldVersion<5)await db.execute('CREATE TABLE IF NOT EXISTS notification_evidence_queue (event_id TEXT PRIMARY KEY, notifications_enabled INTEGER NOT NULL, selected_at TEXT NOT NULL)');
   if(oldVersion<6)await db.execute('CREATE TABLE IF NOT EXISTS safety_live_events (event_id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL, event_type TEXT NOT NULL, recorded_at TEXT NOT NULL)');
 },onOpen:(db)async {
   // Repair partially initialized databases without deleting trips or GPS samples.
   // SQLite database user_version can already be current even when a table is missing.
   await db.transaction((txn)async {
     await txn.execute('CREATE TABLE IF NOT EXISTS gps_queue (sample_id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL, captured_at TEXT NOT NULL, payload TEXT NOT NULL)');
     await txn.execute('CREATE TABLE IF NOT EXISTS local_trips (local_id INTEGER PRIMARY KEY, remote_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT)');
     await txn.execute('CREATE TABLE IF NOT EXISTS maintenance_notices (notice_key TEXT PRIMARY KEY, created_at TEXT NOT NULL)');
     await txn.execute('CREATE TABLE IF NOT EXISTS privacy_evidence_queue (event_id TEXT PRIMARY KEY, privacy_enabled INTEGER NOT NULL, selected_at TEXT NOT NULL)');
     await txn.execute('CREATE TABLE IF NOT EXISTS notification_evidence_queue (event_id TEXT PRIMARY KEY, notifications_enabled INTEGER NOT NULL, selected_at TEXT NOT NULL)');
     await txn.execute('CREATE TABLE IF NOT EXISTS safety_live_events (event_id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL, event_type TEXT NOT NULL, recorded_at TEXT NOT NULL)');
     final cols=await txn.rawQuery('PRAGMA table_info(safety_live_events)');
     if(!cols.any((c)=>c['name']=='value'))await txn.execute('ALTER TABLE safety_live_events ADD COLUMN value REAL');
     await txn.execute('CREATE TABLE IF NOT EXISTS local_score_history (trip_id INTEGER PRIMARY KEY, ended_at TEXT NOT NULL, points INTEGER NOT NULL, event_count INTEGER NOT NULL)');
     await txn.execute('CREATE TABLE IF NOT EXISTS local_daily_score_notices (local_day TEXT PRIMARY KEY, sent_at TEXT NOT NULL)');
   });
 });
}

// Best-effort local housekeeping. Never delete unsent GPS, trips or audit evidence.
// Confirmed backend data remains authoritative; only old, unlinked coaching records expire.
Future<void> pruneAcknowledgedLocalMetadata(Database db) async {
 try {
  final safetyCutoff=DateTime.now().toUtc().subtract(const Duration(days:14)).toIso8601String();
  final noticeCutoff=DateTime.now().toUtc().subtract(const Duration(days:90)).toIso8601String();
  await db.transaction((txn) async {
   await txn.rawDelete("""DELETE FROM safety_live_events
     WHERE recorded_at < ? AND NOT EXISTS
     (SELECT 1 FROM local_trips WHERE local_trips.local_id = safety_live_events.trip_id)""",[safetyCutoff]);
   await txn.delete('maintenance_notices',where:'created_at < ?',whereArgs:[noticeCutoff]);
   final historyCutoff=DateTime.now().toUtc().subtract(const Duration(days:120)).toIso8601String();
   await txn.rawDelete('DELETE FROM local_score_history WHERE ended_at < ? AND trip_id NOT IN (SELECT trip_id FROM local_score_history ORDER BY ended_at DESC LIMIT 1)',[historyCutoff]);
   await txn.rawDelete('DELETE FROM local_daily_score_notices WHERE sent_at < ?',[historyCutoff]);
  });
 }catch(e){await nuqatiLog('LOCAL_METADATA_PRUNE_FAILED',e);}
}

// Local driver-coaching scores do not use or modify backend RAG.
// Normal warnings cost 2 points, excessive warnings cost 3 points.
int nuqatiLocalPenalty(String kind)=>kind.startsWith('excessive_')?3:2;
Future<Map<String,int>> nuqatiCountLocalEvents(Database db,int tripId) async {
 final rows=await db.rawQuery('SELECT event_type, COUNT(*) AS n FROM safety_live_events WHERE trip_id = ? GROUP BY event_type',[tripId]);
 return {for(final row in rows) (row['event_type'] as String):((row['n'] as num?)?.toInt()??0)};
}
int nuqatiPointsFromCounts(Map<String,int> counts)=>
 (100-counts.entries.fold<int>(0,(sum,e)=>sum+e.value*nuqatiLocalPenalty(e.key))).clamp(0,100).toInt();
Future<Map<String,dynamic>> nuqatiFinalizeLocalPoints(Database db,int id,DateTime ended) async {
 final counts=await nuqatiCountLocalEvents(db,id);
 final points=nuqatiPointsFromCounts(counts);
 final previous=await db.query('local_score_history',where:'trip_id != ?',whereArgs:[id],orderBy:'ended_at DESC',limit:1);
 final previousPoints=previous.isEmpty?null:(previous.first['points'] as num).toInt();
 await db.insert('local_score_history',{'trip_id':id,'ended_at':ended.toUtc().toIso8601String(),
  'points':points,'event_count':counts.values.fold<int>(0,(sum,n)=>sum+n)},conflictAlgorithm:ConflictAlgorithm.replace);
 return {'points':points,'previous':previousPoints,'events':counts.values.fold<int>(0,(sum,n)=>sum+n)};
}
String nuqatiLocalProgressMessage(int points,int? previous,String lang){
 if(previous==null)return localizedAlert(lang,'Trip complete: $points/100 points. Keep driving safely.','انتهت الرحلة: $points من 100 نقطة. واصل القيادة الآمنة.','ٹرپ مکمل: $points/100 پوائنٹس۔ محفوظ ڈرائیونگ جاری رکھیں۔');
 final diff=points-previous;
 if(diff>0)return localizedAlert(lang,'Trip: $points/100. Improved by $diff points!','الرحلة: $points من 100. تحسنت بمقدار $diff نقطة!','ٹرپ: $points/100۔ $diff پوائنٹس بہتری!');
 if(diff<0)return localizedAlert(lang,'Trip: $points/100. Down by ${-diff} points; keep practising.','الرحلة: $points من 100. تراجعت ${-diff} نقطة؛ واصل التحسن.','ٹرپ: $points/100۔ ${-diff} پوائنٹس کم، مزید مشق کریں۔');
 return localizedAlert(lang,'Trip: $points/100. Consistent driving, keep it up!','الرحلة: $points من 100. أداء ثابت، واصل!','ٹرپ: $points/100۔ اچھی مستقل کارکردگی!');
}
Future<void> createNuqatiTrackingChannel() async {
 const channel = AndroidNotificationChannel(
  'nuqati_active_trip',
  'Nuqati active trip tracking',
  description: 'Shows when Nuqati is recording an active driving trip',
  importance: Importance.low,
  playSound: false,
  enableVibration: false,
 );
 final notifications = FlutterLocalNotificationsPlugin();
 await notifications.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
     ?.createNotificationChannel(channel);
}

// Persist language so background notifications use the driver's selection.
const nuqatiLanguageKey='nuqati_language';
Future<String> nuqatiLanguage() async => (await const FlutterSecureStorage().read(key:nuqatiLanguageKey))??'en';
String localizedAlert(String lang,String en,String ar,String ur)=>lang=='ar'?ar:lang=='ur'?ur:en;
Future<bool> trackingPermissionsReady() async {
 if(!await Geolocator.isLocationServiceEnabled())return false;
 final p=await Geolocator.checkPermission();
 // While-in-use permission can support an already-running foreground location
 // service. Background permission is requested separately in the UI.
 return p==LocationPermission.always||p==LocationPermission.whileInUse;
}
final FlutterLocalNotificationsPlugin nuqatiAlerts=FlutterLocalNotificationsPlugin();
Future<void> initializeViolationAlerts({bool requestPermission=true}) async {
 const settings=InitializationSettings(android:AndroidInitializationSettings('ic_bg_service_small'));
 await nuqatiAlerts.initialize(settings);
 const channel=AndroidNotificationChannel('nuqati_violations_v1','Driving safety warnings',description:'Speeding, braking, acceleration and cornering alerts',importance:Importance.high,playSound:true,enableVibration:true);
 final android=nuqatiAlerts.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
 await android?.createNotificationChannel(channel);
 if(requestPermission)await android?.requestNotificationsPermission();
}
Future<void> showViolationAlert(String message,int notificationId) async {
 if((await const FlutterSecureStorage().read(key:'nuqati_alerts_enabled'))=='0'){await nuqatiLog('VIOLATION_NOTIFICATION_MUTED');return;}
 await nuqatiLog('VIOLATION_NOTIFICATION_ATTEMPT');
 try {
  final lang=await nuqatiLanguage();
  await nuqatiAlerts.show(notificationId,localizedAlert(lang,'Nuqati safety alert','تنبيه سلامة من نقاطي','نقاطی حفاظتی انتباہ'),message,
    const NotificationDetails(android:AndroidNotificationDetails('nuqati_violations_v1','Driving safety warnings',channelDescription:'Speeding, harsh braking and acceleration alerts',importance:Importance.high,priority:Priority.high,playSound:true,enableVibration:true)));
 }catch(e,s){await nuqatiLog('VIOLATION_NOTIFICATION_FAILED',e,s);}
}
Future<int?> locallyActiveTrip() async {
 final db=await openTrackingDatabase();
 final rows=await db.query('local_trips',where:'ended_at IS NULL',orderBy:'started_at DESC',limit:1);
 return rows.isEmpty?null:rows.first['local_id'] as int;
}
Future<void> configureTrackingService() async {
 await createNuqatiTrackingChannel();
 final service=FlutterBackgroundService();
 await service.configure(
  androidConfiguration:AndroidConfiguration(
    onStart:nuqatiTrackingEntry,autoStart:false,autoStartOnBoot:true,isForegroundMode:true,
    notificationChannelId:'nuqati_active_trip',initialNotificationTitle:'Nuqati movement monitoring',
    initialNotificationContent:'GPS tracking is active',foregroundServiceNotificationId:2301,
  ),
  iosConfiguration:IosConfiguration(autoStart:false),
 );
}

@pragma('vm:entry-point')
void nuqatiTrackingEntry(ServiceInstance service) async {
 DartPluginRegistrant.ensureInitialized();
 await nuqatiLog('SERVICE_ENTRY');
 final Database db;
 try {db=await openTrackingDatabase();await nuqatiLog('SERVICE_DB_OPEN_OK');unawaited(pruneAcknowledgedLocalMetadata(db));}
 catch(e,s){await nuqatiLog('SERVICE_DB_OPEN_FAILED',e,s);rethrow;}
 const secure=FlutterSecureStorage();
 int? activeTrip;
 StreamSubscription<Position>? locationSub;
 Timer? flushTimer;
 int syncFailureCount=0;
 DateTime? nextSyncAttempt;

 DateTime? lastSaved;
 DateTime? lastCaptureFixReceivedAt;
 DateTime? lastMonitorFixReceivedAt;
 bool captureRestarting=false;
 bool monitorRestarting=false;
 // Event eligibility requires stable movement; altitude is not a reliable floor detector.
 DateTime? stableDrivingSince;
 DateTime? lastReliableMovementAt;
 Position? stableMovementAnchor;
 Position? previous;
 double? lastHeading;DateTime? lastHeadingAt;
 final Map<String, DateTime> lastCoachingEventAt = <String, DateTime>{};
 // Keep a short sequence of valid GPS *speed* readings for motion detection.
 // Unlike location/odometer sampling, do not reset this on a single poor fix.
 double? previousAlertSpeed;
 DateTime? previousAlertTime;
 DateTime? lastSafetyDiagnosticAt;
 double alertSpeedLimit=100, alertHarshAccel=3, alertHarshBrake=3;
 double alertCorneringMs2=3.5, aggressiveBrakeMs2=4.5, aggressiveAccelMs2=4.5;
 double excessiveSpeedMarginKmh=20; // App coaching only; independent of backend RAG.
 Map<String,dynamic> alertEnabled={'speeding':true,'harsh_acceleration':true,'harsh_braking':true,'harsh_cornering':true};
 List<Map<String,dynamic>> speedZones=[];
 final Set<String> zoneInside=<String>{};
 final Set<String> zoneKnown=<String>{};

 bool flushing=false;
 bool privacy=false;
 StreamSubscription<Position>? monitorSub;
 DateTime? movingSince, stationarySince;
 // Indoor GPS drift guard: only auto-start after sustained, spatially consistent travel.
 // All state stays inside the background location service; no home coordinates are stored.
 final List<Position> candidateMovement=<Position>[];
 const double autoStartMaxAccuracyM=35.0; // Auto-start monitoring; event validation remains <=20 m.
 const double autoStartMinSpeedKmh=7.0;
 const int autoStartMinimumSeconds=12;
 DateTime? lastMotionGateLog;
 Future<void> logMotionGate(String reason, Position p) async {
  final now=DateTime.now().toUtc();
  if(lastMotionGateLog!=null&&now.difference(lastMotionGateLog!).inSeconds<20)return;
  lastMotionGateLog=now;
  await nuqatiLog('MOTION_GATE reason=$reason speed_kmh=${(p.speed*3.6).toStringAsFixed(1)} accuracy_m=${p.accuracy.toStringAsFixed(1)} fix_age_s=${now.difference(p.timestamp.toUtc()).inSeconds} samples=${candidateMovement.length}');
 }

 const double autoStartMinDisplacementM=25.0;
 void resetMovementCandidate(){candidateMovement.clear();movingSince=null;}
 bool confirmsRealTravel(Position p){
  final speedKmh=p.speed.isFinite?p.speed*3.6:0.0;
  final time=p.timestamp.toUtc();
  if(!p.latitude.isFinite||!p.longitude.isFinite||
      !p.accuracy.isFinite||p.accuracy<=0||p.accuracy>autoStartMaxAccuracyM||
      !p.speed.isFinite||speedKmh<autoStartMinSpeedKmh||speedKmh>180||
      DateTime.now().toUtc().difference(time).inSeconds.abs()>10){
   unawaited(logMotionGate('INVALID_FIX_OR_SPEED',p));resetMovementCandidate();return false;
  }
  if(candidateMovement.isNotEmpty){
   final previous=candidateMovement.last;
   final gap=time.difference(previous.timestamp.toUtc()).inMilliseconds/1000;
   if(gap<=0||gap>10){resetMovementCandidate();}
  }
  candidateMovement.add(p);
  // Limit the amount of GPS data retained in memory to the confirmation window.
  while(candidateMovement.length>2 &&
    time.difference(candidateMovement.first.timestamp.toUtc()).inSeconds>30){
   candidateMovement.removeAt(0);
  }
  if(candidateMovement.length<3){unawaited(logMotionGate('WAITING_FOR_FIXES',p));return false;}
  final start=candidateMovement.first;
  final elapsed=time.difference(start.timestamp.toUtc()).inMilliseconds/1000;
  if(elapsed<autoStartMinimumSeconds){unawaited(logMotionGate('CONFIRMING_DURATION',p));return false;}
  final net=Geolocator.distanceBetween(start.latitude,start.longitude,p.latitude,p.longitude);
  if(net<autoStartMinDisplacementM){unawaited(logMotionGate('INSUFFICIENT_DISPLACEMENT',p));return false;}
  double path=0;int movingSegments=0;
  for(var i=1;i<candidateMovement.length;i++){
   final a=candidateMovement[i-1],b=candidateMovement[i];
   final step=Geolocator.distanceBetween(a.latitude,a.longitude,b.latitude,b.longitude);
   final dt=b.timestamp.toUtc().difference(a.timestamp.toUtc()).inMilliseconds/1000;
   if(dt<=0)return false;
   // Reject GPS teleporting that is inconsistent with reported driving speed.
   final plausibleMeters=((a.speed+b.speed)/2).clamp(0.0,50.0)*dt+15;
   if(step>plausibleMeters){resetMovementCandidate();return false;}
   path+=step;
   // With 1 Hz GPS, 7 m between successive fixes would reject normal
   // 7–25 km/h movement. Use a time-scaled displacement threshold while
   // retaining net travel, duration, speed, accuracy and jump protection.
   if(step>= (1.4*dt).clamp(1.5,7.0))movingSegments++;
  }
  // Indoor GPS drift usually wanders around the same spot, not along a path.
  if(movingSegments<2||path>net*1.8+12){unawaited(logMotionGate('INCONSISTENT_PATH',p));return false;}
  unawaited(nuqatiLog('MOTION_CONFIRMED'));return true;
 }
 bool autoBusy=false;
 Future<void> checkMaintenance() async {
  if(privacy)return;
  try {
   final access=await secure.read(key:'nuqati_driver_access_token');
   if(access==null||access.isEmpty)return;
   final response=await http.get(Uri.parse('$api/api/v1/mobile/maintenance-reminders'),headers:{'Authorization':'Bearer $access'}).timeout(const Duration(seconds:10));
   if(response.statusCode!=200)return;
   final data=jsonDecode(response.body) as Map;
   for(final item in (data['reminders'] as List? ?? [])){
    final reminder=Map<String,dynamic>.from(item as Map);
    final key='${reminder['cycle_key']}:${reminder['stage']}';
    final seen=await db.query('maintenance_notices',where:'notice_key = ?',whereArgs:[key],limit:1);
    if(seen.isNotEmpty)continue;
    final serviceName={'ENGINE_OIL':'Engine oil','SPARK_PLUGS':'Spark plugs','TRANSMISSION_OIL':'Gear oil','TYRES':'Tyres'}[reminder['service_type']]??'Maintenance';
    final stage=reminder['stage'] as String;
    final distance=(reminder['remaining_km'] as num).abs().round();
    final detail=stage=='DUE'?'Service due now':stage=='1000_OVERDUE'?'Overdue by $distance km':'$distance km remaining';
    final lang=await nuqatiLanguage();
    final localizedService=reminder['service_type']=='TYRES'?localizedAlert(lang,'Tyres','الإطارات','ٹائر'):serviceName;
    final localizedDetail=stage=='DUE'?localizedAlert(lang,'Service due now','الصيانة مستحقة الآن','سروس کا وقت ہو گیا ہے'):stage=='1000_OVERDUE'?localizedAlert(lang,'Service overdue','تأخرت الصيانة','سروس کی مدت گزر گئی'):localizedAlert(lang,'Maintenance reminder','تذكير بالصيانة','سروس کی یاد دہانی');
    await nuqatiAlerts.show(2500+(reminder['schedule_id'] as int)%1000,'$localizedService · ${reminder['plate_number']}','$localizedDetail · $detail',
      const NotificationDetails(android:AndroidNotificationDetails('nuqati_maintenance_v1','Vehicle maintenance reminders',importance:Importance.high,priority:Priority.high)));
    await db.insert('maintenance_notices',{'notice_key':key,'created_at':DateTime.now().toUtc().toIso8601String()},conflictAlgorithm:ConflictAlgorithm.ignore);
   }
  }catch(e,s){await nuqatiLog('MAINTENANCE_CHECK_FAILED',e,s);}
 }
 Future<void> showTripCompleted() async {
  try {
   final lang=await nuqatiLanguage();
   await nuqatiAlerts.show(2304,localizedAlert(lang,'Nuqati trip completed','اكتملت رحلة نقاطي','نقاطی کا سفر مکمل ہوا'),localizedAlert(lang,'Open Nuqati to review your driving score.','افتح نقاطي لمراجعة نتيجة قيادتك.','اپنا ڈرائیونگ اسکور دیکھنے کے لیے نقاطی کھولیں۔'),
    const NotificationDetails(android:AndroidNotificationDetails('nuqati_trip_updates_v1','Trip updates',importance:Importance.high,priority:Priority.high)));
  }catch(e,s){await nuqatiLog('TRIP_COMPLETED_ALERT_FAILED',e,s);}
 }
 Future<void> flush() async {
  if(flushing || (nextSyncAttempt!=null && DateTime.now().isBefore(nextSyncAttempt!)))return;
  flushing=true;
  try {
   final access=await secure.read(key:'nuqati_driver_access_token');
   if(access==null||access.isEmpty)return;
   final headers={'Content-Type':'application/json','Authorization':'Bearer $access'};
   await db.execute('CREATE TABLE IF NOT EXISTS safety_event_sync_errors (event_id TEXT PRIMARY KEY, status INTEGER NOT NULL, reason TEXT NOT NULL, recorded_at TEXT NOT NULL)');
   final trips=await db.query('local_trips',orderBy:'started_at ASC');
   for(final trip in trips){
    final localId=trip['local_id'] as int;
    int? remoteId=trip['remote_id'] as int?;
    if(remoteId==null){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/start'),headers:headers,body:jsonEncode({'client_trip_id':'trip_$localId','started_at':trip['started_at']})).timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300){await nuqatiLog('SYNC_HTTP_ERROR stage=trip_start status=${r.statusCode}');return;}
     final data=jsonDecode(r.body) as Map;
     remoteId=(data['trip_id'] as num).toInt();
     await db.update('local_trips',{'remote_id':remoteId},where:'local_id = ?',whereArgs:[localId]);
    }
    final rows=await db.query('gps_queue',where:'trip_id = ?',whereArgs:[localId],orderBy:'captured_at ASC',limit:100);
    bool failed=false;
    for(final row in rows){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/$remoteId/sample'),headers:headers,body:row['payload'] as String).timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300){await nuqatiLog('SYNC_HTTP_ERROR stage=gps_sample status=${r.statusCode}');failed=true;break;}
     final data=jsonDecode(r.body);
     if(data is! Map||data['accepted']!=true){failed=true;break;}
     await db.delete('gps_queue',where:'sample_id = ?',whereArgs:[row['sample_id']]);
    }
    if(failed)break;
    // Sync locally recorded safety events before completing the remote trip.
    // Keep each row until the server acknowledges its stable event_id.
    await db.execute('CREATE TABLE IF NOT EXISTS safety_event_receipts (event_id TEXT PRIMARY KEY)');
    final pendingEvents=await db.rawQuery('SELECT e.* FROM safety_live_events e LEFT JOIN safety_event_receipts r ON r.event_id=e.event_id LEFT JOIN safety_event_sync_errors x ON x.event_id=e.event_id WHERE e.trip_id=? AND r.event_id IS NULL AND x.event_id IS NULL ORDER BY e.recorded_at ASC LIMIT 500',[localId]);
    for(final event in pendingEvents){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/$remoteId/safety-event'),headers:headers,
       body:jsonEncode({'event_id':event['event_id'],'event_type':event['event_type'],
        'recorded_at':event['recorded_at'],'value':event['value']})).timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300){
      final reason=r.body.length>350?r.body.substring(0,350):r.body;
      await nuqatiLog('SAFETY_EVENT_SYNC_REJECTED status=${r.statusCode} type=${event['event_type']} event_id=${event['event_id']} reason=$reason');
      if(r.statusCode==400||r.statusCode==404||r.statusCode==409||r.statusCode==422){
       // A permanent validation error must not repeatedly block the queue.
       // Retain the original event locally for audit and later repair.
       await db.insert('safety_event_sync_errors',{'event_id':event['event_id'],'status':r.statusCode,'reason':reason,'recorded_at':DateTime.now().toUtc().toIso8601String()},conflictAlgorithm:ConflictAlgorithm.replace);
       continue;
      }
      failed=true;break;
     }
     final ack=jsonDecode(r.body);
     if(ack is! Map||ack['accepted']!=true){failed=true;break;}
     // Preserve on-device counts, but mark uploaded records to avoid repeated sends.
     await db.insert('safety_event_receipts',{'event_id':event['event_id']},conflictAlgorithm:ConflictAlgorithm.ignore);
    }
    if(failed)break;
    final unacked=Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM safety_live_events e LEFT JOIN safety_event_receipts r ON r.event_id=e.event_id LEFT JOIN safety_event_sync_errors x ON x.event_id=e.event_id WHERE e.trip_id=? AND r.event_id IS NULL AND x.event_id IS NULL',[localId]))??0;
    if(unacked>0)break;
    final remaining=Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM gps_queue WHERE trip_id = ?',[localId]))??0;
    if(remaining>0)break;
    if(trip['ended_at']!=null){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/$remoteId/finish'),headers:headers,body:jsonEncode({'ended_at':trip['ended_at']})).timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300){await nuqatiLog('SYNC_HTTP_ERROR stage=trip_finish status=${r.statusCode}');return;}
     await db.delete('local_trips',where:'local_id = ?',whereArgs:[localId]);await secure.delete(key:'nuqati_live_distance_$localId');service.invoke('officialTripSynced',{'trip_id':remoteId});
     // Keep recent live-coaching history briefly for UI; older acknowledged trips are pruned.
     unawaited(pruneAcknowledgedLocalMetadata(db));
    }
   }
   syncFailureCount=0;nextSyncAttempt=null;
  }catch(e,s){
   syncFailureCount=math.min(syncFailureCount+1,8);
   final delay=math.min(300,15*(1<<math.min(syncFailureCount-1,5)))+math.Random().nextInt(8);
   nextSyncAttempt=DateTime.now().add(Duration(seconds:delay));
   await nuqatiLog('SYNC_DEFERRED retry_in_s=$delay failure_count=$syncFailureCount',e,s);
  }
  finally{flushing=false;}
 }
 double capturedTripKm=0; Position? distanceFix; DateTime? distanceFixAt;
 DateTime? lastDistancePersistedAt,lastDistancePublishedAt;
 void publishLiveDistance(){if(activeTrip!=null){lastDistancePublishedAt=DateTime.now().toUtc();service.invoke('liveDistance',{'trip_id':activeTrip,'km':capturedTripKm});}}
 service.on('liveDistanceRequest').listen((_)=>publishLiveDistance());
 Future<void> stopCapture() async {
  await locationSub?.cancel();locationSub=null;lastCaptureFixReceivedAt=null;stableDrivingSince=null;lastReliableMovementAt=null;stableMovementAnchor=null;
  // Commit the last distance estimate before clearing capture state.
  if(activeTrip!=null){try{await secure.write(key:'nuqati_live_distance_$activeTrip',value:capturedTripKm.toString());}catch(e){await nuqatiLog('DISTANCE_CACHE_SAVE_FAILED',e);}}
  flushTimer?.cancel();flushTimer=null;
  activeTrip=null;capturedTripKm=0;distanceFix=null;distanceFixAt=null;lastDistancePersistedAt=null;lastDistancePublishedAt=null;lastSaved=null;previous=null;lastHeading=null;lastHeadingAt=null;previousAlertSpeed=null;previousAlertTime=null;lastCoachingEventAt.clear();
 }
 Future<void> startCapture(int id) async {
  if(activeTrip==id && locationSub!=null)return;
  await nuqatiLog('START_CAPTURE trip=$id');
  await stopCapture();zoneInside.clear();zoneKnown.clear();activeTrip=id;try{capturedTripKm=double.tryParse(await secure.read(key:'nuqati_live_distance_$id')??'')??0;}catch(_){capturedTripKm=0;}lastDistancePersistedAt=DateTime.now().toUtc();publishLiveDistance();
  try {
   final raw=await secure.read(key:'nuqati_driving_policy');
   if(raw!=null){
    final policy=Map<String,dynamic>.from(jsonDecode(raw) as Map);
    final ownCompany=await secure.read(key:'nuqati_driver_company_id');
    if(ownCompany==null||policy['company_id']?.toString()!=ownCompany)throw StateError('Company policy identity does not match');
    alertSpeedLimit=(policy['speeding_kmh'] as num?)?.toDouble()??100;
    alertHarshAccel=(policy['harsh_accel_ms2'] as num?)?.toDouble()??3;
    alertHarshBrake=(policy['harsh_brake_ms2'] as num?)?.toDouble()??3;
    excessiveSpeedMarginKmh=(policy['excessive_speed_margin_kmh'] as num?)?.toDouble()??20;
    alertCorneringMs2=((policy['phase4'] as Map?)?['cornering_ms2'] as num?)?.toDouble()??3.5;
    aggressiveBrakeMs2=(policy['aggressive_brake_ms2'] as num?)?.toDouble()??alertHarshBrake*1.5;
    aggressiveAccelMs2=(policy['aggressive_accel_ms2'] as num?)?.toDouble()??alertHarshAccel*1.5;
    if(policy['enabled'] is Map)alertEnabled=Map<String,dynamic>.from(policy['enabled'] as Map);
    final rawZones=policy['geofence_speed_zones'];
    speedZones=rawZones is List?rawZones.whereType<Map>().map((z)=>Map<String,dynamic>.from(z)).toList():[];
    final version=policy['policy_version']?.toString();
    if(version!=null)service.invoke('policyApplied',{'version':version,'applied':true});
    await nuqatiLog('COMPANY_POLICY_APPLIED version=$version');
   }
  }catch(e,s){await nuqatiLog('ALERT_POLICY_LOAD_FAILED',e,s);}
  if(!await trackingPermissionsReady()){await nuqatiLog('CAPTURE_BLOCKED_LOCATION_PERMISSION trip=$id');activeTrip=null;service.invoke('trackingError',{'reason':'location_permission'});return;}
  try{await initializeViolationAlerts(requestPermission:false);}catch(e){await nuqatiLog('NOTIFICATION_INIT_FAILED_TRACKING_CONTINUES',e);}
  if(service is AndroidServiceInstance){
   try{service.setAsForegroundService();service.setForegroundNotificationInfo(title:'Nuqati trip #$id',content:'Recording GPS and syncing offline samples');}
   catch(e){await nuqatiLog('TRACKING_NOTIFICATION_FAILED_GPS_CONTINUES',e);}
  }
  locationSub=Geolocator.getPositionStream(locationSettings:AndroidSettings(
    accuracy:LocationAccuracy.bestForNavigation,distanceFilter:0,
    intervalDuration:Duration(seconds:1),
  )).listen((fix) async {
    if(activeTrip!=id)return;
    lastCaptureFixReceivedAt=DateTime.now().toUtc();
    if(!fix.accuracy.isFinite||fix.accuracy<=0||fix.accuracy>50)return;
    final at=fix.timestamp.toUtc();
    if(lastSaved!=null && at.difference(lastSaved!).inMilliseconds<700)return;
    if(DateTime.now().toUtc().difference(at).inSeconds>15)return;
    double accel=0;
    if(previous!=null&&lastSaved!=null){
      final dt=at.difference(lastSaved!).inMilliseconds/1000;
      if(dt>0)accel=((fix.speed-previous!.speed)/dt).clamp(-30.0,30.0).toDouble();
    }
    // Live display distance only: never commit mileage to vehicle DB here.
    // Require trustworthy GPS, plausible speed, and continuous timestamp sequence.
    if(fix.accuracy.isFinite&&fix.accuracy<=20&&fix.speed.isFinite&&fix.speed>=0){
     if(distanceFix!=null&&distanceFixAt!=null){
      final seconds=at.difference(distanceFixAt!).inMilliseconds/1000;
      if(seconds>0&&seconds<=90){
       final metres=Geolocator.distanceBetween(distanceFix!.latitude,distanceFix!.longitude,fix.latitude,fix.longitude);
       final plausible=(fix.speed+distanceFix!.speed).clamp(0.0,100.0)/2*seconds+15;
       if(fix.speed>=2.0&&distanceFix!.speed>=2.0&&metres>=5&&metres<=plausible&&metres<=seconds*50){
        capturedTripKm+=metres/1000;
        // Keystore writes are expensive. Limit to ~once/10s; always save on trip stop.
        if(lastDistancePersistedAt==null||at.difference(lastDistancePersistedAt!).inSeconds>=10){
         lastDistancePersistedAt=at;
         unawaited(secure.write(key:'nuqati_live_distance_$id',value:capturedTripKm.toString()).catchError((Object e){nuqatiLog('DISTANCE_CACHE_SAVE_FAILED',e);}));
        }
        if(lastDistancePublishedAt==null||at.difference(lastDistancePublishedAt!).inSeconds>=3)publishLiveDistance();
       }
      }
     }
     distanceFix=fix;distanceFixAt=at;
    }else{distanceFix=null;distanceFixAt=null;}
    final sampleId='${id}_${at.microsecondsSinceEpoch}';
    final payload=jsonEncode({
      'sample_id':sampleId,'captured_at':at.toIso8601String(),
      'latitude':fix.latitude,'longitude':fix.longitude,'accuracy_m':fix.accuracy,
      'speed_kmh':(fix.speed.isFinite&&fix.speed>0?fix.speed*3.6:0.0).clamp(0.0,350.0),
      'acceleration_ms2':accel,'gps_age_seconds':0.0,
    });
    try{
      await db.insert('gps_queue',{'sample_id':sampleId,'trip_id':id,
        'captured_at':at.toIso8601String(),'payload':payload},
        conflictAlgorithm:ConflictAlgorithm.ignore);
      lastSaved=at;previous=fix;
      final speed=fix.speed.isFinite&&fix.speed>0?fix.speed*3.6:0.0;
      // Reject stationary indoor GPS jumps before evaluating ANY safety event.
      // Altitude alone cannot identify a first/second floor or ground elevation.
      final reliableFix=fix.accuracy<=15 && fix.speedAccuracy.isFinite &&
          fix.speedAccuracy>=0 && fix.speedAccuracy<=2.5 && speed<=180;
      if(!reliableFix){
        stableDrivingSince=null;stableMovementAnchor=null;
      }else if(speed>=7){
        stableDrivingSince??=at;
        stableMovementAnchor??=fix;
        final travelled=Geolocator.distanceBetween(stableMovementAnchor!.latitude,
            stableMovementAnchor!.longitude,fix.latitude,fix.longitude);
        if(travelled>=30)lastReliableMovementAt=at;
      }else if(lastReliableMovementAt==null ||
          at.difference(lastReliableMovementAt!).inSeconds>20){
        stableDrivingSince=null;stableMovementAnchor=null;
      }
      final confirmedDriving=reliableFix && stableDrivingSince!=null &&
          at.difference(stableDrivingSince!).inSeconds>=15 &&
          lastReliableMovementAt!=null &&
          at.difference(lastReliableMovementAt!).inSeconds<=20;
      // Compare consecutive captured GPS speeds using the original 1–12 second window.
      final dt=previousAlertTime==null?0.0:
          at.difference(previousAlertTime!).inMilliseconds/1000;
      final validMotionPair=dt>=1&&dt<=12&&previousAlertSpeed!=null;
      final accelKmhS=validMotionPair?(speed-previousAlertSpeed!)/dt:0.0;
      previousAlertSpeed=speed;
      previousAlertTime=at;
      // Periodic, location-free diagnostics distinguish GPS quality, thresholds and no detections.
      if(lastSafetyDiagnosticAt==null||at.difference(lastSafetyDiagnosticAt!).inSeconds>=15){
        lastSafetyDiagnosticAt=at;
        unawaited(nuqatiLog('SAFETY_MONITOR speed_kmh=${speed.toStringAsFixed(1)} gps_accuracy_m=${fix.accuracy.toStringAsFixed(1)} gps_speed_accuracy_ms=${fix.speedAccuracy.toStringAsFixed(1)} motion_pair=$validMotionPair window_s=${dt.toStringAsFixed(2)} accel_kmh_s=${accelKmhS.toStringAsFixed(2)} brake_threshold_kmh_s=${(alertHarshBrake*3.6).toStringAsFixed(2)} acceleration_threshold_kmh_s=${(alertHarshAccel*3.6).toStringAsFixed(2)} enabled_brake=${alertEnabled['harsh_braking']} enabled_accel=${alertEnabled['harsh_acceleration']}'));
      }
      // GPS heading is noisy at low speed; require >=20 km/h, accurate fix,
      // 1-5 seconds between fixes, and >=18 degrees/second heading change.
      bool cornering=false;
      double lateralCornering=0;
      if(speed>=20&&fix.heading.isFinite&&fix.heading>=0&&fix.accuracy<=20){
       if(lastHeading!=null&&lastHeadingAt!=null){
        final seconds=at.difference(lastHeadingAt!).inMilliseconds/1000;
        final diff=((fix.heading-lastHeading!+540)%360)-180;
        lateralCornering=(speed/3.6)*(diff.abs()*math.pi/180)/seconds.clamp(0.001,1000);
        cornering=seconds>=0.7&&seconds<=5&&lateralCornering>=alertCorneringMs2;
       }
       lastHeading=fix.heading;lastHeadingAt=at;
      }else{lastHeading=null;lastHeadingAt=null;}
      // Zone-entry speed advisory, independently of normal violation scoring.
      // Two accurate consecutive fixes are required before interpreting a boundary crossing.
      if(fix.accuracy.isFinite && fix.accuracy>0 && fix.accuracy<=20 &&
         fix.speed.isFinite && fix.speed>=0 && speed<=200){
        for(final zone in speedZones){
          try{
            final zoneId=zone['id']?.toString()??'';
            final lat=(zone['latitude'] as num).toDouble(), lon=(zone['longitude'] as num).toDouble();
            final radius=(zone['radius_m'] as num).toDouble();
            final limit=(zone['speed_limit_kmh'] as num).toDouble();
            final inside=Geolocator.distanceBetween(fix.latitude,fix.longitude,lat,lon)<=radius;
            if(zoneKnown.contains(zoneId) && !zoneInside.contains(zoneId) && inside && speed>limit){
              final lang=await nuqatiLanguage();
              final name=zone['name']?.toString()??'Geofence';
              final message=localizedAlert(lang,
                'Entering $name. Speed limit ${limit.round()} km/h. Reduce your speed.',
                'دخول منطقة $name. الحد ${limit.round()} كم/س. يرجى تخفيف السرعة.',
                '$name میں داخل ہو رہے ہیں۔ رفتار کی حد ${limit.round()} کلومیٹر فی گھنٹہ ہے۔ رفتار کم کریں۔');
              await showViolationAlert(message,2404);
              await nuqatiLog('GEOFENCE_SPEED_ENTRY_ALERT zone=$zoneId speed=$speed limit=$limit');
            }
            zoneKnown.add(zoneId);
            if(inside){zoneInside.add(zoneId);}else{zoneInside.remove(zoneId);}
          }catch(e){await nuqatiLog('GEOFENCE_ZONE_EVALUATION_FAILED',e);}
        }
      }
      // Evaluate each event type independently; speeding must not suppress braking.
      // The company's thresholds remain authoritative for on-device coaching.
      final brakeCandidate=confirmedDriving&&validMotionPair&&accelKmhS<0&&-accelKmhS+1e-9>=alertHarshBrake*3.6;
      final accelCandidate=confirmedDriving&&validMotionPair&&accelKmhS>0&&accelKmhS+1e-9>=alertHarshAccel*3.6;
      final speedCandidate=confirmedDriving&&fix.accuracy.isFinite&&fix.accuracy>0&&fix.accuracy<=25&&speed>alertSpeedLimit;
      // Severe event is classified INSTEAD of its normal type to avoid two deductions.
      final brakeKind=brakeCandidate?(accelKmhS < -aggressiveBrakeMs2*3.6?'excessive_harsh_braking':'harsh_braking'):null;
      final accelKind=accelCandidate?(accelKmhS > aggressiveAccelMs2*3.6?'excessive_harsh_acceleration':'harsh_acceleration'):null;
      final speedKind=speedCandidate?(speed>alertSpeedLimit+excessiveSpeedMarginKmh?'excessive_speeding':'speeding'):null;
      final List<String> candidates=<String>[
        if(alertEnabled['harsh_braking']!=false&&brakeKind!=null)brakeKind,
        if(alertEnabled['harsh_acceleration']!=false&&accelKind!=null)accelKind,
        if(confirmedDriving&&alertEnabled['harsh_cornering']!=false&&cornering)'harsh_cornering',
        if(alertEnabled['speeding']!=false&&speedKind!=null)speedKind,
      ];
      final qualifying=<String>[];
      for(final candidate in candidates){
        final cooldownKey=candidate.replaceFirst('excessive_','');
        final last=lastCoachingEventAt[cooldownKey];
        if(last==null||at.difference(last).inMilliseconds>=12000){
          qualifying.add(candidate);
        }
      }
      for(final kind in qualifying){
        final lang=await nuqatiLanguage();
        final message=switch(kind){
          'excessive_harsh_braking'=>localizedAlert(lang,'Excessive harsh braking!','فرملة شديدة جداً!','انتہائی سخت بریک!'),
          'excessive_harsh_acceleration'=>localizedAlert(lang,'Excessive harsh acceleration!','تسارع شديد جداً!','انتہائی تیز ایکسلریشن!'),
          'excessive_speeding'=>localizedAlert(lang,'Excessive speeding! Slow down.','تجاوز سرعة شديد! خفف سرعتك.','بہت زیادہ رفتار! رفتار کم کریں۔'),
          'harsh_braking'=>localizedAlert(lang,'Harsh braking detected. Drive safely.','تم رصد فرملة حادة. قد بحذر.','اچانک بریک لگائی گئی۔ احتیاط سے چلائیں۔'),
          'harsh_acceleration'=>localizedAlert(lang,'Harsh acceleration detected.','تم رصد تسارع حاد.','تیز ایکسلریشن کا پتہ چلا۔'),
          'harsh_cornering'=>localizedAlert(lang,'Harsh cornering detected. Slow down.','تم رصد انعطاف حاد. خفف السرعة.','تیز موڑ کا پتہ چلا۔'),
          _=>localizedAlert(lang,'Speeding! Reduce your speed.','تجاوز السرعة! خفف سرعتك.','رفتار زیادہ ہے! رفتار کم کریں۔'),
        };
        final eventId='${id}_${at.microsecondsSinceEpoch}_$kind';
        // Count only if the local event is durably stored. Official backend
        // Flexible RAG scoring is intentionally unaffected.
        try {
          await db.insert('safety_live_events',{'event_id':eventId,'trip_id':id,'event_type':kind,'recorded_at':at.toIso8601String(),
            'value':kind.contains('braking')?-accelKmhS/3.6:kind.contains('acceleration')?accelKmhS/3.6:kind=='harsh_cornering'?lateralCornering:speed},conflictAlgorithm:ConflictAlgorithm.ignore);
          lastCoachingEventAt[kind.replaceFirst('excessive_','')]=at;
          service.invoke('driverSafetyEvent',{'trip_id':id,'type':kind,'event_id':eventId,'at':at.toIso8601String()});
          // Separate notification IDs prevent a subsequent speeding alert from
          // replacing a braking/acceleration notification in Android's tray.
          final notificationId=switch(kind){
            'harsh_braking'||'excessive_harsh_braking'=>2305,
            'harsh_acceleration'||'excessive_harsh_acceleration'=>2306,
            'harsh_cornering'=>2307,
            _=>2302,
          };
          unawaited(showViolationAlert(message,notificationId));
          await nuqatiLog('LIVE_COACHING_EVENT_SAVED type=$kind trip=$id');
        }catch(e,s){await nuqatiLog('LOCAL_SAFETY_EVENT_SAVE_FAILED',e,s);}
      }
      if(lastSafetyDiagnosticAt!=null&&at==lastSafetyDiagnosticAt){
        // This line deliberately never logs coordinates or account credentials.
        unawaited(nuqatiLog('SAFETY_DECISION motion_pair=$validMotionPair braking=$brakeCandidate acceleration=$accelCandidate speed=$speedCandidate candidates=${candidates.join(',')} qualifying=${qualifying.join(',')}')); 
      }
    }catch(e,s){await nuqatiLog('GPS_DB_INSERT_FAILED',e,s);}
  },onError:(Object e,StackTrace st) async {
    await nuqatiLog('LOCATION_STREAM_ERROR',e,st);
    // Never close the trip or discard its offline queue on a provider error.
    await locationSub?.cancel();locationSub=null;lastCaptureFixReceivedAt=null;
    service.invoke('trackingError',{'reason':'location_stream_recovering'});
  });
  // One 30-second upload cycle per active trip; individual GPS points are still durable at 1 Hz.
  flushTimer=Timer.periodic(const Duration(seconds:30),(_) => flush());
  unawaited(flush());
 }
 Future<void> notifyLocalTripPoints(int id) async {
  try {
   final row=await db.query('local_score_history',where:'trip_id = ?',whereArgs:[id],limit:1);
   if(row.isEmpty)return;
   final points=(row.first['points'] as num).toInt();
   final older=await db.query('local_score_history',where:'trip_id != ? AND ended_at < ?',whereArgs:[id,row.first['ended_at']],orderBy:'ended_at DESC',limit:1);
   final previous=older.isEmpty?null:(older.first['points'] as num).toInt();
   final lang=await nuqatiLanguage();
   await nuqatiAlerts.show(2310,localizedAlert(lang,'Nuqati trip points','نقاط رحلة نقاطي','نقاطی ٹرپ پوائنٹس'),nuqatiLocalProgressMessage(points,previous,lang),const NotificationDetails(android:AndroidNotificationDetails('nuqati_trip_updates_v1','Trip updates',importance:Importance.high,priority:Priority.high)));
  }catch(e){await nuqatiLog('LOCAL_TRIP_NOTIFICATION_FAILED',e);}
 }
 Future<void> finishAutomatically() async {
  if(autoBusy||activeTrip==null||privacy)return;
  autoBusy=true;
  try {
   final id=activeTrip!;
   await db.update('local_trips',{'ended_at':DateTime.now().toUtc().toIso8601String()},where:'local_id = ? AND ended_at IS NULL',whereArgs:[id]);
   await stopCapture();
   final localSummary=await nuqatiFinalizeLocalPoints(db,id,DateTime.now());
   service.invoke('localTripEnded',{'trip_id':id,...localSummary});
   unawaited(notifyLocalTripPoints(id));
   service.invoke('tripState',{'trip_id':null});
   await showTripCompleted();
   unawaited(flush());
  }catch(e,s){await nuqatiLog('AUTO_FINISH_FAILED',e,s);}
  finally{autoBusy=false;stationarySince=null;resetMovementCandidate();}
 }
 Future<void> beginAutomatically() async {
  if(autoBusy||activeTrip!=null||privacy)return;
  if(!await trackingPermissionsReady()){await nuqatiLog('AUTO_START_BLOCKED_PERMISSION');return;}
  autoBusy=true;
  try {
   final existing=await db.query('local_trips',where:'ended_at IS NULL',limit:1);
   final id=existing.isNotEmpty?existing.first['local_id'] as int:DateTime.now().microsecondsSinceEpoch;
   if(existing.isEmpty)await db.insert('local_trips',{'local_id':id,'remote_id':null,'started_at':DateTime.now().toUtc().toIso8601String(),'ended_at':null});
   await nuqatiLog('AUTO_TRIP_START_CONFIRMED');
   await startCapture(id);
   service.invoke('tripState',{'trip_id':id});
  }catch(e,s){await nuqatiLog('AUTO_START_FAILED',e,s);}
  finally{autoBusy=false;resetMovementCandidate();stationarySince=null;}
 }
 Future<void> beginMonitoring() async {
  if(privacy||monitorSub!=null)return;
  if(!await trackingPermissionsReady()){await nuqatiLog('MONITOR_BLOCKED_LOCATION_PERMISSION');service.invoke('trackingError',{'reason':'location_permission'});return;}
  try{await initializeViolationAlerts(requestPermission:false);}catch(e){await nuqatiLog('NOTIFICATION_INIT_FAILED_MONITOR_CONTINUES',e);}
  final android=nuqatiAlerts.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
  try{await android?.createNotificationChannel(const AndroidNotificationChannel('nuqati_trip_updates_v1','Trip updates',importance:Importance.high));}catch(e){await nuqatiLog('TRIP_CHANNEL_INIT_FAILED',e);}
  try{await android?.createNotificationChannel(const AndroidNotificationChannel('nuqati_maintenance_v1','Vehicle maintenance reminders',importance:Importance.high));}catch(e){await nuqatiLog('MAINTENANCE_CHANNEL_INIT_FAILED',e);}
  if(service is AndroidServiceInstance){try{service.setAsForegroundService();service.setForegroundNotificationInfo(title:'Nuqati movement monitoring',content:'Automatic trips enabled · Privacy Mode OFF');}catch(e){await nuqatiLog('MONITOR_NOTIFICATION_FAILED_GPS_CONTINUES',e);}}
  await nuqatiLog('MONITOR_STREAM_STARTING');
  lastMonitorFixReceivedAt=DateTime.now().toUtc();
  monitorSub=Geolocator.getPositionStream(locationSettings:AndroidSettings(
    accuracy:LocationAccuracy.bestForNavigation,distanceFilter:0,
    // Trip capture still runs at 1 Hz. This separate auto-start/stop watcher needs fewer fixes.
    intervalDuration:const Duration(seconds:4),
  )).listen((fix) {
   lastMonitorFixReceivedAt=DateTime.now().toUtc();
   if(privacy||autoBusy)return;
   final now=DateTime.now().toUtc();
   if(activeTrip==null){
    stationarySince=null;
    if(confirmsRealTravel(fix)){
     resetMovementCandidate();
     unawaited(beginAutomatically());
    }
   }else{
    resetMovementCandidate();
    if(!fix.accuracy.isFinite||fix.accuracy>35||
       now.difference(fix.timestamp.toUtc()).inSeconds.abs()>15)return;
    final speed=fix.speed.isFinite?fix.speed*3.6:0.0;
    if(speed<5){
     stationarySince??=now;
     final elapsed=now.difference(stationarySince!).inSeconds;
     service.invoke('tripCountdown',{'remaining':(180-elapsed).clamp(0,180)});
     if(elapsed>=180)unawaited(finishAutomatically());
    }else{stationarySince=null;service.invoke('tripCountdown',{'remaining':null});}
   }
  },onError:(Object e,StackTrace st) async {
   await nuqatiLog('MONITOR_ERROR',e,st);await monitorSub?.cancel();monitorSub=null;lastMonitorFixReceivedAt=null;
   service.invoke('trackingError',{'reason':'location_stream'});
   // Recover transient provider failures without requiring the driver to reopen UI.
   await Future<void>.delayed(const Duration(seconds:15));
   if(!privacy && monitorSub==null)await beginMonitoring();
  });
 }
 Future<void> enterPrivacy() async {
  privacy=true;
  await monitorSub?.cancel();monitorSub=null;
  resetMovementCandidate();stationarySince=null;
  // Privacy stops GPS immediately, even if an active trip has not yet finished.
  if(activeTrip!=null){final id=activeTrip!;await db.update('local_trips',{'ended_at':DateTime.now().toUtc().toIso8601String()},where:'local_id = ? AND ended_at IS NULL',whereArgs:[id]);await stopCapture();}
  service.invoke('tripState',{'trip_id':null});
  unawaited(flush());
  service.stopSelf();
 }
 service.on('privacyOn').listen((_) => enterPrivacy());
 service.on('monitorOn').listen((_) async {if(!privacy)await beginMonitoring();});
 service.on('startTrip').listen((event) async {
  final id=(event?['trip_id'] as num?)?.toInt();
  if(id!=null)await startCapture(id);
 });
 service.on('stopTrip').listen((_) async {
  final endedTrip=activeTrip;
  await stopCapture();
  if(endedTrip!=null){
   try{final summary=await nuqatiFinalizeLocalPoints(db,endedTrip,DateTime.now());service.invoke('localTripEnded',{'trip_id':endedTrip,...summary});unawaited(notifyLocalTripPoints(endedTrip));}catch(e){await nuqatiLog('LOCAL_TRIP_SCORE_FINALIZE_FAILED',e);}
  }
  unawaited(flush());await beginMonitoring();
 });
 service.on('policyApply').listen((payload) async {
  try{
   final version=payload?['version']?.toString();
   final raw=await secure.read(key:'nuqati_driving_policy');
   if(raw==null)throw StateError('Policy not stored');
   final policy=Map<String,dynamic>.from(jsonDecode(raw) as Map);
   final ownCompany=await secure.read(key:'nuqati_driver_company_id');
   if(ownCompany==null||policy['company_id']?.toString()!=ownCompany)throw StateError('Company policy mismatch');
   if(version==null||policy['policy_version']!=version)throw StateError('Policy version mismatch');
   alertSpeedLimit=(policy['speeding_kmh'] as num?)?.toDouble()??100;
   alertHarshAccel=(policy['harsh_accel_ms2'] as num?)?.toDouble()??3;
   alertHarshBrake=(policy['harsh_brake_ms2'] as num?)?.toDouble()??3;
   excessiveSpeedMarginKmh=(policy['excessive_speed_margin_kmh'] as num?)?.toDouble()??20;
    alertCorneringMs2=((policy['phase4'] as Map?)?['cornering_ms2'] as num?)?.toDouble()??3.5;
    aggressiveBrakeMs2=(policy['aggressive_brake_ms2'] as num?)?.toDouble()??alertHarshBrake*1.5;
    aggressiveAccelMs2=(policy['aggressive_accel_ms2'] as num?)?.toDouble()??alertHarshAccel*1.5;
   if(policy['enabled'] is Map)alertEnabled=Map<String,dynamic>.from(policy['enabled'] as Map);
   final zones=policy['geofence_speed_zones'];
   speedZones=zones is List?zones.whereType<Map>().map((z)=>Map<String,dynamic>.from(z)).toList():[];
   zoneInside.clear();zoneKnown.clear();
   service.invoke('policyApplied',{'version':version,'applied':true});
   await nuqatiLog('COMPANY_POLICY_APPLIED version=$version');
  }catch(e){await nuqatiLog('COMPANY_POLICY_APPLY_FAILED',e);service.invoke('policyApplied',{'applied':false});}
 });
 service.on('syncNow').listen((_) => flush());
 // Keep the offline queue moving after connectivity returns, even after Stop.
 Future<void> localDailyPointsAtNine() async {
  try {
   final now=DateTime.now();if(now.hour<21)return;
   final today='${now.year.toString().padLeft(4,'0')}-${now.month.toString().padLeft(2,'0')}-${now.day.toString().padLeft(2,'0')}';
   final sent=await db.query('local_daily_score_notices',where:'local_day = ?',whereArgs:[today],limit:1);
   if(sent.isNotEmpty)return;
   final records=await db.query('local_score_history');
   final scores=records.where((r){final ended=DateTime.tryParse(r['ended_at'] as String)?.toLocal();return ended!=null&&ended.year==now.year&&ended.month==now.month&&ended.day==now.day;}).toList();
   if(scores.isEmpty)return;
   final average=scores.fold<double>(0,(sum,r)=>sum+(r['points'] as num).toDouble())/scores.length;
   final lang=await nuqatiLanguage();
   final message=localizedAlert(lang,'Today: ${scores.length} trips · Average ${average.toStringAsFixed(1)}/100 points. Keep driving safely.', 'اليوم: ${scores.length} رحلة · متوسط ${average.toStringAsFixed(1)} من ١٠٠ نقطة. واصل القيادة الآمنة.', 'آج: ${scores.length} ٹرپس · اوسط ${average.toStringAsFixed(1)}/100 پوائنٹس۔');
   await nuqatiAlerts.show(2311,localizedAlert(lang,'Nuqati daily driving points','نقاط القيادة اليومية','نقاطی روزانہ پوائنٹس'),message,const NotificationDetails(android:AndroidNotificationDetails('nuqati_trip_updates_v1','Trip updates',importance:Importance.high)));
   await db.insert('local_daily_score_notices',{'local_day':today,'sent_at':now.toUtc().toIso8601String()},conflictAlgorithm:ConflictAlgorithm.ignore);
  }catch(e){await nuqatiLog('DAILY_LOCAL_POINTS_FAILED',e);}
 }
 Timer.periodic(const Duration(minutes:1),(_){if(!privacy)unawaited(localDailyPointsAtNine());});
 Timer.periodic(const Duration(seconds:60),(_) => flush());
 // Background heartbeat: the website can distinguish screen state from GPS health.
 // Native Activity writes screen transitions to an app-private file; if the Activity
 // has been destroyed, the last screen state may be stale and is labelled unknown.
 Future<void> sendTrackingHeartbeat() async {
   try {
     final token=await secure.read(key:'nuqati_driver_access_token');
     if(token==null||token.isEmpty||privacy)return;
     String screen='unknown';
     final screenFile=File(path.join(await getDatabasesPath(),'nuqati_screen_state.json'));
     if(await screenFile.exists()){
       final state=jsonDecode(await screenFile.readAsString()) as Map<String,dynamic>;
       final value=state['state']?.toString();
       if(value=='locked'||value=='unlocked')screen=value!;
     }
     final now=DateTime.now().toUtc();
     final last=lastCaptureFixReceivedAt??lastMonitorFixReceivedAt;
     final age=last==null?null:now.difference(last).inSeconds;
     final response=await http.post(Uri.parse('$api/api/v1/mobile/tracking-heartbeat'),
       headers:{'Authorization':'Bearer $token','Content-Type':'application/json'},
       body:jsonEncode({'screen_state':screen,'trip_active':activeTrip!=null,
         'gps_fix_age_s':age,'captured_at':now.toIso8601String()}))
       .timeout(const Duration(seconds:12));
     if(response.statusCode<200||response.statusCode>=300){
       await nuqatiLog('TRACKING_HEARTBEAT_REJECTED status=${response.statusCode}');
     }
   }catch(e){await nuqatiLog('TRACKING_HEARTBEAT_FAILED',e);}
 }
 Timer.periodic(const Duration(seconds:30),(_) => unawaited(sendTrackingHeartbeat()));
 unawaited(sendTrackingHeartbeat());
 Timer.periodic(const Duration(seconds:60),(_) => unawaited(nuqatiUploadDiagnostics()));
 unawaited(nuqatiUploadDiagnostics());
 Timer.periodic(const Duration(minutes:2),(_) => checkMaintenance());
 Timer.periodic(const Duration(seconds:45),(_) async {
   if(privacy||monitorRestarting)return;
   final stale=lastMonitorFixReceivedAt!=null &&
       DateTime.now().toUtc().difference(lastMonitorFixReceivedAt!).inSeconds>60;
   if(monitorSub==null||stale){
     monitorRestarting=true;
     try{
       if(stale){await nuqatiLog('GPS_MONITOR_STALE_FIX');await monitorSub?.cancel();monitorSub=null;}
       if(await trackingPermissionsReady())await beginMonitoring();
     }catch(e){await nuqatiLog('GPS_MONITOR_RECOVERY_FAILED',e);}
     finally{monitorRestarting=false;}
   }
 });
 Timer.periodic(const Duration(seconds:20),(_) async {
   if(privacy||autoBusy||captureRestarting)return;
   final stale=lastCaptureFixReceivedAt!=null &&
       DateTime.now().toUtc().difference(lastCaptureFixReceivedAt!).inSeconds>45;
   if(locationSub!=null&&!stale)return;
   captureRestarting=true;
   try {
    final unfinished=await db.query('local_trips',where:'ended_at IS NULL',orderBy:'started_at DESC',limit:1);
    if(unfinished.isNotEmpty&&await trackingPermissionsReady()){
      final id=unfinished.first['local_id'] as int;
      await nuqatiLog('GPS_CAPTURE_WATCHDOG_RESTART trip=$id stale=$stale');
      if(stale){await locationSub?.cancel();locationSub=null;}
      await startCapture(id);
    }
   }catch(e){await nuqatiLog('GPS_CAPTURE_WATCHDOG_FAILED',e);}
   finally{captureRestarting=false;}
 });
 unawaited(checkMaintenance());
 unawaited(flush());
 // Resume monitoring after a normal service restart; never bypass persisted Privacy Mode.
 privacy=(await secure.read(key:'nuqati_privacy_mode'))=='1';
 if(privacy){service.stopSelf();return;}
 final unfinished=await db.query('local_trips',where:'ended_at IS NULL',orderBy:'started_at DESC',limit:1);
 if(unfinished.isNotEmpty)await startCapture(unfinished.first['local_id'] as int);
 await beginMonitoring();
}

Future<void> startBackgroundTrip(int tripId) async {
 if(!await trackingPermissionsReady()){await nuqatiLog('TRIP_START_DENIED_PERMISSION');return;}
 final service=FlutterBackgroundService();
 if(!await service.isRunning()){await nuqatiLog('STARTING_BACKGROUND_SERVICE');await service.startService();}
 // Allow the background isolate to register its event listeners.
 await Future<void>.delayed(const Duration(milliseconds:900));
 service.invoke('startTrip',{'trip_id':tripId});
 await nuqatiLog('START_TRIP_SENT trip=$tripId');
}

Future<void> stopBackgroundTrip() async {
 FlutterBackgroundService().invoke('stopTrip');
}

Future<void> ensureAutomaticMonitoring() async {
 const store=FlutterSecureStorage();
 if(await store.read(key:'nuqati_privacy_mode')=='1')return;
 if((await store.read(key:'nuqati_driver_access_token'))?.isEmpty!=false)return;
 if(!await trackingPermissionsReady()){await nuqatiLog('MONITOR_START_DENIED_PERMISSION');return;}
 final service=FlutterBackgroundService();
 if(!await service.isRunning()){await service.startService();await Future<void>.delayed(const Duration(milliseconds:900));}
 service.invoke('monitorOn');
}
// Privacy choices are queued before the UI changes; only timestamps and toggles are stored.
// No location, route, or speed is collected by this audit mechanism.
Future<void> queuePrivacyEvidence(bool enabled) async {
 final db=await openTrackingDatabase();
 final now=DateTime.now().toUtc();
 final eventId='privacy_${now.microsecondsSinceEpoch}_${enabled?1:0}';
 await db.insert('privacy_evidence_queue',{
  'event_id':eventId,'privacy_enabled':enabled?1:0,'selected_at':now.toIso8601String(),
 },conflictAlgorithm:ConflictAlgorithm.ignore);
}
Future<void> syncPrivacyEvidence() async {
 try {
  const secure=FlutterSecureStorage();
  final access=await secure.read(key:'nuqati_driver_access_token');
  if(access==null||access.isEmpty)return;
  final db=await openTrackingDatabase();
  final events=await db.query('privacy_evidence_queue',orderBy:'selected_at ASC',limit:100);
  for(final event in events){
   final response=await http.post(Uri.parse('$api/api/v1/mobile/privacy-evidence'),
    headers:{'Authorization':'Bearer $access','Content-Type':'application/json'},
    body:jsonEncode({'event_id':event['event_id'],
     'privacy_enabled':event['privacy_enabled']==1,'selected_at':event['selected_at']}))
     .timeout(const Duration(seconds:10));
   if(response.statusCode<200||response.statusCode>=300)break;
   await db.delete('privacy_evidence_queue',where:'event_id = ?',whereArgs:[event['event_id']]);
  }
 }catch(e,s){await nuqatiLog('PRIVACY_EVIDENCE_SYNC_FAILED',e,s);}
}
Future<void> syncNotificationEvidence() async {
 try {
  const secure=FlutterSecureStorage();
  final access=await secure.read(key:'nuqati_driver_access_token');
  if(access==null||access.isEmpty)return;
  final db=await openTrackingDatabase();
  final events=await db.query('notification_evidence_queue',orderBy:'selected_at ASC',limit:100);
  for(final event in events){
   final response=await http.post(Uri.parse('$api/api/v1/mobile/notification-evidence'),
    headers:{'Authorization':'Bearer $access','Content-Type':'application/json'},
    body:jsonEncode({'event_id':event['event_id'],
     'notifications_enabled':event['notifications_enabled']==1,'selected_at':event['selected_at']}))
    .timeout(const Duration(seconds:10));
   if(response.statusCode<200||response.statusCode>=300)break;
   await db.delete('notification_evidence_queue',where:'event_id = ?',whereArgs:[event['event_id']]);
  }
 }catch(e,s){await nuqatiLog('NOTIFICATION_EVIDENCE_SYNC_FAILED',e,s);}
}
Future<void> setFullPrivacy(bool enabled) async {
 const store=FlutterSecureStorage();
 await store.write(key:'nuqati_privacy_mode',value:enabled?'1':'0');
 if(enabled){FlutterBackgroundService().invoke('privacyOn');}
 else{await ensureAutomaticMonitoring();}
}
Future<void> syncPendingTripsOnce() async {
 try {
  final service=FlutterBackgroundService();
  if(!await service.isRunning())await service.startService();
  await Future<void>.delayed(const Duration(milliseconds:900));
  service.invoke('syncNow');
 }catch(e,s){await nuqatiLog('SYNC_WAKE_FAILED',e,s);}
}

class DriverApp extends StatefulWidget{const DriverApp({super.key});@override State<DriverApp> createState()=>_DriverAppState();}
class _DriverAppState extends State<DriverApp> with WidgetsBindingObserver{
 final iqama=TextEditingController(),password=TextEditingController(),oldPassword=TextEditingController(),newPassword=TextEditingController();
 String token='',name='',plate='',company='',vehicleModel='',vehicleDoor='',vehicleYear='',logoData='',status='Sign in with your Iqama / Saudi ID';
 static const _secureStore=FlutterSecureStorage();
 bool privacyMode=false; bool coachExpanded=false;
 bool rememberMe=false; bool loginPasswordVisible=false; bool odometerPromptChecking=false; bool historyPromptShowing=false; bool initialHistoryDue=false;
 double? displayedOdometer; double liveTripKm=0; int? liveTripKmId; Map<String,dynamic>? smartOil; List<dynamic> careReminders=[]; bool monthlyOdometerDue=false, careBusy=false, monthlyPromptShowing=false; DateTime? careLastFetch; Timer? careRefreshTimer;
 String phone=''; int? tripEndRemaining; bool completedTrip=false; int tab=0; double speedKmh=0, accelerationKmhS=0, score=100;
 int speedingCount=0, brakingCount=0, accelerationCount=0, corneringCount=0, severeCount=0;
 static const EventChannel cameraActivityEvents=EventChannel('nuqati/camera_activity');
 StreamSubscription<dynamic>? cameraActivitySubscription;
 bool cameraActivityMonitoring=false, otherCameraBusy=false;
 DateTime? cameraBusySince, lastCameraObservation;
 bool changePasswordExpanded=false; bool notificationsEnabled=true; bool notificationReminderShowing=false;
 Timer? scoreRefreshTimer; bool safetyCountsLoading=false; bool scoreRefreshing=false; bool officialScoreReady=false; Map<String,dynamic>? officialScoreBreakdown;
 Map<String,dynamic> assistContacts={}; bool assistanceBusy=false; String assistanceCategory='manager'; final assistanceDescription=TextEditingController();
 String alert='Drive safely to keep your score green.';
 DateTime? lastAlertAt;
 DateTime? lastLocalViolationAt; double? lastLocalHeading; DateTime? lastLocalHeadingAt;
 StreamSubscription<Position>? positionSubscription;
 DateTime? lastUploadedFix; bool uploadingFix=false;
 double speedLimit=100, harshAcceleration=10.8, harshBraking=10.8;
 Map<String,bool> enabledEvents={'speeding':true,'harsh_acceleration':true,'harsh_braking':true,'harsh_cornering':true};
 Timer? policyTimer;
 Timer? livePositionRequestTimer;
 String? _lastPositionRequestId;
 Future<void> pollLivePositionRequest() async {
   // Foreground-only cooperation: never wake the phone from privacy mode,
   // never generate a fictitious location and never clear local trip records.
   if(token.isEmpty || privacyMode || !mounted) return;
   try {
     final permission=await Geolocator.checkPermission();
     if(permission!=LocationPermission.always && permission!=LocationPermission.whileInUse)return;
     if(!await Geolocator.isLocationServiceEnabled())return;
     final command=await call('/api/v1/mobile/live-position-request');
     if(command['status']!='pending')return;
     final id=(command['request_id']??'').toString();
     if(id.isEmpty || id==_lastPositionRequestId)return;
     final fix=await Geolocator.getCurrentPosition(locationSettings:const LocationSettings(
       accuracy:LocationAccuracy.bestForNavigation,timeLimit:Duration(seconds:12)));
     if(privacyMode || !mounted || token.isEmpty || fix.accuracy>100 || fix.accuracy<0)return;
     await call('/api/v1/mobile/live-position-reply',method:'POST',body:{
       'request_id':id,'latitude':fix.latitude,'longitude':fix.longitude,
       'accuracy_m':fix.accuracy,'speed_kmh':(fix.speed*3.6).clamp(0.0,350.0),
       'recorded_at':fix.timestamp.toUtc().toIso8601String(),
     });
     _lastPositionRequestId=id;
   }catch(e){await nuqatiLog('LIVE_POSITION_REQUEST_UNAVAILABLE',e);}
 }
 void startLivePositionRequestPolling(){
   livePositionRequestTimer?.cancel();
   livePositionRequestTimer=Timer.periodic(const Duration(seconds:20),(_){unawaited(pollLivePositionRequest());});
   unawaited(pollLivePositionRequest());
 }
 Future<void> syncDrivingPolicy() async {
   if(token.isEmpty)return;
   try {
     final policy=await call('/api/v1/mobile/driving-policy');
     final ownCompany=await _secureStore.read(key:'nuqati_driver_company_id');
     if(ownCompany==null||policy['company_id']?.toString()!=ownCompany)throw StateError('Policy belongs to a different company');
     await _secureStore.write(key:'nuqati_driving_policy',value:jsonEncode(policy));
     // The background tracker must report application before the backend receives ACK.
     // Saving alone is not proof that the running detector is using this policy.
     final version=policy['policy_version'];
     if(version is String && version.isNotEmpty){
       FlutterBackgroundService().invoke('policyApply',{'version':version});
     }
     final switches=policy['enabled'];
     if(!mounted)return;
     setState(() {
       speedLimit=(policy['speeding_kmh'] as num).toDouble();
       harshAcceleration=(policy['harsh_accel_ms2'] as num).toDouble()*3.6;
       harshBraking=(policy['harsh_brake_ms2'] as num).toDouble()*3.6;
       if(switches is Map){for(final key in enabledEvents.keys){enabledEvents[key]=switches[key]!=false;}}
     });
   }catch(_){/* Retain last known policy when offline. */}
 }

 String language='en';
 bool get english=>language=='en';
 Future<void> changeLanguage(String next) async {await _secureStore.write(key:nuqatiLanguageKey,value:next);if(mounted)setState(()=>language=next);}
 Future<void> restoreLanguage() async {final next=await nuqatiLanguage();if(mounted)setState(()=>language=next);}
 
 Future<void> requestTrackingConsentIfNeeded({bool force=false}) async {
  if(permissionPromptInProgress||!mounted)return;
  permissionPromptInProgress=true;
  try {
   final prompted=(await _secureStore.read(key:'nuqati_permissions_prompt_v2'))=='1';
   final location=await Geolocator.checkPermission();
   final notifications=await ph.Permission.notification.status;
   final battery=await ph.Permission.ignoreBatteryOptimizations.status;
   // Only show the onboarding explanation once. Changes or revocations are
   // handled by Check tracking permissions, not a repeated login dialog.
   final needsPrompt=force||!prompted;
   if(!needsPrompt||!mounted)return;
   // Remember that onboarding was shown even if the driver chooses Later.
   // A manual Settings action can reopen it when requested.
   await _secureStore.write(key:'nuqati_permissions_prompt_v2',value:'1');
   final proceed=await showDialog<bool>(context:context,builder:(ctx)=>AlertDialog(
    title:Text(tr('Set up location once','إعداد الموقع لمرة واحدة')),
    content:Text(tr('Allow precise location now so Nuqati can detect trips. For automatic tracking when the app is closed, Android may require a one-time Allow all the time selection in app settings. Nuqati will not show this setup on every login.','اسمح بالموقع الدقيق الآن لتسجيل الرحلات. لتتبع الرحلات تلقائياً عند إغلاق التطبيق قد يتطلب أندرويد اختيار السماح طوال الوقت من إعدادات التطبيق لمرة واحدة. لن نكرر هذا الإعداد عند كل تسجيل دخول.')),
    actions:[
      TextButton(onPressed:()=>Navigator.pop(ctx,false),child:Text(tr('Later','لاحقاً'))),
      ElevatedButton(onPressed:()=>Navigator.pop(ctx,true),child:Text(tr('Continue','متابعة'))),
    ],
   ));
   if(proceed!=true||!mounted)return;
   if(!await Geolocator.isLocationServiceEnabled()){
    await Geolocator.openLocationSettings();
   }
   var permission=await Geolocator.checkPermission();
   if(permission==LocationPermission.denied){permission=await Geolocator.requestPermission();}
   // Android 11+ may require a one-time system settings step for background
   // location; requesting here cannot silently grant Always access.
   if(permission==LocationPermission.whileInUse){await ph.Permission.locationAlways.request();}
   await ph.Permission.notification.request();
   await ph.Permission.ignoreBatteryOptimizations.request();
   if(!mounted)return;
   final afterLocation=await Geolocator.checkPermission();
   final afterNotifications=await ph.Permission.notification.status;
   final afterBattery=await ph.Permission.ignoreBatteryOptimizations.status;
   final complete=afterLocation==LocationPermission.always&&afterNotifications.isGranted&&afterBattery.isGranted;
   await showDialog<void>(context:context,builder:(ctx)=>AlertDialog(
    title:Text(tr(complete?'Tracking permissions ready':'Finish setup in Android settings',complete?'صلاحيات التتبع جاهزة':'أكمل الإعداد من إعدادات أندرويد')),
    content:Text(complete
      ? tr('Thank you. Nuqati can now track trips in the background and send alerts reliably.','شكراً لك. يمكن لنقاطي الآن تتبع الرحلات في الخلفية وإرسال التنبيهات بشكل موثوق.')
      : tr('To track automatically with the app closed, Android may require Allow all the time in App settings once. You can also review this later using Check tracking permissions.','للتتبع التلقائي بعد إغلاق التطبيق قد تحتاج إلى اختيار السماح طوال الوقت من إعدادات التطبيق لمرة واحدة. يمكنك المراجعة لاحقاً عبر فحص صلاحيات التتبع.')),
    actions:[
      TextButton(onPressed:()=>Navigator.pop(ctx),child:Text(tr('Close','إغلاق'))),
      if(!complete)TextButton(onPressed:(){Navigator.pop(ctx);Geolocator.openAppSettings();},child:Text(tr('App settings','صلاحيات التطبيق'))),
    ],
   ));
  } finally {permissionPromptInProgress=false;}
 }

Future<void> checkTrackingRequirements() async {
  final location=await Geolocator.checkPermission();
  final notifications=await ph.Permission.notification.status;
  final battery=await ph.Permission.ignoreBatteryOptimizations.status;
  if(!mounted)return;
  await showDialog<void>(context:context,builder:(ctx)=>AlertDialog(
   title:Text(tr('Tracking setup','إعداد التتبع')),
   content:Text('Location: $location\nNotifications: $notifications\nBattery optimization exemption: $battery\n\nRequired: Location = Allow all the time, Notifications = Allowed, Battery = Unrestricted. If any of these are missing, finish them in Android settings.'),
   actions:[TextButton(onPressed:()=>Navigator.pop(ctx),child:const Text('Close')),TextButton(onPressed:(){Navigator.pop(ctx);Geolocator.openAppSettings();},child:const Text('App settings')),TextButton(onPressed:()async{Navigator.pop(ctx);await ph.Permission.notification.request();await ph.Permission.ignoreBatteryOptimizations.request();},child:const Text('Request permissions'))]));
 }

 bool gpsReady=false, gpsChecking=false; DateTime? lastGpsFix; Timer? gpsWatchdog; bool gpsWarningShown=false; bool permissionPromptInProgress=false;
 static const Map<String,String> urduLabels={
 'NUQATI · Driver':'نقاطی · ڈرائیور','My points':'میرے پوائنٹس','Driving':'ڈرائیونگ','Settings':'ترتیبات',
 'GPS status':'جی پی ایس کی حالت','Ready':'تیار','Check required':'جانچ ضروری','Check GPS':'جی پی ایس چیک کریں',
 'MY SAFE TRIP':'میرا محفوظ سفر','Start green. Stay safe. Earn a better score.':'محفوظ ڈرائیونگ کریں اور بہتر اسکور حاصل کریں۔',
 'Your driving summary':'ڈرائیونگ کا خلاصہ','Speeding':'تیز رفتاری','Braking':'سخت بریک','Acceleration':'تیز ایکسلریشن','Cornering':'تیز موڑ',
 'YOUR DRIVING COACH':'آپ کا ڈرائیونگ کوچ','Small changes make every trip safer and more efficient.':'چھوٹی تبدیلیاں ہر سفر کو محفوظ بناتی ہیں۔',
 'Accelerate smoothly':'آہستہ رفتار بڑھائیں','Press the accelerator gently to avoid wasting fuel.':'ایندھن بچانے کے لیے ایکسلریٹر آہستہ دبائیں۔',
 'Brake early and gently':'وقت پر آہستہ بریک لگائیں','Leave more distance to reduce sudden braking and brake wear.':'اچانک بریک سے بچنے کے لیے مناسب فاصلہ رکھیں۔',
 'Keep a steady, safe speed':'محفوظ رفتار رکھیں','Follow posted speed limits and adapt to road conditions.':'رفتار کی حد اور سڑک کے حالات کا خیال رکھیں۔',
 'Tips are general guidance. Your score is a GPS-based estimate, not a measured fuel saving.':'یہ عمومی مشورے ہیں؛ اسکور جی پی ایس کا تخمینہ ہے۔',
 'Driving safety notifications':'ڈرائیونگ حفاظتی اطلاعات','Mute driving warnings only. Trips, scores and GPS continue.':'صرف ڈرائیونگ انتباہات بند ہوں گے۔ سفر، اسکور اور GPS جاری رہیں گے۔','Driving safety alerts are off':'ڈرائیونگ حفاظتی انتباہات بند ہیں','Enable alerts':'انتباہات فعال کریں','A trip has started. Enable safety notifications in Settings to receive driving warnings. GPS tracking and scoring continue when alerts are off.':'سفر شروع ہو گیا ہے۔ وارننگ کے لیے ترتیبات میں اطلاعات فعال کریں۔ GPS اور اسکور جاری رہیں گے۔',
 'CURRENT SPEED':'موجودہ رفتار','Company speed threshold':'کمپنی کی رفتار کی حد','Harsh braking':'سخت بریک','Harsh acceleration':'تیز ایکسلریشن','Harsh cornering':'تیز موڑ',
 'Acceleration / Deceleration':'رفتار بڑھنا / گھٹنا','Severe events':'شدید واقعات','Driver profile':'ڈرائیور کی معلومات',
 'Name':'نام','Iqama / Saudi ID':'اقامہ / شناختی نمبر','Iqama / Saudi ID number':'اقامہ / شناختی نمبر',
 'Phone':'فون','Not provided':'دستیاب نہیں','Company':'کمپنی','Language':'زبان',
 'Check tracking permissions':'ٹریکنگ اجازتیں چیک کریں','Change password':'پاس ورڈ تبدیل کریں',
 'Current password':'موجودہ پاس ورڈ','New password (12+ characters)':'نیا پاس ورڈ (کم از کم ۱۲ حروف)',
 'Update password':'پاس ورڈ اپ ڈیٹ کریں','LOG OUT':'لاگ آؤٹ','Log out':'لاگ آؤٹ',
 'Password':'پاس ورڈ','Remember me / automatic sign in':'مجھے یاد رکھیں / خودکار لاگ ان',
 'Signing in...':'لاگ ان ہو رہا ہے...','Sign in':'لاگ ان',
 'ENABLE PRIVACY MODE':'پرائیویسی موڈ آن کریں','DISABLE PRIVACY MODE':'پرائیویسی موڈ بند کریں',
 'Tracking setup':'ٹریکنگ کی ترتیب','Close':'بند کریں','App settings':'ایپ کی ترتیبات',
 'Location settings':'مقام کی ترتیبات','App permissions':'ایپ کی اجازتیں',
 'GPS signal lost during trip. Restore location services.':'سفر کے دوران جی پی ایس سگنل ختم ہو گیا۔',
 'Trip in progress':'سفر جاری ہے','Trip ended':'سفر ختم ہوا','Waiting for trip':'سفر کا انتظار',
 'Trip ending in':'سفر ختم ہونے میں','Driver':'ڈرائیور','Vehicle':'گاڑی',
 'Privacy Mode ON':'پرائیویسی موڈ فعال','Privacy Mode OFF':'پرائیویسی موڈ بند',
 'Fleet Driver Companion':'فلیٹ ڈرائیور ساتھی',
 'Select language':'زبان منتخب کریں','Show password':'پاس ورڈ دکھائیں','Hide password':'پاس ورڈ چھپائیں',
 'Enter first odometer reading':'پہلی بار اوڈومیٹر ریڈنگ درج کریں','Correct odometer reading':'اوڈومیٹر ریڈنگ درست کریں',
 'By Al-Riadah Workshop':'ورشة الريادة کے تحت',
 'Request workshop help':'ورکشاپ سے مدد طلب کریں',
 'Workshop assistance':'ورکشاپ کی مدد',
 'Workshop manager / complaint':'ورکشاپ مینیجر / شکایت',
 'Mechanic':'مکینک',
 'Electrician':'الیکٹریشن',
 'Towing':'گاڑی ٹو کروائیں',
 'Describe the issue':'مسئلہ بیان کریں',
 'Share current location?':'کیا موجودہ مقام شیئر کریں؟',
 'Share one GPS point with the workshop for this request. Your Privacy Mode remains unchanged.':'اس درخواست کے لیے ورکشاپ کے ساتھ صرف ایک جی پی ایس مقام شیئر کریں۔ پرائیویسی موڈ تبدیل نہیں ہوگا۔',
 'No':'نہیں',
 'Share':'شیئر کریں',
 'Send request':'درخواست بھیجیں',
 'Request delivered':'درخواست پہنچ گئی',
 'Request NOT delivered. Connect to internet or call the workshop.':'درخواست نہیں پہنچی۔ انٹرنیٹ سے جڑیں یا ورکشاپ کو فون کریں۔',
 'Workshop phone not configured':'ورکشاپ کا فون نمبر درج نہیں ہے',
 'For urgent danger, stop safely and call emergency services. Offline requests cannot be delivered; call directly.':'فوری خطرے میں محفوظ مقام پر رکیں اور ایمرجنسی خدمات کو کال کریں۔ آف لائن درخواست نہیں پہنچ سکتی؛ براہ راست فون کریں۔',
 };
 String tr(String en,String ar)=>language=='ur'?(urduLabels[en]??ar):language=='ar'?ar:en;
 String get tripStateLabel=>privacyMode?tr('Privacy Mode ON','وضع الخصوصية مفعّل'):tripId!=null?tr('Trip in progress','الرحلة جارية'):completedTrip?tr('Trip ended','انتهت الرحلة'):tr('Waiting for trip','بانتظار الرحلة');
 Color get scoreColor=>officialScoreReady?(officialRag=='green'?const Color(0xff62df96):officialRag=='amber'?const Color(0xffffc45b):officialRag=='red'?const Color(0xffff6675):Colors.white54):(score>=90?const Color(0xff62df96):score>=60?const Color(0xffffc45b):const Color(0xffff6675));
 String get rating=>officialScoreReady?(officialRag??'NO DATA').toUpperCase():(score>=90?'GREEN':score>=60?'AMBER':'RED');
 // Driver's live trip points are calculated on-device, including without internet.
 // The server retains its independent, distance-normalized historical score.
 // App-only coaching: normal 2 points and excessive 3 points; backend RAG untouched.
 Future<void> _persistLocalTripScore() async {
   final id=tripId;if(id==null)return;
   try {await _secureStore.write(key:'nuqati_live_trip_score',value:jsonEncode({
     'trip_id':id,'score':score,'speeding':speedingCount,'braking':brakingCount,
     'acceleration':accelerationCount,'cornering':corneringCount,'severe':severeCount,
   }));}catch(e){await nuqatiLog('LOCAL_SCORE_SAVE_FAILED',e);}
 }
 Future<void> _restoreLocalTripScore(int id) async {
   try {
     final raw=await _secureStore.read(key:'nuqati_live_trip_score');
     if(raw==null)return;
     final data=jsonDecode(raw) as Map<String,dynamic>;
     if(data['trip_id']!=id||!mounted||tripId!=id)return;
     setState((){
       score=((data['score'] as num?)?.toDouble()??100).clamp(0.0,100.0);
       speedingCount=(data['speeding'] as num?)?.toInt()??0;
       brakingCount=(data['braking'] as num?)?.toInt()??0;
       accelerationCount=(data['acceleration'] as num?)?.toInt()??0;
       corneringCount=(data['cornering'] as num?)?.toInt()??0;
       severeCount=(data['severe'] as num?)?.toInt()??0;
     });
   }catch(e){await nuqatiLog('LOCAL_SCORE_RESTORE_FAILED',e);}
 }
 Future<void> _clearLocalTripScore() async {
   try{await _secureStore.delete(key:'nuqati_live_trip_score');}catch(_){}
 }
 Future<void> restoreCameraActivityMonitoring() async {
  final savedPreference=await _secureStore.read(key:'nuqati_camera_activity_monitoring');
  final enabled=savedPreference!='0'; // Enabled by default; preserve an explicit user opt-out.
  if(mounted)setState(()=>cameraActivityMonitoring=enabled);
  if(enabled) startCameraActivityObservation();
 }
 Future<void> setCameraActivityMonitoring(bool enabled) async {
  await _secureStore.write(key:'nuqati_camera_activity_monitoring',value:enabled?'1':'0');
  if(!mounted)return;
  setState(()=>cameraActivityMonitoring=enabled);
  if(enabled){startCameraActivityObservation();}
  else{await cameraActivitySubscription?.cancel();cameraActivitySubscription=null;otherCameraBusy=false;cameraBusySince=null;}
 }
 void startCameraActivityObservation(){
  cameraActivitySubscription?.cancel();
  if(!cameraActivityMonitoring)return;
  cameraActivitySubscription=cameraActivityEvents.receiveBroadcastStream().listen((value){
   if(!mounted||!cameraActivityMonitoring)return;
   final busy=value==true;
   if(busy!=otherCameraBusy){otherCameraBusy=busy;cameraBusySince=busy?DateTime.now():null;}
  },onError:(Object error){unawaited(nuqatiLog('CAMERA_ACTIVITY_OBSERVER_UNAVAILABLE',error));});
 }
 void evaluateCameraActivity(double speed){
  if(!cameraActivityMonitoring||privacyMode||tripId==null||!otherCameraBusy||speed<=30)return;
  final now=DateTime.now();
  if(cameraBusySince==null||now.difference(cameraBusySince!).inSeconds<5)return;
  if(lastCameraObservation!=null&&now.difference(lastCameraObservation!).inMinutes<5)return;
  lastCameraObservation=now;
  notifyDriver(tr('Possible camera use while driving. Please focus on the road.','احتمال استخدام الكاميرا أثناء القيادة. يرجى التركيز على الطريق.'));
  unawaited(initializeViolationAlerts(requestPermission:false).then((_)=>(notificationsEnabled
    ?nuqatiAlerts.show(73429,tr('Possible camera use while driving','احتمال استخدام الكاميرا أثناء القيادة'),
      tr('Speed above 30 km/h. Please focus on driving.','السرعة أعلى من 30 كم/س. يرجى التركيز على القيادة.'),
      const NotificationDetails(android:AndroidNotificationDetails('nuqati_violations_v1','Driving safety warnings',importance:Importance.high,priority:Priority.high)))
    :Future<void>.value())).catchError((Object e){unawaited(nuqatiLog('CAMERA_ALERT_FAILED',e));}));
  unawaited(sendCameraActivityObservation(speed));
 }
 Future<void> sendCameraActivityObservation(double speed) async {
  if(token.isEmpty)return;
  final now=DateTime.now().toUtc();
  try{await call('/api/v1/mobile/safety-observation',method:'POST',body:{
   'event_id':'camera_${now.microsecondsSinceEpoch}',
   'event_type':'possible_camera_use_driving','speed_kmh':speed,
   'observed_at':now.toIso8601String(),
  });}catch(e){await nuqatiLog('CAMERA_AUDIT_UPLOAD_FAILED',e);}
 }
 void notifyDriver(String message,{bool severe=false}){
   final now=DateTime.now();
   if(lastAlertAt!=null&&now.difference(lastAlertAt!).inSeconds<8)return;
   lastAlertAt=now; if(mounted)setState(()=>alert=message);
 }
 void evaluate(Position p){
   final now=DateTime.now();
   if(p.accuracy>35||now.difference(p.timestamp).inSeconds>5)return;
   lastGpsFix=now;if(mounted&&(!gpsReady||gpsWarningShown))setState(()=>gpsReady=true);gpsWarningShown=false;
   final newSpeed=p.speed.isFinite&&p.speed>0?p.speed*3.6:0.0;
   double newAccel=0;
   if(lastPosition!=null&&lastTime!=null){
     final secs=now.difference(lastTime!).inMilliseconds/1000;
     if(secs>=1&&secs<=12)newAccel=(newSpeed-speedKmh)/secs;
   }
   if(mounted)setState((){speedKmh=newSpeed;accelerationKmhS=newAccel;});
   bool harshCorner=false;
   if(newSpeed>=20&&p.heading.isFinite&&p.heading>=0&&p.accuracy<=20){
     if(lastLocalHeading!=null&&lastLocalHeadingAt!=null){
       final secs=now.difference(lastLocalHeadingAt!).inMilliseconds/1000;
       final turn=((p.heading-lastLocalHeading!+540)%360)-180;
       harshCorner=secs>=1&&secs<=5&&turn.abs()/secs>=18;
     }
     lastLocalHeading=p.heading;lastLocalHeadingAt=now;
   }else{lastLocalHeading=null;lastLocalHeadingAt=null;}
   evaluateCameraActivity(newSpeed);
   // Background tracking owns notification-aligned event counts and live provisional scoring.
   lastPosition=p;lastTime=now;
 }

 Future<void> _loadSafetyCounts(int id) async {
  if(safetyCountsLoading)return;
  safetyCountsLoading=true;
  try{
   final db=await openTrackingDatabase();
   final rows=await db.rawQuery('SELECT event_type, COUNT(*) AS total FROM safety_live_events WHERE trip_id = ? GROUP BY event_type',[id]);
   if(!mounted||tripId!=id)return;
   int sp=0,br=0,ac=0,co=0;
   for(final row in rows){final total=(row['total'] as num?)?.toInt()??0;switch(row['event_type']){
    case 'speeding':case 'excessive_speeding':sp+=total;break;
    case 'harsh_braking':case 'excessive_harsh_braking':br+=total;break;
    case 'harsh_acceleration':case 'excessive_harsh_acceleration':ac+=total;break;
    case 'harsh_cornering':co=total;break;
   }}
   final severe=rows.where((r)=>(r['event_type'] as String).startsWith('excessive_')).fold<int>(0,(sum,r)=>sum+((r['total'] as num?)?.toInt()??0));
   if(sp!=speedingCount||br!=brakingCount||ac!=accelerationCount||co!=corneringCount||severe!=severeCount){
    setState((){speedingCount=sp;brakingCount=br;accelerationCount=ac;corneringCount=co;severeCount=severe;score=nuqatiPointsFromCounts({for(final row in rows) row['event_type'] as String:(row['total'] as num).toInt()}).toDouble();});
    await _persistLocalTripScore();
    await nuqatiLog('LIVE_COACHING_COUNTS_SYNCED speed=$sp braking=$br acceleration=$ac cornering=$co');
   }
  }catch(e){await nuqatiLog('LOCAL_SAFETY_COUNTER_READ_FAILED',e);}
  finally{safetyCountsLoading=false;}
 }
 Future<void> _onSafetyEvent(Map<String,dynamic>? event) async {
  if(!mounted||event==null||privacyMode)return;
  final id=(event['trip_id'] as num?)?.toInt();
  if(id==null||id!=tripId)return;
  await _loadSafetyCounts(id);
   if(mounted)setState(()=>alert=tr('Safety event saved · live coaching points updated','تم حفظ حدث السلامة وتحديث نقاط القيادة')); 
 }
 DateTime? lastEndedAt;
 int? lastOfficialTripId;
 double? previousOfficialScore;
 String officialFeedback='';
 String localTripFeedback='';
 Future<void> showLocalTripResult(int id) async {
  try {
   final db=await openTrackingDatabase();
   final row=await db.query('local_score_history',where:'trip_id = ?',whereArgs:[id],limit:1);
   if(row.isEmpty)return;
   final points=(row.first['points'] as num).toInt();
   final older=await db.query('local_score_history',where:'trip_id != ? AND ended_at < ?',whereArgs:[id,row.first['ended_at']],orderBy:'ended_at DESC',limit:1);
   final previous=older.isEmpty?null:(older.first['points'] as num).toInt();
   final message=nuqatiLocalProgressMessage(points,previous,language);
   if(mounted)setState((){score=points.toDouble();localTripFeedback=message;});
  }catch(e){await nuqatiLog('LOCAL_SCORE_DISPLAY_FAILED',e);}
 }

 String? officialRag;
 bool officialLowerBetter=false;
 Timer? officialPollTimer;
 // Official Flexible RAG stays exclusively on backend reports.
 // This app never requests, converts, or validates a backend driver score.
 Future<void> _checkOfficialTripScore() async {}
 void _scheduleOfficialScoreCheck() {}
 @override void initState(){super.initState();scoreRefreshTimer=Timer.periodic(const Duration(seconds:5),(_){final id=tripId;if(mounted&&id!=null&&!privacyMode)unawaited(_loadSafetyCounts(id));});careRefreshTimer=Timer.periodic(const Duration(minutes:5),(_){if(mounted&&token.isNotEmpty)unawaited(refreshVehicleCare(askMonthly:false));});unawaited(restoreVehicleCareCache());FlutterBackgroundService().on('driverSafetyEvent').listen((data){unawaited(_onSafetyEvent(data));});FlutterBackgroundService().on('policyApplied').listen((data){final version=data?['version']?.toString();if(data?['applied']==true&&version!=null&&token.isNotEmpty){unawaited(() async {try{await call('/api/v1/mobile/driving-policy/ack',method:'POST',body:{'policy_version':version});await nuqatiLog('COMPANY_POLICY_ACK version=$version');}catch(e){await nuqatiLog('COMPANY_POLICY_ACK_RETRY',e);}}());}});FlutterBackgroundService().on('localTripEnded').listen((data){final id=(data?['trip_id'] as num?)?.toInt();if(id!=null)unawaited(showLocalTripResult(id));});FlutterBackgroundService().on('trackingError').listen((event){if(mounted)setState(()=>status='GPS tracking stopped: check location permission and settings');});FlutterBackgroundService().on('tripState').listen((event){if(mounted&&!privacyMode)setState((){final next=(event?['trip_id'] as num?)?.toInt();if(tripId!=null&&next==null){final endedId=tripId!;completedTrip=true;lastEndedAt=DateTime.now().toUtc();officialScoreReady=false;officialScoreBreakdown=null;WidgetsBinding.instance.addPostFrameCallback((_){if(mounted)unawaited(showLocalTripResult(endedId));});}if(next!=null&&tripId!=next){unawaited(remindNotificationsAtTripStart());completedTrip=false;score=100;localTripFeedback='';officialScoreReady=false;officialLowerBetter=false;officialScoreBreakdown=null;officialFeedback='';officialRag=null;officialPollTimer?.cancel();speedingCount=0;brakingCount=0;accelerationCount=0;corneringCount=0;severeCount=0;lastLocalViolationAt=null;lastLocalHeading=null;lastLocalHeadingAt=null;unawaited(_restoreLocalTripScore(next).then((_)=>(_loadSafetyCounts(next))));}if(next!=tripId){liveTripKm=0;liveTripKmId=next;}tripId=next;tripEndRemaining=null;if(next!=null)FlutterBackgroundService().invoke('liveDistanceRequest');});});FlutterBackgroundService().on('liveDistance').listen((event){if(!mounted)return;final id=(event?['trip_id'] as num?)?.toInt();final km=(event?['km'] as num?)?.toDouble();if(id!=null&&km!=null&&id==tripId&&km>=0)setState((){liveTripKmId=id;liveTripKm=km;});});FlutterBackgroundService().on('tripCountdown').listen((event){if(mounted)setState(()=>tripEndRemaining=(event?['remaining'] as num?)?.toInt());});WidgetsBinding.instance.addObserver(this);WidgetsBinding.instance.addPostFrameCallback((_){if(mounted){restoreLanguage();restorePrivacyState();restoreNotificationPreference();restoreCameraActivityMonitoring();unawaited(() async {await requestTrackingConsentIfNeeded();if(mounted)await restoreSavedSession();}());}});}
 @override void didChangeAppLifecycleState(AppLifecycleState state){
   if(state==AppLifecycleState.resumed && token.isNotEmpty){unawaited(refreshVehicleCare());unawaited(refreshSmartOil());restorePrivacyState();unawaited(syncPendingTripsOnce());unawaited(syncPrivacyEvidence());unawaited(syncNotificationEvidence());if(tripId!=null){FlutterBackgroundService().invoke('liveDistanceRequest');unawaited(_loadSafetyCounts(tripId!));unawaited(remindNotificationsAtTripStart());}}
 }
 @override void dispose(){WidgetsBinding.instance.removeObserver(this);timer?.cancel();policyTimer?.cancel();livePositionRequestTimer?.cancel();scoreRefreshTimer?.cancel();officialPollTimer?.cancel();careRefreshTimer?.cancel();gpsWatchdog?.cancel();positionSubscription?.cancel();cameraActivitySubscription?.cancel();iqama.dispose();password.dispose();oldPassword.dispose();newPassword.dispose();super.dispose();}
 Future<void> checkGps({bool displayDialog=false}) async {
   if(gpsChecking)return;
   if(mounted)setState(()=>gpsChecking=true);
   bool ready=false;String message='';
   try {
     if(!await Geolocator.isLocationServiceEnabled()){
       message=tr('Phone location services are OFF. Turn on GPS to track your trip.','خدمات الموقع مغلقة. شغّل الموقع لتتبع رحلتك.');
     }else{
       var permission=await Geolocator.checkPermission();
       if(permission==LocationPermission.denied){permission=await Geolocator.requestPermission();}
       if(permission==LocationPermission.denied||permission==LocationPermission.deniedForever){
         message=tr('Allow location permission for Nuqati in Android settings.','اسمح لتطبيق نقاطي باستخدام الموقع من إعدادات الهاتف.');
       }else{
         final position=await Geolocator.getCurrentPosition(locationSettings:const LocationSettings(accuracy:LocationAccuracy.bestForNavigation,timeLimit:Duration(seconds:30)));
         ready=position.accuracy<=50 && DateTime.now().difference(position.timestamp).inSeconds<=15;
         if(ready){lastGpsFix=DateTime.now();}
         else{message=tr('GPS signal is weak. Move outdoors and retry.','إشارة الموقع ضعيفة. انتقل إلى مكان مفتوح وأعد المحاولة.');}
       }
     }
   }catch(_){message=tr('Could not obtain a GPS fix. Move outdoors and retry.','تعذر الحصول على موقع دقيق. انتقل إلى مكان مفتوح وأعد المحاولة.');}
   if(!mounted)return;
   setState((){gpsReady=ready;gpsChecking=false;if(!ready)status=message;});
   if(displayDialog||!ready){
     await showDialog<void>(context:context,builder:(dialogContext)=>AlertDialog(
       title:Text(ready?tr('GPS is ready','الموقع جاهز'):tr('GPS required','الموقع مطلوب')),
       content:Text(ready?tr('GPS is working. Keep location enabled throughout your trip. Tracking while the app is closed or locked requires background tracking support.','الموقع يعمل. أبقِ خدمات الموقع مفعلة طوال الرحلة. التتبع عند قفل الهاتف يتطلب دعم العمل في الخلفية.'):message),
       actions:[
         TextButton(onPressed:()=>Navigator.pop(dialogContext),child:Text(tr('Close','إغلاق'))),
         if(!ready)TextButton(onPressed:(){Navigator.pop(dialogContext);Geolocator.openLocationSettings();},child:Text(tr('Location settings','إعدادات الموقع'))),
         if(!ready)TextButton(onPressed:(){Navigator.pop(dialogContext);Geolocator.openAppSettings();},child:Text(tr('App permissions','صلاحيات التطبيق'))),
         if(!ready)TextButton(onPressed:(){Navigator.pop(dialogContext);checkGps(displayDialog:true);},child:Text(tr('Retry','إعادة المحاولة'))),
       ],
     ));
   }
 }
 void startGpsWatchdog(){
   gpsWatchdog?.cancel();gpsWarningShown=false;
   gpsWatchdog=Timer.periodic(const Duration(seconds:20),(_)async{
     if(!mounted||tripId==null)return;
     final enabled=await Geolocator.isLocationServiceEnabled();
     final stale=lastGpsFix==null||DateTime.now().difference(lastGpsFix!).inSeconds>45;
     if(!enabled||stale){
       if(mounted)setState(()=>gpsReady=false);
       if(!gpsWarningShown){gpsWarningShown=true;if(mounted){setState(()=>status=tr('GPS signal lost during trip. Restore location services.','انقطعت إشارة الموقع أثناء الرحلة. أعد تشغيل الموقع.'));unawaited(nuqatiLog('GPS_WATCHDOG_STALE_FIX'));}}
     }else{gpsWarningShown=false;}
   });
 }
 Future<void> refreshGpsMonitor() async {
  if(privacyMode){if(mounted)setState(()=>status=tr('Turn off Privacy Mode to acquire GPS.','أوقف وضع الخصوصية لالتقاط GPS.'));return;}
  if(tripId!=null){
   // Never cancel background capture during a trip, to avoid losing evidence.
   if(mounted)setState(()=>status=tr('GPS recording continues. Move outdoors and check phone location settings.','يستمر تسجيل GPS. انتقل إلى مكان مفتوح وتحقق من إعدادات الموقع.'));
   await checkGps(displayDialog:true);return;
  }
  await positionSubscription?.cancel();positionSubscription=null;
  await nuqatiLog('GPS_MONITOR_REFRESH_REQUESTED');
  if(!await Geolocator.isLocationServiceEnabled()){
   if(mounted)setState(()=>status=tr('Phone location is OFF. Enable it in settings.','الموقع مغلق على الهاتف. شغّله من الإعدادات.'));
   return;
  }
  final permission=await Geolocator.checkPermission();
  if(permission!=LocationPermission.always&&permission!=LocationPermission.whileInUse){
   await checkGps(displayDialog:true);return;
  }
  startLocalMonitoring();
  await ensureAutomaticMonitoring();
  if(mounted)setState(()=>status=tr('GPS monitor refreshed. Waiting for an accurate fix outdoors.','تم تحديث مراقبة GPS. جارٍ انتظار إشارة دقيقة في مكان مفتوح.'));
  // Rechecking fix is informational; it never clears the SQLite queue.
  unawaited(checkGps());
 }
 void startLocalMonitoring(){
   positionSubscription?.cancel();lastPosition=null;lastTime=null;
   positionSubscription=Geolocator.getPositionStream(locationSettings:AndroidSettings(accuracy:LocationAccuracy.high,distanceFilter:0,intervalDuration:const Duration(seconds:3))).listen((p){evaluate(p);},onError:(Object e){if(mounted)setState(()=>status='GPS monitoring: $e');});
 }

 int? tripId; Timer? timer; Position? lastPosition; DateTime? lastTime; bool busy=false; Map<String,dynamic>? report;
 Map<String,String> get headers=>{'Content-Type':'application/json',if(token.isNotEmpty)'Authorization':'Bearer $token'};
 Future<Map<String,dynamic>> call(String path,{String method='GET',Object? body}) async{
  final uri=Uri.parse('$api$path'); final r=await (method=='POST'?http.post(uri,headers:headers,body:jsonEncode(body??{})):http.get(uri,headers:headers)).timeout(const Duration(seconds:15));
  Map<String,dynamic> data;
  try {data=jsonDecode(r.body) as Map<String,dynamic>;}catch(_){throw Exception('Server returned HTTP ${r.statusCode} (non-JSON response)');}
  if(r.statusCode>=400)throw Exception(data['detail']??'HTTP ${r.statusCode}');return data;
 }
 Future<void> restoreNotificationPreference() async {
  final saved=await _secureStore.read(key:'nuqati_alerts_enabled');
  if(mounted)setState(()=>notificationsEnabled=saved!='0');
  unawaited(syncNotificationEvidence());
 }
 Future<void> setNotificationPreference(bool enabled) async {
  await _secureStore.write(key:'nuqati_alerts_enabled',value:enabled?'1':'0');
  final now=DateTime.now().toUtc();
  final db=await openTrackingDatabase();
  await db.insert('notification_evidence_queue',{
   'event_id':'alert_${now.microsecondsSinceEpoch}_${enabled?1:0}',
   'notifications_enabled':enabled?1:0,'selected_at':now.toIso8601String(),
  },conflictAlgorithm:ConflictAlgorithm.ignore);
  if(mounted)setState(()=>notificationsEnabled=enabled);
  unawaited(syncNotificationEvidence());
 }
 Future<void> remindNotificationsAtTripStart() async {
  if(notificationReminderShowing||!mounted)return;
  final optedIn=(await _secureStore.read(key:'nuqati_alerts_enabled'))!='0';
  final allowed=(await ph.Permission.notification.status).isGranted;
  if(optedIn&&allowed)return;
  notificationReminderShowing=true;
  try {
   if(!mounted)return;
   await showDialog<void>(context:context,builder:(ctx)=>AlertDialog(
    title:Text(tr('Driving safety alerts are off','تنبيهات سلامة القيادة متوقفة')),
    content:Text(tr('A trip has started. Enable safety notifications in Settings to receive driving warnings. GPS tracking and scoring continue when alerts are off.','بدأت رحلة. يمكنك تفعيل تنبيهات السلامة من الإعدادات لاستقبال التحذيرات. يستمر تتبع GPS واحتساب النقاط عند إيقاف التنبيهات.')),
    actions:[
      TextButton(onPressed:()=>Navigator.pop(ctx),child:Text(tr('Later','لاحقاً'))),
      TextButton(onPressed:()async{Navigator.pop(ctx);if(!optedIn)await setNotificationPreference(true);if(!allowed)await Geolocator.openAppSettings();},child:Text(tr('Enable alerts','تفعيل التنبيهات'))),
    ],
   ));
  }finally{notificationReminderShowing=false;}
 }
 Future<void> restorePrivacyState() async {
  final enabled=(await _secureStore.read(key:'nuqati_privacy_mode'))=='1';
  if(mounted)setState(()=>privacyMode=enabled);
  if(!enabled)unawaited(ensureAutomaticMonitoring());
 }
 Future<void> togglePrivacy() async {
  if(busy)return;
  setState(()=>busy=true);
  try {
   final enable=!privacyMode;
   if(enable){
    final id=await locallyActiveTrip();
    if(id!=null){await (await openTrackingDatabase()).update('local_trips',{'ended_at':DateTime.now().toUtc().toIso8601String()},where:'local_id = ? AND ended_at IS NULL',whereArgs:[id]);}
   }
   await queuePrivacyEvidence(enable);
   await setFullPrivacy(enable);
   unawaited(syncPrivacyEvidence());
   await positionSubscription?.cancel();positionSubscription=null;
   gpsWatchdog?.cancel();gpsWatchdog=null;
   if(mounted)setState((){privacyMode=enable;tripId=null;status=enable?'Privacy Mode ON: GPS and movement detection disabled.':'Privacy Mode OFF: automatic monitoring enabled.';});
  }catch(e,s){await nuqatiLog('PRIVACY_TOGGLE_FAILED',e,s);if(mounted)setState(()=>status='Privacy Mode error: $e');}
  finally{if(mounted)setState(()=>busy=false);}
 }
 Future<void> saveOfflineProfile() async {
  await _secureStore.write(key:'nuqati_offline_profile',value:jsonEncode({
   'name':name,'plate':plate,'company':company,'vehicleModel':vehicleModel,'vehicleDoor':vehicleDoor,'vehicleYear':vehicleYear,'phone':phone,'logoData':logoData,
  }));
 }
 Future<void> enterSavedSession(String saved,{required bool offline}) async {
  final raw=await _secureStore.read(key:'nuqati_offline_profile');
  if(raw==null||raw.isEmpty)throw Exception('First complete one online login with Remember me enabled.');
  final profile=jsonDecode(raw) as Map<String,dynamic>;
  if(!mounted)return;
  setState((){token=saved;rememberMe=true;name=(profile['name']??'Driver').toString();
   plate=(profile['plate']??'Not assigned').toString();company=(profile['company']??'').toString();vehicleModel=(profile['vehicleModel']??'').toString();vehicleDoor=(profile['vehicleDoor']??'').toString();vehicleYear=(profile['vehicleYear']??'').toString();
   phone=(profile['phone']??'').toString();logoData=(profile['logoData']??'').toString();
   status=offline?'Offline session restored. Trips are saved locally until connection returns.':'Session restored';});
  unawaited(syncDrivingPolicy());
  policyTimer?.cancel();policyTimer=Timer.periodic(const Duration(seconds:60),(_){syncDrivingPolicy();});startLivePositionRequestPolling();
  if(!privacyMode){await restoreActiveTrip();await ensureAutomaticMonitoring();}
  unawaited(syncPendingTripsOnce());unawaited(syncPrivacyEvidence());await requestTrackingConsentIfNeeded();if(mounted)unawaited(refreshVehicleCare());if(mounted)unawaited(refreshSmartOil());
 }
 Future<void> restoreSavedSession() async {
  try {
   final saved=await _secureStore.read(key:'nuqati_driver_access_token');
   if(saved==null||saved.isEmpty||!mounted)return;
   if(await _secureStore.read(key:'nuqati_remember_me')!='1')return;
   // Local restoration must not depend on DNS, mobile data, or API availability.
   await enterSavedSession(saved,offline:true);
   try {
    final me=await call('/api/v1/mobile/me');
    Map<String,dynamic> branding={};try{branding=await call('/api/v1/mobile/branding');}catch(_){}
    if(!mounted)return;
    setState((){name=(me['full_name']??name).toString();plate=(me['vehicle']?['plate_number']??plate).toString();
     company=(me['company_name']??branding['company_name']??company).toString();vehicleModel=(me['vehicle']?['make_model']??'').toString();vehicleDoor=(me['vehicle']?['door_number']??'').toString();vehicleYear=(me['vehicle']?['year']??'').toString();phone=(me['phone']??me['phone_number']??phone).toString();
     logoData=(branding['logo_data']??logoData).toString();status='Session restored and verified online';});
    await _secureStore.write(key:'nuqati_driver_company_id',value:me['company_id'].toString());
    await saveOfflineProfile();
   }catch(e){await nuqatiLog('SESSION_ONLINE_VERIFY_UNAVAILABLE',e);}
  }catch(e,s){await nuqatiLog('SESSION_RESTORE_FAILED',e,s);if(mounted)setState(()=>status='Saved session unavailable: $e');}
 }
 Future<void> restoreActiveTrip() async {
  if(token.isEmpty||privacyMode)return;
  final local=await locallyActiveTrip();
  if(local!=null){
   if(!mounted)return;
   setState((){tripId=local;liveTripKmId=local;liveTripKm=0;status='Active trip restored from phone storage';});FlutterBackgroundService().invoke('liveDistanceRequest');
   await _restoreLocalTripScore(local);await _loadSafetyCounts(local);
   startLocalMonitoring();startGpsWatchdog();await startBackgroundTrip(local);
   return;
  }
  try {
   final data=await call('/api/v1/mobile/trips/active');
   if(data['active']!=true)return;
   final pending=await (await openTrackingDatabase()).query('local_trips',where:'ended_at IS NOT NULL',limit:1);
   if(pending.isNotEmpty)return;
   final remote=(data['trip_id'] as num).toInt();
   final db=await openTrackingDatabase();
   final existing=await db.query('local_trips',where:'remote_id = ?',whereArgs:[remote],limit:1);
   final id=existing.isNotEmpty?existing.first['local_id'] as int:DateTime.now().microsecondsSinceEpoch;
   if(existing.isEmpty)await db.insert('local_trips',{'local_id':id,'remote_id':remote,'started_at':DateTime.now().toUtc().toIso8601String(),'ended_at':null});
   if(!mounted)return;
   setState((){tripId=id;status='Active server trip restored';});
   await _restoreLocalTripScore(id);await _loadSafetyCounts(id);
   startLocalMonitoring();startGpsWatchdog();await startBackgroundTrip(id);unawaited(remindNotificationsAtTripStart());
  }catch(e){await nuqatiLog('RESTORE_REMOTE_TRIP_FAILED',e);}
 }
 Future<void> login()async{if(busy)return;setState(()=>busy=true);try{
  final r=await call('/api/v1/auth/driver-iqama-login',method:'POST',body:{'iqama':iqama.text.trim(),'password':password.text});
  if(r['user']['role']!='driver')throw Exception('This account is not a driver');token=r['access_token'];
  await _secureStore.write(key:'nuqati_driver_access_token',value:token);
  await _secureStore.write(key:'nuqati_remember_me',value:rememberMe?'1':'0');
  final me=await call('/api/v1/mobile/me');await _secureStore.write(key:'nuqati_driver_company_id',value:me['company_id'].toString());unawaited(call('/api/v1/mobile/login-ack',method:'POST').catchError((Object e)=> <String,dynamic>{}));
  Map<String,dynamic> branding={};try{branding=await call('/api/v1/mobile/branding');}catch(_){}
  if(mounted)setState((){name=me['full_name']??r['user']['full_name']??'Driver';plate=me['vehicle']?['plate_number']??'Not assigned';company=(me['company_name']??branding['company_name']??'').toString();vehicleModel=(me['vehicle']?['make_model']??'').toString();vehicleDoor=(me['vehicle']?['door_number']??'').toString();vehicleYear=(me['vehicle']?['year']??'').toString();phone=(me['phone']??me['phone_number']??'').toString();logoData=branding['logo_data']??'';status='Signed in successfully';password.clear();});
  if(rememberMe)await saveOfflineProfile();
  unawaited(syncDrivingPolicy());policyTimer?.cancel();policyTimer=Timer.periodic(const Duration(seconds:60),(_){syncDrivingPolicy();});startLivePositionRequestPolling();if(!privacyMode){await restoreActiveTrip();await ensureAutomaticMonitoring();}unawaited(syncPendingTripsOnce());unawaited(syncPrivacyEvidence());await requestTrackingConsentIfNeeded();if(mounted)unawaited(refreshVehicleCare());
 }catch(e){
  // Only a previously authenticated, opted-in driver may restore an offline session.
  final saved=await _secureStore.read(key:'nuqati_driver_access_token');
  final optedIn=await _secureStore.read(key:'nuqati_remember_me')=='1';
  final networkFailure=e is SocketException || e is TimeoutException || e is http.ClientException ||
   e.toString().contains('Failed host lookup') || e.toString().contains('SocketException');
  if(networkFailure&&optedIn&&saved!=null&&saved.isNotEmpty){
   try{await enterSavedSession(saved,offline:true);}catch(error){if(mounted)setState(()=>status='$error');}
  }else if(mounted){setState(()=>status='$e');}
 }finally{if(mounted)setState(()=>busy=false);}}
 Future<void> restoreVehicleCareCache()async{
  try{final raw=await _secureStore.read(key:'nuqati_vehicle_care_cache');if(raw==null)return;
   final data=jsonDecode(raw) as Map<String,dynamic>;
   if(!mounted)return;
   setState((){displayedOdometer=(data['odometer_km'] as num?)?.toDouble();careReminders=((data['maintenance'] as List?)??[]).where((x)=>x is Map&&(x['status']=='DUE_SOON'||x['status']=='OVERDUE')).toList();monthlyOdometerDue=data['first_odometer_due']==true;initialHistoryDue=data['initial_history_due']==true;});
  }catch(_){ }
 }
 Future<void> refreshSmartOil() async {
  if(token.isEmpty)return;
  try{
   final result=await call('/api/v1/mobile/smart-oil');
   if(mounted)setState(()=>smartOil=result);
  }catch(e){await nuqatiLog('SMART_OIL_FETCH_FAILED',e);}
 }
 Widget smartOilWarning(){
  final oil=smartOil!;
  final actual=(oil['original_next_due_km'] as num).toDouble()-(displayedOdometer??(oil['current_odometer_km'] as num).toDouble())-(tripId!=null&&liveTripKmId==tripId?liveTripKm:0);
  final smart=(oil['pilot_allowance_remaining_km'] as num).toDouble()-(tripId!=null&&liveTripKmId==tripId?liveTripKm:0);
  final enough=oil['status']=='estimate_available';
  final overdue=actual<=0||(enough&&smart<=0);
  return panel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
   Row(children:[const Icon(Icons.oil_barrel,color:lime),const SizedBox(width:8),Expanded(child:Text('Smart Oil Life Estimator',style:const TextStyle(color:lime,fontWeight:FontWeight.bold)))]),
   const SizedBox(height:8),Text(tr(overdue?'Oil change due':'Oil change approaching',overdue?'حان موعد تغيير زيت المحرك':'اقترب موعد تغيير زيت المحرك'),style:TextStyle(color:overdue?Colors.redAccent:Colors.orangeAccent,fontWeight:FontWeight.bold)),
   const SizedBox(height:7),Text('${tr('Actual scheduled remaining','المتبقي حسب جدول الصيانة')}: ${actual<=0?tr('Overdue by','متأخر بمقدار'):''} ${actual.abs().toStringAsFixed(0)} km',style:const TextStyle(color:Colors.white)),
   if(enough)Text('${tr('Smart estimated remaining','المتبقي بالتقدير الذكي')}: ${smart<=0?tr('Overdue by','متأخر بمقدار'):''} ${smart.abs().toStringAsFixed(0)} km',style:const TextStyle(color:Colors.white70)),
   const SizedBox(height:7),Text(tr('Smart estimate is advisory; GPS stationary time is not measured engine idling.','التقدير الذكي إرشادي؛ التوقف عبر GPS لا يعني بالضرورة دوران المحرك.'),style:const TextStyle(color:Colors.white60,fontSize:11)),
  ]));
 }
 bool get shouldShowSmartOil {
  final oil=smartOil;
  if(oil==null||oil['original_next_due_km'] is! num||oil['current_odometer_km'] is! num||oil['pilot_allowance_remaining_km'] is! num)return false;
  final live=tripId!=null&&liveTripKmId==tripId?liveTripKm:0.0;
  final actual=(oil['original_next_due_km'] as num).toDouble()-(displayedOdometer??(oil['current_odometer_km'] as num).toDouble())-live;
  final smart=(oil['pilot_allowance_remaining_km'] as num).toDouble()-live;
  return actual<=500||(oil['status']=='estimate_available'&&smart<=500);
 }
 Future<void> refreshVehicleCare({bool askMonthly=true}) async {
  if(token.isEmpty||careBusy)return;
  careBusy=true;
  try {
   final result=await call('/api/v1/mobile/vehicle-care');
   if(!mounted)return;
   await _secureStore.write(key:'nuqati_vehicle_care_cache',value:jsonEncode(result));
   final nextOdometer=(result['odometer_km'] as num?)?.toDouble();
   final nextReminders=(result['maintenance'] as List?)??[];
   final due=result['first_odometer_due']==true;
   setState((){displayedOdometer=nextOdometer;careReminders=nextReminders.where((x)=>x is Map && (x['status']=='DUE_SOON'||x['status']=='OVERDUE')).toList();monthlyOdometerDue=due;initialHistoryDue=result['initial_history_due']==true;careLastFetch=DateTime.now();});unawaited(refreshSmartOil());
   if(result['initial_history_due']==true && !historyPromptShowing && mounted){
     historyPromptShowing=true;
     WidgetsBinding.instance.addPostFrameCallback((_) async {
       try {
         // Permissions and Android settings may resume the app while its first-run
         // dialog is still mounted. Never stack the maintenance dialog on it.
         for(var attempt=0;attempt<60 && mounted;attempt++){
           final route=ModalRoute.of(context);
           if(!permissionPromptInProgress && (route==null || route.isCurrent))break;
           await Future<void>.delayed(const Duration(milliseconds:250));
         }
         if(!mounted || permissionPromptInProgress || (ModalRoute.of(context)?.isCurrent==false))return;
         await showInitialServiceHistory();
       } catch(e,s) { await nuqatiLog('INITIAL_MAINTENANCE_DIALOG_FAILED',e,s); }
       finally{historyPromptShowing=false;}
     });
   }
   // Ask once when the driver first registers an odometer reading, not monthly.
   // For each new due/overdue maintenance cycle, offer another reading correction.
   if(askMonthly && result['initial_history_due']!=true && !historyPromptShowing&&!monthlyPromptShowing&&!odometerPromptChecking&&mounted){
    odometerPromptChecking=true;
    try {
     String? promptKey;
     if(due){promptKey='first:${result['vehicle_id']}';}
     else {
      for(final service in nextReminders){
       if(service is! Map || (service['status']!='OVERDUE'&&service['status']!='DUE_SOON'))continue;
       final key='due:${result['vehicle_id']}:${service['id']}:${service['last_service_km']}:${service['next_due_km']}';
       if(await _secureStore.read(key:'nuqati_odometer_prompt_$key')!='1'){promptKey=key;break;}
      }
     }
     if(promptKey!=null&&mounted){
      final key=promptKey;
      monthlyPromptShowing=true;
      WidgetsBinding.instance.addPostFrameCallback((_)async{
       try {
        for(var attempt=0;attempt<60 && mounted;attempt++){
          if(!permissionPromptInProgress && !historyPromptShowing && (ModalRoute.of(context)?.isCurrent!=false))break;
          await Future<void>.delayed(const Duration(milliseconds:250));
        }
        if(!mounted || permissionPromptInProgress || historyPromptShowing || ModalRoute.of(context)?.isCurrent==false)return;
        await showOdometerDialog(monthly:false);
        // Due/overdue prompts are shown once per service cycle.
        if(!due)await _secureStore.write(key:'nuqati_odometer_prompt_$key',value:'1');
       }catch(e,s){await nuqatiLog('ODOMETER_DIALOG_FAILED',e,s);}
       finally{monthlyPromptShowing=false;}
      });
     }
    }finally{odometerPromptChecking=false;}
   }
  }catch(e){await nuqatiLog('VEHICLE_CARE_FETCH_FAILED',e);}
  finally{careBusy=false;}
 }
 Future<void> showInitialServiceHistory() async {
  if(!mounted || token.isEmpty) return;
  final odo=TextEditingController(text:displayedOdometer?.toStringAsFixed(0)??'');
  const services=['ENGINE_OIL','SPARK_PLUGS','TRANSMISSION_OIL','TYRES'];
  final values={for(final service in services)service:TextEditingController()};
  final knowledge={for(final service in services)service:false};
  final readingType={for(final service in services)service:'LAST'};
  int oilInterval=5000;
  String? errorText;
  bool sending=false;
  String serviceTitle(String service){
    switch(service){
     case 'ENGINE_OIL':return tr('Engine oil','زيت المحرك');
     case 'SPARK_PLUGS':return tr('Spark plugs','البواجي');
     case 'TRANSMISSION_OIL':return tr('Gear oil','زيت القير');
     default:return tr('Tyres','الإطارات');
    }
  }
  bool initialHistorySaved=false;
  try{
   initialHistorySaved=await showDialog<bool>(context:context,barrierDismissible:false,builder:(context)=>StatefulBuilder(builder:(ctx,update){
    return AlertDialog(
     title:Text(tr('Initial vehicle maintenance details','معلومات صيانة المركبة لأول مرة')),
     content:SizedBox(width:420,child:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,crossAxisAlignment:CrossAxisAlignment.start,children:[
       Text(tr('Enter the actual odometer. For each service, choose I don’t know or provide the last change / next due mileage. No unknown values will be guessed.','أدخل العداد الفعلي. لكل صيانة اختر لا أعرف أو أدخل عداد آخر تغيير أو موعد التغيير القادم. لن يتم تخمين القيم المجهولة.')),
       const SizedBox(height:12),TextField(controller:odo,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:InputDecoration(labelText:tr('Current odometer (km)','العداد الحالي (كم)'))),
       for(final service in services)...[
        const Divider(height:24),Text(serviceTitle(service),style:const TextStyle(fontWeight:FontWeight.bold)),
        SwitchListTile(contentPadding:EdgeInsets.zero,title:Text(tr('I know the service mileage','أعرف عداد الصيانة')),subtitle:Text(knowledge[service]! ? tr('Enter accurate details','أدخل المعلومات الصحيحة'):tr('I do not know — record as unknown','لا أعرف — سجلها كمجهولة')),
          value:knowledge[service]!,onChanged:(v)=>update(()=>knowledge[service]=v)),
        if(knowledge[service]!)...[
         DropdownButtonFormField<String>(value:readingType[service],decoration:InputDecoration(labelText:tr('Mileage provided','نوع قراءة العداد')),items:[
          DropdownMenuItem(value:'LAST',child:Text(tr('Last changed at (km)','آخر تغيير عند (كم)'))),
          DropdownMenuItem(value:'NEXT',child:Text(tr('Next change at (km)','التغيير القادم عند (كم)'))),
         ],onChanged:(v){if(v!=null)update(()=>readingType[service]=v);}),
         TextField(controller:values[service],keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:InputDecoration(labelText:tr('Odometer (km)','العداد (كم)'))),
         if(service=='ENGINE_OIL')DropdownButtonFormField<int>(value:oilInterval,decoration:InputDecoration(labelText:tr('Oil type / change interval','نوع الزيت / فترة التغيير')),items:[
          DropdownMenuItem(value:5000,child:Text(tr('5,000 km oil','زيت ٥٠٠٠ كم'))),
          DropdownMenuItem(value:10000,child:Text(tr('10,000 km oil','زيت ١٠٠٠٠ كم')))
         ],onChanged:(v){if(v!=null)update(()=>oilInterval=v);}),
        ],
       ],
       if(errorText!=null)Padding(padding:const EdgeInsets.only(top:12),child:Text(errorText!,style:const TextStyle(color:Colors.redAccent))),
     ]))),
     actions:[
       TextButton(onPressed:sending?null:()=>Navigator.pop(ctx),child:Text(tr('Later','لاحقًا'))),
       FilledButton(onPressed:sending?null:()async{
        final km=double.tryParse(odo.text.trim());
        if(km==null || km<0){update(()=>errorText=tr('Enter a valid current odometer','أدخل قراءة عداد صحيحة'));return;}
        final entries=<Map<String,dynamic>>[];
        for(final service in services){
         if(!knowledge[service]!){entries.add({'service_type':service,'knowledge':'UNKNOWN'});continue;}
         final reading=double.tryParse(values[service]!.text.trim());
         if(reading==null || reading<0){update(()=>errorText='${serviceTitle(service)}: ${tr('Enter a valid mileage','أدخل عداد صحيح')}');return;}
         entries.add({'service_type':service,'knowledge':'KNOWN','reading_type':readingType[service],
          'reading_km':reading,'oil_interval_km':service=='ENGINE_OIL'?oilInterval:null});
        }
        update((){sending=true;errorText=null;});
        try{
         await call('/api/v1/mobile/vehicle-care/initial-history',method:'POST',body:{'odometer_km':km,'services':entries});
         // Return the result without modifying parent state while this route exits.
         // The parent refresh happens only after the dialog has fully disappeared.
         if(ctx.mounted)Navigator.of(ctx).pop(true);
         return;
        }catch(e){if(ctx.mounted){update((){sending=false;errorText=e.toString();});}}
       },child:Text(tr('Save details','حفظ المعلومات')))
     ],
    );
   })) == true;
  }finally{
   // Allow the reverse dialog transition to finish before disposing TextFields.
   await Future<void>.delayed(const Duration(milliseconds:700));
   odo.dispose();for(final controller in values.values){controller.dispose();}
  }
  if(initialHistorySaved && mounted){
   ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(tr('Vehicle maintenance information saved','تم حفظ معلومات صيانة المركبة'))));
   // Refresh only after the dialog's inherited widgets are fully unmounted.
   await refreshVehicleCare(askMonthly:false);
  }
 }
 Future<void> showOdometerDialog({bool monthly=false})async{
  if(!mounted||token.isEmpty)return;
  final ctrl=TextEditingController(text:displayedOdometer?.toStringAsFixed(0)??'');
  try{
   final reading=await showDialog<double>(context:context,builder:(ctx)=>AlertDialog(
    title:Text(tr(monthly?'Monthly odometer update':'Update odometer',monthly?'تحديث العداد الشهري':'تحديث عداد المركبة')),
    content:Column(mainAxisSize:MainAxisSize.min,children:[Text(tr('Enter your actual dashboard odometer in kilometres. Do not enter trip distance.','أدخل قراءة عداد السيارة الفعلية بالكيلومتر، وليس مسافة الرحلة.')),TextField(controller:ctrl,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:InputDecoration(labelText:tr('Odometer (km)','العداد (كم)')))]),
    actions:[TextButton(onPressed:()=>Navigator.pop(ctx),child:Text(tr('Later','لاحقًا'))),FilledButton(onPressed:(){final value=double.tryParse(ctrl.text.trim());if(value==null||value<0){return;}Navigator.pop(ctx,value);},child:Text(tr('Save','حفظ')))]));
   if(reading==null||!mounted)return;
   await Future<void>.delayed(const Duration(milliseconds:450));
   if(!mounted)return;
   await call('/api/v1/mobile/vehicle-care/odometer',method:'POST',body:{'reading_km':reading});
   if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(tr('Odometer saved on server','تم حفظ العداد على الخادم'))));
   await refreshVehicleCare(askMonthly:false);
  }catch(e){if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text('${tr('Could not save odometer','تعذر حفظ العداد')}: $e')));}
  finally{ctrl.dispose();}
 }
 Future<void> confirmServiceCompletion(Map<String,dynamic> service)async{
  if(token.isEmpty||!mounted)return;
  final id=(service['id'] as num?)?.toInt();if(id==null)return;
  final ctrl=TextEditingController(text:displayedOdometer?.toStringAsFixed(0)??'');
  try{
   final km=await showDialog<double>(context:context,builder:(ctx)=>AlertDialog(
    title:Text(tr('Confirm maintenance completed','تأكيد إتمام الصيانة')),
    content:Column(mainAxisSize:MainAxisSize.min,children:[Text('${service['service_type']} — ${tr('Only confirm if the service was actually completed. Enter the actual odometer.','أكد فقط إذا اكتملت الصيانة فعليًا، وأدخل قراءة العداد الفعلية.')}'),TextField(controller:ctrl,keyboardType:const TextInputType.numberWithOptions(decimal:true),decoration:InputDecoration(labelText:tr('Service odometer (km)','عداد الصيانة (كم)')))]),
    actions:[TextButton(onPressed:()=>Navigator.pop(ctx),child:Text(tr('Cancel','إلغاء'))),FilledButton(onPressed:(){final n=double.tryParse(ctrl.text.trim());if(n!=null&&n>=0)Navigator.pop(ctx,n);},child:Text(tr('Service completed','تمت الصيانة')))]));
   if(km==null)return;
   await call('/api/v1/mobile/vehicle-care/maintenance/$id/complete',method:'POST',body:{'confirmed':true,'reading_km':km});
   if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(tr('Service saved. Next maintenance interval started.','تم حفظ الصيانة وبدء دورة الصيانة التالية.'))));
   await refreshVehicleCare(askMonthly:false);
  }catch(e){if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text('${tr('Could not confirm maintenance','تعذر تأكيد الصيانة')}: $e')));}
  finally{ctrl.dispose();}
 }
 Widget maintenanceDriverCard()=>panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
  Row(children:[const Icon(Icons.build_circle_outlined,color:Colors.redAccent),const SizedBox(width:8),Expanded(child:Text(tr('Maintenance due / overdue','صيانة مستحقة / متأخرة'),style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold))),IconButton(onPressed:()=>refreshVehicleCare(askMonthly:false),icon:const Icon(Icons.refresh,color:Colors.white))]),
  ...careReminders.map((item){final m=Map<String,dynamic>.from(item as Map);final overdue=m['status']=='OVERDUE';return Padding(padding:const EdgeInsets.only(top:10),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text('${m['service_type']} · ${overdue?tr('OVERDUE','متأخرة'):tr('DUE SOON','قريبة الاستحقاق')} · ${m['remaining_km']} km',style:const TextStyle(color:Colors.redAccent,fontSize:12,fontWeight:FontWeight.bold)),Align(alignment:Alignment.centerRight,child:TextButton(onPressed:()=>confirmServiceCompletion(m),child:Text(tr('Done — confirm service','تم — تأكيد الصيانة'),style:const TextStyle(color:lime))))]));}),
 ]));
 Future<void> refresh()async{if(token.isEmpty)return;try{final r=await call('/api/v1/fleet/report?period=daily');if(mounted)setState(()=>report=r);}catch(_){}}
 Future<void> changePassword()async{try{await call('/api/v1/mobile/change-password',method:'POST',body:{'current_password':oldPassword.text,'new_password':newPassword.text});oldPassword.clear();newPassword.clear();if(mounted)setState(()=>status='Password changed');}catch(e){if(mounted)setState(()=>status='$e');}}
 Future<void> uploadFix(Position pos) async {
   final id=tripId;
   if(id==null||uploadingFix||pos.accuracy>50)return;
   final stamp=pos.timestamp;
   if(lastUploadedFix!=null&&stamp.difference(lastUploadedFix!).inMilliseconds<900)return;
   if(DateTime.now().difference(stamp).inSeconds>15)return;
   uploadingFix=true;
   try {
     double accel=0;
     if(lastUploadPosition!=null&&lastUploadedFix!=null){
       final secs=stamp.difference(lastUploadedFix!).inMilliseconds/1000;
       if(secs>0)accel=((pos.speed-lastUploadPosition!.speed)/secs).clamp(-30.0,30.0);
     }
     await call('/api/v1/mobile/trips/$id/sample',method:'POST',body:{
       'latitude':pos.latitude,'longitude':pos.longitude,'accuracy_m':pos.accuracy,
       'speed_kmh':pos.speed<0?0:pos.speed*3.6,'acceleration_ms2':accel,
       'gps_age_seconds':DateTime.now().difference(stamp).inMilliseconds.clamp(0,3600000)/1000
     });
     lastUploadedFix=stamp;lastUploadPosition=pos;
     if(mounted)setState(()=>status='GPS recorded · ${pos.accuracy.round()} m accuracy');
   }catch(e){if(mounted)setState(()=>status='GPS upload failed: $e');}
   finally{uploadingFix=false;}
 }
 Position? lastUploadPosition;
 Future<void> sample() async {
   if(tripId==null||uploadingFix)return;
   try {final pos=await Geolocator.getCurrentPosition(locationSettings:const LocationSettings(accuracy:LocationAccuracy.high,timeLimit:Duration(seconds:15)));await uploadFix(pos);}
   catch(e){if(mounted)setState(()=>status='GPS unavailable: $e');}
 }
 Future<void> start()async{
  if(busy||tripId!=null)return;
  // Do not block the trip for a 15-second cold-fix timeout. The foreground
  // tracking service starts acquisition and records only usable GPS samples.
  // Auto-start movement validation remains strict and unchanged.
  if(!await Geolocator.isLocationServiceEnabled()){
   if(mounted)setState(()=>status=tr('Turn on phone location to start recording.','شغّل موقع الهاتف لبدء التسجيل.'));
   return;
  }
  var permission=await Geolocator.checkPermission();
  if(permission==LocationPermission.denied)permission=await Geolocator.requestPermission();
  if(permission==LocationPermission.denied||permission==LocationPermission.deniedForever){
   if(mounted)setState(()=>status=tr('Allow location access to start recording.','اسمح بالوصول إلى الموقع لبدء التسجيل.'));
   return;
  }
  setState(()=>busy=true);
  try{
   final db=await openTrackingDatabase();
   final id=DateTime.now().microsecondsSinceEpoch;
   await db.insert('local_trips',{'local_id':id,'remote_id':null,'started_at':DateTime.now().toUtc().toIso8601String(),'ended_at':null});
   if(mounted)setState((){liveTripKm=0;liveTripKmId=id;tripId=id;completedTrip=false;officialFeedback='';localTripFeedback='';officialRag=null;officialPollTimer?.cancel();tripEndRemaining=null;status='Trip recording locally (syncs when online)';score=100;officialScoreReady=false;officialLowerBetter=false;officialScoreBreakdown=null;speedKmh=0;accelerationKmhS=0;speedingCount=0;brakingCount=0;accelerationCount=0;corneringCount=0;severeCount=0;lastLocalViolationAt=null;lastLocalHeading=null;lastLocalHeadingAt=null;unawaited(_clearLocalTripScore());alert='Safe trip started. Keep it green!';tab=0;});
   startLocalMonitoring();startGpsWatchdog();await startBackgroundTrip(id);
   if(mounted&&!gpsReady)setState(()=>status=tr('Trip started. Acquiring GPS outdoors; points will record when a valid fix arrives.','بدأت الرحلة. جارٍ التقاط إشارة GPS في مكان مفتوح؛ يبدأ تسجيل النقاط عند توفر موقع دقيق.'));
  }catch(e,s){await nuqatiLog('START_LOCAL_FAILED',e,s);if(mounted)setState(()=>status='Start failed: $e');}
  finally{if(mounted)setState(()=>busy=false);}
 }
 Future<void> finish()async{
  if(busy)return;
  final id=tripId??await locallyActiveTrip();
  if(id==null)return;
  if(mounted)setState(()=>busy=true);
  try{
   final db=await openTrackingDatabase();
   await db.update('local_trips',{'ended_at':DateTime.now().toUtc().toIso8601String()},where:'local_id = ?',whereArgs:[id]);
   await stopBackgroundTrip();
   timer?.cancel();timer=null;livePositionRequestTimer?.cancel();livePositionRequestTimer=null;gpsWatchdog?.cancel();gpsWatchdog=null;
   await positionSubscription?.cancel();positionSubscription=null;
   if(mounted)setState((){tripId=null;completedTrip=true;lastEndedAt=DateTime.now().toUtc();tripEndRemaining=null;officialScoreReady=false;officialScoreBreakdown=null;status='Trip stopped and saved on phone. Pending data will sync when online.';});
   // A short-lived sync attempt is optional; local Stop never waits for internet.
   unawaited(syncPendingTripsOnce());
   // Locally persist the finished-trip score even without a backend connection.
   unawaited(() async {try{await nuqatiFinalizeLocalPoints(db,id,DateTime.now());await showLocalTripResult(id);}catch(e){await nuqatiLog('LOCAL_TRIP_FINALIZE_FAILED',e);}}());
  }catch(e,s){await nuqatiLog('STOP_LOCAL_FAILED',e,s);if(mounted)setState(()=>status='Stop failed: $e');}
  finally{if(mounted)setState(()=>busy=false);}
 }
 Future<void> logout()async{if(tripId!=null){setState(()=>status='Finish your active trip before logging out');return;}timer?.cancel();timer=null;livePositionRequestTimer?.cancel();livePositionRequestTimer=null;gpsWatchdog?.cancel();gpsWatchdog=null;positionSubscription?.cancel();positionSubscription=null;await cameraActivitySubscription?.cancel();cameraActivitySubscription=null;await _secureStore.delete(key:'nuqati_driver_access_token');await _secureStore.delete(key:'nuqati_remember_me');await _secureStore.delete(key:'nuqati_offline_profile');await _secureStore.delete(key:'nuqati_driver_company_id');await _secureStore.delete(key:'nuqati_driving_policy');await _secureStore.delete(key:'nuqati_vehicle_care_cache');setState((){token='';name='';plate='';company='';vehicleModel='';vehicleDoor='';vehicleYear='';logoData='';displayedOdometer=null;careReminders=[];monthlyOdometerDue=false;report=null;status='Signed out';});}
 String? _decodedLogoSource;
 Uint8List? _decodedLogoBytes;
 Uint8List? get logoBytes{
  if(logoData==_decodedLogoSource)return _decodedLogoBytes;
  _decodedLogoSource=logoData;
  _decodedLogoBytes=null;
  try{
   if(logoData.startsWith('data:image/') && logoData.length<450000){
    _decodedLogoBytes=base64Decode(logoData.split(',').last);
   }
  }catch(_){_decodedLogoBytes=null;}
  return _decodedLogoBytes;
 }
 Widget brand(){final bytes=logoBytes;return Column(children:[if(bytes!=null)Image.memory(bytes,height:90,fit:BoxFit.contain)else Container(width:88,height:88,padding:const EdgeInsets.all(14),decoration:BoxDecoration(color:lime.withOpacity(.13),borderRadius:BorderRadius.circular(24)),child:Image.asset('assets/nuqati_icon.png',fit:BoxFit.contain)),const SizedBox(height:12),Text(company.isNotEmpty?company:'NUQATI',textAlign:TextAlign.center,style:const TextStyle(color:Colors.white,fontSize:25,fontWeight:FontWeight.bold)),Text(tr('Fleet Driver Companion','رفيق سائق الأسطول'),style:const TextStyle(color:lime,fontSize:13)),const SizedBox(height:4),Text(tr('By Al-Riadah Workshop','من ورشة حلول الريادة'),textAlign:TextAlign.center,style:const TextStyle(color:Colors.white70,fontSize:11,fontWeight:FontWeight.w600))]);}
 Widget field(TextEditingController c,String label,{bool secret=false,bool numeric=false})=>TextField(controller:c,obscureText:secret,keyboardType:numeric?TextInputType.number:TextInputType.text,maxLength:numeric?10:null,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:label,labelStyle:const TextStyle(color:Colors.white70),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(12))));
 Widget action(String title,VoidCallback? onPressed,{bool secondary=false})=>SizedBox(width:double.infinity,height:50,child:ElevatedButton(onPressed:onPressed,style:ElevatedButton.styleFrom(backgroundColor:secondary?blue:lime,foregroundColor:secondary?Colors.white:navy,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(12))),child:Text(title,style:const TextStyle(fontWeight:FontWeight.bold))));

 Widget panel({required Widget child})=>Container(width:double.infinity,margin:const EdgeInsets.only(bottom:14),padding:const EdgeInsets.all(18),decoration:BoxDecoration(color:blue.withOpacity(.9),borderRadius:BorderRadius.circular(22),border:Border.all(color:Colors.white12)),child:child);
 Widget stat(String title,String value,IconData icon)=>Container(
  height:124,padding:const EdgeInsets.symmetric(vertical:12,horizontal:5),
  decoration:BoxDecoration(color:blue.withOpacity(.9),borderRadius:BorderRadius.circular(18),border:Border.all(color:Colors.white12)),
  child:Column(mainAxisAlignment:MainAxisAlignment.center,children:[Icon(icon,color:lime,size:24),const SizedBox(height:7),Text(value,style:const TextStyle(fontSize:25,fontWeight:FontWeight.w800,color:Colors.white)),const SizedBox(height:3),Text(title,textAlign:TextAlign.center,maxLines:2,overflow:TextOverflow.ellipsis,style:const TextStyle(fontSize:11,color:Colors.white70))]));
 Widget compactMetric(String label,String value,IconData icon)=>Container(padding:const EdgeInsets.symmetric(vertical:8,horizontal:3),decoration:BoxDecoration(color:navy.withOpacity(.55),borderRadius:BorderRadius.circular(12)),child:Column(children:[Icon(icon,color:lime,size:18),Text(value,style:const TextStyle(color:Colors.white,fontSize:20,fontWeight:FontWeight.bold)),Text(label,textAlign:TextAlign.center,maxLines:2,style:const TextStyle(color:Colors.white70,fontSize:10))]));
 Widget homeTab()=>Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
  panel(child:Column(children:[
   Row(children:[const CircleAvatar(radius:18,backgroundColor:lime,child:Icon(Icons.person,color:navy,size:20)),const SizedBox(width:10),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(name,maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold,fontSize:16)),if(company.isNotEmpty)Text('${tr('Company','الشركة')}: $company',maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:Colors.white70,fontSize:12)),Text('${tr('Vehicle','المركبة')}: $plate',maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:lime,fontSize:12)),if(vehicleModel.isNotEmpty||vehicleYear.isNotEmpty)Text('${tr('Model','الطراز')}: $vehicleModel${vehicleYear.isNotEmpty?' ($vehicleYear)':''}',maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:Colors.white70,fontSize:11)),if(vehicleDoor.isNotEmpty)Text('${tr('Door number','رقم الباب')}: $vehicleDoor',maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:Colors.white70,fontSize:11)),Text("${tr('Odometer','عداد المركبة')}: ${displayedOdometer==null?'—':(displayedOdometer!+(tripId!=null&&liveTripKmId==tripId?liveTripKm:0)).toStringAsFixed(1)} km${tripId!=null?' (${tr('live estimate','تقدير مباشر')})':''}",style:const TextStyle(color:Colors.white70,fontSize:11))])),Icon(gpsReady?Icons.gps_fixed:Icons.gps_off,color:gpsReady?lime:Colors.orangeAccent)]),
   const SizedBox(height:10),Row(children:[Icon(tripId!=null?Icons.directions_car:Icons.flag_outlined,color:lime,size:19),const SizedBox(width:7),Expanded(child:Text(tripStateLabel,style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold))),if(tripId!=null&&tripEndRemaining!=null)Text('${tr('Trip ending in','تنتهي الرحلة خلال')} $tripEndRemaining s',style:const TextStyle(color:Colors.orangeAccent,fontSize:12,fontWeight:FontWeight.bold))]),
   const SizedBox(height:8),Text(tr('MY SAFE TRIP','رحلتي الآمنة'),style:const TextStyle(color:lime,fontSize:13,fontWeight:FontWeight.bold)),
   const SizedBox(height:9),Center(child:SizedBox(width:154,height:154,child:Stack(alignment:Alignment.center,children:[
    SizedBox.expand(child:CircularProgressIndicator(value:(score/100).clamp(0.0,1.0),strokeWidth:12,backgroundColor:Colors.white12,valueColor:AlwaysStoppedAnimation<Color>(scoreColor),strokeCap:StrokeCap.round)),
    Column(mainAxisAlignment:MainAxisAlignment.center,children:[Text(officialScoreReady&&officialScoreBreakdown?['score']==null?'—':score.toStringAsFixed(officialScoreReady?1:0),style:TextStyle(color:scoreColor,fontSize:59,fontWeight:FontWeight.w900,height:1)),const SizedBox(height:4),Text(rating,style:TextStyle(color:scoreColor,fontSize:12,fontWeight:FontWeight.bold))])
   ]))),
   if(tripId!=null)Text(tr('LIVE POINTS · 2 per event / 3 per excessive event','النقاط المباشرة · نقطتان للحدث و٣ للشديد'),textAlign:TextAlign.center,style:const TextStyle(color:Colors.white70,fontSize:10)),
   if(tripId!=null)Padding(padding:const EdgeInsets.only(top:10),child:Wrap(alignment:WrapAlignment.center,spacing:7,runSpacing:7,children:[
    SizedBox(width:94,child:compactMetric(tr('Speeding','السرعة'),'$speedingCount',Icons.speed)),
    SizedBox(width:94,child:compactMetric(tr('Braking','الفرملة'),'$brakingCount',Icons.warning_amber)),
    SizedBox(width:94,child:compactMetric(tr('Acceleration','التسارع'),'$accelerationCount',Icons.trending_up)),
    SizedBox(width:94,child:compactMetric(tr('Cornering','الانعطاف'),'$corneringCount',Icons.turn_right)),
    SizedBox(width:94,child:compactMetric(tr('Excessive','شديد'),'$severeCount',Icons.priority_high)),
   ])),
   if(tripId==null&&completedTrip)Text(tr('FINAL LOCAL TRIP POINTS','نقاط الرحلة المحلية النهائية'),style:const TextStyle(color:lime,fontSize:11,fontWeight:FontWeight.bold)),
   if(tripId==null&&completedTrip)Text(tr('Trip points / 100 · App coaching only','نقاط الرحلة من ١٠٠ · التقييم المحلي'),textAlign:TextAlign.center,style:const TextStyle(color:Colors.white70,fontSize:10)),
   if(tripId==null&&completedTrip&&localTripFeedback.isNotEmpty)Padding(padding:const EdgeInsets.only(top:8),child:Text(localTripFeedback,textAlign:TextAlign.center,style:const TextStyle(color:Colors.white,fontSize:12))),
   if(alert.isNotEmpty)Text(alert,maxLines:2,overflow:TextOverflow.ellipsis,style:const TextStyle(color:Colors.white70,fontSize:11)),
  ])),
  if(careReminders.isNotEmpty)...[maintenanceDriverCard(),action(tr('Correct odometer reading','تصحيح قراءة العداد'),()=>showOdometerDialog())],
  if(monthlyOdometerDue)action(tr('Enter first odometer reading','أدخل قراءة العداد لأول مرة'),()=>showOdometerDialog()),
  if(shouldShowSmartOil)smartOilWarning(),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Row(children:[const Icon(Icons.shield_outlined,color:lime,size:18),const SizedBox(width:8),Expanded(child:Text(tr(privacyMode?'Privacy Mode ON':'Privacy Mode OFF',privacyMode?'وضع الخصوصية مفعّل':'وضع الخصوصية غير مفعّل'),style:const TextStyle(color:Colors.white,fontSize:13,fontWeight:FontWeight.bold))),Switch(value:privacyMode,onChanged:busy?null:(_)=>togglePrivacy(),activeColor:lime)]),Text(tr('ENABLE PRIVACY MODE','تفعيل وضع الخصوصية'),style:const TextStyle(color:Colors.white54,fontSize:10))])),
  if(tripId==null&&completedTrip)panel(child:Column(children:[Text(tr('Local driving events · independent of backend RAG','أحداث القيادة المحلية · منفصلة عن تقييم الخادم'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:8),Wrap(spacing:6,runSpacing:6,children:[SizedBox(width:125,child:compactMetric(tr('Speeding','تجاوز السرعة'),'$speedingCount',Icons.speed)),SizedBox(width:125,child:compactMetric(tr('Braking','فرملة حادة'),'$brakingCount',Icons.warning_amber)),SizedBox(width:125,child:compactMetric(tr('Acceleration','تسارع حاد'),'$accelerationCount',Icons.trending_up)),SizedBox(width:125,child:compactMetric(tr('Cornering','انعطاف حاد'),'$corneringCount',Icons.turn_right))])])),
  action(tr('Request workshop help','طلب مساعدة الورشة'),showAssistance),
  coachingCard(),
 ]);
 Future<void> getAssistanceContacts() async {
  try {final contacts=await call('/api/v1/mobile/assistance/contacts');await _secureStore.write(key:'nuqati_assistance_contacts',value:jsonEncode(contacts));if(mounted)setState(()=>assistContacts=contacts);}
  catch(_){final cached=await _secureStore.read(key:'nuqati_assistance_contacts');if(cached!=null){try{if(mounted)setState(()=>assistContacts=jsonDecode(cached));}catch(_){}}}
 }
 Future<void> callWorkshop(String category) async {
  final phone=(assistContacts[category]??'').toString().trim();
  if(phone.isEmpty){if(mounted)ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text(tr('Workshop phone not configured','رقم الورشة غير محدد'))));return;}
  final uri=Uri(scheme:'tel',path:phone.replaceAll(RegExp(r'[^0-9+]'),''));
  if(!await launchUrl(uri,mode:LaunchMode.externalApplication) && mounted){ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('Cannot open dialer')));}
 }
 Future<void> submitAssistance(StateSetter updateDialog) async {
  if(assistanceDescription.text.trim().length<3)return;
  updateDialog(()=>assistanceBusy=true);
  try {
   // Single location snapshot only with explicit driver consent; never disable Privacy Mode.
   double? lat,lon,acc;
   final share=await showDialog<bool>(context:context,builder:(ctx)=>AlertDialog(title:Text(tr('Share current location?','هل تريد مشاركة موقعك الحالي؟')),content:Text(tr('Share one GPS point with the workshop for this request. Your Privacy Mode remains unchanged.','مشاركة نقطة موقع واحدة مع الورشة لهذا الطلب. لن يتغير وضع الخصوصية.')),actions:[TextButton(onPressed:()=>Navigator.pop(ctx,false),child:Text(tr('No','لا'))),TextButton(onPressed:()=>Navigator.pop(ctx,true),child:Text(tr('Share','مشاركة')))]));
   if(share==true){try{final p=await Geolocator.getCurrentPosition(desiredAccuracy:LocationAccuracy.high).timeout(const Duration(seconds:12));lat=p.latitude;lon=p.longitude;acc=p.accuracy;}catch(_){}}
   final response=await call('/api/v1/mobile/assistance/requests',method:'POST',body:{'category':assistanceCategory,'description':assistanceDescription.text.trim(),'latitude':lat,'longitude':lon,'location_accuracy_m':acc});
   if(response['delivered']!=true || response['id']==null)throw Exception('Server did not confirm delivery');
   if(!mounted)return;
   updateDialog(()=>assistanceBusy=false);
   Navigator.of(context).pop();assistanceDescription.clear();
   ScaffoldMessenger.of(context).showSnackBar(SnackBar(content:Text('${tr('Request delivered','تم إرسال الطلب')} #${response['id']}')));
   } catch (e) {
    await nuqatiLog('ASSISTANCE_SUBMISSION_FAILED', e);
    if (mounted) {
     ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
       content: Text(
        "${tr('Request NOT delivered. Connect to internet or call the workshop.', 'لم يتم إرسال الطلب. اتصل بالإنترنت أو اتصل بالورشة.')} ${e.toString()}",
        maxLines: 4,
       ),
      ),
     );
    }
   }
  finally{if(mounted){try{updateDialog(()=>assistanceBusy=false);}catch(_){}}}
 }
 Future<void> showAssistance() async {
  await getAssistanceContacts();
  if(!mounted)return;
  await showDialog<void>(context:context,builder:(ctx)=>StatefulBuilder(builder:(ctx,refresh)=>AlertDialog(
   title:Text(tr('Workshop assistance','مساعدة الورشة')),
   content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
    for(final item in [('manager','Workshop manager / complaint','مدير الورشة / شكوى'),('mechanic','Mechanic','ميكانيكي'),('electrician','Electrician','كهربائي'),('towing','Towing','سطحة')])
     Padding(padding:const EdgeInsets.only(bottom:8),child:Row(children:[Expanded(child:RadioListTile<String>(dense:true,contentPadding:EdgeInsets.zero,title:Text(tr(item.$2,item.$3),style:const TextStyle(fontSize:13)),value:item.$1,groupValue:assistanceCategory,onChanged:(v)=>refresh(()=>assistanceCategory=v!))),IconButton(onPressed:()=>callWorkshop(item.$1),icon:const Icon(Icons.call,color:Colors.green))])),
    TextField(controller:assistanceDescription,minLines:2,maxLines:4,maxLength:2000,decoration:InputDecoration(labelText:tr('Describe the issue','اشرح المشكلة'))),
    Text(tr('For urgent danger, stop safely and call emergency services. Offline requests cannot be delivered; call directly.','عند الخطر توقف في مكان آمن واتصل بالطوارئ. الطلب دون إنترنت لا يصل؛ اتصل مباشرة.'),style:const TextStyle(fontSize:11))
   ])),actions:[TextButton(onPressed:()=>Navigator.pop(ctx),child:Text(tr('Close','إغلاق'))),ElevatedButton(onPressed:assistanceBusy?null:()=>submitAssistance(refresh),child:Text(tr('Send request','إرسال الطلب')))])));
 }
 Widget coachingCard()=>panel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
  InkWell(onTap:()=>setState(()=>coachExpanded=!coachExpanded),child:Row(children:[const Icon(Icons.eco_outlined,color:lime),const SizedBox(width:10),Expanded(child:Text(tr('YOUR DRIVING COACH','مدرب قيادتك'),style:const TextStyle(color:lime,fontSize:15,fontWeight:FontWeight.w800))),Icon(coachExpanded?Icons.expand_less:Icons.expand_more,color:lime)])),
  if(coachExpanded)...[
  const SizedBox(height:10),
  Text(tr('Small changes make every trip safer and more efficient.','تغييرات بسيطة تجعل كل رحلة أكثر أماناً وكفاءة.'),style:const TextStyle(color:Colors.white70)),
  const SizedBox(height:16),
  coachingTip(Icons.trending_up,tr('Accelerate smoothly','تسارع بسلاسة'),tr('Press the accelerator gently to avoid wasting fuel.','اضغط على دواسة الوقود تدريجياً لتقليل الهدر في الوقود.')),
  coachingTip(Icons.pan_tool_outlined,tr('Brake early and gently','خفف السرعة مبكراً'),tr('Leave more distance to reduce sudden braking and brake wear.','اترك مسافة أمان لتقليل الفرملة الحادة وتآكل المكابح.')),
  coachingTip(Icons.speed,tr('Keep a steady, safe speed','حافظ على سرعة آمنة وثابتة'),tr('Follow posted speed limits and adapt to road conditions.','التزم بحدود السرعة وعدّل قيادتك حسب ظروف الطريق.')),
  const SizedBox(height:8),Text(tr('Tips are general guidance. Your score is a GPS-based estimate, not a measured fuel saving.','هذه نصائح عامة. نقاطك تقديرية من GPS وليست قياساً لتوفير الوقود.'),style:const TextStyle(color:Colors.white54,fontSize:11))
  ]
 ]));
 Widget coachingTip(IconData icon,String heading,String detail)=>Padding(padding:const EdgeInsets.only(bottom:14),child:Row(crossAxisAlignment:CrossAxisAlignment.start,children:[Icon(icon,color:lime,size:22),const SizedBox(width:12),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(heading,style:const TextStyle(color:Colors.white,fontWeight:FontWeight.w700)),const SizedBox(height:4),Text(detail,style:const TextStyle(color:Colors.white70,fontSize:12))]))]));
 Widget metricsTab()=>Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
  panel(child:Column(children:[Text(tr('CURRENT SPEED','السرعة الحالية'),style:const TextStyle(color:Colors.white70)),Text(speedKmh.toStringAsFixed(0),style:const TextStyle(color:lime,fontSize:76,fontWeight:FontWeight.w900)),const Text('km/h',style:TextStyle(color:Colors.white70)),const SizedBox(height:12),Text('${tr('Company speed threshold','حد السرعة للشركة')}${company.isNotEmpty?' · $company':''}: ${speedLimit.toStringAsFixed(0)} km/h',textAlign:TextAlign.center,style:const TextStyle(color:Colors.white))])),
  // Fill the full content width with two equally sized event cards per row.
  LayoutBuilder(builder:(context,constraints){
   const gap=10.0;
   final cardWidth=(constraints.maxWidth-gap)/2;
   return Wrap(spacing:gap,runSpacing:gap,children:[
    SizedBox(width:cardWidth,child:stat(tr('Speeding','تجاوز السرعة'),'$speedingCount',Icons.speed)),
    SizedBox(width:cardWidth,child:stat(tr('Harsh braking','فرملة حادة'),'$brakingCount',Icons.south)),
    SizedBox(width:cardWidth,child:stat(tr('Harsh acceleration','تسارع حاد'),'$accelerationCount',Icons.north)),
    SizedBox(width:cardWidth,child:stat(tr('Harsh cornering','انعطاف حاد'),'$corneringCount',Icons.turn_right)),
   ]);
  }),
  panel(child:Column(children:[Text(tr('Acceleration / Deceleration','التسارع / التباطؤ'),style:const TextStyle(color:Colors.white70)),Text('${accelerationKmhS.toStringAsFixed(1)} km/h/s',style:const TextStyle(color:Colors.white,fontSize:28,fontWeight:FontWeight.bold)),const SizedBox(height:10),Text('${tr('Severe events','المخالفات الشديدة')}: $severeCount',style:const TextStyle(color:Colors.orangeAccent))]))
 ]);
 Widget settingsTab()=>Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(tr('Driver profile','الملف الشخصي'),style:const TextStyle(color:lime,fontSize:20,fontWeight:FontWeight.bold)),const SizedBox(height:12),Text('${tr('Name','الاسم')}: $name',style:const TextStyle(color:Colors.white)),const SizedBox(height:8),Text('${tr('Iqama / Saudi ID','الإقامة / الهوية')}: ••••${iqama.text.length>=4?iqama.text.substring(iqama.text.length-4):''}',style:const TextStyle(color:Colors.white)),const SizedBox(height:8),Text('${tr('Phone','الهاتف')}: ${phone.isEmpty?tr('Not provided','غير متوفر'):phone}',style:const TextStyle(color:Colors.white)),const SizedBox(height:8),Text('${tr('Company','الشركة')}: $company',style:const TextStyle(color:Colors.white))])),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text(tr('Language','اللغة'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:10),Row(children:[Expanded(child:action('English',()=>changeLanguage('en'),secondary:language!='en')),const SizedBox(width:8),Expanded(child:action('العربية',()=>changeLanguage('ar'),secondary:language!='ar')),const SizedBox(width:8),Expanded(child:action('اردو',()=>changeLanguage('ur'),secondary:language!='ur'))])])),
  panel(child:SwitchListTile.adaptive(contentPadding:EdgeInsets.zero,activeColor:lime,
   title:Text(tr('Driving safety notifications','إشعارات سلامة القيادة'),style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold)),
   subtitle:Text(tr('Mute driving warnings only. Trips, scores and GPS continue.','إيقاف تنبيهات القيادة فقط. يستمر تسجيل الرحلات والنقاط وGPS.'),style:const TextStyle(color:Colors.white70,fontSize:11)),
   value:notificationsEnabled,onChanged:(value)=>setNotificationPreference(value))),
  panel(child:SwitchListTile.adaptive(contentPadding:EdgeInsets.zero,activeColor:lime,
   title:Text(tr('Camera activity safety warning','تنبيه سلامة استخدام الكاميرا'),style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold)),
   subtitle:Text(tr('Optional: while Nuqati is open, warn above 30 km/h if another app may be using a camera. No photos, calls or audio are accessed. Camera use is not proof of a video call.','اختياري: أثناء فتح نقاطي، التنبيه عند سرعة تتجاوز 30 كم/س مع احتمال استخدام تطبيق آخر للكاميرا. لا يتم الوصول إلى الصور أو المكالمات أو الصوت.'),style:const TextStyle(color:Colors.white70,fontSize:11)),
   value:cameraActivityMonitoring,onChanged:(value)=>setCameraActivityMonitoring(value))),
  action(tr('Refresh GPS acquisition','إعادة تنشيط استقبال GPS'),refreshGpsMonitor,secondary:true),
  action(tr('Check tracking permissions' ,'فحص صلاحيات التتبع'),checkTrackingRequirements),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
   InkWell(onTap:()=>setState(()=>changePasswordExpanded=!changePasswordExpanded),child:Row(children:[const Icon(Icons.lock_outline,color:lime,size:20),const SizedBox(width:10),Expanded(child:Text(tr('Change password','تغيير كلمة المرور'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold))),Icon(changePasswordExpanded?Icons.expand_less:Icons.expand_more,color:lime)])),
   if(changePasswordExpanded)...[const SizedBox(height:12),field(oldPassword,tr('Current password','كلمة المرور الحالية'),secret:true),const SizedBox(height:10),field(newPassword,tr('New password (12+ characters)','كلمة المرور الجديدة (12 حرفاً على الأقل)'),secret:true),const SizedBox(height:12),action(tr('Update password','تحديث كلمة المرور'),changePassword)]
  ])),
  action(tr('LOG OUT','تسجيل الخروج'),logout,secondary:true)
 ]);
 Widget navItem(IconData icon, String title, int index) {
  return Expanded(
    child: InkWell(
      onTap: () => setState(() => tab = index),
      borderRadius: BorderRadius.circular(18),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 11),
        constraints: const BoxConstraints(minHeight: 74),
        decoration: BoxDecoration(
          color: tab == index
              ? lime.withOpacity(.16)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(18),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              color: tab == index ? lime : Colors.white70,
            ),
            const SizedBox(height: 4),
            Text(
              title,
              style: TextStyle(
                fontSize: 11,
                fontWeight: tab == index
                    ? FontWeight.bold
                    : FontWeight.normal,
                color: tab == index ? lime : Colors.white70,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}
 Future<void> showDiagnostics() async {
  final log=await nuqatiReadDiagnostics();
  if(!mounted)return;
  await showDialog<void>(context:context,builder:(ctx)=>AlertDialog(
   title:const Text('Nuqati diagnostics'),
   content:SizedBox(width:450,child:SingleChildScrollView(child:SelectableText(log,style:const TextStyle(fontSize:11)))),
   actions:[TextButton(onPressed:(){Clipboard.setData(ClipboardData(text:log));ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content:Text('Diagnostics copied')));},child:const Text('Copy log')),
   TextButton(onPressed:()=>Navigator.pop(ctx),child:const Text('Close'))],
  ));
 }
 @override Widget build(BuildContext context)=>Scaffold(
 backgroundColor:navy,
 appBar:AppBar(backgroundColor:navy,foregroundColor:Colors.white,title:Column(crossAxisAlignment:CrossAxisAlignment.start,mainAxisSize:MainAxisSize.min,children:[Text(tr('NUQATI · Driver','نقاطي · السائق')),Text(tr('By Al-Riadah Workshop','من ورشة حلول الريادة'),style:const TextStyle(fontSize:11,color:Colors.white70,fontWeight:FontWeight.w500))]),actions:[IconButton(tooltip:'Diagnostics',onPressed:showDiagnostics,icon:const Icon(Icons.bug_report_outlined)),if(token.isNotEmpty)IconButton(tooltip:tr('Log out','خروج'),onPressed:logout,icon:const Icon(Icons.logout))]),
 bottomNavigationBar:token.isEmpty?null:SafeArea(child:Container(padding:const EdgeInsets.fromLTRB(12,8,12,8),decoration:const BoxDecoration(color:blue,borderRadius:BorderRadius.vertical(top:Radius.circular(24))),child:Row(children:[navItem(Icons.shield_outlined,tr('My points','نقاطي'),0),navItem(Icons.speed,tr('Driving','القيادة'),1),navItem(Icons.settings_outlined,tr('Settings','الإعدادات'),2)]))),
 body:Container(decoration:const BoxDecoration(gradient:LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:[navy,blue,navy])),child:ListView(padding:const EdgeInsets.all(18),children:[const SizedBox(height:10),if(token.isEmpty)brand(),if(token.isEmpty)const SizedBox(height:22),if(token.isEmpty)...[panel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(tr('Select language','اختر اللغة'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:8),Row(children:[Expanded(child:action('English',()=>changeLanguage('en'),secondary:language!='en')),const SizedBox(width:6),Expanded(child:action('العربية',()=>changeLanguage('ar'),secondary:language!='ar')),const SizedBox(width:6),Expanded(child:action('اردو',()=>changeLanguage('ur'),secondary:language!='ur'))])])),const SizedBox(height:12),field(iqama,tr('Iqama / Saudi ID number','رقم الإقامة / الهوية'),numeric:true),const SizedBox(height:10),TextField(controller:password,obscureText:!loginPasswordVisible,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:tr('Password','كلمة المرور'),labelStyle:const TextStyle(color:Colors.white70),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(12)),suffixIcon:IconButton(tooltip:loginPasswordVisible?tr('Hide password','إخفاء كلمة المرور'):tr('Show password','إظهار كلمة المرور'),onPressed:()=>setState(()=>loginPasswordVisible=!loginPasswordVisible),icon:Icon(loginPasswordVisible?Icons.visibility_off:Icons.visibility,color:lime)))),CheckboxListTile(value:rememberMe,onChanged:(v)=>setState(()=>rememberMe=v??false),title:Text(tr('Remember me / automatic sign in','تذكرني / تسجيل الدخول تلقائياً'),style:const TextStyle(color:Colors.white)),activeColor:lime,checkColor:navy,controlAffinity:ListTileControlAffinity.leading),const SizedBox(height:16),action(busy?tr('Signing in...','جار تسجيل الدخول'):tr('Sign in','دخول'),busy?null:login)]else ...[if(tab==0)homeTab(),if(tab==1)metricsTab(),if(tab==2)settingsTab()],const SizedBox(height:12),Text(status,style:const TextStyle(color:Colors.white70)),const SizedBox(height:12),if(token.isNotEmpty)Text(tr('GPS is recorded by a foreground location service while the trip is active. Uploads retry when online. Scores are pilot indicators, not certified safety ratings.','يتم تسجيل الموقع عبر خدمة نشطة أثناء الرحلة، وتتم إعادة محاولة الرفع عند توفر الإنترنت. النقاط تجريبية وليست تقييماً معتمداً.'),style:const TextStyle(color:Colors.orangeAccent,fontSize:11))])));

}
