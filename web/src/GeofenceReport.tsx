import {useEffect,useState} from 'react';

type Entity = {id:number;company_id:number;full_name?:string;name?:string};
type Crossing = {event:'entry'|'exit';zone_id:string;zone_name:string;driver_id:number;driver_name:string;plate_number:string;time:string;speed_kmh:number;speed_limit_kmh:number|null;latitude:number;longitude:number};

export default function GeofenceReport({request,lang,companyId,companies,drivers}:{request:(path:string)=>Promise<any>;lang:'en'|'ar';companyId:number|null;companies:Entity[];drivers:Entity[]}){
 const [company,setCompany]=useState(companyId?String(companyId):'');
 const [driver,setDriver]=useState('');
 const [zone,setZone]=useState('');
 const [zones,setZones]=useState<Array<{id:string;name:string}>>([]);
 const localDate=(d:Date)=>{const pad=(x:number)=>String(x).padStart(2,'0');return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;};
 const [from,setFrom]=useState(()=>localDate(new Date(Date.now()-7*86400000)));
 const [to,setTo]=useState(()=>localDate(new Date()));
 const [rows,setRows]=useState<Crossing[]|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const [truncated,setTruncated]=useState(false);
 const cid=companyId?String(companyId):company;
 useEffect(()=>{if(companyId)void loadZones(String(companyId));},[companyId]);
 async function loadZones(value:string){setZone('');setRows(null);setZones([]);if(!value)return;try{const result=await request('/api/v1/fleet/phase4?company_id='+encodeURIComponent(value));setZones(result.zones||[]);}catch(e){setError(String(e));}}
 async function search(){setError('');setRows(null);if(!cid){setError(lang==='en'?'Select a company':'اختر الشركة');return;}
  const first=new Date(from),last=new Date(to);
  if(!Number.isFinite(first.getTime())||!Number.isFinite(last.getTime())||first>=last||last.getTime()-first.getTime()>31*86400000){setError(lang==='en'?'Choose a valid date/time range of up to 31 days':'اختر فترة صحيحة لا تتجاوز ٣١ يوماً');return;}
  const query=new URLSearchParams({company_id:cid,start_at:first.toISOString(),end_at:last.toISOString(),limit:'1000'});
  if(driver)query.set('driver_id',driver);if(zone)query.set('zone_id',zone);
  setBusy(true);try{const result=await request('/api/v1/fleet/geofence-crossings?'+query);setRows(result.events||[]);setTruncated(!!result.truncated);}catch(e){setError(String(e));}finally{setBusy(false);}
 }
 function csv(){if(!rows)return;const keys=['time','event','zone_name','driver_name','plate_number','speed_kmh','speed_limit_kmh','latitude','longitude'] as const;
  const cell=(v:unknown)=>'"'+String(v??'').replaceAll('"','""')+'"';const content=[keys.join(','),...rows.map(r=>keys.map(k=>cell(r[k])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob(['\ufeff'+content],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='nuqati-geofence-crossings.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 return <section className="panel nuqati-geo-report"><div className="panel-heading"><div><h3>{lang==='en'?'Geofence Entry & Exit Report':'تقرير الدخول والخروج من المناطق الجغرافية'}</h3><p>{lang==='en'?'Search named geofence crossings with driver, timestamp and crossing speed.':'البحث عن الدخول والخروج حسب اسم المنطقة والسائق والوقت والسرعة.'}</p></div></div>
  <div className="nuqati-geo-report-filters">
   {!companyId&&<label>{lang==='en'?'Company':'الشركة'}<select value={company} onChange={e=>{setCompany(e.target.value);setDriver('');void loadZones(e.target.value);}}><option value="">{lang==='en'?'Select company':'اختر الشركة'}</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
   <label>{lang==='en'?'Driver':'السائق'}<select value={driver} onChange={e=>{setDriver(e.target.value);setRows(null);}}><option value="">{lang==='en'?'All drivers':'جميع السائقين'}</option>{drivers.filter(d=>String(d.company_id)===cid).map(d=><option key={d.id} value={d.id}>{d.full_name}</option>)}</select></label>
   <label>{lang==='en'?'Geofence':'المنطقة'}<select value={zone} onChange={e=>{setZone(e.target.value);setRows(null);}}><option value="">{lang==='en'?'All geofences':'جميع المناطق'}</option>{zones.map(z=><option key={z.id} value={z.id}>{z.name}</option>)}</select></label>
   <label>{lang==='en'?'From date/time':'من تاريخ ووقت'}<input type="datetime-local" value={from} onChange={e=>{setFrom(e.target.value);setRows(null);}}/></label>
   <label>{lang==='en'?'To date/time':'إلى تاريخ ووقت'}<input type="datetime-local" value={to} onChange={e=>{setTo(e.target.value);setRows(null);}}/></label>
  </div>
  <div className="nuqati-geo-report-actions"><button className="primary" disabled={busy} onClick={()=>void search()}>{busy?'Loading…':lang==='en'?'Search crossings':'بحث'}</button><button className="refresh" onClick={()=>{setRows(null);setDriver('');setZone('');setError('');}}>{lang==='en'?'Clear':'مسح'}</button><button className="refresh" disabled={!rows?.length} onClick={csv}>{lang==='en'?'Export CSV':'تصدير CSV'}</button></div>
  {error&&<p role="alert">{error}</p>}
  {rows===null?<div className="empty">{lang==='en'?'Select filters and press Search to view geofence history.':'حدد معايير البحث ثم اضغط بحث لعرض السجل.'}</div>:<><p>{rows.length} {lang==='en'?'crossings found':'عملية دخول أو خروج'}{truncated?' · Results limited; narrow the date range.':' '}</p><div className="table-wrap"><table><thead><tr>{(lang==='en'?['Date / Time','Event','Geofence','Driver','Vehicle','Speed','Zone speed limit','Location']:['التاريخ والوقت','الحدث','المنطقة','السائق','المركبة','السرعة','حد المنطقة','الموقع']).map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={r.time+r.zone_id+r.driver_id+i}><td>{new Date(r.time).toLocaleString(lang==='ar'?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh'})}</td><td>{r.event==='entry'?(lang==='en'?'Entry':'دخول'):(lang==='en'?'Exit':'خروج')}</td><td>{r.zone_name}</td><td>{r.driver_name}</td><td>{r.plate_number}</td><td>{r.speed_kmh.toFixed(1)} km/h</td><td>{r.speed_limit_kmh??'—'}</td><td><a href={`https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}#map=16/${r.latitude}/${r.longitude}`} target="_blank" rel="noreferrer">{lang==='en'?'Map':'خريطة'}</a></td></tr>)}</tbody></table></div>{rows.length===0&&<div className="empty">{lang==='en'?'No matching crossings.':'لا توجد سجلات مطابقة.'}</div>}</>}
  <small>{lang==='en'?'Historical crossings are reconstructed from accurate saved GPS fixes; gaps longer than 2 minutes are not interpreted as boundary crossings. Times displayed in Saudi Arabia time (UTC+3).':'يتم استخراج العبور من عينات GPS المحفوظة والدقيقة؛ لا يتم استنتاج عبور عند انقطاع البيانات لأكثر من دقيقتين. التوقيت المعروض بتوقيت السعودية.'}</small>
 </section>;
}
