import { useMemo } from 'react';

type Zone = {id:string;name:string;latitude:number;longitude:number;radius_m:number;mode:string;vehicle_ids?:number[]|null;speed_limit_kmh?:number|null;shape?:string;polygon_points?:number[][]|null};
type Area = {id:string;name:string;status:string;speed_limit_kmh?:number|null};
type Position = {vehicle_id:number;plate:string;driver_name:string|null;driver_id:number|null;latitude:number|null;longitude:number|null;recorded_at:string|null;speed_kmh:number|null;accuracy_m:number|null;age_seconds:number|null;state:string;trip_active:boolean;geofences:Area[]};
type Event = {id:number;driver_id:number;type:string;latitude:number;longitude:number;recorded_at:string;value:number;layer:'active'|'passive'};

export default function FleetPositionMap({positions,lang,zones=[],events=[],selectedVehicleId=null,showActive=true,showPassive=false,showZones=true,limitEventsToPositions=false}:{positions:Position[];lang:'en'|'ar';zones?:Zone[];events?:Event[];selectedVehicleId?:number|null;showActive?:boolean;showPassive?:boolean;showZones?:boolean;limitEventsToPositions?:boolean}){
  const html = useMemo(()=>{
    const serialize = (value:unknown)=>JSON.stringify(value).replace(/</g,'\\u003c').replace(/\u2028|\u2029/g,' ');
    const filtered = selectedVehicleId ? positions.filter(p=>p.vehicle_id===selectedVehicleId):positions;
    const includedZones = showZones ? zones.filter(z=>!selectedVehicleId || z.vehicle_ids==null || z.vehicle_ids.includes(selectedVehicleId)):[];
    const allowedDrivers = new Set(filtered.map(p=>p.driver_id).filter((id):id is number=>id!==null));
    const visibleEvents = events.filter(e=>(e.layer==='active'?showActive:showPassive)&&((!selectedVehicleId&&!limitEventsToPositions)||allowedDrivers.has(e.driver_id)));
    const key=serialize(import.meta.env.VITE_MAPTILER_API_KEY||'');
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{height:100%;width:100%;margin:0}body{font:13px Arial}.legend{position:absolute;bottom:18px;right:10px;background:#10283d;color:white;padding:9px;border-radius:7px;z-index:900;box-shadow:0 2px 8px #0004}.legend span{display:block;padding:2px}.legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}.leaflet-popup-content{line-height:1.65}</style></head><body><div id="map"></div><div class="legend"><span><i style="background:#a5d84c"></i>${lang==='en'?'Moving':'متحرك'}</span><span><i style="background:#f0ac4d"></i>${lang==='en'?'Stationary':'متوقف'}</span><span><i style="background:#9ca3af"></i>${lang==='en'?'Stale / uncertain':'غير محدث / غير مؤكد'}</span></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
    const positions=${serialize(filtered)},zones=${serialize(includedZones)},events=${serialize(visibleEvents)},key=${key};
    const map=L.map('map').setView([26.3,50.2],10);const bounds=[];
    if(key){L.tileLayer('https://api.maptiler.com/maps/streets-v4/256/{z}/{x}/{y}.png?key='+encodeURIComponent(key),{maxZoom:19,attribution:'&copy; MapTiler &copy; OpenStreetMap'}).addTo(map)}else{L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map)}
    function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
    function fmtDate(s){if(!s)return '—';try{return new Date(s).toLocaleString(${serialize(lang==='ar'?'ar-SA':'en-GB')},{timeZone:'Asia/Riyadh'})}catch(e){return String(s)}}
    for(const z of zones){if(!Number.isFinite(z.latitude)||!Number.isFinite(z.longitude))continue;
      const center=[z.latitude,z.longitude];const color=z.mode==='restricted'?'#e65d50':'#20a78f';
      const shape=(z.shape && z.shape!=='circle' && Array.isArray(z.polygon_points) && z.polygon_points.length>=3)?L.polygon(z.polygon_points,{color,weight:2,fillOpacity:.10}):L.circle(center,{radius:z.radius_m,color,weight:2,fillOpacity:.10});
      shape.addTo(map).bindPopup('<b>'+esc(z.name)+'</b><br>'+esc(z.shape||'circle'));
      L.marker(center,{icon:L.divIcon({className:'',html:'<span style="background:#10283d;color:#c8fc61;border:1px solid #a5d84c;border-radius:5px;padding:4px;white-space:nowrap">'+esc(z.name)+'</span>'})}).addTo(map);
    }
    for(const p of positions){if(!Number.isFinite(p.latitude)||!Number.isFinite(p.longitude))continue;
      const color=p.state==='moving'?'#a5d84c':p.state==='stationary'?'#f0ac4d':'#9ca3af';
      const inside=(p.geofences||[]).filter(z=>z.status==='inside');const uncertain=(p.geofences||[]).filter(z=>z.status==='boundary_uncertain');
      const areaText=inside.length?inside.map(z=>esc(z.name)).join(', '):${serialize(lang==='en'?'Outside assigned geofences':'خارج المناطق المحددة')};
      const popup='<b>'+esc(p.plate)+'</b><br>'+esc(p.driver_name||'—')+'<br>${lang==='en'?'Status':'الحالة'}: '+esc(p.state)+'<br>${lang==='en'?'Speed':'السرعة'}: '+esc(p.speed_kmh??'—')+' km/h<br>${lang==='en'?'Last GPS':'آخر تحديث'}: '+esc(fmtDate(p.recorded_at))+'<br>${lang==='en'?'Age':'عمر البيانات'}: '+esc(p.age_seconds??'—')+' s<br>${lang==='en'?'GPS accuracy':'دقة GPS'}: '+esc(p.accuracy_m??'—')+' m<br>${lang==='en'?'Geofence':'المنطقة'}: '+areaText+(uncertain.length?'<br>${lang==='en'?'Boundary uncertain':'حدود المنطقة غير مؤكدة'}: '+uncertain.map(z=>esc(z.name)).join(', '):'');
      const marker=L.circleMarker([p.latitude,p.longitude],{radius:10,weight:2,color:'#10283d',fillColor:color,fillOpacity:1}).addTo(map).bindPopup(popup);
      if(${selectedVehicleId?'true':'false'})marker.openPopup();bounds.push([p.latitude,p.longitude]);
    }
    for(const e of events){if(!Number.isFinite(e.latitude)||!Number.isFinite(e.longitude))continue;const color=e.layer==='active'?'#e65d50':'#64748b';
      L.circleMarker([e.latitude,e.longitude],{radius:5,color,fillColor:color,fillOpacity:.85}).addTo(map).bindPopup('<b>'+esc(e.type)+'</b><br>'+esc(fmtDate(e.recorded_at))+'<br>'+esc(e.value));}
    if(bounds.length)map.fitBounds(L.latLngBounds(bounds).pad(.2),{maxZoom:14});else if(zones.length){map.setView([zones[0].latitude,zones[0].longitude],12)}
    </script></body></html>`;
  },[positions,zones,events,lang,selectedVehicleId,showActive,showPassive,showZones,limitEventsToPositions]);
  return <iframe title={lang==='en'?'Fleet tracking and geofences':'تتبع الأسطول والمناطق'} srcDoc={html} sandbox="allow-scripts" style={{width:'100%',height:530,border:0,borderRadius:12,background:'#e5e7eb'}}/>;
}
