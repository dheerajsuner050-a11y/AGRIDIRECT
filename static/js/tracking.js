/**
 * AgriDirect AI — Live GPS & WebSocket Tracking Client
 * Manages device geolocation streaming, WebSocket subscriber connections, and DEMO simulation.
 */

let activeGeoWatchId = null;
let activeWebSocket = null;
let demoSimulationTimer = null;

/**
 * Starts device GPS tracking using navigator.geolocation.watchPosition()
 * and continuously posts coordinates to the delivery backend.
 */
function startDeliveryGPSTracking(orderId, onUpdateCallback = null) {
  if (!navigator.geolocation) {
    console.warn("Geolocation API is not supported by this browser.");
    return null;
  }

  if (activeGeoWatchId !== null) {
    navigator.geolocation.clearWatch(activeGeoWatchId);
  }

  const options = {
    enableHighAccuracy: true,
    maximumAge: 3000,
    timeout: 10000
  };

  activeGeoWatchId = navigator.geolocation.watchPosition(
    async (position) => {
      const { latitude, longitude, speed, heading, accuracy } = position.coords;

      try {
        const res = await fetch(`/delivery/orders/${orderId}/location`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            latitude,
            longitude,
            speed: speed || 0.0,
            heading: heading || 0.0,
            accuracy: accuracy || 5.0
          })
        });

        if (res.ok) {
          const data = await res.json();
          if (onUpdateCallback) {
            onUpdateCallback({ latitude, longitude, speed, heading, ...data });
          }
        }
      } catch (err) {
        console.warn("Failed to stream GPS coordinate to server:", err);
      }
    },
    (err) => {
      console.warn("Geolocation watch error:", err.message);
    },
    options
  );

  return activeGeoWatchId;
}

/**
 * Stops device GPS tracking.
 */
function stopDeliveryGPSTracking() {
  if (activeGeoWatchId !== null) {
    navigator.geolocation.clearWatch(activeGeoWatchId);
    activeGeoWatchId = null;
  }
}

/**
 * Connects buyer tracking page to the FastAPI WebSocket live channel.
 */
function connectTrackingWebSocket(orderId, callbacks = {}) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/delivery/${orderId}`;

  if (activeWebSocket) {
    activeWebSocket.close();
  }

  activeWebSocket = new WebSocket(wsUrl);

  activeWebSocket.onopen = () => {
    console.log(`Connected to live tracking WebSocket for Order #${orderId}`);
    if (callbacks.onOpen) callbacks.onOpen();
  };

  activeWebSocket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "LOCATION_UPDATE" && callbacks.onLocationUpdate) {
        callbacks.onLocationUpdate(data);
      } else if (data.type === "STATUS_UPDATE" && callbacks.onStatusUpdate) {
        callbacks.onStatusUpdate(data);
      }
    } catch (e) {
      console.warn("Malformed WebSocket tracking message:", event.data);
    }
  };

  activeWebSocket.onclose = () => {
    console.log(`WebSocket closed for Order #${orderId}.`);
    if (callbacks.onClose) callbacks.onClose();
  };

  activeWebSocket.onerror = (err) => {
    console.warn("WebSocket error:", err);
    if (callbacks.onError) callbacks.onError(err);
  };

  return activeWebSocket;
}

/**
 * DEMO_MODE: Simulates live vehicle GPS movement along route coordinates.
 * Allows instant testing without needing physical hardware movement.
 */
function startDemoRouteSimulation(orderId, coordinates, onStepCallback) {
  if (demoSimulationTimer) {
    clearInterval(demoSimulationTimer);
  }

  if (!coordinates || coordinates.length === 0) return;

  let currentIndex = 0;
  const total = coordinates.length;
  // Step every 2 seconds
  demoSimulationTimer = setInterval(async () => {
    if (currentIndex >= total) {
      clearInterval(demoSimulationTimer);
      return;
    }

    const [lat, lon] = coordinates[currentIndex];
    const prevCoord = currentIndex > 0 ? coordinates[currentIndex - 1] : [lat, lon];
    const heading = Math.atan2(lon - prevCoord[1], lat - prevCoord[0]) * (180 / Math.PI);

    try {
      await fetch(`/delivery/orders/${orderId}/location`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: lat,
          longitude: lon,
          speed: 32.5,
          heading: (heading + 360) % 360,
          accuracy: 2.0
        })
      });
    } catch (e) {
      console.warn("Demo GPS ping error:", e);
    }

    if (onStepCallback) {
      onStepCallback({
        latitude: lat,
        longitude: lon,
        index: currentIndex,
        total: total
      });
    }

    currentIndex++;
  }, 2200);

  return demoSimulationTimer;
}

function stopDemoRouteSimulation() {
  if (demoSimulationTimer) {
    clearInterval(demoSimulationTimer);
    demoSimulationTimer = null;
  }
}
