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
  if(mounted)setState((){name=me['full_name']??r['user']['full_name']??'Driver';plate=me['vehicle']?['plate_number']??'Not assigned';company=branding['company_name']??'';logoData=branding['logo_data']??'';status='Signed in successfully';password.clear();});
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
   lastPosition=pos;lastTime=now;if(mounted)setState(()=>status='Last GPS sent ${TimeOfDay.now().format(context)} · ${pos.accuracy.round()} m accuracy');
  }catch(e){if(mounted)setState(()=>status='GPS upload failed: $e');}
 }
 Future<void> start()async{if(busy)return;setState(()=>busy=true);try{
  if(!await Geolocator.isLocationServiceEnabled())throw Exception('Enable location services');
  var p=await Geolocator.checkPermission();if(p==LocationPermission.denied)p=await Geolocator.requestPermission();if(p==LocationPermission.denied||p==LocationPermission.deniedForever)throw Exception('Allow location access');
  final r=await call('/api/v1/mobile/trips/start',method:'POST');if(mounted)setState((){tripId=r['trip_id'];status='Trip started · GPS uploads every 60 seconds while app is open';});
  timer?.cancel();timer=Timer.periodic(const Duration(minutes:1),(_){sample();});
 }catch(e){if(mounted)setState(()=>status='$e');}finally{if(mounted)setState(()=>busy=false);}if(tripId!=null)await sample();
 }
 Future<void> finish()async{timer?.cancel();timer=null;final id=tripId;if(id==null)return;await sample();try{await call('/api/v1/mobile/trips/$id/finish',method:'POST');if(mounted)setState((){tripId=null;status='Trip completed';});await refresh();}catch(e){if(mounted)setState(()=>status='Finish failed: $e');}}
 void logout(){if(tripId!=null){setState(()=>status='Finish your active trip before logging out');return;}timer?.cancel();timer=null;setState((){token='';name='';plate='';company='';logoData='';report=null;status='Signed out';});}
 Uint8List? get logoBytes{try{if(logoData.startsWith('data:image/'))return base64Decode(logoData.split(',').last);}catch(_){}return null;}
 Widget brand(){final bytes=logoBytes;return Column(children:[if(bytes!=null)Image.memory(bytes,height:90,fit:BoxFit.contain)else Container(width:88,height:88,decoration:BoxDecoration(color:lime.withOpacity(.13),borderRadius:BorderRadius.circular(24)),child:const Icon(Icons.route,color:lime,size:52)),const SizedBox(height:12),Text(company.isNotEmpty?company:'NUQATI',textAlign:TextAlign.center,style:const TextStyle(color:Colors.white,fontSize:25,fontWeight:FontWeight.bold)),const Text('Fleet Driver Companion',style:TextStyle(color:lime,fontSize:13))]);}
 Widget field(TextEditingController c,String label,{bool secret=false,bool numeric=false})=>TextField(controller:c,obscureText:secret,keyboardType:numeric?TextInputType.number:TextInputType.text,maxLength:numeric?10:null,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:label,labelStyle:const TextStyle(color:Colors.white70),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(12))));
 Widget action(String title,VoidCallback? onPressed,{bool secondary=false})=>SizedBox(width:double.infinity,height:50,child:ElevatedButton(onPressed:onPressed,style:ElevatedButton.styleFrom(backgroundColor:secondary?blue:lime,foregroundColor:secondary?Colors.white:navy,shape:RoundedRectangleBorder(borderRadius:BorderRadius.circular(12))),child:Text(title,style:const TextStyle(fontWeight:FontWeight.bold))));
 @override Widget build(BuildContext context)=>Scaffold(backgroundColor:navy,appBar:AppBar(backgroundColor:navy,foregroundColor:Colors.white,title:const Text('NUQATI · Driver'),actions:[if(token.isNotEmpty)IconButton(tooltip:'Log out',onPressed:logout,icon:const Icon(Icons.logout))]),body:Container(decoration:const BoxDecoration(gradient:LinearGradient(begin:Alignment.topLeft,end:Alignment.bottomRight,colors:[navy,blue,navy])),child:ListView(padding:const EdgeInsets.all(22),children:[const SizedBox(height:16),brand(),const SizedBox(height:30),if(token.isEmpty)...[field(iqama,'Iqama / Saudi ID number',numeric:true),const SizedBox(height:10),field(password,'Password',secret:true),const SizedBox(height:16),action(busy?'Signing in...':'Sign in',busy?null:login)]else ...[Card(color:blue,child:Padding(padding:const EdgeInsets.all(20),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('Welcome, $name',style:const TextStyle(color:Colors.white,fontSize:22,fontWeight:FontWeight.bold)),const SizedBox(height:8),Text('Assigned vehicle: $plate',style:const TextStyle(color:lime,fontSize:17)),if(tripId!=null)Text('Active trip #$tripId',style:const TextStyle(color:Colors.white))]))),const SizedBox(height:16),action('START TRIP',tripId==null&&!busy?start:null),const SizedBox(height:12),action('END TRIP',tripId!=null?finish:null,secondary:true),const SizedBox(height:12),action('Refresh today’s report',refresh,secondary:true),if(report!=null)Padding(padding:const EdgeInsets.symmetric(vertical:16),child:Text('Trips today: ${report!['trip_count']}',style:const TextStyle(color:Colors.white,fontSize:16))),const SizedBox(height:16),const Text('Change password',style:TextStyle(color:lime,fontSize:18,fontWeight:FontWeight.bold)),const SizedBox(height:8),field(oldPassword,'Current password',secret:true),const SizedBox(height:8),field(newPassword,'New password (12+ characters)',secret:true),const SizedBox(height:10),action('Update password',changePassword,secondary:true),const SizedBox(height:16),action('LOG OUT',logout,secondary:true)],const SizedBox(height:24),Text(status,style:const TextStyle(color:Colors.white70)),const SizedBox(height:14),const Text('GPS is sent at trip start, approximately once per minute, and at trip end while this app remains open. Background tracking and offline retry are not enabled.',style:TextStyle(color:Colors.orangeAccent,fontSize:12))])));
 @override void dispose(){timer?.cancel();iqama.dispose();password.dispose();oldPassword.dispose();newPassword.dispose();super.dispose();}
}
