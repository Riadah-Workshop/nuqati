import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;

const api = String.fromEnvironment('NUQATI_API', defaultValue:'https://staging-nuqati.al-riadah.sa');
const navy=Color(0xff0b1c30), lime=Color(0xffa8d941), blue=Color(0xff17334d);
void main()=>runApp(const MaterialApp(debugShowCheckedModeBanner:false,home:DriverApp()));
class DriverApp extends StatefulWidget{const DriverApp({super.key});@override State<DriverApp> createState()=>_DriverAppState();}
class _DriverAppState extends State<DriverApp>{
 final iqama=TextEditingController(),password=TextEditingController(),oldPassword=TextEditingController(),newPassword=TextEditingController();
 String token='',name='',plate='',company='',logoData='',status='Sign in with your Iqama / Saudi ID';
 String phone=''; int tab=0; double speedKmh=0, accelerationKmhS=0, score=100;
 int speedingCount=0, brakingCount=0, accelerationCount=0, severeCount=0;
 String alert='Drive safely to keep your score green.';
 DateTime? lastAlertAt;
 StreamSubscription<Position>? positionSubscription;
 double speedLimit=110, harshAcceleration=10, harshBraking=11;
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
     final overSpeed=newSpeed>speedLimit;
     final hardBrake=newAccel < -harshBraking;
     final hardAccel=newAccel > harshAcceleration;
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
 @override void initState(){super.initState();WidgetsBinding.instance.addPostFrameCallback((_){if(mounted)checkGps(showDialog:true);});}
 Future<void> checkGps({bool showDialog=false}) async {
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
   if(showDialog||!ready){
     await showDialog<void>(context:context,builder:(dialogContext)=>AlertDialog(
       title:Text(ready?tr('GPS is ready','الموقع جاهز'):tr('GPS required','الموقع مطلوب')),
       content:Text(ready?tr('GPS is working. Keep location enabled throughout your trip. Tracking while the app is closed or locked requires background tracking support.','الموقع يعمل. أبقِ خدمات الموقع مفعلة طوال الرحلة. التتبع عند قفل الهاتف يتطلب دعم العمل في الخلفية.'):message),
       actions:[
         TextButton(onPressed:()=>Navigator.pop(dialogContext),child:Text(tr('Close','إغلاق'))),
         if(!ready)TextButton(onPressed:(){Navigator.pop(dialogContext);Geolocator.openLocationSettings();},child:Text(tr('Location settings','إعدادات الموقع'))),
         if(!ready)TextButton(onPressed:(){Navigator.pop(dialogContext);Geolocator.openAppSettings();},child:Text(tr('App permissions','صلاحيات التطبيق'))),
         if(!ready)TextButton(onPressed:(){Navigator.pop(dialogContext);checkGps(showDialog:true);},child:Text(tr('Retry','إعادة المحاولة'))),
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
       if(!gpsWarningShown){gpsWarningShown=true;if(mounted){setState(()=>status=tr('GPS signal lost during trip. Restore location services.','انقطعت إشارة الموقع أثناء الرحلة. أعد تشغيل الموقع.'));checkGps(showDialog:true);}}
     }else{gpsWarningShown=false;}
   });
 }
 void startLocalMonitoring(){
   positionSubscription?.cancel();lastPosition=null;lastTime=null;
   positionSubscription=Geolocator.getPositionStream(locationSettings:const LocationSettings(accuracy:LocationAccuracy.high,distanceFilter:0)).listen(evaluate,onError:(Object e){if(mounted)setState(()=>status='GPS monitoring: $e');});
 }

 int? tripId; Timer? timer; Position? lastPosition; DateTime? lastTime; bool busy=false; Map<String,dynamic>? report;
 Map<String,String> get headers=>{'Content-Type':'application/json',if(token.isNotEmpty)'Authorization':'Bearer $token'};
 Future<Map<String,dynamic>> call(String path,{String method='GET',Object? body}) async{
  final uri=Uri.parse('$api$path'); final r=method=='POST'?await http.post(uri,headers:headers,body:jsonEncode(body??{})):await http.get(uri,headers:headers);
  final data=jsonDecode(r.body) as Map<String,dynamic>;if(r.statusCode>=400)throw Exception(data['detail']??'HTTP ${r.statusCode}');return data;
 }
 Future<void> login()async{if(busy)return;setState(()=>busy=true);try{
  final r=await call('/api/v1/auth/driver-iqama-login',method:'POST',body:{'iqama':iqama.text.trim(),'password':password.text});
  if(r['user']['role']!='driver')throw Exception('This account is not a driver');token=r['access_token'];
  final me=await call('/api/v1/mobile/me');await call('/api/v1/mobile/login-ack',method:'POST');
  Map<String,dynamic> branding={};try{branding=await call('/api/v1/mobile/branding');}catch(_){}
  if(mounted)setState((){name=me['full_name']??r['user']['full_name']??'Driver';plate=me['vehicle']?['plate_number']??'Not assigned';company=branding['company_name']??'';phone=(me['phone']??me['phone_number']??'').toString();logoData=branding['logo_data']??'';status='Signed in successfully';password.clear();});
  await refresh();
 }catch(e){if(mounted)setState(()=>status='$e');}finally{if(mounted)setState(()=>busy=false);}}
 Future<void> refresh()async{if(token.isEmpty)return;try{final r=await call('/api/v1/fleet/report?period=daily');if(mounted)setState(()=>report=r);}catch(_){}}
 Future<void> changePassword()async{try{await call('/api/v1/mobile/change-password',method:'POST',body:{'current_password':oldPassword.text,'new_password':newPassword.text});oldPassword.clear();newPassword.clear();if(mounted)setState(()=>status='Password changed');}catch(e){if(mounted)setState(()=>status='$e');}}
 Future<void> sample()async{
  final id=tripId;if(id==null||busy)return;
  try{final pos=await Geolocator.getCurrentPosition(locationSettings:const LocationSettings(accuracy:LocationAccuracy.high,timeLimit:Duration(seconds:20)));
   if(pos.accuracy>50){if(mounted)setState(()=>status='Waiting for accurate GPS (${pos.accuracy.round()} m)');return;}
   double accel=0;final now=DateTime.now();if(lastPosition!=null&&lastTime!=null){final secs=now.difference(lastTime!).inMilliseconds/1000;if(secs>0)accel=((pos.speed-lastPosition!.speed)/secs).clamp(-30.0,30.0);}
   await call('/api/v1/mobile/trips/$id/sample',method:'POST',body:{'latitude':pos.latitude,'longitude':pos.longitude,'accuracy_m':pos.accuracy,'speed_kmh':pos.speed<0?0:pos.speed*3.6,'acceleration_ms2':accel,'gps_age_seconds':DateTime.now().difference(pos.timestamp).inMilliseconds.clamp(0,3600000)/1000});
   if(positionSubscription==null)evaluate(pos);if(mounted)setState(()=>status='Last GPS sent ${TimeOfDay.now().format(context)} · ${pos.accuracy.round()} m accuracy');
  }catch(e){if(mounted)setState(()=>status='GPS upload failed: $e');}
 }
 Future<void> start()async{if(busy)return;await checkGps();if(!gpsReady)return;setState(()=>busy=true);try{
  if(!await Geolocator.isLocationServiceEnabled())throw Exception('Enable location services');
  var p=await Geolocator.checkPermission();if(p==LocationPermission.denied)p=await Geolocator.requestPermission();if(p==LocationPermission.denied||p==LocationPermission.deniedForever)throw Exception('Allow location access');
  final r=await call('/api/v1/mobile/trips/start',method:'POST');if(mounted)setState((){tripId=r['trip_id'];status='Trip started · GPS uploads every 60 seconds while app is open';});
  if(mounted)setState((){score=100;speedKmh=0;accelerationKmhS=0;speedingCount=0;brakingCount=0;accelerationCount=0;severeCount=0;alert='Safe trip started. Keep it green!';tab=0;});
  startLocalMonitoring();startGpsWatchdog();
  timer?.cancel();timer=Timer.periodic(const Duration(minutes:1),(_){sample();});
 }catch(e){if(mounted)setState(()=>status='$e');}finally{if(mounted)setState(()=>busy=false);}if(tripId!=null)await sample();
 }
 Future<void> finish()async{gpsWatchdog?.cancel();gpsWatchdog=null;timer?.cancel();timer=null;await positionSubscription?.cancel();positionSubscription=null;final id=tripId;if(id==null)return;await sample();try{await call('/api/v1/mobile/trips/$id/finish',method:'POST');if(mounted)setState((){tripId=null;status='Trip completed';});await refresh();}catch(e){if(mounted)setState(()=>status='Finish failed: $e');}}
 void logout(){if(tripId!=null){setState(()=>status='Finish your active trip before logging out');return;}timer?.cancel();timer=null;gpsWatchdog?.cancel();gpsWatchdog=null;positionSubscription?.cancel();positionSubscription=null;setState((){token='';name='';plate='';company='';logoData='';report=null;status='Signed out';});}
 Uint8List? get logoBytes{try{if(logoData.startsWith('data:image/'))return base64Decode(logoData.split(',').last);}catch(_){}return null;}
 Widget brand(){final bytes=logoBytes;return Column(children:[if(bytes!=null)Image.memory(bytes,height:90,fit:BoxFit.contain)else Container(width:88,height:88,decoration:BoxDecoration(color:lime.withOpacity(.13),borderRadius:BorderRadius.circular(24)),child:const Icon(Icons.route,color:lime,size:52)),const SizedBox(height:12),Text(company.isNotEmpty?company:'NUQATI',textAlign:TextAlign.center,style:const TextStyle(color:Colors.white,fontSize:25,fontWeight:FontWeight.bold)),const Text('Fleet Driver Companion',style:TextStyle(color:lime,fontSize:13))]);}
 Widget field(TextEditingController c,String label,{bool secret=false,bool numeric=false})=>TextField(controller:c,obscureText:secret,keyboardType:numeric?TextInputType.number:TextInputType.text,maxLength:numeric?10:null,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:label,labelStyle:const TextStyle(color:Colors.white70),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(12))));
 Widget action(String title,VoidCallback? onPressed,{bool secondary=false})=>SizedBox(width:double.infinity,height:50,child:ElevatedButton(onPressed:onPressed,style:ElevatedButton.styleFrom(backgroundColor:secondary?blue:lime,foregroundColor:secondary?Colors.white:navy,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(12))),child:Text(title,style:const TextStyle(fontWeight:FontWeight.bold))));

 Widget panel({required Widget child})=>Container(margin:const EdgeInsets.only(bottom:14),padding:const EdgeInsets.all(18),decoration:BoxDecoration(color:blue.withOpacity(.9),borderRadius:BorderRadius.circular(22),border:Border.all(color:Colors.white12)),child:child);
 Widget stat(String title,String value,IconData icon)=>Expanded(child:panel(child:Column(children:[Icon(icon,color:lime,size:24),const SizedBox(height:8),Text(value,style:const TextStyle(fontSize:24,fontWeight:FontWeight.w800,color:Colors.white)),Text(title,textAlign:TextAlign.center,style:const TextStyle(fontSize:12,color:Colors.white70))])));
 Widget homeTab()=>Column(children:[
  panel(child:Column(children:[Text(tr('GPS status','حالة الموقع')+': '+(gpsReady?tr('Ready','جاهز'):tr('Check required','يلزم التحقق')),style:TextStyle(color:gpsReady?lime:Colors.orangeAccent,fontWeight:FontWeight.bold)),TextButton(onPressed:()=>checkGps(showDialog:true),child:Text(tr('Check GPS','فحص الموقع'))),Text(tr('MY SAFE TRIP','رحلتي الآمنة'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold,letterSpacing:2)),const SizedBox(height:14),Container(width:160,height:160,decoration:BoxDecoration(shape:BoxShape.circle,border:Border.all(color:scoreColor,width:11),color:scoreColor.withOpacity(.12)),child:Column(mainAxisAlignment:MainAxisAlignment.center,children:[Text(score.toStringAsFixed(0),style:TextStyle(color:scoreColor,fontSize:58,fontWeight:FontWeight.w900)),Text(rating,style:TextStyle(color:scoreColor,fontWeight:FontWeight.bold))])),const SizedBox(height:14),Text(tr('Start green. Stay safe. Earn a better score.','ابدأ بالأخضر، قد بأمان، وحافظ على نقاطك'),textAlign:TextAlign.center,style:const TextStyle(color:Colors.white70)),const SizedBox(height:12),Text(alert,textAlign:TextAlign.center,style:TextStyle(color:scoreColor,fontWeight:FontWeight.bold))])),
  panel(child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text('$name  •  $plate',style:const TextStyle(color:Colors.white,fontSize:17,fontWeight:FontWeight.bold)),const SizedBox(height:12),Text(tr(tripId==null?'Ready for a new trip':'Trip #$tripId is active',tripId==null?'جاهز لرحلة جديدة':'الرحلة رقم $tripId نشطة'),style:const TextStyle(color:Colors.white70)),const SizedBox(height:14),action(tripId==null?tr('START TRIP','بدء الرحلة'):tr('STOP TRIP','إيقاف الرحلة'),busy?null:(tripId==null?start:finish),secondary:tripId!=null)])),
  panel(child:Column(children:[Text(tr('Your driving summary','ملخص القيادة'),style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold)),const SizedBox(height:12),Row(children:[stat(tr('Speeding','تجاوز السرعة'),'$speedingCount',Icons.speed),const SizedBox(width:8),stat(tr('Braking','فرملة حادة'),'$brakingCount',Icons.warning_amber),const SizedBox(width:8),stat(tr('Acceleration','تسارع حاد'),'$accelerationCount',Icons.trending_up)])]))
 ]);
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
 @override Widget build(BuildContext context)=>Scaffold(
 backgroundColor:navy,
 appBar:AppBar(backgroundColor:navy,foregroundColor:Colors.white,title:Text(tr('NUQATI · Driver','نقاطي · السائق')),actions:[if(token.isNotEmpty)IconButton(tooltip:tr('Log out','خروج'),onPressed:logout,icon:const Icon(Icons.logout))]),
 bottomNavigationBar:token.isEmpty?null:SafeArea(child:Container(padding:const EdgeInsets.fromLTRB(12,8,12,8),decoration:const BoxDecoration(color:blue,borderRadius:BorderRadius.vertical(top:Radius.circular(24))),child:Row(children:[navItem(Icons.shield_outlined,tr('My points','نقاطي'),0),navItem(Icons.speed,tr('Driving','القيادة'),1),navItem(Icons.settings_outlined,tr('Settings','الإعدادات'),2)]))),
 body:Container(decoration:const BoxDecoration(gradient:LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:[navy,blue,navy])),child:ListView(padding:const EdgeInsets.all(18),children:[const SizedBox(height:10),brand(),const SizedBox(height:22),if(token.isEmpty)...[field(iqama,tr('Iqama / Saudi ID number','رقم الإقامة / الهوية'),numeric:true),const SizedBox(height:10),field(password,tr('Password','كلمة المرور'),secret:true),const SizedBox(height:16),action(busy?tr('Signing in...','جار تسجيل الدخول'):tr('Sign in','دخول'),busy?null:login)]else ...[if(tab==0)homeTab(),if(tab==1)metricsTab(),if(tab==2)settingsTab()],const SizedBox(height:12),Text(status,style:const TextStyle(color:Colors.white70)),const SizedBox(height:12),if(token.isNotEmpty)Text(tr('Live metrics are estimated from foreground GPS. Uploads occur every 60 seconds. Scores are pilot indicators, not certified safety ratings.','القياسات تقديرية من GPS أثناء فتح التطبيق. يتم الإرسال كل 60 ثانية. النقاط تجريبية وليست تقييماً معتمداً.'),style:const TextStyle(color:Colors.orangeAccent,fontSize:11))])));
 @override void dispose(){gpsWatchdog?.cancel();timer?.cancel();positionSubscription?.cancel();iqama.dispose();password.dispose();oldPassword.dispose();newPassword.dispose();super.dispose();}
}
