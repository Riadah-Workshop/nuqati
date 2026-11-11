// Vehicle receiving/returning is intentionally online-only. No offline photo
// queue, SQLite table, secure-storage draft or speculative plate selection.
// The system camera may create its usual OS temporary file; it is deleted
// immediately after reading into volatile memory, and no handover is persisted
// locally. Only a successful, authenticated server response changes the link.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';

class VehicleHandoverPage extends StatefulWidget {
  final String api;
  final String language;
  final Future<String?> Function() accessToken;
  final Future<bool> Function() canSwitchVehicle;
  final Future<void> Function() onAssignmentChanged;
  const VehicleHandoverPage({super.key,required this.api,required this.language,
    required this.accessToken,required this.canSwitchVehicle,required this.onAssignmentChanged});
  @override State<VehicleHandoverPage> createState()=>_VehicleHandoverPageState();
}

class _VehicleHandoverPageState extends State<VehicleHandoverPage> {
  static const navy=Color(0xff0d1d2c), blue=Color(0xff1b3548), lime=Color(0xffc3ec61);
  static const requiredPhotos=['front','rear','left','right','cabin_front','cabin_rear','dashboard','odometer'];
  final picker=ImagePicker();
  Timer? pendingReviewTimer;
  final odometer=TextEditingController(),warnings=TextEditingController(),notes=TextEditingController();
  final Map<String,Uint8List> photos={};
  final Map<int,Uint8List> previousPhotos={};
  List<dynamic> vehicles=[];
  Map<String,dynamic>? assignment,legacyVehicle,priorInspection;
  int? selectedVehicleId;
  String engine='normal',interior='normal',message='';
  bool online=false,loading=true,submitting=false,acknowledged=false,detailsVisible=false;
  final List<Map<String,String>> damage=[];
  final Set<String> missingItems={};
  bool get receiving=>assignment==null || (assignment?['status']=='rejected');
  bool get pending=>['pending_receipt','pending_return'].contains(assignment?['status']);
  bool get rtl=>widget.language!='en';
  String tr(String en,String ar,[String? ur])=>widget.language=='ar'?ar:widget.language=='ur'?(ur??ar):en;
  String photoLabel(String key){const labels={
    'front':['Front','الأمام','سامنے'],'rear':['Rear','الخلف','پیچھے'],
    'left':['Left side','الجانب الأيسر','بائیں جانب'],'right':['Right side','الجانب الأيمن','دائیں جانب'],
    'cabin_front':['Front cabin','المقصورة الأمامية','اگلا کیبن'],'cabin_rear':['Rear cabin','المقصورة الخلفية','پچھلا کیبن'],
    'dashboard':['Dashboard','لوحة العدادات','ڈیش بورڈ'],'odometer':['Odometer','عداد الكيلومترات','اوڈومیٹر'],
    'damage':['Damage detail','صورة الضرر','نقصان کی تصویر'],
    'equipment':['Missing equipment','المعدات الناقصة','گمشدہ سامان'],
    'engine':['Engine compartment','حجرة المحرك','انجن']};
    final value=labels[key];return value==null?key:widget.language=='ar'?value[1]:widget.language=='ur'?value[2]:value[0];
  }
  @override void initState(){
    super.initState();
    unawaited(refresh());
    // Online-only polling while this screen is open. Supervisor approvals can
    // change an assignment without the driver manually pressing Refresh.
    pendingReviewTimer=Timer.periodic(const Duration(seconds:20),(_){
      if(mounted&&pending&&!loading&&!submitting)unawaited(refresh());
    });
  }
  @override void dispose(){pendingReviewTimer?.cancel();photos.clear();previousPhotos.clear();odometer.dispose();warnings.dispose();notes.dispose();super.dispose();}
  Future<Map<String,dynamic>> apiCall(String path,{String method='GET',Object? body,Duration timeout=const Duration(seconds:20)}) async {
    final token=await widget.accessToken();
    if(token==null||token.isEmpty)throw const SocketException('Online authorization required');
    final uri=Uri.parse('${widget.api}/api/v1/handover$path');
    final headers={'Authorization':'Bearer $token','Content-Type':'application/json','Cache-Control':'no-store'};
    final response=await (method=='POST'
       ?http.post(uri,headers:headers,body:jsonEncode(body)).timeout(timeout)
       :http.get(uri,headers:headers).timeout(timeout));
    Map<String,dynamic> result={};
    try{result=Map<String,dynamic>.from(jsonDecode(response.body) as Map);}catch(_){}
    if(response.statusCode<200||response.statusCode>=300)throw StateError('${result['detail']??'HTTP ${response.statusCode}'}');
    return result;
  }
  Future<void> refresh() async {
    if(!mounted)return;
    setState((){loading=true;message='';online=false;});
    try{
      final result=await apiCall('/driver/status');
      if(!mounted)return;
      final previousStatus=assignment?['status'];
      final hadVerifiedVehicle=assignment!=null||legacyVehicle!=null;
      final current=result['active_assignment'];
      final newStatus=current is Map?current['status']:null;
      final legacy=result['legacy_vehicle'];
      final newSelection=(current is Map?current['vehicle_id']:legacy is Map?legacy['id']:null) as int?;
      setState((){online=result['online_verified']==true;vehicles=(result['vehicles'] as List?)??[];
        assignment=current is Map?Map<String,dynamic>.from(current):null;
        legacyVehicle=legacy is Map?Map<String,dynamic>.from(legacy):null;
        // Do not silently keep the previously returned plate selected.
        selectedVehicleId=newSelection??(hadVerifiedVehicle?null:selectedVehicleId);
        if(!vehicles.any((v)=>v['id']==selectedVehicleId))selectedVehicleId=null;
        loading=false;});
      // Only a server-confirmed transition from a pending inspection can
      // rebind (or clear) the native recording owner on this device.
      if((previousStatus=='pending_receipt'||previousStatus=='pending_return')
          &&(newStatus=='active'||current==null)){
        try{await widget.onAssignmentChanged();}
        catch(_){if(mounted)setState(()=>message=tr(
          'Handover approved, but local vehicle identity needs refreshing before driving.',
          'تم اعتماد العهدة، لكن يلزم تحديث ربط المركبة محلياً قبل القيادة.'));}
      }
    }catch(e){if(mounted)setState((){online=false;loading=false;photos.clear();message=tr(
      'Internet connection and backend verification are required. No inspection or plate change is available offline.',
      'يلزم الاتصال بالإنترنت والتحقق من الخادم. لا يوجد استلام أو تسليم أو تغيير لوحة دون اتصال.',
      'انٹرنیٹ اور سرور تصدیق لازم ہے۔ آف لائن وصولی یا واپسی ممکن نہیں۔');});}
  }
  Future<void> verifyOnline() async {
    await apiCall('/driver/status',timeout:const Duration(seconds:12));
  }
  Future<void> takePhoto(String category) async {
    if(!online||submitting)return;
    try{
      await verifyOnline();
      final file=await picker.pickImage(source:ImageSource.camera,imageQuality:42,maxWidth:1100,maxHeight:850);
      if(file==null)return;
      Uint8List bytes;
      try{bytes=await file.readAsBytes();}finally{
        // image_picker's temporary camera file is not an offline handover draft.
        try{await File(file.path).delete();}catch(_){}
      }
      if(bytes.length>950000)throw StateError(tr('Photo too large. Retake at lower resolution.','الصورة كبيرة. التقط صورة أصغر.'));
      if(!mounted)return;
      setState(()=>photos[category]=bytes);
    }on SocketException{if(mounted)setState((){online=false;photos.clear();message=tr('Connection lost. Inspection photos were not saved. Reconnect and start again.','فُقد الاتصال. لم تُحفظ الصور. أعد الاتصال وابدأ من جديد.');});}
    on TimeoutException{if(mounted)setState((){online=false;photos.clear();message=tr('Backend is unavailable. Photos were not saved.','الخادم غير متاح. لم تُحفظ الصور.');});}
    catch(e){if(mounted)setState(()=>message=e.toString());}
  }
  void clearForm(){photos.clear();previousPhotos.clear();damage.clear();missingItems.clear();odometer.clear();warnings.clear();notes.clear();engine='normal';interior='normal';acknowledged=false;priorInspection=null;detailsVisible=false;}
  Future<void> loadPreviousCondition() async {
    if(selectedVehicleId==null)return;
    try{
      await verifyOnline();
      final history=await apiCall('/vehicles/$selectedVehicleId/history');
      final assignments=(history['assignments'] as List?)??[];
      int? id;
      for(final a in assignments){
        final item=Map<String,dynamic>.from(a as Map);
        final candidate=item['return_inspection_id']??item['receipt_inspection_id'];
        if(candidate is int){id=candidate;break;}
      }
      if(id==null){if(mounted)setState(()=>message=tr('No previous inspection recorded.','لا توجد معاينة سابقة لهذه المركبة.'));return;}
      final result=await apiCall('/inspections/$id');
      final token=await widget.accessToken();
      final fetched=<int,Uint8List>{};
      if(token!=null){
       final images=(result['photos'] as List?)??[];
       // Previous photos are loaded from the server only, into RAM for viewing.
       await Future.wait(images.where((p)=>['front','rear','left','right','cabin_front','cabin_rear','dashboard','odometer'].contains(p['category'])).take(8).map((p)async{
        final response=await http.get(Uri.parse('${widget.api}${p['url']}'),headers:{'Authorization':'Bearer $token'}).timeout(const Duration(seconds:20));
        if(response.statusCode==200)fetched[p['id'] as int]=response.bodyBytes;
       }));
      }
      if(mounted)setState((){priorInspection=result;previousPhotos..clear()..addAll(fetched);detailsVisible=true;});
    }catch(e){if(mounted)setState(()=>message=tr('Could not load the previous report. Check connection.','تعذر جلب التقرير السابق. تحقق من الاتصال.'));}
  }
  Future<void> addDamage() async {
    final area=TextEditingController(),description=TextEditingController();
    String type='scratch',state=receiving?'existing':'new';
    await showDialog<void>(context:context,builder:(ctx)=>StatefulBuilder(builder:(ctx,redraw)=>AlertDialog(
      backgroundColor:blue,title:Text(tr('Document damage','توثيق الضرر'),style:const TextStyle(color:Colors.white)),
      content:SingleChildScrollView(child:Column(mainAxisSize:MainAxisSize.min,children:[
        TextField(controller:area,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:tr('Area (door, bumper...)','الموقع (باب، صدام...)'))),
        DropdownButtonFormField<String>(value:type,dropdownColor:blue,style:const TextStyle(color:Colors.white),
          decoration:InputDecoration(labelText:tr('Damage type','نوع الضرر')),
          items:conditionOptions(const ['scratch','dent','accident','broken','missing','other']),onChanged:(v)=>redraw(()=>type=v??type)),
        TextField(controller:description,maxLines:3,style:const TextStyle(color:Colors.white),decoration:InputDecoration(labelText:tr('Description','الوصف'))),
        DropdownButtonFormField<String>(value:state,dropdownColor:blue,style:const TextStyle(color:Colors.white),
          decoration:InputDecoration(labelText:tr('Damage status','حالة الضرر')),
          items:conditionOptions(const ['existing','new']),onChanged:(v)=>redraw(()=>state=v??state)),
      ])),actions:[TextButton(onPressed:()=>Navigator.pop(ctx),child:Text(tr('Cancel','إلغاء'))),
        TextButton(onPressed:(){if(area.text.trim().length<2||description.text.trim().length<3)return;
          if(damage.length>=10)return;
          setState(()=>damage.add({'area':area.text.trim(),'description':description.text.trim(),'kind':type,'status':state}));Navigator.pop(ctx);
        },child:Text(tr('Add','إضافة')))])));
    area.dispose();description.dispose();
  }
  Future<void> submit() async {
    if(submitting||!online)return;
    if(selectedVehicleId==null){setState(()=>message=tr('Select a plate.','اختر لوحة المركبة.'));return;}
    if(!requiredPhotos.every(photos.containsKey)||damage.asMap().keys.any((i)=>!photos.containsKey('damage_$i'))
      ||(missingItems.isNotEmpty&&!photos.containsKey('equipment')&&!photos.keys.any((k)=>k.startsWith('damage_')))
      ||(['warning','problem'].contains(engine)&&!photos.containsKey('engine'))){
      setState(()=>message=tr('Complete all eight required photos plus each damage, missing item or engine warning photo.','أكمل الصور الثماني وصور الأضرار والمعدات الناقصة أو مشاكل المحرك.'));return;}
    final km=double.tryParse(odometer.text.trim());
    if(km==null||km<0){setState(()=>message=tr('Enter a valid odometer reading.','أدخل قراءة عداد صحيحة.'));return;}
    if(!acknowledged){setState(()=>message=tr('Confirm the condition report before submitting.','أكد صحة بيانات الفحص قبل الإرسال.'));return;}
    setState((){submitting=true;message='';});
    try{
      await verifyOnline();
      if(!await widget.canSwitchVehicle())throw StateError(tr(
        'Finish and synchronize all recorded trips before changing your vehicle.',
        'يجب إنهاء ومزامنة الرحلات المسجلة قبل تغيير العهدة.'));
      final encoded=photos.entries.map((e)=>{'category':e.key.startsWith('damage_')?'damage':e.key,'note':e.key.startsWith('damage_')?damage[int.parse(e.key.substring(7))]['area']:'',
        'data_base64':base64Encode(e.value),'mime_type':'image/jpeg'}).toList();
      final response=await apiCall(receiving?'/driver/receive':'/driver/return',method:'POST',timeout:const Duration(seconds:110),body:{
        'vehicle_id':selectedVehicleId,'odometer_km':km,'engine_status':engine,
        'interior_status':interior,'dashboard_warnings':warnings.text.trim(),
        'missing_items':missingItems.toList(),'damage_items':damage,'notes':notes.text.trim(),
        'photos':encoded,'acknowledged':true,
      });
      clearForm();
      var identityRefreshFailed=false;
      if(response['vehicle_linked']==true||response['vehicle_released']==true){
        try{await widget.onAssignmentChanged();}catch(_){identityRefreshFailed=true;}
      }
      if(!mounted)return;
      await refresh();
      if(!mounted)return;
      setState(()=>message=identityRefreshFailed
        ?tr('The server accepted the handover, but local vehicle identity needs refreshing. Reopen My Vehicle before driving.',
             'أكد الخادم التسليم أو الاستلام، لكن يلزم تحديث هوية المركبة محلياً. أعد فتح مركبتي قبل القيادة.')
        :response['requires_supervisor']==true
          ?tr('Submitted online. Waiting for supervisor approval.','تم إرسال الفحص. بانتظار موافقة المشرف.')
          :tr('Handover confirmed by the backend.','تم تأكيد الاستلام/التسليم من الخادم.'));
    }on SocketException{if(mounted)setState((){online=false;photos.clear();message=tr('No internet. Nothing was saved locally. Refresh and retry.','لا يوجد إنترنت. لم يتم حفظ أي صور محلياً. أعد الاتصال.');});}
    on TimeoutException{if(mounted)setState((){online=false;photos.clear();message=tr('Server timeout. Nothing was saved locally. Refresh server status before retrying.','انتهت مهلة الخادم. لم تُحفظ الصور محلياً. تحقق من الحالة قبل الإعادة.');});}
    catch(e){if(mounted)setState(()=>message=e.toString());}
    finally{if(mounted)setState(()=>submitting=false);}
  }
  // Keep dropdown entries strongly typed for DropdownButtonFormField<String>.
  List<DropdownMenuItem<String>> conditionOptions(List<String> values) =>
      values.map((value) => DropdownMenuItem<String>(
        value: value,
        child: Text(value),
      )).toList();

  // Separate builders avoid accidental missing parentheses in a nested
  // collection-spread and preserve each photo's category key.
  Widget requiredPhotoButton(String key) => Padding(
    padding: const EdgeInsets.only(bottom: 7),
    child: OutlinedButton.icon(
      icon: Icon(
        photos.containsKey(key) ? Icons.check_circle : Icons.camera_alt,
        color: photos.containsKey(key) ? lime : Colors.white70,
      ),
      onPressed: () => takePhoto(key),
      label: Text('${photoLabel(key)} ${photos.containsKey(key) ? '✓' : ''}'),
    ),
  );

  Widget damagePhotoButton(MapEntry<int, Map<String, String>> entry) =>
      OutlinedButton.icon(
        onPressed: () => takePhoto('damage_${entry.key}'),
        icon: Icon(
          photos.containsKey('damage_${entry.key}')
              ? Icons.check_circle
              : Icons.camera_alt,
        ),
        label: Text('${photoLabel('damage')}: ${entry.value['area']}'),
      );

  Widget option(String title,Widget control)=>Padding(padding:const EdgeInsets.only(bottom:12),child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[Text(title,style:const TextStyle(color:Colors.white,fontWeight:FontWeight.w600)),const SizedBox(height:6),control]));
  InputDecoration decoration(String hint)=>InputDecoration(hintText:hint,hintStyle:const TextStyle(color:Colors.white54),filled:true,fillColor:blue,border:OutlineInputBorder(borderRadius:BorderRadius.circular(10)));
  Widget panel(Widget child)=>Container(margin:const EdgeInsets.only(bottom:12),padding:const EdgeInsets.all(15),decoration:BoxDecoration(color:blue,borderRadius:BorderRadius.circular(15),border:Border.all(color:Colors.white12)),child:child);
  @override Widget build(BuildContext context){
    final held=assignment!=null;
    final canInspect=online&&!pending;
    final selectionLocked=held||legacyVehicle!=null;
    final currentPlate=assignment?['plate_number']??legacyVehicle?['plate_number'];
    return Scaffold(backgroundColor:navy,appBar:AppBar(backgroundColor:navy,foregroundColor:Colors.white,title:Text(tr('Vehicle handover','استلام وتسليم المركبة','گاڑی وصولی / واپسی')),actions:[IconButton(icon:const Icon(Icons.refresh),onPressed:submitting?null:refresh)]),
      body:Directionality(textDirection:rtl?TextDirection.rtl:TextDirection.ltr,child:ListView(padding:const EdgeInsets.all(16),children:[
        Text(tr('ONLINE ONLY · verified with Nuqati backend','يتطلب الإنترنت · تحقق مباشر من الخادم','صرف انٹرنیٹ پر'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:12),
        if(loading)const Center(child:CircularProgressIndicator(color:lime)),
        if(!online&&!loading)panel(Column(children:[const Icon(Icons.wifi_off,color:Colors.orangeAccent,size:32),const SizedBox(height:8),Text(message,style:const TextStyle(color:Colors.white)),const SizedBox(height:10),ElevatedButton(onPressed:refresh,child:Text(tr('Retry online verification','إعادة التحقق من الإنترنت')))])),
        if(online)...[
          panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
           Text(tr('Assigned vehicle','المركبة الحالية'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),const SizedBox(height:6),
           Text(currentPlate?.toString()??tr('Not assigned','غير مرتبط'),style:const TextStyle(color:Colors.white,fontSize:22,fontWeight:FontWeight.bold)),
           if(held)Text('${assignment!['status']}',style:TextStyle(color:pending?Colors.orangeAccent:lime)),
           if(legacyVehicle!=null)Text(tr('Existing assignment: perform first baseline inspection.','ربط سابق: يجب إجراء فحص الاستلام الأولي.'),style:const TextStyle(color:Colors.white70)),
           const SizedBox(height:8),Text(receiving?tr('Receive / baseline inspection','فحص استلام المركبة'):tr('Return inspection','فحص تسليم المركبة'),style:const TextStyle(color:Colors.white70)),
          ])),
          if(pending)panel(Text(tr('Supervisor approval is pending. You cannot change plates or submit another inspection.','بانتظار موافقة المشرف. لا يمكن تغيير اللوحة أو تقديم فحص آخر.'),style:const TextStyle(color:Colors.orangeAccent))),
          if(canInspect)...[
           panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
             option(tr('Vehicle plate','لوحة المركبة'),DropdownButtonFormField<int>(
               key:ValueKey(selectedVehicleId),value:selectedVehicleId,
               isExpanded:true,dropdownColor:blue,style:const TextStyle(color:Colors.white),
               decoration:decoration(tr('Select company plate','اختر لوحة الشركة')),
               items:vehicles.where((e)=>e['available']==true||e['id']==selectedVehicleId)
                 .map<DropdownMenuItem<int>>((v)=>DropdownMenuItem<int>(value:v['id'] as int,child:Text('${v['plate_number']}  ·  ${v['make_model']??''}',overflow:TextOverflow.ellipsis))).toList(),
               onChanged:selectionLocked?null:(value){setState((){selectedVehicleId=value;priorInspection=null;detailsVisible=false;photos.clear();});},
             )),
             OutlinedButton.icon(onPressed:selectedVehicleId==null?null:loadPreviousCondition,icon:const Icon(Icons.history),label:Text(tr('Review previous condition report','عرض آخر تقرير حالة للمركبة'))),
             if(detailsVisible&&priorInspection!=null)Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
               const SizedBox(height:12),Text(tr('Previous inspection','الفحص السابق'),style:const TextStyle(color:lime,fontWeight:FontWeight.bold)),
               Text('${tr('Odometer','العداد')}: ${priorInspection!['odometer_km']} km · ${tr('Engine','المحرك')}: ${priorInspection!['engine_status']}',style:const TextStyle(color:Colors.white)),
               Text('${tr('Damage','الأضرار')}: ${(priorInspection!['damage_items'] as List?)?.length??0} · ${tr('Missing','المفقود')}: ${(priorInspection!['missing_items'] as List?)?.join(', ')??'-'}',style:const TextStyle(color:Colors.white70)),
               Wrap(spacing:8,runSpacing:8,children:previousPhotos.entries.map((e)=>ClipRRect(borderRadius:BorderRadius.circular(9),child:Image.memory(e.value,width:125,height:95,fit:BoxFit.cover))).toList()),
             ])
           ])),
           panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
             Text(tr('1. Photograph the vehicle','١. تصوير المركبة'),style:const TextStyle(color:lime,fontSize:16,fontWeight:FontWeight.bold)),
             const SizedBox(height:10),Text(tr('Take all 8 photos. Photos are never stored as offline drafts.','التقط الصور الثماني. لا تُحفظ الصور في مسودات دون اتصال.'),style:const TextStyle(color:Colors.white70)),const SizedBox(height:10),
             ...requiredPhotos.map(requiredPhotoButton),
             ...damage.asMap().entries.map(damagePhotoButton),
             OutlinedButton.icon(onPressed:()=>takePhoto('engine'),icon:const Icon(Icons.camera_alt),label:Text(photoLabel('engine'))),
             if(missingItems.isNotEmpty)OutlinedButton.icon(onPressed:()=>takePhoto('equipment'),icon:const Icon(Icons.camera_alt),label:Text(photoLabel('equipment'))),
             Text('${photos.length} ${tr('photos ready in memory for online submission','صور جاهزة للإرسال الفوري فقط')}',style:const TextStyle(color:Colors.white70,fontSize:12)),
           ])),
           panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
             Text(tr('2. Vehicle condition','٢. حالة المركبة'),style:const TextStyle(color:lime,fontSize:16,fontWeight:FontWeight.bold)),const SizedBox(height:12),
             option(tr('Odometer in km','قراءة العداد بالكيلومتر'),TextField(controller:odometer,keyboardType:const TextInputType.numberWithOptions(decimal:true),style:const TextStyle(color:Colors.white),decoration:decoration('km'))),
             option(tr('Engine condition / warning','حالة المحرك'),DropdownButtonFormField<String>(value:engine,dropdownColor:blue,style:const TextStyle(color:Colors.white),decoration:decoration(''),items:conditionOptions(const ['normal','warning','problem','unknown']),onChanged:(v)=>setState(()=>engine=v??engine))),
             option(tr('Interior condition','حالة المقصورة'),DropdownButtonFormField<String>(value:interior,dropdownColor:blue,style:const TextStyle(color:Colors.white),decoration:decoration(''),items:conditionOptions(const ['normal','damaged','dirty']),onChanged:(v)=>setState(()=>interior=v??interior))),
             option(tr('Dashboard warning messages','رسائل تحذير الطبلون'),TextField(controller:warnings,maxLength:500,style:const TextStyle(color:Colors.white),decoration:decoration(tr('None if normal','اتركه فارغاً عند عدم وجود تحذير')))),
             Text(tr('Missing equipment','المعدات الناقصة'),style:const TextStyle(color:Colors.white,fontWeight:FontWeight.bold)),
             ...['spare_tire','jack','tools','first_aid','fire_extinguisher','extra_key'].map((item)=>CheckboxListTile(
               contentPadding:EdgeInsets.zero,activeColor:lime,checkColor:navy,
               title:Text(item.replaceAll('_',' '),style:const TextStyle(color:Colors.white)),
               value:missingItems.contains(item),onChanged:(v)=>setState((){if(v==true){missingItems.add(item);}else{missingItems.remove(item);}}))),
             OutlinedButton.icon(onPressed:addDamage,icon:const Icon(Icons.add_photo_alternate_outlined),label:Text(tr('Report existing / new scratch or damage','أضف خدشاً أو ضرراً قديماً / جديداً'))),
             ...damage.asMap().entries.map((entry)=>ListTile(contentPadding:EdgeInsets.zero,
               title:Text('${entry.value['area']} · ${entry.value['kind']}',style:const TextStyle(color:Colors.white)),
               subtitle:Text('${entry.value['status']} · ${entry.value['description']}',style:const TextStyle(color:Colors.white70)),
               trailing:IconButton(icon:const Icon(Icons.close,color:Colors.orangeAccent),onPressed:()=>setState((){damage.removeAt(entry.key);photos.removeWhere((k,v)=>k.startsWith('damage_'));})))),
             option(tr('Other notes','ملاحظات أخرى'),TextField(controller:notes,maxLines:3,maxLength:2000,style:const TextStyle(color:Colors.white),decoration:decoration(''))),
           ])),
           panel(Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
             CheckboxListTile(contentPadding:EdgeInsets.zero,activeColor:lime,checkColor:navy,
              title:Text(tr('I confirm the condition and photographs are accurate.','أقر بصحة بيانات الفحص والصور المرفقة.'),style:const TextStyle(color:Colors.white)),
              value:acknowledged,onChanged:(v)=>setState(()=>acknowledged=v??false)),
             const SizedBox(height:8),ElevatedButton.icon(
               style:ElevatedButton.styleFrom(backgroundColor:lime,foregroundColor:navy,padding:const EdgeInsets.all(16)),
               onPressed:submitting?null:submit,icon:submitting?const SizedBox(height:17,width:17,child:CircularProgressIndicator(strokeWidth:2)):const Icon(Icons.verified_user),
               label:Text(submitting?tr('Uploading to server...','جارٍ الإرسال للخادم'):
                 receiving?tr('Receive vehicle · online verification','استلام المركبة · تأكيد إلكتروني'):tr('Return vehicle · online verification','تسليم المركبة · تأكيد إلكتروني'))),
             const SizedBox(height:9),Text(tr('A clean inspection is approved automatically; discrepancies require supervisor review.','يتم اعتماد الفحص السليم تلقائياً؛ والأضرار أو الفروقات تتطلب مراجعة المشرف.'),style:const TextStyle(color:Colors.white70,fontSize:12)),
           ])),
          ],
          if(message.isNotEmpty)panel(Text(message,style:const TextStyle(color:Colors.orangeAccent))),
        ],
      ])));
  }
}
