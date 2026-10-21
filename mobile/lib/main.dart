import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;

// Build with --dart-define=NUQATI_API=https://your-https-api-domain
const api = String.fromEnvironment('NUQATI_API', defaultValue: 'https://staging-nuqati.al-riadah.sa');
void main() => runApp(const MaterialApp(debugShowCheckedModeBanner:false, home: DriverApp()));
class DriverApp extends StatefulWidget { const DriverApp({super.key}); @override State<DriverApp> createState()=>_DriverAppState(); }
class _DriverAppState extends State<DriverApp> {
  final phone=TextEditingController(), password=TextEditingController();
  String token='',name='',plate='',status='Sign in to your driver account';
  int? tripId; StreamSubscription<Position>? sub; Position? previous; DateTime? previousTime;
  Map<String,dynamic>? report;
  Future<Map<String,dynamic>> call(String path,{String method='GET',Object? body}) async {
    final r=await (method=='POST'?http.post(Uri.parse('$api$path'),headers:headers,body:jsonEncode(body??{})):http.get(Uri.parse('$api$path'),headers:headers));
    final data=jsonDecode(r.body) as Map<String,dynamic>;
    if(r.statusCode>=400) throw Exception(data['detail']??'HTTP ${r.statusCode}');return data;
  }
  Map<String,String> get headers=>{'Content-Type':'application/json',if(token.isNotEmpty)'Authorization':'Bearer $token'};
  Future<void> login() async {try{
    final result=await call('/api/v1/auth/driver-phone-login',method:'POST',body:{'phone':phone.text.trim(),'password':password.text});
    if(result['user']['role']!='driver')throw Exception('This app requires a linked driver account');
    token=result['access_token']; final me=await call('/api/v1/mobile/me');
    setState(() {name=me['full_name'];plate=me['vehicle']?['plate_number']??'No assigned vehicle';status='Ready · foreground tracking only';});await refresh();
  }catch(e){setState(()=>status='$e');}}
  Future<void> refresh() async {if(token.isEmpty)return;try{final r=await call('/api/v1/fleet/report?period=daily');setState(()=>report=r);}catch(e){setState(()=>status='$e');}}
  Future<void> start() async {try{
    if(!await Geolocator.isLocationServiceEnabled())throw Exception('Enable device location first');
    var permission=await Geolocator.checkPermission();if(permission==LocationPermission.denied)permission=await Geolocator.requestPermission();
    if(permission==LocationPermission.denied||permission==LocationPermission.deniedForever)throw Exception('Location permission required');
    final r=await call('/api/v1/mobile/trips/start',method:'POST');tripId=r['trip_id'];previous=null;previousTime=null;
    setState(()=>status='Trip #$tripId active. Keep the app open.');
    sub=Geolocator.getPositionStream(locationSettings:const LocationSettings(accuracy:LocationAccuracy.high,distanceFilter:15)).listen((pos) async {
      if(tripId==null||pos.accuracy>50)return;
      final now=DateTime.now();double acceleration=0;
      if(previous!=null&&previousTime!=null){final seconds=now.difference(previousTime!).inMilliseconds/1000.0;if(seconds>0)acceleration=(pos.speed-previous!.speed)/seconds;}
      previous=pos;previousTime=now;
      try{await call('/api/v1/mobile/trips/$tripId/sample',method:'POST',body:{'latitude':pos.latitude,'longitude':pos.longitude,'accuracy_m':pos.accuracy,'speed_kmh':pos.speed<0?0:pos.speed*3.6,'acceleration_ms2':acceleration.clamp(-30,30)});if(mounted)setState(()=>status='Tracking · ${pos.speed<0?0:(pos.speed*3.6).round()} km/h · accuracy ${pos.accuracy.round()}m');}
      catch(e){if(mounted)setState(()=>status='Sample not sent: $e');}
    });
  }catch(e){setState(()=>status='$e');}}
  Future<void> finish() async {await sub?.cancel();sub=null;final id=tripId;tripId=null;if(id!=null){try{await call('/api/v1/mobile/trips/$id/finish',method:'POST');setState(()=>status='Trip completed');await refresh();}catch(e){setState(()=>status='Finish failed: $e');}}}
  @override void dispose(){sub?.cancel();phone.dispose();password.dispose();super.dispose();}
  @override Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('NUQATI · Driver'),backgroundColor:const Color(0xff10243b),foregroundColor:Colors.white),body:ListView(padding:const EdgeInsets.all(20),children:[
    if(token.isEmpty)...[TextField(controller:phone,keyboardType:TextInputType.phone,decoration:const InputDecoration(labelText:'Driver mobile number (+966...)')),TextField(controller:password,obscureText:true,decoration:const InputDecoration(labelText:'Password')),const SizedBox(height:12),FilledButton(onPressed:login,child:const Text('Sign in'))]
    else ...[Text(name,style:Theme.of(context).textTheme.headlineSmall),Text('Vehicle: $plate'),const SizedBox(height:16),FilledButton(onPressed:tripId==null?start:null,child:const Text('Start trip')),OutlinedButton(onPressed:tripId!=null?finish:null,child:const Text('Finish trip')),OutlinedButton(onPressed:refresh,child:const Text('Refresh today’s score')),if(report!=null)...[Text('Trips today: ${report!['trip_count']}'),Text('Score: ${report!['drivers']?.isNotEmpty==true?report!['drivers'][0]['score']??'No data':'No data'}'),Text('Violations: ${report!['drivers']?.isNotEmpty==true?report!['drivers'][0]['violations']:'None'}')]],
    const SizedBox(height:20),Text(status),const SizedBox(height:16),const Text('PILOT: location is sent only during an explicitly started trip while the app is open. No background tracking, offline buffering, push alerts or verified road-speed-limit detection yet.',style:TextStyle(color:Colors.orange)),
  ]));
}
