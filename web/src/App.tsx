import VehicleHandover from './VehicleHandover';
import VehicleEditPage, { type VehicleUpdate } from './VehicleEditPage';
import CompanyEditPage, { type CompanyUpdate } from './CompanyEditPage';
import DriverEditPage, { type DriverUpdate } from './DriverEditPage';
import UserEditPage, { type UserUpdate } from './UserEditPage';
import LifecyclePrivacyAudit from './LifecyclePrivacyAudit';
import {FlexibleRagSettings,FlexibleRagReports} from './FlexibleRag';
import GeofenceReport from './GeofenceReport';
import ReportSubscriptions from './ReportSubscriptions';
import ReportSuite, {type ReportId} from './ReportSuite';
import HardwareDevices from './HardwareDevices';
import SmartOilEstimator from './SmartOilEstimator';
import FleetPositionMap from './FleetPositionMap';
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import TripLiveMap from './TripLiveMap';
import GeofenceLocationsMap from './GeofenceLocationsMap';
import { Activity, CarFront, Users, Route, Gauge, Wrench, Plus, Search, RefreshCw, ShieldCheck, LogOut, Building2, UserCog, Trash2, Shield, MapPin, Clock3, ArrowUpDown, X, ChevronDown, Globe2 } from 'lucide-react';

const API = import.meta.env.VITE_API_BASE_URL ?? '';
type Vehicle = {id:number; company_id:number; plate_number:string; make_model:string; year:number|null; door_number:string|null; odometer_km:number|null; assigned_driver_id?:number|null};
type Driver = {id:number; company_id:number; full_name:string; phone:string; status:string};
type Company = {id:number; name:string};
type Me = {id:number;email:string;full_name:string;role:string;company_id:number|null};
type LiveMotionFilter = 'all' | 'moving' | 'stationary';
type LivePosition = {vehicle_id:number;plate:string;driver_name:string|null;driver_id:number|null;recorded_at:string|null;speed_kmh:number|null;age_seconds:number|null;state:string;trip_active:boolean;geofences:{id:string;name:string;status:string;speed_limit_kmh?:number|null}[];latitude:number|null;longitude:number|null;accuracy_m:number|null};

type OverviewSeries={key:string;label:string;color:string};
function OverviewBars({title,rows,series}:{title:string;rows:any[];series:OverviewSeries[]}){
 const max=Math.max(1,...rows.flatMap(r=>series.map(s=>Math.max(0,Number(r[s.key]||0)))));
 return <article className="nuqati-chart-card"><h3>{title}</h3><div className="nuqati-chart-legend">{series.map(s=><span key={s.key}><i style={{background:s.color}}/>{s.label}</span>)}</div><div className="nuqati-chart-bars">{rows.map((r,i)=><div key={r.date||i} className="nuqati-bar-column" title={`${r.date}: ${series.map(s=>`${s.label} ${Number(r[s.key]||0).toFixed(1)}`).join(' · ')}`}><div className="nuqati-bar-track">{series.map(s=><div key={s.key} style={{height:`${100*Math.max(0,Number(r[s.key]||0))/max}%`,background:s.color}}/>)}</div><small>{String(r.date||'').slice(5)}</small></div>)}</div></article>;
}

function OverviewMotionDonut({moving,stationary,unknown,asOf,lang,error}:{moving:number;stationary:number;unknown:number;asOf?:string;lang:'en'|'ar';error?:string}){
  const total=Math.max(0,moving)+Math.max(0,stationary)+Math.max(0,unknown);
  const movingPercent=total>0?100*Math.max(0,moving)/total:0;
  const stationaryPercent=total>0?100*Math.max(0,stationary)/total:0;
  const unknownPercent=total>0?100*Math.max(0,unknown)/total:0;
  const updatedAt=asOf?new Date(asOf).toLocaleTimeString(lang==='ar'?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh',hour:'2-digit',minute:'2-digit',second:'2-digit'}):null;
  return <article className="nuqati-chart-card nuqati-motion-chart">
    <h3>{lang==='en'?'Live vehicle motion — Moving vs Stationary':'حركة المركبات المباشرة — متحركة مقابل متوقفة'}</h3>
    {error?<p role="alert" className="notice">{lang==='en'?'Live motion unavailable: check connectivity and refresh.':'حالة الحركة المباشرة غير متاحة: تحقق من الاتصال وأعد التحديث.'}</p>:<>
      <div className="nuqati-motion-chart-body">
        <div className="nuqati-motion-donut" role="img" aria-label={lang==='en'?`Moving ${moving}, stationary ${stationary}, unknown ${unknown}`:`متحركة ${moving}، متوقفة ${stationary}، غير معروفة ${unknown}`}
             style={{background:total>0?`conic-gradient(#a5d84c 0 ${movingPercent}%, #f0ac4d ${movingPercent}% ${movingPercent+stationaryPercent}%, #667b89 ${movingPercent+stationaryPercent}% 100%)`:'conic-gradient(#364d5b 0 100%)'}}>
          <div className="nuqati-motion-donut-center"><strong>{total}</strong><small>{lang==='en'?'fleet vehicles':'مركبات الأسطول'}</small></div>
        </div>
        <div className="nuqati-motion-breakdown">
          <div><span><i className="nuqati-motion-dot moving"/>{lang==='en'?'Moving':'متحركة'}</span><strong>{moving}</strong><small>{Math.round(movingPercent)}%</small></div>
          <div><span><i className="nuqati-motion-dot stationary"/>{lang==='en'?'Stationary':'متوقفة'}</span><strong>{stationary}</strong><small>{Math.round(stationaryPercent)}%</small></div>
          <div><span><i className="nuqati-motion-dot unknown"/>{lang==='en'?'Unknown / offline':'غير معروفة / غير متصلة'}</span><strong>{unknown}</strong><small>{Math.round(unknownPercent)}%</small></div>
        </div>
      </div>
      <p className="nuqati-motion-caption">{lang==='en'?`Live GPS (last 5 min): moving ≥5 km/h, stationary ≤2 km/h. Intermediate, stale, private or missing GPS = unknown. Auto-refreshes every 30s.`:`GPS مباشر (آخر 5 دقائق): متحركة بسرعة 5 كم/س فأكثر، متوقفة بسرعة 2 كم/س فأقل. القراءة غير المؤكدة أو القديمة أو الخاصة أو المفقودة = غير معروفة. تحديث تلقائي كل 30 ثانية.`} {updatedAt?(lang==='en'?`Updated ${updatedAt} (Saudi time).`:`آخر تحديث ${updatedAt} (بتوقيت السعودية).`):''}</p>
    </>}
  </article>;
}

function PublicLiveShare({shareToken}:{shareToken:string}){
 const [data,setData]=useState<any>(null);const [error,setError]=useState('');
 useEffect(()=>{let active=true;async function update(){try{const r=await fetch(`${API}/api/v1/public/live-share/${encodeURIComponent(shareToken)}`,{cache:'no-store'});const json=await r.json();if(!r.ok)throw Error(json.detail||'Link expired');if(active){setData(json);setError('');}}catch(e){if(active){setError(String(e));setData(null);}}}
 void update();const timer=window.setInterval(()=>void update(),30000);return ()=>{active=false;window.clearInterval(timer)};
 },[shareToken]);
 return <main className="nuqati-public-live"><h2>Nuqati · Shared vehicle location</h2><p>Limited live-sharing link — refreshes every 30 seconds.</p>{error?<p role="alert">{error}</p>:data?.status==='available'?<div className="panel"><h3>{data.plate}</h3><p>Last GPS: {new Date(data.recorded_at).toLocaleString()} · Speed: {data.speed_kmh} km/h</p><iframe title="Shared vehicle location" src={`https://www.openstreetmap.org/export/embed.html?bbox=${data.longitude-0.01}%2C${data.latitude-0.01}%2C${data.longitude+0.01}%2C${data.latitude+0.01}&layer=mapnik&marker=${data.latitude}%2C${data.longitude}`} style={{width:'100%',height:400,border:0}}/></div>:<div className="panel">{data?'No recent GPS location available.':'Loading location…'}</div>}<small>Only recent GPS locations are shared. Expiry: {data?.expires_at?new Date(data.expires_at).toLocaleString():'—'}</small></main>;
}


type DiagnosticRow={event_id:string;occurred_at:string;received_at:string;severity:string;category:string;code:string;detail:string;driver_name:string|null;plate_number:string|null};
function MobileDiagnostics({token,lang}:{token:string;lang:'en'|'ar'}){
 const [plate,setPlate]=useState('');const [driver,setDriver]=useState('');
 const [severity,setSeverity]=useState('');const [category,setCategory]=useState('');
 const [rows,setRows]=useState<DiagnosticRow[]>([]);const [error,setError]=useState('');const [loading,setLoading]=useState(false);
 async function refresh(){setLoading(true);try{
  const q=new URLSearchParams({plate,driver,severity,category,limit:'300'});
  const r=await fetch(`${API}/api/v1/maintenance/mobile-diagnostics?${q}`,{headers:{Authorization:`Bearer ${token}`}});
  if(!r.ok)throw Error(`HTTP ${r.status}`);
  setRows(await r.json());setError('');
 }catch(e){setError(String(e));}finally{setLoading(false);}}
 useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),30000);return()=>window.clearInterval(timer);},[token,plate,driver,severity,category]);
 return <section className="panel"><h3>{lang==='en'?'Mobile Diagnostics & GPS Trip Detection':'تشخيص التطبيق واكتشاف رحلات GPS'}</h3>
 <p>{lang==='en'?'Automatically refreshes every 30 seconds. Diagnostic events upload when the device has internet access.':'تحديث تلقائي كل 30 ثانية. تُرسل السجلات عند توفر الإنترنت في الهاتف.'}</p>
 <div className="entry-form"><label>{lang==='en'?'Plate':'اللوحة'}<input value={plate} onChange={e=>setPlate(e.target.value)}/></label>
 <label>{lang==='en'?'Driver':'السائق'}<input value={driver} onChange={e=>setDriver(e.target.value)}/></label>
 <label>{lang==='en'?'Severity':'المستوى'}<select value={severity} onChange={e=>setSeverity(e.target.value)}>{['','INFO','WARNING','ERROR','CRASH'].map(x=><option key={x} value={x}>{x||'All'}</option>)}</select></label>
 <label>{lang==='en'?'Category':'الفئة'}<select value={category} onChange={e=>setCategory(e.target.value)}>{['','GPS','TRIP','APP','SYNC','PERMISSION','OTHER'].map(x=><option key={x} value={x}>{x||'All'}</option>)}</select></label>
 <button type="button" className="refresh" onClick={()=>void refresh()}>{loading?'Loading…':'Refresh'}</button></div>
 {error&&<p role="alert">{error}</p>}
 <div className="table-wrap"><table><thead><tr>{['Time','Plate','Driver','Severity','Category','Code','Details'].map(h=><th key={h}>{h}</th>)}</tr></thead>
 <tbody>{rows.map(r=><tr key={r.event_id}><td>{new Date(r.occurred_at).toLocaleString()}</td><td>{r.plate_number||'—'}</td><td>{r.driver_name||'—'}</td><td><strong>{r.severity}</strong></td><td>{r.category}</td><td>{r.code}</td><td>{r.detail||'—'}</td></tr>)}</tbody></table></div>
 {!rows.length&&!error&&<p>{lang==='en'?'No diagnostic events found.':'لا توجد سجلات مطابقة.'}</p>}
 </section>;
}

export default function App() {
  const publicShareToken=new URLSearchParams(window.location.search).get('live_share')||'';
  const [lang,setLang]=useState<'en'|'ar'>(()=>localStorage.getItem('nuqati_lang')==='en'?'en':'ar');
  const [branding,setBranding]=useState<{logo_data:string;labels:Record<string,Record<string,string>>}>({logo_data:'',labels:{}});
  const [defaults,setDefaults]=useState<Record<string,Record<string,string>>>({});
  const [inviteToken]=useState(()=>new URLSearchParams(window.location.search).get('invite')||'');
  const [invitePassword,setInvitePassword]=useState('');
  const [inviteStatus,setInviteStatus]=useState('');
  const [invite,setInvite]=useState({email:'',full_name:'',role:'company_admin',company_id:''});
  const label=(key:string,en:string,ar:string)=>(lang==='en'?((branding.labels[key]?.en && !/[\u0600-\u06FF]/.test(branding.labels[key].en))?branding.labels[key].en:en):(branding.labels[key]?.ar||defaults[key]?.ar||ar));
  const logo=branding.logo_data||'/solutions-logo.png';
  useEffect(()=>{fetch(`${API}/api/v1/public/branding`).then(r=>r.json()).then(setBranding).catch(()=>{});fetch(`${API}/api/v1/public/label-defaults`).then(r=>r.json()).then(setDefaults).catch(()=>{});},[]);
  useEffect(()=>{document.documentElement.lang=lang;document.documentElement.dir=lang==='ar'?'rtl':'ltr';},[lang]);
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
  const [resetToken]=useState(()=>new URLSearchParams(window.location.search).get('reset')||'');
  const [verifyEmailToken]=useState(()=>new URLSearchParams(window.location.search).get('confirm_email')||'');
  const [recoveryEmail,setRecoveryEmail]=useState('');
  const [recoveryPassword,setRecoveryPassword]=useState('');
  const [recoveryConfirm,setRecoveryConfirm]=useState('');
  const [recoveryStatus,setRecoveryStatus]=useState('');
  const [showRecovery,setShowRecovery]=useState(false);
  const [accountPassword,setAccountPassword]=useState({current:'',next:'',confirm:''});
  const [accountNewEmail,setAccountNewEmail]=useState('');
  const [accountEmailPassword,setAccountEmailPassword]=useState('');
  const [accountStatus,setAccountStatus]=useState('');
  async function recoveryPost(path:string,body:unknown){
    const res=await fetch(`${API}${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await res.json().catch(()=>({}));
    if(!res.ok)throw new Error(data.detail||'Request failed');
    return data;
  }
  async function requestRecovery(e:React.FormEvent){e.preventDefault();setRecoveryStatus('');try{
    const result=await recoveryPost('/api/v1/auth/password-reset/request',{email:recoveryEmail});
    setRecoveryStatus(result.message||'If an account exists, we sent a reset link.');
  }catch(e){setRecoveryStatus(String(e));}}
  async function completeRecovery(e:React.FormEvent){e.preventDefault();
    if(recoveryPassword!==recoveryConfirm){setRecoveryStatus('Passwords do not match');return;}
    try{await recoveryPost('/api/v1/auth/password-reset/confirm',{token:resetToken,new_password:recoveryPassword});
      setRecoveryStatus('Password updated. Return to login.');setRecoveryPassword('');setRecoveryConfirm('');
    }catch(e){setRecoveryStatus(String(e));}}
  async function completeEmailVerification(){setRecoveryStatus('');try{
    await recoveryPost('/api/v1/auth/email-change/confirm',{token:verifyEmailToken});
    sessionStorage.removeItem('nuqati_token');setToken('');setMe(null);
    setRecoveryStatus('Email verified. Sign in again using the new email address.');
  }catch(e){setRecoveryStatus(String(e));}}
  async function updateOwnPassword(e:React.FormEvent){e.preventDefault();setAccountStatus('');
    if(accountPassword.next!==accountPassword.confirm){setAccountStatus('Passwords do not match');return;}
    try{await request('/api/v1/account/password',{method:'POST',body:JSON.stringify({current_password:accountPassword.current,new_password:accountPassword.next})});
      setAccountPassword({current:'',next:'',confirm:''});signOut();setLoginError(lang==='en'?'Password changed. Sign in with your new password.':'تم تغيير كلمة المرور. سجّل الدخول مجددًا.');
    }catch(e){setAccountStatus(String(e));}}
  async function updateOwnEmail(e:React.FormEvent){e.preventDefault();setAccountStatus('');
    try{await request('/api/v1/account/email/request',{method:'POST',body:JSON.stringify({current_password:accountEmailPassword,new_email:accountNewEmail})});
      setAccountEmailPassword('');setAccountStatus(lang==='en'?'Confirmation link sent to the new email address.':'تم إرسال رابط التأكيد إلى البريد الجديد.');
    }catch(e){setAccountStatus(String(e));}}

  const [newUser,setNewUser]=useState({email:'',full_name:'',password:'',role:'company_admin',company_id:''});
  const [users,setUsers]=useState<(Me&{is_active:boolean})[]>([]);
  const [selectedInviteUserId,setSelectedInviteUserId]=useState('');
  const [accountForm,setAccountForm]=useState({full_name:'',email:'',role:'company_admin',password:''});
  const [editingUserId,setEditingUserId]=useState<number|null>(null);

  const [activeCompany,setActiveCompany]=useState('');
  const activeCompanyId=me?.role==='super_admin'?activeCompany:String(me?.company_id||'');
  function chooseActiveCompany(companyId:string){
    setActiveCompany(companyId);
    if(me?.role==='super_admin'){try{localStorage.setItem(`nuqati.company-context.${me.id}`,companyId);}catch{/* Storage unavailable */}}
  }
  useEffect(()=>{
    if(!me){setActiveCompany('');return;}
    if(me.role==='super_admin'){
      try{setActiveCompany(localStorage.getItem(`nuqati.company-context.${me.id}`)||'');}
      catch{setActiveCompany('');}
    }else setActiveCompany(String(me.company_id||''));
  },[me?.id,me?.role,me?.company_id]);
  async function signIn(e:React.FormEvent){e.preventDefault();try{
    const r=await fetch(`${API}/api/v1/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    const data=await r.json();if(!r.ok)throw new Error(data.detail||'Login failed');
    sessionStorage.setItem('nuqati_token',data.access_token);setToken(data.access_token);setMe(data.user);setPassword('');setLoginError('');
  }catch(err){setLoginError(String(err));}}
  function signOut(){sessionStorage.removeItem('nuqati_token');setToken('');setMe(null);setCompanies([]);setDrivers([]);setVehicles([]);}

  const [tab,setTab] = useState<'overview'|'vehicles'|'drivers'|'odometer'|'maintenance'|'mobile-diagnostics'|'companies'|'users'|'reports'|'settings'|'privacy-audit'|'safety'|'configuration'|'assistance'|'trips'|'live-tracking'|'historical-tracking'|'my-account'|'handover'>('overview');
  const [companies,setCompanies] = useState<Company[]>([]);
  useEffect(()=>{
    if(me?.role==='super_admin'&&activeCompany&&companies.length&&!companies.some(c=>String(c.id)===activeCompany)){
      chooseActiveCompany('');
    }
  },[activeCompany,companies,me?.id,me?.role]);
  const [vehicles,setVehicles] = useState<Vehicle[]>([]);
  // Vehicle single-page editor state; retained alongside Company and Driver editors.
  const [editingVehicleId,setEditingVehicleId] = useState<number|null>(null);
  const [vehicleSaving,setVehicleSaving] = useState(false);
  const [drivers,setDrivers] = useState<Driver[]>([]);
  const [editingDriver,setEditingDriver]=useState<number|null>(null);
  const [driverEditorLoading,setDriverEditorLoading]=useState(false);
  const [driverDetails,setDriverDetails]=useState<Record<string,{id_number:string;site_name:string;vehicle_id:number|null}>>({});
  const [driverLogins,setDriverLogins]=useState<Record<string,string>>({});
  async function loadDriverExtras(){
    try{const [details,acks]=await Promise.all([request('/api/v1/drivers/details'),request('/api/v1/drivers/login-acknowledgments')]);setDriverDetails(details.drivers||{});setDriverLogins(acks.last_logins||{});}catch(err){setMessage(String(err));}
  }
  async function beginDriverEdit(d:Driver){
    setTab('drivers');setDriverEditorLoading(true);setMessage('');setEditingDriver(d.id);
    try{
      // Refresh identity, site and assignment from backend rather than relying on stale list metadata.
      const [details,acks]=await Promise.all([request('/api/v1/drivers/details'),request('/api/v1/drivers/login-acknowledgments')]);
      setDriverDetails(details.drivers||{});setDriverLogins(acks.last_logins||{});
      if(!details.drivers?.[String(d.id)])throw Error('Driver details not found');
    }catch(err){setEditingDriver(null);setMessage(String(err));}finally{setDriverEditorLoading(false);}
  }
  async function saveDriverEdit(changes:DriverUpdate){
    if(editingDriver===null)return;
    await request(`/api/v1/drivers/${editingDriver}`,{method:'PATCH',body:JSON.stringify(changes)});
    setEditingDriver(null);await load();await loadDriverExtras();
    setMessage(lang==='en'?'All driver changes saved successfully.':'تم حفظ جميع تعديلات السائق بنجاح.');
  }

  const [listSearch,setListSearch]=useState('');
  const [listCompany,setListCompany]=useState('all');
  const [listStatus,setListStatus]=useState('all');
  // Selection-first UI: no table rows on initial navigation, without changing API permissions.
  const [companyViewId,setCompanyViewId]=useState('');
  const [usersViewCompany,setUsersViewCompany]=useState('');
  const [vehicleViewCompany,setVehicleViewCompany]=useState('');
  const [vehicleViewSearch,setVehicleViewSearch]=useState('');
  const [vehicleViewStatus,setVehicleViewStatus]=useState('all');
  const [driverViewCompany,setDriverViewCompany]=useState('');
  const [driverViewSearch,setDriverViewSearch]=useState('');
  const [driverViewStatus,setDriverViewStatus]=useState('all');
  const [configCompany,setConfigCompany]=useState('');
  const [configSection,setConfigSection]=useState('');
  useLayoutEffect(()=>{
    if(tab==='companies'){setExpandedCompany(null);}
    if(tab==='users'){setSelectedInviteUserId('');}
    if(tab==='vehicles'){setVehicleViewSearch('');setVehicleViewStatus('all');}
    if(tab==='drivers'){setDriverViewSearch('');setDriverViewStatus('all');}
    if(tab==='assistance'){setAssistSearch('');setAssistStatus('all');setAssistFrom('');setAssistTo('');}
    if(tab==='configuration'){setConfigSection('');setScorePolicy(null);setPolicyAcks([]);setEventConditions([]);}
  },[tab,me?.id]);
  const [inlineEdit,setInlineEdit]=useState<{kind:'users'|'companies'|'drivers'|'vehicles';id:number;field:string;value:string}|null>(null);
  const [overviewDays,setOverviewDays]=useState(7);
  const todayOverview=()=>new Date().toISOString().slice(0,10);
  const [overviewFrom,setOverviewFrom]=useState(()=>{const d=new Date();d.setUTCDate(d.getUTCDate()-6);return d.toISOString().slice(0,10)});
  const [overviewTo,setOverviewTo]=useState(todayOverview);
  const [overviewFromTime,setOverviewFromTime]=useState('00:00');
  const [overviewToTime,setOverviewToTime]=useState('23:59');
  const [overviewApplied,setOverviewApplied]=useState({from:overviewFrom,to:overviewTo,fromTime:'00:00',toTime:'23:59'});
  const [overviewCustomize,setOverviewCustomize]=useState(false);
  const overviewWidgetOptions=[
    {id:'kpis',en:'Fleet KPI cards',ar:'مؤشرات الأسطول'},
    {id:'distance',en:'Daily distance',ar:'المسافة اليومية'},
    {id:'activity',en:'Trips & driver activity',ar:'الرحلات ونشاط السائقين'},
    {id:'violations',en:'Driving violations',ar:'مخالفات القيادة'},
    {id:'utilization',en:'Vehicle utilization',ar:'استخدام المركبات'},
    {id:'vehicleTrips',en:'Vehicles with/without trips',ar:'المركبات برحلات أو بدون رحلات'},
    {id:'motion',en:'Moving vs stationary vehicles',ar:'المركبات المتحركة والمتوقفة'},
    {id:'insights',en:'Fleet insights',ar:'ملخص الأسطول'},
  ];
  const [overviewVisible,setOverviewVisible]=useState<Record<string,boolean>>({});
  useEffect(()=>{if(!me)return;try{setOverviewVisible(JSON.parse(localStorage.getItem(`nuqati_overview_widgets_${me.id}`)||'{}'));}catch{setOverviewVisible({});}},[me?.id]);
  function setOverviewWidget(id:string,enabled:boolean){setOverviewVisible(old=>{const next={...old,[id]:enabled};if(me)localStorage.setItem(`nuqati_overview_widgets_${me.id}`,JSON.stringify(next));return next;});}
  const showOverviewWidget=(id:string)=>overviewVisible[id]!==false;
  function applyOverviewRange(){setOverviewDays(0);const a=`${overviewFrom}T${overviewFromTime}:00Z`,b=`${overviewTo}T${overviewToTime}:59Z`;if(!overviewFrom||!overviewTo||new Date(a)>new Date(b)){setOverviewError(lang==='en'?'Select a valid start and end date/time.':'اختر تاريخ ووقت بداية ونهاية صحيحين.');return;}if((new Date(b).getTime()-new Date(a).getTime())>366*86400000){setOverviewError(lang==='en'?'Maximum range is 366 days.':'أقصى فترة 366 يوماً.');return;}setOverviewApplied({from:overviewFrom,to:overviewTo,fromTime:overviewFromTime,toTime:overviewToTime});}
  function overviewPreset(days:number){const end=new Date(),start=new Date();start.setUTCDate(end.getUTCDate()-(days-1));const from=start.toISOString().slice(0,10),to=end.toISOString().slice(0,10);setOverviewDays(days);setOverviewFrom(from);setOverviewTo(to);setOverviewFromTime('00:00');setOverviewToTime('23:59');setOverviewApplied({from,to,fromTime:'00:00',toTime:'23:59'});}

  const [overviewCompany,setOverviewCompany]=useState('');
  const [overviewData,setOverviewData]=useState<any>(null);
  const [overviewError,setOverviewError]=useState('');
  const [overviewMotionError,setOverviewMotionError]=useState('');
  const overviewReportVersion=useRef(0);
  type AssistTicket={id:number;company_id:number;driver_name:string;plate_number:string|null;category:string;description:string;latitude:number|null;longitude:number|null;status:string;resolution_note:string;created_at:string};
  const [assistTickets,setAssistTickets]=useState<AssistTicket[]>([]);
  const [assistPhones,setAssistPhones]=useState({manager:'',mechanic:'',electrician:'',towing:''});
  const [assistSearch,setAssistSearch]=useState('');
  const [assistStatus,setAssistStatus]=useState('all');
  const [assistCompany,setAssistCompany]=useState('');
  const [assistFrom,setAssistFrom]=useState('');
  const [assistTo,setAssistTo]=useState('');
  async function loadAssistance(){
    if(!assistCompany){setAssistTickets([]);return;}
    try{
      const filters=new URLSearchParams({company_id:assistCompany});
      if(assistFrom)filters.set('from_date',assistFrom);
      if(assistTo)filters.set('to_date',assistTo);
      const tickets=await request('/api/v1/workshop/assistance/requests?'+filters);
      setAssistTickets(tickets);
    }catch(e){setMessage(String(e));setAssistTickets([]);}
  }
  async function saveAssistPhones(){try{setAssistPhones(await request('/api/v1/workshop/assistance/contacts',{method:'PUT',body:JSON.stringify(assistPhones)}));setMessage('Workshop contacts saved');}catch(e){setMessage(String(e));}}
  async function updateAssistTicket(ticket:AssistTicket){try{await request(`/api/v1/workshop/assistance/requests/${ticket.id}`,{method:'PATCH',body:JSON.stringify({status:ticket.status,resolution_note:ticket.resolution_note})});setMessage('Request updated');await loadAssistance();}catch(e){setMessage(String(e));}}
  useEffect(()=>{
    if(tab!=='assistance'||!me)return;
    // Don't request cross-company tickets before the user selects a company.
    if(!assistCompany){setAssistTickets([]);}else{
      let active=true;
      const qs=new URLSearchParams({company_id:assistCompany});
      if(assistFrom)qs.set('from_date',assistFrom);
      if(assistTo)qs.set('to_date',assistTo);
      void request('/api/v1/workshop/assistance/requests?'+qs).then((tickets:any)=>{if(active)setAssistTickets(tickets);}).catch((err:any)=>{if(active){setAssistTickets([]);setMessage(String(err));}});
      return ()=>{active=false;};
    }
  },[tab,me?.id,assistCompany,assistFrom,assistTo]);
  useEffect(()=>{if(tab==='assistance'&&me?.role==='super_admin')void request('/api/v1/workshop/assistance/contacts').then(setAssistPhones).catch(e=>setMessage(String(e)));},[tab,me?.id]);
  const [stats,setStats] = useState({companies:0,drivers:0,vehicles:0,trips_active:0});
  const [message,setMessage] = useState('');
  const [monthlyReport,setMonthlyReport]=useState<any>(null);
  const [reportMonth,setReportMonth]=useState(()=>new Date().toISOString().slice(0,7));
  const [monthlyBusy,setMonthlyBusy]=useState(false);
  const [reportPeriod,setReportPeriod]=useState('daily');
  const [reportSuiteSelected,setReportSuiteSelected]=useState<ReportId|null>(null);
  const [reportDriver,setReportDriver]=useState('');
  const [reportCompany,setReportCompany]=useState('');
  const [report,setReport]=useState<any>(null);
  const [selectedRoute,setSelectedRoute]=useState<any>(null);
  const [selectedTripId,setSelectedTripId]=useState<number|null>(null);
  const [routeLoading,setRouteLoading]=useState(false);
  const [tripSearch,setTripSearch]=useState('');
  const [historyDriverId,setHistoryDriverId]=useState('');
  const [historyVehicleId,setHistoryVehicleId]=useState('');
  const [historySite,setHistorySite]=useState('');
  const [tripFrom,setTripFrom]=useState('');
  const [tripTo,setTripTo]=useState('');
  const [preciseTrips,setPreciseTrips]=useState<any[]|null>(null);
  const [rangePlaying,setRangePlaying]=useState(false);
  const [rangeQueue,setRangeQueue]=useState<number[]>([]);
  const [rangeCursor,setRangeCursor]=useState(0);
  const [rangeSearching,setRangeSearching]=useState(false);
  const [fleetDriverSearch,setFleetDriverSearch]=useState('');
  const [fleetVehicleSearch,setFleetVehicleSearch]=useState('');
  const [trackingList,setTrackingList]=useState<'vehicles'|'drivers'>('vehicles');
  const [fleetDriverFocus,setFleetDriverFocus]=useState('');
  const [tripStatusFilter,setTripStatusFilter]=useState('all');
  const [historyEventsOnly,setHistoryEventsOnly]=useState(false);
  const [historyLayers,setHistoryLayers]=useState({route:true,events:true,labels:true,direction:true});
  const [historyRoutes,setHistoryRoutes]=useState<Record<number,any>>({});
  const [historyBusy,setHistoryBusy]=useState<number[]>([]);
  const historyRouteRequestRef=useRef(0);
  async function toggleHistoryTrip(id:number){
    if(!historyRoutes[id]&&Object.keys(historyRoutes).length>=8){setMessage('Show at most 8 additional trips at once for map performance.');return;}
    if(historyRoutes[id]){setHistoryRoutes(old=>{const next={...old};delete next[id];return next;});return;}
    setHistoryBusy(old=>[...old,id]);
    try{const route=await request(`/api/v1/fleet/trips/${id}/route`);setHistoryRoutes(old=>({...old,[id]:route}));}
    catch(e){setMessage(String(e));}finally{setHistoryBusy(old=>old.filter(x=>x!==id));}
  }
  function clearHistoryRoutes(){setHistoryRoutes({});setSelectedRoute(null);setSelectedTripId(null);stopRangePlayback();}
  function exportHistoryKml(route:any){
    if(!route?.points?.length)return;
    const coords=route.points.filter((p:any)=>Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)).map((p:any)=>`${p.longitude},${p.latitude},0`).join(' ');
    const xml=`<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Nuqati Trip ${Number(route.trip_id)}</name><Placemark><name>Recorded GPS route</name><LineString><tessellate>1</tessellate><coordinates>${coords}</coordinates></LineString></Placemark></Document></kml>`;
    const url=URL.createObjectURL(new Blob([xml],{type:'application/vnd.google-earth.kml+xml'}));
    const link=document.createElement('a');link.href=url;link.download=`nuqati-trip-${route.trip_id}.kml`;link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1500);
  }

  const [companyLogos,setCompanyLogos]=useState<Record<number,string>>({});
  const [expandedCompany,setExpandedCompany]=useState<number|null>(null);
  const [editingCompany,setEditingCompany]=useState<number|null>(null);
  const [companyEditorLoading,setCompanyEditorLoading]=useState(false);
  const [companyEditLogo,setCompanyEditLogo]=useState('');

  // Company editor combines existing name and Android driver-app logo into one save.
  async function openCompanyEdit(c:Company){
    setEditingCompany(c.id);setCompanyEditorLoading(true);setMessage('');
    try{const result=await request(`/api/v1/companies/${c.id}/driver-logo`);setCompanyEditLogo(result.logo_data||'');}
    catch(err){setEditingCompany(null);setMessage(String(err));}
    finally{setCompanyEditorLoading(false);}
  }
  async function saveCompanyEdit(changes:CompanyUpdate){
    if(editingCompany===null)return;
    await request(`/api/v1/companies/${editingCompany}`,{method:'PATCH',body:JSON.stringify(changes)});
    if(changes.logo_data!==undefined)setCompanyLogos(old=>({...old,[editingCompany]:changes.logo_data||''}));
    setEditingCompany(null);await load();
    setMessage(lang==='en'?'All company changes saved successfully.':'تم حفظ جميع تعديلات الشركة بنجاح.');
  }
  function beginVehicleEdit(v:Vehicle){setEditingVehicleId(v.id);setTab('vehicles');setMessage('');}
  async function saveVehicleEdit(changes:VehicleUpdate){
    if(editingVehicleId===null||vehicleSaving)return;
    setVehicleSaving(true);
    try{
      // One PATCH commits the vehicle fields and, if provided, an audited odometer correction.
      await request(`/api/v1/vehicles/${editingVehicleId}`,{method:'PATCH',body:JSON.stringify(changes)});
      await load();setEditingVehicleId(null);
      setMessage(lang==='en'?'All vehicle changes saved successfully.':'تم حفظ جميع تعديلات المركبة بنجاح.');
    }finally{setVehicleSaving(false);}
  }

  async function loadPreciseTrips(){
    if(!tripFrom||!tripTo||new Date(tripTo)<=new Date(tripFrom)){setMessage('Choose a valid From and To date/time');return;}
    setRangeSearching(true);
    try{
      const q=new URLSearchParams({start_at:new Date(tripFrom).toISOString(),end_at:new Date(tripTo).toISOString(),limit:'1000'});
      if(me?.role==='super_admin')q.set('company_id',reportCompany);
      if(historyDriverId)q.set('driver_id',historyDriverId);
      if(historyVehicleId)q.set('vehicle_id',historyVehicleId);
      const result=await request(`/api/v1/fleet/trips/search?${q}`);
      setPreciseTrips(result.trips);setSelectedTripId(null);setSelectedRoute(null);setHistoryRoutes({});setRangePlaying(false);
      if(result.truncated)setMessage('Showing first 1000 trips; narrow the date range');
    }catch(e){setMessage(String(e));}finally{setRangeSearching(false)}
  }
  async function startRangePlayback(ids:number[]){
    if(!ids.length)return;
    setRangeQueue(ids);setRangeCursor(0);setRangePlaying(true);await viewTripRoute(ids[0]);
  }
  function stopRangePlayback(){setRangePlaying(false);setRangeQueue([]);setRangeCursor(0);}
  async function nextRangeTrip(){
    if(!rangePlaying)return;
    const next=rangeCursor+1;
    if(next>=rangeQueue.length){stopRangePlayback();return;}
    setRangeCursor(next);await viewTripRoute(rangeQueue[next]);
  }
  async function viewTripRoute(id:number){const requestId=++historyRouteRequestRef.current;setSelectedTripId(id);setRouteLoading(true);try{const route=await request(`/api/v1/fleet/trips/${id}/route`);if(requestId===historyRouteRequestRef.current)setSelectedRoute(route);}catch(e){if(requestId===historyRouteRequestRef.current)setMessage(String(e));}finally{if(requestId===historyRouteRequestRef.current)setRouteLoading(false);}}
  const canDeleteTrip=me?.role==='super_admin'||me?.role==='company_admin';
  async function deleteTripFromWeb(tripId:number,status:string){
    if(!canDeleteTrip||status==='active'){setMessage(lang==='en'?'Only completed trips can be removed.':'يمكن حذف الرحلات المكتملة فقط.');return;}
    const confirmation=window.prompt(lang==='en'?`Permanently delete trip #${tripId} and all its events and GPS points? Type the trip number to confirm.`:`حذف الرحلة #${tripId} نهائياً مع المخالفات ونقاط GPS؟ اكتب رقم الرحلة للتأكيد.`);
    if(confirmation!==String(tripId))return;
    const reason=window.prompt(lang==='en'?'Reason for deletion (minimum 8 characters):':'سبب الحذف (8 أحرف على الأقل):');
    if(!reason||reason.trim().length<8)return;
    try{
      await request(`/api/v1/fleet/trips/${tripId}`,{method:'DELETE',body:JSON.stringify({confirm_trip_id:tripId,reason:reason.trim()})});
      setPreciseTrips(prev=>prev?.filter(t=>t.id!==tripId)||null);
      setHistoryRoutes(prev=>{const copy={...prev};delete copy[tripId];return copy;});
      if(selectedTripId===tripId){setSelectedTripId(null);setSelectedRoute(null);stopRangePlayback();}
      setMessage(lang==='en'?`Trip #${tripId} was permanently deleted.`:`تم حذف الرحلة #${tripId} نهائياً.`);
      await load();if(report)await fetchReport(reportPeriod,'',reportCompany);
    }catch(e){setMessage(String(e));}
  }
  async function deleteTripEvent(tripId:number,eventId:number){
    if(!canDeleteTrip)return;
    const reason=window.prompt(lang==='en'?`Delete event #${eventId} from trip #${tripId}? Provide a reason (minimum 8 characters).`:`حذف المخالفة #${eventId} من الرحلة #${tripId}؟ أدخل السبب (8 أحرف على الأقل).`);
    if(!reason||reason.trim().length<8)return;
    try{
      await request(`/api/v1/fleet/trips/${tripId}/events/${eventId}`,{method:'DELETE',body:JSON.stringify({confirm_trip_id:tripId,reason:reason.trim()})});
      if(selectedTripId===tripId)await viewTripRoute(tripId);
      setPreciseTrips(prev=>prev?.map(t=>t.id===tripId?{...t,event_count:Math.max(0,Number(t.event_count||0)-1)}:t)||null);
      setMessage(lang==='en'?'Event permanently deleted.':'تم حذف المخالفة نهائياً.');
      await load();if(report)await fetchReport(reportPeriod,'',reportCompany);
    }catch(e){setMessage(String(e));}
  }

  useEffect(()=>{if(tab!=='historical-tracking'||!selectedTripId||selectedRoute?.status!=='active')return;
    let alive=true;const refresh=async()=>{try{const r=await request(`/api/v1/fleet/trips/${selectedTripId}/route`);if(alive)setSelectedRoute(r);}catch{/* keep last known route */}};
    const timer=window.setInterval(refresh,15000);return()=>{alive=false;window.clearInterval(timer)};
  },[tab,selectedTripId,selectedRoute?.status]);
  async function loadCompanyLogo(id:number){try{const r=await request(`/api/v1/companies/${id}/driver-logo`);setCompanyLogos(old=>({...old,[id]:r.logo_data||''}));}catch(e){setMessage(String(e));}}
  async function uploadCompanyLogo(id:number,file?:File){if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>220000){setMessage('PNG/JPEG/WebP only, maximum 220 KB');return;}const reader=new FileReader();reader.onload=async()=>{try{const logo_data=String(reader.result);await request(`/api/v1/companies/${id}/driver-logo`,{method:'PUT',body:JSON.stringify({logo_data})});setCompanyLogos(old=>({...old,[id]:logo_data}));setMessage('Company driver logo saved');}catch(e){setMessage(String(e));}};reader.readAsDataURL(file);}

  const [reportLoading,setReportLoading]=useState(false);
  const [speedSessions,setSpeedSessions]=useState<any[]>([]);
  const [speedSessionsLoading,setSpeedSessionsLoading]=useState(false);
  async function loadSpeedSessions(){
    const cid=configCid;
    if(!cid){setMessage(lang==='en'?'Select a company':'اختر شركة');return;}
    setSpeedSessionsLoading(true);
    try{const result=await request('/api/v1/fleet/speeding-sessions?company_id='+cid+'&limit=200');setSpeedSessions(result.sessions||[]);}
    catch(e){setMessage(String(e));}finally{setSpeedSessionsLoading(false);}
  }

  const [speedThreshold,setSpeedThreshold]=useState('100');
  const [accelThreshold,setAccelThreshold]=useState('3');
  const [aggressiveAccel,setAggressiveAccel]=useState('16.2');
  const [aggressiveBrake,setAggressiveBrake]=useState('16.2');
  const [brakeThreshold,setBrakeThreshold]=useState('3');
  type EventCondition = {event_type:string;max_gps_age_seconds:number;max_hdop:number|null;min_satellites:number|null;max_accuracy_m:number;gps_age_operator?:string;hdop_operator?:string;satellites_operator?:string;accuracy_operator?:string};
  const eventKinds=['speeding','excessive_speeding','harsh_acceleration','excessive_harsh_acceleration','harsh_braking','excessive_harsh_braking','harsh_cornering','geofence_entry','geofence_exit','geofence_restricted'];
  const [eventConditions,setEventConditions]=useState<EventCondition[]>([]);
  const [openEvent,setOpenEvent]=useState<string|null>(null);
  const [eventPolicy,setEventPolicy]=useState<{enabled:Record<string,boolean>;enforce_gps_conditions:boolean}>({enabled:{speeding:true,harsh_acceleration:true,excessive_harsh_acceleration:true,harsh_braking:true,excessive_harsh_braking:true,excessive_speeding:true,harsh_cornering:true,geofence_entry:true,geofence_exit:true,geofence_restricted:true},enforce_gps_conditions:true});
  type GeoZone = {id:string;name:string;latitude:number;longitude:number;radius_m:number;mode:string;shape?:'circle'|'rectangle'|'polygon';polygon_points?:number[][]|null;speed_limit_kmh:number|null;vehicle_ids?:number[]|null};
  type RiskDriver = {driver_id:number;driver_name:string;distance_km:number;score:number|null;risk:string;event_count:number};
  const [phase4Zones,setPhase4Zones]=useState<GeoZone[]>([]);
  const [phase4Risk,setPhase4Risk]=useState<RiskDriver[]>([]);
  const [policyAcks,setPolicyAcks]=useState<{driver_id:number;driver_name:string;status:string;received_at:string|null}[]>([]);
  const [scorePolicy,setScorePolicy]=useState<any>(null);
  const [scorePolicyCompany,setScorePolicyCompany]=useState('');
  const [phase4Settings,setPhase4Settings]=useState({cornering_ms2:3.5,min_cornering_speed_kmh:20,risk_medium_below:85,risk_high_below:70,risk_critical_below:50});
  const [phase4Company,setPhase4Company]=useState('');
  const [phase4Period,setPhase4Period]=useState('weekly');
  const [selectedGeoId,setSelectedGeoId]=useState<string|null>(null);
  const [showGeoDetails,setShowGeoDetails]=useState(false);
  const [geoSelection,setGeoSelection]=useState<number[]|null>(null);
  const [liveZones,setLiveZones]=useState<GeoZone[]>([]);
  const [liveSnapshot,setLiveSnapshot]=useState<any|null>(null);
  const [liveError,setLiveError]=useState('');
  const [liveVehicleId,setLiveVehicleId]=useState<number|null>(null);
  const [liveMotionFilter,setLiveMotionFilter]=useState<LiveMotionFilter>('all');
  const [liveShowZones,setLiveShowZones]=useState(true);
  const [liveShowActive,setLiveShowActive]=useState(true);
  const [liveShowPassive,setLiveShowPassive]=useState(false);
  const [liveShareLinks,setLiveShareLinks]=useState<any[]>([]);
  const [liveShareMinutes,setLiveShareMinutes]=useState('15');
  const [liveShareUrl,setLiveShareUrl]=useState('');
  const [liveRequestMessage,setLiveRequestMessage]=useState('');
  const [liveActiveKinds,setLiveActiveKinds]=useState<string[]>([]);
  const [zoneForm,setZoneForm]=useState({name:'',latitude:'',longitude:'',radius_m:'200',mode:'restricted',speed_limit_kmh:'',shape:'circle' as 'circle'|'rectangle'|'polygon'});
  const [zonePoints,setZonePoints]=useState<[number,number][]>([]);
  // A change of company is applied once to every fleet workspace, not on tab navigation.
  useEffect(()=>{
    if(!me)return;
    const cid=activeCompanyId;
    setListCompany(cid||'none');setOverviewCompany(cid);
    setCompanyViewId(cid);setUsersViewCompany(cid);setVehicleViewCompany(cid);
    setDriverViewCompany(cid);setAssistCompany(cid);setConfigCompany(cid);
    setPhase4Company(cid);setReportCompany(cid);
    setPrivacyFilter({company:cid,driver:'',action:'all'});
    setNotificationFilter({company:cid,driver:'',action:'all'});
    setCameraFilter({company:cid,driver:'',action:'all'});
    setPrivacyApplied(null);setNotificationApplied(null);setCameraApplied(null);
    setReport(null);setMonthlyReport(null);setReportDriver('');
    setLiveSnapshot(null);setLiveVehicleId(null);setLiveShareUrl('');
    setSelectedTripId(null);setSelectedRoute(null);setPreciseTrips(null);
    setHistoryDriverId('');setHistoryVehicleId('');setHistoryRoutes({});
    setConfigSection('');setScorePolicy(null);setEventConditions([]);
    setPolicyAcks([]);setPhase4Zones([]);setSelectedGeoId(null);
    setAssistTickets([]);setOdometerRecords([]);setOdometerHistorySearched(false);
  },[activeCompanyId,me?.id]);
  const phase4Cid=me?.role==='super_admin'?(tab==='configuration'?configCompany:phase4Company):String(me?.company_id||'');
  async function loadPhase4(){if(!phase4Cid)return;try{
    const config=await request(`/api/v1/fleet/phase4?company_id=${phase4Cid}`);
    setPhase4Zones(config.zones||[]);setPhase4Settings(config.settings);
  }catch(e){setMessage(String(e));}}
  async function addZone(e:React.FormEvent){e.preventDefault();if(!phase4Cid)return;try{
    const shape=zoneForm.shape;
    const points=shape==='rectangle'&&zonePoints.length===2?[
      zonePoints[0], [zonePoints[0][0],zonePoints[1][1]],zonePoints[1], [zonePoints[1][0],zonePoints[0][1]]
    ]:zonePoints;
    if(shape==='circle' && (!zoneForm.latitude||!zoneForm.longitude))throw Error(lang==='ar'?'حدد مركز الدائرة أولاً':'Select the circle center first');
    if(shape!=='circle' && (points.length<3 || (shape==='rectangle' && zonePoints.length!==2)))throw Error(lang==='ar'?'حدد زوايا المنطقة أولاً':'Choose the zone corners first');
    const lat=shape==='circle'?Number(zoneForm.latitude):points.reduce((a,p)=>a+p[0],0)/points.length;
    const lon=shape==='circle'?Number(zoneForm.longitude):points.reduce((a,p)=>a+p[1],0)/points.length;
    await request(`/api/v1/fleet/phase4/zones?company_id=${phase4Cid}`,{method:'POST',body:JSON.stringify({name:zoneForm.name,latitude:lat,longitude:lon,radius_m:Number(zoneForm.radius_m),shape,polygon_points:shape==='circle'?null:points,mode:zoneForm.mode,speed_limit_kmh:zoneForm.speed_limit_kmh?Number(zoneForm.speed_limit_kmh):null})});
    setZoneForm({...zoneForm,name:''});setZonePoints([]);await loadPhase4();
  }catch(e){setMessage(String(e));}}
  async function deleteZone(id:string){if(!phase4Cid)return;try{await request(`/api/v1/fleet/phase4/zones/${id}?company_id=${phase4Cid}`,{method:'DELETE'});await loadPhase4();}catch(e){setMessage(String(e));}}
  async function savePhase4Settings(){if(!phase4Cid)return;try{await request(`/api/v1/fleet/phase4/settings?company_id=${phase4Cid}`,{method:'PUT',body:JSON.stringify(phase4Settings)});await loadPhase4();setMessage(lang==='en'?'Safety policy saved':'تم حفظ سياسة السلامة');}catch(e){setMessage(String(e));}}
  useEffect(()=>{if(tab==='safety'&&phase4Cid)void loadPhase4();},[tab,phase4Cid]);
  useEffect(()=>{const cid=me?.role==='super_admin'?reportCompany:String(me?.company_id||'');if(tab!=='live-tracking'||!cid){setLiveZones([]);return;}request(`/api/v1/fleet/phase4?company_id=${cid}`).then(v=>setLiveZones(v.zones||[])).catch(()=>setLiveZones([]));},[tab,reportCompany,me?.company_id,me?.role]);
  async function saveZoneVehicles(){if(!phase4Cid||!selectedGeoId)return;try{await request(`/api/v1/fleet/phase4/zones/${selectedGeoId}/vehicles?company_id=${phase4Cid}`,{method:'PUT',body:JSON.stringify({vehicle_ids:geoSelection})});await loadPhase4();setShowGeoDetails(false);setMessage(lang==='en'?'Vehicle assignments saved':'تم حفظ المركبات المرتبطة بالمنطقة');}catch(e){setMessage(String(e));}}
  function openGeo(zone:GeoZone){setSelectedGeoId(zone.id);setGeoSelection(zone.vehicle_ids??null);setShowGeoDetails(true);}
  async function loadEventPolicy(cid:string|number){if(!cid)return;try{setEventPolicy(await request('/api/v1/fleet/event-policy?company_id='+cid));}catch(e){setMessage(String(e));}}
  const configCid=String(me?.role==='super_admin'?configCompany:(me?.company_id||''));
  async function loadConfiguration(){
    if(!configCid)return;
    try{
      const [settings,policyAck,phase]=await Promise.all([
        request('/api/v1/fleet/settings?company_id='+configCid),
        request('/api/v1/fleet/driving-policy/ack?company_id='+configCid),
        request('/api/v1/fleet/phase4?company_id='+configCid)]);
      setSpeedThreshold(String(settings.speeding_kmh));
      setAccelThreshold(String(Number((Number(settings.harsh_accel_ms2)*3.6).toFixed(2))));
      setBrakeThreshold(String(Number((Number(settings.harsh_brake_ms2)*3.6).toFixed(2))));setAggressiveAccel(String(Number((Number(settings.aggressive_accel_ms2)*3.6).toFixed(2))));setAggressiveBrake(String(Number((Number(settings.aggressive_brake_ms2)*3.6).toFixed(2))));
      setPolicyAcks(policyAck.drivers||[]);
      setPhase4Settings(phase.settings);
      await Promise.all([loadEventPolicy(configCid),loadScorePolicy(configCid),loadEventConditions(configCid)]);
    }catch(e){setMessage(String(e));}
  }
  useEffect(()=>{if(tab==='configuration'&&configCid)void loadConfiguration();},[tab,configCid]);
  useEffect(()=>{
    if(tab!=='configuration'||!configCid)return;
    const refresh=()=>{void request('/api/v1/fleet/driving-policy/ack?company_id='+configCid).then((r:any)=>setPolicyAcks(r.drivers||[])).catch(()=>{});};
    const interval=window.setInterval(refresh,30000);
    return ()=>window.clearInterval(interval);
  },[tab,configCid]);
  async function loadScorePolicy(cid:string){if(!cid)return;try{const p=await request('/api/v1/fleet/safety-score/policy?company_id='+cid);setScorePolicy(p);setScorePolicyCompany(cid);}catch(e){setMessage(String(e));}}
  async function saveScorePolicy(){try{const cid=configCid;if(!cid||!scorePolicy)throw Error('Select company and load policy');const weights=scorePolicy.weights; if(Object.values(weights).reduce((a:number,b:any)=>a+Number(b),0)!==100)throw Error('Weights must total 100%');await request('/api/v1/fleet/safety-score/policy?company_id='+cid,{method:'PUT',body:JSON.stringify({weights,excessive_speed_margin_kmh:Number(scorePolicy.excessive_speed_margin_kmh),events_per_100km_full_penalty:Number(scorePolicy.events_per_100km_full_penalty),minimum_distance_km:Number(scorePolicy.minimum_distance_km)})});setMessage(lang==='en'?'Safety score policy saved':'تم حفظ سياسة نقاط السلامة');if(reportCompany===String(cid))await fetchReport();}catch(e){setMessage(String(e));}}
  async function saveEventPolicy(){try{const cid=configCid;if(!cid)throw Error('Select company');await request('/api/v1/fleet/event-policy?company_id='+cid,{method:'PUT',body:JSON.stringify({enabled:eventPolicy.enabled,enforce_gps_conditions:eventPolicy.enforce_gps_conditions})});setMessage(lang==='en'?'Event policy saved':'تم حفظ سياسة الأحداث');await loadEventPolicy(cid);}catch(e){setMessage(String(e));}}

  async function loadEventConditions(cid:string|number){
    if(!cid)return;
    try{const r=await request('/api/v1/fleet/event-conditions?company_id='+cid);setEventConditions(r.events||[]);}catch(e){setMessage(String(e));}
  }
  function editCondition(kind:string,key:keyof EventCondition,value:any){setEventConditions(old=>old.map(c=>c.event_type===kind?{...c,[key]:value}:c));}
  async function saveEventCondition(c:EventCondition){
    try{const cid=configCid;if(!cid)throw Error('Select company');
      await request('/api/v1/fleet/event-conditions/'+c.event_type+'?company_id='+cid,{method:'PUT',body:JSON.stringify({max_gps_age_seconds:Number(c.max_gps_age_seconds),max_hdop:c.max_hdop===null?null:Number(c.max_hdop),min_satellites:c.min_satellites===null?null:Number(c.min_satellites),max_accuracy_m:Number(c.max_accuracy_m),gps_age_operator:c.gps_age_operator||'<',hdop_operator:c.hdop_operator||'<',satellites_operator:c.satellites_operator||'>',accuracy_operator:c.accuracy_operator||'<'})});
      setMessage(lang==='en'?'Event conditions saved':'تم حفظ شروط الحدث');await loadEventConditions(cid);
    }catch(e){setMessage(String(e));}
  }
  const [driverLinks,setDriverLinks]=useState<{driver_id:number;user_id:number;email:string;vehicle_id:number|null}[]>([]);
  const [linkSelection,setLinkSelection]=useState<Record<number,{user_id:string;vehicle_id:string}>>({});
  const [driverAccount,setDriverAccount]=useState({driver_id:'',email:'',full_name:'',password:''});
  async function fetchReport(period=reportPeriod,driver=reportDriver,company=reportCompany){
    setReportLoading(true);try{
      const cid=me?.role==='super_admin'?(company||activeCompanyId):me?.company_id;
      if(!cid)throw new Error('Select a company');
      const qs=new URLSearchParams({period,company_id:String(cid)});if(driver)qs.set('driver_id',driver);
      const data=await request('/api/v1/fleet/report?'+qs);setReport(data);await loadEventPolicy(cid);setMessage('');
      const settings=await request('/api/v1/fleet/settings?company_id='+cid);setSpeedThreshold(String(settings.speeding_kmh));setAccelThreshold(String(Number((Number(settings.harsh_accel_ms2)*3.6).toFixed(2))));setBrakeThreshold(String(Number((Number(settings.harsh_brake_ms2)*3.6).toFixed(2))));setAggressiveAccel(String(Number((Number(settings.aggressive_accel_ms2)*3.6).toFixed(2))));setAggressiveBrake(String(Number((Number(settings.aggressive_brake_ms2)*3.6).toFixed(2))));
    }catch(err){setMessage(String(err));}finally{setReportLoading(false);}
  }
  useEffect(()=>{if((tab==='live-tracking'||tab==='historical-tracking')&&me&&(me.role!=='super_admin'||reportCompany))void fetchReport(tab==='live-tracking'?'daily':reportPeriod,'',reportCompany);},[tab,reportCompany,me?.id]);
  async function loadMonthlyReport(){
    setMonthlyBusy(true);
    try{
      const cid=me?.role==='super_admin'?reportCompany:me?.company_id;
      if(!cid)throw Error('Select a company first');
      const [year,month]=reportMonth.split('-').map(Number);
      const params=new URLSearchParams({company_id:String(cid),year:String(year),month:String(month)});
      if(reportDriver)params.set('driver_id',reportDriver);
      setMonthlyReport(await request('/api/v1/fleet/monthly-reports?'+params));setMessage('');
    }catch(err){setMessage(String(err));}finally{setMonthlyBusy(false);}
  }
  async function downloadMonthlyReport(kind:string,format:'pdf'|'csv'|'xlsx'){
    try{
      const cid=me?.role==='super_admin'?reportCompany:me?.company_id;
      if(!cid)throw Error('Select a company first');
      const [year,month]=reportMonth.split('-').map(Number);
      const params=new URLSearchParams({company_id:String(cid),year:String(year),month:String(month),kind,format});
      if(reportDriver)params.set('driver_id',reportDriver);
      const res=await fetch(`${API}/api/v1/fleet/monthly-reports/export?${params}`,{headers:{Authorization:`Bearer ${token}`}});
      if(!res.ok)throw Error(`Export failed (${res.status}): ${await res.text()}`);
      const blob=await res.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');
      a.href=url;a.download=`nuqati-${kind}-${reportMonth}.${format}`;document.body.appendChild(a);a.click();a.remove();
      window.setTimeout(()=>URL.revokeObjectURL(url),2000);
    }catch(err){setMessage(String(err));}
  }
  async function createDriverAccount(e:React.FormEvent){e.preventDefault();try{
    await request('/api/v1/driver-accounts',{method:'POST',body:JSON.stringify({...driverAccount,driver_id:Number(driverAccount.driver_id)})});
    setDriverAccount({driver_id:'',email:'',full_name:'',password:''});setMessage('Driver app account created. Give credentials to the driver securely.');
  }catch(err){setMessage(String(err));}}
  async function saveSpeed(){try{const cid=configCid;if(!cid)throw Error('Select company');const speed=Number(speedThreshold),accel=Number(accelThreshold),brake=Number(brakeThreshold);if(!Number.isFinite(speed)||speed<20||speed>200||!Number.isFinite(accel)||accel<3.6||accel>36||!Number.isFinite(brake)||brake<3.6||brake>36)throw Error('Speed: 20–200 km/h; acceleration and braking: 3.6–36 km/h/s');await request('/api/v1/fleet/settings?company_id='+cid,{method:'PUT',body:JSON.stringify({speeding_kmh:speed,harsh_accel_ms2:accel/3.6,harsh_brake_ms2:brake/3.6,aggressive_brake_ms2:Number(aggressiveBrake)/3.6,aggressive_accel_ms2:Number(aggressiveAccel)/3.6})});setMessage('Driving policy saved for selected company');}catch(err){setMessage(String(err));}}
  function exportReport(){if(!report)return;const lines=[['Driver','Trips','Score','Speeding','Harsh braking','Harsh acceleration','Harsh cornering'],...report.drivers.map((d:any)=>[d.driver_name,d.trips,d.score??'',d.violations.speeding,d.violations.harsh_braking,d.violations.harsh_acceleration,d.violations.harsh_cornering??0])];const csv=lines.map(r=>r.map((v:any)=>'"'+String(v).replace(/ /g,'_')+'"').join(',')).join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));a.download=`nuqati-${report.period}-${report.company_id}.csv`;a.click();URL.revokeObjectURL(a.href);}

  const [companyName,setCompanyName] = useState('حلول الريادة - تجربة');
  const [plate,setPlate] = useState('أ ب ج 1234');
  const [model,setModel] = useState('Toyota Camry');
  const [vehicleYear,setVehicleYear] = useState('');
  const [vehicleDoorNumber,setVehicleDoorNumber] = useState('');
  const [vehicleOdometer,setVehicleOdometer] = useState('');
  const [driverName,setDriverName] = useState('سائق تجريبي');
  const [driverPhone,setDriverPhone] = useState('');
  const [driverIdNumber,setDriverIdNumber]=useState('');const [driverSite,setDriverSite]=useState('');const [driverVehicle,setDriverVehicle]=useState('');const [driverInitialPassword,setDriverInitialPassword]=useState('');
  const [readingVehicle,setReadingVehicle] = useState('');
  type OdometerRecord = {id:number;company_id:number;vehicle_id:number;reading_km:number;source:string;note:string;created_at:string};
  const [odometerRecords,setOdometerRecords]=useState<OdometerRecord[]>([]);
  type PrivacyAuditRow = {event_id:string;company_id:number;driver_id:number;vehicle_id:number|null;privacy_enabled:boolean;selected_at:string;received_at:string};
  type NotificationAuditRow = {event_id:string;company_id:number;driver_id:number;vehicle_id:number|null;notifications_enabled:boolean;selected_at:string;received_at:string};
  type SafetyObservationRow = {event_id:string;company_id:number;driver_id:number;vehicle_id:number|null;event_type:string;speed_kmh:number|null;observed_at:string;received_at:string};
  const [safetyObservations,setSafetyObservations]=useState<SafetyObservationRow[]>([]);
  const [notificationAudit,setNotificationAudit]=useState<NotificationAuditRow[]>([]);
  type TrackingHeartbeatRow = {driver_id:number;company_id:number;vehicle_id:number|null;screen_state:'locked'|'unlocked'|'unknown';trip_active:boolean;gps_fix_age_s:number|null;captured_at:string;received_at:string};
  const [trackingHeartbeats,setTrackingHeartbeats]=useState<TrackingHeartbeatRow[]>([]);
  type ConnectionAlertRow = {id:number;driver_id:number;company_id:number;driver_name:string;plate_number:string;last_contact_at:string;detected_at:string;email_sent_at:string|null};
  const [connectionAlerts,setConnectionAlerts]=useState<ConnectionAlertRow[]>([]);
  useEffect(()=>{
    if(!me||!token||!activeCompanyId){setConnectionAlerts([]);return;}
    let active=true;
    const refresh=async()=>{
      try{
        const rows=await request(`/api/v1/fleet/connection-alerts?company_id=${encodeURIComponent(activeCompanyId)}`);
        if(active)setConnectionAlerts(Array.isArray(rows)?rows:[]);
      }catch{/* An API error is not evidence a driver recovered; keep the last alert. */}
    };
    void refresh();
    const interval=window.setInterval(()=>void refresh(),30000);
    return ()=>{active=false;window.clearInterval(interval);};
  },[token,me?.id,activeCompanyId]);
  const [privacyAudit,setPrivacyAudit]=useState<PrivacyAuditRow[]>([]);
  type PrivacyRequestRow={id:number;company_id:number;driver_id:number;company_name:string;driver_name:string;status:string;reason:string;requested_at:string;decided_at:string|null};
  const [privacyRequests,setPrivacyRequests]=useState<PrivacyRequestRow[]>([]);
  async function loadPrivacyRequests(){try{const rows=await request('/api/v1/fleet/privacy-requests');setPrivacyRequests(Array.isArray(rows)?rows:[]);}catch(e){setPrivacyError(String(e));}}
  async function privacyRequestAction(id:number,action:'approve'|'reject'|'revoke'){
   try{await request(`/api/v1/fleet/privacy-requests/${id}/${action==='revoke'?'revoke':'decision'}`,{method:'POST',...(action==='revoke'?{}:{body:JSON.stringify({approve:action==='approve'})})});await loadPrivacyRequests();}catch(e){setPrivacyError(String(e));}
  }

  const [privacySection,setPrivacySection]=useState('requests');
  const [privacyLoading,setPrivacyLoading]=useState(false);
  const [privacyError,setPrivacyError]=useState('');
  type AuditFilter = {company:string;driver:string;action:string};
  const defaultAuditFilter:AuditFilter = {company:'',driver:'',action:'all'};
  const [privacyFilter,setPrivacyFilter]=useState<AuditFilter>({...defaultAuditFilter});
  const [notificationFilter,setNotificationFilter]=useState<AuditFilter>({...defaultAuditFilter});
  const [cameraFilter,setCameraFilter]=useState<AuditFilter>({...defaultAuditFilter});
  const [privacyApplied,setPrivacyApplied]=useState<AuditFilter|null>(null);
  const [notificationApplied,setNotificationApplied]=useState<AuditFilter|null>(null);
  const [cameraApplied,setCameraApplied]=useState<AuditFilter|null>(null);
  async function loadPrivacyAudit(){
    setPrivacyLoading(true);setPrivacyError('');
    try{
      const [rows,notifications,safety,heartbeats]=await Promise.all([request('/api/v1/privacy-audit?limit=500'),request('/api/v1/notification-audit?limit=500'),request('/api/v1/safety-observations?limit=500'),request('/api/v1/tracking-heartbeats')]);
      setTrackingHeartbeats(Array.isArray(heartbeats)?heartbeats:[]);setPrivacyAudit(Array.isArray(rows)?rows:[]);setNotificationAudit(Array.isArray(notifications)?notifications:[]);setSafetyObservations(Array.isArray(safety)?safety:[]);
    }catch(err){setPrivacyError(String(err));setPrivacyAudit([]);setNotificationAudit([]);setSafetyObservations([]);}
    finally{setPrivacyLoading(false);}
  }
  useEffect(()=>{if(tab==='privacy-audit'&&me){setPrivacyApplied(null);setNotificationApplied(null);setCameraApplied(null);void loadPrivacyAudit();void loadPrivacyRequests();}},[tab,me?.id]);
  function matchesAudit(r:{company_id:number;driver_id:number},filter:AuditFilter|null){
    return !!activeCompanyId && !!filter && !!filter.driver && String(r.company_id)===activeCompanyId && String(r.driver_id)===filter.driver;
  }
  const privacyVisible=privacyAudit.filter(r=>matchesAudit(r,privacyApplied)&&(privacyApplied?.action==='all'||(privacyApplied?.action==='enabled')===r.privacy_enabled));
  const notificationVisible=notificationAudit.filter(r=>matchesAudit(r,notificationApplied)&&(notificationApplied?.action==='all'||(notificationApplied?.action==='enabled')===r.notifications_enabled));
  const cameraVisible=safetyObservations.filter(r=>matchesAudit(r,cameraApplied));
  function auditControls(filter:AuditFilter,setFilter:React.Dispatch<React.SetStateAction<AuditFilter>>,apply:(value:AuditFilter|null)=>void,showAction:boolean){
    const allCompanies=false;
    return <div className="entry-form">

      <label>{lang==='en'?'Driver':'السائق'}<select value={filter.driver} onChange={e=>{setFilter(v=>({...v,driver:e.target.value}));apply(null);}} disabled={allCompanies&&!filter.company}><option value="">{lang==='en'?'Select driver':'اختر السائق'}</option>{drivers.filter(d=>String(d.company_id)===activeCompanyId).map(d=><option key={d.id} value={d.id}>{d.full_name}</option>)}</select></label>
      {showAction&&<label>{lang==='en'?'Action':'الإجراء'}<select value={filter.action} onChange={e=>{setFilter(v=>({...v,action:e.target.value}));apply(null);}}><option value="all">{lang==='en'?'All actions':'جميع الإجراءات'}</option><option value="enabled">{lang==='en'?'Enabled':'مفعّل'}</option><option value="disabled">{lang==='en'?'Disabled':'معطّل'}</option></select></label>}
      <button type="button" className="primary" disabled={!filter.driver||privacyLoading} onClick={()=>apply({...filter})}>{lang==='en'?'Search':'بحث'}</button>
      <button type="button" className="refresh" onClick={()=>{setFilter({...defaultAuditFilter,company:activeCompanyId});apply(null);}}>{lang==='en'?'Clear':'مسح'}</button>
    </div>;
  }
  function exportPrivacyAudit(){
    const headers=['Event ID','Company ID','Driver ID','Vehicle ID','Action','Selected at','Received at'];
    const cells=privacyVisible.map(r=>[r.event_id,r.company_id,r.driver_id,r.vehicle_id??'',r.privacy_enabled?'Enabled':'Disabled',r.selected_at,r.received_at]);
    const csv=[headers,...cells].map(row=>row.map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='nuqati-privacy-audit.csv';link.click();URL.revokeObjectURL(url);
  }

  const [currentOdometerVehicle,setCurrentOdometerVehicle]=useState('all');
  const [currentOdometerMin,setCurrentOdometerMin]=useState('');
  const [currentOdometerMax,setCurrentOdometerMax]=useState('');
  const [odometerHistoryVehicle,setOdometerHistoryVehicle]=useState('all');
  const [odometerHistorySource,setOdometerHistorySource]=useState('all');
  const [odometerHistoryFrom,setOdometerHistoryFrom]=useState('');
  const [odometerHistoryTo,setOdometerHistoryTo]=useState('');
  const [odometerHistorySearched,setOdometerHistorySearched]=useState(false);
  const [odometerHistoryLoading,setOdometerHistoryLoading]=useState(false);
  const clearOdometerSearch=()=>{setOdometerHistorySearched(false);setOdometerRecords([]);};
  async function loadOdometerHistory(){
    if(odometerHistoryFrom&&odometerHistoryTo&&new Date(odometerHistoryFrom)>new Date(odometerHistoryTo)){
      setMessage(lang==='ar'?'يجب أن يكون تاريخ البداية قبل تاريخ النهاية':'Start date/time must be before end date/time');return;
    }
    setOdometerHistorySearched(false);setOdometerRecords([]);setOdometerHistoryLoading(true);
    try {
      const qs=new URLSearchParams();
      if(odometerHistoryVehicle!=='all')qs.set('vehicle_id',odometerHistoryVehicle);
      if(odometerHistorySource!=='all')qs.set('source',odometerHistorySource);
      if(odometerHistoryFrom)qs.set('from_time',new Date(odometerHistoryFrom).toISOString());
      if(odometerHistoryTo)qs.set('to_time',new Date(odometerHistoryTo).toISOString());
      const rows=await fetchAllPages('/api/v1/odometer-readings?'+qs.toString());
      setOdometerRecords(Array.isArray(rows)?rows:[]);setOdometerHistorySearched(true);
    }catch(err){setMessage('Could not search odometer history: '+String(err));}
    finally{setOdometerHistoryLoading(false);}
  }
  useEffect(()=>{clearOdometerSearch();},[tab,me?.id,listCompany]);
  const [reading,setReading] = useState('');
  const [source,setSource] = useState('MANUAL');
  type Schedule = {id:number;vehicle_id:number;service_type:string;interval_km:number;last_service_km:number;next_due_km:number;current_odometer_km:number|null;remaining_km:number|null;status:string};
  const [schedules,setSchedules] = useState<Schedule[]>([]);
  const [maintenanceVehicle,setMaintenanceVehicle] = useState('');
  type DriverServiceAnswer={driver_id:number;driver_name:string;vehicle_id:number;service_type:string;knowledge:string;reading_type:string|null;reading_km:number|null;interval_km:number|null;submitted_at:string};
  const [driverServiceHistory,setDriverServiceHistory]=useState<DriverServiceAnswer[]>([]);
  useEffect(()=>{
   if(tab!=='maintenance'||!maintenanceVehicle||!token){setDriverServiceHistory([]);return;}
   let valid=true;
   request(`/api/v1/maintenance/driver-history?vehicle_id=${encodeURIComponent(maintenanceVehicle)}`)
    .then((rows:DriverServiceAnswer[])=>{if(valid)setDriverServiceHistory(Array.isArray(rows)?rows:[]);})
    .catch(()=>{if(valid)setDriverServiceHistory([]);});
   return()=>{valid=false;};
  },[tab,maintenanceVehicle,token]);
  const [serviceType,setServiceType] = useState('ENGINE_OIL');
  const [interval,setInterval] = useState('5000');
  const [lastService,setLastService] = useState('0');
  const [warningBefore,setWarningBefore] = useState('500');
  async function request(path:string, options?:RequestInit) {
    const r = await fetch(`${API}${path}`, {headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`} : {}),...(options?.headers||{})},...options});
    if(!r.ok) { const body = await r.json().catch(()=>({})); throw new Error(body.detail || `HTTP ${r.status}`); }
    return r.json();
  }
  async function fetchAllPages(path:string) {
    const results:any[]=[];
    for(let offset=0;offset<1000000;offset+=500){
      const join=path.includes('?')?'&':'?';
      const page=await request(`${path}${join}limit=500&offset=${offset}`);
      if(!Array.isArray(page))throw Error('Unexpected paginated response');
      results.push(...page);
      if(page.length<500)return results;
    }
    throw Error('Fleet data exceeded safe pagination limit; narrow your selection.');
  }
  async function load() {
    try {
      const [s,c,v,d,m] = await Promise.all([request('/api/v1/dashboard'),request('/api/v1/companies'),fetchAllPages('/api/v1/vehicles'),fetchAllPages('/api/v1/drivers'),request('/api/v1/maintenance-schedules')]);
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
      if(!activeCompanyId)throw Error(lang==='en'?'Select a company in the top bar first.':'اختر الشركة من الشريط العلوي أولاً.');
      const data={full_name:accountForm.full_name.trim(),email:accountForm.email.trim(),role:accountForm.role,company_id:Number(activeCompanyId)};
      await request('/api/v1/invitations',{method:'POST',body:JSON.stringify(data)});
      setAccountForm({full_name:'',email:'',role:'company_admin',password:''});
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
    setTab('users');setEditingUserId(u.id);setMessage('');
  }
  async function saveUserEdit(changes:UserUpdate){
    if(editingUserId===null)throw Error('No user selected');
    await request(`/api/v1/users/${editingUserId}`,{method:'PATCH',body:JSON.stringify(changes)});
    setEditingUserId(null);await loadUsers();
    setMessage(lang==='en'?'All user changes saved successfully.':'تم حفظ جميع تعديلات المستخدم بنجاح.');
  }
  async function addUser(e:React.FormEvent){e.preventDefault();try{await request('/api/v1/users',{method:'POST',body:JSON.stringify({...newUser,company_id:Number(newUser.company_id)||null})});await loadUsers();setMessage(lang==='en'?'User created':'تم إنشاء المستخدم');setNewUser({...newUser,email:'',full_name:'',password:''});}catch(err){setMessage(String(err));}}
  async function deactivate(id:number){if(!window.confirm('Deactivate this user?'))return;try{await request(`/api/v1/users/${id}/deactivate`,{method:'PATCH'});await loadUsers();}catch(err){setMessage(String(err));}}
  function adminEdit(kind:'users'|'companies'|'drivers'|'vehicles',id:number,field:string,current:string|number|null){
    setInlineEdit({kind,id,field,value:String(current??'')});
  }
  async function saveInlineEdit(){
    if(!inlineEdit)return;
    const {kind,id,field,value}=inlineEdit;
    const data:Record<string,string|number|null|boolean>={};
    data[field]=['company_id','assigned_driver_id','year'].includes(field)?(value?Number(value):null):field==='is_active'?value.toLowerCase()==='true':value;
    try{if(kind==='vehicles'&&field==='odometer_km'){await request(`/api/v1/vehicles/${id}/odometer-correction`,{method:'POST',body:JSON.stringify({reading_km:Number(value),reason:'Administrator corrected odometer from vehicle editor'})});}else{await request(`/api/v1/${kind}/${id}`,{method:'PATCH',body:JSON.stringify(data)});}setInlineEdit(null);await load();if(kind==='users')await loadUsers();setMessage('Updated successfully');}
    catch(err){setMessage(String(err));}
  }
  const searchMatches=(...parts:unknown[])=>parts.some(v=>String(v??'').toLocaleLowerCase().includes(listSearch.trim().toLocaleLowerCase()));
  const visibleVehicles=vehicles.filter(v=>(listCompany==='all'||String(v.company_id)===listCompany)&&searchMatches(v.plate_number,v.make_model,v.year,v.door_number,v.odometer_km,companies.find(c=>c.id===v.company_id)?.name,drivers.find(d=>d.id===v.assigned_driver_id)?.full_name)&& (listStatus==='all'||(listStatus==='assigned'?!!v.assigned_driver_id:!v.assigned_driver_id)));
  const visibleDrivers=drivers.filter(d=>(listCompany==='all'||String(d.company_id)===listCompany)&&(listStatus==='all'||d.status===listStatus)&&searchMatches(d.full_name,d.phone,d.status,companies.find(c=>c.id===d.company_id)?.name,vehicles.find(v=>v.assigned_driver_id===d.id)?.plate_number));
  const visibleVehicleRows=(!vehicleViewCompany&&!vehicleViewSearch.trim()?[]:vehicles.filter(v=>
    (!vehicleViewCompany||String(v.company_id)===vehicleViewCompany)&&
    (vehicleViewStatus==='all'||(vehicleViewStatus==='assigned'?!!v.assigned_driver_id:!v.assigned_driver_id))&&
    [v.plate_number,v.make_model,v.door_number,drivers.find(d=>d.id===v.assigned_driver_id)?.full_name].some(x=>String(x??'').toLocaleLowerCase().includes(vehicleViewSearch.trim().toLocaleLowerCase()))));
  const visibleDriverRows=(!driverViewCompany&&!driverViewSearch.trim()?[]:drivers.filter(d=>
    (!driverViewCompany||String(d.company_id)===driverViewCompany)&&
    (driverViewStatus==='all'||d.status===driverViewStatus)&&
    [d.full_name,d.phone,vehicles.find(v=>v.assigned_driver_id===d.id)?.plate_number].some(x=>String(x??'').toLocaleLowerCase().includes(driverViewSearch.trim().toLocaleLowerCase()))));
  const visibleUserRows=users.filter(u=>usersViewCompany==='workshop'?u.company_id==null:String(u.company_id)===usersViewCompany);
  const visibleAssistRows=assistTickets.filter(t=>{
    if(String(t.company_id)!==assistCompany|| (assistStatus!=='all'&&t.status!==assistStatus))return false;
    const text=`${t.driver_name} ${t.plate_number||''} ${t.description} ${t.category}`.toLocaleLowerCase();
    if(!text.includes(assistSearch.trim().toLocaleLowerCase()))return false;
    const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Riyadh',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t.created_at));
    return (!assistFrom||day>=assistFrom)&&(!assistTo||day<=assistTo);
  });
  const visibleSchedules=schedules.filter(m=>(listCompany==='all'||String(vehicles.find(v=>v.id===m.vehicle_id)?.company_id)===listCompany)&&(listStatus==='all'||m.status===listStatus)&&searchMatches(m.service_type,m.status,vehicles.find(v=>v.id===m.vehicle_id)?.plate_number,companies.find(c=>c.id===vehicles.find(v=>v.id===m.vehicle_id)?.company_id)?.name));
  async function loadOverview(){
    const version=++overviewReportVersion.current;
    try{const q=new URLSearchParams({from_at:`${overviewApplied.from}T${overviewApplied.fromTime}:00Z`,to_at:new Date(new Date(`${overviewApplied.to}T${overviewApplied.toTime}:00Z`).getTime()+60000).toISOString()});if(overviewCompany)q.set('company_id',overviewCompany);else if(me?.role==='super_admin')return;const result=await request(`/api/v1/fleet/overview/daily?${q}`);if(version===overviewReportVersion.current){setOverviewData(result);setOverviewError('');}}catch(e){if(version===overviewReportVersion.current)setOverviewError(String(e));}
  }
  // Historical report filters must not determine the real-time vehicle motion snapshot.
  // Poll the lightweight live endpoint separately from the daily report aggregates.
  useEffect(()=>{
    if(!token||!me||tab!=='overview'||(me.role==='super_admin'&&!overviewCompany))return;
    let active=true;
    const update=async()=>{
      try{
        const q=new URLSearchParams();if(overviewCompany)q.set('company_id',overviewCompany);
        const motion=await request(`/api/v1/fleet/overview/motion?${q}`);
        if(active){setOverviewData((prev:any)=>prev?{...prev,motion}:prev);setOverviewMotionError('');}
      }catch(e){if(active){setOverviewMotionError(String(e));}}
    };
    void update();const timer=window.setInterval(()=>void update(),30000);
    return()=>{active=false;window.clearInterval(timer);};
  },[token,me?.id,tab,overviewCompany]);
  useEffect(()=>{
    if(!token||!me||tab!=='overview')return;
    setOverviewData(null);void loadOverview();const timer=window.setInterval(()=>void loadOverview(),60000);
    return()=>{overviewReportVersion.current++;window.clearInterval(timer);};
  },[token,me?.id,tab,overviewApplied,overviewCompany,stats.trips_active]);
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
      if(!window.confirm('Deletion is permanent and recovery may be impossible. Continue?'))return;
    }
    if(!window.confirm(`FINAL WARNING: Permanently delete ${preview.company_name} and ALL associated data?`))return;
    await request(`/api/v1/companies/${id}/permanent-delete`,{method:'POST',body:JSON.stringify({confirm_name:confirmedName,confirm_word:word,backup_reference:backupReference})});
    await load();await loadUsers();setMessage('Company permanently deleted. Audit entry recorded.');
  }catch(err){setMessage(String(err));}}

  async function addCompany(e:React.FormEvent) { e.preventDefault(); try { await request('/api/v1/companies',{method:'POST',body:JSON.stringify({name:companyName})}); await load(); setMessage(lang==='en'?'Company added.':'تمت إضافة الشركة.'); } catch(err) {setMessage(String(err));} }
  async function addVehicle(e:React.FormEvent) { e.preventDefault(); if(!activeCompanyId) {setMessage(lang==='en'?'Add a company first.':'أضف شركة أولًا.'); return;} try { await request('/api/v1/vehicles',{method:'POST',body:JSON.stringify({company_id:Number(activeCompanyId),plate_number:plate.trim(),make_model:model.trim(),year:vehicleYear?Number(vehicleYear):null,door_number:vehicleDoorNumber.trim()||null,odometer_km:vehicleOdometer?Number(vehicleOdometer):null})}); await load(); setVehicleYear('');setVehicleDoorNumber('');setVehicleOdometer('');setMessage(lang==='en'?'Vehicle added.':'تمت إضافة السيارة.'); } catch(err) {setMessage(String(err));} }
  useEffect(()=>{if(tab==='drivers'&&me)void loadDriverExtras();},[tab,me?.id]);
  async function addDriver(e:React.FormEvent){e.preventDefault();try{
    const companyId=Number(me?.role==='super_admin'?activeCompanyId:me?.company_id);if(!companyId)throw Error('Select a company in the top bar first');
    await request('/api/v1/drivers/onboard',{method:'POST',body:JSON.stringify({company_id:companyId,full_name:driverName,phone:driverPhone,id_number:driverIdNumber,site_name:driverSite,vehicle_id:driverVehicle?Number(driverVehicle):null,initial_password:driverInitialPassword})});
    setDriverName('');setDriverPhone('');setDriverIdNumber('');setDriverSite('');setDriverVehicle('');setDriverInitialPassword('');await load();setMessage(driverVehicle?'Driver account and vehicle link created. Share the private temporary password securely.':'Driver account created without a vehicle. Driver will select a company plate in My Vehicle after login.');
  }catch(err){setMessage(String(err));}}
  async function addReading(e:React.FormEvent) { e.preventDefault(); if(!readingVehicle || !vehicles.length) {setMessage(lang==='en'?'Add a vehicle first.':'أضف سيارة أولًا.'); return;} const v=vehicles.find(x=>x.id===Number(readingVehicle)); if(!v) return; try { await request('/api/v1/odometer-readings',{method:'POST',body:JSON.stringify({company_id:v.company_id,vehicle_id:v.id,reading_km:Number(reading),source,note:'Entered from Nuqati dashboard'})}); await load(); clearOdometerSearch(); setMessage(lang==='en'?'Odometer reading saved.':'تم حفظ قراءة العداد.'); setReading(''); } catch(err) {setMessage(String(err));} }
  async function saveSchedule(e:React.FormEvent) { e.preventDefault(); const v=vehicles.find(x=>x.id===Number(maintenanceVehicle)); if(!v) {setMessage(lang==='en'?'Choose a vehicle first.':'اختر سيارة أولًا.');return;} try {await request('/api/v1/maintenance-schedules',{method:'PUT',body:JSON.stringify({company_id:v.company_id,vehicle_id:v.id,service_type:serviceType,interval_km:Number(interval),last_service_km:Number(lastService),warning_before_km:Number(warningBefore)})});await load();setMessage(lang==='en'?'Maintenance schedule saved.':'تم حفظ جدول الصيانة.');}catch(err){setMessage(String(err));}}
  async function refreshLiveShares(){
    try{setLiveShareLinks(await request('/api/v1/fleet/live-shares'));}catch(_){setLiveShareLinks([]);}
  }
  async function makeLiveShare(vehicleId:number|null=liveVehicleId){
    if(!vehicleId)return;
    try{const result=await request('/api/v1/fleet/live-shares',{method:'POST',body:JSON.stringify({vehicle_id:vehicleId,expiry_minutes:Number(liveShareMinutes)})});
      const url=`${window.location.origin}/?live_share=${encodeURIComponent(result.token)}`;
      setLiveShareUrl(url);await refreshLiveShares();
    }catch(e){setLiveRequestMessage(String(e));}
  }
  async function revokeLiveShare(shareId:string){try{await request(`/api/v1/fleet/live-shares/${shareId}`,{method:'DELETE'});await refreshLiveShares();}catch(e){setLiveRequestMessage(String(e));}}
  async function requestNewLivePosition(vehicleId:number|null=liveVehicleId){
    if(!vehicleId)return;
    try{const result=await request(`/api/v1/fleet/live-position-request/${vehicleId}`,{method:'POST'});
      setLiveRequestMessage(lang==='en'?`Request sent. Awaiting the Driver app; expires ${new Date(result.expires_at).toLocaleTimeString()}.`:'تم إرسال الطلب. بانتظار تطبيق السائق.');
    }catch(e){setLiveRequestMessage(String(e));}
  }
  async function saveLiveEventKinds(){
    const cid=me?.role==='super_admin'?reportCompany:String(me?.company_id||'');
    if(!cid)return;
    try{await request(`/api/v1/fleet/live-active-events?company_id=${cid}`,{method:'PUT',body:JSON.stringify({event_types:liveActiveKinds})});setLiveRequestMessage(lang==='en'?'Active event configuration saved.':'تم حفظ إعداد الأحداث النشطة.');void fetchLiveSnapshot();}catch(e){setLiveRequestMessage(String(e));}
  }
  async function fetchLiveSnapshot(){
    const cid=me?.role==='super_admin'?reportCompany:String(me?.company_id||'');
    if(!cid)return;
    try{const data=await request(`/api/v1/fleet/live-snapshot?company_id=${encodeURIComponent(cid)}&minutes=30`);
      setLiveSnapshot(data);setLiveError('');setLiveActiveKinds(data.active_event_kinds||[]);
    }catch(e){setLiveError(String(e));}
  }
  useEffect(()=>{
    if(tab!=='live-tracking'||!me||(me.role==='super_admin'&&!reportCompany)){setLiveSnapshot(null);return;}
    void fetchLiveSnapshot();void refreshLiveShares();
    const tick=window.setInterval(()=>{void fetchLiveSnapshot();},30000);
    return ()=>window.clearInterval(tick);
  },[tab,me?.id,reportCompany]);
  // One company-scoped snapshot drives the status counts, sorted list and map.
  // Use the backend's freshness-aware state; do not infer motion from an old speed.
  const livePositions = useMemo<LivePosition[]>(()=>{
    const rows:LivePosition[]=Array.isArray(liveSnapshot?.positions)?liveSnapshot.positions:[];
    const timestamp=(value:string|null)=>{
      const parsed=value?Date.parse(value):NaN;
      return Number.isFinite(parsed)?parsed:-Infinity;
    };
    return [...rows].sort((a,b)=>timestamp(b.recorded_at)-timestamp(a.recorded_at) || a.plate.localeCompare(b.plate) || a.vehicle_id-b.vehicle_id);
  },[liveSnapshot]);
  const liveMovingCount=livePositions.filter(p=>p.state==='moving').length;
  const liveStationaryCount=livePositions.filter(p=>p.state==='stationary').length;
  const liveUnknownCount=livePositions.length-liveMovingCount-liveStationaryCount;
  const visibleLivePositions=useMemo(()=>{
    const search=fleetVehicleSearch.trim().toLocaleLowerCase();
    return livePositions.filter(p=>(liveMotionFilter==='all'||p.state===liveMotionFilter)
      &&(!search||`${p.plate} ${p.driver_name||''}`.toLocaleLowerCase().includes(search)));
  },[livePositions,liveMotionFilter,fleetVehicleSearch]);
  const displayedLiveVehicleId=liveVehicleId!==null&&visibleLivePositions.some(p=>p.vehicle_id===liveVehicleId)?liveVehicleId:null;
  const selectedLivePosition=displayedLiveVehicleId!==null?visibleLivePositions.find(p=>p.vehicle_id===displayedLiveVehicleId):null;
  const liveSnapshotTime=liveSnapshot?.generated_at?new Date(liveSnapshot.generated_at).toLocaleTimeString(lang==='ar'?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh',hour:'2-digit',minute:'2-digit',second:'2-digit'}):null;
  const chooseLiveMotion=(motion:'moving'|'stationary')=>{
    setLiveMotionFilter(previous=>previous===motion?'all':motion);
    setLiveVehicleId(null);
  };
  const clearLiveFilters=()=>{setLiveMotionFilter('all');setFleetVehicleSearch('');setLiveVehicleId(null);};
  const nav = [{id:'overview',emoji:'📊',label:label('overview','Overview','نظرة عامة'),icon:Activity},{id:'companies',emoji:'🏢',label:label('companies','Companies','الشركات'),icon:Building2},{id:'users',emoji:'🔑',label:label('users','Users & Access','المستخدمون والصلاحيات'),icon:UserCog},{id:'vehicles',emoji:'🚙',label:label('vehicles','Vehicles','السيارات'),icon:CarFront},{id:'drivers',emoji:'👥',label:label('drivers','Drivers','السائقون'),icon:Users},{id:'handover',emoji:'🔄',label:lang==='en'?'Vehicle Handover':'استلام وتسليم المركبات',icon:ShieldCheck},{id:'live-tracking',emoji:'📍',label:label('live-tracking','Live Tracking','التتبع المباشر'),icon:CarFront},{id:'historical-tracking',emoji:'🗺️',label:label('historical-tracking','Historical Tracking','التتبع التاريخي'),icon:Route},{id:'odometer',emoji:'🧭',label:label('odometer','Odometer','قراءة العداد'),icon:Gauge},{id:'assistance',emoji:'🛠️',label:label('assistance','Workshop Requests','طلبات الورشة'),icon:Wrench},{id:'maintenance',emoji:'🔧',label:label('maintenance','Maintenance Alerts','تنبيهات الصيانة'),icon:Wrench},{id:'mobile-diagnostics',emoji:'📱',label:lang==='en'?'App Diagnostics':'تشخيص التطبيق',icon:Activity},{id:'safety',emoji:'🛡️',label:label('safety','Geofence Location','مواقع المناطق الجغرافية'),icon:ShieldCheck},{id:'configuration',emoji:'⚙️',label:label('configuration','Configuration','الإعدادات'),icon:ShieldCheck},{id:'privacy-audit',emoji:'🔒',label:label('privacy-audit','Privacy Audit','سجل وضع الخصوصية'),icon:Shield},{id:'reports',emoji:'📈',label:label('reports','Fleet Reports','تقارير الأسطول'),icon:Route},{id:'settings',emoji:'🎨',label:label('settings','Branding & Language','الهوية واللغة'),icon:UserCog},{id:'my-account',emoji:'👤',label:lang==='en'?'My Account':'حسابي',icon:UserCog}] as const;
  if(publicShareToken)return <PublicLiveShare shareToken={publicShareToken}/>;
  if(resetToken) return <div className="login-screen"><form className="login-card" onSubmit={completeRecovery}><h2>{lang==='en'?'Reset password':'إعادة تعيين كلمة المرور'}</h2><label>{lang==='en'?'New password (12+ characters)':'كلمة المرور الجديدة (12 حرفًا على الأقل)'}<input type="password" minLength={12} maxLength={128} autoComplete="new-password" required value={recoveryPassword} onChange={e=>setRecoveryPassword(e.target.value)}/></label><label>{lang==='en'?'Confirm new password':'تأكيد كلمة المرور'}<input type="password" minLength={12} maxLength={128} autoComplete="new-password" required value={recoveryConfirm} onChange={e=>setRecoveryConfirm(e.target.value)}/></label><button className="primary">{lang==='en'?'Change password':'تغيير كلمة المرور'}</button><div className="notice" role="status">{recoveryStatus}</div><a href="/">{lang==='en'?'Back to login':'العودة لتسجيل الدخول'}</a></form></div>;
  if(verifyEmailToken) return <div className="login-screen"><div className="login-card"><h2>{lang==='en'?'Confirm new email':'تأكيد البريد الإلكتروني الجديد'}</h2><p>{lang==='en'?'Confirm that this email belongs to you.':'أكد أن هذا البريد الإلكتروني يخصك.'}</p><button className="primary" onClick={completeEmailVerification}>{lang==='en'?'Confirm email':'تأكيد البريد'}</button><div className="notice" role="status">{recoveryStatus}</div><a href="/">{lang==='en'?'Back to login':'العودة لتسجيل الدخول'}</a></div></div>;
  if(inviteToken) return <div className="login-screen"><form className="login-card" onSubmit={acceptInvite}><img src={logo} alt="Nuqati"/><h2>Nuqati by Al-Riadah Workshop</h2><p>{lang==='en'?'Activate account':'تفعيل الحساب'}</p><label>New password (12+ characters)<input type="password" minLength={12} required value={invitePassword} onChange={e=>setInvitePassword(e.target.value)}/></label><button className="primary">Activate account</button><div className="notice">{inviteStatus}</div>{inviteStatus.startsWith('Account activated')&&<a href="/">Go to login</a>}</form></div>;
  if(!token || !me) return <div className="login-screen"><form className="login-card" onSubmit={signIn}><img src={logo} alt="Solutions Workshop"/><h1>{lang==='en'?'NUQATI':'نقاطي'}</h1><p>Secure Fleet Management</p><label>{lang==='en'?'Email':'البريد الإلكتروني'}<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)}/></label><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/></label>{loginError&&<div className="notice">{loginError}</div>}<button className="primary">Sign in</button><small>{lang==='en'?'Nuqati by Al-Riadah Workshop':'نقاطي من ورشة حلول الريادة'}</small><button type="button" className="refresh" onClick={()=>switchLang(lang==='en'?'ar':'en')}>{lang==='en'?'العربية':'English'}</button><button type="button" className="refresh" onClick={()=>setShowRecovery(v=>!v)}>{lang==='en'?'Forgot password?':'نسيت كلمة المرور؟'}</button>{showRecovery&&<div className="nuqati-account-recovery" role="group"><label>{lang==='en'?'Account email':'البريد الإلكتروني للحساب'}<input type="email" value={recoveryEmail} onChange={e=>setRecoveryEmail(e.target.value)}/></label><button type="button" className="primary" onClick={()=>{if(recoveryEmail.includes('@'))void requestRecovery({preventDefault:()=>{}} as React.FormEvent);else setRecoveryStatus('Enter a valid email');}}>{lang==='en'?'Send reset email':'إرسال رابط إعادة التعيين'}</button><div className="notice" role="status">{recoveryStatus}</div></div>}</form></div>;
  const canManage=me.role==='super_admin';
  const canCreateUsers=me.role==='super_admin';
  return <div className="app-shell nuqati-design-2026 nq-reference-layout" data-page={tab} dir={lang==='ar'?'rtl':'ltr'}>
    <aside className="sidebar"><div className="brand"><img className="brand-logo" src={logo} alt="Solutions Workshop"/><div><strong>{lang==='en'?'Nuqati':'نقاطي | Nuqati'}</strong><small>Al-Riadah Workshop</small></div></div>
      <nav className="nuqati-nav" aria-label={lang==='en'?'Main navigation':'القائمة الرئيسية'}>
      {([['overview'],['companies','vehicles','drivers','handover','live-tracking','historical-tracking'],['safety','configuration','privacy-audit'],['odometer','maintenance','mobile-diagnostics','assistance'],['reports'],['users','settings','my-account']] as const).map((ids,index)=>{
        const groupNames=[lang==='en'?'Home':'الرئيسية',lang==='en'?'Fleet':'الأسطول',lang==='en'?'Safety':'السلامة',lang==='en'?'Maintenance':'الصيانة',lang==='en'?'Reports':'التقارير',lang==='en'?'Administration':'الإدارة'];
        const groupIcons=[Activity,CarFront,Shield,Wrench,Route,UserCog];
        const GroupIcon=groupIcons[index];
        const allowed=nav.filter(n=>ids.some(id=>id===n.id)&&(n.id!=='companies'||me.role==='super_admin')&&(n.id!=='users'||canCreateUsers)&&(n.id!=='settings'||canCreateUsers));
        if(!allowed.length)return null;
        return <details key={index} open={ids.some(id=>id===tab)} className="nuqati-nav-group"><summary><span className="nuqati-nav-group-label"><GroupIcon size={16} aria-hidden="true"/>{groupNames[index]}</span><ChevronDown size={15} className="nuqati-nav-chevron" aria-hidden="true"/></summary>{allowed.map(n=><button type="button" key={n.id} aria-current={tab===n.id?'page':undefined} className={`nav-item ${tab===n.id?'active':''}`} onClick={()=>setTab(n.id)}><span className="nq-nav-emoji" aria-hidden="true">{n.emoji}</span><span className="nq-nav-label">{n.label}</span></button>)}</details>;
      })}
      </nav>
      <div className="sidebar-bottom"><ShieldCheck size={18}/><span>{lang==='en'?'Production':'الإصدار الرسمي'}</span></div>
    </aside>
    <main className="main"><header className="topbar"><div className="nuqati-page-heading"><span className="nuqati-page-icon"><span className="nq-page-emoji" aria-hidden="true">{nav.find(n=>n.id===tab)?.emoji}</span></span><div><span className="eyebrow">{lang==='en'?'Driver Performance Platform':'منصة أداء السائقين'}</span><h1>{nav.find(n=>n.id===tab)?.label}</h1></div></div><div className="header-actions">{me.role==='super_admin'&&<label className="nuqati-top-company nq-global-company"><Building2 size={16}/><span>{lang==='en'?'Active company':'الشركة الحالية'}</span><select aria-label={lang==='en'?'Active company for all pages':'الشركة الحالية لجميع الصفحات'} value={activeCompany} onChange={e=>chooseActiveCompany(e.target.value)}><option value="">{lang==='en'?'Select a company':'اختر الشركة'}</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}{me.role!=='super_admin'&&me.company_id&&<span className="nq-company-identity"><Building2 size={15}/>{companies.find(c=>c.id===me.company_id)?.name||''}</span>}<button type="button" className="user-chip nuqati-account-button" onClick={()=>setTab('my-account')}><UserCog size={15} aria-hidden="true"/><span>{me.full_name} · {me.role}</span></button><button type="button" className="refresh nuqati-button-language" onClick={()=>switchLang(lang==='en'?'ar':'en')}><Globe2 size={16} aria-hidden="true"/>{lang==='en'?'العربية':'English'}</button><button className="refresh" onClick={()=>void load()}><RefreshCw size={16}/> {label('refresh','Refresh','تحديث')}</button><button className="refresh" onClick={signOut}><LogOut size={16}/> {label('logout','Log out','خروج')}</button></div></header>
      {me.role==='super_admin'&&!activeCompanyId&&tab!=='my-account'&&tab!=='settings'&&<div className="nq-context-hint" role="status"><Building2 size={17}/>{lang==='en'?'Select a company in the top bar once to use company-specific pages.':'اختر الشركة مرة واحدة من الشريط العلوي لاستخدام صفحات الشركة.'}</div>}
      {connectionAlerts.length>0&&<section className="panel" role="alert" style={{border:'1px solid #b7791f',background:'rgba(180,108,15,0.12)',padding:'14px 18px',marginBottom:16}}>
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:10}}>
          <strong style={{fontSize:16}}>{lang==='en'?`Connection lost · ${connectionAlerts.length} driver(s)`:`انقطاع الاتصال · ${connectionAlerts.length} سائق`}</strong>
          <button type="button" className="refresh" onClick={()=>setTab('live-tracking')}>{lang==='en'?'Review live tracking':'عرض التتبع المباشر'}</button>
        </div>
        <p style={{margin:'8px 0 0'}}>{connectionAlerts.slice(0,5).map(a=>`${a.driver_name}${a.plate_number?` (${a.plate_number})`:''} · ${lang==='en'?'last contact':'آخر اتصال'} ${new Date(a.last_contact_at).toLocaleString(lang==='en'?'en-GB':'ar-SA')}`).join('  |  ')}</p>
        <small>{lang==='en'?'No server heartbeat for 15+ minutes; the VPN is only one possible cause. Trip GPS may still be recorded locally.':'لم يصل نبض اتصال للخادم منذ 15 دقيقة أو أكثر؛ قد يكون VPN أحد الأسباب فقط، وقد يستمر تسجيل GPS محلياً.'}</small>
      </section>}
      {message && <div className="notice" role="status">{message}</div>}
      {tab==='handover'&&<VehicleHandover key={activeCompanyId} token={token} lang={lang} api={API} companyId={Number(activeCompanyId)||null} isSuperAdmin={me.role==='super_admin'} companies={companies}/>}
      {tab==='my-account'&&<section className="panel nuqati-self-service" aria-label="My account security">
        <div className="nuqati-account-heading"><div className="nuqati-account-heading-icon"><ShieldCheck size={21}/></div><div><h3>{lang==='en'?'Account & Security':'الحساب والأمان'}</h3><p>{lang==='en'?'Manage your login details securely.':'إدارة بيانات الدخول الخاصة بك بأمان.'}</p></div></div>
        <div className="nuqati-account-identity"><div><small>{lang==='en'?'Signed in as':'تم تسجيل الدخول باسم'}</small><strong>{me.full_name}</strong></div><div><small>{lang==='en'?'Login email':'البريد الإلكتروني للدخول'}</small><strong dir="ltr">{me.email}</strong></div></div>
        <div className="nuqati-account-grid">
          <form onSubmit={updateOwnPassword} className="nuqati-account-card">
            <div className="nuqati-account-card-heading"><div><h4>{lang==='en'?'Change password':'تغيير كلمة المرور'}</h4><p>{lang==='en'?'Use at least 12 characters for your new password.':'استخدم 12 حرفًا على الأقل في كلمة المرور الجديدة.'}</p></div></div>
            <label>{lang==='en'?'Current password':'كلمة المرور الحالية'}<input type="password" autoComplete="current-password" required value={accountPassword.current} onChange={e=>setAccountPassword({...accountPassword,current:e.target.value})}/></label>
            <label>{lang==='en'?'New password':'كلمة المرور الجديدة'}<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={accountPassword.next} onChange={e=>setAccountPassword({...accountPassword,next:e.target.value})}/></label>
            <label>{lang==='en'?'Confirm new password':'تأكيد كلمة المرور'}<input type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={accountPassword.confirm} onChange={e=>setAccountPassword({...accountPassword,confirm:e.target.value})}/></label>
            <button className="primary" type="submit">{lang==='en'?'Update password':'تحديث كلمة المرور'}</button>
          </form>
          <form onSubmit={updateOwnEmail} className="nuqati-account-card">
            <div className="nuqati-account-card-heading"><div><h4>{lang==='en'?'Change email address':'تغيير البريد الإلكتروني'}</h4><p>{lang==='en'?'Confirm your new address using the link we send.':'أكد عنوانك الجديد من خلال الرابط المرسل إليه.'}</p></div></div>
            <label>{lang==='en'?'New email address':'البريد الإلكتروني الجديد'}<input type="email" autoComplete="email" required placeholder="name@company.com" value={accountNewEmail} onChange={e=>setAccountNewEmail(e.target.value)}/></label>
            <label>{lang==='en'?'Current password':'كلمة المرور الحالية'}<input type="password" autoComplete="current-password" required value={accountEmailPassword} onChange={e=>setAccountEmailPassword(e.target.value)}/></label>
            <p className="nuqati-account-hint">{lang==='en'?'Your login email changes only after verification.':'لن يتغير بريد الدخول إلا بعد التحقق.'}</p>
            <button className="primary" type="submit">{lang==='en'?'Send verification link':'إرسال رابط التحقق'}</button>
          </form>
        </div>{accountStatus&&<div className="notice nuqati-account-status" role="status">{accountStatus}</div>}
      </section>}

      {tab==='maintenance'&&<section className="nuqati-filter-bar" aria-label="Fleet list filters">
        <label>{lang==='en'?'Search':'بحث'}<input value={listSearch} onChange={e=>setListSearch(e.target.value)} placeholder={lang==='en'?'Name, plate, phone, status or service':'الاسم أو اللوحة أو الهاتف أو الحالة'}/></label>
          <label>{lang==='en'?'Status':'الحالة'}<select value={listStatus} onChange={e=>setListStatus(e.target.value)}>
            <option value="all">{lang==='en'?'All statuses':'كل الحالات'}</option>
            {(['OK','DUE_SOON','OVERDUE','UNKNOWN'] as const).map(status=><option value={status} key={status}>{lang==='en'?({OK:'OK',DUE_SOON:'Due soon',OVERDUE:'Overdue',UNKNOWN:'Unknown'} as Record<string,string>)[status]:({OK:'سليم',DUE_SOON:'قريب الاستحقاق',OVERDUE:'متأخر',UNKNOWN:'غير معروف'} as Record<string,string>)[status]}</option>)}
          </select></label>
        <button type="button" className="refresh" onClick={()=>{setListSearch('');setListStatus('all');}}>{lang==='en'?'Clear':'مسح'}</button>
      </section>}
      {tab==='vehicles'&&editingVehicleId===null&&<section className="nq-selection-toolbar" aria-label={lang==='en'?'Vehicle search':'البحث عن المركبات'}>
        <div className="nq-selection-heading"><strong>{lang==='en'?'Find vehicles':'البحث عن المركبات'}</strong><small>{lang==='en'?'Search by plate, vehicle or driver within the selected company.':'ابحث باللوحة أو المركبة أو السائق ضمن الشركة الحالية.'}</small></div>
        <div className="nq-selection-controls">
        <label>{lang==='en'?'Plate / vehicle / driver':'اللوحة / المركبة / السائق'}<input type="search" value={vehicleViewSearch} onChange={e=>setVehicleViewSearch(e.target.value)} placeholder={lang==='en'?'Search by plate number':'ابحث برقم اللوحة'}/></label>
        <label>{lang==='en'?'Assignment':'التعيين'}<select value={vehicleViewStatus} onChange={e=>setVehicleViewStatus(e.target.value)}><option value="all">{lang==='en'?'All assignments':'كل التعيينات'}</option><option value="assigned">{lang==='en'?'Assigned':'معيّنة'}</option><option value="unassigned">{lang==='en'?'Unassigned':'غير معيّنة'}</option></select></label>
        <button type="button" className="refresh" onClick={()=>{setVehicleViewSearch('');setVehicleViewStatus('all');}}>{lang==='en'?'Clear':'مسح'}</button></div></section>}
      {tab==='drivers'&&editingDriver===null&&<section className="nq-selection-toolbar" aria-label={lang==='en'?'Driver search':'البحث عن السائقين'}>
        <div className="nq-selection-heading"><strong>{lang==='en'?'Find drivers':'البحث عن السائقين'}</strong><small>{lang==='en'?'Search the selected company by driver, phone or vehicle plate.':'ابحث باسم السائق أو الهاتف أو اللوحة ضمن الشركة الحالية.'}</small></div>
        <div className="nq-selection-controls">
        <label>{lang==='en'?'Driver / phone / plate':'السائق / الهاتف / اللوحة'}<input type="search" value={driverViewSearch} onChange={e=>setDriverViewSearch(e.target.value)} placeholder={lang==='en'?'Search drivers':'بحث السائقين'}/></label>
        <label>{lang==='en'?'Status':'الحالة'}<select value={driverViewStatus} onChange={e=>setDriverViewStatus(e.target.value)}><option value="all">{lang==='en'?'All statuses':'كل الحالات'}</option>{['active','inactive','archived'].map(k=><option key={k} value={k}>{lang==='en'?k:({active:'نشط',inactive:'غير نشط',archived:'مؤرشف'} as Record<string,string>)[k]}</option>)}</select></label>
        <button type="button" className="refresh" onClick={()=>{setDriverViewSearch('');setDriverViewStatus('all');}}>{lang==='en'?'Clear':'مسح'}</button></div></section>}
      {inlineEdit&&<section className="nuqati-filter-bar" aria-label="Inline field editor"><strong>{inlineEdit.kind} #{inlineEdit.id} · {inlineEdit.field}</strong><input aria-label={inlineEdit.field} value={inlineEdit.value} onChange={e=>setInlineEdit({...inlineEdit,value:e.target.value})}/><button type="button" className="primary" onClick={saveInlineEdit}>{lang==='en'?'Save':'حفظ'}</button><button type="button" className="refresh" onClick={()=>setInlineEdit(null)}>{lang==='en'?'Cancel':'إلغاء'}</button></section>}

      {tab==='settings' && me.role==='super_admin' && <section className="panel"><h3>{lang==='en'?'Branding & Language':'الهوية واللغة'}</h3><p>{lang==='en'?'Global settings: only Super Admin can publish changes.':'الإعدادات العامة: يستطيع المدير العام وحده نشر التغييرات.'}</p><div className="entry-form"><label>{lang==='en'?'Dashboard logo (PNG, JPEG or WebP; under 220 KB)':'شعار لوحة التحكم (صورة بحجم أقل من ٢٢٠ كيلوبايت)'}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>chooseLogo(e.target.files?.[0])}/></label><img src={logo} alt="Current logo" style={{maxWidth:160,maxHeight:100,objectFit:'contain'}}/><button className="refresh" onClick={()=>setBranding(b=>({...b,logo_data:''}))}>{lang==='en'?'Restore default logo':'استعادة الشعار الافتراضي'}</button></div><h3>{lang==='en'?'Editable navigation and core labels':'تعديل تسميات القائمة والعناصر الأساسية'}</h3><div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Key':'المفتاح'}</th><th>{lang==='en'?'English':'الإنجليزية'}</th><th>{lang==='en'?'Arabic':'العربية'}</th></tr></thead><tbody>{Object.entries(defaults).map(([key,values])=><tr key={key}><td>{key}</td>{(['en','ar'] as const).map(language=><td key={language}><input style={{width:'100%',minWidth:200}} maxLength={120} value={branding.labels[key]?.[language]??values[language]??''} onChange={e=>setBranding(b=>({...b,labels:{...b.labels,[key]:{...(b.labels[key]||{}),[language]:e.target.value}}}))}/></td>)}</tr>)}</tbody></table></div><button className="primary" onClick={saveBranding}>{lang==='en'?'Save branding and labels':'حفظ الهوية والتسميات'}</button></section>}
      {tab==='companies' && me.role==='super_admin' && (editingCompany!==null
        ? (()=>{const c=companies.find(item=>item.id===editingCompany);
            return companyEditorLoading?<section className="panel"><p>{lang==='en'?'Loading company details…':'جارٍ تحميل بيانات الشركة…'}</p></section>
              : c?<CompanyEditPage key={c.id} company={c} initialLogo={companyEditLogo} lang={lang}
                driverCount={drivers.filter(d=>d.company_id===c.id).length}
                vehicleCount={vehicles.filter(v=>v.company_id===c.id).length}
                userCount={users.filter(u=>u.company_id===c.id).length}
                onClose={()=>setEditingCompany(null)} onSave={saveCompanyEdit}/>
              :<section className="panel"><p>{lang==='en'?'Company not found.':'تعذر العثور على الشركة.'}</p><button type="button" onClick={()=>setEditingCompany(null)} className="refresh">{lang==='en'?'Back to companies':'العودة للشركات'}</button></section>;
          })()
        :<section className="panel"><div className="panel-heading"><div><h3>{lang==='en'?'Client Companies':'الشركات العميلة'}</h3><p>{lang==='en'?'Click any company to open its complete editor and save all changes once.':'اضغط على الشركة لفتح صفحة تعديل جميع الحقول وحفظها مرة واحدة.'}</p></div></div>
          <details className="nq-ve-add-form" style={{marginBottom:20}}><summary>{lang==='en'?'+ Add company':'+ إضافة شركة'}</summary><form onSubmit={addCompany} className="entry-form"><label>{lang==='en'?'Company name':'اسم الشركة'}<input required value={companyName} onChange={e=>setCompanyName(e.target.value)}/></label><button className="primary">{lang==='en'?'Add company':'إضافة شركة'}</button></form></details>
          <div className="nq-selection-toolbar"><div className="nq-selection-heading"><strong>{lang==='en'?'Choose a company to manage':'اختر الشركة لإدارة بياناتها'}</strong><small>{lang==='en'?'Company details stay hidden until you select one.':'بيانات الشركات مخفية حتى تحدد الشركة المطلوبة.'}</small></div><div className="nq-selection-controls"><button className="refresh" type="button" onClick={()=>setExpandedCompany(null)}>{lang==='en'?'Clear':'مسح'}</button></div></div>
          {companyViewId?<div className="table-wrap"><table><thead><tr><th>ID</th><th>{lang==='en'?'Company':'الشركة'}</th><th>{lang==='en'?'Drivers':'السائقون'}</th><th>{lang==='en'?'Vehicles':'السيارات'}</th><th>{lang==='en'?'Users':'المستخدمون'}</th><th>{lang==='en'?'Actions':'الإجراءات'}</th></tr></thead><tbody>
          {companies.filter(c=>String(c.id)===companyViewId).map(c=><Fragment key={c.id}><tr className="nq-ve-row-clickable" onClick={()=>void openCompanyEdit(c)}><td>{c.id}</td><td><button type="button" className="nq-ve-plate-link" onClick={e=>{e.stopPropagation();void openCompanyEdit(c);}}>{c.name}</button></td><td>{drivers.filter(d=>d.company_id===c.id).length}</td><td>{vehicles.filter(v=>v.company_id===c.id).length}</td><td>{users.filter(u=>u.company_id===c.id).length}</td><td><button type="button" data-nq-action="edit" className="refresh" onClick={e=>{e.stopPropagation();void openCompanyEdit(c);}}>{lang==='en'?'Edit all fields':'تعديل جميع الحقول'}</button> <button type="button" className="refresh" onClick={e=>{e.stopPropagation();setExpandedCompany(expandedCompany===c.id?null:c.id);void loadUsers();void loadDriverExtras();}}>{expandedCompany===c.id?(lang==='en'?'Hide related records':'إخفاء السجلات'):lang==='en'?'View related records':'عرض السجلات المرتبطة'}</button> <button type="button" className="refresh" onClick={e=>{e.stopPropagation();removeCompany(c.id);}}><Trash2 size={14}/> {lang==='en'?'Permanently delete company + linked data':'حذف الشركة وجميع بياناتها المرتبطة نهائياً'}</button></td></tr>
          {expandedCompany===c.id&&<tr><td colSpan={6}><div className="nq-entity-related"><h3>{lang==='en'?'Company records':'سجلات الشركة'} — {c.name}</h3><div><h4>{lang==='en'?'Drivers':'السائقون'} ({drivers.filter(d=>d.company_id===c.id).length})</h4>{drivers.filter(d=>d.company_id===c.id).map(d=><div key={d.id}>{d.full_name} — {d.phone} — {lang==='en'?d.status:({active:'نشط',inactive:'غير نشط',archived:'مؤرشف'} as Record<string,string>)[d.status]||d.status} <button type="button" className="refresh" onClick={()=>void beginDriverEdit(d)}>{lang==='en'?'Open driver editor':'فتح تعديل السائق'}</button></div>)}{!drivers.some(d=>d.company_id===c.id)&&<p>{lang==='en'?'No drivers':'لا يوجد سائقون'}</p>}</div><div><h4>{lang==='en'?'Vehicles':'المركبات'} ({vehicles.filter(v=>v.company_id===c.id).length})</h4>{vehicles.filter(v=>v.company_id===c.id).map(v=><div key={v.id}>{v.plate_number} — {v.make_model}{v.door_number?` · ${lang==='en'?'Door':'باب'} ${v.door_number}`:''} <button type="button" className="refresh" onClick={()=>beginVehicleEdit(v)}>{lang==='en'?'Open vehicle editor':'فتح تعديل المركبة'}</button></div>)}{!vehicles.some(v=>v.company_id===c.id)&&<p>{lang==='en'?'No vehicles':'لا توجد مركبات'}</p>}</div><div><h4>{lang==='en'?'Users':'المستخدمون'} ({users.filter(u=>u.company_id===c.id).length})</h4>{users.filter(u=>u.company_id===c.id).map(u=><div key={u.id}>{u.full_name} — {lang==='en'?u.role:({super_admin:'المدير العام',company_admin:'مدير الشركة',fleet_manager:'مدير الأسطول',driver:'سائق',representative:'ممثل',workshop_staff:'موظف الورشة'} as Record<string,string>)[u.role]||u.role} — {u.email} <button type="button" className="refresh" onClick={()=>{beginUserEdit(u);setTab('users');}}>{lang==='en'?'Edit user fields':'تعديل بيانات المستخدم'}</button></div>)}{!users.some(u=>u.company_id===c.id)&&<p>{lang==='en'?'No users':'لا يوجد مستخدمون'}</p>}</div></div></td></tr>}</Fragment>)}
          </tbody></table>{!companies.length&&<div className="empty">{lang==='en'?'No companies registered.':'لا توجد شركات مسجلة.'}</div>}</div>:<div className="nq-selection-empty">{lang==='en'?'Select a company above to display its information.':'اختر شركة من الأعلى لعرض بياناتها.'}</div>}</section>)}
      {tab==='companies'&&me.role!=='super_admin'&&me.company_id&&<section className="panel"><h3>{lang==='en'?'Company logo for Android driver app':'شعار الشركة لتطبيق السائق'}</h3><div style={{display:'flex',alignItems:'center',gap:12,flexWrap:'wrap',padding:12}}><strong>{companies.find(c=>c.id===me.company_id)?.name||''}</strong><button type="button" className="refresh" onClick={()=>loadCompanyLogo(me.company_id!)}>{lang==='en'?'View logo':'عرض الشعار'}</button>{companyLogos[me.company_id]&&<img src={companyLogos[me.company_id]} alt="Company logo" style={{width:90,height:90,objectFit:'contain'}}/>}{me.role==='company_admin'&&<input aria-label="Upload company logo" type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>uploadCompanyLogo(me.company_id!,e.target.files?.[0])}/>}</div></section>}
      {tab==='users' && canCreateUsers && (editingUserId!==null
        ? (()=>{const u=users.find(item=>item.id===editingUserId);
            return u?<UserEditPage key={u.id} user={u} companies={companies} currentUserId={me.id} lang={lang}
              onClose={()=>setEditingUserId(null)} onSave={saveUserEdit}/>
              :<section className="panel"><p>{lang==='en'?'User not found.':'تعذر العثور على المستخدم.'}</p><button type="button" className="refresh" onClick={()=>setEditingUserId(null)}>{lang==='en'?'Back to users':'العودة للمستخدمين'}</button></section>;
          })()
        :<section className="panel">
        <div className="panel-heading"><div><h3>{lang==='en'?'Users & Access':'المستخدمون والصلاحيات'}</h3><p>{lang==='en'?'Click any account to edit all supported fields together.':'اضغط على المستخدم لفتح صفحة واحدة لتعديل الحقول المسموح بها.'}</p></div></div>
        <details className="nuqati-help" style={{margin:"8px 0 14px"}}><summary style={{cursor:"pointer",color:"#b5d86c",fontWeight:600}}>★ {lang==='en'?'More details':'المزيد من التفاصيل'}</summary><p style={{marginTop:8}}>{lang==='en'?'Create a user and automatically send an activation invitation. Select any existing user below to resend an invitation or send a sign-in reminder. Select a user to open the complete editor and save all changes once.':'إنشاء مستخدم وإرسال دعوة تفعيل تلقائيًا. يمكنك اختيار مستخدم مسجل لإعادة إرسال الدعوة أو تذكير الدخول. اضغط على المستخدم لفتح صفحة تعديل كاملة وحفظ التغييرات مرة واحدة.'}</p></details>
        <details className="nq-ve-add-form" style={{marginBottom:20}}><summary>{lang==='en'?'+ Add user and send invitation':'+ إضافة مستخدم وإرسال دعوة'}</summary>
        <form className="entry-form" onSubmit={submitAccount}>
          <label>{lang==='en'?'Full name':'الاسم الكامل'}<input required minLength={2} value={accountForm.full_name} onChange={e=>setAccountForm({...accountForm,full_name:e.target.value})}/></label>
          <label>{lang==='en'?'Email':'البريد الإلكتروني'}<input type="email" required value={accountForm.email} onChange={e=>setAccountForm({...accountForm,email:e.target.value})}/></label>
          <label>{lang==='en'?'Role':'الدور'}<select value={accountForm.role} onChange={e=>setAccountForm({...accountForm,role:e.target.value})}>{(me.role==='super_admin'?['company_admin','fleet_manager']:['fleet_manager']).map(r=><option key={r} value={r}>{lang==='en'?r:({company_admin:'مدير الشركة',fleet_manager:'مدير الأسطول'} as Record<string,string>)[r]||r}</option>)}</select></label>
          <button className="primary" disabled={!activeCompanyId}>{lang==='en'?'Create user + Send invitation':'إنشاء مستخدم وإرسال الدعوة'}</button>
        </form>
        </details>
        <div className="nq-selection-toolbar"><div className="nq-selection-heading"><strong>{lang==='en'?'Registered users':'المستخدمون المسجلون'}</strong><small>{lang==='en'?'Only the company selected in the top bar is displayed.':'تُعرض فقط حسابات الشركة المحددة في الشريط العلوي.'}</small></div><div className="nq-selection-controls"><button type="button" className="refresh" onClick={()=>setSelectedInviteUserId('')}>{lang==='en'?'Clear':'مسح'}</button></div></div>
        {usersViewCompany?<><h3>{lang==='en'?'Registered users':'المستخدمون المسجلون'} · {visibleUserRows.length}</h3>
        <div className="entry-form">
          <label>Select user to email
            <select value={selectedInviteUserId} onChange={e=>setSelectedInviteUserId(e.target.value)}>
              <option value="">{lang==='en'?'Choose registered user':'اختر مستخدمًا مسجلًا'}</option>
              {visibleUserRows.filter(u=>u.role!=='driver' && !u.email.endsWith('@login.nuqati.invalid')).map(u=><option key={u.id} value={u.id}>{u.full_name} — {u.email} — {u.is_active?(lang==='en'?'Active':'نشط'):(lang==='en'?'Pending':'بانتظار التفعيل')}</option>)}
            </select>
          </label>
          <button type="button" className="primary" disabled={!selectedInviteUserId} onClick={sendSelectedUserEmail}>{lang==='en'?'Send invitation / Reminder':'إرسال دعوة / تذكير'}</button>
          <button type="button" className="refresh" onClick={loadUsers}>{lang==='en'?'Refresh users':'تحديث المستخدمين'}</button>
        </div>
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Name':'الاسم'}</th><th>{lang==='en'?'Email':'البريد الإلكتروني'}</th><th>{lang==='en'?'Role':'الدور'}</th><th>{lang==='en'?'Company':'الشركة'}</th><th>{lang==='en'?'Status':'الحالة'}</th><th>{lang==='en'?'Actions':'الإجراءات'}</th></tr></thead><tbody>
          {visibleUserRows.map(u=><tr key={u.id} className="nq-ve-row-clickable" onClick={()=>beginUserEdit(u)}>
            <td><button type="button" className="nq-ve-plate-link" onClick={e=>{e.stopPropagation();beginUserEdit(u);}}>{u.full_name}</button></td><td>{u.email}</td><td>{lang==='en'?u.role:({super_admin:'المدير العام',company_admin:'مدير الشركة',fleet_manager:'مدير الأسطول',driver:'سائق',representative:'ممثل',workshop_staff:'موظف الورشة'} as Record<string,string>)[u.role]||u.role}</td><td>{companies.find(c=>c.id===u.company_id)?.name||(lang==='en'?'Workshop':'الورشة')}</td><td>{u.is_active?(lang==='en'?'Active':'نشط'):(lang==='en'?'Disabled / Pending':'معطل / بانتظار التفعيل')}</td>
            <td>{me.role==='super_admin'&&<button type="button" data-nq-action="edit" className="refresh" onClick={e=>{e.stopPropagation();beginUserEdit(u);}}>{lang==='en'?'Edit all fields':'تعديل جميع الحقول'}</button>}{!u.is_active&&<button type="button" className="refresh" onClick={e=>{e.stopPropagation();void resendInvite(u.id);}}>{lang==='en'?'Resend invitation':'إعادة إرسال الدعوة'}</button>}{u.id!==me.id&&<button type="button" className="refresh" onClick={e=>{e.stopPropagation();void deactivate(u.id);}}>{lang==='en'?'Deactivate':'تعطيل'}</button>}{me.role==='super_admin'&&u.id!==me.id&&<button type="button" className="refresh" onClick={e=>{e.stopPropagation();void adminDelete('users',u.id);}}>{lang==='en'?'Delete':'حذف'}</button>}</td>
          </tr>)}
        </tbody></table></div>{!visibleUserRows.length&&<div className="nq-selection-empty">{lang==='en'?'No registered users for this selection.':'لا يوجد مستخدمون لهذا الاختيار.'}</div>}</>:<div className="nq-selection-empty">{lang==='en'?'Choose a company to display registered accounts.':'اختر الشركة لعرض الحسابات المسجلة.'}</div>}
      </section>)}
      {tab==='safety'&&<section className="panel nuqati-geo-page">
        <div className="panel-heading"><div><h2>{lang==='en'?'Geofence Location':'مواقع المناطق الجغرافية'}</h2><p>{lang==='en'?'View named zones, choose their vehicles, and create new geofences on the map.':'عرض المناطق بأسمائها وتحديد المركبات وإنشاء مناطق جديدة على الخريطة.'}</p></div><button className="refresh" type="button" onClick={loadPhase4}>{lang==='en'?'Refresh':'تحديث'}</button></div>
        {me.role==='super_admin'&&<div className="nuqati-geo-company"></div>}
        {phase4Cid?<>
          <div className="nuqati-geo-workspace" dir={lang==='ar'?'rtl':'ltr'}>
            <aside className="nuqati-geo-sidebar">
              <h3>{lang==='en'?'Created geofences':'المناطق المنشأة'} ({phase4Zones.length})</h3>
              <div className="nuqati-geo-list">{phase4Zones.map(zone=><button type="button" key={zone.id} className={'nuqati-geo-list-item '+(zone.id===selectedGeoId?'active':'')} onClick={()=>openGeo(zone)}><strong>📍 {zone.name}</strong><small>{zone.shape&&zone.shape!=='circle'?(zone.shape==='rectangle'?(lang==='en'?'Rectangle':'مستطيل'):(lang==='en'?'Polygon':'مضلع')):`${Math.round(zone.radius_m)} m`} · {zone.mode}</small><small>{zone.vehicle_ids==null?(lang==='en'?'All company vehicles':'كل مركبات الشركة'):`${zone.vehicle_ids.length} ${lang==='en'?'selected vehicles':'مركبات محددة'}`}</small></button>)}</div>
              {!phase4Zones.length&&<p>{lang==='en'?'No geofences created yet.':'لا توجد مناطق حتى الآن.'}</p>}
            </aside>
            <div className="nuqati-geo-map"><GeofenceLocationsMap language={lang} zones={phase4Zones} focusedId={selectedGeoId} latitude={zoneForm.latitude?Number(zoneForm.latitude):null} longitude={zoneForm.longitude?Number(zoneForm.longitude):null} radius={Number(zoneForm.radius_m)||200} draftShape={zoneForm.shape} draftPoints={zonePoints} onDraftPoint={(lat,lng)=>setZonePoints(old=>{const point:[number,number]=[lat,lng];return zoneForm.shape==='rectangle'?(old.length>=2?[point]:[...old,point]):old.length>=60?old:[...old,point]})} onSelect={(latitude,longitude)=>setZoneForm(prev=>({...prev,latitude:latitude.toFixed(6),longitude:longitude.toFixed(6)}))} onZoneClick={id=>{const zone=phase4Zones.find(z=>z.id===id);if(zone)openGeo(zone);}}/></div>
          </div>
          {(me.role==='super_admin'||me.role==='company_admin')&&<form className="nuqati-geo-form" onSubmit={addZone}>
            <h3>{lang==='en'?'Create a geofence':'إنشاء منطقة جغرافية'}</h3>
            <div className="entry-form"><label>{lang==='en'?'Zone name':'اسم المنطقة'}<input required value={zoneForm.name} onChange={e=>setZoneForm({...zoneForm,name:e.target.value})}/></label><label>{lang==='en'?'Shape':'الشكل'}<select value={zoneForm.shape} onChange={e=>{setZoneForm({...zoneForm,shape:e.target.value as 'circle'|'rectangle'|'polygon'});setZonePoints([])}}><option value="circle">{lang==='en'?'Circle':'دائرة'}</option><option value="rectangle">{lang==='en'?'Rectangle':'مستطيل'}</option><option value="polygon">{lang==='en'?'Custom polygon':'مضلع حر'}</option></select></label>{zoneForm.shape==='circle'&&<label>{lang==='en'?'Radius (m)':'نصف القطر (م)'}<input required type="number" min="50" max="20000" value={zoneForm.radius_m} onChange={e=>setZoneForm({...zoneForm,radius_m:e.target.value})}/></label>}<label>{lang==='en'?'Mode':'نوع المنطقة'}<select value={zoneForm.mode} onChange={e=>setZoneForm({...zoneForm,mode:e.target.value})}><option value="restricted">Restricted</option><option value="monitor">Monitor</option></select></label><label>{lang==='en'?'Speed limit (km/h, optional)':'حد السرعة (اختياري)'}<input type="number" min="10" max="200" value={zoneForm.speed_limit_kmh} onChange={e=>setZoneForm({...zoneForm,speed_limit_kmh:e.target.value})}/></label><button className="primary" disabled={zoneForm.shape==='circle'?(!zoneForm.latitude||!zoneForm.longitude):(zoneForm.shape==='rectangle'?zonePoints.length!==2:zonePoints.length<3)}>{lang==='en'?'Add zone':'إضافة المنطقة'}</button>{zoneForm.shape!=='circle'&&<><button type="button" className="refresh" disabled={!zonePoints.length} onClick={()=>setZonePoints(p=>p.slice(0,-1))}>{lang==='en'?'Undo point':'تراجع عن نقطة'}</button><button type="button" className="refresh" onClick={()=>setZonePoints([])}>{lang==='en'?'Clear corners':'مسح الزوايا'}</button></>}</div>
            <small>{zoneForm.shape!=='circle'?`${zonePoints.length} ${lang==='en'?'corners selected':'زوايا محددة'}`:zoneForm.latitude&&zoneForm.longitude?`${zoneForm.latitude}, ${zoneForm.longitude}`:(lang==='en'?'Click on the map to select the new zone center.':'اضغط على الخريطة لتحديد مركز المنطقة الجديدة.')}</small>
          </form>}
        </>:<div className="empty">{lang==='en'?'Select a company to show its geofences.':'اختر الشركة لعرض مناطقها.'}</div>}
        {showGeoDetails&&(()=>{const zone=phase4Zones.find(z=>z.id===selectedGeoId);if(!zone)return null;const companyVehicles=vehicles.filter(v=>v.company_id===Number(phase4Cid));return <div className="nuqati-geo-modal-backdrop" role="presentation" onClick={()=>setShowGeoDetails(false)}><div className="nuqati-geo-modal" role="dialog" aria-modal="true" aria-label={zone.name} onClick={e=>e.stopPropagation()}><div className="panel-heading"><h3>{zone.name}</h3><button type="button" className="refresh" onClick={()=>setShowGeoDetails(false)}>✕</button></div><GeofenceLocationsMap language={lang} zones={[zone]} focusedId={zone.id} latitude={null} longitude={null} radius={zone.radius_m} onSelect={()=>{}} onZoneClick={()=>{}}/><p>{zone.mode} · {zone.shape&&zone.shape!=='circle'?zone.shape:`${zone.radius_m} m`} · {zone.latitude.toFixed(5)}, {zone.longitude.toFixed(5)}</p><h3>{lang==='en'?'Vehicles included in this geofence':'المركبات المشمولة في هذه المنطقة'}</h3><label className="nuqati-geo-check"><input disabled={me.role!=='super_admin'&&me.role!=='company_admin'} type="checkbox" checked={geoSelection===null} onChange={e=>setGeoSelection(e.target.checked?null:[])}/>{lang==='en'?'All company vehicles':'جميع مركبات الشركة'}</label><div className="nuqati-geo-vehicle-list">{companyVehicles.map(v=><label key={v.id} className="nuqati-geo-check"><input disabled={geoSelection===null||(me.role!=='super_admin'&&me.role!=='company_admin')} type="checkbox" checked={geoSelection===null||geoSelection.includes(v.id)} onChange={e=>setGeoSelection(prev=>e.target.checked?[...(prev||[]),v.id]:(prev||[]).filter(id=>id!==v.id))}/>{v.plate_number} · {v.make_model}</label>)}</div>{(me.role==='super_admin'||me.role==='company_admin')&&<div className="nuqati-geo-actions"><button className="primary" type="button" disabled={geoSelection!==null&&geoSelection.length===0} onClick={saveZoneVehicles}>{lang==='en'?'Save assigned vehicles':'حفظ المركبات'}</button><button className="refresh" type="button" onClick={async()=>{if(!window.confirm(lang==='en'?'Delete this geofence?':'حذف هذه المنطقة؟'))return;await deleteZone(zone.id);setShowGeoDetails(false);}}>{lang==='en'?'Delete zone':'حذف المنطقة'}</button></div>}</div></div>})()}
      </section>}
      {tab==='assistance' && <section className="panel"><h3>{lang==='en'?'Workshop Assistance Requests':'طلبات المساعدة من الورشة'}</h3><p>{lang==='en'?'Driver reports, phone advice, technician and towing dispatch. Coordinates appear only if the driver explicitly shared them.':'بلاغات السائقين والاستشارات والإصلاح والسطحات. الموقع يظهر بموافقة السائق فقط.'}</p>
      {me.role==='super_admin'&&<details className="nq-ve-add-form"><summary>{lang==='en'?'Workshop contact numbers':'أرقام الاتصال بالورشة'}</summary><div className="entry-form">{(['manager','mechanic','electrician','towing'] as const).map(k=><label key={k}>{k}<input value={assistPhones[k]} onChange={e=>setAssistPhones({...assistPhones,[k]:e.target.value})} placeholder="+966..."/></label>)}<button type="button" className="primary" onClick={saveAssistPhones}>{lang==='en'?'Save workshop phones':'حفظ أرقام الورشة'}</button></div></details>}
      <div className="nq-selection-toolbar"><div className="nq-selection-heading"><strong>{lang==='en'?'Filter workshop requests':'تصفية طلبات الورشة'}</strong><small>{lang==='en'?'Using the active company; dates use Saudi Arabia time.':'حسب الشركة الحالية والتوقيت السعودي.'}</small></div><div className="nq-selection-controls"><label>{lang==='en'?'From date':'من تاريخ'}<input aria-label={lang==='en'?'From date':'من تاريخ'} type="date" value={assistFrom} max={assistTo||undefined} onChange={e=>setAssistFrom(e.target.value)}/></label><label>{lang==='en'?'To date':'إلى تاريخ'}<input aria-label={lang==='en'?'To date':'إلى تاريخ'} type="date" value={assistTo} min={assistFrom||undefined} onChange={e=>setAssistTo(e.target.value)}/></label><button type="button" className="refresh" onClick={()=>{setAssistFrom('');setAssistTo('');setAssistSearch('');setAssistStatus('all');}}>{lang==='en'?'Clear':'مسح'}</button></div></div>
      {assistCompany?<><div className="entry-form"><label>{lang==='en'?'Search driver, plate, issue':'بحث السائق أو اللوحة أو المشكلة'}<input value={assistSearch} onChange={e=>setAssistSearch(e.target.value)}/></label><label>{lang==='en'?'Status':'الحالة'}<select value={assistStatus} onChange={e=>setAssistStatus(e.target.value)}>{['all','new','assigned','in_progress','awaiting_parts','at_workshop','resolved','cancelled'].map(k=><option key={k} value={k}>{lang==='en'?({all:'All statuses',new:'New',assigned:'Assigned',in_progress:'In progress',awaiting_parts:'Awaiting parts',at_workshop:'At workshop',resolved:'Resolved',cancelled:'Cancelled'} as Record<string,string>)[k]:({all:'جميع الحالات',new:'جديد',assigned:'تم التعيين',in_progress:'قيد المعالجة',awaiting_parts:'بانتظار قطع الغيار',at_workshop:'في الورشة',resolved:'تم الحل',cancelled:'ملغي'} as Record<string,string>)[k]}</option>)}</select></label><button type="button" className="refresh" onClick={loadAssistance}>{lang==='en'?'Refresh requests':'تحديث الطلبات'}</button></div>
      <div className="nq-workshop-count"><strong>{visibleAssistRows.length}</strong><span>{lang==='en'?'Matching requests':'الطلبات المطابقة'}</span><small>{companies.find(c=>String(c.id)===assistCompany)?.name||''}</small></div>
      <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'ID / Date':'الرقم / التاريخ'}</th><th>{lang==='en'?'Driver / Vehicle':'السائق / المركبة'}</th><th>{lang==='en'?'Issue':'البلاغ'}</th><th>{lang==='en'?'Shared GPS':'الموقع المشترك'}</th><th>{lang==='en'?'Status':'الحالة'}</th><th>{lang==='en'?'Advice / resolution':'الملاحظة / الحل'}</th><th>{lang==='en'?'Save':'حفظ'}</th></tr></thead><tbody>{visibleAssistRows.map(t=><tr key={t.id}><td>#{t.id}<br/>{new Date(t.created_at).toLocaleString(lang==='en'?'en-GB':'ar-SA',{timeZone:'Asia/Riyadh'})}</td><td>{t.driver_name}<br/>{t.plate_number||'—'}</td><td><strong>{t.category}</strong><br/>{t.description}</td><td>{t.latitude!=null&&t.longitude!=null?<a target="_blank" rel="noopener noreferrer" href={`https://www.google.com/maps?q=${t.latitude},${t.longitude}`}>{lang==='en'?'View location':'عرض الموقع'}</a>:(lang==='en'?'Not shared':'غير مشارك')}</td><td><select value={t.status} onChange={e=>setAssistTickets(all=>all.map(x=>x.id===t.id?{...x,status:e.target.value}:x))}>{['new','assigned','in_progress','awaiting_parts','at_workshop','resolved','cancelled'].map(v=><option key={v} value={v}>{lang==='en'?({new:'New',assigned:'Assigned',in_progress:'In progress',awaiting_parts:'Awaiting parts',at_workshop:'At workshop',resolved:'Resolved',cancelled:'Cancelled'} as Record<string,string>)[v]:({new:'جديد',assigned:'تم التعيين',in_progress:'قيد المعالجة',awaiting_parts:'بانتظار قطع الغيار',at_workshop:'في الورشة',resolved:'تم الحل',cancelled:'ملغي'} as Record<string,string>)[v]}</option>)}</select></td><td><textarea rows={2} value={t.resolution_note} onChange={e=>setAssistTickets(all=>all.map(x=>x.id===t.id?{...x,resolution_note:e.target.value}:x))}/></td><td><button type="button" className="refresh" onClick={()=>updateAssistTicket(t)}>{lang==='en'?'Save':'حفظ'}</button></td></tr>)}</tbody></table></div>{!visibleAssistRows.length&&<div className="nq-selection-empty">{lang==='en'?'No workshop requests match this company and date range.':'لا توجد طلبات ورشة مطابقة للشركة والفترة المحددة.'}</div>}</>:<div className="nq-selection-empty">{lang==='en'?'Select a company to display its workshop requests.':'اختر الشركة لعرض طلبات الورشة الخاصة بها.'}</div>}</section>}
      {tab==='privacy-audit'&&<div className="nq-privacy-header" dir={lang==='ar'?'rtl':'ltr'}>
        <span className="nq-config-eyebrow">NUQATI / PRIVACY & GOVERNANCE</span>
        <h2>{lang==='en'?'Privacy & Device Audit':'تدقيق الخصوصية والأجهزة'}</h2>
        <p>{lang==='en'?'Select an audit area to review one topic at a time, with clear filters and export options.':'اختر قسم التدقيق لعرض موضوع واحد في كل مرة مع فلاتر وخيارات تصدير واضحة.'}</p>
        <nav className="nq-privacy-nav" aria-label={lang==='en'?'Privacy audit sections':'أقسام تدقيق الخصوصية'}>
          {([['requests','01',lang==='en'?'Privacy approvals':'موافقات الخصوصية'],['lifecycle','02',lang==='en'?'Device & access events':'أحداث الجهاز والدخول'],['tracking','03',lang==='en'?'Tracking heartbeat':'حالة التتبع'],['mode','04',lang==='en'?'Privacy changes':'تغييرات الخصوصية'],['notifications','05',lang==='en'?'Notifications':'الإشعارات'],['camera','06',lang==='en'?'Camera observations':'ملاحظات الكاميرا']] as const).map(([id,num,name])=><button key={id} type="button" aria-pressed={privacySection===id} className={privacySection===id?'is-active':''} onClick={()=>setPrivacySection(id)}><span>{num}</span><strong>{name}</strong></button>)}
        </nav>
      </div>}
      {tab==='privacy-audit' && privacySection==='requests' && (me.role==='super_admin'||me.role==='company_admin'||me.role==='fleet_manager') && <section className="panel nq-privacy-panel">
       <div className="panel-heading"><div><h3>{lang==='en'?'Privacy Mode approval requests':'طلبات الموافقة على وضع الخصوصية'}</h3><p>{lang==='en'?'Tracking continues until the driver receives approval.':'يستمر التتبع حتى وصول الموافقة إلى السائق.'}</p></div><button type="button" className="refresh" onClick={loadPrivacyRequests}>{lang==='en'?'Refresh requests':'تحديث الطلبات'}</button></div>
       <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Company':'الشركة'}</th><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Requested':'تاريخ الطلب'}</th><th>{lang==='en'?'Status':'الحالة'}</th><th>{lang==='en'?'Action':'الإجراء'}</th></tr></thead><tbody>{privacyRequests.filter(r=>String(r.company_id)===activeCompanyId).map(r=><tr key={r.id}><td>{r.company_name}</td><td>{r.driver_name}</td><td>{new Date(r.requested_at).toLocaleString()}</td><td>{r.status}</td><td>{r.status==='pending'?<><button type="button" className="refresh" onClick={()=>privacyRequestAction(r.id,'approve')}>{lang==='en'?'Approve':'موافقة'}</button>{' '}<button type="button" className="refresh" onClick={()=>privacyRequestAction(r.id,'reject')}>{lang==='en'?'Reject':'رفض'}</button></>:['approved','active'].includes(r.status)?<button type="button" className="refresh" onClick={()=>privacyRequestAction(r.id,'revoke')}>{lang==='en'?'Revoke':'إلغاء الموافقة'}</button>:null}</td></tr>)}</tbody></table></div>
       {privacyRequests.filter(r=>String(r.company_id)===activeCompanyId).length===0&&<p>{lang==='en'?'No requests found.':'لا توجد طلبات.'}</p>}
       {privacyError&&<p role="alert">{privacyError}</p>}
      </section>}
      {tab==='privacy-audit' && privacySection!=='requests' && <section className="panel nq-privacy-panel">
        {privacySection==='lifecycle'&&(me.role==='super_admin'||me.role==='company_admin'||me.role==='fleet_manager')&&<LifecyclePrivacyAudit request={request} lang={lang} drivers={drivers} companies={companies} companyId={activeCompanyId} isSuperAdmin={false}/>}
         {privacySection==='tracking'&&<><h3>{lang==='en'?'Driver device tracking status':'حالة تتبع أجهزة السائقين'}</h3>
        <p>{lang==='en'?'Latest background-service heartbeat. A stale heartbeat means status is unknown, not that tracking has stopped.':'آخر إشارة من خدمة التتبع الخلفية. الإشارة القديمة تعني أن الحالة غير معروفة ولا تثبت توقف التتبع.'}</p>
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Screen':'الشاشة'}</th><th>{lang==='en'?'Trip':'الرحلة'}</th><th>{lang==='en'?'GPS fix age':'عمر قراءة GPS'}</th><th>{lang==='en'?'Last server heartbeat':'آخر اتصال بالخادم'}</th></tr></thead><tbody>{trackingHeartbeats.filter(r=>String(r.company_id)===activeCompanyId).map(r=>{const fresh=Date.now()-new Date(r.received_at).getTime()<90000;return <tr key={r.driver_id}><td>{drivers.find(d=>d.id===r.driver_id)?.full_name||`#${r.driver_id}`}</td><td>{!fresh?(lang==='en'?'Unknown (stale)':'غير معروف (قديم)'):r.screen_state==='locked'?(lang==='en'?'Locked':'مقفلة'):r.screen_state==='unlocked'?(lang==='en'?'Unlocked':'مفتوحة'):(lang==='en'?'Unknown':'غير معروف')}</td><td>{fresh?(r.trip_active?(lang==='en'?'Active':'نشطة'):(lang==='en'?'Inactive':'غير نشطة')):'—'}</td><td>{fresh&&r.gps_fix_age_s!=null?`${r.gps_fix_age_s}s`:'—'}</td><td>{new Date(r.received_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td></tr>})}</tbody></table>{!trackingHeartbeats.length&&<div className="empty">{lang==='en'?'No device heartbeats received yet.':'لم تصل إشارات من الأجهزة بعد.'}</div>}</div>

        </>}
         {privacySection==='mode'&&<><div className="panel-heading"><div><h3>{lang==='en'?'Privacy Mode Audit':'سجل تفعيل وإيقاف وضع الخصوصية'}</h3><p>{lang==='en'?'Driver privacy selections, without location or route information.':'سجل اختيارات السائق لوضع الخصوصية دون حفظ الموقع أو مسار الرحلة.'}</p></div></div>
        {auditControls(privacyFilter,setPrivacyFilter,setPrivacyApplied,true)}
        <button type="button" className="refresh" disabled={privacyLoading} onClick={loadPrivacyAudit}><RefreshCw size={16}/>{lang==='en'?'Refresh audit data':'تحديث بيانات السجل'}</button>{' '}
        <button type="button" className="refresh" disabled={!privacyVisible.length} onClick={exportPrivacyAudit}>{lang==='en'?'Export selected CSV':'تصدير النتائج CSV'}</button>
        {privacyError&&<div className="notice" role="alert">{lang==='en'?'Unable to load privacy audit: ':'تعذر تحميل سجل الخصوصية: '}{privacyError}</div>}
        <p>{privacyApplied?(lang==='en'?`Showing ${privacyVisible.length} matching privacy records.`:`عرض ${privacyVisible.length} سجل خصوصية مطابق.`):(lang==='en'?'Select a company and driver, then Search to display records.':'اختر الشركة والسائق ثم اضغط بحث لعرض السجلات.')}</p>
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Vehicle':'السيارة'}</th><th>{lang==='en'?'Company':'الشركة'}</th><th>{lang==='en'?'Action':'الإجراء'}</th><th>{lang==='en'?'Selected on phone':'وقت الاختيار على الهاتف'}</th><th>{lang==='en'?'Received by server':'وقت الاستلام بالخادم'}</th><th>{lang==='en'?'Event ID':'معرّف الحدث'}</th></tr></thead><tbody>{privacyVisible.map(r=><tr key={r.event_id}><td>{drivers.find(d=>d.id===r.driver_id)?.full_name||`#${r.driver_id}`}</td><td>{r.vehicle_id==null?'—':vehicles.find(v=>v.id===r.vehicle_id)?.plate_number||`#${r.vehicle_id}`}</td><td>{companies.find(c=>c.id===r.company_id)?.name||`#${r.company_id}`}</td><td><span className="status">{r.privacy_enabled?(lang==='en'?'Privacy ON':'الخصوصية مفعّلة'):(lang==='en'?'Privacy OFF':'الخصوصية متوقفة')}</span></td><td>{new Date(r.selected_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td><td>{new Date(r.received_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td><td title={r.event_id}>{r.event_id.slice(0,14)}…</td></tr>)}</tbody></table>{!privacyLoading&&!privacyError&&!privacyVisible.length&&<div className="empty">{privacyApplied?(lang==='en'?'No matching privacy events.':'لا توجد أحداث خصوصية مطابقة.'):(lang==='en'?'Select a driver and search.':'اختر السائق ثم ابحث.')}</div>}</div>
        </>}
         {privacySection==='notifications'&&<><h3 style={{marginTop:24}}>{lang==='en'?'Driving notification settings audit':'سجل إعدادات إشعارات القيادة'}</h3>
        <p>{lang==='en'?'Most recent changes submitted by drivers (offline changes appear after synchronization).':'آخر تغييرات الإشعارات المرسلة من السائقين (تظهر التغييرات دون اتصال بعد المزامنة).'}</p>
        {auditControls(notificationFilter,setNotificationFilter,setNotificationApplied,true)}
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Vehicle':'السيارة'}</th><th>{lang==='en'?'Company':'الشركة'}</th><th>{lang==='en'?'Notifications':'الإشعارات'}</th><th>{lang==='en'?'Selected on phone':'وقت الاختيار'}</th><th>{lang==='en'?'Received':'وقت الاستلام'}</th></tr></thead><tbody>{notificationVisible.map(r=><tr key={r.event_id}><td>{drivers.find(d=>d.id===r.driver_id)?.full_name||`#${r.driver_id}`}</td><td>{r.vehicle_id==null?'—':vehicles.find(v=>v.id===r.vehicle_id)?.plate_number||`#${r.vehicle_id}`}</td><td>{companies.find(c=>c.id===r.company_id)?.name||`#${r.company_id}`}</td><td><span className="status">{r.notifications_enabled?(lang==='en'?'Enabled':'مفعّلة'):(lang==='en'?'Disabled':'متوقفة')}</span></td><td>{new Date(r.selected_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td><td>{new Date(r.received_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td></tr>)}</tbody></table>{!notificationVisible.length&&<div className="empty">{notificationApplied?(lang==='en'?'No matching notification changes.':'لا توجد تغييرات إشعارات مطابقة.'):(lang==='en'?'Select a driver and search.':'اختر السائق ثم ابحث.')}</div>}</div>
        </>}
         {privacySection==='camera'&&<><h4>{lang==='en'?'Driving camera activity observations':'ملاحظات نشاط الكاميرا أثناء القيادة'}</h4>
        <p>{lang==='en'?'Camera busy is not proof of a video call. No camera frames, photos or audio are uploaded.':'انشغال الكاميرا لا يثبت إجراء مكالمة فيديو. لا يتم رفع صور أو فيديو أو صوت.'}</p>
        {auditControls(cameraFilter,setCameraFilter,setCameraApplied,false)}
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Vehicle':'السيارة'}</th><th>{lang==='en'?'Observation':'الملاحظة'}</th><th>{lang==='en'?'Speed km/h':'السرعة كم/س'}</th><th>{lang==='en'?'Time':'الوقت'}</th></tr></thead><tbody>{cameraVisible.map(r=><tr key={r.event_id}><td>{drivers.find(d=>d.id===r.driver_id)?.full_name||`#${r.driver_id}`}</td><td>{vehicles.find(v=>v.id===r.vehicle_id)?.plate_number||'—'}</td><td>{lang==='en'?'Possible camera use':'احتمال استخدام الكاميرا'}</td><td>{r.speed_kmh?.toFixed(0)??'—'}</td><td>{new Date(r.observed_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td></tr>)}</tbody></table>{!cameraVisible.length&&<div className="empty">{cameraApplied?(lang==='en'?'No matching camera observations.':'لا توجد ملاحظات كاميرا مطابقة.'):(lang==='en'?'Select a driver and search.':'اختر السائق ثم ابحث.')}</div>}</div>
        </>}
        <div className="tip">{lang==='en'?'Audit entries record privacy selection only. No private-trip GPS positions are stored in this audit.':'يسجل هذا السجل اختيار وضع الخصوصية فقط ولا يخزن مواقع GPS للرحلات الخاصة.'}</div>
      </section>}
      {tab==='configuration'&&<section className="panel nq-config" dir={lang==='ar'?'rtl':'ltr'}>
        <div className="nq-config-header"><div><span className="nq-config-eyebrow">NUQATI / FLEET SAFETY</span><h2>{lang==='en'?'Safety & Event Configuration':'إعدادات السلامة والأحداث'}</h2><p>{lang==='en'?'Configure detection thresholds, driver scores, GPS quality and policy delivery from one place.':'اضبط حدود اكتشاف الأحداث وتقييم السائقين وجودة GPS وتوزيع السياسات من مكان واحد.'}</p></div><div className="nq-config-actions"><button type="button" className="refresh" disabled={!configCid} onClick={()=>void loadConfiguration()}><RefreshCw size={16}/>{lang==='en'?'Reload settings':'إعادة تحميل الإعدادات'}</button></div></div>
        <div className="nq-config-company"><strong>{lang==='en'?'Your company settings':'إعدادات شركتك'}</strong><span>{lang==='en'?'Changes apply only to the selected company. Driver apps receive policies during synchronization.':'تُطبق التغييرات على الشركة المختارة فقط، وتصل لتطبيقات السائقين عند المزامنة.'}</span></div>
        {configCid?<><nav className="nq-config-nav" aria-label={lang==='en'?'Configuration sections':'أقسام الإعدادات'}>{([['cfg-thresholds','01',lang==='en'?'Event thresholds':'حدود الأحداث'],['cfg-scoring','02',lang==='en'?'Driver scoring':'تقييم السائقين'],['cfg-detection','03',lang==='en'?'Detection & GPS':'الاكتشاف وGPS'],['cfg-risk','04',lang==='en'?'Risk levels':'مستويات المخاطر'],['cfg-delivery','05',lang==='en'?'Delivery status':'حالة الاستلام']] as const).map(([id,n,title])=><button type="button" key={id} className={configSection===id?'nq-config-active':''} onClick={()=>setConfigSection(configSection===id?'':id)} aria-pressed={configSection===id}><span>{n}</span>{title}</button>)}</nav>
        {!configSection&&<div className="nq-selection-empty">{lang==='en'?'Choose a configuration category above. Only that section will open.':'اختر قسم الإعدادات من الأعلى، وسيُعرض القسم المختار فقط.'}</div>}
        {configSection==='cfg-thresholds'&&(me.role==='super_admin'||me.role==='company_admin')&&<section id="cfg-thresholds" className="nq-config-section"><header><div><span className="nq-config-eyebrow">01 / EVENTS</span><h3>{lang==='en'?'Driving event thresholds':'حدود أحداث القيادة'}</h3><p>{lang==='en'?'Set the trigger for each event. Lower acceleration values detect gentler changes. All acceleration thresholds are in km/h per second.':'حدد مستوى اكتشاف كل حدث. القيم الأقل للتسارع ترصد تغيّرات أخف. جميع قيم التسارع بوحدة كم/ساعة لكل ثانية.'}</p></div></header><div className="nq-threshold-grid">{([
          ['speed',lang==='en'?'Overspeeding':'تجاوز السرعة',lang==='en'?'Absolute speed limit':'الحد المطلق للسرعة',speedThreshold,setSpeedThreshold,'km/h',20,200,1],
          ['accel',lang==='en'?'Harsh acceleration':'التسارع العنيف',lang==='en'?'Rapid increase in speed':'زيادة سريعة في السرعة',accelThreshold,setAccelThreshold,'km/h/s',3.6,36,0.1],
          ['brake',lang==='en'?'Harsh braking':'الفرملة العنيفة',lang==='en'?'Rapid decrease in speed':'انخفاض سريع في السرعة',brakeThreshold,setBrakeThreshold,'km/h/s',3.6,36,0.1],
          ['aggressive-accel',lang==='en'?'Severe acceleration':'التسارع الشديد جداً',lang==='en'?'Higher severity threshold':'حد الحدث شديد الخطورة',aggressiveAccel,setAggressiveAccel,'km/h/s',3.6,72,0.1],
          ['aggressive-brake',lang==='en'?'Severe braking':'الفرملة الشديدة جداً',lang==='en'?'Higher severity threshold':'حد الحدث شديد الخطورة',aggressiveBrake,setAggressiveBrake,'km/h/s',3.6,72,0.1]
        ] as const).map(([key,title,desc,value,setValue,unit,min,max,step])=><label className="nq-threshold-card" key={key}><strong>{title}</strong><small>{desc}</small><div className="nq-input-unit"><input aria-label={title} type="number" min={min} max={max} step={step} value={value} onChange={e=>setValue(e.target.value)}/><span>{unit}</span></div>{unit==='km/h/s'&&<small>{lang==='en'?'Equivalent:':'ما يعادل:'} {Number.isFinite(Number(value))?(Number(value)/3.6).toFixed(2):'—'} m/s²</small>}</label>)}</div><div className="nq-config-savebar"><small>{lang==='en'?'Save threshold changes to publish this company policy.':'احفظ تعديلات الحدود لنشر سياسة هذه الشركة.'}</small><button type="button" className="primary" disabled={!configCid||!speedThreshold||!accelThreshold||!brakeThreshold||!aggressiveAccel||!aggressiveBrake||Number(aggressiveAccel)<Number(accelThreshold)||Number(aggressiveBrake)<Number(brakeThreshold)} onClick={saveSpeed}>{lang==='en'?'Save event thresholds':'حفظ حدود الأحداث'}</button></div></section>}
        {configSection==='cfg-scoring'&&<section id="cfg-scoring" className="nq-config-section"><header><div><span className="nq-config-eyebrow">02 / SCORING</span><h3>{lang==='en'?'Driver score & penalties':'تقييم السائق والخصومات'}</h3><p>{lang==='en'?'Manage the official score weights and flexible RAG scoring independently.':'إدارة أوزان التقييم الرسمي ونظام تقييم RAG المرن بشكل مستقل.'}</p></div></header>
        {(me.role==='super_admin'||me.role==='company_admin')&&<FlexibleRagSettings request={request} companyId={configCid} lang={lang}/>}
        {(me.role==='super_admin'||me.role==='company_admin')&&<details style={{margin:'14px 0',padding:14,border:'1px solid #35495a',borderRadius:10}}><summary style={{cursor:'pointer',fontWeight:700}}>{lang==='en'?'Driver Safety Score · Configurable weights':'نقاط سلامة السائق · أوزان قابلة للتعديل'}</summary><button className="refresh" style={{marginTop:10}} onClick={()=>loadScorePolicy(configCid)}>{lang==='en'?'Load scoring policy':'تحميل سياسة التقييم'}</button>{scorePolicy&&scorePolicyCompany===configCid&&<div className="entry-form" style={{marginTop:12}}>{(['harsh_acceleration','harsh_braking','harsh_cornering','speeding','excessive_speeding'] as const).map(k=><label key={k}>{({harsh_acceleration:lang==='en'?'Harsh acceleration %':'التسارع العنيف %',harsh_braking:lang==='en'?'Harsh braking %':'الفرملة العنيفة %',harsh_cornering:lang==='en'?'Harsh cornering %':'الانعطاف الحاد %',speeding:lang==='en'?'Speeding %':'تجاوز السرعة %',excessive_speeding:lang==='en'?'Excessive speeding %':'تجاوز السرعة الشديد %'} as Record<string,string>)[k]}<input type="number" min="0" max="100" step="1" value={scorePolicy.weights[k]} onChange={e=>setScorePolicy((v:any)=>({...v,weights:{...v.weights,[k]:Number(e.target.value)}}))}/></label>)}<label>{lang==='en'?'Excessive speed margin (km/h)':'هامش تجاوز السرعة الشديد (كم/ساعة)'}<input type="number" min="5" max="100" value={scorePolicy.excessive_speed_margin_kmh} onChange={e=>setScorePolicy((v:any)=>({...v,excessive_speed_margin_kmh:Number(e.target.value)}))}/></label><label>{lang==='en'?'Events per 100 km for full category penalty':'الأحداث لكل ١٠٠ كم للخصم الكامل'}<input type="number" min="1" max="100" value={scorePolicy.events_per_100km_full_penalty} onChange={e=>setScorePolicy((v:any)=>({...v,events_per_100km_full_penalty:Number(e.target.value)}))}/></label><strong>{lang==='en'?'Total':'المجموع'}: {Object.values(scorePolicy.weights).reduce((a:number,b:any)=>a+Number(b),0)}%</strong><button className="primary" onClick={saveScorePolicy}>{lang==='en'?'Save score policy':'حفظ سياسة التقييم'}</button></div>}</details>}
        </section>}
        {configSection==='cfg-scoring'&&<details style={{margin:'14px 0',padding:14,border:'1px solid #35495a',borderRadius:10}}>
          <summary>{lang==='en'?'Speeding session durations':'مدد جلسات تجاوز السرعة'}</summary>
          <button className="refresh" disabled={speedSessionsLoading} onClick={loadSpeedSessions}>{lang==='en'?'Load sessions':'عرض الجلسات'}</button>
          <div style={{overflowX:'auto'}}><table><thead><tr><th>{lang==='en'?'Trip':'الرحلة'}</th><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Severity':'الخطورة'}</th><th>{lang==='en'?'Duration (s)':'المدة (ث)'}</th><th>{lang==='en'?'Ended':'النهاية'}</th></tr></thead><tbody>{speedSessions.map((s:any,i:number)=><tr key={i}><td>{s.trip_id}</td><td>{s.driver_id}</td><td>{s.severity==='aggressive'?(lang==='en'?'Aggressive':'شديد'):(lang==='en'?'Normal':'عادي')}</td><td>{Number(s.duration_seconds).toFixed(1)}</td><td>{new Date(s.ended_at).toLocaleString(lang==='en'?'en-GB':'ar-SA')}</td></tr>)}</tbody></table></div>
        </details>}
        {configSection==='cfg-detection'&&<section id="cfg-detection" className="nq-config-section"><header><div><span className="nq-config-eyebrow">03 / DETECTION</span><h3>{lang==='en'?'Event detection & GPS conditions':'اكتشاف الأحداث وشروط GPS'}</h3><p>{lang==='en'?'Enable event categories, then adjust optional GPS quality gates individually.':'فعّل أنواع الأحداث ثم اضبط شروط جودة GPS الاختيارية لكل حدث.'}</p></div></header>
        {(me.role==='super_admin'||me.role==='company_admin')&&<div style={{marginTop:18,marginBottom:18}}>
          <h3>{lang==='en'?'Driving event controls':'التحكم بأحداث القيادة'}</h3>
          <div className="nq-event-switches">
            <div className="nq-switch-grid">{eventKinds.map(kind=><label className="nq-switch-item" key={kind}><input type="checkbox" checked={eventPolicy.enabled[kind]!==false} onChange={e=>setEventPolicy(old=>({...old,enabled:{...old.enabled,[kind]:e.target.checked}}))}/><span>{kind==='speeding'?(lang==='en'?'Detect speeding':'رصد تجاوز السرعة'):kind==='harsh_acceleration'?(lang==='en'?'Detect harsh acceleration':'رصد التسارع العنيف'):kind==='harsh_braking'?(lang==='en'?'Detect harsh braking':'رصد الفرملة العنيفة'):kind==='excessive_speeding'?(lang==='en'?'Detect aggressive speeding':'رصد تجاوز السرعة الشديد'):kind==='excessive_harsh_braking'?(lang==='en'?'Detect aggressive braking':'رصد الفرملة الشديدة جداً'):kind==='excessive_harsh_acceleration'?(lang==='en'?'Detect aggressive acceleration':'رصد التسارع الشديد جداً'):kind==='harsh_cornering'?(lang==='en'?'Detect harsh cornering':'رصد الانعطاف الحاد'):kind==='geofence_entry'?(lang==='en'?'Detect geofence entry':'رصد دخول المنطقة'):kind==='geofence_exit'?(lang==='en'?'Detect geofence exit':'رصد الخروج من المنطقة'):(lang==='en'?'Detect restricted geofence':'رصد المنطقة المحظورة')}</span></label>)}</div>
            <label style={{display:'flex',alignItems:'center',gap:12,marginBottom:12}}><input type="checkbox" checked={eventPolicy.enforce_gps_conditions} onChange={e=>setEventPolicy(old=>({...old,enforce_gps_conditions:e.target.checked}))}/><span>{lang==='en'?'Require additional GPS event conditions':'اشتراط شروط GPS الإضافية'}</span></label>
            <p style={{fontSize:13,opacity:.8}}>{lang==='en'?'Turning off GPS conditions bypasses age/HDOP/satellite/accuracy event gates, but does not disable GPS collection or its basic accuracy filter. Turning off event detection never stops GPS tracking.':'تعطيل شروط GPS يتجاوز شروط عمر القراءة والأقمار والدقة الإضافية للأحداث فقط، ولا يوقف تسجيل الموقع أو فلتر الدقة الأساسي. تعطيل الأحداث لا يوقف التتبع.'}</p>
            <button className="primary" onClick={saveEventPolicy}>{lang==='en'?'Save event switches':'حفظ إعدادات الأحداث'}</button>
          </div>
          <h3>{lang==='en'?'GPS event conditions':'شروط أحداث نظام تحديد المواقع'}</h3>
          <button className="refresh" onClick={()=>loadEventConditions(configCid)}>{lang==='en'?'Load event conditions':'تحميل شروط الأحداث'}</button>
          {eventKinds.map(kind=>{const c=eventConditions.find(x=>x.event_type===kind);const label=({speeding:lang==='en'?'Overspeeding':'تجاوز السرعة',harsh_acceleration:lang==='en'?'Harsh acceleration':'التسارع العنيف',harsh_braking:lang==='en'?'Harsh braking':'الفرملة العنيفة',harsh_cornering:lang==='en'?'Harsh cornering':'الانعطاف الحاد',geofence_entry:lang==='en'?'Geofence entry':'دخول المنطقة',geofence_exit:lang==='en'?'Geofence exit':'الخروج من المنطقة',geofence_restricted:lang==='en'?'Restricted geofence':'منطقة محظورة'} as Record<string,string>)[kind];return <div key={kind} className="nq-event-condition">
            <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:12}}><strong>{label} — {kind==='speeding'?speedThreshold+' km/h':kind==='harsh_acceleration'?accelThreshold+' km/h/s':kind==='harsh_braking'?brakeThreshold+' km/h/s':kind==='harsh_cornering'?phase4Settings.cornering_ms2+' m/s²':''}</strong><button className="refresh" onClick={()=>{setOpenEvent(openEvent===kind?null:kind);if(!c)loadEventConditions(configCid);}}>{openEvent===kind?(lang==='en'?'Hide conditions':'إخفاء الشروط'):(lang==='en'?'Edit conditions':'تعديل الشروط')}</button></div>
            {openEvent===kind&&c&&<div style={{marginTop:12,padding:12,borderRadius:8,background:'rgba(120,160,160,.08)'}}>
              <p style={{margin:'0 0 10px'}}>{lang==='en'?'Event occurs only when ALL conditions are met:':'يُسجّل الحدث فقط عند تحقق جميع الشروط:'}</p>
              <div style={{padding:12,borderLeft:'3px solid #a6d84d',borderRadius:8}}>
                <div style={{fontWeight:700,marginBottom:8}}>{label} {kind==='speeding'?' > '+speedThreshold+' km/h':kind==='harsh_acceleration'?' > '+accelThreshold+' km/h/s':kind==='harsh_braking'?' > '+brakeThreshold+' km/h/s':kind==='harsh_cornering'?' > '+phase4Settings.cornering_ms2+' m/s²':''}</div>
                <div style={{paddingLeft:12}}>(
                  {([
                    ['max_gps_age_seconds','gps_age_operator',lang==='en'?'GPS age (seconds)':'عمر قراءة الموقع (ثانية)',0.1,60,0.1],
                    ['max_hdop','hdop_operator',lang==='en'?'GPS HDOP':'تشتت دقة الموقع',0.1,50,0.1],
                    ['min_satellites','satellites_operator',lang==='en'?'GPS satellites':'عدد الأقمار الصناعية',1,50,1],
                    ['max_accuracy_m','accuracy_operator',lang==='en'?'GPS accuracy (meters)':'خطأ الموقع (متر)',1,500,1]
                  ] as const).map(([field,operator,title,min,max,step],idx)=><div key={field} style={{display:'flex',alignItems:'center',gap:10,flexWrap:'wrap',padding:'6px 0'}}>
                    <span style={{minWidth:180}}>{title}</span>
                    <select aria-label={title+' operator'} style={{width:85}} value={(c as any)[operator]||(operator==='satellites_operator'?'>':'<')} onChange={e=>editCondition(kind,operator,e.target.value)}>{['<','<=','=','>=','>'].map(op=><option key={op} value={op}>{op}</option>)}</select>
                    <input aria-label={title+' value'} type="number" min={min} max={max} step={step} style={{width:115}} placeholder={lang==='en'?'Disabled':'معطل'} value={(c as any)[field]??''} onChange={e=>editCondition(kind,field,e.target.value===''&&field!=='max_gps_age_seconds'&&field!=='max_accuracy_m'?null:e.target.value)}/>
                    {idx<3&&<strong style={{color:'#a6d84d'}}>AND</strong>}
                  </div>)}
                )</div>
              </div>
              <button className="primary" style={{marginTop:12}} onClick={()=>saveEventCondition(c)}>{lang==='en'?'Save event conditions':'حفظ شروط الحدث'}</button>
              <details style={{marginTop:10}}><summary>★ {lang==='en'?'More details':'المزيد من التفاصيل'}</summary><p>{lang==='en'?'All enabled conditions must pass. Blank HDOP or satellite fields disable that specific check. Missing required GPS metrics reject events.':'يجب تحقق جميع الشروط المفعلة. ترك قيمة تشتت الدقة أو الأقمار فارغة يعطل ذلك الشرط. نقص بيانات الموقع المطلوبة يمنع تسجيل المخالفة.'}</p></details>
            </div>}
          </div>})}
        </div>}

        </section>}{configSection==='cfg-risk'&&<section id="cfg-risk" className="nq-config-section"><span className="nq-config-eyebrow">04 / RISK</span><h3>{lang==='en'?'Cornering and risk thresholds':'حدود الانعطاف والمخاطر'}</h3>
        <div className="entry-form">{(['cornering_ms2','min_cornering_speed_kmh','risk_medium_below','risk_high_below','risk_critical_below'] as const).map(k=><label key={k}>{({cornering_ms2:lang==='en'?'Harsh cornering (m/s²)':'الانعطاف الحاد (م/ث²)',min_cornering_speed_kmh:lang==='en'?'Minimum cornering speed (km/h)':'أدنى سرعة للانعطاف (كم/ساعة)',risk_medium_below:lang==='en'?'Medium risk below score':'مخاطر متوسطة تحت درجة',risk_high_below:lang==='en'?'High risk below score':'مخاطر عالية تحت درجة',risk_critical_below:lang==='en'?'Critical risk below score':'مخاطر حرجة تحت درجة'} as Record<string,string>)[k]}<input type="number" step="any" value={phase4Settings[k]} onChange={e=>setPhase4Settings(v=>({...v,[k]:Number(e.target.value)}))}/></label>)}<button className="primary" disabled={!phase4Cid} onClick={savePhase4Settings}>{lang==='en'?'Save policy':'حفظ السياسة'}</button></div>
        </section>}{configSection==='cfg-delivery'&&<section id="cfg-delivery" className="nq-config-section"><span className="nq-config-eyebrow">05 / DELIVERY</span><h3>{lang==='en'?'Policy delivery acknowledgment':'تأكيد استلام سياسة القيادة'}</h3>
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Status':'الحالة'}</th><th>{lang==='en'?'Received at':'وقت الاستلام'}</th></tr></thead><tbody>{policyAcks.map(a=><tr key={a.driver_id}><td>{a.driver_name}</td><td>{a.status==='received'?(lang==='en'?'Received':'تم الاستلام'):(lang==='en'?'Pending':'معلق')}</td><td>{a.received_at?new Date(a.received_at).toLocaleString():'—'}</td></tr>)}</tbody></table></div></section>}
      </>:<div className="nq-selection-empty">{lang==='en'?'Select a company to configure its driving policies.':'اختر شركة لضبط سياسات القيادة الخاصة بها.'}</div>}
      </section>}
      {tab==='reports'&&<ReportSuite lang={lang} role={me.role} userId={me.id} selected={reportSuiteSelected} onSelect={id=>{
        if(id==='privacy-audit'||id==='mobile-diagnostics'||id==='overview'||id==='historical-tracking'){
          setReportSuiteSelected(null);setTab(id);
        }else setReportSuiteSelected(id);
      }}>
      {reportSuiteSelected==='geofence'&&<GeofenceReport request={request} lang={lang} companyId={Number(activeCompanyId)||null} companies={companies} drivers={drivers}/>}
      {reportSuiteSelected==='subscriptions'&&<ReportSubscriptions key={activeCompanyId} request={request} lang={lang} role={me.role} companyId={me.company_id} selectedCompany={reportCompany} companies={companies} drivers={drivers} vehicles={vehicles}/>}
      {(reportSuiteSelected==='performance'||reportSuiteSelected==='monthly'||reportSuiteSelected==='rag')&&<section className="panel"><h3>{lang==='en'?(reportSuiteSelected==='monthly'?'Monthly Report Filters':reportSuiteSelected==='rag'?'RAG Report Filters':'Driver Safety & Performance Reports'):(reportSuiteSelected==='monthly'?'معايير التقارير الشهرية':reportSuiteSelected==='rag'?'معايير تقرير RAG':'تحليلات الأسطول · تقارير السائقين')}</h3><details className="nuqati-help" style={{margin:"8px 0 14px"}}><summary style={{cursor:"pointer",color:"#b5d86c",fontWeight:600}}>★ {lang==='en'?'More details':'المزيد من التفاصيل'}</summary><p style={{marginTop:8}}>{lang==='en'?'Company administrators see only their own drivers. Select a driver for individual trip and violation details. Latest location is not necessarily live.':'يرى مديرو الشركات سائقي شركاتهم فقط. اختر سائقًا لعرض الرحلات والمخالفات. قد لا يكون آخر موقع مسجل مباشرًا.'}</p></details>
        <div className="entry-form">
        {reportSuiteSelected==='performance'&&<label>{lang==='en'?'Period':'الفترة'}<select value={reportPeriod} onChange={e=>setReportPeriod(e.target.value)}>{['daily','weekly','monthly','yearly'].map(x=><option key={x} value={x}>{lang==='en'?x:({daily:'يومي',weekly:'أسبوعي',monthly:'شهري',yearly:'سنوي'} as Record<string,string>)[x]}</option>)}</select></label>}
        {(reportSuiteSelected==='performance'||reportSuiteSelected==='monthly')&&<label>{lang==='en'?'Driver':'السائق'}<select value={reportDriver} onChange={e=>{setReportDriver(e.target.value);setReport(null);setMonthlyReport(null)}}><option value="">{lang==='en'?'All drivers':'جميع السائقين'}</option>{drivers.filter(d=>d.company_id===Number(me.role==='super_admin'?activeCompanyId:me.company_id)).map(d=><option key={d.id} value={d.id}>{d.full_name}</option>)}</select></label>}
        {reportSuiteSelected==='performance'&&<button className="primary" disabled={reportLoading||(!reportCompany&&me.role==='super_admin')} onClick={()=>fetchReport()}>{reportLoading?(lang==='en'?'Loading…':'جار التحميل…'):(lang==='en'?'Generate report':'إنشاء التقرير')}</button>} {reportSuiteSelected==='performance'&&<button className="refresh" disabled={!report} onClick={exportReport}>{lang==='en'?'Export CSV':'تصدير CSV'}</button>}</div>
        {reportSuiteSelected==='monthly'&&<details open style={{margin:'16px 0',padding:16,border:'1px solid #35495a',borderRadius:12}}>
          <summary style={{fontWeight:700,cursor:'pointer'}}>{lang==='en'?'Monthly Reports Center — PDF / CSV / Excel':'مركز التقارير الشهرية — PDF / CSV / Excel'}</summary>
          <div className="entry-form" style={{marginTop:12}}>
            <label>{lang==='en'?'Report month':'شهر التقرير'}<input type="month" value={reportMonth} onChange={e=>{setReportMonth(e.target.value);setMonthlyReport(null);}}/></label>
            <button className="primary" disabled={monthlyBusy||!reportMonth||(!reportCompany&&me.role==='super_admin')} onClick={loadMonthlyReport}>{monthlyBusy?'Loading…':lang==='en'?'Generate monthly reports':'إنشاء التقارير الشهرية'}</button>
          </div>
          <small>{lang==='en'?'Uses the company and driver filters above. Leave driver as All drivers for company-wide reports.':'يستخدم فلتر الشركة والسائق أعلاه. اختر جميع السائقين للحصول على تقارير الشركة كاملة.'}</small>
          {monthlyReport&&<>
            <div className="stats" style={{marginTop:12}}><article className="stat-card"><span>{lang==='en'?'Vehicles':'المركبات'}</span><strong>{monthlyReport.vehicles.length}</strong></article><article className="stat-card"><span>{lang==='en'?'Drivers':'السائقون'}</span><strong>{monthlyReport.drivers.length}</strong></article></div>
            {(['vehicles','utilization','rag','violations'] as const).map(kind=><div key={kind} style={{padding:'12px 0',borderBottom:'1px solid #35495a',display:'flex',justifyContent:'space-between',alignItems:'center',gap:12,flexWrap:'wrap'}}>
              <strong>{({vehicles:lang==='en'?'Vehicles & assigned drivers':'المركبات والسائقون المعينون',utilization:lang==='en'?'Driver utilization by vehicle':'استخدام السائق لكل مركبة',rag:lang==='en'?'Monthly RAG score':'تصنيف السائقين الشهري',violations:lang==='en'?'Monthly driver violations':'مخالفات السائقين الشهرية'} as Record<string,string>)[kind]}</strong>
              <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>{(['pdf','csv','xlsx'] as const).map(fmt=><button key={fmt} className="refresh" onClick={()=>downloadMonthlyReport(kind,fmt)}>{fmt==='xlsx'?'Excel':fmt.toUpperCase()}</button>)}</div>
            </div>)}
            <div className="table-wrap" style={{marginTop:14}}><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Trips':'الرحلات'}</th><th>km</th><th>{lang==='en'?'Hours':'الساعات'}</th><th>{monthlyReport.score_model==='flexible_rag'?(lang==='en'?'RAG penalty ↓':'درجة RAG ↓'):(lang==='en'?'Score / 100':'التقييم / ١٠٠')}</th><th>RAG</th><th>{lang==='en'?'Total violations':'مجموع المخالفات'}</th></tr></thead><tbody>{monthlyReport.drivers.map((d:any)=><tr key={d.driver_id}><td>{d.driver_name}</td><td>{d.trip_count}</td><td>{d.distance_km}</td><td>{d.driving_hours}</td><td>{d.score??'—'}</td><td style={{fontWeight:700,color:d.rag==='Green'?'#22c55e':d.rag==='Amber'?'#eab308':d.rag==='Red'?'#ef4444':'inherit'}}>{d.rag}</td><td>{d.total_violations}</td></tr>)}</tbody></table></div>
            <small>{lang==='en'?'Excessive speeding is included within speeding totals. Driving hours represent completed-trip duration. No data means insufficient distance for scoring.':'تجاوز السرعة الشديد جزء من مجموع تجاوز السرعة. ساعات القيادة هي مدة الرحلات المكتملة. عدم وجود نقاط يعني عدم كفاية المسافة.'}</small>
          </>}
        </details>}
        {reportSuiteSelected==='rag'&&<FlexibleRagReports request={request} companyId={me.role==='super_admin'?reportCompany:me.company_id} lang={lang}/>}
        {reportSuiteSelected==='performance'&&report&&<><div className="stats"><article className="stat-card"><span>{lang==='en'?'Drivers':'السائقون'}</span><strong>{report.driver_count}</strong></article><article className="stat-card"><span>{lang==='en'?'Trips':'الرحلات'}</span><strong>{report.trip_count}</strong></article><article className="stat-card"><span>{lang==='en'?'Average official score':'متوسط النتيجة الرسمية'}</span><strong>{report.average_score??'No data'}</strong></article></div>
        <div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Trips':'الرحلات'}</th><th>{lang==='en'?'Official score':'النتيجة الرسمية'}</th><th>{lang==='en'?'Risk':'المخاطر'}</th><th>{lang==='en'?'Speeding':'تجاوز السرعة'}</th><th>{lang==='en'?'Harsh braking':'الفرملة العنيفة'}</th><th>{lang==='en'?'Harsh acceleration':'التسارع العنيف'}</th><th>{lang==='en'?'Harsh cornering':'الانعطاف الحاد'}</th><th>{lang==='en'?'Last GPS':'آخر موقع GPS'}</th></tr></thead><tbody>{report.drivers.map((d:any)=><tr key={d.driver_id}><td>{d.driver_name}</td><td>{d.trips}</td><td>{d.score??'—'}</td><td>{d.risk??'—'}</td><td>{d.violations.speeding}</td><td>{d.violations.harsh_braking}</td><td>{d.violations.harsh_acceleration}</td><td>{d.violations.harsh_cornering??0}</td><td>{d.latest_location?<><a href={`https://www.openstreetmap.org/?mlat=${d.latest_location.latitude}&mlon=${d.latest_location.longitude}#map=15/${d.latest_location.latitude}/${d.latest_location.longitude}`} target="_blank" rel="noreferrer">{lang==='en'?'View map':'عرض الخريطة'}</a><small> {new Date(d.latest_location.recorded_at).toLocaleString()}</small></>:(lang==='en'?'No GPS data':'لا توجد بيانات موقع')}</td></tr>)}</tbody></table></div>

      </>}
      </section>}
      </ReportSuite>}
      {tab==='live-tracking'&&<section className="panel nuqati-tracking-page">
        <div className="nuqati-tracking-heading">
          <div><span className="nuqati-live-eyebrow"><span className="nuqati-live-pulse"/>{lang==='en'?'FLEET OPERATIONS':'عمليات الأسطول'}</span><h2>{lang==='en'?'Live Tracking':'التتبع المباشر'}</h2><p>{lang==='en'?'Monitor vehicle locations and activity in one workspace':'راقب مواقع المركبات وحركتها من لوحة واحدة'}</p></div>
          <div className="nuqati-live-refresh"><small>{liveSnapshotTime?(lang==='en'?`Last snapshot · ${liveSnapshotTime} (Saudi time)`:`آخر تحديث للبيانات · ${liveSnapshotTime} (بتوقيت السعودية)`):(lang==='en'?'Automatically refreshes every 30 seconds':'تحديث تلقائي كل ٣٠ ثانية')}</small><button type="button" className="primary" disabled={!reportCompany&&me.role==='super_admin'} onClick={()=>void fetchLiveSnapshot()}><RefreshCw size={15}/>{lang==='en'?'Refresh positions':'تحديث المواقع'}</button></div>
        </div>
        {liveError&&<div className="notice" role="alert">{liveError}</div>}
        {liveSnapshot&&<>
          <div className="nuqati-live-stats" aria-label={lang==='en'?'Vehicle motion summary':'ملخص حركة المركبات'}>
            <article><span>{lang==='en'?'Fleet vehicles':'مركبات الأسطول'}</span><strong>{livePositions.length}</strong><small>{lang==='en'?'Registered vehicles':'المركبات المسجلة'}</small></article>
            <article className="is-moving"><span><i className="nuqati-live-dot moving"/>{lang==='en'?'Moving now':'متحركة الآن'}</span><strong>{liveMovingCount}</strong><small>{lang==='en'?'Current valid GPS':'GPS حالي وصالح'}</small></article>
            <article className="is-stationary"><span><i className="nuqati-live-dot stationary"/>{lang==='en'?'Stationary now':'متوقفة الآن'}</span><strong>{liveStationaryCount}</strong><small>{lang==='en'?'Current valid GPS':'GPS حالي وصالح'}</small></article>
            <article><span><i className="nuqati-live-dot unknown"/>{lang==='en'?'Offline / uncertain':'غير متصلة / غير مؤكدة'}</span><strong>{liveUnknownCount}</strong><small>{lang==='en'?'Not classified as live motion':'ليست حركة مؤكدة مباشرة'}</small></article>
          </div>
          <div className="nuqati-live-filterbar">
            <div className="nuqati-live-filter-intro"><strong>{lang==='en'?'Filter by motion':'التصفية حسب الحركة'}</strong><small>{lang==='en'?'Choose a status to show only matching vehicles on the list and map.':'اختر الحالة لعرض المركبات المطابقة فقط في القائمة والخريطة.'}</small></div>
            <div className="nuqati-live-motion-buttons" role="group" aria-label={lang==='en'?'Filter vehicle movement':'تصفية حركة المركبات'}>
              <button type="button" className={'nuqati-live-motion-btn moving '+(liveMotionFilter==='moving'?'is-active':'')} aria-pressed={liveMotionFilter==='moving'} onClick={()=>chooseLiveMotion('moving')}><span className="nuqati-live-dot moving"/>{lang==='en'?'Moving':'متحركة'}<b>{liveMovingCount}</b></button>
              <button type="button" className={'nuqati-live-motion-btn stationary '+(liveMotionFilter==='stationary'?'is-active':'')} aria-pressed={liveMotionFilter==='stationary'} onClick={()=>chooseLiveMotion('stationary')}><span className="nuqati-live-dot stationary"/>{lang==='en'?'Stationary':'متوقفة'}<b>{liveStationaryCount}</b></button>
            </div>
            <button type="button" className={'nuqati-live-clear '+(liveMotionFilter==='all'?'is-current':'')} onClick={()=>{setLiveMotionFilter('all');setLiveVehicleId(null);}} aria-pressed={liveMotionFilter==='all'}>{lang==='en'?'All statuses':'جميع الحالات'}</button>
          </div>
        </>}
        <div className="nuqati-live-controls">
          <label>{lang==='en'?'Jump to vehicle':'الانتقال إلى مركبة'}<select value={displayedLiveVehicleId??''} onChange={e=>setLiveVehicleId(e.target.value?Number(e.target.value):null)}><option value="">{lang==='en'?'View filtered fleet':'عرض الأسطول المحدد'}</option>{visibleLivePositions.map(p=><option key={p.vehicle_id} value={p.vehicle_id}>{p.plate} · {p.driver_name||'—'}</option>)}</select></label>
          <div className="nuqati-live-layer-controls">
            <label><input type="checkbox" checked={liveShowZones} onChange={e=>setLiveShowZones(e.target.checked)}/>{lang==='en'?'Geofences':'المناطق الجغرافية'}</label>
            <label><input type="checkbox" checked={liveShowActive} onChange={e=>setLiveShowActive(e.target.checked)}/>{lang==='en'?'Active events':'الأحداث النشطة'}</label>
            {['super_admin','company_admin','fleet_manager'].includes(me.role)&&<label><input type="checkbox" checked={liveShowPassive} onChange={e=>setLiveShowPassive(e.target.checked)}/>{lang==='en'?'Reference events':'أحداث مرجعية'}</label>}
          </div>
        </div>
        {liveSnapshot?<div className="nuqati-tracking-workspace" dir={lang==='ar'?'rtl':'ltr'}>
          <aside className="nuqati-map-side nuqati-live-sidebar">
            <div className="nuqati-live-sidebar-head"><div><h3>{lang==='en'?'Vehicles':'المركبات'}</h3><small><ArrowUpDown size={13}/>{lang==='en'?'Latest GPS update first':'الأحدث تحديثًا أولاً'}</small></div><span className="nuqati-live-visible-count">{visibleLivePositions.length} / {livePositions.length}</span></div>
            <div className="nuqati-live-search"><Search size={17}/><input aria-label={lang==='en'?'Search vehicles by plate or driver':'البحث عن مركبة باللوحة أو السائق'} placeholder={lang==='en'?'Search plate or driver':'ابحث باللوحة أو السائق'} value={fleetVehicleSearch} onChange={e=>setFleetVehicleSearch(e.target.value)}/>{fleetVehicleSearch&&<button type="button" aria-label={lang==='en'?'Clear search':'مسح البحث'} onClick={()=>setFleetVehicleSearch('')}><X size={15}/></button>}</div>
            <div className="nuqati-live-sidebar-caption"><span>{lang==='en'?`${visibleLivePositions.length} matching vehicles`:`${visibleLivePositions.length} مركبة مطابقة`}</span><button type="button" onClick={clearLiveFilters}>{lang==='en'?'Reset filters':'إعادة التصفية'}</button></div>
            <div className="nuqati-side-scroll" aria-label={lang==='en'?'Vehicle list sorted by latest update':'قائمة المركبات مرتبة حسب آخر تحديث'}>
              {visibleLivePositions.map(p=><div key={p.vehicle_id} className={'nuqati-side-item nuqati-live-vehicle-card '+(displayedLiveVehicleId===p.vehicle_id?'selected':'')}><button type="button" className="nq-live-card-select" aria-pressed={displayedLiveVehicleId===p.vehicle_id} onClick={()=>setLiveVehicleId(p.vehicle_id)}>
                <div className="nuqati-live-card-top"><strong dir="auto">{p.plate}</strong><span className={'nuqati-live-state '+(p.state==='moving'?'moving':p.state==='stationary'?'stationary':'unknown')}><i className={'nuqati-live-dot '+(p.state==='moving'?'moving':p.state==='stationary'?'stationary':'unknown')}/>{p.state==='moving'?(lang==='en'?'Moving':'متحركة'):p.state==='stationary'?(lang==='en'?'Stationary':'متوقفة'):(lang==='en'?'Offline / uncertain':'غير متصلة / غير مؤكدة')}</span></div>
                <span className="nuqati-live-driver" dir="auto">{p.driver_name||(lang==='en'?'Unassigned driver':'لا يوجد سائق معين')}</span>
                <div className="nuqati-live-card-metrics"><span><Gauge size={14}/><b>{p.speed_kmh==null?'—':Number(p.speed_kmh).toFixed(1)}</b> {lang==='en'?'km/h':'كم/س'}</span><span className="nq-last-position"><Clock3 size={14}/><span><b>{lang==='en'?'Last GPS':'آخر موقع'}</b> {p.recorded_at?new Date(p.recorded_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh',year:'numeric',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):(lang==='en'?'Not reported':'غير متوفر')}</span></span></div>
                {(p.geofences||[]).some(z=>z.status==='inside')&&<span className="nuqati-live-card-geofence"><MapPin size={12}/>{p.geofences.filter(z=>z.status==='inside').map(z=>z.name).join(', ')}</span>}
              </button>
               {['super_admin','company_admin','fleet_manager'].includes(me.role)&&<details className="nq-live-card-actions"><summary><MapPin size={13}/>{lang==='en'?'Position & share':'الموقع والمشاركة'}<ChevronDown size={13}/></summary><div className="nq-live-card-action-row"><button type="button" onClick={()=>void requestNewLivePosition(p.vehicle_id)}><RefreshCw size={13}/>{lang==='en'?'Request position':'طلب الموقع'}</button><button type="button" onClick={()=>void makeLiveShare(p.vehicle_id)}><Route size={13}/>{lang==='en'?'Share link':'مشاركة'}</button><label>{lang==='en'?'Expiry':'المدة'}<select aria-label={lang==='en'?'Share expiry for vehicle':'مدة مشاركة الموقع'} value={liveShareMinutes} onChange={e=>setLiveShareMinutes(e.target.value)}><option value="5">5 min</option><option value="15">15 min</option><option value="30">30 min</option><option value="60">60 min</option></select></label></div></details>}
              </div>)}
              {visibleLivePositions.length===0&&<div className="nuqati-live-no-results"><Search size={24}/><strong>{lang==='en'?'No matching vehicles':'لا توجد مركبات مطابقة'}</strong><p>{lang==='en'?'Try another motion status or clear your search.':'اختر حالة حركة أخرى أو امسح البحث.'}</p><button type="button" className="refresh" onClick={clearLiveFilters}>{lang==='en'?'Show all vehicles':'عرض جميع المركبات'}</button></div>}
            </div>
          </aside>
          <div className="nuqati-fleet-map-center">
            <div className="nuqati-live-map-heading"><div><strong><MapPin size={16}/>{lang==='en'?'Fleet location map':'خريطة مواقع الأسطول'}</strong><small>{selectedLivePosition?(lang==='en'?`Focused on ${selectedLivePosition.plate}`:`التركيز على ${selectedLivePosition.plate}`):(lang==='en'?`Displaying ${visibleLivePositions.length} vehicles`:`عرض ${visibleLivePositions.length} مركبة`)}</small></div>{displayedLiveVehicleId!==null&&<button type="button" className="refresh" onClick={()=>setLiveVehicleId(null)}>{lang==='en'?'Back to fleet':'العودة للأسطول'}</button>}</div>
            {visibleLivePositions.length>0?<FleetPositionMap lang={lang} positions={visibleLivePositions} zones={liveSnapshot.zones||[]} events={liveSnapshot.events||[]} selectedVehicleId={displayedLiveVehicleId} showZones={liveShowZones} showActive={liveShowActive} showPassive={liveShowPassive} limitEventsToPositions={liveMotionFilter!=='all'||Boolean(fleetVehicleSearch.trim())}/>:<div className="nuqati-live-map-empty"><MapPin size={34}/><strong>{lang==='en'?'No vehicles to display':'لا توجد مركبات للعرض'}</strong><p>{lang==='en'?'Change your filters to see vehicle locations.':'غيّر معايير التصفية لعرض مواقع المركبات.'}</p></div>}
            <small>{lang==='en'?'Locations reflect the last reported GPS fix, not guaranteed current positions. Grey status means stale, private or uncertain GPS.':'المواقع هي آخر قراءات GPS وليست بالضرورة المواقع الحالية. الحالة الرمادية تعني معلومات قديمة أو خاصة أو غير مؤكدة.'}</small>
          </div>
        </div>:<div className="empty">{lang==='en'?'Choose a company to load vehicle positions.':'اختر شركة لعرض مواقع المركبات.'}</div>}
         {(liveShareUrl||liveRequestMessage)&&<div className="nq-live-action-feedback" role="status">{liveRequestMessage&&<p>{liveRequestMessage}</p>}{liveShareUrl&&<div className="nuqati-live-generated"><input readOnly aria-label="Live share link" value={liveShareUrl}/><button type="button" className="refresh" onClick={()=>void navigator.clipboard.writeText(liveShareUrl)}>{lang==='en'?'Copy link':'نسخ الرابط'}</button></div>}</div>}
        {liveShareLinks.filter((link:any)=>!link.revoked&&new Date(link.expires_at)>new Date()&&livePositions.some(p=>p.vehicle_id===link.vehicle_id)).length>0&&<details className="nuqati-live-shares"><summary>{lang==='en'?'My active sharing links':'روابط المشاركة الخاصة بي'}</summary>{liveShareLinks.filter((link:any)=>!link.revoked&&new Date(link.expires_at)>new Date()&&livePositions.some(p=>p.vehicle_id===link.vehicle_id)).map((link:any)=><div key={link.share_id}>{livePositions.find(p=>p.vehicle_id===link.vehicle_id)?.plate||link.vehicle_id} · {new Date(link.expires_at).toLocaleString()} <button type="button" className="refresh" onClick={()=>void revokeLiveShare(link.share_id)}>{lang==='en'?'Revoke':'إلغاء'}</button></div>)}</details>}
        {['super_admin','company_admin'].includes(me.role)&&<details className="nuqati-live-active-settings"><summary>{lang==='en'?'Configure active event types':'إعداد الأحداث النشطة'}</summary><div>{eventKinds.map(kind=><label key={kind}><input type="checkbox" checked={liveActiveKinds.includes(kind)} onChange={e=>setLiveActiveKinds(prev=>e.target.checked?[...prev,kind]:prev.filter(k=>k!==kind))}/>{kind.replaceAll('_',' ')}</label>)}</div><button type="button" className="primary" onClick={()=>void saveLiveEventKinds()}>{lang==='en'?'Save active events':'حفظ الأحداث النشطة'}</button></details>}
        <div className="nuqati-tracking-disclaimer">{lang==='en'?'Vehicle status uses valid GPS from the last 5 minutes: moving ≥5 km/h, stationary ≤2 km/h. Other readings are uncertain or offline. Active event layers can be configured independently of historical records.':'تعتمد حالة المركبة على GPS صالح خلال آخر ٥ دقائق: متحركة بسرعة ٥ كم/س فأكثر ومتوقفة بسرعة ٢ كم/س فأقل. القراءات الأخرى غير مؤكدة أو غير متصلة. يمكن ضبط طبقات الأحداث بمعزل عن السجل التاريخي.'}</div>
      </section>}
      {tab==='historical-tracking'&&<section className="panel nuqati-trips-page nuqati-history-page">
        <header className="nuqati-history-hero">
          <div className="nuqati-history-hero-title">
            <span className="nuqati-history-eyebrow"><Route size={15}/>{lang==='en'?'FLEET JOURNEYS':'رحلات الأسطول'}</span>
            <h2>{lang==='en'?'Historical Tracking':'التتبع التاريخي'}</h2>
            <p>{lang==='en'?'Explore journeys, replay GPS routes and investigate safety events in one workspace.':'استعرض الرحلات، وأعد تشغيل مسارات GPS، وراجع أحداث السلامة في واجهة واحدة.'}</p>
          </div>
          <div className="nuqati-history-hero-actions">
            <label>{lang==='en'?'Report period':'فترة التقرير'}
              <select aria-label={lang==='en'?'Historical report period':'فترة تقرير التتبع التاريخي'} value={reportPeriod} onChange={e=>{const period=e.target.value;setReportPeriod(period);setPreciseTrips(null);setSelectedTripId(null);setSelectedRoute(null);setHistoryRoutes({});stopRangePlayback();void fetchReport(period,'',reportCompany);}}>
                {(['daily','weekly','monthly','yearly'] as const).map(x=><option key={x} value={x}>{({daily:lang==='en'?'Today':'اليوم',weekly:lang==='en'?'This week':'هذا الأسبوع',monthly:lang==='en'?'This month':'هذا الشهر',yearly:lang==='en'?'This year':'هذا العام'})[x]}</option>)}
              </select>
            </label>
            <button type="button" className="primary" disabled={reportLoading||rangeSearching||(!reportCompany&&me.role==='super_admin')} onClick={()=>preciseTrips!==null?void loadPreciseTrips():void fetchReport(reportPeriod,'',reportCompany)}><RefreshCw size={16}/>{reportLoading||rangeSearching?(lang==='en'?'Loading…':'جار التحميل…'):(lang==='en'?'Refresh trips':'تحديث الرحلات')}</button>
          </div>
        </header>
        {(report||preciseTrips)?(()=>{
          const trips:any[]=preciseTrips??(report?.drivers||[]).flatMap((d:any)=>(d.trip_details||[]).map((t:any)=>({...t,driver_name:d.driver_name,driver_id:d.driver_id})));
          const eventCount=(t:any):number=>Array.isArray(t.violations)?t.violations.length:Number(t.event_count||0);
          const vehicleFor=(t:any)=>vehicles.find(v=>v.id===t.vehicle_id);
          const baseTrips=trips.filter((t:any)=>(!historyDriverId||String(t.driver_id)===historyDriverId)&&(!historyVehicleId||String(t.vehicle_id)===historyVehicleId)&&(!historySite||driverDetails[String(t.driver_id)]?.site_name===historySite)&&(!tripSearch||`${t.id} ${t.driver_name||''} ${vehicleFor(t)?.plate_number||''} ${vehicleFor(t)?.make_model||''}`.toLowerCase().includes(tripSearch.trim().toLowerCase())));
          const shown=baseTrips.filter((t:any)=>(tripStatusFilter==='all'||t.status===tripStatusFilter)&&(!historyEventsOnly||eventCount(t)>0)).sort((a:any,b:any)=>(Date.parse(b.started_at)||0)-(Date.parse(a.started_at)||0)||b.id-a.id);
          const totalKm=shown.reduce((sum:number,t:any)=>sum+Number(t.distance_km||0),0);
          const totalMinutes=shown.reduce((sum:number,t:any)=>sum+Math.max(0,(new Date(t.ended_at||Date.now()).getTime()-new Date(t.started_at).getTime())/60000),0);
          const violations=shown.reduce((sum:number,t:any)=>sum+eventCount(t),0);
          const activeCount=baseTrips.filter((t:any)=>t.status==='active').length;
          const completedCount=baseTrips.filter((t:any)=>t.status==='completed').length;
          const eventsCount=baseTrips.filter((t:any)=>eventCount(t)>0).length;
          const saDate=(v:string)=>{const date=new Date(v);return Number.isFinite(date.getTime())?date.toLocaleString(lang==='ar'?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh',year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';};
          const duration=(t:any)=>{const min=Math.max(0,Math.floor((new Date(t.ended_at||Date.now()).getTime()-new Date(t.started_at).getTime())/60000));return `${Math.floor(min/60)}${lang==='en'?'h':'س'} ${min%60}${lang==='en'?'m':'د'}`;};
          const overlayCount=Object.keys(historyRoutes).length;
          const hasCompany=me.role!=='super_admin'||Boolean(reportCompany);
          const resetHistoryFilters=()=>{setHistoryDriverId('');setHistoryVehicleId('');setHistorySite('');setTripFrom('');setTripTo('');setPreciseTrips(null);setTripSearch('');setTripStatusFilter('all');setHistoryEventsOnly(false);setSelectedTripId(null);setSelectedRoute(null);setHistoryRoutes({});stopRangePlayback();};
          const visibleSelectedTripId=shown.some((t:any)=>t.id===selectedTripId)?selectedTripId:null;
          const activeRoute=selectedRoute&&selectedRoute.trip_id===visibleSelectedTripId?selectedRoute:Object.values(historyRoutes)[0];
          return <div className="nuqati-history-content">
            <div className="nuqati-history-kpis" aria-label={lang==='en'?'Filtered trip statistics':'إحصائيات الرحلات بعد التصفية'}>
              <article><span><Route size={16}/>{lang==='en'?'Matching trips':'الرحلات المطابقة'}</span><strong>{shown.length.toLocaleString('en-US')}</strong><small>{lang==='en'?'of '+trips.length+' loaded trips':'من أصل '+trips.length+' رحلة محمّلة'}</small></article>
              <article><span><MapPin size={16}/>{lang==='en'?'Distance traveled':'المسافة المقطوعة'}</span><strong>{totalKm.toFixed(1)} <em>{lang==='en'?'km':'كم'}</em></strong><small>{lang==='en'?'Recorded trip distance':'المسافة المسجلة للرحلات'}</small></article>
              <article><span><Clock3 size={16}/>{lang==='en'?'Driving time':'وقت القيادة'}</span><strong>{Math.floor(totalMinutes/60)}<em>{lang==='en'?'h':'س'}</em> {Math.floor(totalMinutes%60)}<em>{lang==='en'?'m':'د'}</em></strong><small>{lang==='en'?'Within displayed trips':'ضمن الرحلات المعروضة'}</small></article>
              <article><span><Shield size={16}/>{lang==='en'?'Safety events':'أحداث السلامة'}</span><strong>{violations.toLocaleString('en-US')}</strong><small>{lang==='en'?'Recorded event count':'عدد الأحداث المسجلة'}</small></article>
              <article><span><Activity size={16}/>{lang==='en'?'Active journeys':'الرحلات الجارية'}</span><strong>{shown.filter((t:any)=>t.status==='active').length}</strong><small>{lang==='en'?'Among matching trips':'ضمن الرحلات المطابقة'}</small></article>
            </div>
            <div className="nuqati-history-filters">
              <div className="nuqati-history-section-heading"><div><h3>{lang==='en'?'Find a journey':'البحث عن رحلة'}</h3><p>{lang==='en'?'Choose a status, driver or vehicle. The list and results update together.':'اختر الحالة أو السائق أو المركبة، وستتحدث القائمة والنتائج معًا.'}</p></div>
                <button type="button" className="nuqati-history-reset" onClick={resetHistoryFilters}><X size={15}/>{lang==='en'?'Reset filters':'إعادة ضبط التصفية'}</button>
              </div>
              <div className="nuqati-history-status-tabs" role="group" aria-label={lang==='en'?'Trip status filter':'تصفية حالة الرحلة'}>
                <button type="button" className={tripStatusFilter==='all'&&!historyEventsOnly?'is-active':''} aria-pressed={tripStatusFilter==='all'&&!historyEventsOnly} onClick={()=>{setTripStatusFilter('all');setHistoryEventsOnly(false)}}>{lang==='en'?'All trips':'كل الرحلات'}<b>{baseTrips.length}</b></button>
                <button type="button" className={tripStatusFilter==='active'&&!historyEventsOnly?'is-active':''} aria-pressed={tripStatusFilter==='active'&&!historyEventsOnly} onClick={()=>{setTripStatusFilter('active');setHistoryEventsOnly(false)}}><i className="nuqati-history-state-dot active"/>{lang==='en'?'Active':'جارية'}<b>{activeCount}</b></button>
                <button type="button" className={tripStatusFilter==='completed'&&!historyEventsOnly?'is-active':''} aria-pressed={tripStatusFilter==='completed'&&!historyEventsOnly} onClick={()=>{setTripStatusFilter('completed');setHistoryEventsOnly(false)}}><i className="nuqati-history-state-dot complete"/>{lang==='en'?'Completed':'مكتملة'}<b>{completedCount}</b></button>
                <button type="button" className={historyEventsOnly?'is-active':''} aria-pressed={historyEventsOnly} onClick={()=>{setTripStatusFilter('all');setHistoryEventsOnly(true)}}><Shield size={14}/>{lang==='en'?'With events':'بها أحداث'}<b>{eventsCount}</b></button>
              </div>
              <div className="nuqati-history-filter-grid">
                <label>{lang==='en'?'Driver':'السائق'}<select aria-label={lang==='en'?'Historical driver filter':'تصفية السائق'} value={historyDriverId} onChange={e=>setHistoryDriverId(e.target.value)}><option value="">{lang==='en'?'All drivers':'جميع السائقين'}</option>{drivers.filter(d=>me.role!=='super_admin'||String(d.company_id)===reportCompany).map(d=><option key={d.id} value={d.id}>{d.full_name}</option>)}</select></label>
                <label>{lang==='en'?'Vehicle':'المركبة'}<select aria-label={lang==='en'?'Historical vehicle filter':'تصفية المركبة'} value={historyVehicleId} onChange={e=>setHistoryVehicleId(e.target.value)}><option value="">{lang==='en'?'All vehicles':'جميع المركبات'}</option>{vehicles.filter(v=>me.role!=='super_admin'||String(v.company_id)===reportCompany).map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label>
                <label>{lang==='en'?'Site / department':'الموقع / القسم'}<select aria-label={lang==='en'?'Historical site filter':'تصفية الموقع'} value={historySite} onChange={e=>setHistorySite(e.target.value)}><option value="">{lang==='en'?'All sites':'جميع المواقع'}</option>{[...new Set(drivers.filter(d=>me.role!=='super_admin'||String(d.company_id)===reportCompany).map(d=>driverDetails[String(d.id)]?.site_name||'').filter(Boolean))].sort().map(site=><option key={site} value={site}>{site}</option>)}</select></label>
              </div>
              <details className="nuqati-history-range" open={Boolean(tripFrom||tripTo)}><summary><Clock3 size={16}/>{lang==='en'?'Custom date and time range':'نطاق تاريخ ووقت مخصص'}{preciseTrips!==null&&<span className="nuqati-history-range-pill">{lang==='en'?'Custom range active':'النطاق المخصص مفعّل'}</span>}</summary>
                <div className="nuqati-history-range-body"><label>{lang==='en'?'From (your local time)':'من (توقيت جهازك)'}<input type="datetime-local" value={tripFrom} onChange={e=>setTripFrom(e.target.value)}/></label><label>{lang==='en'?'To (your local time)':'إلى (توقيت جهازك)'}<input type="datetime-local" value={tripTo} onChange={e=>setTripTo(e.target.value)}/></label>
                  <button type="button" className="primary" disabled={rangeSearching||!hasCompany} onClick={()=>void loadPreciseTrips()}><Search size={15}/>{rangeSearching?(lang==='en'?'Searching…':'جار البحث…'):(lang==='en'?'Search range':'بحث في النطاق')}</button>
                  <button type="button" className="refresh" onClick={()=>{setPreciseTrips(null);setTripFrom('');setTripTo('');setSelectedTripId(null);setSelectedRoute(null);setHistoryRoutes({});stopRangePlayback();}}>{lang==='en'?'Back to report period':'العودة إلى فترة التقرير'}</button>
                </div><p>{lang==='en'?'Exact-time search retrieves up to 1,000 trips. Apply the range again after changing a driver or vehicle to search on the server.':'يعرض البحث الدقيق حتى ١٠٠٠ رحلة. أعد تطبيق النطاق بعد تغيير السائق أو المركبة ليُعاد البحث على الخادم.'}</p>
              </details>
            </div>
            <div className="nuqati-history-workspace" dir={lang==='ar'?'rtl':'ltr'}>
              <aside className="nuqati-history-sidebar" aria-label={lang==='en'?'Recorded trip list':'قائمة الرحلات المسجلة'}>
                <div className="nuqati-history-sidebar-heading"><div><h3>{lang==='en'?'Recorded journeys':'الرحلات المسجلة'}</h3><small><ArrowUpDown size={13}/>{lang==='en'?'Latest trip first':'أحدث رحلة أولًا'}</small></div><span className="nuqati-history-match-count">{shown.length} / {trips.length}</span></div>
                <div className="nuqati-live-search nuqati-history-search"><Search size={17}/><input aria-label={lang==='en'?'Search history by trip, plate or driver':'البحث برقم الرحلة أو اللوحة أو السائق'} placeholder={lang==='en'?'Search trip, plate or driver…':'ابحث عن رحلة أو لوحة أو سائق…'} value={tripSearch} onChange={e=>setTripSearch(e.target.value)}/>{tripSearch&&<button type="button" aria-label={lang==='en'?'Clear history search':'مسح البحث'} onClick={()=>setTripSearch('')}><X size={15}/></button>}</div>
                <div className="nuqati-history-list-caption"><span>{lang==='en'?`${shown.length} matching journeys`:`${shown.length} رحلة مطابقة`}</span><small>{lang==='en'?'Select a card to inspect its route':'اختر بطاقة لعرض المسار'}</small></div>
                <div className="nuqati-history-scroll">
                  {shown.map((t:any)=>{
                    const vehicle=vehicleFor(t);const selected=visibleSelectedTripId===t.id;const plotted=Boolean(historyRoutes[t.id]);const events=eventCount(t);
                    return <article key={t.id} className={'nuqati-history-trip-card '+(selected?'selected':'')}>
                      <button type="button" className="nuqati-history-trip-main" aria-pressed={selected} onClick={()=>void viewTripRoute(t.id)}>
                        <span className="nuqati-history-card-top"><strong dir="auto">{vehicle?.plate_number||`#${t.vehicle_id||'—'}`}</strong><span className={'nuqati-history-state '+(t.status==='active'?'active':'complete')}><i className={'nuqati-history-state-dot '+(t.status==='active'?'active':'complete')}/>{t.status==='active'?(lang==='en'?'Active':'جارية'):(lang==='en'?'Completed':'مكتملة')}</span></span>
                        <span className="nuqati-history-driver" dir="auto">{t.driver_name||(lang==='en'?'Unknown driver':'سائق غير معروف')}<small>#{t.id}{vehicle?.make_model?` · ${vehicle.make_model}`:''}</small></span>
                        <span className="nuqati-history-start"><Clock3 size={13}/>{saDate(t.started_at)}</span>
                        <span className="nuqati-history-card-metrics"><span><Route size={14}/><b>{Number(t.distance_km||0).toFixed(2)}</b> {lang==='en'?'km':'كم'}</span><span><Clock3 size={14}/>{duration(t)}</span><span className={events>0?'has-events':''}><Shield size={14}/><b>{events}</b> {lang==='en'?'events':'أحداث'}</span></span>
                      </button>
                      <div className="nuqati-history-card-actions"><span>{lang==='en'?'Trip':'رحلة'} #{t.id}</span><button type="button" className={plotted?'is-plotted':''} disabled={historyBusy.includes(t.id)} aria-pressed={plotted} onClick={()=>void toggleHistoryTrip(t.id)}>{historyBusy.includes(t.id)?'…':plotted?(lang==='en'?'Remove overlay':'إزالة المسار'):(lang==='en'?'Compare on map':'قارن على الخريطة')}</button></div>
                    </article>;
                  })}
                  {shown.length===0&&<div className="nuqati-history-no-results"><Search size={24}/><strong>{lang==='en'?'No matching journeys':'لا توجد رحلات مطابقة'}</strong><p>{lang==='en'?'Try another status, clear your search or broaden the date range.':'غيّر الحالة أو امسح البحث أو وسّع النطاق الزمني.'}</p><button type="button" className="refresh" onClick={resetHistoryFilters}>{lang==='en'?'Show available trips':'عرض الرحلات المتاحة'}</button></div>}
                </div>
              </aside>
              <div className="nuqati-history-map-panel">
                <div className="nuqati-history-map-heading"><div><strong><MapPin size={17}/>{visibleSelectedTripId?(lang==='en'?`Trip #${visibleSelectedTripId} route`:`مسار الرحلة #${visibleSelectedTripId}`):(lang==='en'?'Historical route map':'خريطة المسارات التاريخية')}</strong><small>{visibleSelectedTripId?(lang==='en'?'Actual recorded GPS points and events':'نقاط GPS والأحداث المسجلة فعليًا'):(lang==='en'?'Select a trip to display its recorded route':'اختر رحلة لعرض مسارها المسجل')}</small></div><div className="nuqati-history-map-actions">
                  {selectedRoute?.points?.length>0&&selectedRoute.trip_id===visibleSelectedTripId&&<button type="button" className="refresh" onClick={()=>exportHistoryKml(selectedRoute)}>{lang==='en'?'Export KML':'تصدير KML'}</button>}
                  {visibleSelectedTripId&&<button type="button" className="refresh" onClick={()=>{historyRouteRequestRef.current++;setSelectedTripId(null);setSelectedRoute(null);setRouteLoading(false);stopRangePlayback();}}><X size={14}/>{lang==='en'?'Deselect':'إلغاء التحديد'}</button>}
                </div></div>
                {routeLoading?<div className="nuqati-history-map-empty" role="status"><RefreshCw size={27}/><strong>{lang==='en'?'Loading recorded route…':'جار تحميل المسار المسجل…'}</strong></div>:activeRoute?<TripLiveMap route={activeRoute} lang={lang} autoPlay={rangePlaying} onPlaybackEnded={nextRangeTrip} layers={historyLayers} overlayRoutes={Object.values(historyRoutes).filter((r:any)=>r.trip_id!==activeRoute.trip_id)}/>:<div className="nuqati-history-map-empty"><Route size={44}/><strong>{lang==='en'?'Select a journey to view its route':'اختر رحلة لعرض مسارها'}</strong><p>{lang==='en'?'Choose a card from the list. You can also compare routes and replay trips using recorded GPS data.':'اختر بطاقة من القائمة، ويمكنك مقارنة المسارات أو إعادة تشغيل الرحلات وفق بيانات GPS المسجلة.'}</p></div>}
                <div className="nuqati-history-map-layers"><span>{lang==='en'?'Map layers':'طبقات الخريطة'}</span><div>{([['route','Route','المسار'],['events','Events','الأحداث'],['labels','Labels','التسميات'],['direction','Direction','الاتجاه']] as const).map(([key,en,ar])=><label key={key}><input type="checkbox" checked={historyLayers[key]} onChange={e=>setHistoryLayers(old=>({...old,[key]:e.target.checked}))}/>{lang==='en'?en:ar}</label>)}</div></div>
                <div className="nuqati-history-overlays"><span>{lang==='en'?`${overlayCount} comparison routes plotted (maximum 8)`:`${overlayCount} مسارات للمقارنة (الحد الأقصى ٨)`}</span>{overlayCount>0&&<button type="button" className="refresh" onClick={()=>setHistoryRoutes({})}>{lang==='en'?'Clear comparisons':'مسح المقارنات'}</button>}</div>
                {selectedRoute&&selectedRoute.trip_id===visibleSelectedTripId&&<details className="nuqati-history-events"><summary><Shield size={15}/>{lang==='en'?'Trip safety events':'أحداث سلامة الرحلة'} <b>{selectedRoute.violations?.length||0}</b></summary>
                  <div className="nuqati-history-event-list">{(selectedRoute.violations||[]).map((ev:any)=><div key={ev.id} className="nuqati-history-event-row"><span><strong>#{ev.id} · {String(ev.type).replaceAll('_',' ')}</strong><small>{saDate(ev.recorded_at)} · {Number(ev.value||0).toFixed(1)}</small></span>{canDeleteTrip&&selectedRoute.status!=='active'&&<button type="button" className="refresh" onClick={()=>void deleteTripEvent(selectedRoute.trip_id,ev.id)}>{lang==='en'?'Delete event':'حذف الحدث'}</button>}</div>)}{!selectedRoute.violations?.length&&<p>{lang==='en'?'No safety events recorded for this trip.':'لم تُسجّل أحداث سلامة لهذه الرحلة.'}</p>}</div>
                  {canDeleteTrip&&selectedRoute.status!=='active'&&<button type="button" className="nuqati-history-danger" onClick={()=>void deleteTripFromWeb(selectedRoute.trip_id,selectedRoute.status)}><Trash2 size={15}/>{lang==='en'?'Permanently delete this trip':'حذف هذه الرحلة نهائيًا'}</button>}
                </details>}
              </div>
            </div>
            <div className="nuqati-history-playbar"><div><strong><Route size={16}/>{lang==='en'?'Journey playback':'إعادة تشغيل الرحلات'}</strong><small>{lang==='en'?'Replay the filtered trips in chronological order. The map contains actual recorded GPS samples.':'شغّل الرحلات المطابقة حسب ترتيبها الزمني. تعرض الخريطة نقاط GPS المسجلة فعليًا.'}</small></div><div className="nuqati-history-playbar-actions"><button type="button" className={rangePlaying?'nuqati-history-stop':'primary'} disabled={!rangePlaying&&(!shown.length||routeLoading)} onClick={()=>rangePlaying?stopRangePlayback():void startRangePlayback([...shown].sort((a:any,b:any)=>(Date.parse(a.started_at)||0)-(Date.parse(b.started_at)||0)||a.id-b.id).map((t:any)=>t.id))}>{rangePlaying?(lang==='en'?'■ Stop playback':'■ إيقاف التشغيل'):(lang==='en'?'▶ Play filtered trips':'▶ تشغيل الرحلات المطابقة')}</button>{rangePlaying&&<span role="status">{rangeCursor+1} / {rangeQueue.length}</span>}</div></div>
            <details className="nuqati-history-register"><summary><span><ArrowUpDown size={17}/>{lang==='en'?'Detailed trip register':'جدول الرحلات التفصيلي'}</span><small>{lang==='en'?`${shown.length} matching records · click to expand`:`${shown.length} سجل مطابق · اضغط للتوسيع`}</small></summary>
              <div className="table-wrap nuqati-trip-table-wrap"><table className="nuqati-trip-table"><thead><tr><th>#</th><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Vehicle':'المركبة'}</th><th>{lang==='en'?'Start · Saudi time':'البداية · السعودية'}</th><th>{lang==='en'?'Stop · Saudi time':'النهاية · السعودية'}</th><th>{lang==='en'?'Duration':'المدة'}</th><th>{lang==='en'?'Distance':'المسافة'}</th><th>{lang==='en'?'Max speed':'السرعة القصوى'}</th><th>{lang==='en'?'Events':'الأحداث'}</th><th>{lang==='en'?'Status':'الحالة'}</th><th>{lang==='en'?'Actions':'الإجراءات'}</th></tr></thead>
                <tbody>{shown.map((t:any)=><tr key={t.id} className={visibleSelectedTripId===t.id?'nuqati-trip-selected':''}><td><strong>#{t.id}</strong></td><td>{t.driver_name||'—'}</td><td dir="auto">{vehicleFor(t)?.plate_number||'—'}</td><td>{saDate(t.started_at)}</td><td>{t.ended_at?saDate(t.ended_at):(lang==='en'?'In progress':'جارية')}</td><td>{duration(t)}</td><td>{Number(t.distance_km||0).toFixed(2)} {lang==='en'?'km':'كم'}</td><td>{t.max_speed_kmh==null?'—':Number(t.max_speed_kmh).toFixed(1)+' km/h'}</td><td><span className={eventCount(t)>0?'nuqati-violation-count is-alert':'nuqati-violation-count'}>{eventCount(t)}</span></td><td><span className={'nuqati-trip-status '+(t.status==='active'?'is-active':'is-completed')}>{t.status==='active'?(lang==='en'?'Active':'جارية'):(lang==='en'?'Completed':'مكتملة')}</span></td><td><div className="nuqati-history-register-actions"><button type="button" className="nuqati-map-button" onClick={()=>void viewTripRoute(t.id)}>{lang==='en'?'View route':'عرض المسار'}</button>{canDeleteTrip&&t.status!=='active'&&<button type="button" className="refresh" onClick={()=>void deleteTripFromWeb(t.id,t.status)} aria-label={lang==='en'?`Delete trip ${t.id}`:`حذف الرحلة ${t.id}`}><Trash2 size={15}/></button>}</div></td></tr>)}</tbody></table>{shown.length===0&&<div className="empty">{lang==='en'?'No matching trips':'لا توجد رحلات مطابقة'}</div>}</div>
            </details>
            <p className="nuqati-history-footnote">{lang==='en'?'GPS paths and safety events reflect uploaded records. Custom date searches may be limited to the first 1,000 results; narrow the range for complete results. Times are displayed in Saudi Arabia time.':'تعرض مسارات GPS وأحداث السلامة البيانات التي رُفعت إلى الخادم. قد يقتصر البحث الزمني المخصص على أول ١٠٠٠ نتيجة؛ قلّص النطاق للحصول على نتائج كاملة. تُعرض الأوقات بتوقيت السعودية.'}</p>
          </div>;
        })():<div className="nuqati-history-no-company"><Route size={32}/><strong>{lang==='en'?'No trip records loaded yet':'لم تُحمّل سجلات الرحلات بعد'}</strong><p>{lang==='en'?'Select a company above and refresh to view its trips.':'اختر شركة من الأعلى ثم حدّث لعرض رحلاتها.'}</p></div>}
      </section>}
      {tab==='overview' && <>
        <section className="nuqati-intelligence-hero">
          <div className="nuqati-intelligence-copy"><span className="hero-pill">NUQATI · DRIVER PERFORMANCE PLATFORM</span>
            <h2>{lang==='en'?'Smarter Driving. Safer Behavior. Better Fleet Performance.':'قيادة أذكى. سلوك أكثر أماناً. أداء أفضل للأسطول.'}</h2>
            <p>{lang==='en'?'Track driver motion, safety points, fleet activity and maintenance insights in one place.':'تابع حركة السائقين ونقاط السلامة ونشاط الأسطول ومؤشرات الصيانة في مكان واحد.'}</p>
            <div className="nuqati-intelligence-tags"><span><Gauge size={15}/> {lang==='en'?'Driver Scores':'نقاط السائقين'}</span><span><Route size={15}/> {lang==='en'?'Motion Monitoring':'مراقبة الحركة'}</span><span><ShieldCheck size={15}/> {lang==='en'?'Safety Insights':'مؤشرات السلامة'}</span><span><Wrench size={15}/> {lang==='en'?'Fleet Maintenance':'صيانة الأسطول'}</span></div>
            <div className="hero-branding">{lang==='en'?'By Al-Riadah Workshop':'من ورشة حلول الريادة'}</div>
          </div>
          <div className="nuqati-intelligence-visual" aria-hidden="true"><div className="nuqati-motion-track"/><div className="nuqati-motion-car"><CarFront size={65}/></div><div className="nuqati-motion-score"><Gauge size={20}/><strong>100</strong><small>PTS</small></div><div className="nuqati-motion-shield"><ShieldCheck size={33}/></div></div>
        </section>
        <div className="nuqati-overview-range nq-overview-filters" aria-label={lang==='en'?'Overview date and time':'تاريخ ووقت النظرة العامة'}>
          <div className="nuqati-overview-presets"><strong className="nq-range-label">{lang==='en'?'Quick range':'فترة سريعة'}</strong>{[[1,'Today','اليوم'],[2,'Yesterday','أمس'],[7,'Week','أسبوع'],[30,'Month','شهر']].map(([days,en,ar])=><button key={String(en)} type="button" className={overviewDays===Number(days)?'is-active':''} aria-pressed={overviewDays===Number(days)} onClick={()=>{if(days===2){const d=new Date();d.setUTCDate(d.getUTCDate()-1);const date=d.toISOString().slice(0,10);setOverviewDays(2);setOverviewFrom(date);setOverviewTo(date);setOverviewFromTime('00:00');setOverviewToTime('23:59');setOverviewApplied({from:date,to:date,fromTime:'00:00',toTime:'23:59'});}else overviewPreset(Number(days));}}>{lang==='en'?en:ar}</button>)}</div>
          <label><span className="nq-overview-date-label">{lang==='en'?'From':'من'}</span> <input type="date" value={overviewFrom} onChange={e=>setOverviewFrom(e.target.value)}/><input type="time" value={overviewFromTime} onChange={e=>setOverviewFromTime(e.target.value)}/></label>
          <label><span className="nq-overview-date-label">{lang==='en'?'To':'إلى'}</span> <input type="date" value={overviewTo} onChange={e=>setOverviewTo(e.target.value)}/><input type="time" value={overviewToTime} onChange={e=>setOverviewToTime(e.target.value)}/></label>
          <button type="button" className="primary" onClick={applyOverviewRange}>{lang==='en'?'Apply':'تطبيق'}</button>
        </div>
        <div className="nuqati-overview-actions"><button type="button" className="refresh" aria-expanded={overviewCustomize} onClick={()=>setOverviewCustomize(!overviewCustomize)}><UserCog size={16}/>{lang==='en'?'Customize Overview':'تخصيص النظرة العامة'}</button></div>
        {overviewCustomize&&<div className="nuqati-overview-customize"><div><strong>{lang==='en'?'Visible overview widgets':'عناصر النظرة العامة'}</strong><p>{lang==='en'?'Your selections are saved in this browser for your account.':'تُحفظ اختياراتك لهذا الحساب في هذا المتصفح.'}</p></div><div className="nuqati-overview-customize-list">{overviewWidgetOptions.map(o=><label key={o.id}><input type="checkbox" checked={showOverviewWidget(o.id)} onChange={e=>setOverviewWidget(o.id,e.target.checked)}/>{lang==='en'?o.en:o.ar}</label>)}</div><button className="refresh" type="button" onClick={()=>{overviewWidgetOptions.forEach(o=>setOverviewWidget(o.id,true));}}>{lang==='en'?'Show all':'إظهار الكل'}</button></div>}
        <section className="nuqati-overview-dashboard">
          <div className="nuqati-overview-toolbar"><div><h2>{lang==='en'?'Fleet utilisation & driver performance':'استخدام الأسطول وأداء السائقين'}</h2><small>{lang==='en'?'Trip starts and driving-behavior events · UTC days · auto-refresh 60s':'بداية الرحلات وأحداث سلوك القيادة · أيام UTC · تحديث كل 60 ثانية'}</small></div><div className="nq-overview-refresh"><button type="button" className="refresh" onClick={loadOverview}><RefreshCw size={15}/>{lang==='en'?'Refresh':'تحديث'}</button></div></div>
          {overviewError&&<p className="notice">{overviewError}</p>}
          {overviewData&&<>
            {showOverviewWidget('kpis')&&<div className="nuqati-overview-kpis">{[
              [lang==='en'?'Trip distance (km)':'مسافة الرحلات (كم)',overviewData.totals.distance_km],
              [lang==='en'?'Trips':'الرحلات',overviewData.totals.trips],
              [lang==='en'?'Drivers with trips':'سائقون لديهم رحلات',overviewData.totals.drivers_active],
              [lang==='en'?'Driving-behavior events':'أحداث سلوك القيادة',overviewData.totals.violations]
            ].map(([name,value])=><article key={String(name)}><small>{name}</small><strong>{Number(value).toLocaleString()}</strong></article>)}</div>}
            <div className="nuqati-overview-grid">
              {showOverviewWidget('distance')&&<OverviewBars title={lang==='en'?'Distance of trips started each day (km)':'مسافة الرحلات التي بدأت يومياً (كم)'} rows={overviewData.days} series={[{key:'distance_km',label:lang==='en'?'Km':'كم',color:'#5b9de3'}]}/>}
              {showOverviewWidget('activity')&&<OverviewBars title={lang==='en'?'Daily trips & driver activity':'الرحلات ونشاط السائقين يومياً'} rows={overviewData.days} series={[{key:'trips',label:lang==='en'?'Trips':'رحلات',color:'#5b9de3'},{key:'drivers_active',label:lang==='en'?'Active drivers':'سائقون نشطون',color:'#a5d84c'}]}/>}
              {showOverviewWidget('violations')&&<OverviewBars title={lang==='en'?'Daily driving-behavior events':'أحداث سلوك القيادة اليومية'} rows={overviewData.days} series={[{key:'speeding',label:lang==='en'?'Speeding':'السرعة',color:'#ef7777'},{key:'harsh_braking',label:lang==='en'?'Braking':'فرملة',color:'#e6ab57'},{key:'harsh_acceleration',label:lang==='en'?'Acceleration':'تسارع',color:'#5baee2'},{key:'harsh_cornering',label:lang==='en'?'Cornering':'انعطاف',color:'#ab87e3'}]}/>}
              {showOverviewWidget('utilization')&&<OverviewBars title={lang==='en'?'Daily vehicle utilization (% with trips)':'استخدام المركبات اليومي (% لديها رحلات)'} rows={(overviewData.days||[]).map((d:any)=>({...d,utilization_pct:overviewData.vehicle_count>0?Math.round(1000*Number(d.vehicles_with_trips||0)/Number(overviewData.vehicle_count))/10:0}))} series={[{key:'utilization_pct',label:lang==='en'?'Utilization %':'نسبة الاستخدام %',color:'#a5d84c'}]}/>}
              {showOverviewWidget('vehicleTrips')&&<OverviewBars title={lang==='en'?'Vehicles with trips vs without trips':'سيارات لديها رحلات مقابل دون رحلات'} rows={overviewData.days} series={[{key:'vehicles_with_trips',label:lang==='en'?'With trips':'لديها رحلات',color:'#5b9de3'},{key:'vehicles_without_trips',label:lang==='en'?'No trips':'دون رحلات',color:'#95a2b1'}]}/>}
              {showOverviewWidget('motion')&&<OverviewMotionDonut moving={Number(overviewData.motion?.moving||0)} stationary={Number(overviewData.motion?.stationary||0)} unknown={Number(overviewData.motion?.unknown||0)} asOf={overviewData.motion?.as_of} lang={lang} error={overviewMotionError}/>}
            </div>
            {showOverviewWidget('insights')&&<div className="nuqati-overview-insights"><article><small>{lang==='en'?'Fleet vehicles':'مركبات الأسطول'}</small><strong>{Number(overviewData.vehicle_count||0).toLocaleString()}</strong></article><article><small>{lang==='en'?'Unique vehicles with trips in period':'المركبات الفريدة ذات الرحلات خلال الفترة'}</small><strong>{Number(overviewData.totals.vehicles_with_trips||0)}</strong></article><article><small>{lang==='en'?'Driving-behavior events':'أحداث سلوك القيادة'}</small><strong>{overviewData.totals.violations}</strong></article></div>}
            <p className="nuqati-chart-note">{lang==='en'?'All daily figures use UTC trip-start dates. Trip distance includes active and completed trips and is assigned to the day the trip started. Utilization = vehicles with trips started that day ÷ current fleet vehicles. No trips does not imply stationary; offline journeys may not be uploaded yet. Activity means drivers with recorded trips. Driving-behavior events include severe variants but exclude GPS speeding-session and geofence notification records.':'تعتمد الأرقام اليومية على تاريخ بدء الرحلة بتوقيت UTC. تشمل المسافة الرحلات الجارية والمكتملة وتُنسب إلى يوم بدء الرحلة. الاستخدام = المركبات ذات الرحلات التي بدأت في اليوم ÷ إجمالي المركبات الحالي. غياب الرحلات لا يعني توقف السيارة؛ وقد تتأخر مزامنة الرحلات. السائق النشط هو من لديه رحلة مسجلة. تشمل أحداث سلوك القيادة الحالات الشديدة وتستثني سجلات جلسات السرعة وإشعارات النطاق الجغرافي.'}</p>
          </>}
        </section>




      </>}
      {tab==='vehicles' && (editingVehicleId!==null
        ? (()=>{const target=vehicles.find(v=>v.id===editingVehicleId);
          return target?<VehicleEditPage key={target.id} vehicle={target}
            companyName={companies.find(c=>c.id===target.company_id)?.name||`#${target.company_id}`}
            drivers={drivers} vehicles={vehicles} lang={lang}
            canEdit={me.role==='super_admin'||me.role==='company_admin'}
            canCorrectOdometer={me.role==='super_admin'}
            onClose={()=>setEditingVehicleId(null)} onSave={saveVehicleEdit}/>
           :<section className="panel"><p>{lang==='en'?'Vehicle not found.':'تعذر العثور على المركبة.'}</p><button type="button" className="refresh" onClick={()=>setEditingVehicleId(null)}>{lang==='en'?'Back to vehicles':'العودة للمركبات'}</button></section>;
        })()
        : <section className="panel"><div className="panel-heading"><div><h3>{lang==='en'?'Vehicle Management':'إدارة السيارات'}</h3><p>{lang==='en'?'Click a vehicle to open its complete editor. Changes are saved once.':'اضغط على المركبة لفتح صفحة تعديل جميع الحقول وحفظها مرة واحدة.'}</p></div></div>
          {(me.role==='super_admin'||me.role==='company_admin')&&<details className="nq-ve-add-form" style={{marginBottom:20}}><summary>{lang==='en'?'+ Add a new vehicle':'+ إضافة مركبة جديدة'}</summary>
          <form onSubmit={addVehicle} className="entry-form" style={{display:(me.role==='super_admin'||me.role==='company_admin')?undefined:'none'}}>
            
            <label>{lang==='en'?'Plate number':'رقم اللوحة'}<input value={plate} onChange={e=>setPlate(e.target.value)} required/></label>
            <label>{lang==='en'?'Make and model':'الماركة والموديل'}<input value={model} onChange={e=>setModel(e.target.value)} maxLength={120} required placeholder="Toyota Camry"/></label>
            <label>{lang==='en'?'Model year':'سنة الموديل'}<input type="number" min="1900" max="2100" step="1" value={vehicleYear} onChange={e=>setVehicleYear(e.target.value)} placeholder="2024"/></label>
            <label>{lang==='en'?'Door number (optional)':'رقم الباب (اختياري)'}<input value={vehicleDoorNumber} onChange={e=>setVehicleDoorNumber(e.target.value)} maxLength={40} placeholder="014"/></label>
            <label>{lang==='en'?'Current odometer (km)':'قراءة العداد الحالية (كم)'}<input type="number" min="0" step="0.1" value={vehicleOdometer} onChange={e=>setVehicleOdometer(e.target.value)} placeholder="85000"/></label>
            <button className="primary"><Plus size={16}/> {lang==='en'?'Add vehicle':'إضافة سيارة'}</button>
          </form></details>}
          {(vehicleViewCompany||vehicleViewSearch.trim())&&<div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Plate / Open details':'اللوحة / فتح التفاصيل'}</th><th>{lang==='en'?'Vehicle':'المركبة'}</th><th>{lang==='en'?'Door number':'رقم الباب'}</th><th>{lang==='en'?'Odometer':'قراءة العداد'}</th><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Company':'الشركة'}</th>{(me.role==='super_admin'||me.role==='company_admin')&&<th>{lang==='en'?'Actions':'الإجراءات'}</th>}</tr></thead>
          <tbody>{visibleVehicleRows.map(v=><tr key={v.id} className="nq-ve-row-clickable" onClick={()=>beginVehicleEdit(v)}><td><button type="button" className="nq-ve-plate-link" onClick={e=>{e.stopPropagation();beginVehicleEdit(v);}}>{v.plate_number}</button></td><td>{v.make_model||'—'}{v.year?` (${v.year})`:''}</td><td>{v.door_number||'—'}</td><td>{v.odometer_km==null?(lang==='en'?'Not recorded':'غير مسجل'):`${v.odometer_km.toLocaleString('en-US')} ${lang==='en'?'km':'كم'}`}</td><td>{drivers.find(d=>d.id===v.assigned_driver_id)?.full_name||(lang==='en'?'Unassigned':'غير معيّن')}</td><td>{companies.find(c=>c.id===v.company_id)?.name||`#${v.company_id}`}</td>{(me.role==='super_admin'||me.role==='company_admin')&&<td><button type="button" data-nq-action="edit" className="refresh" onClick={e=>{e.stopPropagation();beginVehicleEdit(v);}}>{lang==='en'?'Edit all fields':'تعديل جميع الحقول'}</button>{me.role==='super_admin'&&<button type="button" data-nq-action="delete" className="refresh" onClick={e=>{e.stopPropagation();adminDelete('vehicles',v.id);}}>{lang==='en'?'Delete':'حذف'}</button>}</td>}</tr>)}</tbody>
          </table>{!visibleVehicleRows.length&&<div className="nq-selection-empty">{!vehicleViewCompany&&!vehicleViewSearch.trim()?(lang==='en'?'Choose a company or search by plate to display vehicles.':'اختر الشركة أو ابحث برقم اللوحة لعرض المركبات.'):(lang==='en'?'No matching vehicles.':'لا توجد مركبات مطابقة.')}</div>}</div>}
          {!(vehicleViewCompany||vehicleViewSearch.trim())&&<div className="nq-selection-empty">{lang==='en'?'Choose a company or search a plate number to view vehicles.':'اختر شركة أو ابحث عن لوحة لعرض المركبات.'}</div>}
          <details className="nq-ve-add-form"><summary>{lang==='en'?'GPS hardware devices':'أجهزة تتبع GPS'}</summary><HardwareDevices key={activeCompanyId} vehicles={visibleVehicles} token={token} lang={lang}/></details>
        </section>)}
      {tab==='drivers' && (editingDriver!==null ? (()=>{const d=drivers.find(item=>item.id===editingDriver);const details=driverDetails[String(editingDriver)];return driverEditorLoading?<section className="panel"><p>{lang==='en'?'Loading driver details…':'جارٍ تحميل بيانات السائق…'}</p></section>:d&&details?<DriverEditPage key={d.id} driver={d} details={details} lang={lang} companyName={companies.find(c=>c.id===d.company_id)?.name||`#${d.company_id}`} vehicles={vehicles} lastLogin={driverLogins[String(d.id)]} onClose={()=>setEditingDriver(null)} onSave={saveDriverEdit}/>:<section className="panel"><p>{lang==='en'?'Driver details unavailable.':'بيانات السائق غير متاحة.'}</p><button type="button" className="refresh" onClick={()=>setEditingDriver(null)}>{lang==='en'?'Back to drivers':'العودة للسائقين'}</button></section>;})() : <section className="panel"><div className="panel-heading"><div><h3>{lang==='en'?'Driver Management':'إدارة السائقين'}</h3><p>{lang==='en'?'Click any driver to open the unified editor. Edit the profile and assignment, then save once.':'اضغط على السائق لفتح صفحة تعديل البيانات والتعيين وحفظها مرة واحدة.'}</p></div></div><details className="nq-ve-add-form" style={{marginBottom:20}}><summary>{lang==='en'?'+ Add driver':'+ إضافة سائق'}</summary><h3>{lang==='en'?'Add Driver + Enable Login':'إضافة سائق ومنحه صلاحية الدخول'}</h3><details className="nuqati-help" style={{margin:"8px 0 14px"}}><summary style={{cursor:"pointer",color:"#b5d86c",fontWeight:600}}>★ {lang==='en'?'More details':'المزيد من التفاصيل'}</summary><p style={{marginTop:8}}>{lang==='en'?'One action creates the driver, phone login and vehicle assignment. No driver email is needed. Use a private temporary password (12+ characters); the plate is visible publicly and must not be used as a permanent password.':'إجراء واحد لإنشاء السائق وتفعيل الدخول بالهاتف وتعيين السيارة. لا يلزم بريد إلكتروني للسائق. استخدم كلمة مرور مؤقتة خاصة لا تقل عن ١٢ حرفًا، ولا تستخدم رقم اللوحة كلمة مرور.'}</p></details><form onSubmit={addDriver} className="entry-form"><label>{lang==='en'?'Full name':'الاسم الكامل'}<input required value={driverName} onChange={e=>setDriverName(e.target.value)}/></label><label>{lang==='en'?'Mobile number (+966...)':'رقم الجوال (+966...)'}<input required type="tel" value={driverPhone} onChange={e=>setDriverPhone(e.target.value)} placeholder="+9665XXXXXXXX"/></label><label>{lang==='en'?'ID / Iqama number':'رقم الهوية / الإقامة'}<input required value={driverIdNumber} onChange={e=>setDriverIdNumber(e.target.value)}/></label><label>{lang==='en'?'Site / Branch':'الموقع / الفرع'}<input required value={driverSite} onChange={e=>setDriverSite(e.target.value)}/></label><label>{lang==='en'?'Assign available vehicle':'تعيين سيارة متاحة'}<select value={driverVehicle} onChange={e=>setDriverVehicle(e.target.value)}><option value="">{lang==='en'?'No vehicle — driver selects plate in app':'بدون مركبة — يختار السائق اللوحة من التطبيق'}</option>{vehicles.filter(v=>v.company_id===Number(me.role==='super_admin'?activeCompanyId:me.company_id)&&!drivers.some(d=>driverLinks.some(l=>l.driver_id===d.id&&l.vehicle_id===v.id))).map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>{lang==='en'?'Private temporary password (12+ characters)':'كلمة مرور مؤقتة خاصة (١٢ حرفًا على الأقل)'}<input type="password" required minLength={12} value={driverInitialPassword} onChange={e=>setDriverInitialPassword(e.target.value)}/></label><button className="primary">{lang==='en'?'Create Driver & Enable Login':'إنشاء سائق وتفعيل الدخول'}</button></form></details><h3>{lang==='en'?'Registered drivers':'السائقون المسجلون'}</h3><button type="button" className="refresh" onClick={loadDriverExtras}>{lang==='en'?'Refresh app login acknowledgments':'تحديث سجلات دخول التطبيق'}</button>{(driverViewCompany||driverViewSearch.trim())?<div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Name':'الاسم'}</th><th>{lang==='en'?'Phone':'الهاتف'}</th><th>{lang==='en'?'Company':'الشركة'}</th><th>{lang==='en'?'Status':'الحالة'}</th><th>{lang==='en'?'Vehicle':'السيارة'}</th><th>{lang==='en'?'App login acknowledgment (UTC)':'تأكيد دخول التطبيق (بالتوقيت العالمي)'}</th>{me.role==='super_admin'&&<th>{lang==='en'?'Actions':'الإجراءات'}</th>}</tr></thead><tbody>{visibleDriverRows.map(d=><tr key={d.id} className={me.role==='super_admin'?'nq-ve-row-clickable':''} onClick={()=>{if(me.role==='super_admin')void beginDriverEdit(d);}}><td>{me.role==='super_admin'?<button type="button" className="nq-ve-plate-link" onClick={e=>{e.stopPropagation();void beginDriverEdit(d);}}>{d.full_name}</button>:d.full_name}</td><td>{d.phone}</td><td>{companies.find(c=>c.id===d.company_id)?.name}</td><td>{lang==='en'?d.status:({active:'نشط',inactive:'غير نشط',archived:'مؤرشف'} as Record<string,string>)[d.status]||d.status}</td><td>{vehicles.find(v=>v.assigned_driver_id===d.id)?.plate_number||(lang==='en'?'Not assigned':'غير معيّن')}</td><td>{driverLogins[String(d.id)]?new Date(driverLogins[String(d.id)]).toLocaleString(lang==='ar'?'ar-SA':'en-GB'):(lang==='en'?'Never acknowledged':'لم يتم تأكيد الدخول')}</td>{me.role==='super_admin'&&<td><button type="button" data-nq-action="edit" className="refresh" onClick={e=>{e.stopPropagation();void beginDriverEdit(d);}}>{lang==='en'?'Edit all fields':'تعديل جميع الحقول'}</button><button type="button" className="refresh" onClick={e=>{e.stopPropagation();adminDelete('drivers',d.id);}}>{lang==='en'?'Delete':'حذف'}</button></td>}</tr>)}</tbody></table>{!visibleDriverRows.length&&<div className="nq-selection-empty">{lang==='en'?'No matching drivers.':'لا يوجد سائقون مطابقون.'}</div>}</div>:<div className="nq-selection-empty">{lang==='en'?'Choose a company or search for a driver to display records.':'اختر الشركة أو ابحث عن سائق لعرض السجلات.'}</div>}</section>)}
      {tab==='odometer' && <section className="panel"><div className="panel-heading"><div><h3>{lang==='en'?'Record Odometer Reading':'تسجيل قراءة العداد'}</h3><p>{lang==='en'?'GPS distance is an estimate and does not replace the vehicle odometer.':'قراءة GPS تقديرية وليست بديلًا عن عداد السيارة الفعلي.'}</p></div></div><form onSubmit={addReading} className="entry-form" style={{display:canManage?undefined:'none'}}><label>{lang==='en'?'Vehicle':'السيارة'}<select value={readingVehicle} onChange={e=>setReadingVehicle(e.target.value)} required><option value="">{lang==='en'?'Choose vehicle':'اختر السيارة'}</option>{vehicles.map(v=><option value={v.id} key={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>{lang==='en'?'Reading (km)':'القراءة (كم)'}<input type="number" min="0" step="0.1" value={reading} onChange={e=>setReading(e.target.value)} required/></label><label>{lang==='en'?'Source':'المصدر'}<select value={source} onChange={e=>setSource(e.target.value)}><option value="MANUAL">{lang==='en'?'Manual entry':'إدخال يدوي'}</option><option value="GPS">{lang==='en'?'GPS estimate':'تقدير GPS'}</option></select></label><button className="primary"><Plus size={16}/> {lang==='en'?'Save reading':'حفظ القراءة'}</button></form>
<div className="odometer-current-section" style={{marginTop:22}}>
  <h3>{lang==='ar'?'العداد الحالي لكل سيارة':'Current odometer for every vehicle'}</h3>
  <div className="entry-form">
    <label>{lang==='ar'?'السيارة':'Vehicle'}
      <select value={currentOdometerVehicle} onChange={e=>setCurrentOdometerVehicle(e.target.value)}>
        <option value="all">{lang==='ar'?'جميع السيارات':'All vehicles'}</option>
        {vehicles.filter(v=>listCompany==='all'||String(v.company_id)===listCompany).map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}
      </select>
    </label>
    <label>{lang==='ar'?'العداد من (كم)':'Odometer from (km)'}
      <input type="number" min="0" step="0.1" value={currentOdometerMin} onChange={e=>setCurrentOdometerMin(e.target.value)} placeholder={lang==='ar'?'الحد الأدنى':'Minimum km'}/>
    </label>
    <label>{lang==='ar'?'العداد إلى (كم)':'Odometer to (km)'}
      <input type="number" min="0" step="0.1" value={currentOdometerMax} onChange={e=>setCurrentOdometerMax(e.target.value)} placeholder={lang==='ar'?'الحد الأعلى':'Maximum km'}/>
    </label>
    <button type="button" className="refresh" onClick={()=>{setCurrentOdometerVehicle('all');setCurrentOdometerMin('');setCurrentOdometerMax('');}}>{lang==='ar'?'مسح الفلاتر':'Clear filters'}</button>
  </div>
  <div className="table-wrap"><table><thead><tr>
    <th>{lang==='ar'?'السيارة':'Vehicle'}</th><th>{lang==='ar'?'الشركة':'Company'}</th><th>{lang==='ar'?'العداد الحالي (كم)':'Current odometer (km)'}</th>
  </tr></thead><tbody>
    {visibleVehicles.filter(v=>
      (currentOdometerVehicle==='all'||String(v.id)===currentOdometerVehicle)&&
      ((currentOdometerMin===''&&currentOdometerMax==='')||(
        v.odometer_km!=null&&
        (currentOdometerMin===''||v.odometer_km>=Number(currentOdometerMin))&&
        (currentOdometerMax===''||v.odometer_km<=Number(currentOdometerMax))
      ))
    ).map(v=><tr key={v.id}>
      <td>{v.plate_number} — {v.make_model}</td>
      <td>{companies.find(c=>c.id===v.company_id)?.name||'#'+v.company_id}</td>
      <td>{v.odometer_km==null?'—':v.odometer_km.toLocaleString('en-US')}</td>
    </tr>)}
  </tbody></table>
  {!visibleVehicles.some(v=>(currentOdometerVehicle==='all'||String(v.id)===currentOdometerVehicle)&&((currentOdometerMin===''&&currentOdometerMax==='')||(v.odometer_km!=null&&(currentOdometerMin===''||v.odometer_km>=Number(currentOdometerMin))&&(currentOdometerMax===''||v.odometer_km<=Number(currentOdometerMax)))))&&<div className="empty">{lang==='ar'?'لا توجد سيارات تطابق الفلاتر':'No vehicles match these filters.'}</div>}
  </div>
</div>

<div className="odometer-history-section" style={{marginTop:22,display:'grid',gap:14}}>
  <h3>{lang==='ar'?'سجل قراءات العداد المحفوظة لجميع السيارات':'Odometer History — Saved Readings for All Vehicles'}</h3>
  <div className="entry-form">
    <label>{lang==='ar'?'السيارة':'Vehicle'}<select value={odometerHistoryVehicle} onChange={e=>{setOdometerHistoryVehicle(e.target.value);clearOdometerSearch();}}><option value="all">{lang==='ar'?'جميع السيارات':'All vehicles'}</option>{vehicles.filter(v=>listCompany==='all'||String(v.company_id)===listCompany).map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label>
    <label>{lang==='ar'?'من تاريخ ووقت':'From date/time'}<input type="datetime-local" value={odometerHistoryFrom} onChange={e=>{setOdometerHistoryFrom(e.target.value);clearOdometerSearch();}}/></label>
    <label>{lang==='ar'?'إلى تاريخ ووقت':'To date/time'}<input type="datetime-local" value={odometerHistoryTo} onChange={e=>{setOdometerHistoryTo(e.target.value);clearOdometerSearch();}}/></label>
    <label>{lang==='ar'?'المصدر':'Source'}<select value={odometerHistorySource} onChange={e=>{setOdometerHistorySource(e.target.value);clearOdometerSearch();}}><option value="all">{lang==='ar'?'جميع المصادر':'All sources'}</option><option value="MANUAL">{lang==='ar'?'يدوي':'Manual'}</option><option value="GPS">{lang==='ar'?'تقدير GPS':'GPS estimate'}</option></select></label>
    <button type="button" className="primary" onClick={loadOdometerHistory} disabled={odometerHistoryLoading}><Search size={15}/>{odometerHistoryLoading?(lang==='ar'?'جاري البحث...':'Searching...'):(lang==='ar'?'بحث':'Search')}</button>
    <button type="button" className="refresh" onClick={()=>{setOdometerHistoryVehicle('all');setOdometerHistorySource('all');setOdometerHistoryFrom('');setOdometerHistoryTo('');clearOdometerSearch();}}>{lang==='ar'?'مسح':'Clear'}</button>
  </div>
{odometerHistorySearched&&<div className="table-wrap"><table><thead><tr><th>{lang==='ar'?'التاريخ':'Date'}</th><th>{lang==='ar'?'السيارة':'Vehicle'}</th><th>{lang==='ar'?'الشركة':'Company'}</th><th>{lang==='ar'?'القراءة (كم)':'Reading (km)'}</th><th>{lang==='ar'?'المصدر':'Source'}</th><th>{lang==='ar'?'ملاحظات':'Notes'}</th></tr></thead><tbody>{odometerRecords.filter(r=>(listCompany==='all'||String(r.company_id)===listCompany)&&(odometerHistoryVehicle==='all'||String(r.vehicle_id)===odometerHistoryVehicle)).map(r=>{const v=vehicles.find(v=>v.id===r.vehicle_id);return <tr key={r.id}><td>{new Date(r.created_at).toLocaleString(lang==='ar'?'ar-SA':'en-GB')}</td><td>{v?`${v.plate_number} — ${v.make_model}`:`#${r.vehicle_id}`}</td><td>{companies.find(c=>c.id===r.company_id)?.name||'#'+r.company_id}</td><td>{r.reading_km.toLocaleString('en-US')}</td><td>{lang==='en'?({MANUAL:'Manual',GPS:'GPS estimate'} as Record<string,string>)[r.source]||r.source:({MANUAL:'يدوي',GPS:'تقدير GPS'} as Record<string,string>)[r.source]||r.source}</td><td>{r.note==='تم الإدخال من لوحة نقاطي'?(lang==='en'?'Entered from Nuqati dashboard':r.note):r.note||'—'}</td></tr>;})}</tbody></table>{odometerRecords.filter(r=>(listCompany==='all'||String(r.company_id)===listCompany)&&(odometerHistoryVehicle==='all'||String(r.vehicle_id)===odometerHistoryVehicle)).length===0&&<div className="empty">{lang==='ar'?'لا توجد قراءات مطابقة':'No matching readings'}</div>}</div>}
  <p style={{opacity:.75,fontSize:12}}>{lang==='ar'?'يعرض البحث حتى 500 قراءة مطابقة.':'Search returns up to 500 matching readings.'}</p>
  {!odometerHistorySearched&&<div className="empty">{lang==='ar'?'اختر معايير البحث ثم اضغط بحث لعرض القراءات المحفوظة.':'Select search filters and press Search to display saved readings.'}</div>}
</div>
<div className="tip">{lang==='en'?'Readings are saved with source and date. Editing or deleting historical readings is not supported in this version.':'تُحفظ القراءات بسجل مستقل مع المصدر والتاريخ. لا تدعم النسخة الحالية تصحيح القراءات السابقة أو حذفها من الواجهة.'}</div>
</section>}
      {tab==='mobile-diagnostics' && <MobileDiagnostics token={token} lang={lang}/>}
      {tab==='maintenance' && <><section className="panel"><div className="panel-heading"><div><h3>{lang==='en'?'Odometer-Based Maintenance Reminders':'تذكيرات الصيانة حسب العداد'}</h3><details className="nuqati-help" style={{margin:"8px 0 14px"}}><summary style={{cursor:"pointer",color:"#b5d86c",fontWeight:600}}>★ {lang==='en'?'More details':'المزيد من التفاصيل'}</summary><p style={{marginTop:8}}>{lang==='en'?'Select a vehicle, enter the last service odometer and service interval. Reminders are estimates and require checking the actual odometer.':'لا حاجة لربط نظام ورشة أو تصوير اللوحة. اختر السيارة وسجل آخر صيانة والفاصل بالكيلومتر. التنبيهات تقديرية وتحتاج مراجعة العداد الفعلي.'}</p></details></div></div><div className="maintenance-vehicle-filter"><label>{lang==='en'?'Select vehicle to view maintenance':'اختر السيارة لعرض الصيانة'}<select value={maintenanceVehicle} onChange={e=>setMaintenanceVehicle(e.target.value)}><option value="">{lang==='en'?'— Select a vehicle —':'— اختر سيارة —'}</option>{vehicles.map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label>{maintenanceVehicle&&<div className="maintenance-vehicle-summary"><strong>{vehicles.find(v=>String(v.id)===maintenanceVehicle)?.plate_number}</strong><span>{lang==='en'?'Current odometer':'العداد الحالي'}: {schedules.find(m=>String(m.vehicle_id)===maintenanceVehicle&&m.current_odometer_km!=null)?.current_odometer_km?.toLocaleString('en-US')??(lang==='en'?'Unknown':'غير معروف')} {lang==='en'?'km':'كم'}</span><span>{lang==='en'?'Services':'الخدمات'}: {schedules.filter(m=>String(m.vehicle_id)===maintenanceVehicle).length}</span></div>}</div>{maintenanceVehicle&&driverServiceHistory.length>0&&<div className="panel" style={{marginBottom:16}}><h3>{lang==='en'?'Driver-reported maintenance history':'سجل الصيانة حسب إفادة السائق'}</h3><p style={{opacity:.8}}>{lang==='en'?'Unknown means the driver could not confirm that service. It is not a verified service completion.':'غير معروف يعني أن السائق لم يتمكن من تأكيد الصيانة، وليس إثباتًا على إتمامها.'}</p><div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Driver':'السائق'}</th><th>{lang==='en'?'Service':'الصيانة'}</th><th>{lang==='en'?'Driver answer':'إفادة السائق'}</th><th>{lang==='en'?'Mileage':'العداد'}</th><th>{lang==='en'?'Interval':'الفاصل'}</th></tr></thead><tbody>{driverServiceHistory.map((r,i)=><tr key={`${r.driver_id}-${r.service_type}-${i}`}><td>{r.driver_name}</td><td>{({ENGINE_OIL:lang==='en'?'Engine oil':'زيت المحرك',SPARK_PLUGS:lang==='en'?'Spark plugs':'البواجي',TRANSMISSION_OIL:lang==='en'?'Gear oil':'زيت القير',TYRES:lang==='en'?'Tyres':'الإطارات'} as Record<string,string>)[r.service_type]||r.service_type}</td><td>{r.knowledge==='UNKNOWN'?(lang==='en'?'Does not know':'لا يعرف'):(r.reading_type==='NEXT'?(lang==='en'?'Next change':'التغيير القادم'):(lang==='en'?'Last change':'آخر تغيير'))}</td><td>{r.reading_km==null?'—':`${r.reading_km.toLocaleString('en-US')} km`}</td><td>{r.interval_km==null?'—':`${r.interval_km.toLocaleString('en-US')} km`}</td></tr>)}</tbody></table></div></div>}<form onSubmit={saveSchedule} className="entry-form" style={{display:canManage&&!!maintenanceVehicle?undefined:'none'}}><label>{lang==='en'?'Service':'الخدمة'}<select value={serviceType} onChange={e=>{setServiceType(e.target.value);setInterval(e.target.value==='ENGINE_OIL'?'5000':e.target.value==='SPARK_PLUGS'||e.target.value==='TYRES'?'60000':'80000')}}><option value="ENGINE_OIL">{lang==='en'?'Engine oil':'زيت المحرك'}</option><option value="SPARK_PLUGS">{lang==='en'?'Spark plugs':'البواجي'}</option><option value="TRANSMISSION_OIL">{lang==='en'?'Transmission oil':'زيت القير'}</option><option value="TYRES">{lang==='en'?'Tyre replacement (60,000 km / 1 year)':'تغيير الإطارات (٦٠٬٠٠٠ كم / سنة)'}</option></select></label><label>{lang==='en'?'Interval (km)':'الفاصل (كم)'}<input type="number" min="1" value={interval} onChange={e=>setInterval(e.target.value)} required/></label><label>{lang==='en'?'Last service odometer (km)':'عداد آخر صيانة (كم)'}<input type="number" min="0" value={lastService} onChange={e=>setLastService(e.target.value)} required/></label><label>{lang==='en'?'Notify before due (km)':'التنبيه قبل الموعد (كم)'}<input type="number" min="0" value={warningBefore} onChange={e=>setWarningBefore(e.target.value)} required/></label><button className="primary"><Plus size={16}/> {lang==='en'?'Save / Update Reminder':'حفظ / تحديث التذكير'}</button></form><div className="table-wrap"><table><thead><tr><th>{lang==='en'?'Vehicle':'السيارة'}</th><th>{lang==='en'?'Service':'الخدمة'}</th><th>{lang==='en'?'Next due':'الموعد القادم'}</th><th>{lang==='en'?'Remaining':'المتبقي'}</th><th>{lang==='en'?'Status':'الحالة'}</th>{me.role==='super_admin'&&<th>{lang==='en'?'Actions':'الإجراءات'}</th>}</tr></thead><tbody>{schedules.filter(m=>String(m.vehicle_id)===maintenanceVehicle).map(m=><tr key={m.id}><td>{vehicles.find(v=>v.id===m.vehicle_id)?.plate_number||m.vehicle_id}</td><td>{(lang==='en'?({ENGINE_OIL:'Engine oil',SPARK_PLUGS:'Spark plugs',TRANSMISSION_OIL:'Transmission oil',TYRES:'Tyres'} as Record<string,string>):({ENGINE_OIL:'زيت المحرك',SPARK_PLUGS:'البواجي',TRANSMISSION_OIL:'زيت القير',TYRES:'الإطارات'} as Record<string,string>))[m.service_type]||m.service_type}</td><td>{m.next_due_km.toLocaleString('en-US')} كم</td><td>{m.remaining_km==null?'غير معروف':`${Math.round(m.remaining_km).toLocaleString('en-US')} ${lang==='en'?'km':'كم'}`}</td><td><span className="status">{(lang==='en'?({OK:'OK',DUE_SOON:'Due soon',OVERDUE:'Overdue',UNKNOWN:'Enter odometer'} as Record<string,string>):({OK:'سليم',DUE_SOON:'قريب',OVERDUE:'مستحق',UNKNOWN:'أدخل العداد'} as Record<string,string>))[m.status]||m.status}</span></td>{me.role==='super_admin'&&<td><button className="refresh" onClick={()=>adminDelete('maintenance-schedules',m.id)}>{lang==='en'?'Delete':'حذف'}</button></td>}</tr>)}</tbody></table>{maintenanceVehicle && !schedules.some(m=>String(m.vehicle_id)===maintenanceVehicle)&&<div className="empty">{lang==='en'?'No maintenance services configured for this vehicle.':'لا توجد خدمات صيانة مسجلة لهذه السيارة.'}</div>}{!maintenanceVehicle&&<div className="empty">{lang==='en'?'Select a vehicle above to see its maintenance services.':'اختر سيارة من الأعلى لعرض خدمات صيانتها.'}</div>}</div><div className="tip">{lang==='en'?'These are in-dashboard alerts, not automatic phone notifications. Adjust service intervals to manufacturer recommendations.':'هذه تنبيهات داخل لوحة الاختبار، وليست إشعارات هاتفية آلية بعد. فترات الخدمة قابلة للتعديل حسب توصيات الشركة المصنعة.'}</div></section><SmartOilEstimator vehicleId={maintenanceVehicle} lang={lang} request={request}/></>}
      <footer>{lang==='en'?'Nuqati by Al-Riadah Workshop':'نقاطي من ورشة حلول الريادة'} © {new Date().getFullYear()} — {lang==='en'?'Al-Riadah Automotive Maintenance':'حلول الريادة لصيانة السيارات'} <span>{lang==='en'?'Dark blue · Lime green':'الأزرق الداكن · الأخضر الليموني'}</span></footer>
    </main>
  </div>;
}
