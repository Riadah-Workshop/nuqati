import { Fragment, useEffect, useState } from 'react';
import { Activity, CarFront, Users, Route, Gauge, Wrench, Plus, RefreshCw, ShieldCheck, LogOut, Building2, UserCog, Trash2 } from 'lucide-react';

const API = import.meta.env.VITE_API_BASE_URL ?? '';
type Vehicle = {id:number; company_id:number; plate_number:string; make_model:string; year:number|null; odometer_km:number|null; assigned_driver_id?:number|null};
type Driver = {id:number; company_id:number; full_name:string; phone:string; status:string};
type Company = {id:number; name:string};
type Me = {id:number;email:string;full_name:string;role:string;company_id:number|null};
export default function App() {
  const [lang,setLang]=useState<'en'|'ar'>(()=>localStorage.getItem('nuqati_lang')==='en'?'en':'ar');
  const [branding,setBranding]=useState<{logo_data:string;labels:Record<string,Record<string,string>>}>({logo_data:'',labels:{}});
  const [defaults,setDefaults]=useState<Record<string,Record<string,string>>>({});
  const [inviteToken]=useState(()=>new URLSearchParams(window.location.search).get('invite')||'');
  const [invitePassword,setInvitePassword]=useState('');
  const [inviteStatus,setInviteStatus]=useState('');
  const [invite,setInvite]=useState({email:'',full_name:'',role:'company_admin',company_id:''});
  const label=(key:string,en:string,ar:string)=>branding.labels[key]?.[lang]||defaults[key]?.[lang]||(lang==='en'?en:ar);
  const logo=branding.logo_data||'/solutions-logo.png';
  useEffect(()=>{fetch(`${API}/api/v1/public/branding`).then(r=>r.json()).then(setBranding).catch(()=>{});fetch(`${API}/api/v1/public/label-defaults`).then(r=>r.json()).then(setDefaults).catch(()=>{});},[]);
  function switchLang(next:'en'|'ar'){setLang(next);localStorage.setItem('nuqati_lang',next);document.documentElement.lang=next;document.documentElement.dir=next==='ar'?'rtl':'ltr';}
  async function acceptInvite(e:React.FormEvent){e.preventDefault();try{const r=await fetch(`${API}/api/v1/invitations/accept`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:inviteToken,password:invitePassword})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Activation failed');setInviteStatus('Account activated. Return to the login page.');setInvitePassword('');}catch(err){setInviteStatus(String(err));}}
  async function sendInvite(e:React.FormEvent){e.preventDefault();try{await request('/api/v1/invitations',{method:'POST',body:JSON.stringify({...invite,company_id:invite.role==='workshop_staff'?null:Number(invite.company_id)})});setMessage('Invitation sent.');setInvite({...invite,email:'',full_name:''});await loadUsers();}catch(err){setMessage(String(err));}}
  async function resendInvite(id:number){try{await request(`/api/v1/invitations/${id}/resend`,{method:'POST'});setMessage('Invitation resent.');}catch(err){setMessage(String(err));}}
  async function saveBranding(){try{await request('/api/v1/admin/branding',{method:'PUT',body:JSON.stringify(branding)});setMessage('Branding saved.');}catch(err){setMessage(String(err));}}
  async function chooseLogo(file:File|undefined){if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>220000){setMessage('Choose PNG, JPEG or WebP under 220 KB');return;}const reader=new FileReader();reader.onload=()=>setBranding(b=>({...b,logo_data:String(reader.result)}));reader.readAsDataURL(file);}
  const [token,setToken]=useState(()=>sessionStorage.getItem('nuqati_token')||'');
  const [me,setMe]=useState<Me|null>(null);
  const [email,setEmail]=useState(''); const [password,setPassword]=useState('');
  const [loginError,setLoginError]=useState('');
  const [newUser,setNewUser]=useState({email:'',full_name:'',password:'',role:'company_admin',company_id:''});
  const [users,setUsers]=useState<(Me&{is_active:boolean})[]>([]);
  const [selectedInviteUserId,setSelectedInviteUserId]=useState('');
  const [accountForm,setAccountForm]=useState({full_name:'',email:'',role:'company_admin',company_id:'',password:''});
  const [editingUserId,setEditingUserId]=useState<number|null>(null);
  const [userEditForm,setUserEditForm]=useState({full_name:'',role:'company_admin',company_id:'',is_active:true});

  const [selectedCompany,setSelectedCompany]=useState('');
  async function signIn(e:React.FormEvent){e.preventDefault();try{
    const r=await fetch(`${API}/api/v1/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    const data=await r.json();if(!r.ok)throw new Error(data.detail||'Login failed');
    sessionStorage.setItem('nuqati_token',data.access_token);setToken(data.access_token);setMe(data.user);setPassword('');setLoginError('');
  }catch(err){setLoginError(String(err));}}
  function signOut(){sessionStorage.removeItem('nuqati_token');setToken('');setMe(null);setCompanies([]);setDrivers([]);setVehicles([]);}

  const [tab,setTab] = useState<'overview'|'vehicles'|'drivers'|'odometer'|'maintenance'|'companies'|'users'|'reports'|'settings'>('overview');
  const [companies,setCompanies] = useState<Company[]>([]);
  const [vehicles,setVehicles] = useState<Vehicle[]>([]);
  const [drivers,setDrivers] = useState<Driver[]>([]);
  const [driverDetails,setDriverDetails]=useState<Record<string,{id_number:string;site_name:string;vehicle_id:number|null}>>({});
  const [driverLogins,setDriverLogins]=useState<Record<string,string>>({});
  const [editingDriver,setEditingDriver]=useState<number|null>(null);
  const [driverEditForm,setDriverEditForm]=useState({full_name:'',phone:'',status:'active',id_number:'',site_name:'',vehicle_id:''});
  async function loadDriverExtras(){
    try{const [details,acks]=await Promise.all([request('/api/v1/drivers/details'),request('/api/v1/drivers/login-acknowledgments')]);setDriverDetails(details.drivers||{});setDriverLogins(acks.last_logins||{});}catch(err){setMessage(String(err));}
  }
  function beginDriverEdit(d:Driver){const meta=driverDetails[String(d.id)];setEditingDriver(d.id);setDriverEditForm({full_name:d.full_name,phone:d.phone,status:d.status,id_number:meta?.id_number||'',site_name:meta?.site_name||'',vehicle_id:meta?.vehicle_id?String(meta.vehicle_id):''});}
  async function saveDriverEdit(){if(editingDriver===null)return;try{
    await request(`/api/v1/drivers/${editingDriver}`,{method:'PATCH',body:JSON.stringify({...driverEditForm,vehicle_id:driverEditForm.vehicle_id?Number(driverEditForm.vehicle_id):null})});
    setEditingDriver(null);await load();await loadDriverExtras();setMessage('Driver updated successfully');
  }catch(err){setMessage(String(err));}}

  const [stats,setStats] = useState({companies:0,drivers:0,vehicles:0,trips_active:0});
  const [message,setMessage] = useState('');
  const [reportPeriod,setReportPeriod]=useState('daily');
  const [reportDriver,setReportDriver]=useState('');
  const [reportCompany,setReportCompany]=useState('');
  const [report,setReport]=useState<any>(null);
  const [selectedRoute,setSelectedRoute]=useState<any>(null);
  const [routeLoading,setRouteLoading]=useState(false);
  const [companyLogos,setCompanyLogos]=useState<Record<number,string>>({});
  const [expandedCompany,setExpandedCompany]=useState<number|null>(null);
  const [editingCompany,setEditingCompany]=useState<number|null>(null);
  const [companyEditName,setCompanyEditName]=useState('');
  const [logoCompanyId,setLogoCompanyId]=useState('');
  const [editingCompanyVehicle,setEditingCompanyVehicle]=useState<number|null>(null);
  const [companyVehicleForm,setCompanyVehicleForm]=useState({plate_number:'',make_model:'',year:'',odometer_km:''});
  function openCompanyEdit(c:Company){setExpandedCompany(c.id);setEditingCompany(c.id);setCompanyEditName(c.name);}
  async function saveCompanyName(){if(editingCompany===null||!companyEditName.trim())return;try{await request(`/api/v1/companies/${editingCompany}`,{method:'PATCH',body:JSON.stringify({name:companyEditName.trim()})});await load();setEditingCompany(null);setMessage('Company name saved');}catch(e){setMessage(String(e));}}
  function beginCompanyVehicleEdit(v:Vehicle){setEditingCompanyVehicle(v.id);setCompanyVehicleForm({plate_number:v.plate_number,make_model:v.make_model,year:v.year==null?'':String(v.year),odometer_km:v.odometer_km==null?'':String(v.odometer_km)});}
  async function saveCompanyVehicle(){if(editingCompanyVehicle===null)return;try{await request(`/api/v1/vehicles/${editingCompanyVehicle}`,{method:'PATCH',body:JSON.stringify({plate_number:companyVehicleForm.plate_number,make_model:companyVehicleForm.make_model,year:companyVehicleForm.year?Number(companyVehicleForm.year):null,odometer_km:companyVehicleForm.odometer_km?Number(companyVehicleForm.odometer_km):null})});await load();setEditingCompanyVehicle(null);setMessage('Vehicle saved');}catch(e){setMessage(String(e));}}

  async function viewTripRoute(id:number){setRouteLoading(true);try{setSelectedRoute(await request(`/api/v1/fleet/trips/${id}/route`));}catch(e){setMessage(String(e));}finally{setRouteLoading(false);}}
  async function loadCompanyLogo(id:number){try{const r=await request(`/api/v1/companies/${id}/driver-logo`);setCompanyLogos(old=>({...old,[id]:r.logo_data||''}));}catch(e){setMessage(String(e));}}
  async function uploadCompanyLogo(id:number,file?:File){if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>220000){setMessage('PNG/JPEG/WebP only, maximum 220 KB');return;}const reader=new FileReader();reader.onload=async()=>{try{const logo_data=String(reader.result);await request(`/api/v1/companies/${id}/driver-logo`,{method:'PUT',body:JSON.stringify({logo_data})});setCompanyLogos(old=>({...old,[id]:logo_data}));setMessage('Company driver logo saved');}catch(e){setMessage(String(e));}};reader.readAsDataURL(file);}

  const [reportLoading,setReportLoading]=useState(false);
  const [speedThreshold,setSpeedThreshold]=useState('100');
  const [accelThreshold,setAccelThreshold]=useState('3');
  const [brakeThreshold,setBrakeThreshold]=useState('3');
  const [driverLinks,setDriverLinks]=useState<{driver_id:number;user_id:number;email:string;vehicle_id:number|null}[]>([]);
  const [linkSelection,setLinkSelection]=useState<Record<number,{user_id:string;vehicle_id:string}>>({});
  const [driverAccount,setDriverAccount]=useState({driver_id:'',email:'',full_name:'',password:''});
  async function fetchReport(period=reportPeriod,driver=reportDriver,company=reportCompany){
    setReportLoading(true);try{
      const cid=me?.role==='super_admin'?(company||companies[0]?.id):me?.company_id;
      if(!cid)throw new Error('Select a company');
      const qs=new URLSearchParams({period,company_id:String(cid)});if(driver)qs.set('driver_id',driver);
      const data=await request('/api/v1/fleet/report?'+qs);setReport(data);setMessage('');
      const settings=await request('/api/v1/fleet/settings?company_id='+cid);setSpeedThreshold(String(settings.speeding_kmh));setAccelThreshold(String(settings.harsh_accel_ms2));setBrakeThreshold(String(settings.harsh_brake_ms2));
    }catch(err){setMessage(String(err));}finally{setReportLoading(false);}
  }
  async function createDriverAccount(e:React.FormEvent){e.preventDefault();try{
    await request('/api/v1/driver-accounts',{method:'POST',body:JSON.stringify({...driverAccount,driver_id:Number(driverAccount.driver_id)})});
    setDriverAccount({driver_id:'',email:'',full_name:'',password:''});setMessage('Driver app account created. Give credentials to the driver securely.');
  }catch(err){setMessage(String(err));}}
  async function saveSpeed(){try{const cid=me?.role==='super_admin'?reportCompany:me?.company_id;if(!cid)throw Error('Select company');const speed=Number(speedThreshold),accel=Number(accelThreshold),brake=Number(brakeThreshold);if(!Number.isFinite(speed)||speed<20||speed>200||!Number.isFinite(accel)||accel<1||accel>10||!Number.isFinite(brake)||brake<1||brake>10)throw Error('Speed: 20–200 km/h; acceleration and braking: 1–10 m/s²');await request('/api/v1/fleet/settings?company_id='+cid,{method:'PUT',body:JSON.stringify({speeding_kmh:speed,harsh_accel_ms2:accel,harsh_brake_ms2:brake})});setMessage('Driving policy saved for selected company');}catch(err){setMessage(String(err));}}
  function exportReport(){if(!report)return;const lines=[['Driver','Trips','Score','Speeding','Harsh braking','Harsh acceleration'],...report.drivers.map((d:any)=>[d.driver_name,d.trips,d.score??'',d.violations.speeding,d.violations.harsh_braking,d.violations.harsh_acceleration])];const csv=lines.map(r=>r.map((v:any)=>'"'+String(v).replace(/ /g,'_')+'"').join(',')).join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download=`nuqati-${report.period}-${report.company_id}.csv`;a.click();URL.revokeObjectURL(a.href);}

  const [companyName,setCompanyName] = useState('حلول الريادة - تجربة');
  const [plate,setPlate] = useState('أ ب ج 1234');
  const [model,setModel] = useState('Toyota Camry');
  const [vehicleYear,setVehicleYear] = useState('');
  const [vehicleOdometer,setVehicleOdometer] = useState('');
  const [driverName,setDriverName] = useState('سائق تجريبي');
  const [driverPhone,setDriverPhone] = useState('');
  const [driverIdNumber,setDriverIdNumber]=useState('');const [driverSite,setDriverSite]=useState('');const [driverVehicle,setDriverVehicle]=useState('');const [driverInitialPassword,setDriverInitialPassword]=useState('');
  const [readingVehicle,setReadingVehicle] = useState('');
  type OdometerRecord = {id:number;company_id:number;vehicle_id:number;reading_km:number;source:string;note:string;created_at:string};
  const [odometerRecords,setOdometerRecords]=useState<OdometerRecord[]>([]);
  const [odometerHistoryVehicle,setOdometerHistoryVehicle]=useState('all');
  const [odometerHistoryLoading,setOdometerHistoryLoading]=useState(false);
  async function loadOdometerHistory(){setOdometerHistoryLoading(true);try{const rows=await request('/api/v1/odometer-readings');setOdometerRecords(Array.isArray(rows)?rows:[]);}catch(err){setMessage('Could not load odometer history: '+String(err));}finally{setOdometerHistoryLoading(false);}}
  useEffect(()=>{if(tab==='odometer'&&me)void loadOdometerHistory();},[tab,me?.id]);
  const [reading,setReading] = useState('');
  const [source,setSource] = useState('MANUAL');
  type Schedule = {id:number;vehicle_id:number;service_type:string;interval_km:number;last_service_km:number;next_due_km:number;current_odometer_km:number|null;remaining_km:number|null;status:string};
  const [schedules,setSchedules] = useState<Schedule[]>([]);
  const [serviceType,setServiceType] = useState('ENGINE_OIL');
  const [interval,setInterval] = useState('5000');
  const [lastService,setLastService] = useState('0');
  const [warningBefore,setWarningBefore] = useState('500');
  async function request(path:string, options?:RequestInit) {
    const r = await fetch(`${API}${path}`, {headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`} : {}),...(options?.headers||{})},...options});
    if(!r.ok) { const body = await r.json().catch(()=>({})); throw new Error(body.detail || `HTTP ${r.status}`); }
    return r.json();
  }
  async function load() {
    try {
      const [s,c,v,d,m] = await Promise.all([request('/api/v1/dashboard'),request('/api/v1/companies'),request('/api/v1/vehicles'),request('/api/v1/drivers'),request('/api/v1/maintenance-schedules')]);
      setStats(s); setCompanies(c); setVehicles(v); setDrivers(d); setSchedules(m); if(me?.role==='super_admin'||me?.role==='company_admin'||me?.role==='fleet_manager'){loadDriverLinks();loadUsers();} setMessage('');
      if(!readingVehicle && v[0]) setReadingVehicle(String(v[0].id));
    } catch(err) { setMessage(String(err)); }
  }
  useEffect(()=>{if(!token)return;request('/api/v1/auth/me').then(setMe).then(()=>load()).catch(()=>signOut());},[token]);
  async function loadUsers(){try{setUsers(await request('/api/v1/users'));}catch(err){setMessage(String(err));}}
  async function loadDriverLinks(){try{setDriverLinks(await request('/api/v1/driver-accounts'));}catch(err){setMessage(String(err));}}
  async function linkDriver(driverId:number){
    const selection=linkSelection[driverId];if(!selection?.user_id){setMessage('Select a driver login account');return;}
    try{await request(`/api/v1/drivers/${driverId}/account-link`,{method:'PUT',body:JSON.stringify({user_id:Number(selection.user_id),vehicle_id:selection.vehicle_id?Number(selection.vehicle_id):null})});await load();await loadDriverLinks();setMessage('Driver login linked. Reopen the Android app.');}catch(err){setMessage(String(err));}
  }

  async function submitAccount(e:React.FormEvent){
    e.preventDefault();
    try{
      const data={full_name:accountForm.full_name.trim(),email:accountForm.email.trim(),role:accountForm.role,company_id:Number(accountForm.company_id)};
      await request('/api/v1/invitations',{method:'POST',body:JSON.stringify(data)});
      setAccountForm({full_name:'',email:'',role:'company_admin',company_id:'',password:''});
      await loadUsers();
      setMessage('User created and invitation email sent. The user must set a password to activate the account.');
    }catch(err){setMessage(String(err));}
  }
  async function sendSelectedUserEmail(){
    if(!selectedInviteUserId){setMessage('Choose a user first.');return;}
    try{
      const result=await request(`/api/v1/invitations/${Number(selectedInviteUserId)}/resend`,{method:'POST'});
      setMessage(result.status==='reminder_sent'?'Sign-in reminder sent to the active user.':'Invitation sent to the selected user.');
      await loadUsers();
    }catch(err){setMessage(String(err));}
  }
  function beginUserEdit(u:Me&{is_active:boolean}){
    setEditingUserId(u.id);
    setUserEditForm({full_name:u.full_name,role:u.role,company_id:String(u.company_id??''),is_active:u.is_active});
  }
  async function saveUserEdit(){
    if(editingUserId===null)return;
    try{
      await request(`/api/v1/users/${editingUserId}`,{method:'PATCH',body:JSON.stringify({
        full_name:userEditForm.full_name.trim(),role:userEditForm.role,
        company_id:userEditForm.role==='super_admin'?null:Number(userEditForm.company_id),
        is_active:userEditForm.is_active
      })});
      setEditingUserId(null);await loadUsers();setMessage('User changes saved.');
    }catch(err){setMessage(String(err));}
  }
  async function addUser(e:React.FormEvent){e.preventDefault();try{await request('/api/v1/users',{method:'POST',body:JSON.stringify({...newUser,company_id:Number(newUser.company_id)||null})});await loadUsers();setMessage('تم إنشاء المستخدم');setNewUser({...newUser,email:'',full_name:'',password:''});}catch(err){setMessage(String(err));}}
  async function deactivate(id:number){if(!window.confirm('Deactivate this user?'))return;try{await request(`/api/v1/users/${id}/deactivate`,{method:'PATCH'});await loadUsers();}catch(err){setMessage(String(err));}}
  async function adminEdit(kind:'users'|'companies'|'drivers'|'vehicles',id:number,field:string,current:string|number|null){
    const value=window.prompt(`Edit ${field}`,String(current??''));if(value===null)return;
    const data:Record<string,string|number|null|boolean>={};data[field]=field==='company_id'||field==='assigned_driver_id'||field==='year'?(value?Number(value):null):field==='is_active'?value.toLowerCase()==='true':value;
    try{await request(`/api/v1/${kind}/${id}`,{method:'PATCH',body:JSON.stringify(data)});await load();if(kind==='users')await loadUsers();setMessage('Updated successfully');}catch(err){setMessage(String(err));}
  }
  async function adminDelete(kind:'users'|'drivers'|'vehicles'|'maintenance-schedules',id:number){
    if(!window.confirm(`Delete ${kind} #${id}? Historical trip records cannot be deleted individually; archive the driver or permanently delete the company if needed.`))return;
    try{await request(`/api/v1/${kind}/${id}`,{method:'DELETE'});await load();if(kind==='users')await loadUsers();setMessage('Deleted successfully');}catch(err){setMessage(String(err));}
  }
  async function removeCompany(id:number){try{
    const preview=await request(`/api/v1/companies/${id}/deletion-preview`);
    const counts=Object.entries(preview.counts).map(([key,value])=>`${key}: ${value}`).join('\n');
    const confirmedName=window.prompt(`PERMANENTLY DELETE company #${id}: ${preview.company_name}\n\nALL linked records will be erased.\n\n${counts}\n\nFirst: type the exact company name:`);
    if(confirmedName===null)return;
    if(confirmedName!==preview.company_name){setMessage('Name did not match. Nothing deleted.');return;}
    const word=window.prompt('Second: type DELETE in uppercase to confirm irreversible deletion:');
    if(word!=='DELETE'){setMessage('Deletion cancelled.');return;}
    let backupReference: string | null = null;
    if(preview.requires_backup){
      backupReference=window.prompt('Third: enter the exact verified OFF-SERVER database backup reference configured by the operator in Coolify:');
      if(!backupReference){setMessage('Backup reference required. Nothing deleted.');return;}
    }else{
      if(!window.confirm('STAGING ONLY: No verified backup is required. Deletion is permanent and recovery may be impossible. Continue?'))return;
    }
    if(!window.confirm(`FINAL WARNING: Permanently delete ${preview.company_name} and ALL associated data?`))return;
    await request(`/api/v1/companies/${id}/permanent-delete`,{method:'POST',body:JSON.stringify({confirm_name:confirmedName,confirm_word:word,backup_reference:backupReference})});
    await load();await loadUsers();setMessage('Company permanently deleted. Audit entry recorded.');
  }catch(err){setMessage(String(err));}}

  async function addCompany(e:React.FormEvent) { e.preventDefault(); try { await request('/api/v1/companies',{method:'POST',body:JSON.stringify({name:companyName})}); await load(); setMessage('تمت إضافة الشركة.'); } catch(err) {setMessage(String(err));} }
  async function addVehicle(e:React.FormEvent) { e.preventDefault(); if(!selectedCompany && !companies[0]) {setMessage('أضف شركة أولًا.'); return;} try { await request('/api/v1/vehicles',{method:'POST',body:JSON.stringify({company_id:Number(selectedCompany||companies[0].id),plate_number:plate.trim(),make_model:model.trim(),year:vehicleYear?Number(vehicleYear):null,odometer_km:vehicleOdometer?Number(vehicleOdometer):null})}); await load(); setVehicleYear('');setVehicleOdometer('');setMessage('تمت إضافة السيارة.'); } catch(err) {setMessage(String(err));} }
  useEffect(()=>{if(tab==='drivers'&&me)void loadDriverExtras();},[tab,me?.id]);
  async function addDriver(e:React.FormEvent){e.preventDefault();try{
    const companyId=Number(me?.role==='super_admin'?(selectedCompany||companies[0]?.id):me?.company_id);
    if(!companyId||!driverVehicle)throw Error('Select a company and an available vehicle');
    await request('/api/v1/drivers/onboard',{method:'POST',body:JSON.stringify({company_id:companyId,full_name:driverName,phone:driverPhone,id_number:driverIdNumber,site_name:driverSite,vehicle_id:Number(driverVehicle),initial_password:driverInitialPassword})});
    setDriverName('');setDriverPhone('');setDriverIdNumber('');setDriverSite('');setDriverVehicle('');setDriverInitialPassword('');await load();setMessage('Driver, phone login and vehicle assignment created together. Share the private temporary password securely.');
  }catch(err){setMessage(String(err));}}
  async function addReading(e:React.FormEvent) { e.preventDefault(); if(!readingVehicle || !vehicles.length) {setMessage('أضف سيارة أولًا.'); return;} const v=vehicles.find(x=>x.id===Number(readingVehicle)); if(!v) return; try { await request('/api/v1/odometer-readings',{method:'POST',body:JSON.stringify({company_id:v.company_id,vehicle_id:v.id,reading_km:Number(reading),source,note:'تم الإدخال من لوحة نقاطي'})}); await load(); await loadOdometerHistory(); setMessage('تم حفظ قراءة العداد.'); setReading(''); } catch(err) {setMessage(String(err));} }
  async function saveSchedule(e:React.FormEvent) { e.preventDefault(); const v=vehicles.find(x=>x.id===Number(readingVehicle)); if(!v) {setMessage('اختر سيارة أولًا.');return;} try {await request('/api/v1/maintenance-schedules',{method:'PUT',body:JSON.stringify({company_id:v.company_id,vehicle_id:v.id,service_type:serviceType,interval_km:Number(interval),last_service_km:Number(lastService),warning_before_km:Number(warningBefore)})});await load();setMessage('تم حفظ جدول الصيانة.');}catch(err){setMessage(String(err));}}
  const nav = [{id:'overview',label:label('overview','Overview','نظرة عامة'),icon:Activity},{id:'companies',label:label('companies','Companies','الشركات'),icon:Building2},{id:'users',label:label('users','Users & Access','المستخدمون والصلاحيات'),icon:UserCog},{id:'vehicles',label:label('vehicles','Vehicles','السيارات'),icon:CarFront},{id:'drivers',label:label('drivers','Drivers','السائقون'),icon:Users},{id:'odometer',label:label('odometer','Odometer','قراءة العداد'),icon:Gauge},{id:'maintenance',label:label('maintenance','Maintenance Alerts','تنبيهات الصيانة'),icon:Wrench},{id:'reports',label:label('reports','Fleet Reports','تقارير الأسطول'),icon:Route},{id:'settings',label:label('settings','Branding & Language','الهوية واللغة'),icon:UserCog}] as const;
  if(inviteToken) return <div className="login-screen"><form className="login-card" onSubmit={acceptInvite}><img src={logo} alt="Nuqati"/><h2>Nuqati by Al-Riadah Workshop</h2><p>Activate account | تفعيل الحساب</p><label>New password (12+ characters)<input type="password" minLength={12} required value={invitePassword} onChange={e=>setInvitePassword(e.target.value)}/></label><button className="primary">Activate account</button><div className="notice">{inviteStatus}</div>{inviteStatus.startsWith('Account activated')&&<a href="/">Go to login</a>}</form></div>;
  if(!token || !me) return <div className="login-screen"><form className="login-card" onSubmit={signIn}><img src={logo} alt="Solutions Workshop"/><h1>NUQATI | نقاطي</h1><p>Secure Fleet Management</p><label>Email<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/></label>{loginError&&<div className="notice">{loginError}</div>}<button className="primary">Sign in</button><small>Nuqati by Al-Riadah Workshop | نقاطي من ورشة حلول الريادة</small><button type="button" className="refresh" onClick={()=>switchLang(lang==='en'?'ar':'en')}>{lang==='en'?'العربية':'English'}</button></form></div>;
  const canManage=me.role==='super_admin';
  const canCreateUsers=me.role==='super_admin';
  return <div className="app-shell" dir={lang==='ar'?'rtl':'ltr'}>
    <aside className="sidebar"><div className="brand"><img className="brand-logo" src={logo} alt="Solutions Workshop"/><div><strong>نقاطي | Nuqati</strong><small>Al-Riadah Workshop</small></div></div>
      <div className="side-caption">إدارة الأسطول</div>{nav.filter(n=>(n.id!=='companies'||me.role==='super_admin')&&(n.id!=='users'||canCreateUsers)&&(n.id!=='settings'||canCreateUsers)).map(n=><button key={n.id} className={`nav-item ${tab===n.id?'active':''}`} onClick={()=>setTab(n.id)}><n.icon size={18}/>{n.label}</button>)}
      <div className="sidebar-bottom"><ShieldCheck size={18}/><span>نسخة تجريبية</span></div>
    </aside>
    <main className="main"><header className="topbar"><div><span className="eyebrow">منصة أداء السائقين</span><h1>{nav.find(n=>n.id===tab)?.label}</h1></div><div className="header-actions"><span className="user-chip">{me.full_name} · {me.role}</span><button className="refresh" onClick={()=>switchLang(lang==='en'?'ar':'en')}>{lang==='en'?'العربية':'English'}</button><button className="refresh" onClick={()=>void load()}><RefreshCw size={16}/> {label('refresh','Refresh','تحديث')}</button><button className="refresh" onClick={signOut}><LogOut size={16}/> {label('logout','Log out','خروج')}</button></div></header>
      {message && <div className="notice" role="status">{message}</div>}
      {tab==='settings' && me.role==='super_admin' && <section className="panel"><h3>Branding & Language | الهوية واللغة</h3><p>Global settings: only Super Admin can publish changes.</p><div className="entry-form"><label>Dashboard logo (PNG, JPEG or WebP; under 220 KB)<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>chooseLogo(e.target.files?.[0])}/></label><img src={logo} alt="Current logo" style={{maxWidth:160,maxHeight:100,objectFit:'contain'}}/><button className="refresh" onClick={()=>setBranding(b=>({...b,logo_data:''}))}>Restore default logo</button></div><h3>Editable navigation and core labels</h3><div className="table-wrap"><table><thead><tr><th>Key</th><th>English</th><th>العربية</th></tr></thead><tbody>{Object.entries(defaults).map(([key,values])=><tr key={key}><td>{key}</td>{(['en','ar'] as const).map(language=><td key={language}><input style={{width:'100%',minWidth:200}} maxLength={120} value={branding.labels[key]?.[language]??values[language]??''} onChange={e=>setBranding(b=>({...b,labels:{...b.labels,[key]:{...(b.labels[key]||{}),[language]:e.target.value}}}))}/></td>)}</tr>)}</tbody></table></div><button className="primary" onClick={saveBranding}>Save branding and labels</button></section>}
      {tab==='companies' && me.role==='super_admin' && <section className="panel"><h3>Client Companies</h3><form onSubmit={addCompany} className="entry-form"><label>Company name<input required value={companyName} onChange={e=>setCompanyName(e.target.value)}/></label><button className="primary">Add company</button></form><div className="table-wrap"><table><thead><tr><th>ID</th><th>Company</th><th>Drivers</th><th>Vehicles</th><th>Users</th><th>Actions</th></tr></thead><tbody>{companies.map(c=><Fragment key={c.id}><tr><td>{c.id}</td><td>{c.name}</td><td>{drivers.filter(d=>d.company_id===c.id).length}</td><td>{vehicles.filter(v=>v.company_id===c.id).length}</td><td>{users.filter(u=>u.company_id===c.id).length}</td><td><button type="button" className="refresh" onClick={()=>{setExpandedCompany(expandedCompany===c.id?null:c.id);setEditingCompany(null);setEditingCompanyVehicle(null);loadUsers();loadDriverExtras();}}>{expandedCompany===c.id?'Hide details':'View / Edit details'}</button> <button type="button" className="refresh" onClick={()=>removeCompany(c.id)}><Trash2 size={14}/> Permanently delete company + linked data</button></td></tr>{expandedCompany===c.id&&<tr><td colSpan={6}><div style={{padding:16,display:'grid',gap:18}}><div><h3>Company details</h3>{editingCompany===c.id?<div className="entry-form"><label>Company name<input value={companyEditName} onChange={e=>setCompanyEditName(e.target.value)}/></label><button type="button" className="primary" onClick={saveCompanyName}>Save company</button><button type="button" className="refresh" onClick={()=>setEditingCompany(null)}>Cancel</button></div>:<button type="button" className="refresh" onClick={()=>openCompanyEdit(c)}>Edit company name inline</button>}</div><div><h3>Drivers ({drivers.filter(d=>d.company_id===c.id).length})</h3>{drivers.filter(d=>d.company_id===c.id).map(d=><div key={d.id} style={{padding:8,borderBottom:'1px solid #345'}}>{d.full_name} — {d.phone} — {d.status} <button type="button" className="refresh" onClick={()=>{beginDriverEdit(d);setTab('drivers');}}>Edit driver fields</button></div>)}{!drivers.some(d=>d.company_id===c.id)&&<p>No drivers</p>}</div><div><h3>Vehicles ({vehicles.filter(v=>v.company_id===c.id).length})</h3>{vehicles.filter(v=>v.company_id===c.id).map(v=><div key={v.id} style={{padding:8,borderBottom:'1px solid #345'}}>{editingCompanyVehicle===v.id?<div className="entry-form"><label>Plate<input value={companyVehicleForm.plate_number} onChange={e=>setCompanyVehicleForm({...companyVehicleForm,plate_number:e.target.value})}/></label><label>Model<input value={companyVehicleForm.make_model} onChange={e=>setCompanyVehicleForm({...companyVehicleForm,make_model:e.target.value})}/></label><label>Year<input type="number" value={companyVehicleForm.year} onChange={e=>setCompanyVehicleForm({...companyVehicleForm,year:e.target.value})}/></label><label>Odometer (km)<input type="number" value={companyVehicleForm.odometer_km} onChange={e=>setCompanyVehicleForm({...companyVehicleForm,odometer_km:e.target.value})}/></label><button type="button" className="primary" onClick={saveCompanyVehicle}>Save vehicle</button><button type="button" className="refresh" onClick={()=>setEditingCompanyVehicle(null)}>Cancel</button></div>:<>{v.plate_number} — {v.make_model} <button type="button" className="refresh" onClick={()=>beginCompanyVehicleEdit(v)}>Edit fields</button></>}</div>)}{!vehicles.some(v=>v.company_id===c.id)&&<p>No vehicles</p>}</div><div><h3>Users ({users.filter(u=>u.company_id===c.id).length})</h3>{users.filter(u=>u.company_id===c.id).map(u=><div key={u.id} style={{padding:8,borderBottom:'1px solid #345'}}>{u.full_name} — {u.role} — {u.email} <button type="button" className="refresh" onClick={()=>{beginUserEdit(u);setTab('users');}}>Edit user fields</button></div>)}{!users.some(u=>u.company_id===c.id)&&<p>No users</p>}</div></div></td></tr>}</Fragment>)}</tbody></table></div></section>}
      {tab==='companies'&&<section className="panel"><h3>Company logo for Android driver app</h3><div className="entry-form"><label>Select company<select value={logoCompanyId} onChange={e=>setLogoCompanyId(e.target.value)}><option value="">Choose company</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label></div>{logoCompanyId&&<div style={{display:'flex',alignItems:'center',gap:12,flexWrap:'wrap',padding:12}}><strong>{companies.find(c=>c.id===Number(logoCompanyId))?.name}</strong><button type="button" className="refresh" onClick={()=>loadCompanyLogo(Number(logoCompanyId))}>View logo</button>{companyLogos[Number(logoCompanyId)]&&<img src={companyLogos[Number(logoCompanyId)]} alt="Company logo" style={{width:90,height:90,objectFit:'contain'}}/>}{(me.role==='super_admin'||me.role==='company_admin')&&<input aria-label="Upload selected company logo" type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>uploadCompanyLogo(Number(logoCompanyId),e.target.files?.[0])}/>}</div>}</section>}
      {tab==='users' && canCreateUsers && <section className="panel">
        <h3>Users & Access | إدارة المستخدمين والصلاحيات</h3>
        <p>Create a user and automatically send an activation invitation. Select any existing user below to resend an invitation or send a sign-in reminder. All edits stay inline.</p>
        <form className="entry-form" onSubmit={submitAccount}>
          <label>Full name<input required minLength={2} value={accountForm.full_name} onChange={e=>setAccountForm({...accountForm,full_name:e.target.value})}/></label>
          <label>Email<input type="email" required value={accountForm.email} onChange={e=>setAccountForm({...accountForm,email:e.target.value})}/></label>
          <label>Role<select value={accountForm.role} onChange={e=>setAccountForm({...accountForm,role:e.target.value})}>{(me.role==='super_admin'?['company_admin','fleet_manager']:['fleet_manager']).map(r=><option key={r} value={r}>{r}</option>)}</select></label>
          <label>Company<select required value={accountForm.company_id} onChange={e=>setAccountForm({...accountForm,company_id:e.target.value})}><option value="">Choose company</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <button className="primary">Create user + Send invitation</button>
        </form>
        <h3>Registered users</h3>
        <div className="entry-form">
          <label>Select user to email
            <select value={selectedInviteUserId} onChange={e=>setSelectedInviteUserId(e.target.value)}>
              <option value="">Choose registered user</option>
              {users.filter(u=>u.role!=='driver' && !u.email.endsWith('@login.nuqati.invalid')).map(u=><option key={u.id} value={u.id}>{u.full_name} — {u.email} — {u.is_active?'Active':'Pending'}</option>)}
            </select>
          </label>
          <button type="button" className="primary" disabled={!selectedInviteUserId} onClick={sendSelectedUserEmail}>Send invitation / Reminder</button>
          <button type="button" className="refresh" onClick={loadUsers}>Refresh users</button>
        </div>
        <div className="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Company</th><th>Status</th><th>Actions</th></tr></thead><tbody>
          {users.map(u=><tr key={u.id}>
            <td>{u.full_name}</td><td>{u.email}</td><td>{u.role}</td><td>{companies.find(c=>c.id===u.company_id)?.name||'Workshop'}</td><td>{u.is_active?'Active':'Disabled / Pending'}</td>
            <td>{me.role==='super_admin'&&<button type="button" className="refresh" onClick={()=>beginUserEdit(u)}>Edit details</button>}{!u.is_active&&<button type="button" className="refresh" onClick={()=>resendInvite(u.id)}>Resend invitation</button>}{u.id!==me.id&&<button type="button" className="refresh" onClick={()=>deactivate(u.id)}>Deactivate</button>}{me.role==='super_admin'&&u.id!==me.id&&<button type="button" className="refresh" onClick={()=>adminDelete('users',u.id)}>Delete</button>}</td>
          </tr>)}
        </tbody></table></div>
        {editingUserId!==null&&<div className="panel" style={{marginTop:16}}>
          <h3>Edit user #{editingUserId}</h3>
          <div className="entry-form">
            <label>Full name<input required value={userEditForm.full_name} onChange={e=>setUserEditForm({...userEditForm,full_name:e.target.value})}/></label>
            <label>Role<select value={userEditForm.role} onChange={e=>setUserEditForm({...userEditForm,role:e.target.value})}>{['super_admin','company_admin','fleet_manager','representative','driver','workshop_staff'].map(r=><option key={r} value={r}>{r}</option>)}</select></label>
            {userEditForm.role!=='super_admin'&&<label>Company<select value={userEditForm.company_id} onChange={e=>setUserEditForm({...userEditForm,company_id:e.target.value})}><option value="">Choose company</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
            <label>Status<select value={userEditForm.is_active?'active':'inactive'} onChange={e=>setUserEditForm({...userEditForm,is_active:e.target.value==='active'})}><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
            <button type="button" className="primary" onClick={saveUserEdit}>Save changes</button>
            <button type="button" className="refresh" onClick={()=>setEditingUserId(null)}>Cancel</button>
          </div><p>Email and password are not editable through this endpoint; invitation and password reset remain separate secure flows.</p>
        </div>}
      </section>}
      {tab==='reports' && <section className="panel"><h3>Fleet Intelligence · Driver Reports</h3><p>Company administrators see only their own drivers. Select a driver for individual trip and violation details. Latest location is not necessarily live.</p>
        <div className="entry-form">{me.role==='super_admin'&&<label>Company<select value={reportCompany} onChange={e=>{const cid=e.target.value;setReportCompany(cid);setReport(null);setReportDriver('');if(cid)request('/api/v1/fleet/settings?company_id='+cid).then(settings=>{setSpeedThreshold(String(settings.speeding_kmh));setAccelThreshold(String(settings.harsh_accel_ms2));setBrakeThreshold(String(settings.harsh_brake_ms2));}).catch(err=>setMessage(String(err)));}}><option value="">Choose company</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
        <label>Period<select value={reportPeriod} onChange={e=>setReportPeriod(e.target.value)}>{['daily','weekly','monthly','yearly'].map(x=><option key={x}>{x}</option>)}</select></label>
        <label>Driver<select value={reportDriver} onChange={e=>setReportDriver(e.target.value)}><option value="">All drivers</option>{drivers.filter(d=>d.company_id===Number(me.role==='super_admin'?(reportCompany||companies[0]?.id):me.company_id)).map(d=><option key={d.id} value={d.id}>{d.full_name}</option>)}</select></label>
        <button className="primary" disabled={reportLoading} onClick={()=>fetchReport()}>{reportLoading?'Loading...':'Generate report'}</button><button className="refresh" disabled={!report} onClick={exportReport}>Export CSV</button></div>
        {(me.role==='super_admin'||me.role==='company_admin')&&<div className="entry-form"><label>Speeding threshold (km/h)<input type="number" min="20" max="200" step="1" value={speedThreshold} onChange={e=>setSpeedThreshold(e.target.value)}/></label><label>Harsh acceleration threshold (m/s²)<input type="number" min="1" max="10" step="0.1" value={accelThreshold} onChange={e=>setAccelThreshold(e.target.value)}/></label><label>Harsh braking threshold (m/s²)<input type="number" min="1" max="10" step="0.1" value={brakeThreshold} onChange={e=>setBrakeThreshold(e.target.value)}/></label><button className="refresh" disabled={me.role==='super_admin'&&!reportCompany} onClick={saveSpeed}>Save company policy</button><small>Settings apply only to the selected company. Generate report to load its current policy.</small></div>}
        {report&&<><div className="stats"><article className="stat-card"><span>Drivers</span><strong>{report.driver_count}</strong></article><article className="stat-card"><span>Trips</span><strong>{report.trip_count}</strong></article><article className="stat-card"><span>Average score</span><strong>{report.average_score??'No data'}</strong></article></div>
        <div className="table-wrap"><table><thead><tr><th>Driver</th><th>Trips</th><th>Score /100</th><th>Speeding</th><th>Harsh braking</th><th>Harsh acceleration</th><th>Last GPS</th></tr></thead><tbody>{report.drivers.map((d:any)=><tr key={d.driver_id}><td>{d.driver_name}</td><td>{d.trips}</td><td>{d.score??'—'}</td><td>{d.violations.speeding}</td><td>{d.violations.harsh_braking}</td><td>{d.violations.harsh_acceleration}</td><td>{d.latest_location?<><a href={`https://www.openstreetmap.org/?mlat=${d.latest_location.latitude}&mlon=${d.latest_location.longitude}#map=15/${d.latest_location.latitude}/${d.latest_location.longitude}`} target="_blank" rel="noreferrer">View map</a><small> {new Date(d.latest_location.recorded_at).toLocaleString()}</small></>:'No GPS data'}</td></tr>)}</tbody></table></div>
        {report.drivers.map((d:any)=><article key={d.driver_id} className="panel"><h3>{d.driver_name} · Trip history</h3>{d.trip_details.length?d.trip_details.map((t:any)=><div key={t.id} className="tip"><button type="button" className="refresh" onClick={()=>viewTripRoute(t.id)}>View trip map</button> <strong>Trip #{t.id}</strong> · {new Date(t.started_at).toLocaleString()} · {t.status} · {t.violations.length} violation(s){t.violations.map((v:any,i:number)=><div key={i}>{v.type.replaceAll('_',' ')} · {v.value.toFixed(1)} · {new Date(v.recorded_at).toLocaleString()}</div>)}</div>):<p>No trips in selected period</p>}</article>)}</>}
      </section>}
      {tab==='overview' && <>
        <section className="hero"><div><span className="hero-pill">NUQATI FLEET INTELLIGENCE</span><h2>قيادة أذكى، أسطول أكثر كفاءة.</h2><p>قيادة آمنة وتذكيرات صيانة مستقلة بناءً على قراءات العداد.</p></div><div className="hero-icon"><Route size={54}/></div></section>
        <section className="stats">{[{label:label('companies','Companies','الشركات'),value:stats.companies,icon:Wrench},{label:label('vehicles','Vehicles','السيارات'),value:stats.vehicles,icon:CarFront},{label:label('drivers','Drivers','السائقون'),value:stats.drivers,icon:Users},{label:'الرحلات النشطة',value:stats.trips_active,icon:Route}].map(x=><article className="stat-card" key={x.label}><div className="stat-icon"><x.icon size={20}/></div><span>{x.label}</span><strong>{x.value}</strong></article>)}</section>
        <section className="content-grid"><article className="panel"><div className="panel-heading"><div><h3>البدء السريع</h3><p>أدخل بيانات تجريبية لتجربة لوحة الإدارة.</p></div></div><form onSubmit={addCompany} className="form-row" style={{display:me.role==='super_admin'?undefined:'none'}}><label>اسم الشركة<input value={companyName} onChange={e=>setCompanyName(e.target.value)} required /></label><button className="primary"><Plus size={16}/> إضافة شركة</button></form><div className="tip">للتجربة: أضف شركة، ثم انتقل إلى السيارات والسائقين. الدخول والصلاحيات مفعّلان للاختبار؛ لا تستخدم بيانات حقيقية قبل مراجعة الأمان.</div></article><article className="panel"><div className="panel-heading"><div><h3>مراحل الربط</h3><p>ما هو متاح الآن وما يأتي لاحقًا</p></div></div><div className="milestone done"><span>1</span><div><b>إدخال البيانات يدويًا</b><small>الشركات والسيارات والسائقون والعداد</small></div><em>أساسي</em></div><div className="milestone"><span>2</span><div><b>تطبيق GPS</b><small>الرحلات والتنبيهات والتتبع الخلفي</small></div><em>قادم</em></div><div className="milestone done"><span>3</span><div><b>تنبيهات الصيانة</b><small>جدول مستقل لكل مركبة دون ربط بنظام ورشة</small></div><em>أساسي</em></div></article></section>
      </>}
      {tab==='reports'&&selectedRoute&&<section className="panel"><h3>Trip #{selectedRoute.trip_id} · GPS route</h3><button className="refresh" onClick={()=>setSelectedRoute(null)}>Close map</button>{routeLoading&&<p>Loading...</p>}<p>Start: {selectedRoute.start?`${selectedRoute.start.latitude.toFixed(5)}, ${selectedRoute.start.longitude.toFixed(5)}`:'No GPS data'} · End / latest: {selectedRoute.end?`${selectedRoute.end.latitude.toFixed(5)}, ${selectedRoute.end.longitude.toFixed(5)}`:'No GPS data'} · {selectedRoute.points.length} points</p>{selectedRoute.points.length>0&&<><iframe title="Trip location map" width="100%" height="360" style={{border:0,borderRadius:12}} loading="lazy" src={`https://www.openstreetmap.org/export/embed.html?bbox=${Math.min(...selectedRoute.points.map((p:any)=>p.longitude))-.005}%2C${Math.min(...selectedRoute.points.map((p:any)=>p.latitude))-.005}%2C${Math.max(...selectedRoute.points.map((p:any)=>p.longitude))+.005}%2C${Math.max(...selectedRoute.points.map((p:any)=>p.latitude))+.005}&layer=mapnik&marker=${selectedRoute.end.latitude}%2C${selectedRoute.end.longitude}`}/><p><a target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/?mlat=${selectedRoute.start.latitude}&mlon=${selectedRoute.start.longitude}#map=14/${selectedRoute.start.latitude}/${selectedRoute.start.longitude}`}>Open start point</a> · <a target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/?mlat=${selectedRoute.end.latitude}&mlon=${selectedRoute.end.longitude}#map=14/${selectedRoute.end.latitude}/${selectedRoute.end.longitude}`}>Open end point</a></p><div style={{maxHeight:120,overflow:'auto'}}>{selectedRoute.points.map((pt:any,i:number)=><small key={i} style={{display:'block'}}>{i+1}. {new Date(pt.recorded_at).toLocaleString()} · {pt.latitude.toFixed(5)}, {pt.longitude.toFixed(5)}</small>)}</div></>}</section>}
      {tab==='vehicles' && <section className="panel"><div className="panel-heading"><div><h3>إدارة السيارات</h3><p>تُضاف السيارة إلى أول شركة مسجلة في النسخة التجريبية.</p></div></div><form onSubmit={addVehicle} className="entry-form" style={{display:canManage?undefined:'none'}}><label>Company<select value={selectedCompany} onChange={e=>setSelectedCompany(e.target.value)}><option value="">Select company</option>{companies.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label><label>رقم اللوحة<input value={plate} onChange={e=>setPlate(e.target.value)} required/></label><label>الماركة والموديل / Make and model<input value={model} onChange={e=>setModel(e.target.value)} maxLength={120} required placeholder="Toyota Camry"/></label><label>سنة الموديل / Model year<input type="number" min="1900" max="2100" step="1" value={vehicleYear} onChange={e=>setVehicleYear(e.target.value)} placeholder="2024"/></label><label>قراءة العداد الحالية (كم) / Odometer (km)<input type="number" min="0" step="0.1" value={vehicleOdometer} onChange={e=>setVehicleOdometer(e.target.value)} placeholder="85000"/></label><button className="primary"><Plus size={16}/> إضافة سيارة</button></form><div className="table-wrap"><table><thead><tr><th>اللوحة</th><th>المركبة</th><th>قراءة العداد</th><th>الشركة</th>{me.role==='super_admin'&&<th>Actions</th>}</tr></thead><tbody>{vehicles.map(v=><tr key={v.id}><td>{v.plate_number}</td><td>{v.make_model||'—'}{v.year?` (${v.year})`: ''}</td><td>{v.odometer_km==null?'غير مسجل':`${v.odometer_km.toLocaleString('en-US')} كم`}</td><td>{companies.find(c=>c.id===v.company_id)?.name||`#${v.company_id}`}</td>{me.role==='super_admin'&&<td><button className="refresh" onClick={()=>adminEdit('vehicles',v.id,'plate_number',v.plate_number)}>Edit plate</button><button className="refresh" onClick={()=>adminEdit('vehicles',v.id,'make_model',v.make_model)}>Edit model</button><button className="refresh" onClick={()=>adminDelete('vehicles',v.id)}>Delete</button></td>}</tr>)}</tbody></table>{!vehicles.length&&<div className="empty">لا توجد سيارات حتى الآن.</div>}</div></section>}
      {tab==='drivers' && <section className="panel"><h3>Add Driver + Enable Login | إضافة سائق ومنحه صلاحية الدخول</h3><p>One action creates the driver, phone login and vehicle assignment. No driver email is needed. Use a private temporary password (12+ characters); the plate is visible publicly and must not be used as a permanent password.</p><form onSubmit={addDriver} className="entry-form">{me.role==='super_admin'&&<label>Company<select required value={selectedCompany} onChange={e=>{setSelectedCompany(e.target.value);setDriverVehicle('')}}><option value="">Choose company</option>{companies.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label>}<label>Full name<input required value={driverName} onChange={e=>setDriverName(e.target.value)}/></label><label>Mobile number (+966...)<input required type="tel" value={driverPhone} onChange={e=>setDriverPhone(e.target.value)} placeholder="+9665XXXXXXXX"/></label><label>ID / Iqama number<input required value={driverIdNumber} onChange={e=>setDriverIdNumber(e.target.value)}/></label><label>Site / Branch<input required value={driverSite} onChange={e=>setDriverSite(e.target.value)}/></label><label>Assign available vehicle<select required value={driverVehicle} onChange={e=>setDriverVehicle(e.target.value)}><option value="">Choose available vehicle</option>{vehicles.filter(v=>v.company_id===Number(me.role==='super_admin'?(selectedCompany||companies[0]?.id):me.company_id)&&!drivers.some(d=>driverLinks.some(l=>l.driver_id===d.id&&l.vehicle_id===v.id))).map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>Private temporary password (12+ characters)<input type="password" required minLength={12} value={driverInitialPassword} onChange={e=>setDriverInitialPassword(e.target.value)}/></label><button className="primary">Create Driver & Enable Login</button></form><h3>Registered drivers</h3><button type="button" className="refresh" onClick={loadDriverExtras}>Refresh app login acknowledgments</button><div className="table-wrap"><table><thead><tr><th>Name</th><th>Phone</th><th>Company</th><th>Status</th><th>Vehicle</th><th>App login acknowledgment (UTC)</th>{me.role==='super_admin'&&<th>Actions</th>}</tr></thead><tbody>{drivers.map(d=><tr key={d.id}><td>{d.full_name}</td><td>{d.phone}</td><td>{companies.find(c=>c.id===d.company_id)?.name}</td><td>{d.status}</td><td>{vehicles.find(v=>v.assigned_driver_id===d.id)?.plate_number||'Not assigned'}</td><td>{driverLogins[String(d.id)]?new Date(driverLogins[String(d.id)]).toLocaleString():'Never acknowledged'}</td>{me.role==='super_admin'&&<td><button type="button" className="refresh" onClick={()=>beginDriverEdit(d)}>Edit all fields</button><button type="button" className="refresh" onClick={()=>adminDelete('drivers',d.id)}>Delete</button></td>}</tr>)}</tbody></table></div>{editingDriver!==null&&<div className="panel" style={{marginTop:20}}><h3>Edit Driver #{editingDriver} (inline)</h3><div className="entry-form"><label>Full name<input value={driverEditForm.full_name} onChange={e=>setDriverEditForm({...driverEditForm,full_name:e.target.value})}/></label><label>Mobile<input value={driverEditForm.phone} onChange={e=>setDriverEditForm({...driverEditForm,phone:e.target.value})}/></label><label>ID / Iqama<input value={driverEditForm.id_number} onChange={e=>setDriverEditForm({...driverEditForm,id_number:e.target.value})}/></label><label>Site / Branch<input value={driverEditForm.site_name} onChange={e=>setDriverEditForm({...driverEditForm,site_name:e.target.value})}/></label><label>Status<select value={driverEditForm.status} onChange={e=>setDriverEditForm({...driverEditForm,status:e.target.value})}><option value="active">Active</option><option value="inactive">Inactive</option><option value="archived">Archived</option></select></label><label>Assigned vehicle<select value={driverEditForm.vehicle_id} onChange={e=>setDriverEditForm({...driverEditForm,vehicle_id:e.target.value})}><option value="">Unassigned</option>{vehicles.filter(v=>v.company_id===drivers.find(d=>d.id===editingDriver)?.company_id&&(!v.assigned_driver_id||v.assigned_driver_id===editingDriver)).map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><button type="button" className="primary" onClick={saveDriverEdit}>Save changes</button><button type="button" className="refresh" onClick={()=>setEditingDriver(null)}>Cancel</button></div><p>Company reassignment is intentionally blocked to protect cross-company records. Password reset remains a separate secure operation.</p></div>}</section>}
      {tab==='odometer' && <section className="panel"><div className="panel-heading"><div><h3>تسجيل قراءة العداد</h3><p>قراءة GPS تقديرية وليست بديلًا عن عداد السيارة الفعلي.</p></div></div><form onSubmit={addReading} className="entry-form" style={{display:canManage?undefined:'none'}}><label>السيارة<select value={readingVehicle} onChange={e=>setReadingVehicle(e.target.value)} required><option value="">اختر السيارة</option>{vehicles.map(v=><option value={v.id} key={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>القراءة (كم)<input type="number" min="0" step="0.1" value={reading} onChange={e=>setReading(e.target.value)} required/></label><label>المصدر<select value={source} onChange={e=>setSource(e.target.value)}><option value="MANUAL">إدخال يدوي</option><option value="GPS">تقدير GPS</option></select></label><button className="primary"><Plus size={16}/> حفظ القراءة</button></form><div style={{marginTop:22,display:'grid',gap:14}}><h3>{lang==='ar'?'سجل قراءات العداد لجميع السيارات':'Odometer history for all vehicles'}</h3><div className="entry-form"><label>{lang==='ar'?'عرض سجلات السيارة':'Filter records by vehicle'}<select value={odometerHistoryVehicle} onChange={e=>setOdometerHistoryVehicle(e.target.value)}><option value="all">{lang==='ar'?'جميع السيارات':'All vehicles'}</option>{vehicles.map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model} ({companies.find(c=>c.id===v.company_id)?.name||'#'+v.company_id})</option>)}</select></label><button type="button" className="refresh" onClick={loadOdometerHistory} disabled={odometerHistoryLoading}><RefreshCw size={15}/>{odometerHistoryLoading?'Loading...':(lang==='ar'?'تحديث السجل':'Refresh records')}</button></div><h4>{lang==='ar'?'العداد الحالي لكل سيارة':'Current odometer for every vehicle'}</h4><div className="table-wrap"><table><thead><tr><th>{lang==='ar'?'السيارة':'Vehicle'}</th><th>{lang==='ar'?'الشركة':'Company'}</th><th>{lang==='ar'?'العداد الحالي (كم)':'Current odometer (km)'}</th></tr></thead><tbody>{vehicles.map(v=><tr key={v.id}><td>{v.plate_number} — {v.make_model}</td><td>{companies.find(c=>c.id===v.company_id)?.name||'#'+v.company_id}</td><td>{v.odometer_km==null?'—':v.odometer_km.toLocaleString('en-US')}</td></tr>)}</tbody></table>{vehicles.length===0&&<div className="empty">No vehicles</div>}</div><h4>{lang==='ar'?'جميع القراءات المحفوظة':'Saved reading records'}</h4><div className="table-wrap"><table><thead><tr><th>{lang==='ar'?'التاريخ':'Date'}</th><th>{lang==='ar'?'السيارة':'Vehicle'}</th><th>{lang==='ar'?'الشركة':'Company'}</th><th>{lang==='ar'?'القراءة (كم)':'Reading (km)'}</th><th>{lang==='ar'?'المصدر':'Source'}</th><th>{lang==='ar'?'ملاحظات':'Notes'}</th></tr></thead><tbody>{odometerRecords.filter(r=>odometerHistoryVehicle==='all'||String(r.vehicle_id)===odometerHistoryVehicle).map(r=>{const v=vehicles.find(v=>v.id===r.vehicle_id);return <tr key={r.id}><td>{new Date(r.created_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td><td>{v?`${v.plate_number} — ${v.make_model}`:`#${r.vehicle_id}`}</td><td>{companies.find(c=>c.id===r.company_id)?.name||'#'+r.company_id}</td><td>{r.reading_km.toLocaleString('en-US')}</td><td>{r.source}</td><td>{r.note||'—'}</td></tr>;})}</tbody></table>{odometerRecords.filter(r=>odometerHistoryVehicle==='all'||String(r.vehicle_id)===odometerHistoryVehicle).length===0&&<div className="empty">{lang==='ar'?'لا توجد قراءات محفوظة':'No saved readings'}</div>}</div><p style={{opacity:.75,fontSize:12}}>{lang==='ar'?'يعرض السجل آخر 500 قراءة كحد أقصى وفق واجهة الخادم الحالية.':'The current server API returns up to 500 most recent readings.'}</p></div><div className="tip">تُحفظ القراءات بسجل مستقل مع المصدر والتاريخ. لا تدعم النسخة الحالية تصحيح القراءات السابقة أو حذفها من الواجهة.</div></section>}
      {tab==='maintenance' && <section className="panel"><div className="panel-heading"><div><h3>تذكيرات الصيانة حسب العداد</h3><p>لا حاجة لربط نظام ورشة أو تصوير اللوحة. اختر السيارة وسجل آخر صيانة والفاصل بالكيلومتر. التنبيهات تقديرية وتحتاج مراجعة العداد الفعلي.</p></div></div><form onSubmit={saveSchedule} className="entry-form" style={{display:canManage?undefined:'none'}}><label>السيارة<select value={readingVehicle} onChange={e=>setReadingVehicle(e.target.value)} required><option value="">اختر السيارة</option>{vehicles.map(v=><option value={v.id} key={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>الخدمة<select value={serviceType} onChange={e=>{setServiceType(e.target.value);setInterval(e.target.value==='ENGINE_OIL'?'5000':e.target.value==='SPARK_PLUGS'?'60000':'80000')}}><option value="ENGINE_OIL">زيت المحرك</option><option value="SPARK_PLUGS">البواجي</option><option value="TRANSMISSION_OIL">زيت القير</option></select></label><label>الفاصل (كم)<input type="number" min="1" value={interval} onChange={e=>setInterval(e.target.value)} required/></label><label>عداد آخر صيانة (كم)<input type="number" min="0" value={lastService} onChange={e=>setLastService(e.target.value)} required/></label><label>التنبيه قبل الموعد (كم)<input type="number" min="0" value={warningBefore} onChange={e=>setWarningBefore(e.target.value)} required/></label><button className="primary"><Plus size={16}/> حفظ / تحديث التذكير</button></form><div className="table-wrap"><table><thead><tr><th>السيارة</th><th>الخدمة</th><th>الموعد القادم</th><th>المتبقي</th><th>الحالة</th>{me.role==='super_admin'&&<th>Actions</th>}</tr></thead><tbody>{schedules.map(m=><tr key={m.id}><td>{vehicles.find(v=>v.id===m.vehicle_id)?.plate_number||m.vehicle_id}</td><td>{({ENGINE_OIL:'زيت المحرك',SPARK_PLUGS:'البواجي',TRANSMISSION_OIL:'زيت القير'} as Record<string,string>)[m.service_type]||m.service_type}</td><td>{m.next_due_km.toLocaleString('en-US')} كم</td><td>{m.remaining_km==null?'غير معروف':`${Math.round(m.remaining_km).toLocaleString('en-US')} كم`}</td><td><span className="status">{({OK:'سليم',DUE_SOON:'قريب',OVERDUE:'مستحق',UNKNOWN:'أدخل العداد'} as Record<string,string>)[m.status]||m.status}</span></td>{me.role==='super_admin'&&<td><button className="refresh" onClick={()=>adminDelete('maintenance-schedules',m.id)}>Delete</button></td>}</tr>)}</tbody></table>{!schedules.length&&<div className="empty">أضف جدول صيانة لبدء التذكيرات.</div>}</div><div className="tip">هذه تنبيهات داخل لوحة الاختبار، وليست إشعارات هاتفية آلية بعد. فترات الخدمة قابلة للتعديل حسب توصيات الشركة المصنعة.</div></section>}
      <footer>Nuqati by Al-Riadah Workshop | نقاطي من ورشة حلول الريادة © {new Date().getFullYear()} — حلول الريادة لصيانة السيارات <span>الأزرق الداكن · الأخضر الليموني</span></footer>
    </main>
  </div>;
}
