// Artifact Capture app scripts
(function () {
  "use strict";

  // ---- helpers ----
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  // ---- persisted form values (per object type) ----
  // Stores values for inputs/selects/textareas (excluding file inputs) by object_type + field name.
  const PERSIST_KEY = "artifact_capture_persist_v1";

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
          el.checked = !!values[name];
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
        saved[type][name] = !!el.checked;
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
  });
})();
