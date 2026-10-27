import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as path;
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
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

const api = String.fromEnvironment('NUQATI_API', defaultValue:'https://staging-nuqati.al-riadah.sa');
const navy=Color(0xff0b1c30), lime=Color(0xffa8d941), blue=Color(0xff17334d);
Future<void> main() async {
 WidgetsFlutterBinding.ensureInitialized();
 FlutterError.onError=(details){FlutterError.presentError(details);nuqatiLog('FLUTTER_ERROR',details.exception,details.stack);};
 PlatformDispatcher.instance.onError=(error,stack){nuqatiLog('UNHANDLED_PLATFORM_ERROR',error,stack);return false;};
 try {await configureTrackingService();await initializeViolationAlerts();await nuqatiLog('UI service configured');}
 catch(e,s){await nuqatiLog('SERVICE_CONFIG_FAILED',e,s);}
 runApp(const MaterialApp(debugShowCheckedModeBanner:false,home:DriverApp()));
}

// Phase 1B: the Android foreground service owns GPS capture and durable delivery.
// Samples are written to SQLite BEFORE attempting HTTP upload.
Future<Database> openTrackingDatabase() async {
 final dbPath=path.join(await getDatabasesPath(),'nuqati_gps_queue_v1.db');
 return openDatabase(dbPath,version:2,onCreate:(db,_)async {
   await db.execute('CREATE TABLE gps_queue (sample_id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL, captured_at TEXT NOT NULL, payload TEXT NOT NULL)');
   await db.execute('CREATE TABLE local_trips (local_id INTEGER PRIMARY KEY, remote_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT)');
 },onUpgrade:(db,oldVersion,newVersion)async {
   if(oldVersion<2)await db.execute('CREATE TABLE IF NOT EXISTS local_trips (local_id INTEGER PRIMARY KEY, remote_id INTEGER, started_at TEXT NOT NULL, ended_at TEXT)');
 });
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

final FlutterLocalNotificationsPlugin nuqatiAlerts=FlutterLocalNotificationsPlugin();
Future<void> initializeViolationAlerts({bool requestPermission=true}) async {
 const settings=InitializationSettings(android:AndroidInitializationSettings('ic_bg_service_small'));
 await nuqatiAlerts.initialize(settings);
 const channel=AndroidNotificationChannel('nuqati_violations_v1','Driving safety warnings',description:'Speeding, harsh braking and acceleration alerts',importance:Importance.high,playSound:true,enableVibration:true);
 final android=nuqatiAlerts.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
 await android?.createNotificationChannel(channel);
 if(requestPermission)await android?.requestNotificationsPermission();
}
Future<void> showViolationAlert(String message,int notificationId) async {
 try {
  await nuqatiAlerts.show(notificationId,'Nuqati safety alert',message,
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
    onStart:nuqatiTrackingEntry,autoStart:false,isForegroundMode:true,
    notificationChannelId:'nuqati_active_trip',initialNotificationTitle:'Nuqati trip tracking',
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
 try {db=await openTrackingDatabase();await nuqatiLog('SERVICE_DB_OPEN_OK');}
 catch(e,s){await nuqatiLog('SERVICE_DB_OPEN_FAILED',e,s);rethrow;}
 const secure=FlutterSecureStorage();
 int? activeTrip;
 StreamSubscription<Position>? locationSub;
 Timer? flushTimer;
 DateTime? lastSaved;
 Position? previous;
 DateTime? lastViolationAt;
 double? previousAlertSpeed;
 DateTime? previousAlertTime;
 double alertSpeedLimit=100, alertHarshAccel=3, alertHarshBrake=3;
 Map<String,dynamic> alertEnabled={'speeding':true,'harsh_acceleration':true,'harsh_braking':true};
 bool flushing=false;
 Future<void> flush() async {
  if(flushing)return;
  flushing=true;
  try {
   final access=await secure.read(key:'nuqati_driver_access_token');
   if(access==null||access.isEmpty)return;
   final headers={'Content-Type':'application/json','Authorization':'Bearer $access'};
   final trips=await db.query('local_trips',orderBy:'started_at ASC');
   for(final trip in trips){
    final localId=trip['local_id'] as int;
    int? remoteId=trip['remote_id'] as int?;
    if(remoteId==null){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/start'),headers:headers,body:'{}').timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300)break;
     final data=jsonDecode(r.body) as Map;
     remoteId=(data['trip_id'] as num).toInt();
     await db.update('local_trips',{'remote_id':remoteId},where:'local_id = ?',whereArgs:[localId]);
    }
    final rows=await db.query('gps_queue',where:'trip_id = ?',whereArgs:[localId],orderBy:'captured_at ASC',limit:100);
    bool failed=false;
    for(final row in rows){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/$remoteId/sample'),headers:headers,body:row['payload'] as String).timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300){failed=true;break;}
     final data=jsonDecode(r.body);
     if(data is! Map||data['accepted']!=true){failed=true;break;}
     await db.delete('gps_queue',where:'sample_id = ?',whereArgs:[row['sample_id']]);
    }
    if(failed)break;
    final remaining=Sqflite.firstIntValue(await db.rawQuery('SELECT COUNT(*) FROM gps_queue WHERE trip_id = ?',[localId]))??0;
    if(remaining>0)break;
    if(trip['ended_at']!=null){
     final r=await http.post(Uri.parse('$api/api/v1/mobile/trips/$remoteId/finish'),headers:headers,body:'{}').timeout(const Duration(seconds:10));
     if(r.statusCode<200||r.statusCode>=300)break;
     await db.delete('local_trips',where:'local_id = ?',whereArgs:[localId]);
    }
   }
  }catch(e,s){await nuqatiLog('SYNC_FAILED',e,s);}
  finally{flushing=false;}
 }
 Future<void> stopCapture() async {
  await locationSub?.cancel();locationSub=null;
  flushTimer?.cancel();flushTimer=null;
  activeTrip=null;lastSaved=null;previous=null;previousAlertSpeed=null;previousAlertTime=null;lastViolationAt=null;
 }
 Future<void> startCapture(int id) async {
  if(activeTrip==id && locationSub!=null)return;
  await nuqatiLog('START_CAPTURE trip=$id');
  await stopCapture();activeTrip=id;
  try{
   final raw=await secure.read(key:'nuqati_driving_policy');
   if(raw!=null){final policy=jsonDecode(raw) as Map;
    alertSpeedLimit=(policy['speeding_kmh'] as num?)?.toDouble()??100;
    alertHarshAccel=(policy['harsh_accel_ms2'] as num?)?.toDouble()??3;
    alertHarshBrake=(policy['harsh_brake_ms2'] as num?)?.toDouble()??3;
    if(policy['enabled'] is Map)alertEnabled=Map<String,dynamic>.from(policy['enabled'] as Map);
   }
  }catch(e,s){await nuqatiLog('ALERT_POLICY_LOAD_FAILED',e,s);}
  await initializeViolationAlerts(requestPermission:false);
  if(service is AndroidServiceInstance){
   service.setAsForegroundService();
   service.setForegroundNotificationInfo(title:'Nuqati trip #$id',content:'Recording GPS and syncing offline samples');
  }
  locationSub=Geolocator.getPositionStream(locationSettings:const LocationSettings(
    accuracy:LocationAccuracy.bestForNavigation,distanceFilter:0,
  )).listen((fix) async {
    if(activeTrip!=id || fix.accuracy>50)return;
    final at=fix.timestamp.toUtc();
    if(lastSaved!=null && at.difference(lastSaved!).inMilliseconds<900)return;
    if(DateTime.now().toUtc().difference(at).inSeconds>15)return;
    double accel=0;
    if(previous!=null&&lastSaved!=null){
      final dt=at.difference(lastSaved!).inMilliseconds/1000;
      if(dt>0)accel=((fix.speed-previous!.speed)/dt).clamp(-30.0,30.0).toDouble();
    }
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
      final dt=previousAlertTime==null?0.0:at.difference(previousAlertTime!).inMilliseconds/1000;
      final accelKmhS=dt>=1&&dt<=12&&previousAlertSpeed!=null?(speed-previousAlertSpeed!)/dt:0.0;
      previousAlertSpeed=speed;previousAlertTime=at;
      if(lastViolationAt==null||at.difference(lastViolationAt!).inSeconds>=12){
       String? message;
       if(alertEnabled['speeding']!=false&&speed>alertSpeedLimit)message='Speeding! Reduce your speed.';
       else if(alertEnabled['harsh_braking']!=false&&accelKmhS < -alertHarshBrake*3.6)message='Harsh braking detected. Drive safely.';
       else if(alertEnabled['harsh_acceleration']!=false&&accelKmhS > alertHarshAccel*3.6)message='Harsh acceleration detected.';
       if(message!=null){lastViolationAt=at;await showViolationAlert(message,2302);await nuqatiLog('VIOLATION_ALERT $message');}
      }
    }catch(e,s){await nuqatiLog('GPS_DB_INSERT_FAILED',e,s);}
  },onError:(Object e,StackTrace s){nuqatiLog('LOCATION_STREAM_ERROR',e,s);});
  flushTimer=Timer.periodic(const Duration(seconds:5),(_) => flush());
  await flush();
 }
 service.on('startTrip').listen((event) async {
  final id=(event?['trip_id'] as num?)?.toInt();
  if(id!=null)await startCapture(id);
 });
 service.on('stopTrip').listen((_) async {await stopCapture();await flush();service.stopSelf();});
 service.on('syncNow').listen((_) => flush());
 // Keep the offline queue moving after connectivity returns, even after Stop.
 Timer.periodic(const Duration(seconds:30),(_) => flush());
 unawaited(flush());
 // On a service restart, the UI re-sends the active trip after authentication.
}

Future<void> startBackgroundTrip(int tripId) async {
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
 String token='',name='',plate='',company='',logoData='',status='Sign in with your Iqama / Saudi ID';
 static const _secureStore=FlutterSecureStorage();
 bool rememberMe=false;
 String phone=''; int tab=0; double speedKmh=0, accelerationKmhS=0, score=100;
 int speedingCount=0, brakingCount=0, accelerationCount=0, severeCount=0;
 String alert='Drive safely to keep your score green.';
 DateTime? lastAlertAt;
 StreamSubscription<Position>? positionSubscription;
 DateTime? lastUploadedFix; bool uploadingFix=false;
 double speedLimit=100, harshAcceleration=10.8, harshBraking=10.8;
 Map<String,bool> enabledEvents={'speeding':true,'harsh_acceleration':true,'harsh_braking':true};
 Timer? policyTimer;
 Future<void> syncDrivingPolicy() async {
   if(token.isEmpty)return;
   try {
     final policy=await call('/api/v1/mobile/driving-policy');
     await _secureStore.write(key:'nuqati_driving_policy',value:jsonEncode(policy));
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

 bool english=true;
 bool gpsReady=false, gpsChecking=false; DateTime? lastGpsFix; Timer? gpsWatchdog; bool gpsWarningShown=false;
 String tr(String en,String ar)=>english?en:ar;
 Color get scoreColor=>score>=85?const Color(0xff62df96):score>=65?const Color(0xffffc45b):const Color(0xffff6675);
 String get rating=>score>=85?'SAFE':score>=65?'CAUTION':'HIGH RISK';
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
   // A cooldown avoids repeatedly penalizing a continuous event.
   if(lastAlertAt==null||now.difference(lastAlertAt!).inSeconds>=12){
     final severeSpeed=newSpeed>speedLimit+25;
     final overSpeed=enabledEvents['speeding']==true&&newSpeed>speedLimit;
     final hardBrake=enabledEvents['harsh_braking']==true&&newAccel < -harshBraking;
     final hardAccel=enabledEvents['harsh_acceleration']==true&&newAccel > harshAcceleration;
     if(overSpeed||hardBrake||hardAccel){
       if(mounted)setState((){
         if(overSpeed)speedingCount++;
         if(hardBrake)brakingCount++;
         if(hardAccel)accelerationCount++;
         if(severeSpeed||newAccel < -harshBraking*1.6||newAccel>harshAcceleration*1.6)severeCount++;
         score=(score-(severeSpeed?18:overSpeed?8:0)-(hardBrake?10:0)-(hardAccel?10:0)).clamp(0,100).toDouble();
       });
       notifyDriver(severeSpeed?'Danger: excessive speed!':overSpeed?'Speed limit exceeded!':hardBrake?'Harsh braking detected!':'Harsh acceleration detected!');
     }
   }
   lastPosition=p;lastTime=now;
 }
 @override void initState(){super.initState();WidgetsBinding.instance.addObserver(this);WidgetsBinding.instance.addPostFrameCallback((_){if(mounted){checkGps(displayDialog:true);restoreSavedSession();}});}
 @override void didChangeAppLifecycleState(AppLifecycleState state){
   if(state==AppLifecycleState.resumed && token.isNotEmpty){restoreActiveTrip();unawaited(syncPendingTripsOnce());}
 }
 @override void dispose(){WidgetsBinding.instance.removeObserver(this);timer?.cancel();policyTimer?.cancel();gpsWatchdog?.cancel();positionSubscription?.cancel();iqama.dispose();password.dispose();oldPassword.dispose();newPassword.dispose();super.dispose();}
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
         final position=await Geolocator.getCurrentPosition(locationSettings:const LocationSettings(accuracy:LocationAccuracy.high,timeLimit:Duration(seconds:15)));
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
       if(!gpsWarningShown){gpsWarningShown=true;if(mounted){setState(()=>status=tr('GPS signal lost during trip. Restore location services.','انقطعت إشارة الموقع أثناء الرحلة. أعد تشغيل الموقع.'));checkGps(displayDialog:true);}}
     }else{gpsWarningShown=false;}
   });
 }
 void startLocalMonitoring(){
   positionSubscription?.cancel();lastPosition=null;lastTime=null;
   positionSubscription=Geolocator.getPositionStream(locationSettings:const LocationSettings(accuracy:LocationAccuracy.bestForNavigation,distanceFilter:0)).listen((p){evaluate(p);},onError:(Object e){if(mounted)setState(()=>status='GPS monitoring: $e');});
 }

 int? tripId; Timer? timer; Position? lastPosition; DateTime? lastTime; bool busy=false; Map<String,dynamic>? report;
 Map<String,String> get headers=>{'Content-Type':'application/json',if(token.isNotEmpty)'Authorization':'Bearer $token'};
 Future<Map<String,dynamic>> call(String path,{String method='GET',Object? body}) async{
  final uri=Uri.parse('$api$path'); final r=method=='POST'?await http.post(uri,headers:headers,body:jsonEncode(body??{})):await http.get(uri,headers:headers);
  Map<String,dynamic> data;
  try {data=jsonDecode(r.body) as Map<String,dynamic>;}catch(_){throw Exception('Server HTTP ${r.statusCode}: ${r.body.length>120?r.body.substring(0,120):r.body}');}
  if(r.statusCode>=400)throw Exception(data['detail']??'HTTP ${r.statusCode}');return data;
 }
 Future<void> restoreSavedSession() async {
   try {
     final saved=await _secureStore.read(key:'nuqati_driver_access_token');
     if(saved==null||saved.isEmpty||!mounted)return;
     if(await _secureStore.read(key:'nuqati_remember_me')!='1')return;
     token=saved;
     final me=await call('/api/v1/mobile/me');
     Map<String,dynamic> branding={};
     try{branding=await call('/api/v1/mobile/branding');}catch(_){}
     if(!mounted)return;
     setState((){rememberMe=true;name=(me['full_name']??'Driver').toString();plate=(me['vehicle']?['plate_number']??'Not assigned').toString();company=(branding['company_name']??'').toString();phone=(me['phone']??me['phone_number']??'').toString();logoData=(branding['logo_data']??'').toString();status='Session restored';});
     await syncDrivingPolicy();
     policyTimer?.cancel();policyTimer=Timer.periodic(const Duration(seconds:60),(_){syncDrivingPolicy();});
     await restoreActiveTrip();unawaited(syncPendingTripsOnce());await refresh();
   }catch(_){
     token='';
     await _secureStore.delete(key:'nuqati_driver_access_token');
     if(mounted)setState(()=>status='Please sign in again');
   }
 }
 Future<void> restoreActiveTrip() async {
  if(token.isEmpty)return;
  final local=await locallyActiveTrip();
  if(local!=null){
   if(!mounted)return;
   setState((){tripId=local;status='Active trip restored from phone storage';});
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
   startLocalMonitoring();startGpsWatchdog();await startBackgroundTrip(id);
  }catch(e){await nuqatiLog('RESTORE_REMOTE_TRIP_FAILED',e);}
 }
 Future<void> login()async{if(busy)return;setState(()=>busy=true);try{
  final r=await call('/api/v1/auth/driver-iqama-login',method:'POST',body:{'iqama':iqama.text.trim(),'password':password.text});
  if(r['user']['role']!='driver')throw Exception('This account is not a driver');token=r['access_token'];
  await _secureStore.write(key:'nuqati_driver_access_token',value:token);
  await _secureStore.write(key:'nuqati_remember_me',value:rememberMe?'1':'0');
  final me=await call('/api/v1/mobile/me');await call('/api/v1/mobile/login-ack',method:'POST');
  Map<String,dynamic> branding={};try{branding=await call('/api/v1/mobile/branding');}catch(_){}
  if(mounted)setState((){name=me['full_name']??r['user']['full_name']??'Driver';plate=me['vehicle']?['plate_number']??'Not assigned';company=branding['company_name']??'';phone=(me['phone']??me['phone_number']??'').toString();logoData=branding['logo_data']??'';status='Signed in successfully';password.clear();});
  await syncDrivingPolicy();policyTimer?.cancel();policyTimer=Timer.periodic(const Duration(seconds:60),(_){syncDrivingPolicy();});await restoreActiveTrip();unawaited(syncPendingTripsOnce());await refresh();
 }catch(e){if(mounted)setState(()=>status='$e');}finally{if(mounted)setState(()=>busy=false);}}
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
  await checkGps();if(!gpsReady)return;
  setState(()=>busy=true);
  try{
   final db=await openTrackingDatabase();
   final id=DateTime.now().microsecondsSinceEpoch;
   await db.insert('local_trips',{'local_id':id,'remote_id':null,'started_at':DateTime.now().toUtc().toIso8601String(),'ended_at':null});
   if(mounted)setState((){tripId=id;status='Trip recording locally (syncs when online)';score=100;speedKmh=0;accelerationKmhS=0;speedingCount=0;brakingCount=0;accelerationCount=0;severeCount=0;alert='Safe trip started. Keep it green!';tab=0;});
   startLocalMonitoring();startGpsWatchdog();await startBackgroundTrip(id);
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
   timer?.cancel();timer=null;gpsWatchdog?.cancel();gpsWatchdog=null;
   await positionSubscription?.cancel();positionSubscription=null;
   if(mounted)setState((){tripId=null;status='Trip stopped and saved on phone. Pending data will sync when online.';});
   // A short-lived sync attempt is optional; local Stop never waits for internet.
   unawaited(syncPendingTripsOnce());
  }catch(e,s){await nuqatiLog('STOP_LOCAL_FAILED',e,s);if(mounted)setState(()=>status='Stop failed: $e');}
  finally{if(mounted)setState(()=>busy=false);}
 }
 Future<void> logout()async{if(tripId!=null){setState(()=>status='Finish your active trip before logging out');return;}timer?.cancel();timer=null;gpsWatchdog?.cancel();gpsWatchdog=null;positionSubscription?.cancel();positionSubscription=null;await _secureStore.delete(key:'nuqati_driver_access_token');await _secureStore.delete(key:'nuqati_remember_me');setState((){token='';name='';plate='';company='';logoData='';report=null;status='Signed out';});}
 Uint8List? get logoBytes{try{if(logoData.startsWith('data:image/'))return base64Decode(logoData.split(',').last);}catch(_){}return null;}
 Widget brand(){final bytes=logoBytes;return Column(children:[if(bytes!=null)Image.memory(bytes,height:90,fit:BoxFit.contain)else Container(width:88,height:88,decoration:BoxDecoration(color:lime.withOpacity(.13),borderRadius:BorderRadius.circular(24)),child:const Icon(Icons.route,color:lime,size:52)),const SizedBox(height:12),Text(company.isNotEmpty?company:'NUQATI',textAlign:TextAlign.center,style:const TextStyle(color:Colors.white,fontSize:25,fontWeight:FontWeight.bold)),const Text('Fleet Driver Companion',style:TextStyle(color:lime,fontSize:13))]);}
 Widget field(TextEditingController c,String label,{bool secret=false,bool numeric=false})=>TextField(controller:c,obscureText:secret,keyboardType:numeric?TextInputType.number:TextInputType.text,maxLength:numeric?10:null,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:label,labelStyle:const TextStyle(color:Colors.white70),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(12))));
 Widget action(String title,VoidCallback? onPressed,{bool secondary=false})=>SizedBox(width:double.infinity,height:50,child:ElevatedButton(onPressed:onPressed,style:ElevatedButton.styleFrom(backgroundColor:secondary?blue:lime,foregroundColor:secondary?Colors.white:navy,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(12))),child:Text(title,style:const TextStyle(fontWeight:FontWeight.bold))));

 Widget panel({required Widget child})=>Container(margin:const EdgeInsets.only(bottom:14),padding:const EdgeInsets.all(18),decoration:BoxDecoration(color:blue.withOpacity(.9),borderRadius:BorderRadius.circular(22),border:Border.all(color:Colors.white12)),child:child);
 Widget stat(String title,String value,IconData icon)=>Expanded(child:panel(child:Column(children:[Icon(icon,color:lime,size:24),const SizedBox(height:8),Text(value,style:const TextStyle(fontSize:24,fontWeight:FontWeight.w800,color:Colors.white)),Text(title,textAlign:TextAlign.center,style:const TextStyle(fontSize:12,color:Colors.white70))])));
 Widget homeTab()=>Column(children:[
  panel(child:Column(children:[Text(tr('GPS status','حالة الموقع')+': '+(gpsReady?tr('Ready','جاهز'):tr('Check required','يلزم التحقق')),style:TextStyle(color:gpsReady?lime:Colors.orangeAccent,fontWeight:FontWeight.bold)),TextButton(onPressed:()=>checkGps(displayDialog:true),child:Text(tr('Check GPS','فحص الموقع'))),Text(tr('MY SAFE TRIP','رحلتي الآمنة'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold,letterSpacing:2)),const SizedBox(height:14),Container(width:160,height:160,decoration:BoxDecoration(shape:BoxShape.circle,border:Border.all(color:scoreColor,width:11),color:scoreColor.withOpacity(.12)),child:Column(mainAxisAlignment:MainAxisAlignment.center,children:[Text(score.toStringAsFixed(0),style:TextStyle(color:scoreColor,fontSize:58,fontWeight:FontWeight.w900)),Text(rating,style:TextStyle(color:scoreColor,fontWeight:FontWeight.bold))])),const SizedBox(height:14),Text(tr('Start green. Stay safe. Earn a better score.','ابدأ بالأخضر، قد بأمان، وحافظ على نقاطك'),textAlign:TextAlign.center,style:const TextStyle(color:Colors.white70)),const SizedBox(height:12),Text(alert,textAlign:TextAlign.center,style:TextStyle(color:scoreColor,fontWeight:FontWeight.bold))])),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text('$name  •  $plate',style:const TextStyle(color:Colors.white,fontSize:17,fontWeight:FontWeight.bold)),const SizedBox(height:12),Text(tr(tripId==null?'Ready for a new trip':'Trip #$tripId is active',tripId==null?'جاهز لرحلة جديدة':'الرحلة رقم $tripId نشطة'),style:const TextStyle(color:Colors.white70)),const SizedBox(height:14),action(tripId==null?tr('START TRIP','بدء الرحلة'):tr('STOP TRIP','إيقاف الرحلة'),busy?null:(tripId==null?start:finish),secondary:tripId!=null)])),
  coachingCard(),
  panel(child:Column(children:[Text(tr('Your driving summary','ملخص القيادة'),style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold)),const SizedBox(height:12),Row(children:[stat(tr('Speeding','تجاوز السرعة'),'$speedingCount',Icons.speed),const SizedBox(width:8),stat(tr('Braking','فرملة حادة'),'$brakingCount',Icons.warning_amber),const SizedBox(width:8),stat(tr('Acceleration','تسارع حاد'),'$accelerationCount',Icons.trending_up)])]))
 ]);
 Widget coachingCard()=>panel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[
  Row(children:[const Icon(Icons.eco_outlined,color:lime),const SizedBox(width:10),Expanded(child:Text(tr('YOUR DRIVING COACH','مدرب قيادتك'),style:const TextStyle(color:lime,fontSize:18,fontWeight:FontWeight.w800)))]),
  const SizedBox(height:10),
  Text(tr('Small changes make every trip safer and more efficient.','تغييرات بسيطة تجعل كل رحلة أكثر أماناً وكفاءة.'),style:const TextStyle(color:Colors.white70)),
  const SizedBox(height:16),
  coachingTip(Icons.trending_up,tr('Accelerate smoothly','تسارع بسلاسة'),tr('Press the accelerator gently to avoid wasting fuel.','اضغط على دواسة الوقود تدريجياً لتقليل الهدر في الوقود.')),
  coachingTip(Icons.pan_tool_outlined,tr('Brake early and gently','خفف السرعة مبكراً'),tr('Leave more distance to reduce sudden braking and brake wear.','اترك مسافة أمان لتقليل الفرملة الحادة وتآكل المكابح.')),
  coachingTip(Icons.speed,tr('Keep a steady, safe speed','حافظ على سرعة آمنة وثابتة'),tr('Follow posted speed limits and adapt to road conditions.','التزم بحدود السرعة وعدّل قيادتك حسب ظروف الطريق.')),
  const SizedBox(height:8),Text(tr('Tips are general guidance. Your score is a GPS-based estimate, not a measured fuel saving.','هذه نصائح عامة. نقاطك تقديرية من GPS وليست قياساً لتوفير الوقود.'),style:const TextStyle(color:Colors.white54,fontSize:11))
 ]));
 Widget coachingTip(IconData icon,String heading,String detail)=>Padding(padding:const EdgeInsets.only(bottom:14),child:Row(crossAxisAlignment:CrossAxisAlignment.start,children:[Icon(icon,color:lime,size:22),const SizedBox(width:12),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(heading,style:const TextStyle(color:Colors.white,fontWeight:FontWeight.w700)),const SizedBox(height:4),Text(detail,style:const TextStyle(color:Colors.white70,fontSize:12))]))]));
 Widget metricsTab()=>Column(children:[
  panel(child:Column(children:[Text(tr('CURRENT SPEED','السرعة الحالية'),style:const TextStyle(color:Colors.white70)),Text(speedKmh.toStringAsFixed(0),style:const TextStyle(color:lime,fontSize:76,fontWeight:FontWeight.w900)),const Text('km/h',style:TextStyle(color:Colors.white70)),const SizedBox(height:12),Text('${tr('Company speed threshold','حد السرعة للشركة')}: ${speedLimit.toStringAsFixed(0)} km/h',style:const TextStyle(color:Colors.white))])),
  Row(children:[stat(tr('Harsh braking','فرملة حادة'),'$brakingCount',Icons.south),const SizedBox(width:10),stat(tr('Harsh acceleration','تسارع حاد'),'$accelerationCount',Icons.north)]),
  panel(child:Column(children:[Text(tr('Acceleration / Deceleration','التسارع / التباطؤ'),style:const TextStyle(color:Colors.white70)),Text('${accelerationKmhS.toStringAsFixed(1)} km/h/s',style:const TextStyle(color:Colors.white,fontSize:28,fontWeight:FontWeight.bold)),const SizedBox(height:10),Text('${tr('Severe events','المخالفات الشديدة')}: $severeCount',style:const TextStyle(color:Colors.orangeAccent))]))
 ]);
 Widget settingsTab()=>Column(children:[
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(tr('Driver profile','الملف الشخصي'),style:const TextStyle(color:lime,fontSize:20,fontWeight:FontWeight.bold)),const SizedBox(height:12),Text('${tr('Name','الاسم')}: $name',style:const TextStyle(color:Colors.white)),const SizedBox(height:8),Text('${tr('Iqama / Saudi ID','الإقامة / الهوية')}: ${iqama.text}',style:const TextStyle(color:Colors.white)),const SizedBox(height:8),Text('${tr('Phone','الهاتف')}: ${phone.isEmpty?tr('Not provided','غير متوفر'):phone}',style:const TextStyle(color:Colors.white)),const SizedBox(height:8),Text('${tr('Company','الشركة')}: $company',style:const TextStyle(color:Colors.white))])),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text(tr('Language','اللغة'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:10),Row(children:[Expanded(child:action('English',()=>setState(()=>english=true),secondary:!english)),const SizedBox(width:10),Expanded(child:action('العربية',()=>setState(()=>english=false),secondary:english))])])),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text(tr('Change password','تغيير كلمة المرور'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:12),field(oldPassword,tr('Current password','كلمة المرور الحالية'),secret:true),const SizedBox(height:10),field(newPassword,tr('New password (12+ characters)','كلمة المرور الجديدة (12 حرفاً على الأقل)'),secret:true),const SizedBox(height:12),action(tr('Update password','تحديث كلمة المرور'),changePassword)])),
  action(tr('LOG OUT','تسجيل الخروج'),logout,secondary:true)
 ]);
 Widget navItem(IconData icon, String title, int index) {
  return Expanded(
    child: InkWell(
      onTap: () => setState(() => tab = index),
      borderRadius: BorderRadius.circular(18),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 11),
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
 appBar:AppBar(backgroundColor:navy,foregroundColor:Colors.white,title:Text(tr('NUQATI · Driver','نقاطي · السائق')),actions:[IconButton(tooltip:'Diagnostics',onPressed:showDiagnostics,icon:const Icon(Icons.bug_report_outlined)),if(token.isNotEmpty)IconButton(tooltip:tr('Log out','خروج'),onPressed:logout,icon:const Icon(Icons.logout))]),
 bottomNavigationBar:token.isEmpty?null:SafeArea(child:Container(padding:const EdgeInsets.fromLTRB(12,8,12,8),decoration:const BoxDecoration(color:blue,borderRadius:BorderRadius.vertical(top:Radius.circular(24))),child:Row(children:[navItem(Icons.shield_outlined,tr('My points','نقاطي'),0),navItem(Icons.speed,tr('Driving','القيادة'),1),navItem(Icons.settings_outlined,tr('Settings','الإعدادات'),2)]))),
 body:Container(decoration:const BoxDecoration(gradient:LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:[navy,blue,navy])),child:ListView(padding:const EdgeInsets.all(18),children:[const SizedBox(height:10),brand(),const SizedBox(height:22),if(token.isEmpty)...[field(iqama,tr('Iqama / Saudi ID number','رقم الإقامة / الهوية'),numeric:true),const SizedBox(height:10),field(password,tr('Password','كلمة المرور'),secret:true),CheckboxListTile(value:rememberMe,onChanged:(v)=>setState(()=>rememberMe=v??false),title:Text(tr('Remember me / automatic sign in','تذكرني / تسجيل الدخول تلقائياً'),style:const TextStyle(color:Colors.white)),activeColor:lime,checkColor:navy,controlAffinity:ListTileControlAffinity.leading),const SizedBox(height:16),action(busy?tr('Signing in...','جار تسجيل الدخول'):tr('Sign in','دخول'),busy?null:login)]else ...[if(tab==0)homeTab(),if(tab==1)metricsTab(),if(tab==2)settingsTab()],const SizedBox(height:12),Text(status,style:const TextStyle(color:Colors.white70)),const SizedBox(height:12),if(token.isNotEmpty)Text(tr('GPS is recorded by a foreground location service while the trip is active. Uploads retry when online. Scores are pilot indicators, not certified safety ratings.','يتم تسجيل الموقع عبر خدمة نشطة أثناء الرحلة، وتتم إعادة محاولة الرفع عند توفر الإنترنت. النقاط تجريبية وليست تقييماً معتمداً.'),style:const TextStyle(color:Colors.orangeAccent,fontSize:11))])));

}
