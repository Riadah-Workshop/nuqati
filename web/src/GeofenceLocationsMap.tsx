import {useEffect,useRef} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

type Point=[number,number];
type Zone={id:string;name:string;latitude:number;longitude:number;radius_m:number;mode:string;shape?:'circle'|'rectangle'|'polygon';polygon_points?:number[][]|null};
type Shape='circle'|'rectangle'|'polygon';
type Props={zones:Zone[];focusedId:string|null;latitude:number|null;longitude:number|null;radius:number;language:'en'|'ar';onSelect:(lat:number,lng:number)=>void;onZoneClick:(id:string)=>void;draftShape?:Shape;draftPoints?:Point[];onDraftPoint?:(lat:number,lng:number)=>void};
function rectangleCorners(points:Point[]):Point[]{
 if(points.length<2)return points;
 const [a,b]=points;
 return [[a[0],a[1]],[a[0],b[1]],[b[0],b[1]],[b[0],a[1]]];
}
export default function GeofenceLocationsMap({zones,focusedId,latitude,longitude,radius,language,onSelect,onZoneClick,draftShape='circle',draftPoints=[],onDraftPoint}:Props){
 const host=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),layer=useRef<L.LayerGroup|null>(null);
 const onSelectRef=useRef(onSelect),zoneRef=useRef(onZoneClick),draftRef=useRef(onDraftPoint),shapeRef=useRef(draftShape);
 onSelectRef.current=onSelect;zoneRef.current=onZoneClick;draftRef.current=onDraftPoint;shapeRef.current=draftShape;
 useEffect(()=>{if(!host.current)return;const instance=L.map(host.current,{scrollWheelZoom:true}).setView([26.42,50.09],10);map.current=instance;
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(instance);
 layer.current=L.layerGroup().addTo(instance);
 instance.on('click',(e:L.LeafletMouseEvent)=>{
  if(shapeRef.current==='circle')onSelectRef.current(e.latlng.lat,e.latlng.lng);
  else draftRef.current?.(e.latlng.lat,e.latlng.lng);
 });
 const timeout=window.setTimeout(()=>instance.invalidateSize(),180);
 return()=>{window.clearTimeout(timeout);instance.remove();map.current=null;layer.current=null};},[]);
 useEffect(()=>{const m=map.current,l=layer.current;if(!m||!l)return;l.clearLayers();const bounds:L.LatLngExpression[]=[];
 for(const z of zones){const color=z.mode==='restricted'?'#ea654f':'#3ac6a4';const center:L.LatLngExpression=[z.latitude,z.longitude];
  const polygon=(z.shape&&z.shape!=='circle'&&z.polygon_points&&z.polygon_points.length>=3)?z.polygon_points as Point[]:null;
  const shape=polygon?L.polygon(polygon,{color,weight:z.id===focusedId?4:2,fillOpacity:.13}):L.circle(center,{radius:z.radius_m,color,weight:z.id===focusedId?4:2,fillOpacity:.13});
  shape.addTo(l).on('click',(e:L.LeafletMouseEvent)=>{L.DomEvent.stopPropagation(e);zoneRef.current(z.id)});
  const label=L.marker(center,{icon:L.divIcon({className:'nuqati-zone-label',html:'<span></span>',iconSize:[0,0]})}).addTo(l);
  const el=document.createElement('span');el.className='nuqati-zone-label-text';el.textContent=z.name;
  (label.getElement()?.firstElementChild as HTMLElement|null)?.replaceWith(el);
  label.on('click',(e:L.LeafletMouseEvent)=>{L.DomEvent.stopPropagation(e);zoneRef.current(z.id)});
  if(polygon)bounds.push(...polygon);else bounds.push(center);
 }
 if(draftShape==='circle'&&latitude!==null&&longitude!==null){L.circle([latitude,longitude],{radius,color:'#b4e95b',weight:2,fillOpacity:.16,dashArray:'5 4'}).addTo(l);bounds.push([latitude,longitude]);}
 if(draftShape!=='circle'){
  const points=draftShape==='rectangle'?rectangleCorners(draftPoints):draftPoints;
  if(points.length>=3)L.polygon(points,{color:'#b4e95b',weight:2,fillOpacity:.14,dashArray:'5 4'}).addTo(l);
  else if(points.length>=2)L.polyline(points,{color:'#b4e95b',weight:2,dashArray:'5 4'}).addTo(l);
  draftPoints.forEach((point,index)=>{L.circleMarker(point,{radius:5,color:'#b4e95b',fillOpacity:1}).addTo(l).bindTooltip(String(index+1));bounds.push(point);});
 }
 const active=zones.find(z=>z.id===focusedId);
 if(active)m.flyTo([active.latitude,active.longitude],Math.max(11,Math.min(16,Math.round(15-Math.log2(Math.max(100,active.radius_m)/200)))));
 else if(bounds.length && !(draftShape!=='circle'&&draftPoints.length>0))m.fitBounds(L.latLngBounds(bounds).pad(.3),{maxZoom:15});
 },[zones,focusedId,latitude,longitude,radius,draftShape,draftPoints]);
 const hint=draftShape==='circle'?(language==='en'?'Click to choose a circle center':'اضغط لتحديد مركز الدائرة'):
  draftShape==='rectangle'?(language==='en'?'Click two opposite rectangle corners':'اضغط على زاويتين متقابلتين للمستطيل'):
  (language==='en'?'Click at least 3 polygon vertices in order':'اضغط على ثلاث زوايا على الأقل للمضلع بالترتيب');
 return <div className="nuqati-geo-map-container"><div ref={host} className="nuqati-geo-leaflet" role="application" aria-label={language==='en'?'Geofence map':'خريطة المناطق الجغرافية'}/><div className="nuqati-geo-map-hint">{hint}</div></div>;
}
