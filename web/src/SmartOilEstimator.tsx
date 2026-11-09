import { useEffect, useState } from 'react';

type OilInfo = {
  status: string; note?: string; make_model?: string; year?: number|null;
  distance_since_service_km?: number; configured_interval_km?:number;
  original_next_due_km?:number; gps_stationary_hours?:number;
  gps_observed_hours?:number; trip_distance_coverage_pct?:number;
  pilot_extra_usage_km?:number; pilot_equivalent_usage_km?:number;
  pilot_allowance_remaining_km?:number; pilot_advisory?:string;
  pilot_equivalent_km_per_stationary_hour?:number;
  manufacturer_guidance?:string;
};

export default function SmartOilEstimator({vehicleId,lang,request}:{vehicleId:string;lang:'en'|'ar';request:(path:string)=>Promise<OilInfo>}) {
  const [data,setData]=useState<OilInfo|null>(null);
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let valid=true;
    setData(null);setError('');
    if(!vehicleId)return;
    setLoading(true);
    request(`/api/v1/maintenance/smart-oil/${encodeURIComponent(vehicleId)}`)
      .then(result=>{if(valid)setData(result);})
      .catch(e=>{if(valid)setError(String(e));})
      .finally(()=>{if(valid)setLoading(false);});
    return ()=>{valid=false;};
    // Request callback uses current authenticated dashboard session; refresh on vehicle selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[vehicleId,refresh]);
  if(!vehicleId)return null;
  const ar=lang==='ar';
  const fmt=(x:number|undefined)=>x===undefined?'—':Math.round(x).toLocaleString('en-US');
  const insufficient=data?.status==='limited_data';
  const brand=(data?.make_model||'').toLowerCase();
  return <section className="panel nuqati-smart-oil">
    <div className="panel-heading"><div>
      <h3>{ar?'تقدير استهلاك زيت المحرك الذكي':'Smart Oil Life Estimator'} <small className="smart-oil-badge">{ar?'استشاري فقط':'Advisory only'}</small></h3>
      <p>{ar?'مستقل عن جداول الصيانة الحالية، ولا يغيّر موعد تغيير الزيت.':'Separate from existing maintenance schedules; never changes the oil due mileage.'}</p>
    </div><button type="button" className="refresh" onClick={()=>setRefresh(v=>v+1)}>{ar?'تحديث':'Refresh estimate'}</button></div>
    {loading&&<p>{ar?'جارٍ احتساب تقدير القيادة...':'Calculating observed usage…'}</p>}
    {error&&<p className="smart-oil-warning">{error}</p>}
    {data&&data.status==='needs_existing_oil_schedule'&&<p>{ar?'يلزم تسجيل عداد السيارة وجدول زيت المحرك أولاً.':'Please enter a vehicle odometer and an engine-oil schedule first.'}</p>}
    {data&&data.status!=='needs_existing_oil_schedule'&&<>
      <div className="smart-oil-grid">
        <div><span>{ar?'المسافة منذ آخر تغيير زيت':'Distance since last oil change'}</span><strong>{fmt(data.distance_since_service_km)} km</strong></div>
        <div><span>{ar?'زمن التوقف المرصود عبر GPS':'GPS-observed stationary time'}</span><strong>{data.gps_stationary_hours?.toFixed(2)??'—'} h</strong></div>
        <div><span>{ar?'الاستخدام المكافئ التقديري':'Pilot equivalent usage'}</span><strong>{fmt(data.pilot_equivalent_usage_km)} km</strong></div>
        <div><span>{ar?'الرصيد الاستشاري المتبقي':'Advisory allowance remaining'}</span><strong>{fmt(data.pilot_allowance_remaining_km)} km</strong></div>
      </div>
      <p className={insufficient?'smart-oil-warning':'smart-oil-note'}>
        {insufficient?(ar?'البيانات غير كافية: التقدير غير صالح لاتخاذ قرار الصيانة.':'Limited GPS trip history: do not use this estimate for maintenance decisions.'):ar?'هذا تقدير للمراجعة فقط، وليس قياساً لعمر الزيت.':'Indicative review only; this is not a measured oil-life percentage.'}
      </p>
      <p className="smart-oil-muted">{ar?'تغطية المسافة برحلات مسجلة':'Recorded trip-distance coverage'}: {data.trip_distance_coverage_pct?.toFixed(1)??'—'}% · {ar?'الفاصل الحالي':'Existing oil interval'}: {fmt(data.configured_interval_km)} km · {ar?'العداد المستحق الحالي':'Current scheduled due odometer'}: {fmt(data.original_next_due_km)} km</p>
      <p className="smart-oil-muted">{ar?'افتراض تجريبي':'Pilot assumption'}: {fmt(data.pilot_equivalent_km_per_stationary_hour)} {ar?'كم مكافئ / ساعة توقف مرصودة':'equivalent km / GPS-observed stationary hour'}. {ar?'قد يكون المحرك مطفأ أثناء التوقف؛ لا توجد قراءة مباشرة لساعات تشغيل المحرك.':'The engine could be off during stops; actual engine hours are not measured.'}</p>
      <p className="smart-oil-muted">{ar?'مرجع الشركة المصنعة':'Manufacturer guidance'}: {ar?'راجِع دليل السيارة الدقيق حسب سنة الصنع والمحرك والمواصفات المحلية.':'Verify the precise model/year/engine/market and oil grade against its owner or warranty manual.'} {brand.includes('toyota')&&<a href="https://www.toyota.com.sa/en/my-toyota/periodic-maintenance" target="_blank" rel="noopener noreferrer">{ar?'جدول صيانة تويوتا السعودية':'Toyota Saudi maintenance guidance'}</a>}</p>
    </>}
  </section>;
}
