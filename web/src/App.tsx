import { useEffect, useState } from 'react';
import { Activity, CarFront, Users, Route, Gauge, Wrench, Plus, RefreshCw, ShieldCheck } from 'lucide-react';

const API = import.meta.env.VITE_API_BASE_URL ?? '';
type Vehicle = {id:number; company_id:number; plate_number:string; make_model:string; year:number|null; odometer_km:number|null};
type Driver = {id:number; company_id:number; full_name:string; phone:string; status:string};
type Company = {id:number; name:string};
export default function App() {
  const [tab,setTab] = useState<'overview'|'vehicles'|'drivers'|'odometer'|'maintenance'>('overview');
  const [companies,setCompanies] = useState<Company[]>([]);
  const [vehicles,setVehicles] = useState<Vehicle[]>([]);
  const [drivers,setDrivers] = useState<Driver[]>([]);
  const [stats,setStats] = useState({companies:0,drivers:0,vehicles:0,trips_active:0});
  const [message,setMessage] = useState('');
  const [companyName,setCompanyName] = useState('حلول الريادة - تجربة');
  const [plate,setPlate] = useState('أ ب ج 1234');
  const [model,setModel] = useState('Toyota Camry');
  const [driverName,setDriverName] = useState('سائق تجريبي');
  const [driverPhone,setDriverPhone] = useState('');
  const [readingVehicle,setReadingVehicle] = useState('');
  const [reading,setReading] = useState('');
  const [source,setSource] = useState('MANUAL');
  type Schedule = {id:number;vehicle_id:number;service_type:string;interval_km:number;last_service_km:number;next_due_km:number;current_odometer_km:number|null;remaining_km:number|null;status:string};
  const [schedules,setSchedules] = useState<Schedule[]>([]);
  const [serviceType,setServiceType] = useState('ENGINE_OIL');
  const [interval,setInterval] = useState('5000');
  const [lastService,setLastService] = useState('0');
  const [warningBefore,setWarningBefore] = useState('500');
  async function request(path:string, options?:RequestInit) {
    const r = await fetch(`${API}${path}`, {headers:{'Content-Type':'application/json',...(options?.headers||{})},...options});
    if(!r.ok) { const body = await r.json().catch(()=>({})); throw new Error(body.detail || `HTTP ${r.status}`); }
    return r.json();
  }
  async function load() {
    try {
      const [s,c,v,d,m] = await Promise.all([request('/api/v1/dashboard'),request('/api/v1/companies'),request('/api/v1/vehicles'),request('/api/v1/drivers'),request('/api/v1/maintenance-schedules')]);
      setStats(s); setCompanies(c); setVehicles(v); setDrivers(d); setSchedules(m); setMessage('');
      if(!readingVehicle && v[0]) setReadingVehicle(String(v[0].id));
    } catch { setMessage('تعذر الاتصال بالخادم. شغّل API أولًا من مجلد backend.'); }
  }
  useEffect(()=>{void load()},[]);
  async function addCompany(e:React.FormEvent) { e.preventDefault(); try { await request('/api/v1/companies',{method:'POST',body:JSON.stringify({name:companyName})}); await load(); setMessage('تمت إضافة الشركة.'); } catch(err) {setMessage(String(err));} }
  async function addVehicle(e:React.FormEvent) { e.preventDefault(); if(!companies[0]) {setMessage('أضف شركة أولًا.'); return;} try { await request('/api/v1/vehicles',{method:'POST',body:JSON.stringify({company_id:companies[0].id,plate_number:plate,make_model:model})}); await load(); setMessage('تمت إضافة السيارة.'); } catch(err) {setMessage(String(err));} }
  async function addDriver(e:React.FormEvent) { e.preventDefault(); if(!companies[0]) {setMessage('أضف شركة أولًا.'); return;} try { await request('/api/v1/drivers',{method:'POST',body:JSON.stringify({company_id:companies[0].id,full_name:driverName,phone:driverPhone})}); await load(); setMessage('تمت إضافة السائق.'); } catch(err) {setMessage(String(err));} }
  async function addReading(e:React.FormEvent) { e.preventDefault(); if(!readingVehicle || !vehicles.length) {setMessage('أضف سيارة أولًا.'); return;} const v=vehicles.find(x=>x.id===Number(readingVehicle)); if(!v) return; try { await request('/api/v1/odometer-readings',{method:'POST',body:JSON.stringify({company_id:v.company_id,vehicle_id:v.id,reading_km:Number(reading),source,note:'تم الإدخال من لوحة نقاطي'})}); await load(); setMessage('تم حفظ قراءة العداد.'); setReading(''); } catch(err) {setMessage(String(err));} }
  async function saveSchedule(e:React.FormEvent) { e.preventDefault(); const v=vehicles.find(x=>x.id===Number(readingVehicle)); if(!v) {setMessage('اختر سيارة أولًا.');return;} try {await request('/api/v1/maintenance-schedules',{method:'PUT',body:JSON.stringify({company_id:v.company_id,vehicle_id:v.id,service_type:serviceType,interval_km:Number(interval),last_service_km:Number(lastService),warning_before_km:Number(warningBefore)})});await load();setMessage('تم حفظ جدول الصيانة.');}catch(err){setMessage(String(err));}}
  const nav = [{id:'overview',label:'نظرة عامة',icon:Activity},{id:'vehicles',label:'السيارات',icon:CarFront},{id:'drivers',label:'السائقون',icon:Users},{id:'odometer',label:'قراءة العداد',icon:Gauge},{id:'maintenance',label:'تنبيهات الصيانة',icon:Wrench}] as const;
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><div className="brand-mark">ن</div><div><strong>نقاطي</strong><small>حلول الريادة</small></div></div>
      <div className="side-caption">إدارة الأسطول</div>{nav.map(n=><button key={n.id} className={`nav-item ${tab===n.id?'active':''}`} onClick={()=>setTab(n.id)}><n.icon size={18}/>{n.label}</button>)}
      <div className="sidebar-bottom"><ShieldCheck size={18}/><span>نسخة تجريبية</span></div>
    </aside>
    <main className="main"><header className="topbar"><div><span className="eyebrow">منصة أداء السائقين</span><h1>{nav.find(n=>n.id===tab)?.label}</h1></div><button className="refresh" onClick={()=>void load()}><RefreshCw size={16}/> تحديث البيانات</button></header>
      {message && <div className="notice" role="status">{message}</div>}
      {tab==='overview' && <>
        <section className="hero"><div><span className="hero-pill">NUQATI FLEET INTELLIGENCE</span><h2>قيادة أذكى، أسطول أكثر كفاءة.</h2><p>قيادة آمنة وتذكيرات صيانة مستقلة بناءً على قراءات العداد.</p></div><div className="hero-icon"><Route size={54}/></div></section>
        <section className="stats">{[{label:'الشركات',value:stats.companies,icon:Wrench},{label:'السيارات',value:stats.vehicles,icon:CarFront},{label:'السائقون',value:stats.drivers,icon:Users},{label:'الرحلات النشطة',value:stats.trips_active,icon:Route}].map(x=><article className="stat-card" key={x.label}><div className="stat-icon"><x.icon size={20}/></div><span>{x.label}</span><strong>{x.value}</strong></article>)}</section>
        <section className="content-grid"><article className="panel"><div className="panel-heading"><div><h3>البدء السريع</h3><p>أدخل بيانات تجريبية لتجربة لوحة الإدارة.</p></div></div><form onSubmit={addCompany} className="form-row"><label>اسم الشركة<input value={companyName} onChange={e=>setCompanyName(e.target.value)} required /></label><button className="primary"><Plus size={16}/> إضافة شركة</button></form><div className="tip">للتجربة: أضف شركة، ثم انتقل إلى السيارات والسائقين. هذه النسخة لا تحتوي بعد على تسجيل دخول إنتاجي.</div></article><article className="panel"><div className="panel-heading"><div><h3>مراحل الربط</h3><p>ما هو متاح الآن وما يأتي لاحقًا</p></div></div><div className="milestone done"><span>1</span><div><b>إدخال البيانات يدويًا</b><small>الشركات والسيارات والسائقون والعداد</small></div><em>أساسي</em></div><div className="milestone"><span>2</span><div><b>تطبيق GPS</b><small>الرحلات والتنبيهات والتتبع الخلفي</small></div><em>قادم</em></div><div className="milestone done"><span>3</span><div><b>تنبيهات الصيانة</b><small>جدول مستقل لكل مركبة دون ربط بنظام ورشة</small></div><em>أساسي</em></div></article></section>
      </>}
      {tab==='vehicles' && <section className="panel"><div className="panel-heading"><div><h3>إدارة السيارات</h3><p>تُضاف السيارة إلى أول شركة مسجلة في النسخة التجريبية.</p></div></div><form onSubmit={addVehicle} className="entry-form"><label>رقم اللوحة<input value={plate} onChange={e=>setPlate(e.target.value)} required/></label><label>الماركة والموديل<input value={model} onChange={e=>setModel(e.target.value)} required/></label><button className="primary"><Plus size={16}/> إضافة سيارة</button></form><div className="table-wrap"><table><thead><tr><th>اللوحة</th><th>المركبة</th><th>قراءة العداد</th><th>الشركة</th></tr></thead><tbody>{vehicles.map(v=><tr key={v.id}><td>{v.plate_number}</td><td>{v.make_model||'—'}</td><td>{v.odometer_km==null?'غير مسجل':`${v.odometer_km.toLocaleString('en-US')} كم`}</td><td>{companies.find(c=>c.id===v.company_id)?.name||`#${v.company_id}`}</td></tr>)}</tbody></table>{!vehicles.length&&<div className="empty">لا توجد سيارات حتى الآن.</div>}</div></section>}
      {tab==='drivers' && <section className="panel"><div className="panel-heading"><div><h3>إدارة السائقين</h3><p>إضافة بيانات السائقين يدويًا.</p></div></div><form onSubmit={addDriver} className="entry-form"><label>اسم السائق<input value={driverName} onChange={e=>setDriverName(e.target.value)} required/></label><label>رقم الجوال<input value={driverPhone} onChange={e=>setDriverPhone(e.target.value)} /></label><button className="primary"><Plus size={16}/> إضافة سائق</button></form><div className="table-wrap"><table><thead><tr><th>الاسم</th><th>الجوال</th><th>الشركة</th><th>الحالة</th></tr></thead><tbody>{drivers.map(d=><tr key={d.id}><td>{d.full_name}</td><td>{d.phone||'—'}</td><td>{companies.find(c=>c.id===d.company_id)?.name||`#${d.company_id}`}</td><td><span className="status">{d.status==='active'?'نشط':d.status}</span></td></tr>)}</tbody></table>{!drivers.length&&<div className="empty">لا يوجد سائقون حتى الآن.</div>}</div></section>}
      {tab==='odometer' && <section className="panel"><div className="panel-heading"><div><h3>تسجيل قراءة العداد</h3><p>قراءة GPS تقديرية وليست بديلًا عن عداد السيارة الفعلي.</p></div></div><form onSubmit={addReading} className="entry-form"><label>السيارة<select value={readingVehicle} onChange={e=>setReadingVehicle(e.target.value)} required><option value="">اختر السيارة</option>{vehicles.map(v=><option value={v.id} key={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>القراءة (كم)<input type="number" min="0" step="0.1" value={reading} onChange={e=>setReading(e.target.value)} required/></label><label>المصدر<select value={source} onChange={e=>setSource(e.target.value)}><option value="MANUAL">إدخال يدوي</option><option value="GPS">تقدير GPS</option></select></label><button className="primary"><Plus size={16}/> حفظ القراءة</button></form><div className="tip">تُحفظ القراءات بسجل مستقل مع المصدر والتاريخ. لا تدعم النسخة الحالية تصحيح القراءات السابقة أو حذفها من الواجهة.</div></section>}
      {tab==='maintenance' && <section className="panel"><div className="panel-heading"><div><h3>تذكيرات الصيانة حسب العداد</h3><p>لا حاجة لربط نظام ورشة أو تصوير اللوحة. اختر السيارة وسجل آخر صيانة والفاصل بالكيلومتر. التنبيهات تقديرية وتحتاج مراجعة العداد الفعلي.</p></div></div><form onSubmit={saveSchedule} className="entry-form"><label>السيارة<select value={readingVehicle} onChange={e=>setReadingVehicle(e.target.value)} required><option value="">اختر السيارة</option>{vehicles.map(v=><option value={v.id} key={v.id}>{v.plate_number} — {v.make_model}</option>)}</select></label><label>الخدمة<select value={serviceType} onChange={e=>{setServiceType(e.target.value);setInterval(e.target.value==='ENGINE_OIL'?'5000':e.target.value==='SPARK_PLUGS'?'60000':'80000')}}><option value="ENGINE_OIL">زيت المحرك</option><option value="SPARK_PLUGS">البواجي</option><option value="TRANSMISSION_OIL">زيت القير</option></select></label><label>الفاصل (كم)<input type="number" min="1" value={interval} onChange={e=>setInterval(e.target.value)} required/></label><label>عداد آخر صيانة (كم)<input type="number" min="0" value={lastService} onChange={e=>setLastService(e.target.value)} required/></label><label>التنبيه قبل الموعد (كم)<input type="number" min="0" value={warningBefore} onChange={e=>setWarningBefore(e.target.value)} required/></label><button className="primary"><Plus size={16}/> حفظ / تحديث التذكير</button></form><div className="table-wrap"><table><thead><tr><th>السيارة</th><th>الخدمة</th><th>الموعد القادم</th><th>المتبقي</th><th>الحالة</th></tr></thead><tbody>{schedules.map(m=><tr key={m.id}><td>{vehicles.find(v=>v.id===m.vehicle_id)?.plate_number||m.vehicle_id}</td><td>{({ENGINE_OIL:'زيت المحرك',SPARK_PLUGS:'البواجي',TRANSMISSION_OIL:'زيت القير'} as Record<string,string>)[m.service_type]||m.service_type}</td><td>{m.next_due_km.toLocaleString('en-US')} كم</td><td>{m.remaining_km==null?'غير معروف':`${Math.round(m.remaining_km).toLocaleString('en-US')} كم`}</td><td><span className="status">{({OK:'سليم',DUE_SOON:'قريب',OVERDUE:'مستحق',UNKNOWN:'أدخل العداد'} as Record<string,string>)[m.status]||m.status}</span></td></tr>)}</tbody></table>{!schedules.length&&<div className="empty">أضف جدول صيانة لبدء التذكيرات.</div>}</div><div className="tip">هذه تنبيهات داخل لوحة الاختبار، وليست إشعارات هاتفية آلية بعد. فترات الخدمة قابلة للتعديل حسب توصيات الشركة المصنعة.</div></section>}
      <footer>نقاطي © {new Date().getFullYear()} — حلول الريادة لصيانة السيارات <span>الأزرق الداكن · الأخضر الليموني</span></footer>
    </main>
  </div>;
}
