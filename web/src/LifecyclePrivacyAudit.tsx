import {useEffect,useMemo,useState} from 'react';

type LifecycleRecord={event_id:string;company_id:number;driver_id:number;event_type:string;occurred_at:string;received_at:string};
type Person={id:number;full_name?:string;name?:string;company_id?:number};
type Company={id:number;name:string};
type Props={request:(path:string)=>Promise<any>;lang:string;drivers:Person[];companies:Company[];isSuperAdmin:boolean};

const labels:Record<string,[string,string]>={
 first_authenticated_launch:['First authenticated launch','أول تشغيل بعد تسجيل الدخول'],
 camera_monitoring_disabled:['Camera monitoring disabled','تعطيل مراقبة الكاميرا'],
 camera_monitoring_enabled:['Camera monitoring enabled','تفعيل مراقبة الكاميرا'],
 login:['Login','تسجيل الدخول'],
 logout:['Logout','تسجيل الخروج']
};
const csvCell=(v:unknown)=>'"'+String(v??'').replace(/"/g,'""')+'"';

export default function LifecyclePrivacyAudit({request,lang,drivers,companies,isSuperAdmin}:Props){
 const ar=lang==='ar';
 const [records,setRecords]=useState<LifecycleRecord[]>([]);
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState('');
 const [company,setCompany]=useState('');
 const [driver,setDriver]=useState('');
 const [event,setEvent]=useState('');
 const [from,setFrom]=useState('');
 const [to,setTo]=useState('');
 const [applied,setApplied]=useState({company:'',driver:'',event:'',from:'',to:''});
 const load=async()=>{
  setLoading(true);setError('');
  try{
   const data=await request('/api/v1/fleet/lifecycle-audit?limit=500');
   if(!Array.isArray(data))throw Error('Unexpected audit response');
   setRecords(data);
  }catch(e){setError(String(e));}
  finally{setLoading(false);}
 };
 useEffect(()=>{void load();},[]);
 const filtered=useMemo(()=>records.filter(r=>{
  if(applied.company&&String(r.company_id)!==applied.company)return false;
  if(applied.driver&&String(r.driver_id)!==applied.driver)return false;
  if(applied.event&&r.event_type!==applied.event)return false;
  const t=Date.parse(r.occurred_at);
  if(applied.from&&t<Date.parse(applied.from+'T00:00:00'))return false;
  if(applied.to&&t>Date.parse(applied.to+'T23:59:59.999'))return false;
  return true;
 }),[records,applied]);
 const exportCsv=()=>{
  const header=['event_id','company','driver','event_type','occurred_at','received_at'];
  const rows=filtered.map(r=>[r.event_id,companies.find(c=>c.id===r.company_id)?.name??r.company_id,drivers.find(d=>d.id===r.driver_id)?.full_name??r.driver_id,r.event_type,r.occurred_at,r.received_at]);
  const csv='\uFEFF'+[header,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='nuqati-device-lifecycle-audit.csv';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
 return <div style={{marginTop:24}}>
  <h3>{ar?'سجل دخول وخروج السائق وتغييرات الكاميرا':'Driver login, logout & camera preference audit'}</h3>
  <p>{ar?'أحداث الجهاز المرسلة من التطبيق، بدون تسجيل صور أو مواقع.':'App-submitted device events, without images or location data.'}</p>
  <div className="entry-form">
   {isSuperAdmin&&<label>{ar?'الشركة':'Company'}<select value={company} onChange={e=>{setCompany(e.target.value);setDriver('');}}><option value="">{ar?'كل الشركات':'All companies'}</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
   <label>{ar?'السائق':'Driver'}<select value={driver} onChange={e=>setDriver(e.target.value)}><option value="">{ar?'كل السائقين':'All drivers'}</option>{drivers.filter(d=>!company||String(d.company_id)===company).map(d=><option key={d.id} value={d.id}>{d.full_name||d.name||`#${d.id}`}</option>)}</select></label>
   <label>{ar?'نوع الحدث':'Event'}<select value={event} onChange={e=>setEvent(e.target.value)}><option value="">{ar?'كل الأحداث':'All events'}</option>{Object.entries(labels).map(([key,v])=><option key={key} value={key}>{v[ar?1:0]}</option>)}</select></label>
   <label>{ar?'من تاريخ':'From'}<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label>
   <label>{ar?'إلى تاريخ':'To'}<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>
  </div>
  <div style={{display:'flex',gap:8,flexWrap:'wrap',margin:'12px 0'}}>
   <button type="button" className="primary" onClick={()=>setApplied({company,driver,event,from,to})}>{ar?'بحث':'Search'}</button>
   <button type="button" className="refresh" onClick={()=>{setCompany('');setDriver('');setEvent('');setFrom('');setTo('');setApplied({company:'',driver:'',event:'',from:'',to:''});}}>{ar?'مسح الفلاتر':'Clear filters'}</button>
   <button type="button" className="refresh" disabled={loading} onClick={()=>void load()}>{ar?'تحديث':'Refresh'}</button>
   <button type="button" className="refresh" disabled={!filtered.length} onClick={exportCsv}>{ar?'تصدير CSV (يفتح في Excel)':'Export CSV (Excel-compatible)'}</button>
  </div>
  {error&&<div className="notice" role="alert">{error}</div>}
  <p>{ar?`عدد السجلات: ${filtered.length}`:`${filtered.length} records`}{records.length>=500?' · '+(ar?'النتائج محدودة بآخر 500 سجل':'Limited to latest 500 records'):''}</p>
  <div className="table-wrap"><table><thead><tr><th>{ar?'الشركة':'Company'}</th><th>{ar?'السائق':'Driver'}</th><th>{ar?'الحدث':'Event'}</th><th>{ar?'وقت الحدث':'Occurred'}</th><th>{ar?'وقت الاستلام':'Received'}</th></tr></thead><tbody>
   {filtered.map(r=><tr key={r.event_id}><td>{companies.find(c=>c.id===r.company_id)?.name||`#${r.company_id}`}</td><td>{drivers.find(d=>d.id===r.driver_id)?.full_name||`#${r.driver_id}`}</td><td>{labels[r.event_type]?.[ar?1:0]||r.event_type}</td><td>{new Date(r.occurred_at).toLocaleString(ar?'ar-SA':'en-GB')}</td><td>{new Date(r.received_at).toLocaleString(ar?'ar-SA':'en-GB')}</td></tr>)}
  </tbody></table>{!filtered.length&&!loading&&<div className="empty">{ar?'لا توجد سجلات مطابقة':'No matching records'}</div>}</div>
  <p className="tip">{ar?'لا يمكن للتطبيق الإبلاغ عن إلغاء تثبيته بعد الحذف؛ يتطلب ذلك كشفاً منفصلاً من الخادم.':'An app cannot report its own uninstall after removal. Uninstall inference requires separate server-side monitoring.'}</p>
 </div>;
}
