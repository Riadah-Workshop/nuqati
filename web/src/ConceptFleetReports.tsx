import {useEffect, useMemo, useState} from 'react';
import {CalendarDays, Download, FileBarChart2, FileSpreadsheet, FileText, Gauge, MapPinned, RefreshCw, Route, ShieldCheck} from 'lucide-react';
import './concept-fleet-reports.css';

type Lang='en'|'ar';
export type ConceptReportKind='movement'|'daily-trips'|'utilization'|'daily-rag';
type ReportColumn={key:string;en:string;ar:string};
type ReportData={kind:ConceptReportKind;title:Record<Lang,string>;company_name:string;start_date:string;end_date:string;
  columns:ReportColumn[];rows:Record<string,string|number|null>[];summary:{trips:number;distance_km:number;vehicles:number;drivers:number;days:number};notes:string[];notes_ar?:string[];score_model:string|null};
type FilterPerson={id:number;full_name:string;company_id:number};
type FilterVehicle={id:number;plate_number:string;make_model:string;company_id:number};
const API=import.meta.env.VITE_API_BASE_URL??'';
const names:Record<ConceptReportKind,{en:string;ar:string;descriptionEn:string;descriptionAr:string}>={
 'movement':{en:'Trip Movement Detail',ar:'تفاصيل حركة الرحلات',descriptionEn:'Departure and arrival, GPS locations, duration, movement and speed, trip by trip.',descriptionAr:'المغادرة والوصول وإحداثيات GPS والمدة والحركة والسرعة لكل رحلة.'},
 'daily-trips':{en:'Daily Fleet Trips',ar:'الرحلات اليومية للأسطول',descriptionEn:'Daily summary by vehicle and driver, including distance, time and speed.',descriptionAr:'ملخص يومي حسب المركبة والسائق يتضمن المسافة والوقت والسرعة.'},
 'utilization':{en:'Vehicle Utilization Calendar',ar:'تقويم استخدام المركبات',descriptionEn:'Daily distance matrix with weekdays, weekends and days with trips.',descriptionAr:'جدول مسافة يومية مع أيام العمل وعطلة نهاية الأسبوع وأيام الرحلات.'},
 'daily-rag':{en:'Daily Driver Safety & RAG',ar:'سلامة السائقين وتصنيف RAG اليومي',descriptionEn:'Safety events per 100 km, observed speeding and official company-policy RAG.',descriptionAr:'مخالفات السلامة لكل 100 كم وتجاوز السرعة وتصنيف RAG وفق سياسة الشركة.'},
};
const dateOffset=(days:number)=>new Date(Date.now()+3*3600000+days*86400000).toISOString().slice(0,10);
const label=(en:string,ar:string,l:Lang)=>l==='ar'?ar:en;
const valueText=(key:string,val:string|number|null|undefined)=>{
 if(val===null||val===undefined||val==='')return '—';
 if(typeof val==='number')return val.toLocaleString('en-US',{maximumFractionDigits:3});
 if(key==='rag')return val.toUpperCase();
 return String(val);
};

export default function ConceptFleetReports({kind,lang,companyId,drivers,vehicles}:{kind:ConceptReportKind;lang:Lang;companyId:string|number|null|undefined;drivers:FilterPerson[];vehicles:FilterVehicle[]}){
 const ar=lang==='ar';const cid=String(companyId??'');
 const [start,setStart]=useState(()=>dateOffset(-6));const [end,setEnd]=useState(()=>dateOffset(0));
 const [driver,setDriver]=useState('');const [vehicle,setVehicle]=useState('');
 const [report,setReport]=useState<ReportData|null>(null);const [busy,setBusy]=useState(false);
 const [exporting,setExporting]=useState('');const [error,setError]=useState('');
 const [showAll,setShowAll]=useState(false);
 useEffect(()=>{setReport(null);setError('');setDriver('');setVehicle('');setShowAll(false);},[cid,kind]);
 const availableDrivers=useMemo(()=>drivers.filter(d=>String(d.company_id)===cid),[drivers,cid]);
 const availableVehicles=useMemo(()=>vehicles.filter(v=>String(v.company_id)===cid),[vehicles,cid]);
 const valid=Boolean(cid&&start&&end&&end>=start&&(Date.parse(end)-Date.parse(start))/86400000<=30);
 const query=()=>{const q=new URLSearchParams({company_id:cid,start_date:start,end_date:end});if(driver)q.set('driver_id',driver);if(vehicle)q.set('vehicle_id',vehicle);return q;};
 async function generate(){if(!valid)return;setBusy(true);setError('');setReport(null);setShowAll(false);
  try{const response=await fetch(`${API}/api/v1/fleet/concept-reports/${kind}?${query()}`,{headers:{Authorization:`Bearer ${sessionStorage.getItem('nuqati_token')||''}`},cache:'no-store'});
   if(!response.ok){let message=`HTTP ${response.status}`;try{const detail=(await response.json()).detail;if(typeof detail==='string')message=detail;}catch{/* empty */}throw Error(message)}
   setReport(await response.json() as ReportData);
  }catch(e){setError(String(e))}finally{setBusy(false)}
 }
 async function download(format:'xlsx'|'csv'|'pdf'){
  if(!valid||!report)return;setExporting(format);setError('');
  try{const q=query();q.set('format',format);q.set('lang',lang);
   const response=await fetch(`${API}/api/v1/fleet/concept-reports/${kind}/export?${q}`,{headers:{Authorization:`Bearer ${sessionStorage.getItem('nuqati_token')||''}`},cache:'no-store'});
   if(!response.ok){let message=`Export failed (${response.status})`;try{const detail=(await response.json()).detail;if(typeof detail==='string')message=detail;}catch{/* empty */}throw Error(message)}
   const blob=await response.blob();const url=URL.createObjectURL(blob);const anchor=document.createElement('a');
   anchor.href=url;anchor.download=`nuqati-${kind}-${start}-${end}.${format}`;document.body.append(anchor);anchor.click();anchor.remove();
   window.setTimeout(()=>URL.revokeObjectURL(url),2000);
  }catch(e){setError(String(e))}finally{setExporting('')}
 }
 const data=names[kind];const maxVisible=100;const rows=report?.rows||[];const preview=showAll?rows:rows.slice(0,maxVisible);
 return <section className="nq-concept-report" aria-label={data[lang]}>
  <div className="nq-concept-heading"><span className="nq-concept-mark">{kind==='movement'?<MapPinned/>:kind==='daily-trips'?<Route/>:kind==='utilization'?<Gauge/>:<ShieldCheck/>}</span>
   <div><span className="nq-concept-eyebrow">{label('FLEET INTELLIGENCE / REPORT BUILDER','تقارير الأسطول / إنشاء تقرير',lang)}</span><h3>{data[lang]}</h3><p>{ar?data.descriptionAr:data.descriptionEn}</p></div></div>
  <div className="nq-concept-filter"><div className="nq-concept-filter-title"><CalendarDays size={17}/><strong>{label('Report period & filters','فترة التقرير والتصفية',lang)}</strong><span>{label('Saudi time · max 31 days','بتوقيت السعودية · حتى 31 يوماً',lang)}</span></div>
   <div className="nq-concept-fields">
    <label>{label('From','من',lang)}<input type="date" value={start} onChange={e=>{setStart(e.target.value);setReport(null);}}/></label>
    <label>{label('To','إلى',lang)}<input type="date" value={end} onChange={e=>{setEnd(e.target.value);setReport(null);}}/></label>
    <label>{label('Driver','السائق',lang)}<select value={driver} onChange={e=>{setDriver(e.target.value);setReport(null);}}><option value="">{label('All drivers','جميع السائقين',lang)}</option>{availableDrivers.map(d=><option key={d.id} value={d.id}>{d.full_name}</option>)}</select></label>
    <label>{label('Vehicle','المركبة',lang)}<select value={vehicle} onChange={e=>{setVehicle(e.target.value);setReport(null);}}><option value="">{label('All vehicles','جميع المركبات',lang)}</option>{availableVehicles.map(v=><option key={v.id} value={v.id}>{v.plate_number} · {v.make_model}</option>)}</select></label>
   </div>
   <div className="nq-concept-filter-footer"><span>{!cid?label('Select a company from the dashboard header.','اختر الشركة من أعلى لوحة التحكم.',lang):!valid?label('Choose a valid period of 1–31 days.','اختر فترة صحيحة من 1 إلى 31 يوماً.',lang):label('Reports include completed trips only.','تحتسب الرحلات المكتملة فقط.',lang)}</span><button type="button" className="primary" onClick={()=>void generate()} disabled={!valid||busy}><RefreshCw size={15}/>{busy?label('Generating…','جارٍ الإنشاء…',lang):label('Generate report','إنشاء التقرير',lang)}</button></div>
  </div>
  {error&&<p className="nq-concept-error" role="alert">{error}</p>}
  {!report?<div className="nq-concept-placeholder"><FileBarChart2 size={30}/><strong>{label('Select your filters and generate the report','اختر التصفية ثم أنشئ التقرير',lang)}</strong><small>{label('The report uses actual Nuqati trip and safety data. No sample data is shown.','يستخدم التقرير بيانات نقاطي الفعلية للرحلات والسلامة؛ دون بيانات افتراضية.',lang)}</small></div>:<>
   <div className="nq-concept-generated"><div><span className="nq-concept-eyebrow">NUQATI · {label('GENERATED REPORT','تقرير تم إنشاؤه',lang)}</span><h4>{report.title[lang]}</h4><p>{report.company_name} · {report.start_date} — {report.end_date}</p></div>
    <div className="nq-concept-export"><button type="button" disabled={Boolean(exporting)} onClick={()=>void download('xlsx')}><FileSpreadsheet size={15}/>{exporting==='xlsx'?'…':'Excel'}</button><button type="button" disabled={Boolean(exporting)} onClick={()=>void download('pdf')}><FileText size={15}/>{exporting==='pdf'?'…':'PDF'}</button><button type="button" disabled={Boolean(exporting)} onClick={()=>void download('csv')}><Download size={15}/>{exporting==='csv'?'…':'CSV'}</button></div></div>
   <div className="nq-concept-kpis"><article><small>{label('Recorded trips','الرحلات المسجلة',lang)}</small><strong>{report.summary.trips.toLocaleString()}</strong></article><article><small>{label('Trip distance','مسافة الرحلات',lang)}</small><strong>{report.summary.distance_km.toLocaleString()} <em>km</em></strong></article><article><small>{label('Active drivers','السائقون النشطون',lang)}</small><strong>{report.summary.drivers}</strong></article><article><small>{label('Vehicles with trips','المركبات ذات الرحلات',lang)}</small><strong>{report.summary.vehicles}</strong></article></div>
   <div className="nq-concept-grid-header"><strong>{label('Report records','سجلات التقرير',lang)} <span>({rows.length.toLocaleString()})</span></strong><small>{label('Scroll horizontally for all fields','مرر أفقياً لعرض جميع الحقول',lang)}</small></div>
   <div className="nq-concept-table-wrap"><table><thead><tr>{report.columns.map(c=><th key={c.key}>{c[lang]}</th>)}</tr></thead><tbody>{preview.map((r,i)=><tr key={String(r.trip_id??`${r.date??'row'}-${r.driver_id??r.plate??i}-${i}`)}>{report.columns.map(c=><td key={c.key}>{c.key==='rag'&&r.rag?<span className={`nq-concept-rag nq-rag-${r.rag}`}>{valueText(c.key,r[c.key])}</span>:valueText(c.key,r[c.key])}</td>)}</tr>)}</tbody></table>{!rows.length&&<div className="nq-concept-no-data">{label('No matching records for the selected range.','لا توجد سجلات مطابقة للفترة المختارة.',lang)}</div>}</div>
   {rows.length>maxVisible&&<div className="nq-concept-pagination"><span>{label(showAll?'Showing all records':'Showing the first 100 rows. Exports contain all rows.',showAll?'عرض جميع السجلات':'يتم عرض أول 100 سجل، وتشمل الصادرات جميع السجلات.',lang)}</span><button type="button" className="refresh" onClick={()=>setShowAll(v=>!v)}>{label(showAll?'Show first 100':'Show all rows',showAll?'عرض أول 100':'عرض جميع السجلات',lang)}</button></div>}
   <details className="nq-concept-notes" open><summary>{label('Source & measurement notes','مصدر البيانات وملاحظات القياس',lang)}</summary><ul>{(ar?(report.notes_ar??report.notes):report.notes).map((note,i)=><li key={i}>{note}</li>)}</ul>{kind==='daily-rag'&&<p><strong>{label('Scoring model:','نموذج التقييم:',lang)}</strong> {report.score_model==='flexible_rag'?label('Flexible RAG — lower is better','RAG المرن — الأقل أفضل',lang):label('Standard 100-point score — higher is better','التقييم القياسي من 100 — الأعلى أفضل',lang)}</p>}</details>
  </>}
 </section>;
}
