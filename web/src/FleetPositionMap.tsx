import { useMemo } from 'react';

type DriverPin = {driver_id:number;driver_name:string;plate:string;latest_location:{latitude:number;longitude:number;recorded_at:string}|null};
export default function FleetPositionMap({drivers,lang}:{drivers:DriverPin[];lang:'en'|'ar'}){
  const points=useMemo(()=>drivers.filter(d=>d.latest_location&&Number.isFinite(d.latest_location.latitude)&&Number.isFinite(d.latest_location.longitude)&&Math.abs(d.latest_location.latitude)<=90&&Math.abs(d.latest_location.longitude)<=180).map(d=>({id:d.driver_id,name:d.driver_name,plate:d.plate,lat:d.latest_location!.latitude,lng:d.latest_location!.longitude,recorded_at:d.latest_location!.recorded_at})),[drivers]);
  const html=useMemo(()=>{
    const data=JSON.stringify(points).replace(/</g,'\\u003c');
    const key=JSON.stringify(import.meta.env.VITE_MAPTILER_API_KEY||'');
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>html,body,#map{width:100%;height:100%;margin:0}body{font:14px Arial} .empty{position:absolute;z-index:1000;top:15px;left:15px;background:#fff;color:#111;padding:10px;border-radius:6px}</style></head><body><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
      const pts=${data},key=${key}; const map=L.map('map').setView([24.7136,46.6753],6);
      if(key){L.tileLayer('https://api.maptiler.com/maps/streets-v4/256/{z}/{x}/{y}.png?key='+encodeURIComponent(key),{maxZoom:19,attribution:'&copy; MapTiler &copy; OpenStreetMap'}).addTo(map)}else{L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(map)}
      function escape(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
      const coords=[];for(const p of pts){L.circleMarker([p.lat,p.lng],{radius:9,weight:2,color:'#fff',fillColor:'#0a7c72',fillOpacity:1}).addTo(map).bindPopup('<b>'+escape(p.name)+'</b><br>'+escape(p.plate)+'<br>Last GPS: '+escape(new Date(p.recorded_at).toLocaleString()));coords.push([p.lat,p.lng])}
      if(coords.length)map.fitBounds(coords.length===1?L.latLngBounds(coords[0],coords[0]).pad(1):L.latLngBounds(coords).pad(.2),{maxZoom:13});else{const n=document.createElement('div');n.className='empty';n.textContent=${JSON.stringify(lang==='ar'?'لا توجد مواقع GPS مسجلة للشركة':'No recorded GPS positions for this company')};document.body.appendChild(n)}
      </script></body></html>`;
  },[points,lang]);
  return <iframe title={lang==='en'?'Fleet last known locations':'آخر مواقع مركبات الأسطول'} srcDoc={html} sandbox="allow-scripts" style={{width:'100%',height:'500px',border:0,borderRadius:12,background:'#e5e7eb'}}/>;
}
