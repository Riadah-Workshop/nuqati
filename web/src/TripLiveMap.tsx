import { useMemo, useEffect } from 'react';
import { leafletScriptTag, leafletStyleTag } from './leafletInline';

type Point = {latitude:number;longitude:number;recorded_at:string;speed_kmh?:number};
type Violation = {id:number;type:string;value:number;latitude:number;longitude:number;recorded_at:string};
type RouteData = {trip_id:number;status:string;started_at?:string;ended_at?:string|null;max_speed_kmh?:number|null;distance_km?:number;points:Point[];violations:Violation[];start:Point|null;end:Point|null;truncated?:boolean};

type TripLayers = {route:boolean;events:boolean;labels:boolean;direction:boolean};

// The whole frame as one HTML string (Leaflet included, see leafletInline.ts). Exported so that CI can open it in a real browser.
export function buildTripMapHtml({route,isAr,maptilerKey,autoPlay,overlayRoutes,layers}:{route:RouteData;isAr:boolean;maptilerKey:string;autoPlay:boolean;overlayRoutes:RouteData[];layers:TripLayers}):string{
    // Escape '<' so API-provided strings cannot inject HTML/script into srcDoc.
    const data=JSON.stringify({points:route.points,violations:route.violations,status:route.status,maptilerKey,tripId:route.trip_id,autoPlay,overlayRoutes:overlayRoutes.map(r=>({trip_id:r.trip_id,points:r.points,violations:r.violations})),layers}).replace(/</g,'\\u003c');
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${leafletStyleTag}<style>html,body,#map{margin:0;height:100%;width:100%}body{font-family:Arial,sans-serif}.legend{position:absolute;z-index:900;bottom:92px;left:12px;background:#101d2bf0;color:#edf7fb;padding:9px 12px;border-radius:10px;box-shadow:0 4px 16px #0005;font-size:12px}.playback{position:absolute;z-index:950;bottom:10px;left:10px;right:10px;background:#101d2bf2;color:#eef7fa;padding:12px;border:1px solid #426070;border-radius:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;box-shadow:0 5px 20px #0005}.playback button,.playback select{border:1px solid #496476;background:#203a4b;color:#eef7fa;padding:7px 12px;border-radius:8px;cursor:pointer}.playback button:disabled{opacity:.4;cursor:default}.playback input{flex:1;min-width:100px;accent-color:#a5d84c}.playback output{font-size:12px;min-width:90px;text-align:center}.playback .speed{font-size:12px;color:#b6ef8a}</style></head><body><div id="map"></div><div class="playback" id="playback"><button id="play" type="button">▶ ${isAr?'تشغيل':'Play'}</button><button id="reset" type="button">↺ ${isAr?'إعادة':'Restart'}</button><input id="timeline" type="range" min="0" max="0" value="0" aria-label="Trip timeline"><output id="progress">—</output><select id="rate" aria-label="Playback speed"><option value="1">1×</option><option value="2">2×</option><option value="5">5×</option><option value="10">10×</option></select><span class="speed" id="speed">—</span></div><div class="legend">🟢 ${isAr?'البداية':'Start'} &nbsp; 🔵 ${isAr?'آخر موقع / النهاية':'Latest / End'} &nbsp; 🔴 ${isAr?'مخالفة':'Violation'}</div>${leafletScriptTag}<script>
const data=${data};if(typeof L==='undefined'){document.getElementById('map').textContent='Map library unavailable. Check internet / content security policy.';throw new Error('Leaflet unavailable')}const map=L.map('map');
if(data.maptilerKey){
  L.tileLayer('https://api.maptiler.com/maps/streets-v4/256/{z}/{x}/{y}.png?key='+encodeURIComponent(data.maptilerKey),{maxZoom:19,attribution:'&copy; MapTiler &copy; OpenStreetMap contributors'}).addTo(map);
}else{
  const warning=document.createElement('div');warning.textContent='MapTiler API key is missing. Set VITE_MAPTILER_API_KEY in Coolify and redeploy.';
  Object.assign(warning.style,{position:'absolute',top:'10px',left:'10px',right:'10px',zIndex:'1000',background:'#fff3cd',padding:'10px',borderRadius:'6px'});
  document.body.appendChild(warning);
}

const pts=data.points.filter(p=>Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Math.abs(p.latitude)<=90&&Math.abs(p.longitude)<=180);const coords=pts.map(p=>[p.latitude,p.longitude]);
function pin(p,color,label){const marker=L.circleMarker([p.latitude,p.longitude],{radius:9,color:'#fff',weight:2,fillColor:color,fillOpacity:1}).addTo(map).bindPopup(label);if(data.layers.labels)marker.bindTooltip(label.replace(/<br>/g,' · '));return marker}
const overlayBounds=[];
const overlayColors=['#f59e0b','#a78bfa','#14b8a6','#f472b6','#fb7185'];
for(const [i,extra] of data.overlayRoutes.entries()){
 const valid=(extra.points||[]).filter(p=>Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Math.abs(p.latitude)<=90&&Math.abs(p.longitude)<=180);
 if(!valid.length)continue;
 for(const p of valid)overlayBounds.push([p.latitude,p.longitude]);
 if(data.layers.route)L.polyline(valid.map(p=>[p.latitude,p.longitude]),{color:overlayColors[i%overlayColors.length],weight:3,opacity:.75,dashArray:'7,5'}).addTo(map).bindPopup('Trip #'+extra.trip_id);
 if(data.layers.events)for(const event of extra.violations||[])if(Number.isFinite(event.latitude)&&Number.isFinite(event.longitude))pin(event,'#dc2626','Trip #'+extra.trip_id+' · '+String(event.type).replaceAll('_',' '));
}

if(coords.length){if(data.layers.route)L.polyline(coords,{color:'#2563eb',weight:5,opacity:.8}).addTo(map);pin(pts[0],'#16a34a','${isAr?'بداية الرحلة':'Trip start'}<br>'+new Date(pts[0].recorded_at).toLocaleString());const last=pts[pts.length-1];pin(last,'#2563eb','${isAr?'آخر موقع':'Latest location'}<br>'+new Date(last.recorded_at).toLocaleString()+'<br>'+Number(last.speed_kmh||0).toFixed(1)+' km/h');map.fitBounds(L.latLngBounds(coords).pad(.2),{maxZoom:16});}else if(overlayBounds.length){map.fitBounds(L.latLngBounds(overlayBounds).pad(.2),{maxZoom:16})}else{map.setView([24.7136,46.6753],5)}
// Direction markers are drawn from consecutive recorded positions; no synthetic samples.
if(data.layers.route&&data.layers.direction&&pts.length>=3){
 const stride=Math.max(1,Math.floor(pts.length/14));
 for(let i=stride;i<pts.length;i+=stride){
  const a=pts[Math.max(0,i-stride)],b=pts[i];
  const radians=Math.atan2(b.longitude-a.longitude,b.latitude-a.latitude);
  const angle=radians*180/Math.PI;
  L.marker([b.latitude,b.longitude],{icon:L.divIcon({className:'',html:'<span style="display:block;color:#c6ef55;text-shadow:0 1px 3px #000;font-size:18px;transform:rotate('+angle+'deg)">▲</span>',iconSize:[20,20],iconAnchor:[10,10]})}).addTo(map);
 }
}
// Playback uses the actual recorded timestamps and never fabricates GPS samples.
const playButton=document.getElementById('play');
const restartButton=document.getElementById('reset');
const slider=document.getElementById('timeline');
const rate=document.getElementById('rate');
const progress=document.getElementById('progress');
const speedLabel=document.getElementById('speed');
const timeline=pts.map(p=>new Date(p.recorded_at).getTime());
const validTimes=timeline.every(Number.isFinite);
const firstTime=validTimes&&timeline.length?timeline[0]:0;
const lastTime=validTimes&&timeline.length?timeline[timeline.length-1]:0;
const durationMs=Math.max(0,lastTime-firstTime);
let cursor=0,playing=false,lastFrame=0,frameId=0;
const vehicle=pts.length?L.circleMarker([pts[0].latitude,pts[0].longitude],{radius:11,color:'#102b34',weight:3,fillColor:'#a5d84c',fillOpacity:1}).addTo(map):null;
const traveled=pts.length?L.polyline([[pts[0].latitude,pts[0].longitude]],{color:'#a5d84c',weight:6,opacity:.95}).addTo(map):null;
slider.max=String(Math.max(0,durationMs));
function positionAt(ms){
  if(!pts.length)return;
  let index=0;
  while(index+1<pts.length&&timeline[index+1]<=firstTime+ms)index++;
  const p=pts[index];let lat=p.latitude,lon=p.longitude,spd=Number(p.speed_kmh||0);
  if(index+1<pts.length&&timeline[index+1]>timeline[index]){
    const fraction=Math.max(0,Math.min(1,(firstTime+ms-timeline[index])/(timeline[index+1]-timeline[index])));
    lat+=(pts[index+1].latitude-lat)*fraction;
    lon+=(pts[index+1].longitude-lon)*fraction;
    spd+=(Number(pts[index+1].speed_kmh||0)-spd)*fraction;
  }
  vehicle.setLatLng([lat,lon]);
  traveled.setLatLngs(pts.slice(0,index+1).map(p=>[p.latitude,p.longitude]).concat([[lat,lon]]));
  slider.value=String(Math.round(ms));
  progress.textContent=new Date(firstTime+ms).toLocaleTimeString('${isAr?'ar-SA':'en-GB'}',{timeZone:'Asia/Riyadh',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  speedLabel.textContent=spd.toFixed(0)+' km/h';
}
function stop(){playing=false;playButton.textContent='▶ ${isAr?'تشغيل':'Play'}';if(frameId)cancelAnimationFrame(frameId);frameId=0;lastFrame=0;}
function tick(now){if(!playing)return;if(lastFrame)cursor=Math.min(durationMs,cursor+(now-lastFrame)*Number(rate.value));lastFrame=now;positionAt(cursor);if(cursor>=durationMs){stop();if(data.autoPlay)parent.postMessage({nuqatiPlaybackEnded:data.tripId},'*');return;}frameId=requestAnimationFrame(tick);}
playButton.addEventListener('click',()=>{if(playing){stop();return;}if(cursor>=durationMs)cursor=0;playing=true;lastFrame=0;playButton.textContent='Ⅱ ${isAr?'إيقاف':'Pause'}';frameId=requestAnimationFrame(tick);});
restartButton.addEventListener('click',()=>{stop();cursor=0;positionAt(0);});
slider.addEventListener('input',()=>{cursor=Number(slider.value);positionAt(cursor);lastFrame=0;});
if(pts.length<2||!validTimes||durationMs<=0){playButton.disabled=true;slider.disabled=true;progress.textContent='${isAr?'بيانات غير كافية للتشغيل':'Not enough timed points'}';}else{positionAt(0);if(data.autoPlay)playButton.click();}
if(data.layers.events)for(const e of data.violations){if(!Number.isFinite(e.latitude)||!Number.isFinite(e.longitude))continue;const isMotion=e.type==='harsh_braking'||e.type==='harsh_acceleration'||e.type==='harsh_cornering';const unit=e.type==='speeding'?' km/h':isMotion?' km/h/s':'';const displayValue=Number(e.value)*(isMotion?3.6:1);const label=String(e.type).replaceAll('_',' ')+'<br>'+displayValue.toFixed(1)+unit+'<br>'+new Date(e.recorded_at).toLocaleString();pin(e,'#dc2626',label)}
</script></body></html>`;
}

export default function TripLiveMap({route,lang,autoPlay=false,onPlaybackEnded,overlayRoutes=[],layers={route:true,events:true,labels:true,direction:true}}:{route:RouteData;lang:'en'|'ar';autoPlay?:boolean;onPlaybackEnded?:()=>void;overlayRoutes?:RouteData[];layers?:TripLayers}) {
  useEffect(()=>{if(!autoPlay||!onPlaybackEnded)return;
    const handler=(e:MessageEvent)=>{if(e.data?.nuqatiPlaybackEnded===route.trip_id)onPlaybackEnded();};
    window.addEventListener('message',handler);return()=>window.removeEventListener('message',handler);
  },[autoPlay,onPlaybackEnded,route.trip_id]);
  useEffect(()=>{if(autoPlay && route.points.length<2 && onPlaybackEnded){
    const timer=window.setTimeout(onPlaybackEnded,300);return()=>window.clearTimeout(timer);
  }},[autoPlay,route.trip_id,route.points.length,onPlaybackEnded]);
  const isAr=lang==='ar';
  const maptilerKey = import.meta.env.VITE_MAPTILER_API_KEY || '';
  const html=useMemo(()=>buildTripMapHtml({route,isAr,maptilerKey,autoPlay,overlayRoutes,layers}),[route,isAr,maptilerKey,autoPlay,overlayRoutes,layers]);
  const last=route.end;
  const start=route.started_at?new Date(route.started_at):null;
  const end=route.ended_at?new Date(route.ended_at):null;
  const duration=start?Math.max(0,Math.floor(((end?.getTime()??Date.now())-start.getTime())/60000)):null;
  return <div style={{marginTop:12}}>
    <p>{route.status==='active'?(isAr?'● رحلة نشطة — تحديث تلقائي كل 15 ثانية':'● Active trip — auto-refresh every 15 seconds'):(isAr?'رحلة مكتملة':'Completed trip')} · {route.points.length} {isAr?'نقطة GPS':'GPS points'} · {route.violations.length} {isAr?'مخالفة':'violations'} · {overlayRoutes.length} {isAr?'مسارات إضافية':'additional routes'}</p>
    <p>{isAr?'البداية':'Start'}: {start?start.toLocaleString(isAr?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh'}):'—'} · {isAr?'النهاية':'Stop'}: {end?end.toLocaleString(isAr?'ar-SA':'en-GB',{timeZone:'Asia/Riyadh'}):(isAr?'جارية':'In progress')} · {isAr?'المدة':'Duration'}: {duration??'—'} {isAr?'دقيقة':'min'} · {isAr?'السرعة القصوى':'Max speed'}: {route.max_speed_kmh==null?'—':`${route.max_speed_kmh.toFixed(1)} km/h`} · {isAr?'المسافة':'Distance'}: {Number(route.distance_km||0).toFixed(2)} km</p>
    <iframe key={route.trip_id+'-'+route.points.length} title={isAr?'خريطة تتبع الرحلة':'Trip tracking map'} srcDoc={html} sandbox="allow-scripts" style={{width:'100%',height:540,border:'1px solid #334155',borderRadius:12,background:'#e5e7eb'}} />
    {last&&<p style={{fontSize:12,opacity:.8}}>{isAr?'آخر قراءة':'Last reading'}: {new Date(last.recorded_at).toLocaleString()} · {last.latitude.toFixed(5)}, {last.longitude.toFixed(5)}</p>}
    {route.truncated&&<p>{isAr?'المسار محدود بآخر ١٠٠٠٠ نقطة':'Route limited to 10,000 points'}</p>}
    {!route.points.length&&<p>{isAr?'لا توجد قراءات GPS لهذه الرحلة':'No GPS readings recorded for this trip'}</p>}
  </div>;
}
