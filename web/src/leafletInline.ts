// Leaflet for the map frames, taken from the locked npm package (web/package-lock.json) and written into each frame's
// HTML. The frames are sandboxed `srcDoc` iframes, so nothing is fetched from a CDN: no third party sees the dashboard
// user's address or can change the code that handles fleet positions, and the Content-Security-Policy does not need to
// allow any script host (web/Caddyfile).
import leafletCss from 'leaflet/dist/leaflet.css?raw';
import leafletJs from 'leaflet/dist/leaflet.js?raw';

// A literal "</script" inside the library would end the inline script early. In JavaScript "<\/script" is the same text.
const scriptSafe = (code: string) => code.replace(/<\/(script)/gi, '<\\/$1');

export const leafletStyleTag = `<style>${leafletCss}</style>`;
export const leafletScriptTag = `<script>${scriptSafe(leafletJs)}</script>`;
