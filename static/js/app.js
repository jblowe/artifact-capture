// Artifact Capture app scripts
(function () {
  "use strict";

  // Expose helpers for inline onclick handlers in templates.
  // These must be on window because this file is wrapped in an IIFE.

  window.requirePhoto = function (isRequired) {
    // Toggle the 'required' attribute on the active form's photo input.
    // Inline onclick runs before submit, so HTML5 validation can block submission.
    try {
      var panels = document.querySelectorAll(".type-panel");
      var activePanel = null;
      for (var i = 0; i < panels.length; i++) {
        if (panels[i].offsetParent !== null) { activePanel = panels[i]; break; }
      }
      var scope = activePanel || document;
      var photo = scope.querySelector('input[type="file"][name="photo"]');
      if (photo) {
        if (isRequired) photo.setAttribute("required", "required");
        else photo.removeAttribute("required");
      }
    } catch (e) {}
  };

  window.resetForm = function (typeKey) {
    try {
      var panel = document.querySelector('.type-panel[data-type="' + typeKey + '"]');
      if (!panel) return;
      var form = panel.querySelector("form.captureForm");
      if (!form) return;

      form.reset();

      // Clear GPS hidden fields (by name, IDs are dynamic)
      var lat = panel.querySelector('input[name="gps_lat"]');
      var lon = panel.querySelector('input[name="gps_lon"]');
      var acc = panel.querySelector('input[name="gps_acc"]');
      if (lat) lat.value = "";
      if (lon) lon.value = "";
      if (acc) acc.value = "";

      // Restore GPS status text if present
      var statusEl = panel.querySelector(".gps_status");
      if (statusEl) statusEl.textContent = "Tap to capture location";
    } catch (e) {}
  };



// Expose close handler for inline onclick in upload.html
  window.hideLastCard = function () {
    const card = document.getElementById("lastCard");
    if (card) card.style.display = "none";
  };



  // ---- helpers ----
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  // ---- persisted form values (per object type) ----
  // Stores values for inputs/selects/textareas (excluding file inputs) by object_type + field name.
  const PERSIST_KEY = "artifact_capture_persist_v2";

  function loadPersisted() {
    try { return JSON.parse(localStorage.getItem(PERSIST_KEY) || "{}"); }
    catch (e) { return {}; }
  }

  function savePersisted(obj) {
    try { localStorage.setItem(PERSIST_KEY, JSON.stringify(obj)); }
    catch (e) { /* ignore quota */ }
  }

  function initFormPersistence() {
    const panels = $all(".type-panel");
    if (!panels.length) return;

    const saved = loadPersisted();

    // Restore for each panel
    panels.forEach(panel => {
      const type = panel.getAttribute("data-type") || "";
      if (!type) return;

      const values = saved[type] || {};
      const fields = $all("input, select, textarea", panel);
      fields.forEach(el => {
        const name = el.getAttribute("name");
        if (!name) return;
        const tag = (el.tagName || "").toLowerCase();
        const typeAttr = (el.getAttribute("type") || "").toLowerCase();

        // skip file inputs and hidden object_type
        if (typeAttr === "file") return;
        if (typeAttr === "hidden" && name === "object_type") return;

        if (!(name in values)) return;

        if (typeAttr === "checkbox") {
          const v = values[name];
          if (Array.isArray(v)) {
            el.checked = v.map(String).includes(String(el.value));
          } else {
            el.checked = !!v;
          }
        } else if (typeAttr === "radio") {
          // restore by matching value
          if (String(el.value) === String(values[name])) el.checked = true;
        } else {
          el.value = values[name];
        }
      });
    });

    // Save on change/input for any form field
    function handleChange(ev) {
      const el = ev.target;
      if (!el || !(el instanceof HTMLElement)) return;

      const panel = el.closest(".type-panel");
      if (!panel) return;

      const type = panel.getAttribute("data-type") || "";
      if (!type) return;

      const name = el.getAttribute("name");
      if (!name) return;

      const typeAttr = (el.getAttribute("type") || "").toLowerCase();
      if (typeAttr === "file") return;
      if (typeAttr === "hidden" && name === "object_type") return;

      saved[type] = saved[type] || {};

      if (typeAttr === "checkbox") {
        // If there are multiple checkboxes with the same name (checkbox group), store an array of checked values.
        const group = $all(`input[type="checkbox"][name="${CSS.escape(name)}"]`, panel);
        if (group.length > 1) {
          const checked = group.filter(cb => cb.checked).map(cb => cb.value);
          saved[type][name] = checked;
        } else {
          saved[type][name] = !!el.checked;
        }
      } else if (typeAttr === "radio") {
        if (el.checked) saved[type][name] = el.value;
      } else {
        saved[type][name] = el.value;
      }
      savePersisted(saved);
    }

    document.addEventListener("input", handleChange, true);
    document.addEventListener("change", handleChange, true);
  }

  // ---- admin map (Leaflet) ----

  function initGPSCapture() {
    // Handles capturing client GPS and storing into hidden form fields.
    // Looks for a status element: .gps_status
    const statusEl = document.querySelector(".gps_status");
    if (!statusEl) return; // page doesn't have GPS UI

    // Helpers
    function setStatus(msg) {
      statusEl.textContent = msg;
    }
    function findField(selectors) {
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      return null;
    }
    // Try a few common names/ids from earlier iterations
    const latEl = findField(['input[name="gps_lat"]','input#gps_lat','input[name="lat"]','input#lat']);
    const lonEl = findField(['input[name="gps_lon"]','input[name="gps_lng"]','input#gps_lon','input#gps_lng','input[name="lon"]','input#lon','input[name="lng"]','input#lng']);
    const accEl = findField(['input[name="gps_acc"]','input[name="gps_accuracy"]','input#gps_acc','input#gps_accuracy','input[name="accuracy"]','input#accuracy']);
    const tsEl  = findField(['input[name="gps_ts"]','input[name="gps_timestamp"]','input#gps_ts','input#gps_timestamp']);

    function clearFields() {
      if (latEl) latEl.value = "";
      if (lonEl) lonEl.value = "";
      if (accEl) accEl.value = "";
      if (tsEl)  tsEl.value = "";
    }

    function formatCoords(lat, lon) {
      // Keep decent precision without being unreadable
      return `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
    }

    function requestOnce() {
      if (!("geolocation" in navigator)) {
        clearFields();
        setStatus("GPS not available in this browser.");
        return;
      }

      setStatus("Requesting location…");

      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const c = pos.coords || {};
          const lat = Number(c.latitude);
          const lon = Number(c.longitude);
          const acc = Number(c.accuracy);

          if (Number.isFinite(lat) && Number.isFinite(lon)) {
            if (latEl) latEl.value = String(lat);
            if (lonEl) lonEl.value = String(lon);
            if (accEl && Number.isFinite(acc)) accEl.value = String(acc);
            if (tsEl) tsEl.value = String(pos.timestamp || Date.now());
            setStatus(`${formatCoords(lat, lon)}${Number.isFinite(acc) ? " (±" + Math.round(acc) + "m)" : ""}`);
          } else {
            clearFields();
            setStatus("GPS failed: invalid coordinates returned.");
          }
        },
        (err) => {
          clearFields();
          // err.code: 1=denied, 2=unavailable, 3=timeout
          const msg = (err && err.message) ? err.message : "Unknown error";
          setStatus(`GPS failed (${err && err.code ? err.code : "?"}): ${msg}`);
          // Helpful hint for the most common case
          if (err && err.code === 1) {
            // Permission denied: user/site setting likely blocks prompts, especially on iOS
            statusEl.title = "If you're on iPhone/iPad: Settings → Privacy & Security → Location Services → Safari Websites → set to 'While Using the App', then allow location for this site.";
          }
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
      );
    }

    // Prefer a user gesture so iOS reliably prompts. Make the status clickable.
    statusEl.style.cursor = "pointer";
    statusEl.setAttribute("role", "button");
    statusEl.setAttribute("tabindex", "0");

    function onActivate() { requestOnce(); }
    statusEl.addEventListener("click", onActivate);
    statusEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onActivate();
      }
    });

    // Initial message; also try once automatically (works if permission already granted).
    clearFields();
    setStatus("Tap to capture location");
    // Auto-attempt shortly after load for users who have already granted permission
    setTimeout(() => requestOnce(), 350);
  }



  function initAdminMap() {
    const mapEl = document.getElementById("map");
    if (!mapEl) return;

    const statusEl = document.getElementById("map-status");
    function showStatus(msg) {
      if (!statusEl) return;
      statusEl.textContent = msg || "";
      statusEl.style.display = msg ? "block" : "none";
    }

    if (typeof window.L === "undefined") {
      showStatus("Map library failed to load.");
      return;
    }

    const geoUrl = mapEl.getAttribute("data-geojson-url");
    if (!geoUrl) {
      showStatus("Map data URL missing.");
      return;
    }

    // Basic map init
    const map = window.L.map(mapEl).setView([13.7367, 100.5231], 5); // Thailand-ish default; will fit bounds if points exist

    const tiles = window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    });
    tiles.addTo(map);

    showStatus("Loading points…");

    fetch(geoUrl, { credentials: "same-origin" })
      .then(r => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(gj => {
        if (!gj || !gj.features || !gj.features.length) {
          showStatus("No GPS-enabled records yet.");
          return;
        }

        const layer = window.L.geoJSON(gj, {
          pointToLayer: (feature, latlng) => window.L.circleMarker(latlng, { radius: 6 }),
          onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            const title = props.title || props.id || "Record";
            const link = props.url || null;
            const thumb = props.thumb || null;

            let html = `<strong>${escapeHtml(String(title))}</strong>`;
            if (thumb) html += `<div style="margin-top:.25rem"><img src="${thumb}" style="max-width:220px;max-height:140px;border-radius:6px;"></div>`;
            if (link) html += `<div style="margin-top:.35rem"><a href="${link}">Open</a></div>`;
            layer.bindPopup(html);
          }
        }).addTo(map);

        try {
          map.fitBounds(layer.getBounds().pad(0.1));
        } catch (e) { /* ignore */ }

        showStatus("");
      })
      .catch(err => {
        showStatus("Failed to load map points (" + err.message + ").");
      });
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[c]));
  }

  document.addEventListener("DOMContentLoaded", function () {
    initFormPersistence();
    initAdminMap();
      initGPSCapture();
});
})();
