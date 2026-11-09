import {useEffect,useState} from 'react';

type Lang='en'|'ar';
type Request=(url:string, options?:RequestInit)=>Promise<any>;
type EventRule={kind:string;score_on:'occurrence'|'duration'|'both';weight:number;amber_min:number;amber_max:number};
type RagPolicy={enabled:boolean;events:EventRule[];overall_amber_min:number;overall_amber_max:number;distance_unit_km:number;minimum_distance_km:number;aggregation:'sum'|'weighted_average';supported_events?:string[]};
const supported=['speeding','excessive_speeding','harsh_acceleration','harsh_braking','harsh_cornering','geofence_entry','geofence_exit','geofence_restricted'];
const title=(k:string)=>k.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());

export function FlexibleRagSettings({request,companyId,lang}:{request:Request;companyId:string|number|undefined|null;lang:Lang}){
 const [policy,setPolicy]=useState<RagPolicy|null>(null);
 const [message,setMessage]=useState('');const [saving,setSaving]=useState(false);
 const ar=lang==='ar';
 useEffect(()=>{let active=true;setPolicy(null);setMessage('');if(!companyId)return;
  request(`/api/v1/fleet/flexible-rag/policy?company_id=${companyId}`).then(d=>{if(active)setPolicy(d)}).catch(e=>{if(active)setMessage(String(e))});return()=>{active=false};
 },[companyId]);
 const update=(patch:Partial<RagPolicy>)=>setPolicy(old=>old?{...old,...patch}:old);
 const change=(kind:string,patch:Partial<EventRule>)=>update({events:policy!.events.map(e=>e.kind===kind?{...e,...patch}:e)});
 async function save(){if(!policy||!companyId)return;setSaving(true);setMessage('');try{
  const {enabled,events,overall_amber_min,overall_amber_max,distance_unit_km,minimum_distance_km,aggregation}=policy;
  await request(`/api/v1/fleet/flexible-rag/policy?company_id=${companyId}`,{method:'PUT',body:JSON.stringify({enabled,events,overall_amber_min,overall_amber_max,distance_unit_km,minimum_distance_km,aggregation})});
  setMessage(ar?'تم حفظ سياسة RAG. التقارير الرسمية ستستخدم النموذج الجديد عند تفعيله.':'RAG policy saved. Official reports use the new model when enabled.');
 }catch(e){setMessage(String(e))}finally{setSaving(false)}}
 return <details className="nuqati-rag-settings">
  <summary>{ar?'نموذج RAG المرن — الأقل أفضل':'Flexible RAG scoring — lower is better'}</summary>
  {!companyId?<p>{ar?'اختر الشركة أولاً':'Select a company first.'}</p>:!policy?<p>{message||'Loading scoring policy…'}</p>:<div className="nuqati-rag-config">
   <p>{ar?'النموذج القديم من 100 نقطة يبقى حتى يتم تفعيل هذا الخيار. لا يتم تغيير البيانات السابقة.':'Existing 100-point scoring remains in use until you enable this model. Historical records are preserved.'}</p>
   <label className="nuqati-rag-switch"><input type="checkbox" checked={policy.enabled} onChange={e=>update({enabled:e.target.checked})}/>{ar?'تفعيل نموذج RAG المرن لهذه الشركة':'Enable Flexible RAG for this company'}</label>
   <p><strong>{ar?'أقل نتيجة هي الأفضل؛ 0 هو الهدف':'Lower is better; target score is 0.'}</strong> {ar?'الأحداث تُقسّم على المسافة، والأحداث دون قياسات GPS لا تحصل على مدة افتراضية.':'Events are normalized by distance; missing GPS evidence never creates invented event duration.'}</p>
   <div className="nuqati-rag-fields">
    <label>{ar?'المسافة القياسية (كم)':'Normalize per (km)'}<input type="number" min="1" max="1000" value={policy.distance_unit_km} onChange={e=>update({distance_unit_km:Number(e.target.value)})}/></label>
    <label>{ar?'أقل مسافة مؤهلة (كم)':'Minimum scored distance (km)'}<input type="number" min="1" max="1000" value={policy.minimum_distance_km} onChange={e=>update({minimum_distance_km:Number(e.target.value)})}/></label>
    <label>{ar?'طريقة الدمج':'Combine event scores'}<select value={policy.aggregation} onChange={e=>update({aggregation:e.target.value as RagPolicy['aggregation']})}><option value="sum">{ar?'المجموع المرجح':'Weighted sum'}</option><option value="weighted_average">{ar?'المتوسط المرجح':'Weighted average'}</option></select></label>
    <label>{ar?'حد الأصفر الأدنى':'Overall amber from'}<input type="number" min="0" step="0.1" value={policy.overall_amber_min} onChange={e=>update({overall_amber_min:Number(e.target.value)})}/></label>
    <label>{ar?'حد الأصفر الأعلى':'Overall amber to'}<input type="number" min="0" step="0.1" value={policy.overall_amber_max} onChange={e=>update({overall_amber_max:Number(e.target.value)})}/></label>
   </div>
   <h4>{ar?'الأحداث المختارة (حتى 10)':'Selected events (up to 10)'}</h4>
   <div className="table-wrap"><table><thead><tr><th>{ar?'الحدث':'Event'}</th><th>{ar?'طريقة الحساب':'Score on'}</th><th>{ar?'الوزن':'Weight'}</th><th>{ar?'أصفر من':'Amber from'}</th><th>{ar?'أصفر إلى':'Amber to'}</th><th/></tr></thead><tbody>
    {policy.events.map(e=><tr key={e.kind}><td>{title(e.kind)}</td><td><select value={e.score_on} onChange={v=>change(e.kind,{score_on:v.target.value as EventRule['score_on']})}><option value="occurrence">{ar?'عدد':'Occurrence'}</option>{e.kind==='speeding'&&<><option value="duration">{ar?'مدة':'Duration'}</option><option value="both">{ar?'الاثنان':'Both'}</option></>}</select></td>
    <td><input type="number" min="0.1" max="100" step="0.1" value={e.weight} onChange={v=>change(e.kind,{weight:Number(v.target.value)})}/></td>
    <td><input type="number" min="0" step="0.1" value={e.amber_min} onChange={v=>change(e.kind,{amber_min:Number(v.target.value)})}/></td>
    <td><input type="number" min="0" step="0.1" value={e.amber_max} onChange={v=>change(e.kind,{amber_max:Number(v.target.value)})}/></td>
    <td><button type="button" className="refresh" onClick={()=>update({events:policy.events.filter(x=>x.kind!==e.kind)})} disabled={policy.events.length<=1}>{ar?'حذف':'Remove'}</button></td></tr>)}
   </tbody></table></div>
   <label>{ar?'إضافة حدث':'Add event'} <select value="" disabled={policy.events.length>=10} onChange={e=>{if(e.target.value&&!policy.events.some(r=>r.kind===e.target.value))update({events:[...policy.events,{kind:e.target.value,score_on:'occurrence',weight:1,amber_min:2,amber_max:5}]})}}><option value="">{ar?'اختر حدثاً':'Choose event'}</option>{supported.filter(k=>!policy.events.some(e=>e.kind===k)).map(k=><option key={k} value={k}>{title(k)}</option>)}</select></label>
   <p className="nuqati-rag-hint">{ar?'حساب المدة متاح حالياً لتجاوز السرعة فقط، باستخدام قراءات GPS المتصلة والجيدة. يبدأ الحساب بعد توفر الحد الأدنى من المسافة.':'Duration is supported for speeding only, using adjacent high-quality GPS readings. Scores are withheld below the minimum distance.'}</p>
   <button type="button" className="primary" disabled={saving||policy.events.length<1} onClick={save}>{saving?'Saving…':ar?'حفظ سياسة RAG':'Save RAG policy'}</button>
   {message&&<p role="status">{message}</p>}
  </div>}
 </details>
}

export function FlexibleRagReports({request,companyId,lang}:{request:Request;companyId:string|number|undefined|null;lang:Lang}){
 const ar=lang==='ar';const [view,setView]=useState('summary');const [start,setStart]=useState('');const [end,setEnd]=useState('');
 const [data,setData]=useState<any>(null);const [message,setMessage]=useState('');const [loading,setLoading]=useState(false);
 useEffect(()=>{setData(null);setMessage('')},[companyId]);
 async function search(){if(!companyId)return;setLoading(true);setMessage('');try{
  const p=new URLSearchParams({company_id:String(companyId),view});if(start)p.set('start_date',start);if(end)p.set('end_date',end);
  const result=await request('/api/v1/fleet/flexible-rag/reports?'+p);setData(result);
 }catch(e){setMessage(String(e));setData(null)}finally{setLoading(false)}}
 function csv(){if(!data)return;const rows=[['Driver','Period','Trips','Distance (km)','RAG score (lower better)','RAG'],...data.rows.map((r:any)=>[r.driver_name,r.period,r.trips,r.distance_km,r.score??'',r.rag??'No data'])];const text=rows.map(r=>r.map((v:any)=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));a.download='nuqati-flexible-rag-'+view+'.csv';a.click();URL.revokeObjectURL(a.href)}
 return <section className="nuqati-rag-report">
  <h3>{ar?'تقارير RAG المرنة':'Flexible RAG Reports'}</h3>
  <p>{ar?'الأقل أفضل: أخضر أقل من 2، أصفر من 2 إلى 5، وأحمر فوق 5 افتراضياً.':'Lower is better. Defaults: Green below 2, Amber 2–5, Red above 5. Company thresholds may differ.'}</p>
  <div className="nuqati-rag-fields"><label>{ar?'نوع التقرير':'Report view'}<select value={view} onChange={e=>{setView(e.target.value);setData(null)}}><option value="daily">{ar?'يومي':'Daily'}</option><option value="summary">{ar?'ملخص الفترة':'Period summary'}</option><option value="ytd">{ar?'العام حتى تاريخه':'Year to date — monthly'}</option></select></label>
  <label>{ar?'من':'From'}<input type="date" value={start} onChange={e=>{setStart(e.target.value);setData(null)}}/></label><label>{ar?'إلى':'To'}<input type="date" value={end} onChange={e=>{setEnd(e.target.value);setData(null)}}/></label>
  <div className="nuqati-rag-actions"><button type="button" className="primary" disabled={!companyId||loading} onClick={search}>{loading?'Loading…':ar?'عرض التقرير':'Search report'}</button><button type="button" className="refresh" onClick={csv} disabled={!data}>{ar?'تصدير CSV':'Export CSV'}</button></div></div>
  {message&&<p role="alert">{message}</p>}
  {!data?<p className="nuqati-rag-hint">{ar?'اختر الفترة واضغط بحث لعرض النتائج.':'Choose a reporting period and press Search. Results are hidden until requested.'}</p>:
  <div className="table-wrap"><table><thead><tr><th>{ar?'السائق':'Driver'}</th><th>{ar?'الفترة':'Period'}</th><th>{ar?'الرحلات':'Trips'}</th><th>{ar?'كم':'km'}</th><th>{ar?'النتيجة (الأقل أفضل)':'RAG score ↓'}</th><th>RAG</th></tr></thead><tbody>{data.rows.map((r:any,i:number)=><tr key={i}><td>{r.driver_name}</td><td>{r.period}</td><td>{r.trips}</td><td>{r.distance_km}</td><td>{r.score??'—'}</td><td><span className={'nuqati-rag-pill '+(r.rag||'none')}>{r.rag?.toUpperCase()||'NO DATA'}</span>{r.event_breakdown?.length>0&&<details><summary>{ar?'التفاصيل':'Breakdown'}</summary><ul>{r.event_breakdown.map((e:any)=><li key={e.event}>{title(e.event)}: {e.score} · {e.occurrences} {ar?'أحداث':'events'}{e.score_on!=='occurrence'?` · ${e.duration_seconds}s`:''}</li>)}</ul></details>}{r.reason&&<small>{r.reason.replaceAll('_',' ')}</small>}</td></tr>)}</tbody></table>{!data.rows.length&&<p>{ar?'لا توجد رحلات':'No completed trips found.'}</p>}</div>}
 </section>
}
