import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';


// Small, dependency-free UI localization. Server values (names, plates, IDs) remain unchanged.
final ValueNotifier<bool> managerArabic = ValueNotifier<bool>(false);
const Map<String,String> _arLabels = {
  'By Al-Riadah Workshop': 'بواسطة ورشة الريادة',
  'Company Admin Sign In': 'دخول مسؤول الشركة',
  'Use the same email and password as the web dashboard.': 'استخدم البريد الإلكتروني وكلمة المرور نفسها للوحة التحكم.',
  'Email address': 'البريد الإلكتروني',
  'Password': 'كلمة المرور',
  'Remember me · automatic sign in': 'تذكرني · تسجيل دخول تلقائي',
  'Signing in…': 'جارٍ تسجيل الدخول…',
  'Sign in': 'تسجيل الدخول',
  'Fleet & maintenance access for authorized company admins.': 'الأسطول والصيانة متاحان لمسؤولي الشركات المصرح لهم.',
  'Fleet': 'الأسطول',
  'Maintenance': 'الصيانة',
  'Live': 'مباشر',
  'History': 'السجل',
  'Company vehicles, assigned drivers & safety': 'مركبات الشركة والسائقون والسلامة',
  'Vehicles': 'المركبات',
  'Drivers': 'السائقون',
  'Trips in progress': 'الرحلات النشطة',
  'Trips': 'الرحلات',
  'Vehicles & assignments': 'المركبات والتعيينات',
  'Report period': 'فترة التقرير',
  'Search plate, model or driver': 'بحث باللوحة أو الطراز أو السائق',
  'Vehicle': 'المركبة',
  'Unassigned': 'غير معيّن',
  'No matching vehicles.': 'لا توجد مركبات مطابقة.',
  'Driver performance': 'أداء السائقين',
  'Score': 'النقاط',
  'No score': 'لا توجد نقاط',
  'Odometer-based service reminders': 'تنبيهات الصيانة وفق عداد المسافة',
  'Service schedules': 'جداول الصيانة',
  'Overdue': 'متأخر',
  'Due soon': 'مستحق قريباً',
  'Search vehicle, service or status': 'بحث بالمركبة أو نوع الصيانة أو الحالة',
  'Current': 'الحالي',
  'Next due': 'الصيانة القادمة',
  'Remaining': 'المتبقي',
  'Unknown': 'غير معروف',
  'No matching maintenance schedules.': 'لا توجد جداول صيانة مطابقة.',
  'Service alerts are based on stored odometer readings. Confirm actual mileage and manufacturer service recommendations.': 'تعتمد تنبيهات الصيانة على عداد المسافة المسجل. يرجى التحقق من المسافة الفعلية وتوصيات الشركة المصنعة.',
  'Engine oil': 'زيت المحرك',
  'Transmission oil': 'زيت ناقل الحركة',
  'Spark plugs': 'شمعات الإشعال',
  'Tyre replacement': 'تغيير الإطارات',
  'Historical Tracking': 'التتبع التاريخي',
  'Live Tracking': 'التتبع المباشر',
  'Recorded routes, trips and event markers': 'المسارات والرحلات والمخالفات المسجلة',
  'Last reported GPS positions · refresh every 30 seconds': 'آخر مواقع GPS المبلغ عنها · تحديث كل 30 ثانية',
  'All vehicles': 'جميع المركبات',
  'All drivers': 'جميع السائقين',
  'From': 'من',
  'To': 'إلى',
  'Filter dates': 'تصفية بالتاريخ',
  'Clear dates': 'مسح التواريخ',
  'Searching…': 'جارٍ البحث…',
  'Period': 'الفترة',
  'Choose date/time': 'اختر التاريخ والوقت',
  'Choose a trip to show its recorded route.': 'اختر رحلة لعرض مسارها المسجل.',
  'No GPS positions for this selection.': 'لا توجد مواقع GPS لهذا الاختيار.',
  'Markers show last received positions, not continuous live streaming. Orange means stale (5+ minutes).': 'تُظهر العلامات آخر المواقع المستلمة وليست بثاً مباشراً مستمراً. البرتقالي يعني أن الموقع قديم (أكثر من ٥ دقائق).',
  'Selected trip': 'الرحلة المحددة',
  'GPS points': 'نقاط GPS',
  'Stop playback': 'إيقاف التشغيل',
  'Play filtered trips continuously': 'تشغيل الرحلات المصفّاة بالتتابع',
  'Point': 'النقطة',
  'Select a trip': 'اختر رحلة',
  'Vehicles and assigned drivers': 'المركبات والسائقون المعينون',
  'No matching records for this selection.': 'لا توجد سجلات مطابقة لهذا الاختيار.',
  'No assigned vehicle': 'لا توجد مركبة معينة',
  'No GPS position': 'لا يوجد موقع GPS',
  'Last reported': 'آخر تحديث',
  'Saudi time': 'بتوقيت السعودية',
  'Refresh': 'تحديث',
  'Sign out': 'تسجيل الخروج',
  'Choose a valid start and end date/time': 'اختر تاريخ ووقت البداية والنهاية بشكل صحيح',
  'Showing first 1000 trips. Narrow date range.': 'عرض أول ١٠٠٠ رحلة. قلّص الفترة الزمنية.',
  'Search failed': 'فشل البحث',
  'Trip': 'رحلة',
  'Recent': 'حديث',
  'Last seen': 'شوهد آخر مرة',
  'MapTiler key missing · showing OSM tiles': 'مفتاح MapTiler غير موجود · يتم عرض خريطة بديلة',
  'ENG': 'EN',
  'العربية': 'العربية',
  'daily': 'يومي',
  'weekly': 'أسبوعي',
  'monthly': 'شهري',
  'yearly': 'سنوي',
  'DAILY': 'يومي',
  'WEEKLY': 'أسبوعي',
  'MONTHLY': 'شهري',
  'YEARLY': 'سنوي',
  'NORMAL': 'طبيعي',
  'OVERDUE': 'متأخر',
  'DUE_SOON': 'مستحق قريباً',
  'RED': 'أحمر',
  'GREEN': 'أخضر',
  'AMBER': 'أصفر',
};
String tr(String input) {
  if (!managerArabic.value) return input;
  if (_arLabels.containsKey(input)) return _arLabels[input]!;
  var result = input;
  // Translate labels within strings containing dynamic values without changing names or plates.
  for (final phrase in _arLabels.keys.toList()..sort((a,b)=>b.length.compareTo(a.length))) {
    if (phrase.length < 4) continue;
    result = result.replaceAll(phrase, _arLabels[phrase]!);
  }
  return result;
}
class LText extends StatelessWidget {
  final String data;
  final TextStyle? style;
  final TextAlign? textAlign;
  final TextOverflow? overflow;
  final int? maxLines;
  const LText(this.data,{super.key,this.style,this.textAlign,this.overflow,this.maxLines});
  @override Widget build(BuildContext context) => Text(tr(data),style:style,textAlign:textAlign,overflow:overflow,maxLines:maxLines);
}

const mapTilerKey = String.fromEnvironment('MAPTILER_API_KEY', defaultValue: '');
const api = String.fromEnvironment('NUQATI_API', defaultValue: 'https://staging-nuqati.al-riadah.sa');
const navy = Color(0xFF091C30);
const blue = Color(0xFF153650);
const lime = Color(0xFFB5E54A);
const dim = Color(0xFFB1C5D4);
const white = Color(0xFFEDF7FB);

void main() { WidgetsFlutterBinding.ensureInitialized(); runApp(const ManagerRoot()); }

class ManagerRoot extends StatelessWidget {
  const ManagerRoot({super.key});
  @override Widget build(BuildContext context) => ValueListenableBuilder<bool>(
    valueListenable: managerArabic,
    builder: (context, isArabic, _) => MaterialApp(
      title: 'Nuqati Manager', debugShowCheckedModeBanner: false,
      locale: Locale(isArabic ? 'ar' : 'en'),
      supportedLocales: const [Locale('en'), Locale('ar')],
      localizationsDelegates: const [GlobalMaterialLocalizations.delegate, GlobalWidgetsLocalizations.delegate, GlobalCupertinoLocalizations.delegate],
      theme: ThemeData(useMaterial3: true, scaffoldBackgroundColor: navy,
        colorScheme: ColorScheme.fromSeed(seedColor: lime, brightness: Brightness.dark), fontFamily: 'Roboto'),
      home: const ManagerHome(),
    ),
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
  int companyId = 0, page = 0; bool busy = false, showPassword = false, rememberMe = true;
  final alertPlugin = FlutterLocalNotificationsPlugin();
  Timer? alertsTimer;
  final Map<int,bool> redStatus = {};
  DateTime? rangeStart, rangeEnd;
  List<Map<String,dynamic>> searchedTrips = [];
  bool searchingTrips = false, playingTrips = false;
  int playbackPoint = 0;
  Timer? playbackTimer;
  String period = 'daily';
  int? selectedVehicleId, selectedDriverId, selectedTripId;
  String trackingPeriod='daily';
  Map<String,dynamic> selectedRoute={};
  bool loadingRoute=false;
  Timer? trackingTimer;
  Map<String,dynamic> summary = {}, report = {};
  List<Map<String,dynamic>> vehicles = [], drivers = [], maintenance = [];

  @override void initState() { super.initState(); _setupAlerts(); _restoreLanguage(); _restore(); }
  Future<void> _restoreLanguage() async {
    final saved=await storage.read(key:'nuqati_manager_language');
    if(!mounted) return;
    setState(()=>managerArabic.value=(saved=='ar'));
  }
  void _switchLanguage() {
    setState(()=>managerArabic.value=!managerArabic.value);
    unawaited(storage.write(key:'nuqati_manager_language',value:managerArabic.value?'ar':'en'));
  }
  Widget languageButton() => TextButton.icon(
    onPressed:_switchLanguage,
    icon:const Icon(Icons.language,color:lime,size:18),
    label:LText(managerArabic.value?'EN':'عربي',style:const TextStyle(color:lime,fontSize:12)),
  );
  Future<void> _setupAlerts() async {
    try {await alertPlugin.initialize(const InitializationSettings(android: AndroidInitializationSettings('@mipmap/ic_launcher')));
      final android=alertPlugin.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
      await android?.requestNotificationsPermission();
    } catch (_) {} // Device notification restrictions must not prevent sign-in.
  }
  Future<void> _pollRedScores() async {
    if(token.isEmpty || companyId==0) return;
    try {
      final data=jsonMap(await request('/api/v1/fleet/report?period=daily'));
      for(final d in jsonList(data['drivers'])) {
        final id=(d['driver_id'] as num?)?.toInt(); final score=(d['score'] as num?)?.toDouble();
        if(id==null)continue;
        if(score==null){redStatus.remove(id);continue;}
        final isRed=score<60;
        final key='red_alert_${companyId}_$id';
        final already=await storage.read(key:key)=='red';
        if(isRed && !already && !redStatus.containsKey(id)) {
          await alertPlugin.show(id,'Nuqati · Red driver score', '${asText(d['driver_name'])} reached RED ($score/100)',
            const NotificationDetails(android:AndroidNotificationDetails('manager_red_scores','Driver safety alerts',channelDescription:'Driver score changes to red',importance:Importance.high,priority:Priority.high)));
        }
        redStatus[id]=isRed;
        await storage.write(key:key,value:isRed?'red':'normal');
      }
    } catch (_) { /* Poll failures do not break fleet screens. */ }
  }
  void _startAlerts() {
    alertsTimer?.cancel();
    unawaited(_pollRedScores());
    alertsTimer=Timer.periodic(const Duration(minutes:1),(_)=>unawaited(_pollRedScores()));
  }

  @override void dispose() { trackingTimer?.cancel(); alertsTimer?.cancel(); playbackTimer?.cancel(); email.dispose(); password.dispose(); super.dispose(); }
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
    final saved=await storage.read(key:'nuqati_manager_remember');
    rememberMe=saved!='false';
    final savedEmail=await storage.read(key:'nuqati_manager_email');
    if(savedEmail!=null)email.text=savedEmail;
    if(!rememberMe)return;
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
      await storage.write(key:'nuqati_manager_remember',value:rememberMe?'true':'false');
      await storage.write(key:'nuqati_manager_email',value:email.text.trim());
      if(rememberMe) { await storage.write(key:'nuqati_manager_token',value:token); } else { await storage.delete(key:'nuqati_manager_token'); }
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
    _startTrackingRefresh();
    _startAlerts();
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
  void _startTrackingRefresh(){
    trackingTimer?.cancel();
    trackingTimer=Timer.periodic(const Duration(seconds:30),(_){if(page==2&&token.isNotEmpty)unawaited(refreshTracking());});
  }
  Future<void> refreshTracking() async {
    if(token.isEmpty||companyId==0)return;
    try{final fresh=jsonMap(await request('/api/v1/fleet/report?period=daily'));
      if(mounted)setState(()=>report=fresh);
    }catch(e){if(mounted)setState(()=>message='Tracking refresh: $e');}
  }
  Future<void> chooseTrip(int tripId) async {
    if(loadingRoute)return;
    setState((){selectedTripId=tripId;loadingRoute=true;selectedRoute={};message='';});
    try{final route=jsonMap(await request('/api/v1/fleet/trips/$tripId/route'));
      if(mounted)setState(()=>selectedRoute=route);
    }catch(e){if(mounted)setState(()=>message='Route loading failed: $e');}
    finally{if(mounted)setState(()=>loadingRoute=false);}
  }
  Future<void> changeTrackingPeriod(String v) async {
    setState(()=>trackingPeriod=v);
    try{final data=jsonMap(await request('/api/v1/fleet/report?period=$v'));
      if(mounted)setState(()=>report=data);
    }catch(e){if(mounted)setState(()=>message='$e');}
  }
  Future<void> logout() async { alertsTimer?.cancel(); playbackTimer?.cancel(); await storage.delete(key:'nuqati_manager_token'); if(mounted) setState(() { token=''; companyId=0; userName=''; companyName=''; vehicles=[]; drivers=[]; maintenance=[]; report={}; summary={}; page=0; search=''; message=''; }); }
  String driverName(dynamic id) { if(id==null) return 'Unassigned'; for (final d in drivers) {if(d['id']==id) return asText(d['full_name']);} return 'Unassigned'; }
  String plate(dynamic id) { for(final v in vehicles) {if(v['id']==id) return asText(v['plate_number']);} return '#$id'; }
  Widget title(String text, {double size=17,Color color=white}) => LText(text, style:TextStyle(fontSize:size,fontWeight:FontWeight.w800,color:color));
  Widget panel(Widget child) => Container(width:double.infinity,margin:const EdgeInsets.only(bottom:12),padding:const EdgeInsets.all(16),decoration:BoxDecoration(color:blue,borderRadius:BorderRadius.circular(19),border:Border.all(color:Colors.white12)),child:child);
  Widget little(String label,String value,IconData icon) => Container(padding:const EdgeInsets.all(13),decoration:BoxDecoration(color:blue,borderRadius:BorderRadius.circular(16),border:Border.all(color:Colors.white12)),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Icon(icon,color:lime,size:21),const SizedBox(height:9),LText(value,style:const TextStyle(fontSize:24,color:white,fontWeight:FontWeight.bold)),LText(label,style:const TextStyle(fontSize:12,color:dim))]));
  Widget section(String heading,String subtitle) => Padding(padding:const EdgeInsets.only(top:8,bottom:14),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[title(heading,size:22),const SizedBox(height:4),LText(subtitle,style:const TextStyle(color:dim,fontSize:12))]));
  Widget searchField(String hint) => TextField(onChanged:(v)=>setState(()=>search=v),style:const TextStyle(color:white),decoration:InputDecoration(prefixIcon:const Icon(Icons.search,color:lime),hintText:tr(hint),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(15),borderSide:BorderSide.none),contentPadding:const EdgeInsets.symmetric(vertical:12)));
  Widget loginView() => Center(child:SingleChildScrollView(padding:const EdgeInsets.all(22),child:ConstrainedBox(constraints:const BoxConstraints(maxWidth:440),child:Column(children:[
    Align(alignment:AlignmentDirectional.centerEnd,child:languageButton()),
    Image.asset('assets/nuqati_icon.png',height:90,width:90),const SizedBox(height:15),title('NUQATI MANAGER',size:28,color:lime),
    const LText('By Al-Riadah Workshop',style:TextStyle(color:dim)),const SizedBox(height:25),
    panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[title('Company Admin Sign In',size:19),const SizedBox(height:7),const LText('Use the same email and password as the web dashboard.',style:TextStyle(color:dim,fontSize:12)),const SizedBox(height:20),
    TextField(controller:email,keyboardType:TextInputType.emailAddress,autocorrect:false,decoration:InputDecoration(labelText:tr('Email address'),prefixIcon:Icon(Icons.email_outlined))),const SizedBox(height:10),
    TextField(controller:password,obscureText:!showPassword,onSubmitted:(_)=>login(),decoration:InputDecoration(labelText:tr('Password'),prefixIcon:const Icon(Icons.lock_outline),suffixIcon:IconButton(onPressed:()=>setState(()=>showPassword=!showPassword),icon:Icon(showPassword?Icons.visibility_off:Icons.visibility)))),const SizedBox(height:8),
    CheckboxListTile(contentPadding:EdgeInsets.zero,title:const LText('Remember me · automatic sign in'),value:rememberMe,activeColor:lime,onChanged:(v)=>setState(()=>rememberMe=v??false)),
    const SizedBox(height:10),
    FilledButton(onPressed:busy?null:login,style:FilledButton.styleFrom(backgroundColor:lime,foregroundColor:navy,minimumSize:const Size.fromHeight(50)),child:LText(busy?'Signing in…':'Sign in',style:const TextStyle(fontWeight:FontWeight.bold))),
    ])), if(message.isNotEmpty)Padding(padding:const EdgeInsets.all(10),child:LText(message,style:const TextStyle(color:Colors.orangeAccent),textAlign:TextAlign.center)),
    const LText('Fleet & maintenance access for authorized company admins.',style:TextStyle(fontSize:11,color:dim),textAlign:TextAlign.center),
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
      Row(children:[Expanded(child:title('Vehicles & assignments')),PopupMenuButton<String>(tooltip:'Report period',initialValue:period,onSelected:(v){setState(()=>period=v);loadData();},itemBuilder:(_)=>['daily','weekly','monthly','yearly'].map((e)=>PopupMenuItem(value:e,child:LText(e.toUpperCase()))).toList(),child:Chip(label:LText(period.toUpperCase()),avatar:const Icon(Icons.date_range,size:17)))]),
      const SizedBox(height:12),searchField('Search plate, model or driver'),const SizedBox(height:13),
      ...shown.map((v){final d=map[asText(v['assigned_driver_id'])]??{};return panel(Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Row(children:[const Icon(Icons.directions_car,color:lime),const SizedBox(width:9),Expanded(child:title(asText(v['plate_number']),size:18)),LText('${number(v['odometer_km'])} km',style:const TextStyle(color:lime,fontWeight:FontWeight.w700))]),const SizedBox(height:8),LText(asText(v['make_model']).isEmpty?'Vehicle':asText(v['make_model']),style:const TextStyle(color:dim)),const Divider(height:23,color:Colors.white12),Row(children:[const Icon(Icons.person_outline,color:dim,size:18),const SizedBox(width:6),Expanded(child:LText(driverName(v['assigned_driver_id']),style:const TextStyle(color:white))),const Icon(Icons.speed,color:dim,size:17),const SizedBox(width:5),LText('Score ${d['score']??'—'}',style:const TextStyle(color:white))]) ]));}),
      if(shown.isEmpty)panel(const LText('No matching vehicles.',style:TextStyle(color:dim))),
      const SizedBox(height:8),title('Driver performance'),const SizedBox(height:10),
      ...driverRows.map((d)=>panel(Row(children:[const CircleAvatar(backgroundColor:navy,child:Icon(Icons.person,color:lime)),const SizedBox(width:10),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[LText(asText(d['driver_name']),style:const TextStyle(color:white,fontWeight:FontWeight.bold)),LText('${d['trips']??0} trips · ${d['risk']??'No score'}',style:const TextStyle(color:dim,fontSize:12))])),LText(d['score']==null?'—':'${d['score']}/100',style:const TextStyle(color:lime,fontWeight:FontWeight.bold))]))),
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
      ...shown.map((m){final state=asText(m['status']);final c=statusColor(state);final service=names[asText(m['service_type'])]??asText(m['service_type']);return panel(Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Row(children:[Icon(Icons.handyman_outlined,color:c),const SizedBox(width:9),Expanded(child:title(service,size:17)),Container(padding:const EdgeInsets.symmetric(horizontal:9,vertical:5),decoration:BoxDecoration(color:c.withOpacity(.14),borderRadius:BorderRadius.circular(16)),child:LText(state.replaceAll('_',' '),style:TextStyle(color:c,fontSize:11,fontWeight:FontWeight.bold)))]),const SizedBox(height:11),Row(children:[Icon(Icons.directions_car_outlined,color:dim,size:17),const SizedBox(width:5),LText(plate(m['vehicle_id']),style:const TextStyle(color:dim)),const Spacer(),LText('Current: ${number(m['current_odometer_km'])} km',style:const TextStyle(color:dim,fontSize:11))]),const Divider(height:21,color:Colors.white12),Row(children:[Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[const LText('Next due',style:TextStyle(color:dim,fontSize:11)),LText('${number(m['next_due_km'])} km',style:const TextStyle(color:white,fontWeight:FontWeight.bold))])),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.end,children:[const LText('Remaining',style:TextStyle(color:dim,fontSize:11)),LText(m['remaining_km']==null?'Unknown':'${number(m['remaining_km'])} km',style:TextStyle(color:c,fontWeight:FontWeight.bold))]))]) ]));}),
      if(shown.isEmpty)panel(const LText('No matching maintenance schedules.',style:TextStyle(color:dim))),const SizedBox(height:12),
      const LText('Service alerts are based on stored odometer readings. Confirm actual mileage and manufacturer service recommendations.',style:TextStyle(color:dim,fontSize:11)),
    ]);
  }


  List<Map<String,dynamic>> get _trackDrivers => jsonList(report['drivers']).where((d){
    if(selectedDriverId!=null && d['driver_id']!=selectedDriverId)return false;
    if(selectedVehicleId!=null){
      final v=vehicles.where((v)=>v['id']==selectedVehicleId).firstOrNull;
      if(v==null||v['assigned_driver_id']!=d['driver_id'])return false;
    }
    return true;
  }).toList();
  List<Map<String,dynamic>> get _allTrips {
    if(rangeStart!=null&&rangeEnd!=null)return searchedTrips.where((t)=>(selectedVehicleId==null||t['vehicle_id']==selectedVehicleId)&&(selectedDriverId==null||t['driver_id']==selectedDriverId)).toList()..sort((a,b)=>asText(b['started_at']).compareTo(asText(a['started_at'])));
    final trips=<Map<String,dynamic>>[];
    for(final d in _trackDrivers){
      for(final t in jsonList(d['trip_details'])){
        if(selectedVehicleId!=null&&t['vehicle_id']!=selectedVehicleId)continue;
        trips.add({...t,'driver_name':d['driver_name']});
      }
    }
    trips.sort((a,b)=>asText(b['started_at']).compareTo(asText(a['started_at'])));
    return trips;
  }
  Future<void> selectRange(bool isStart) async {
    final old=isStart?rangeStart:rangeEnd;
    final day=await showDatePicker(context:context,initialDate:old??DateTime.now(),firstDate:DateTime(2020),lastDate:DateTime(2035));
    if(day==null||!mounted)return;
    final time=await showTimePicker(context:context,initialTime:TimeOfDay.fromDateTime(old??DateTime.now()));
    if(time==null||!mounted)return;
    final date=DateTime(day.year,day.month,day.day,time.hour,time.minute);
    setState((){if(isStart){rangeStart=date;}else{rangeEnd=date;}});
  }
  Future<void> loadRangeTrips() async {
    if(rangeStart==null||rangeEnd==null||!rangeEnd!.isAfter(rangeStart!)){
      setState(()=>message='Choose a valid start and end date/time');return;
    }
    setState((){searchingTrips=true;message='';selectedTripId=null;selectedRoute={};});
    try{
      final start=Uri.encodeQueryComponent(rangeStart!.toUtc().toIso8601String());
      final end=Uri.encodeQueryComponent(rangeEnd!.toUtc().toIso8601String());
      final filter='${selectedVehicleId==null?'':'&vehicle_id=$selectedVehicleId'}${selectedDriverId==null?'':'&driver_id=$selectedDriverId'}';
      final data=jsonMap(await request('/api/v1/fleet/trips/search?start_at=$start&end_at=$end$filter&limit=1000'));
      if(mounted)setState(()=>searchedTrips=jsonList(data['trips']));
      if(data['truncated']==true && mounted)setState(()=>message='Showing first 1000 trips. Narrow date range.');
    }catch(e){if(mounted)setState(()=>message='Search failed: $e');}
    finally{if(mounted)setState(()=>searchingTrips=false);}
  }
  Future<void> playRangeTrips() async {
    if(playingTrips){playbackTimer?.cancel();setState(()=>playingTrips=false);return;}
    final trips=_allTrips;
    if(trips.isEmpty)return;
    setState(()=>playingTrips=true);
    // The selected trips are replayed chronologically, never mixed across vehicles.
    for(final trip in trips.reversed){
      if(!mounted||!playingTrips)break;
      final id=(trip['id'] as num?)?.toInt();if(id==null)continue;
      await chooseTrip(id);
      if(!mounted||!playingTrips)break;
      final pts=jsonList(selectedRoute['points']);
      if(pts.isEmpty)continue;
      for(int i=0;i<pts.length;i++){
        if(!mounted||!playingTrips)break;
        setState(()=>playbackPoint=i);
        await Future.delayed(const Duration(milliseconds:350));
      }
    }
    if(mounted)setState(()=>playingTrips=false);
  }
  String dateLabel(DateTime? d)=>d==null?'Choose date/time':'${d.day}/${d.month}/${d.year} ${d.hour.toString().padLeft(2,'0')}:${d.minute.toString().padLeft(2,'0')}';
  Widget trackingFilters({bool historic=false})=>Column(children:[
    Row(children:[
      Expanded(child:DropdownButtonFormField<int>(value:selectedVehicleId,isExpanded:true,decoration:InputDecoration(labelText:tr('Vehicle'),isDense:true),items:[const DropdownMenuItem<int>(value:null,child:LText('All vehicles')), ...vehicles.map((v)=>DropdownMenuItem<int>(value:(v['id'] as num).toInt(),child:LText(asText(v['plate_number']),overflow:TextOverflow.ellipsis)))],onChanged:(v)=>setState((){selectedVehicleId=v;selectedDriverId=null;selectedTripId=null;selectedRoute={};}))),
      const SizedBox(width:8),
      Expanded(child:DropdownButtonFormField<int>(value:selectedDriverId,isExpanded:true,decoration:InputDecoration(labelText:tr('Driver'),isDense:true),items:[const DropdownMenuItem<int>(value:null,child:LText('All drivers')), ...drivers.where((d)=>selectedVehicleId==null||vehicles.any((v)=>v['id']==selectedVehicleId&&v['assigned_driver_id']==d['id'])).map((d)=>DropdownMenuItem<int>(value:(d['id'] as num).toInt(),child:LText(asText(d['full_name']),overflow:TextOverflow.ellipsis)))],onChanged:(v)=>setState((){selectedDriverId=v;selectedTripId=null;selectedRoute={};}))),
    ]),
    if(historic)...[
      const SizedBox(height:12),Row(children:[Expanded(child:OutlinedButton(onPressed:()=>selectRange(true),child:LText('From: ${dateLabel(rangeStart)}',style:const TextStyle(fontSize:11)))),const SizedBox(width:6),Expanded(child:OutlinedButton(onPressed:()=>selectRange(false),child:LText('To: ${dateLabel(rangeEnd)}',style:const TextStyle(fontSize:11))))]),
      Row(children:[FilledButton(onPressed:searchingTrips?null:loadRangeTrips,child:LText(searchingTrips?'Searching…':'Filter dates')),const SizedBox(width:8),TextButton(onPressed:()=>setState((){rangeStart=null;rangeEnd=null;searchedTrips=[];}),child:const LText('Clear dates'))]),
      const SizedBox(height:12),Row(children:[const LText('Period',style:TextStyle(color:dim)),const Spacer(),...['daily','weekly','monthly','yearly'].map((v)=>Padding(padding:const EdgeInsets.only(left:4),child:ChoiceChip(label:LText(v.substring(0,1).toUpperCase()+v.substring(1,3)),selected:trackingPeriod==v,onSelected:(_)=>changeTrackingPeriod(v))))])],
  ]);
  Widget trackingMap({required bool historical}) {
    final points=<LatLng>[];
    final pins=<Marker>[];
    final eventPins=<Marker>[];
    if(historical){
      for(final p in jsonList(selectedRoute['points'])){
        final lat=(p['latitude'] as num?)?.toDouble(),lon=(p['longitude'] as num?)?.toDouble();
        if(lat!=null&&lon!=null&&lat.abs()<=90&&lon.abs()<=180)points.add(LatLng(lat,lon));
      }
      for(final e in jsonList(selectedRoute['violations'])){
        final lat=(e['latitude'] as num?)?.toDouble(),lon=(e['longitude'] as num?)?.toDouble();
        if(lat!=null&&lon!=null)eventPins.add(Marker(point:LatLng(lat,lon),width:36,height:36,child:Tooltip(message:asText(e['type']),child:const Icon(Icons.warning_amber,color:Colors.orangeAccent,size:28))));
      }
      if(playingTrips && playbackPoint<points.length && points.isNotEmpty){pins.add(Marker(point:points[playbackPoint],width:40,height:40,child:const Icon(Icons.directions_car,color:lime,size:35)));}
      if(points.isNotEmpty){pins.add(Marker(point:points.first,width:30,height:30,child:const Icon(Icons.trip_origin,color:lime,size:28)));pins.add(Marker(point:points.last,width:30,height:30,child:const Icon(Icons.flag,color:Colors.redAccent,size:28)));}
    }else{
      for(final d in _trackDrivers){
        final loc=jsonMap(d['latest_location']);
        final lat=(loc['latitude'] as num?)?.toDouble(),lon=(loc['longitude'] as num?)?.toDouble();
        if(lat==null||lon==null||lat.abs()>90||lon.abs()>180)continue;
        final date=DateTime.tryParse(asText(loc['recorded_at']));
        final age=date==null?9999:DateTime.now().toUtc().difference(date.toUtc()).inMinutes;
        final v=vehicles.where((v)=>v['assigned_driver_id']==d['driver_id']).firstOrNull;
        pins.add(Marker(point:LatLng(lat,lon),width:42,height:42,child:Tooltip(message:'${v?['plate_number']??d['driver_name']} · ${age<5?'Recent':'Last seen $age min ago'}',child:Icon(Icons.directions_car_filled,color:age<5?lime:Colors.orangeAccent,size:36))));
        points.add(LatLng(lat,lon));
      }
    }
    final center=points.isNotEmpty?points.first:const LatLng(24.7136,46.6753);
    return ClipRRect(borderRadius:BorderRadius.circular(18),child:SizedBox(height:350,child:Stack(children:[
      FlutterMap(key:ValueKey('${historical?'history':'live'}_${selectedTripId}_${selectedVehicleId}_${selectedDriverId}_${points.length}'),options:MapOptions(initialCenter:center,initialZoom:points.isNotEmpty?12:5),children:[
        TileLayer(urlTemplate:mapTilerKey.isNotEmpty?'https://api.maptiler.com/maps/streets-v4/256/{z}/{x}/{y}.png?key=${Uri.encodeQueryComponent(mapTilerKey)}':'https://tile.openstreetmap.org/{z}/{x}/{y}.png',userAgentPackageName:'sa.alriadah.nuqati_manager',maxZoom:19),
        if(historical&&points.length>=2)PolylineLayer(polylines:[Polyline(points:playingTrips?points.take(playbackPoint+1).toList():points,strokeWidth:4,color:const Color(0xFF0B8FCB))]),
        MarkerLayer(markers:[...pins,...eventPins]),
        RichAttributionWidget(attributions:[TextSourceAttribution(mapTilerKey.isNotEmpty?'MapTiler · OpenStreetMap contributors':'OpenStreetMap contributors')]),
      ]),
      if(mapTilerKey.isEmpty)Positioned(left:10,right:10,bottom:8,child:Container(padding:const EdgeInsets.all(6),color:navy,child:const LText('MapTiler key missing · showing OSM tiles',style:TextStyle(color:Colors.orangeAccent,fontSize:10)))),
      if(points.isEmpty)Positioned(left:10,right:10,top:10,child:Container(padding:const EdgeInsets.all(12),decoration:BoxDecoration(color:navy.withOpacity(.9),borderRadius:BorderRadius.circular(12)),child:LText(historical?'Choose a trip to show its recorded route.':'No GPS positions for this selection.',style:const TextStyle(color:white,fontSize:12)))),
    ])));
  }
  Widget trackingView({required bool historical}) {
    final trips=_allTrips;
    final list=historical?trips:_trackDrivers;
    return Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      section(historical?'Historical Tracking':'Live Tracking',historical?'Recorded routes, trips and event markers':'Last reported GPS positions · refresh every 30 seconds'),
      panel(trackingFilters(historic:historical)),
      trackingMap(historical:historical),
      const SizedBox(height:10),
      if(!historical)const LText('Markers show last received positions, not continuous live streaming. Orange means stale (5+ minutes).',style:TextStyle(color:dim,fontSize:11))
      else LText('Selected trip: ${selectedTripId??'None'} · GPS points: ${jsonList(selectedRoute['points']).length}',style:const TextStyle(color:dim,fontSize:11)),
      if(historical)Row(children:[FilledButton.icon(onPressed:playRangeTrips,icon:Icon(playingTrips?Icons.pause:Icons.play_arrow),label:LText(playingTrips?'Stop playback':'Play filtered trips continuously')),const SizedBox(width:8),if(playingTrips)LText('Point ${playbackPoint+1}',style:const TextStyle(color:dim))]),
      if(loadingRoute)const LinearProgressIndicator(color:lime),
      const SizedBox(height:14),title(historical?'Select a trip':'Vehicles and assigned drivers'),const SizedBox(height:8),
      if(list.isEmpty)panel(const LText('No matching records for this selection.',style:TextStyle(color:dim))),
      ...list.take(150).map((item){
        if(historical){
          final id=(item['id'] as num).toInt();
          return InkWell(onTap:()=>chooseTrip(id),child:panel(Row(children:[Icon(Icons.route,color:selectedTripId==id?lime:dim),const SizedBox(width:10),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[LText('${item['driver_name']} · ${plate(item['vehicle_id'])}',style:const TextStyle(color:white,fontWeight:FontWeight.bold)),LText('Trip #$id · ${when(item['started_at'])} · ${number(item['distance_km'],decimals:1)} km',style:const TextStyle(color:dim,fontSize:12))])),Icon(Icons.chevron_right,color:selectedTripId==id?lime:dim)])));
        }
        final loc=jsonMap(item['latest_location']);
        final v=vehicles.where((v)=>v['assigned_driver_id']==item['driver_id']).firstOrNull;
        return panel(Row(children:[const Icon(Icons.directions_car,color:lime),const SizedBox(width:10),Expanded(child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[LText('${v?['plate_number']??'No assigned vehicle'} · ${item['driver_name']}',style:const TextStyle(color:white,fontWeight:FontWeight.bold)),LText(loc.isEmpty?'No GPS position':'Last reported ${when(loc['recorded_at'])} (Saudi time)',style:const TextStyle(color:dim,fontSize:12))]))]));
      }),
    ]);
  }
  @override Widget build(BuildContext context) => Directionality(textDirection:managerArabic.value?TextDirection.rtl:TextDirection.ltr,child:Scaffold(
    appBar: token.isEmpty ? null : AppBar(backgroundColor:navy,toolbarHeight:77,title:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[const LText('NUQATI MANAGER',style:TextStyle(fontWeight:FontWeight.w900,fontSize:20)),LText(companyName,maxLines:1,overflow:TextOverflow.ellipsis,style:const TextStyle(color:lime,fontSize:12)),const LText('By Al-Riadah Workshop',style:TextStyle(color:dim,fontSize:10))]),actions:[languageButton(),IconButton(onPressed:busy?null:loadData,icon:const Icon(Icons.refresh),tooltip:'Refresh'),IconButton(onPressed:logout,icon:const Icon(Icons.logout),tooltip:'Sign out')]),
    bottomNavigationBar: token.isEmpty ? null : SafeArea(child:Container(color:blue,padding:const EdgeInsets.symmetric(vertical:7,horizontal:14),child:Row(children:[Expanded(child:_nav(Icons.directions_car_filled_outlined,'Fleet',0)),Expanded(child:_nav(Icons.build_circle_outlined,'Maintenance',1)),Expanded(child:_nav(Icons.map_outlined,'Live',2)),Expanded(child:_nav(Icons.history,'History',3))]))),
    body: token.isEmpty ? loginView() : RefreshIndicator(color:lime,onRefresh:loadData,child:ListView(padding:const EdgeInsets.fromLTRB(16,14,16,25),children:[
      if(busy)const LinearProgressIndicator(minHeight:2,color:lime),
      if(message.isNotEmpty)panel(LText(message,style:const TextStyle(color:Colors.orangeAccent))),
      if(page==0)fleetView() else if(page==1)maintenanceView() else if(page==2)trackingView(historical:false) else trackingView(historical:true),
    ])),
  ));
  Widget _nav(IconData icon, String label, int index) => InkWell(
    onTap: () {
      setState(() {
        page = index;
        search = '';
        if (index == 2) trackingPeriod = 'daily';
      });
      if (index == 2) refreshTracking();
      if (index == 3) changeTrackingPeriod(trackingPeriod);
    },
    borderRadius: BorderRadius.circular(16),
    child: Container(
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: page == index ? lime.withOpacity(.18) : Colors.transparent,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, color: page == index ? lime : dim),
        const SizedBox(height: 4),
        LText(label, style: TextStyle(color: page == index ? lime : dim, fontSize: 12, fontWeight: FontWeight.bold)),
      ]),
    ),
  );
}
