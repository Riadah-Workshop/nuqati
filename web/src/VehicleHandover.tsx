/** Nuqati Vehicle Handover: additive dashboard, all data read live from API. */
import {useCallback,useEffect,useMemo,useState} from 'react';
import {CarFront,Camera,CheckCircle2,ClipboardCheck,Download,History,RefreshCw,ShieldAlert,XCircle} from 'lucide-react';

type Lang='ar'|'en';
type Assignment={id:number;company_id:number;vehicle_id:number;plate_number:string;vehicle_model:string;driver_id:number;driver_name:string;status:string;receipt_inspection_id:number|null;return_inspection_id:number|null;started_at:string;ended_at:string|null};
type Photo={id:number;category:string;note:string;sha256:string;url:string};
type Inspection={id:number;kind:string;odometer_km:number;engine_status:string;interior_status:string;dashboard_warnings:string;missing_items:string[];notes:string;damage_items:{area:string;kind:string;description:string;status:string}[];discrepancies:string[];driver_acknowledged:boolean;review_status:string;review_note:string;created_at:string;photos:Photo[]};
type Audit={id:number;created_at:string;actor_user_id:number;action:string;detail:string};
type HandoverDashboard={assignments:Assignment[];pending_count:number;active_count:number;closed_count:number};

function SecurePhoto({photo,token,api}:{photo:Photo;token:string;api:string}){
 const [url,setUrl]=useState('');
 useEffect(()=>{let canceled=false;let blobUrl='';
   void fetch(`${api}${photo.url}`,{headers:{Authorization:`Bearer ${token}`},cache:'no-store'})
    .then(async r=>{if(!r.ok)throw Error('Photo access denied');return await r.blob();})
    .then(blob=>{if(!canceled){blobUrl=URL.createObjectURL(blob);setUrl(blobUrl);}})
    .catch(()=>{if(!canceled)setUrl('');});
   return()=>{canceled=true;if(blobUrl)URL.revokeObjectURL(blobUrl);};
 },[photo.id,photo.url,token,api]);
 return <div className="handover-photo" title={`SHA256: ${photo.sha256}`}>
  {url?<a href={url} target="_blank" rel="noreferrer"><img loading="lazy" src={url} alt={photo.category}/></a>:<span><Camera size={22}/> {photo.category}</span>}
  <small>{photo.category}{photo.note?` · ${photo.note}`:''}</small>
 </div>;
}

export default function VehicleHandover({token,lang,api,companyId,isSuperAdmin,companies}:{token:string;lang:Lang;api:string;companyId:number|null;isSuperAdmin:boolean;companies:{id:number;name:string}[]}){
 const ar=lang==='ar';const t=(en:string,arabic:string)=>ar?arabic:en;
 const [selectedCompany,setSelectedCompany]=useState<string>(companyId?String(companyId):'');
 const [data,setData]=useState<HandoverDashboard>({assignments:[],pending_count:0,active_count:0,closed_count:0});
 const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [filter,setFilter]=useState<'all'|'active'|'pending'|'closed'>('all');
 const [search,setSearch]=useState('');const [selected,setSelected]=useState<number|null>(null);
 const [receipt,setReceipt]=useState<Inspection|null>(null);const [returned,setReturned]=useState<Inspection|null>(null);
 const [audit,setAudit]=useState<Audit[]>([]);const [reviewNote,setReviewNote]=useState('');
 const request=useCallback(async(path:string,options:RequestInit={})=>{
  const r=await fetch(`${api}/api/v1/handover${path}`,{...options,headers:{Authorization:`Bearer ${token}`,...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})},cache:'no-store'});
  const payload=await r.json().catch(()=>({detail:`HTTP ${r.status}`}));
  if(!r.ok)throw new Error(String(payload.detail||`HTTP ${r.status}`));return payload;
 },[token,api]);
 const refresh=useCallback(async()=>{setBusy(true);try{const q=isSuperAdmin&&selectedCompany?`?company_id=${encodeURIComponent(selectedCompany)}`:'';
  const result=await request(`/dashboard${q}`);setData(result);setMessage('');}
  catch(e){setMessage(String(e));}finally{setBusy(false);}},[request,isSuperAdmin,selectedCompany]);
 useEffect(()=>{void refresh();},[refresh]);
 const rows=useMemo(()=>data.assignments.filter(a=>{
  if(filter==='pending'&&!a.status.startsWith('pending'))return false;
  if(filter==='active'&&a.status!=='active')return false;
  if(filter==='closed'&&a.status!=='closed')return false;
  if(search&&!`${a.plate_number} ${a.driver_name} ${a.vehicle_model}`.toLowerCase().includes(search.toLowerCase()))return false;
  return true;
 }),[data.assignments,filter,search]);
 const target=data.assignments.find(a=>a.id===selected);
 useEffect(()=>{let canceled=false;setReceipt(null);setReturned(null);setAudit([]);
  if(!target)return;
  void Promise.all([
   target.receipt_inspection_id?request(`/inspections/${target.receipt_inspection_id}`):Promise.resolve(null),
   target.return_inspection_id?request(`/inspections/${target.return_inspection_id}`):Promise.resolve(null),
   request(`/vehicles/${target.vehicle_id}/history`)
  ]).then(([a,b,h])=>{if(!canceled){setReceipt(a);setReturned(b);setAudit(h.audit||[]);}}).catch(e=>{if(!canceled)setMessage(String(e));});
  return()=>{canceled=true;};
 },[target?.id,target?.receipt_inspection_id,target?.return_inspection_id,request]);
 async function approve(kind:'receipt'|'return',action:'approve'|'reject'){
  const inspection=kind==='receipt'?receipt:returned;if(!inspection)return;
  if(action==='reject'&&reviewNote.trim().length<8){setMessage(t('Provide at least 8 characters explaining rejection.','اكتب سبب الرفض بثمانية أحرف على الأقل.'));return;}
  const prompt=t(`${action==='approve'?'Approve':'Reject'} ${kind} inspection #${inspection.id}?` ,`${action==='approve'?'اعتماد':'رفض'} فحص ${kind==='receipt'?'الاستلام':'التسليم'} رقم ${inspection.id}؟`);
  if(!window.confirm(prompt))return;
  setBusy(true);try{await request(`/inspections/${inspection.id}/review`,{method:'POST',body:JSON.stringify({action,note:reviewNote})});
   setReviewNote('');setMessage(t('Review recorded and assignment updated online.','تم تسجيل القرار وتحديث الربط عبر الإنترنت.'));
   await refresh();const updated=await request(`/inspections/${inspection.id}`);
   if(kind==='receipt')setReceipt(updated);else setReturned(updated);
  }catch(e){setMessage(String(e));}finally{setBusy(false);}
 }
 async function downloadReport(a:Assignment){setBusy(true);try{
  const r=await fetch(`${api}/api/v1/handover/assignments/${a.id}/report`,{headers:{Authorization:`Bearer ${token}`}});
  if(!r.ok)throw Error(`${r.status} report unavailable`);
  const link=URL.createObjectURL(await r.blob());const el=document.createElement('a');el.href=link;el.download=`nuqati-handover-${a.plate_number}-${a.id}.pdf`;el.click();
  window.setTimeout(()=>URL.revokeObjectURL(link),2000);
 }catch(e){setMessage(String(e));}finally{setBusy(false);}}
 async function release(a:Assignment){
  const reason=window.prompt(t(`Reason for administrative release of ${a.plate_number} (minimum 12 characters):`,`سبب إخلاء عهدة اللوحة ${a.plate_number} إدارياً (12 حرفاً على الأقل):`));
  if(!reason||reason.trim().length<12)return;
  if(!window.confirm(t('Release this vehicle without a clean return report? This action is permanently audited.','هل تؤكد إخلاء عهدة المركبة دون فحص تسليم سليم؟ سيُحفظ الإجراء في سجل التدقيق.')))return;
  setBusy(true);try{await request(`/vehicles/${a.vehicle_id}/administrative-release`,{method:'POST',body:JSON.stringify({reason})});
   setMessage(t('Vehicle released with an audit record.','تم إخلاء عهدة السيارة وتوثيق العملية.'));await refresh();
  }catch(e){setMessage(String(e));}finally{setBusy(false);}
 }
 function inspectionPanel(label:string,x:Inspection|null){return <section className="handover-inspection"><h4><ClipboardCheck size={17}/> {label}</h4>
  {!x?<p>{t('No inspection submitted','لم يُقدم الفحص بعد')}</p>:<>
   <div className="handover-data-grid"><span>{t('Odometer','العداد')}: <strong>{x.odometer_km.toLocaleString()} km</strong></span>
    <span>{t('Engine','المحرك')}: <strong>{x.engine_status}</strong></span><span>{t('Interior','المقصورة')}: <strong>{x.interior_status}</strong></span>
    <span>{t('Review','المراجعة')}: <strong>{x.review_status}</strong></span>
    <span>{t('Dashboard warnings','تنبيهات الطبلون')}: <strong>{x.dashboard_warnings||'—'}</strong></span>
    <span>{t('Missing equipment','المعدات الناقصة')}: <strong>{x.missing_items.join(', ')||'—'}</strong></span></div>
   {x.damage_items.length>0&&<div className="handover-flags"><b>{t('Documented damage','الأضرار الموثقة')}</b>{x.damage_items.map((d,i)=><p key={i}>{d.status==='new'?'⚠ ':''}{d.area} · {d.kind}: {d.description}</p>)}</div>}
   {x.discrepancies.length>0&&<div className="handover-flags"><b>{t('Differences requiring review','فروق تتطلب المراجعة')}</b>{x.discrepancies.map((s,i)=><p key={i}>{s}</p>)}</div>}
   {x.notes&&<p>{t('Driver notes','ملاحظات السائق')}: {x.notes}</p>}
   <div className="handover-photos">{x.photos.map(p=><SecurePhoto key={p.id} photo={p} token={token} api={api}/>)}</div>
   {x.review_status==='pending'&&<div className="handover-review"><textarea rows={2} placeholder={t('Supervisor review note','ملاحظات المشرف')} value={reviewNote} onChange={e=>setReviewNote(e.target.value)}/>
    <button disabled={busy} className="primary" onClick={()=>void approve(x.kind as 'receipt'|'return','approve')}><CheckCircle2 size={16}/> {t('Approve','اعتماد')}</button>
    <button disabled={busy} className="refresh" onClick={()=>void approve(x.kind as 'receipt'|'return','reject')}><XCircle size={16}/> {t('Reject','رفض')}</button>
   </div>}
   {x.review_note&&<p>{t('Supervisor note','ملاحظة المشرف')}: {x.review_note}</p>}
  </>}
 </section>}
 return <section className="panel nuqati-handover">
  <div className="handover-heading"><div><h3><CarFront size={21}/> {t('Vehicle Handover & Condition Reports','استلام وتسليم المركبات وفحص الحالة')}</h3>
   <p>{t('Online-only inspection, driver accountability and permanent vehicle condition history.','فحص إلكتروني متصل، توثيق عهدة السائق، وسجل مستمر لحالة المركبات.')}</p></div>
   <button disabled={busy} className="refresh" onClick={()=>void refresh()}><RefreshCw size={16}/> {t('Refresh','تحديث')}</button></div>
  <div className="handover-kpis"><div><span>{t('Pending approvals','بانتظار الموافقة')}</span><strong>{data.pending_count}</strong></div>
   <div><span>{t('Active handovers','العهد النشطة')}</span><strong>{data.active_count}</strong></div>
   <div><span>{t('Completed returns','عمليات التسليم المكتملة')}</span><strong>{data.closed_count}</strong></div></div>
  <div className="handover-toolbar">
   {isSuperAdmin&&<label>{t('Company','الشركة')}<select value={selectedCompany} onChange={e=>{setSelectedCompany(e.target.value);setSelected(null);}}><option value="">{t('All companies','جميع الشركات')}</option>{companies.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></label>}
   <label>{t('Search plate or driver','ابحث باللوحة أو السائق')}<input value={search} onChange={e=>setSearch(e.target.value)} placeholder={t('Plate / name','رقم اللوحة / الاسم')}/></label>
   <label>{t('Status','الحالة')}<select value={filter} onChange={e=>setFilter(e.target.value as typeof filter)}>
    <option value="all">{t('All','الكل')}</option><option value="pending">{t('Pending review','بانتظار المراجعة')}</option>
    <option value="active">{t('Active','نشط')}</option><option value="closed">{t('Returned','مُسلّمة')}</option></select></label>
  </div>
  {message&&<p role="status" className="notice">{message}</p>}
  <div className="table-wrap"><table><thead><tr>{[t('Plate','اللوحة'),t('Driver','السائق'),t('Received','الاستلام'),t('State','الحالة'),t('Action','الإجراء')].map(h=><th key={h}>{h}</th>)}</tr></thead>
  <tbody>{rows.map(a=><tr key={a.id}><td><strong>{a.plate_number}</strong><br/><small>{a.vehicle_model}</small></td><td>{a.driver_name}</td><td>{new Date(a.started_at).toLocaleString(ar?'ar-SA':'en-GB')}</td>
   <td><span className={`handover-status ${a.status}`}>{a.status.replaceAll('_',' ')}</span></td>
   <td><button className="refresh" onClick={()=>setSelected(a.id)}>{t('Inspect history','التفاصيل')}</button></td></tr>)}</tbody></table>
   {!rows.length&&<p style={{padding:12}}>{t('No handover records yet. Drivers can create the first receipt from the app.','لا توجد سجلات حتى الآن. يمكن للسائق بدء الاستلام من التطبيق.')}</p>}
  </div>
  {target&&<div className="handover-details">
   <div className="handover-heading"><div><h3><History size={18}/> {target.plate_number} · {target.driver_name}</h3><small>{t('Record','سجل')} #{target.id} · {target.status}</small></div>
    <div><button className="refresh" onClick={()=>void downloadReport(target)} disabled={busy}><Download size={15}/> {t('Export PDF evidence','تحميل تقرير PDF')}</button>
     {target.status!=='closed'&&target.status!=='administratively_released'&&<button className="refresh" onClick={()=>void release(target)} disabled={busy}><ShieldAlert size={15}/> {t('Admin release','إخلاء إداري')}</button>}</div></div>
   <div className="handover-comparison">{inspectionPanel(t('At vehicle receipt','عند استلام المركبة'),receipt)}{inspectionPanel(t('At vehicle return','عند تسليم المركبة'),returned)}</div>
   {receipt&&returned&&<p className="handover-delta">{t('Odometer change','فرق العداد')}: <strong>{(returned.odometer_km-receipt.odometer_km).toLocaleString()} km</strong>. {t('Photos are presented side by side for visual comparison; no automated damage attribution is made.','الصور معروضة للمقارنة البصرية، ولا يتم تحميل المسؤولية تلقائياً.')}</p>}
   {audit.length>0&&<div className="handover-audit"><h4>{t('Permanent audit history','سجل التدقيق الدائم')}</h4>{audit.map(e=><p key={e.id}><time>{new Date(e.created_at).toLocaleString(ar?'ar-SA':'en-GB')}</time> · {e.action} · {e.detail||'—'} (user #{e.actor_user_id})</p>)}</div>}
  </div>}
 </section>;
}
