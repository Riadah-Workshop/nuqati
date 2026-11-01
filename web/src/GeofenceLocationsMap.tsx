import {useEffect,useRef} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

type Zone={id:string;name:string;latitude:number;longitude:number;radius_m:number;mode:string};
type Props={zones:Zone[];focusedId:string|null;latitude:number|null;longitude:number|null;radius:number;language:'en'|'ar';onSelect:(lat:number,lng:number)=>void;onZoneClick:(id:string)=>void};
export default function GeofenceLocationsMap({zones,focusedId,latitude,longitude,radius,language,onSelect,onZoneClick}:Props){
 const host=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),layer=useRef<L.LayerGroup|null>(null);
 const onSelectRef=useRef(onSelect),zoneRef=useRef(onZoneClick);
 onSelectRef.current=onSelect;zoneRef.current=onZoneClick;
 useEffect(()=>{if(!host.current)return;const instance=L.map(host.current,{scrollWheelZoom:true}).setView([26.42,50.09],10);map.current=instance;
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(instance);
 layer.current=L.layerGroup().addTo(instance);
 instance.on('click',(e:L.LeafletMouseEvent)=>onSelectRef.current(e.latlng.lat,e.latlng.lng));
 const timeout=window.setTimeout(()=>instance.invalidateSize(),180);
 return()=>{window.clearTimeout(timeout);instance.remove();map.current=null;layer.current=null};},[]);
 useEffect(()=>{const m=map.current,l=layer.current;if(!m||!l)return;l.clearLayers();const bounds:L.LatLngExpression[]=[];
 for(const z of zones){const color=z.mode==='restricted'?'#ea654f':'#3ac6a4';const center:L.LatLngExpression=[z.latitude,z.longitude];
 const circle=L.circle(center,{radius:z.radius_m,color,weight:z.id===focusedId?4:2,fillOpacity:.13}).addTo(l);
 const label=L.marker(center,{icon:L.divIcon({className:'nuqati-zone-label',html:'<span></span>',iconSize:[0,0]})}).addTo(l);
 const el=document.createElement('span');el.className='nuqati-zone-label-text';el.textContent=z.name;
 (label.getElement()?.firstElementChild as HTMLElement|null)?.replaceWith(el);
 circle.on('click',()=>zoneRef.current(z.id));label.on('click',()=>zoneRef.current(z.id));bounds.push(center);
 }
 if(latitude!==null&&longitude!==null){L.circle([latitude,longitude],{radius,color:'#b4e95b',weight:2,fillOpacity:.16,dashArray:'5 4'}).addTo(l);bounds.push([latitude,longitude]);}
 const active=zones.find(z=>z.id===focusedId);
 if(active)m.flyTo([active.latitude,active.longitude],Math.max(11,Math.min(16,Math.round(15-Math.log2(Math.max(100,active.radius_m)/200)))));
 else if(bounds.length)m.fitBounds(L.latLngBounds(bounds).pad(.3),{maxZoom:13});
 },[zones,focusedId,latitude,longitude,radius]);
 return <div className="nuqati-geo-map-container"><div ref={host} className="nuqati-geo-leaflet" role="application" aria-label={language==='en'?'Geofence map':'خريطة المناطق الجغرافية'}/><div className="nuqati-geo-map-hint">{language==='en'?'Click the map to choose a new zone center':'انقر الخريطة لتحديد مركز منطقة جديدة'}</div></div>;
}
