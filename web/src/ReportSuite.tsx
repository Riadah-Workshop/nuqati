import {useEffect,useMemo,useState, type ReactNode} from 'react';
import {BookOpen, CalendarClock, ChevronRight, FileBarChart2, Search, Star, X} from 'lucide-react';
import './report-suite.css';

type Lang='en'|'ar';
export type ReportId='privacy-audit'|'mobile-diagnostics'|'overview'|'historical-tracking'|'geofence'|'subscriptions'|'performance'|'monthly'|'rag';
type CategoryId='audit'|'custom'|'dashboard'|'quality'|'events'|'fuel'|'hours'|'journey'|'list'|'materials'|'satellite'|'movement'|'rag'|'risk'|'scoring'|'trip';
type ReportDef={id:ReportId;name:{en:string;ar:string};description:{en:string;ar:string};categories:CategoryId[];privileged?:boolean;nav?:boolean};
const categories:{id:CategoryId;en:string;ar:string}[]=[
 {id:'audit',en:'Audit Reports',ar:'تقارير التدقيق'},
 {id:'custom',en:'Custom Reports',ar:'التقارير المخصصة'},
 {id:'dashboard',en:'Dashboard Widgets',ar:'لوحات المؤشرات'},
 {id:'quality',en:'Data Quality Management',ar:'إدارة جودة البيانات'},
 {id:'events',en:'Event Reports',ar:'تقارير الأحداث'},
 {id:'fuel',en:'Fuel Reports',ar:'تقارير الوقود'},
 {id:'hours',en:'Hours Of Service Reports',ar:'تقارير ساعات القيادة'},
 {id:'journey',en:'Journey Management Reports',ar:'تقارير إدارة الرحلات'},
 {id:'list',en:'List Reports',ar:'تقارير القوائم'},
 {id:'materials',en:'Materials Handling Reports',ar:'تقارير مناولة المواد'},
 {id:'satellite',en:'Mix Sat Comms',ar:'اتصالات الأقمار الصناعية'},
 {id:'movement',en:'Movement Reports',ar:'تقارير الحركة'},
 {id:'rag',en:'RAG Reports',ar:'تقارير ألوان المخاطر RAG'},
 {id:'risk',en:'Risk Management Reports',ar:'تقارير إدارة المخاطر'},
 {id:'scoring',en:'Scoring Reports',ar:'تقارير النقاط'},
 {id:'trip',en:'Trip Reports',ar:'تقارير الرحلات'},
];
// Every available entry opens an existing Nuqati workflow. Intentionally do not
// invent fuel, hardware or compliance reports unsupported by the backend.
const reports:ReportDef[]=[
 {id:'privacy-audit',name:{en:'Driver Privacy & Access Audit',ar:'تدقيق خصوصية السائق والصلاحيات'},description:{en:'Review privacy activity and requests in the existing audit workspace.',ar:'مراجعة سجل الخصوصية والطلبات في صفحة التدقيق الحالية.'},categories:['audit'],privileged:true,nav:true},
 {id:'mobile-diagnostics',name:{en:'GPS & App Diagnostics Log',ar:'سجل تشخيص التطبيق وGPS'},description:{en:'Review GPS, permissions, tracking and synchronization diagnostics.',ar:'مراجعة سجلات GPS والصلاحيات والتتبع والمزامنة.'},categories:['audit','quality'],nav:true},
 {id:'subscriptions',name:{en:'Scheduled Email Report Subscriptions',ar:'اشتراكات التقارير البريدية المجدولة'},description:{en:'Manage report recipients, schedules and delivery history.',ar:'إدارة مستلمي التقارير ومواعيدها وسجل الإرسال.'},categories:['custom']},
 {id:'overview',name:{en:'Fleet Overview Dashboard',ar:'لوحة مؤشرات الأسطول'},description:{en:'Open fleet KPIs, activity and safety trends.',ar:'عرض مؤشرات الأسطول والنشاط واتجاهات السلامة.'},categories:['dashboard'],nav:true},
 {id:'geofence',name:{en:'Geofence Entry & Exit Report',ar:'تقرير دخول المناطق الجغرافية والخروج منها'},description:{en:'Search geofence crossings by driver, zone and date; export CSV.',ar:'البحث في عبور المناطق حسب السائق والمنطقة والتاريخ والتصدير CSV.'},categories:['events','movement']},
 {id:'performance',name:{en:'Driver Safety & Violation Report',ar:'تقرير سلامة السائق والمخالفات'},description:{en:'Compare trips, scores, risk levels and driving violations.',ar:'مقارنة الرحلات والنقاط ومستويات المخاطر ومخالفات القيادة.'},categories:['events','list','risk','scoring','trip','custom']},
 {id:'monthly',name:{en:'Monthly Fleet Reports · PDF / CSV / Excel',ar:'تقارير الأسطول الشهرية · PDF / CSV / Excel'},description:{en:'Export vehicle assignments, utilization, RAG and violations.',ar:'تصدير تخصيص المركبات والاستخدام وتصنيف RAG والمخالفات.'},categories:['hours','list','rag','trip','custom']},
 {id:'historical-tracking',name:{en:'Historical Trips & Movement',ar:'الرحلات والحركة التاريخية'},description:{en:'Open historical routes, date filters and trip details.',ar:'عرض المسارات التاريخية وفلاتر التاريخ وتفاصيل الرحلات.'},categories:['journey','movement','trip'],nav:true},
 {id:'rag',name:{en:'Flexible RAG Driver Report',ar:'تقرير تصنيف السائقين RAG المرن'},description:{en:'Review policy-based RAG scores and event breakdowns.',ar:'مراجعة نقاط RAG حسب السياسة وتفاصيل الأحداث.'},categories:['rag','risk','scoring']},
];

function readList(key:string):string[]{try{const data=JSON.parse(localStorage.getItem(key)||'[]');return Array.isArray(data)?data.filter(x=>typeof x==='string'):[]}catch{return []}}
function readTimes(key:string):Record<string,string>{try{const data=JSON.parse(localStorage.getItem(key)||'{}');return data&&typeof data==='object'&&!Array.isArray(data)?data:{}}catch{return {}}}

export default function ReportSuite({lang,role,userId,selected,onSelect,children}:{lang:Lang;role:string;userId:number;selected:ReportId|null;onSelect:(id:ReportId|null)=>void;children?:ReactNode}){
 const ar=lang==='ar';
 const [category,setCategory]=useState<CategoryId>('audit');
 const [view,setView]=useState<'suite'|'favorites'>('suite');
 const [search,setSearch]=useState('');
 const storageKey=`nuqati.report-suite.user.${userId}`;
 const [favorites,setFavorites]=useState<string[]>(()=>readList(`${storageKey}.favorites`));
 const [viewed,setViewed]=useState<Record<string,string>>(()=>readTimes(`${storageKey}.viewed`));
 useEffect(()=>{setFavorites(readList(`${storageKey}.favorites`));setViewed(readTimes(`${storageKey}.viewed`));setCategory('audit');setView('suite');setSearch('');},[storageKey]);
 const accessible=useMemo(()=>reports.filter(r=>!r.privileged||['super_admin','company_admin','fleet_manager'].includes(role)),[role]);
 const rows=useMemo(()=>accessible.filter(r=>{
   if(view==='favorites'&&!favorites.includes(r.id))return false;
   if(view==='suite'&&!search.trim()&&!r.categories.includes(category))return false;
   const q=search.trim().toLocaleLowerCase();
   return !q||`${r.name.en} ${r.name.ar} ${r.description.en} ${r.description.ar} ${r.categories.map(id=>categories.find(c=>c.id===id)?.en).join(' ')}`.toLocaleLowerCase().includes(q);
 }),[accessible,view,category,search,favorites]);
 const active=accessible.find(r=>r.id===selected);
 const current=categories.find(c=>c.id===category)!;
 function toggleFavorite(id:ReportId){setFavorites(old=>{const next=old.includes(id)?old.filter(v=>v!==id):[...old,id];try{localStorage.setItem(`${storageKey}.favorites`,JSON.stringify(next))}catch{/* Browser storage may be disabled. */}return next;});}
 function selectReport(id:ReportId){const now=new Date().toISOString();setViewed(old=>{const next={...old,[id]:now};try{localStorage.setItem(`${storageKey}.viewed`,JSON.stringify(next))}catch{/* Private mode may block persistence. */}return next;});onSelect(id);}
 return <section className="nq-report-suite" dir={ar?'rtl':'ltr'} aria-label={ar?'مكتبة تقارير الأسطول':'Fleet report suite'}>
  <div className="nq-report-suite-banner"><div className="nq-report-suite-banner-icon"><FileBarChart2 size={25}/></div><div><span>{ar?'الرؤى والتحليلات':'INSIGHTS & ANALYTICS'}</span><h2>{ar?'مكتبة تقارير نقاطي':'Nuqati Report Suite'}</h2><p>{ar?'اختر فئة، وافتح التقرير، وحدد خياراته عند الحاجة':'Choose a category, open a report and configure its filters when needed.'}</p></div><span className="nq-report-suite-count">{accessible.length} {ar?'تقارير متاحة':'available reports'}</span></div>
  <div className="nq-report-suite-layout">
   <nav className="nq-report-suite-aside" aria-label={ar?'التنقل في التقارير':'Reports navigation'}>
    <button type="button" className={view==='suite'?'is-active':''} onClick={()=>{setView('suite');setSearch('');onSelect(null)}}><BookOpen size={17}/>{ar?'مكتبة التقارير':'Report suite'}</button>
    <button type="button" className={view==='favorites'?'is-active':''} onClick={()=>{setView('favorites');setSearch('');onSelect(null)}}><Star size={17}/>{ar?'التقارير المفضلة':'Favorite reports'}<small>{favorites.filter(f=>accessible.some(r=>r.id===f)).length}</small></button>
   </nav>
   <div className="nq-report-suite-workspace">
    <div className="nq-report-suite-toolbar"><div><strong>{view==='suite'?(ar?'اختر فئة التقارير':'Select report category'):(ar?'التقارير المفضلة':'Favorite reports')}</strong><p>{view==='suite'?(ar?'الفئات مطابقة لتنظيم المرجع؛ تظهر فقط التقارير الموجودة فعلياً في نقاطي.':'Categories follow the reference; only reports supported by Nuqati are listed.'):(ar?'التقارير التي أضفتها للمفضلة من هذه المتصفّح.':'Reports you bookmarked in this browser.')}</p></div><label className="nq-report-suite-search"><Search size={16}/><input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder={ar?'بحث في التقارير...':'Filter reports...'} aria-label={ar?'البحث في التقارير':'Filter reports'}/>{search&&<button type="button" onClick={()=>setSearch('')} aria-label={ar?'مسح البحث':'Clear search'}><X size={14}/></button>}</label></div>
    {view==='suite'&&<label className="nq-report-suite-category"><span>{ar?'فئة التقرير':'Report category'}</span><select value={category} onChange={e=>{setCategory(e.target.value as CategoryId);setSearch('');onSelect(null)}}>{categories.map(c=><option key={c.id} value={c.id}>{ar?c.ar:c.en}</option>)}</select></label>}
    <div className="nq-report-suite-table-wrap"><table className="nq-report-suite-table"><thead><tr><th scope="col">{ar?'التقرير':'Report'}</th><th scope="col">{ar?'آخر عرض':'Last viewed'}</th><th scope="col">{ar?'المفضلة':'Favorite'}</th></tr></thead><tbody>{rows.map(r=><tr key={r.id} className={selected===r.id?'is-selected':''}><td><button className="nq-report-suite-open" type="button" onClick={()=>selectReport(r.id)}><span><strong>{r.name[lang]}</strong><small>{r.description[lang]}</small></span><ChevronRight size={16} aria-hidden="true"/></button></td><td className="nq-report-suite-date">{viewed[r.id]?new Date(viewed[r.id]).toLocaleDateString(ar?'ar-SA':'en-GB',{day:'2-digit',month:'short',year:'numeric'}):'—'}</td><td className="nq-report-suite-star"><button type="button" className={favorites.includes(r.id)?'is-favorite':''} aria-label={favorites.includes(r.id)?(ar?`إزالة ${r.name.ar} من المفضلة`:`Remove ${r.name.en} from favorites`):(ar?`إضافة ${r.name.ar} للمفضلة`:`Add ${r.name.en} to favorites`)} aria-pressed={favorites.includes(r.id)} onClick={()=>toggleFavorite(r.id)}><Star size={17} fill={favorites.includes(r.id)?'currentColor':'none'}/></button></td></tr>)}</tbody></table>
     {!rows.length&&<div className="nq-report-suite-noresults"><FileBarChart2 size={22}/><strong>{view==='favorites'?(ar?'لا توجد تقارير مفضلة مطابقة':'No matching favorite reports'):search?(ar?'لا توجد تقارير مطابقة للبحث':'No reports match your search'):(ar?'لا تتوفر تقارير في هذه الفئة حالياً':'No reports available in this category yet')}</strong><p>{view==='favorites'?(ar?'يمكنك إضافة تقرير باستخدام زر النجمة في مكتبة التقارير.':'Use the star next to a report to add it to favorites.'):search?(ar?'جرّب كلمة بحث مختلفة.':'Try another search term.'):(ar?'هذه الفئة موجودة للهيكلة المستقبلية؛ لن يتم توليد بيانات غير متوفرة.':'This category is reserved for future reports; unavailable data is not invented.')}</p></div>}
    </div>
    <div className="nq-report-suite-footer"><CalendarClock size={14}/>{ar?'آخر عرض مسجل على هذا المتصفح فقط؛ ليس سجل تشغيل على الخادم.':'Last viewed is recorded in this browser only; it is not a server-side run history.'}</div>
    {active&&!active.nav&&<div className="nq-report-suite-detail"><div className="nq-report-suite-detail-head"><div><span>{ar?'تقرير محدد':'SELECTED REPORT'}</span><h3>{active.name[lang]}</h3></div><button type="button" className="nq-report-suite-close" onClick={()=>onSelect(null)}><X size={15}/>{ar?'إغلاق التقرير':'Close report'}</button></div>{children}</div>}
   </div>
  </div>
 </section>;
}
