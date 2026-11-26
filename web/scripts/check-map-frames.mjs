// CI check (not part of the production image's runtime): the two map frames must work with Leaflet taken from the
// locked npm package and with NO network access. Each frame is built by the real code (src/FleetPositionMap.tsx and
// src/TripLiveMap.tsx, loaded through Vite), opened in headless Chrome with every host name made unresolvable, and the
// resulting DOM is inspected. A control run with the Leaflet script removed must fail the same checks, so a pass means
// the library really ran. Usage (from web/):  node scripts/check-map-frames.mjs     (CHROME_BIN overrides "google-chrome")
import { createServer } from 'vite';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const chrome = process.env.CHROME_BIN || 'google-chrome';
console.log('browser:', execFileSync(chrome, ['--version'], { encoding: 'utf8' }).trim());

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' });
let fleetHtml, tripHtml, leafletTag;
try {
  const fleet = await server.ssrLoadModule('/src/FleetPositionMap.tsx');
  const trip = await server.ssrLoadModule('/src/TripLiveMap.tsx');
  const inline = await server.ssrLoadModule('/src/leafletInline.ts');
  leafletTag = inline.leafletScriptTag;

  const position = (id, lat, lon, state, driver) => ({
    vehicle_id: id, plate: `ABC ${id}00`, driver_name: `Driver ${id}`, driver_id: driver, latitude: lat, longitude: lon,
    recorded_at: '2026-11-26T10:00:00Z', speed_kmh: 42, accuracy_m: 8, age_seconds: 5, state, trip_active: true,
    geofences: [{ id: 'z1', name: 'Yard', status: 'inside' }],
  });
  fleetHtml = fleet.buildFleetMapHtml({
    lang: 'en', showPassive: true,
    positions: [position(1, 26.31, 50.2, 'moving', 11), position(2, 26.32, 50.21, 'stationary', 12), position(3, null, null, 'stale', 13)],
    zones: [
      { id: 'z1', name: 'Yard', latitude: 26.3, longitude: 50.2, radius_m: 300, mode: 'allowed', shape: 'circle' },
      { id: 'z2', name: 'Restricted', latitude: 26.4, longitude: 50.3, radius_m: 200, mode: 'restricted', shape: 'polygon', polygon_points: [[26.4, 50.3], [26.41, 50.31], [26.39, 50.32]] },
    ],
    events: [
      { id: 1, driver_id: 11, type: 'speeding', latitude: 26.305, longitude: 50.205, recorded_at: '2026-11-26T10:01:00Z', value: 130, layer: 'active' },
      { id: 2, driver_id: 12, type: 'harsh_braking', latitude: 26.306, longitude: 50.206, recorded_at: '2026-11-26T10:02:00Z', value: 9, layer: 'passive' },
    ],
  });
  const points = [0, 1, 2, 3, 4, 5].map(i => ({ latitude: 26.3 + i * 0.002, longitude: 50.2 + i * 0.002, recorded_at: new Date(Date.UTC(2026, 10, 26, 10, i)).toISOString(), speed_kmh: 40 + i }));
  tripHtml = trip.buildTripMapHtml({
    isAr: false, maptilerKey: 'ci-placeholder', autoPlay: false, overlayRoutes: [],
    layers: { route: true, events: true, labels: true, direction: true },
    route: {
      trip_id: 7, status: 'completed', started_at: points[0].recorded_at, ended_at: points[5].recorded_at, distance_km: 3.2, points,
      violations: [{ id: 1, type: 'speeding', value: 120, latitude: points[2].latitude, longitude: points[2].longitude, recorded_at: points[2].recorded_at }],
      start: points[0], end: points[5],
    },
  });
} finally {
  await server.close();
}

const dir = mkdtempSync(join(tmpdir(), 'map-frames-'));
function render(name, html) {
  const file = join(dir, `${name}.html`);
  writeFileSync(file, html);
  return rendered(execFileSync(chrome, [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--host-resolver-rules=MAP * ~NOTFOUND', // nothing can be fetched: no CDN, no tiles
    '--virtual-time-budget=10000', '--dump-dom', pathToFileURL(file).href,
  ], { encoding: 'utf8', timeout: 90000, maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }));
}
// dump-dom also prints the page's own <script> and <style> text (Leaflet's code and stylesheet contain class names and message
// strings), so every check looks at the rendered markup only.
const rendered = dom => dom.replace(/<script\b[\s\S]*?<\/script>/g, '').replace(/<style\b[\s\S]*?<\/style>/g, '');
const count = (dom, pattern) => (dom.match(pattern) || []).length;
const paths = dom => count(dom, /<path\b/g);
// Match the class attribute only: the inlined Leaflet stylesheet also contains these class names as text.
const hasClass = (dom, name) => new RegExp(`class="[^"]*\\b${name}\\b`).test(dom);
const markers = dom => count(dom, /class="[^"]*\bleaflet-marker-icon\b/g);

let failures = 0;
function expect(label, ok, detail = '') {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ` (${detail})` : ''}`);
  if (!ok) failures += 1;
}

for (const [name, html] of [['fleet', fleetHtml], ['trip', tripHtml]]) {
  expect(`${name}: the frame has no reference to a CDN`, !/unpkg\.com|cdn\./i.test(html));
  expect(`${name}: Leaflet is inline in the frame`, html.includes(leafletTag));
}

const fleetDom = render('fleet', fleetHtml);
expect('fleet: the map container exists', hasClass(fleetDom, 'leaflet-container'));
expect('fleet: 2 vehicles + 2 events + 2 geofences are drawn (6 shapes)', paths(fleetDom) === 6, `${paths(fleetDom)} shapes`);
expect('fleet: both geofence labels are markers', markers(fleetDom) === 2, `${markers(fleetDom)} markers`);
expect('fleet: the legend is there', fleetDom.includes('class="legend"'));

const tripDom = render('trip', tripHtml);
expect('trip: the map container exists', hasClass(tripDom, 'leaflet-container'));
expect('trip: route, travelled line and event are drawn', paths(tripDom) >= 3, `${paths(tripDom)} shapes`);
expect('trip: the library error message is absent', !/id="map"[^>]*>\s*Map library unavailable/.test(tripDom));
expect('trip: the playback bar has timed data', tripDom.includes('id="playback"') && !tripDom.includes('Not enough timed points') && !/<output id="progress"[^>]*>—/.test(tripDom));

// Control: without the Leaflet script the same checks must fail, otherwise a pass above would prove nothing.
const brokenFleet = render('fleet-without-leaflet', fleetHtml.split(leafletTag).join(''));
const brokenTrip = render('trip-without-leaflet', tripHtml.split(leafletTag).join(''));
expect('control: fleet frame without Leaflet draws nothing', !hasClass(brokenFleet, 'leaflet-container') && paths(brokenFleet) === 0);
expect('control: trip frame without Leaflet shows the error', /id="map"[^>]*>\s*Map library unavailable/.test(brokenTrip) && paths(brokenTrip) === 0);

if (failures) {
  const svg = dom => (dom.match(/<svg\b[^>]*>[\s\S]*?<\/svg>/) || ['(no svg)'])[0].slice(0, 1500);
  console.error('--- fleet overlay svg:', svg(fleetDom));
  console.error('--- trip overlay svg:', svg(tripDom));
  console.error(`${failures} map frame check(s) failed`);
  process.exit(1);
}
console.log('map frames: all checks passed');
