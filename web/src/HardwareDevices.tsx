import { useEffect, useState } from 'react';

type Vehicle={id:number;company_id:number;plate_number:string};
type Device={id:number;vehicle_id:number;vendor:string;model:string;imei:string;enabled:boolean;last_seen_at:string|null};
const API=import.meta.env.VITE_API_BASE_URL ?? '';
export default function HardwareDevices({vehicles,token,lang}:{vehicles:Vehicle[];token:string;lang:'en'|'ar'}){
 const [vehicle,setVehicle]=useState('');
 const [vendor,setVendor]=useState('teltonika');
 const [model,setModel]=useState('FMC920');
 const [imei,setImei]=useState('');
 const [devices,setDevices]=useState<Device[]>([]);
 const [error,setError]=useState('');
 const [latest,setLatest]=useState<any>(null);
 const ar=lang==='ar';
 async function api(path:string,init?:RequestInit){const r=await fetch(`${API}${path}`,{...init,headers:{'Authorization':`Bearer ${token}`,'Content-Type':'application/json',...init?.headers}});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.detail||`HTTP ${r.status}`);return j;}
 async function refresh(){try{setDevices(await api('/api/v1/hardware/devices'));setError('');}catch(e){setError(String(e));}}
 useEffect(()=>{if(token)refresh();},[token]);
 async function link(e:React.FormEvent){e.preventDefault();try{await api('/api/v1/hardware/devices',{method:'POST',body:JSON.stringify({vehicle_id:Number(vehicle),vendor,model,imei})});setImei('');await refresh();}catch(e){setError(String(e));}}
 async function toggle(d:Device){try{await api(`/api/v1/hardware/devices/${d.id}/enabled?enabled=${!d.enabled}`,{method:'PATCH'});await refresh();}catch(e){setError(String(e));}}
 async function showLatest(d:Device){try{setLatest(await api(`/api/v1/hardware/vehicles/${d.vehicle_id}/latest`));setError('');}catch(e){setError(String(e));}}
 return <section className="panel" style={{marginTop:18}}>
 <h3>{ar?'أجهزة التتبع المرتبطة بالمركبات':'Vehicle GPS Hardware'}</h3>
 <p>{ar?'مصدر تتبع ثانوي. لا يغير المسافات أو نقاط السائق تلقائياً.':'Secondary tracking source. Does not automatically change mileage or driver scores.'}</p>
 <form className="entry-form" onSubmit={link}>
 <label>{ar?'المركبة':'Vehicle'}<select required value={vehicle} onChange={e=>setVehicle(e.target.value)}><option value="">{ar?'اختر مركبة':'Select vehicle'}</option>{vehicles.map(v=><option value={v.id} key={v.id}>{v.plate_number} · #{v.id}</option>)}</select></label>
 <label>{ar?'الشركة المصنعة':'Manufacturer'}<select value={vendor} onChange={e=>{setVendor(e.target.value);setModel(e.target.value==='teltonika'?'FMC920':'Ruptela');}}><option value="teltonika">Teltonika</option><option value="ruptela">Ruptela (registration only)</option></select></label>
 <label>{ar?'الموديل':'Model'}<input required value={model} onChange={e=>setModel(e.target.value)}/></label>
 <label>IMEI (15 digits)<input required pattern="[0-9]{15}" maxLength={15} value={imei} onChange={e=>setImei(e.target.value.trim())}/></label>
 <button className="primary">{ar?'ربط جهاز':'Link device'}</button>
 </form>
 {error&&<p role="alert">{error}</p>}
 <button type="button" className="refresh" onClick={refresh}>{ar?'تحديث':'Refresh devices'}</button>
 <div className="table-wrap"><table><thead><tr><th>{ar?'المركبة':'Vehicle'}</th><th>{ar?'الموديل':'Device'}</th><th>IMEI</th><th>{ar?'آخر اتصال':'Last seen'}</th><th>{ar?'الحالة':'Status'}</th><th>{ar?'الإجراء':'Action'}</th></tr></thead><tbody>
 {devices.map(d=><tr key={d.id}><td>{vehicles.find(v=>v.id===d.vehicle_id)?.plate_number||`#${d.vehicle_id}`}</td><td>{d.vendor} {d.model}</td><td>{d.imei}</td><td>{d.last_seen_at?new Date(d.last_seen_at).toLocaleString():'—'}</td><td>{d.enabled?'Enabled':'Disabled'}</td><td><button type="button" className="refresh" onClick={()=>showLatest(d)}>{ar?'آخر موقع':'Latest position'}</button><button type="button" className="refresh" onClick={()=>toggle(d)}>{d.enabled?(ar?'تعطيل':'Disable'):(ar?'تفعيل':'Enable')}</button></td></tr>)}
 </tbody></table></div>
 {latest&&<p>{ar?'آخر بيانات الجهاز':'Latest device telemetry'}: {latest.latest?`${latest.latest.latitude.toFixed(6)}, ${latest.latest.longitude.toFixed(6)} · ${latest.latest.speed_kmh} km/h · ${new Date(latest.latest.recorded_at).toLocaleString()}`:(ar?'لا توجد بيانات بعد':'No points received yet')}</p>}
 <small>{ar?'استقبال Ruptela يحتاج بروتوكول الشركة الرسمي؛ الربط متاح لكن الاستقبال غير مفعل.':'Ruptela ingestion requires official protocol documentation; linking is available but ingestion is not enabled.'}</small>
 </section>;
}
