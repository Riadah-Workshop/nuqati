import {useEffect,useMemo,useState} from 'react';

type Company={id:number;name:string};
type Driver={id:number;company_id:number;full_name:string};
type Vehicle={id:number;company_id:number;plate_number:string};
type Subscription={id:number;recipient:string;kind:string;frequency:string;scope_type:string;site_name:string|null;next_send_at:string;last_sent_at:string|null;last_error:string|null;enabled:boolean};
type Props={request:(path:string,opts?:RequestInit)=>Promise<any>;lang:'en'|'ar';role:string;companyId:number|null;selectedCompany:string;companies:Company[];drivers:Driver[];vehicles:Vehicle[]};
export default function ReportSubscriptions({request,lang,role,companyId,selectedCompany,companies,drivers,vehicles}:Props){
 const ar=lang==='ar';const cid=role==='super_admin'?Number(selectedCompany):companyId;
 const [records,setRecords]=useState<Subscription[]>([]),[sites,setSites]=useState<string[]>([]);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const [form,setForm]=useState({kind:'vehicle_utilization',frequency:'weekly',recipient:'',scope_type:'all',site_name:'',selected_ids:[] as number[],weekday:0,month_day:1,anchor_month:1,send_hour:9,send_minute:0,timezone:'Asia/Riyadh'});
 const kinds=[['vehicle_utilization',ar?'استخدام المركبات':'Vehicle utilization'],['driver_violations',ar?'مخالفات السائقين':'Driver violations'],['driver_scores',ar?'نقاط السائقين':'Driver scores'],['rag',ar?'تقرير ألوان RAG':'RAG report']];
 const frequencies=[['daily',ar?'يومي':'Daily'],['weekly',ar?'أسبوعي':'Weekly'],['monthly',ar?'شهري':'Monthly'],['quarterly',ar?'ربع سنوي':'Quarterly'],['yearly',ar?'سنوي':'Yearly']];
 const filtered=useMemo(()=>form.kind==='vehicle_utilization'?vehicles.filter(v=>v.company_id===cid):drivers.filter(d=>d.company_id===cid),[form.kind,cid,vehicles,drivers]);
 const name=(item:any)=>'plate_number'in item?item.plate_number:item.full_name;
 const all=(newVal:any)=>setForm(old=>({...old,...newVal}));
 async function reload(){if(!cid){setRecords([]);setSites([]);return;}try{const qs=`?company_id=${cid}`;const [r,s]=await Promise.all([request('/api/v1/fleet/report-subscriptions'+qs),request('/api/v1/fleet/report-subscriptions/sites'+qs)]);setRecords(r);setSites(s);}catch(e){setError(String(e));}}
 useEffect(()=>{void reload();},[cid]);
 async function save(){if(!cid){setError(ar?'اختر الشركة':'Select a company');return;}setBusy(true);setError('');try{await request('/api/v1/fleet/report-subscriptions',{method:'POST',body:JSON.stringify({...form,company_id:cid,scope_type:form.kind==='rag'?'all':form.scope_type,selected_ids:form.kind==='rag'?[]:form.selected_ids})});await reload();setError(ar?'تمت إضافة الاشتراك':'Report subscription saved');}catch(e){setError(String(e));}finally{setBusy(false);}}
 async function modify(id:number,enabled:boolean,remove=false){try{await request(`/api/v1/fleet/report-subscriptions/${id}${remove?'':`?enabled=${enabled}`}`,{method:remove?'DELETE':'PATCH'});await reload();}catch(e){setError(String(e));}}
 return <section className="nuqati-scheduled-reports" dir={ar?'rtl':'ltr'}>
 <div className="nuqati-scheduled-heading"><div><h3>{ar?'اشتراكات التقارير بالبريد الإلكتروني':'Email Report Subscriptions'}</h3><p>{ar?'اختر التقرير والمستلمين والأيام ووقت الإرسال':'Choose report, recipient, coverage and delivery schedule'}</p></div></div>
 <div className="nuqati-scheduled-grid">
 <label>{ar?'نوع التقرير':'Report type'}<select value={form.kind} onChange={e=>all({kind:e.target.value,scope_type:'all',selected_ids:[]})}>{kinds.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
 <label>{ar?'التكرار':'Frequency'}<select value={form.frequency} onChange={e=>all({frequency:e.target.value})}>{frequencies.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
 <label>{ar?'البريد المستلم':'Recipient email'}<input type="email" autoComplete="email" value={form.recipient} placeholder="reports@company.com" onChange={e=>all({recipient:e.target.value})}/></label>
 <label>{ar?'المنطقة الزمنية':'Time zone'}<select value={form.timezone} onChange={e=>all({timezone:e.target.value})}><option value="Asia/Riyadh">Saudi Arabia · Riyadh</option><option value="UTC">UTC</option></select></label>
 {form.kind!=='rag'&&<label>{ar?'نطاق التقرير':'Coverage'}<select value={form.scope_type} onChange={e=>all({scope_type:e.target.value,selected_ids:[]})}><option value="all">{ar?'الكل':'All'}</option><option value="selected">{form.kind==='vehicle_utilization'?(ar?'مركبات محددة':'Selected vehicles'):(ar?'سائقون محددون':'Selected drivers')}</option><option value="site">{ar?'الموقع / القسم':'Department / site'}</option></select></label>}
 {form.scope_type==='site'&&form.kind!=='rag'&&<label>{ar?'القسم / الموقع':'Department / site'}<select value={form.site_name} onChange={e=>all({site_name:e.target.value})}><option value="">{ar?'اختر الموقع':'Select site'}</option>{sites.map(s=><option value={s} key={s}>{s}</option>)}</select></label>}
 {form.frequency==='weekly'&&<label>{ar?'يوم الأسبوع':'Weekday'}<select value={form.weekday} onChange={e=>all({weekday:Number(e.target.value)})}>{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'].map((day,i)=><option key={i} value={i}>{ar?['الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][i]:day}</option>)}</select></label>}
 {['monthly','quarterly','yearly'].includes(form.frequency)&&<label>{ar?'يوم الشهر':'Day of month'}<input type="number" min={1} max={31} value={form.month_day} onChange={e=>all({month_day:Number(e.target.value)})}/></label>}
 {['quarterly','yearly'].includes(form.frequency)&&<label>{ar?'شهر البداية':'Start month'}<select value={form.anchor_month} onChange={e=>all({anchor_month:Number(e.target.value)})}>{Array.from({length:12},(_,i)=><option key={i} value={i+1}>{new Date(2026,i,1).toLocaleString(ar?'ar-SA':'en-US',{month:'long'})}</option>)}</select></label>}
 <label>{ar?'ساعة الإرسال':'Send hour (24h)'}<input type="number" min={0} max={23} value={form.send_hour} onChange={e=>all({send_hour:Number(e.target.value)})}/></label>
 <label>{ar?'دقيقة الإرسال':'Minute'}<input type="number" min={0} max={59} value={form.send_minute} onChange={e=>all({send_minute:Number(e.target.value)})}/></label>
 </div>
 {form.kind!=='rag'&&form.scope_type==='selected'&&<div className="nuqati-scheduled-choices"><strong>{ar?'اختر العناصر':'Select items'}</strong><div>{filtered.map(item=><label key={item.id}><input type="checkbox" checked={form.selected_ids.includes(item.id)} onChange={e=>all({selected_ids:e.target.checked?[...form.selected_ids,item.id]:form.selected_ids.filter(id=>id!==item.id)})}/>{name(item)}</label>)}</div></div>}
 <p className="nuqati-scheduled-note">{ar?'القسم يعتمد على حقل الموقع لدى السائق. المركبات تُصنّف حسب السائق المعيّن حالياً. التقارير تشمل الرحلات المكتملة والمخالفات المؤكدة فقط.':'Department uses the driver Site field; vehicle departments use their currently assigned driver. Reports use completed trips and confirmed events only.'}</p>
 <button type="button" className="primary" disabled={busy||!cid} onClick={save}>{busy?'Saving…':ar?'إضافة اشتراك':'Create subscription'}</button>
 {error&&<p role="status" className="nuqati-scheduled-note">{error}</p>}
 <h4>{ar?'الاشتراكات الحالية':'Existing subscriptions'}</h4>
 <div className="table-wrap"><table><thead><tr><th>{ar?'التقرير':'Report'}</th><th>{ar?'البريد':'Recipient'}</th><th>{ar?'التكرار':'Frequency'}</th><th>{ar?'الإرسال التالي':'Next delivery'}</th><th>{ar?'الحالة':'Status'}</th><th>{ar?'الإجراءات':'Actions'}</th></tr></thead><tbody>{records.map(r=><tr key={r.id}><td>{kinds.find(x=>x[0]===r.kind)?.[1]||r.kind}</td><td>{r.recipient}</td><td>{r.frequency}</td><td>{new Date(r.next_send_at).toLocaleString()}</td><td>{r.last_error?(ar?'خطأ في الإرسال':'Delivery error'):r.enabled?(ar?'نشط':'Active'):(ar?'متوقف':'Paused')}</td><td><button className="refresh" onClick={()=>modify(r.id,!r.enabled)}>{r.enabled?(ar?'إيقاف':'Pause'):(ar?'تفعيل':'Enable')}</button> <button className="refresh" onClick={()=>{if(window.confirm(ar?'حذف الاشتراك؟':'Delete subscription?'))void modify(r.id,false,true);}}>{ar?'حذف':'Delete'}</button></td></tr>)}{records.length===0&&<tr><td colSpan={6}>{ar?'لا توجد اشتراكات':'No subscriptions created'}</td></tr>}</tbody></table></div>
 </section>;
}
