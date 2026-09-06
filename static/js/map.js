/**
 * AgriDirect AI — Map & OSRM Routing Engine
 * Integrates Leaflet.js with OpenStreetMap and OSRM Driving Directions.
 */

const DEFAULT_MAP_CENTER = [22.7196, 75.8577]; // Indore, India
const OSRM_ROUTER_URL = "https://router.project-osrm.org/route/v1/driving";

/**
 * Creates custom styled HTML/SVG Leaflet divIcon.
 */
function createCustomMarkerIcon(emoji, bgClass, pulse = false) {
  return L.divIcon({
    className: "custom-leaflet-marker",
    html: `
      <div style="position: relative; display: flex; align-items: center; justify-content: center;">
        ${pulse ? '<span style="position: absolute; width: 38px; height: 38px; border-radius: 50%; background: rgba(16, 185, 129, 0.4); animation: ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite;"></span>' : ''}
        <div style="width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; box-shadow: 0 4px 12px rgba(0,0,0,0.25); border: 2.5px solid white;" class="${bgClass}">
          ${emoji}
        </div>
      </div>
    `,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -20]
  });
}

/**
 * Initializes a Leaflet Map instance with OpenStreetMap tiles.
 */
function initAgriMap(containerId, center = DEFAULT_MAP_CENTER, zoom = 12) {
  const map = L.map(containerId, {
    zoomControl: true,
    attributionControl: true
  }).setView(center, zoom);

  // Modern OpenStreetMap tiles layer
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  return map;
}

/**
 * Fetches real driving route from OSRM public API.
 * Returns array of [lat, lon] coordinates, distance (km), and estimated duration (mins).
 */
async function fetchOSRMRoute(startLat, startLon, endLat, endLon) {
  const url = `${OSRM_ROUTER_URL}/${startLon},${startLat};${endLon},${endLat}?overview=full&geometries=geojson`;

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("OSRM routing service unavailable");
    const data = await response.json();

    if (!data.routes || data.routes.length === 0) {
      throw new Error("No driving route found between coordinates");
    }

    const route = data.routes[0];
    // Convert GeoJSON [lon, lat] coordinates to Leaflet [lat, lon]
    const latLngs = route.geometry.coordinates.map(coord => [coord[1], coord[0]]);
    const distanceKm = +(route.distance / 1000).toFixed(2);
    const durationMins = Math.ceil(route.duration / 60);

    return {
      coordinates: latLngs,
      distanceKm: distanceKm,
      durationMins: durationMins
    };
  } catch (err) {
    console.warn("OSRM routing fallback to straight line:", err.message);
    // Fallback straight-line coordinates
    return {
      coordinates: [[startLat, startLon], [endLat, endLon]],
      distanceKm: +(Math.hypot(endLat - startLat, endLon - startLon) * 111).toFixed(2),
      durationMins: 25
    };
  }
}

/**
 * Draws styled route polyline on Leaflet map and fits bounds.
 */
function drawRoutePolyline(map, coordinates, options = {}) {
  const polylineColor = options.color || "#059669";
  const polylineWeight = options.weight || 5;

  // Background glow polyline
  const glowLine = L.polyline(coordinates, {
    color: polylineColor,
    weight: polylineWeight + 3,
    opacity: 0.25,
    lineCap: "round",
    lineJoin: "round"
  }).addTo(map);

  // Main vibrant polyline
  const mainLine = L.polyline(coordinates, {
    color: polylineColor,
    weight: polylineWeight,
    opacity: 0.9,
    dashArray: options.dashed ? "8, 8" : null,
    lineCap: "round",
    lineJoin: "round"
  }).addTo(map);

  if (options.fitBounds !== false && coordinates.length > 0) {
    map.fitBounds(mainLine.getBounds(), { padding: [40, 40] });
  }

  return { mainLine, glowLine };
}
