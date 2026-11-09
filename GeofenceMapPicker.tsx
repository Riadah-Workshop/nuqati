import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

type Props = { latitude: number | null; longitude: number | null; radius: number; onSelect: (lat: number, lng: number) => void; language: 'en' | 'ar' };
export default function GeofenceMapPicker({latitude, longitude, radius, onSelect, language}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const circle = useRef<L.Circle | null>(null);
  const callback = useRef(onSelect);
  callback.current = onSelect;
  useEffect(() => {
    if (!container.current || map.current) return;
    const initial: L.LatLngExpression = [latitude ?? 26.42, longitude ?? 50.09];
    const instance = L.map(container.current, {scrollWheelZoom: false}).setView(initial, 11);
    map.current = instance;
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(instance);
    instance.on('click', (event: L.LeafletMouseEvent) => callback.current(event.latlng.lat, event.latlng.lng));
    const handle = window.setTimeout(() => instance.invalidateSize(), 150);
    return () => {window.clearTimeout(handle);instance.remove();map.current = null;circle.current = null;};
  }, []);
  useEffect(() => {
    if (!map.current) return;
    if (circle.current) {circle.current.remove();circle.current = null;}
    if (latitude === null || longitude === null) return;
    const center: L.LatLngExpression = [latitude, longitude];
    circle.current = L.circle(center, {radius: Math.max(50, Math.min(20000, radius)), color:'#16a34a', fillOpacity:0.15}).addTo(map.current);
    map.current.panTo(center);
  }, [latitude, longitude, radius]);
  return <div>
    <p>{language === 'ar' ? 'اضغط على الخريطة لتحديد مركز المنطقة، ثم عدّل نصف القطر.' : 'Click the map to choose the zone center, then adjust its radius.'}</p>
    <div ref={container} style={{height:340, width:'100%', borderRadius:12, overflow:'hidden', zIndex:0}} role="application" aria-label="Geofence map selector" />
  </div>;
}
