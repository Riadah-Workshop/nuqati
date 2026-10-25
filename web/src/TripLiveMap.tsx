import { useMemo } from 'react';

type Point = {latitude:number;longitude:number;recorded_at:string;speed_kmh?:number};
type Violation = {id:number;type:string;value:number;latitude:number;longitude:number;recorded_at:string};
type RouteData = {trip_id:number;status:string;points:Point[];violations:Violation[];start:Point|null;end:Point|null;truncated?:boolean};

export default function TripLiveMap({route,lang}:{route:RouteData;lang:'en'|'ar'}) {
  const isAr=lang==='ar';
  const html=useMemo(()=>{
    // Escape '<' so API-provided strings cannot inject HTML/script into srcDoc.
    const data=JSON.stringify({points:route.points,violations:route.violations,status:route.status}).replace(/</g,'\\u003c');
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{margin:0;height:100%;width:100%}body{font-family:Arial,sans-serif}.legend{position:absolute;z-index:900;bottom:16px;left:12px;background:white;padding:8px;border-radius:6px;box-shadow:0 1px 8px #777;font-size:12px}</style></head><body><div id="map"></div><div class="legend">🟢 ${isAr?'البداية':'Start'} &nbsp; 🔵 ${isAr?'آخر موقع / النهاية':'Latest / End'} &nbsp; 🔴 ${isAr?'مخالفة':'Violation'}</div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const data=${data};const map=L.map('map');L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
const pts=data.points.filter(p=>Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Math.abs(p.latitude)<=90&&Math.abs(p.longitude)<=180);const coords=pts.map(p=>[p.latitude,p.longitude]);
function pin(p,color,label){return L.circleMarker([p.latitude,p.longitude],{radius:9,color:'#fff',weight:2,fillColor:color,fillOpacity:1}).addTo(map).bindPopup(label)}
if(coords.length){L.polyline(coords,{color:'#2563eb',weight:5,opacity:.8}).addTo(map);pin(pts[0],'#16a34a','${isAr?'بداية الرحلة':'Trip start'}<br>'+new Date(pts[0].recorded_at).toLocaleString());const last=pts[pts.length-1];pin(last,'#2563eb','${isAr?'آخر موقع':'Latest location'}<br>'+new Date(last.recorded_at).toLocaleString()+'<br>'+Number(last.speed_kmh||0).toFixed(1)+' km/h');map.fitBounds(L.latLngBounds(coords).pad(.2),{maxZoom:16});}else{map.setView([24.7136,46.6753],5)}
for(const e of data.violations){if(!Number.isFinite(e.latitude)||!Number.isFinite(e.longitude))continue;const unit=e.type==='speeding'?' km/h':' km/h/s';const label=String(e.type).replaceAll('_',' ')+'<br>'+Number(e.value).toFixed(1)+unit+'<br>'+new Date(e.recorded_at).toLocaleString();pin(e,'#dc2626',label)}
</script></body></html>`;
  },[route,isAr]);
  const last=route.end;
  return <div style={{marginTop:12}}>
    <p>{route.status==='active'?(isAr?'● رحلة نشطة — تحديث تلقائي كل 15 ثانية':'● Active trip — auto-refresh every 15 seconds'):(isAr?'رحلة مكتملة':'Completed trip')} · {route.points.length} {isAr?'نقطة GPS':'GPS points'} · {route.violations.length} {isAr?'مخالفة':'violations'}</p>
    <iframe key={route.trip_id} title={isAr?'خريطة تتبع الرحلة':'Trip tracking map'} srcDoc={html} sandbox="allow-scripts" style={{width:'100%',height:460,border:'1px solid #334155',borderRadius:12,background:'#e5e7eb'}} />
    {last&&<p style={{fontSize:12,opacity:.8}}>{isAr?'آخر قراءة':'Last reading'}: {new Date(last.recorded_at).toLocaleString()} · {last.latitude.toFixed(5)}, {last.longitude.toFixed(5)}</p>}
    {route.truncated&&<p>{isAr?'المسار محدود بآخر ١٠٠٠٠ نقطة':'Route limited to 10,000 points'}</p>}
    {!route.points.length&&<p>{isAr?'لا توجد قراءات GPS لهذه الرحلة':'No GPS readings recorded for this trip'}</p>}
  </div>;
}
