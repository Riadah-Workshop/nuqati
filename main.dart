import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

const api = String.fromEnvironment('NUQATI_API', defaultValue: 'https://staging-nuqati.al-riadah.sa');
const navy = Color(0xFF091C30);
const blue = Color(0xFF153650);
const lime = Color(0xFFB5E54A);
const dim = Color(0xFFB1C5D4);
const white = Color(0xFFEDF7FB);

void main() { WidgetsFlutterBinding.ensureInitialized(); runApp(const ManagerRoot()); }

class ManagerRoot extends StatelessWidget {
  const ManagerRoot({super.key});
  @override Widget build(BuildContext context) => MaterialApp(
    title: 'Nuqati Manager', debugShowCheckedModeBanner: false,
    theme: ThemeData(useMaterial3: true, scaffoldBackgroundColor: navy, colorScheme: ColorScheme.fromSeed(seedColor: lime, brightness: Brightness.dark), fontFamily: 'Roboto'),
    home: const ManagerHome(),
  );
}

String asText(dynamic x) => x == null ? '' : '$x';
String number(dynamic v, {int decimals = 0}) {
  final value = v is num ? v : num.tryParse(asText(v));
  return value == null ? '—' : value.toStringAsFixed(decimals);
}
String when(dynamic x) { if (x == null) return '—'; final dt = DateTime.tryParse(asText(x)); if (dt == null) return '—'; final local = dt.toUtc().add(const Duration(hours: 3)); return '${local.day.toString().padLeft(2,'0')}/${local.month.toString().padLeft(2,'0')} ${local.hour.toString().padLeft(2,'0')}:${local.minute.toString().padLeft(2,'0')}'; }
Map<String,dynamic> jsonMap(dynamic v) => v is Map ? Map<String,dynamic>.from(v) : <String,dynamic>{};
List<Map<String,dynamic>> jsonList(dynamic v) => v is List ? v.map(jsonMap).toList() : <Map<String,dynamic>>[];

class ManagerHome extends StatefulWidget { const ManagerHome({super.key}); @override State<ManagerHome> createState() => _ManagerHomeState(); }
class _ManagerHomeState extends State<ManagerHome> {
  static const storage = FlutterSecureStorage();
  final email = TextEditingController(); final password = TextEditingController();
  String token = '', userName = '', companyName = '', message = '', search = '';
  int companyId = 0, page = 0; bool busy = false, showPassword = false;
  String period = 'daily';
  Map<String,dynamic> summary = {}, report = {};
  List<Map<String,dynamic>> vehicles = [], drivers = [], maintenance = [];

  @override void initState() { super.initState(); _restore(); }
  @override void dispose() { email.dispose(); password.dispose(); super.dispose(); }
  Future<dynamic> request(String endpoint, {String method = 'GET', Object? body, String? auth}) async {
    final uri = Uri.parse('$api$endpoint');
    if (uri.scheme != 'https') throw Exception('HTTPS required');
    final headers = <String,String>{'Accept':'application/json','Content-Type':'application/json',if ((auth ?? token).isNotEmpty) 'Authorization': 'Bearer ${auth ?? token}'};
    final http.Response response;
    try {
      response = await (method == 'POST' ? http.post(uri, headers: headers, body: jsonEncode(body ?? {})) : http.get(uri, headers: headers)).timeout(const Duration(seconds: 18));
    } on TimeoutException { throw Exception('Connection timed out. Please check internet access.'); }
    on Exception { rethrow; }
    dynamic decoded;
    try { decoded = jsonDecode(response.body); } catch (_) { throw Exception('Server returned an unexpected response (${response.statusCode}).'); }
    if (response.statusCode == 401) throw Exception('Session expired. Please sign in again.');
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map ? asText(decoded['detail']) : '';
      throw Exception(detail.isNotEmpty ? detail : 'Request failed (${response.statusCode}).');
    }
    return decoded;
  }
  Future<void> _restore() async {
    final existing = await storage.read(key: 'nuqati_manager_token');
    if (existing == null || existing.isEmpty) return;
    if (!mounted) return;
    setState(() { token = existing; busy = true; });
    try { await _initialize(); }
    catch (e) { await storage.delete(key:'nuqati_manager_token'); if (mounted) setState(() { token = ''; message = '$e'; }); }
    finally { if(mounted) setState(() => busy = false); }
  }
  Future<void> login() async {
    if (busy || email.text.trim().isEmpty || password.text.isEmpty) return;
    setState(() { busy = true; message = ''; });
    try {
      final auth = jsonMap(await request('/api/v1/auth/login',method:'POST',body:{'email':email.text.trim().toLowerCase(),'password':password.text}));
      final user = jsonMap(auth['user']);
      if (user['role'] != 'company_admin') throw Exception('Only Company Admin accounts can access Nuqati Manager.');
      if (user['company_id'] == null) throw Exception('This account has no assigned company.');
      final access = asText(auth['access_token']);
      if (access.isEmpty) throw Exception('No access token received.');
      token = access;
      await _initialize();
      await storage.write(key:'nuqati_manager_token',value:token);
      password.clear();
    } catch (e) { if(mounted) setState(() { token = ''; message = '$e'; }); }
    finally { if(mounted) setState(() => busy = false); }
  }
  Future<void> _initialize() async {
    final me = jsonMap(await request('/api/v1/auth/me'));
    if (me['role'] != 'company_admin' || me['company_id'] == null) throw Exception('Company Admin permission required.');
    final id = (me['company_id'] as num).toInt();
    final companies = jsonList(await request('/api/v1/companies'));
    if(mounted) setState(() { companyId = id; userName = asText(me['full_name']); companyName = companies.where((c)=> c['id']==id).map((c)=>asText(c['name'])).firstOrNull ?? 'Company #$id'; });
    await loadData();
  }
  Future<void> loadData() async {
    if(token.isEmpty || companyId==0) return;
    if(mounted) setState(() { busy = true; message = ''; });
    try {
      final data = await Future.wait([
        request('/api/v1/dashboard'),
        request('/api/v1/vehicles'),
        request('/api/v1/drivers'),
        request('/api/v1/maintenance-schedules'),
        request('/api/v1/fleet/report?period=$period'),
      ]);
      if(!mounted) return;
      setState(() {
        summary = jsonMap(data[0]);
        vehicles = jsonList(data[1]).where((v)=> v['company_id'] == companyId).toList();
        drivers = jsonList(data[2]).where((d)=> d['company_id'] == companyId).toList();
        maintenance = jsonList(data[3]).where((m)=> m['company_id'] == companyId).toList();
        report = jsonMap(data[4]);
      });
    } catch(e) { if(mounted) setState(() => message = '$e'); }
    finally { if(mounted) setState(() => busy = false); }
  }
  Future<void> logout() async { await storage.delete(key:'nuqati_manager_token'); if(mounted) setState(() { token=''; companyId=0; userName=''; companyName=''; vehicles=[]; drivers=[]; maintenance=[]; report={}; summary={}; page=0; search=''; message=''; }); }
  String driverName(dynamic id) { if(id==null) return 'Unassigned'; for (final d in drivers) {if(d['id']==id) return asText(d['full_name']);} return 'Unassigned'; }
  String plate(dynamic id) { for(final v in vehicles) {if(v['id']==id) return asText(v['plate_number']);} return '#$id'; }
  Widget title(String text, {double size=17,Color color=white}) => Text(text, style:TextStyle(fontSize:size,fontWeight:FontWeight.w800,color:color));
  Widget panel(Widget child) => Container(width:double.infinity,margin:const EdgeInsets.only(bottom:12),padding:const EdgeInsets.all(16),decoration:BoxDecoration(color:blue,borderRadius:BorderRadius.circular(19),border:Border.all(color:Colors.white12)),child:child);
  Widget little(String label,String value,IconData icon) => Container(padding:const EdgeInsets.all(13),decoration:BoxDecoration(color:blue,borderRadius:BorderRadius.circular(16),border:Border.all(color:Colors.white12)),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Icon(icon,color:lime,size:21),const SizedBox(height:9),Text(value,style:const TextStyle(fontSize:24,color:white,fontWeight:FontWeight.bold)),Text(label,style:const TextStyle(fontSize:12,color:dim))]));
  Widget section(String heading,String subtitle) => Padding(padding:const EdgeInsets.only(top:8,bottom:14),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[title(heading,size:22),const SizedBox(height:4),Text(subtitle,style:const TextStyle(color:dim,fontSize:12))]));
  Widget searchField(String hint) => TextField(onChanged:(v)=>setState(()=>search=v),style:const TextStyle(color:white),decoration:InputDecoration(prefixIcon:const Icon(Icons.search,color:lime),hintText:hint,filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(15),borderSide:BorderSide.none),contentPadding:const EdgeInsets.symmetric(vertical:12)));
  Widget loginView() => Center(child:SingleChildScrollView(padding:const EdgeInsets.all(22),child:ConstrainedBox(constraints:const BoxConstraints(maxWidth:440),child:Column(children:[
    Image.asset('assets/nuqati_icon.png',height:90,width:90),const SizedBox(height:15),title('NUQATI MANAGER',size:28,color:lime),
    const Text('By Al-Riadah Workshop',style:TextStyle(color:dim)),const SizedBox(height:25),
    panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[title('Company Admin Sign In',size:19),const SizedBox(height:7),const Text('Use the same email and password as the web dashboard.',style:TextStyle(color:dim,fontSize:12)),const SizedBox(height:20),
    TextField(controller:email,keyboardType:TextInputType.emailAddress,autocorrect:false,decoration:const InputDecoration(labelText:'Email address',prefixIcon:Icon(Icons.email_outlined))),const SizedBox(height:10),
    TextField(controller:password,obscureText:!showPassword,onSubmitted:(_)=>login(),decoration:InputDecoration(labelText:'Password',prefixIcon:const Icon(Icons.lock_outline),suffixIcon:IconButton(onPressed:()=>setState(()=>showPassword=!showPassword),icon:Icon(showPassword?Icons.visibility_off:Icons.visibility)))),const SizedBox(height:17),
    FilledButton(onPressed:busy?null:login,style:FilledButton.styleFrom(backgroundColor:lime,foregroundColor:navy,minimumSize:const Size.fromHeight(50)),child:Text(busy?'Signing in…':'Sign in',style:const TextStyle(fontWeight:FontWeight.bold))),
    ])), if(message.isNotEmpty)Padding(padding:const EdgeInsets.all(10),child:Text(message,style:const TextStyle(color:Colors.orangeAccent),textAlign:TextAlign.center)),
    const Text('Fleet & maintenance access for authorized company admins.',style:TextStyle(fontSize:11,color:dim),textAlign:TextAlign.center),
  ]))));

  Widget fleetView() {
    final term=search.toLowerCase().trim();
    final shown=vehicles.where((v)=>'${v['plate_number']} ${v['make_model']} ${driverName(v['assigned_driver_id'])}'.toLowerCase().contains(term)).toList();
    final driverRows=jsonList(report['drivers']);
    final map={for(final d in driverRows) asText(d['driver_id']):d};
    final active=summary['trips_active'] ?? 0;
    return Column(crossAxisAlignment:CrossAxisAlignment.start,children:[section('Fleet','Company vehicles, assigned drivers & safety'),
      GridView.count(crossAxisCount:2,shrinkWrap:true,physics:const NeverScrollableScrollPhysics(),mainAxisSpacing:9,crossAxisSpacing:9,childAspectRatio:1.65,children:[
        little('Vehicles','${vehicles.length}',Icons.directions_car_filled_outlined),little('Drivers','${drivers.length}',Icons.people_alt_outlined),
        little('Trips in progress','$active',Icons.route_outlined),little('Trips ($period)','${report['trip_count']??'—'}',Icons.flag_outlined)
      ]),const SizedBox(height:16),
      Row(children:[Expanded(child:title('Vehicles & assignments')),PopupMenuButton<String>(tooltip:'Report period',initialValue:period,onSelected:(v){setState(()=>period=v);loadData();},itemBuilder:(_)=>['daily','weekly','monthly','yearly'].map((e)=>PopupMenuItem(value:e,child:Text(e.toUpperCase()))).toList(),child:Chip(label:Text(period.toUpperCase()),avatar:const Icon(Icons.date_range,size:17)))]),
      const SizedBox(height:12),searchField('Search plate, model or driver'),const SizedBox(height:13),
      ...shown.map((v){final d=map[asText(v['assigned_driver_id'])]??{};return panel(Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Row(children:[const Icon(Icons.directions_car,color:lime),const SizedBox(width:9),Expanded(child:title(asText(v['plate_number']),size:18)),Text('${number(v['odometer_km'])} km',style:const TextStyle(color:lime,fontWeight:FontWeight.w700))]),const SizedBox(height:8),Text(asText(v['make_model']).isEmpty?'Vehicle':asText(v['make_model']),style:const TextStyle(color:dim)),const Divider(height:23,color:Colors.white12),Row(children:[const Icon(Icons.person_outline,color:dim,size:18),const SizedBox(width:6),Expanded(child:Text(driverName(v['assigned_driver_id']),style:const TextStyle(color:white))),const Icon(Icons.speed,color:dim,size:17),const SizedBox(width:5),Text('Score ${d['score']??'—'}',style:const TextStyle(color:white))]) ]));}),
      if(shown.isEmpty)panel(const Text('No matching vehicles.',style:TextStyle(color:dim))),
      const SizedBox(height:8),title('Driver performance'),const SizedBox(height:10),
      ...driverRows.map((d)=>panel(Row(children:[const CircleAvatar(backgroundColor:navy,child:Icon(Icons.person,color:lime)),const SizedBox(width:10),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(asText(d['driver_name']),style:const TextStyle(color:white,fontWeight:FontWeight.bold)),Text('${d['trips']??0} trips · ${d['risk']??'No score'}',style:const TextStyle(color:dim,fontSize:12))])),Text(d['score']==null?'—':'${d['score']}/100',style:const TextStyle(color:lime,fontWeight:FontWeight.bold))]))),
    ]);
  }

  Widget maintenanceView() {
    final term=search.toLowerCase().trim();
    final shown=maintenance.where((m)=> '${plate(m['vehicle_id'])} ${m['service_type']} ${m['status']}'.toLowerCase().contains(term)).toList();
    final urgent=maintenance.where((m)=>m['status']=='OVERDUE').length;
    final soon=maintenance.where((m)=>m['status']=='DUE_SOON').length;
    const names={'ENGINE_OIL':'Engine oil','TRANSMISSION_OIL':'Transmission oil','SPARK_PLUGS':'Spark plugs','TYRES':'Tyre replacement'};
    Color statusColor(String status)=>status=='OVERDUE'?const Color(0xFFF38A82):status=='DUE_SOON'?const Color(0xFFFFCC70):lime;
    return Column(crossAxisAlignment:CrossAxisAlignment.start,children:[section('Maintenance','Odometer-based service reminders'),
      GridView.count(crossAxisCount:2,shrinkWrap:true,physics:const NeverScrollableScrollPhysics(),mainAxisSpacing:9,crossAxisSpacing:9,childAspectRatio:1.65,children:[
        little('Service schedules','${maintenance.length}',Icons.build_outlined),little('Overdue','$urgent',Icons.warning_amber_outlined),
        little('Due soon','$soon',Icons.schedule),little('Vehicles','${vehicles.length}',Icons.directions_car_outlined)
      ]),const SizedBox(height:17), searchField('Search vehicle, service or status'),const SizedBox(height:13),
      ...shown.map((m){final state=asText(m['status']);final c=statusColor(state);final service=names[asText(m['service_type'])]??asText(m['service_type']);return panel(Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Row(children:[Icon(Icons.handyman_outlined,color:c),const SizedBox(width:9),Expanded(child:title(service,size:17)),Container(padding:const EdgeInsets.symmetric(horizontal:9,vertical:5),decoration:BoxDecoration(color:c.withOpacity(.14),borderRadius:BorderRadius.circular(16)),child:Text(state.replaceAll('_',' '),style:TextStyle(color:c,fontSize:11,fontWeight:FontWeight.bold)))]),const SizedBox(height:11),Row(children:[Icon(Icons.directions_car_outlined,color:dim,size:17),const SizedBox(width:5),Text(plate(m['vehicle_id']),style:const TextStyle(color:dim)),const Spacer(),Text('Current: ${number(m['current_odometer_km'])} km',style:const TextStyle(color:dim,fontSize:11))]),const Divider(height:21,color:Colors.white12),Row(children:[Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[const Text('Next due',style:TextStyle(color:dim,fontSize:11)),Text('${number(m['next_due_km'])} km',style:const TextStyle(color:white,fontWeight:FontWeight.bold))])),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.end,children:[const Text('Remaining',style:TextStyle(color:dim,fontSize:11)),Text(m['remaining_km']==null?'Unknown':'${number(m['remaining_km'])} km',style:TextStyle(color:c,fontWeight:FontWeight.bold))]))]) ]));}),
      if(shown.isEmpty)panel(const Text('No matching maintenance schedules.',style:TextStyle(color:dim))),const SizedBox(height:12),
      const Text('Service alerts are based on stored odometer readings. Confirm actual mileage and manufacturer service recommendations.',style:TextStyle(color:dim,fontSize:11)),
    ]);
  }

  @override Widget build(BuildContext context) => Scaffold(
    appBar: token.isEmpty ? null : AppBar(backgroundColor:navy,toolbarHeight:77,title:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[const Text('NUQATI MANAGER',style:TextStyle(fontWeight:FontWeight.w900,fontSize:20)),Text(companyName,maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:lime,fontSize:12)),const Text('By Al-Riadah Workshop',style:TextStyle(color:dim,fontSize:10))]),actions:[IconButton(onPressed:busy?null:loadData,icon:const Icon(Icons.refresh),tooltip:'Refresh'),IconButton(onPressed:logout,icon:const Icon(Icons.logout),tooltip:'Sign out')]),
    bottomNavigationBar: token.isEmpty ? null : SafeArea(child:Container(color:blue,padding:const EdgeInsets.symmetric(vertical:7,horizontal:14),child:Row(children:[Expanded(child:_nav(Icons.directions_car_filled_outlined,'Fleet',0)),Expanded(child:_nav(Icons.build_circle_outlined,'Maintenance',1))]))),
    body: token.isEmpty ? loginView() : RefreshIndicator(color:lime,onRefresh:loadData,child:ListView(padding:const EdgeInsets.fromLTRB(16,14,16,25),children:[
      if(busy)const LinearProgressIndicator(minHeight:2,color:lime),
      if(message.isNotEmpty)panel(Text(message,style:const TextStyle(color:Colors.orangeAccent))),
      if(page==0)fleetView() else maintenanceView(),
    ])),
  );
  Widget _nav(IconData icon,String label,int index)=>InkWell(onTap:()=>setState((){page=index;search='';}),borderRadius:BorderRadius.circular(16),child:Container(padding:const EdgeInsets.all(11),decoration:BoxDecoration(color:page==index?lime.withOpacity(.18):Colors.transparent,borderRadius:BorderRadius.circular(16)),child:Column(mainAxisSize:MainAxisSize.min,children:[Icon(icon,color:page==index?lime:dim),const SizedBox(height:4),Text(label,style:TextStyle(color:page==index?lime:dim,fontSize:12,fontWeight:FontWeight.bold))])));
}
