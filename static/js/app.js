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

      // IMPORTANT: form.reset() only restores *default* values (what was rendered by Jinja)
      // and may look like it "does nothing". Users expect a true clear.
      var els = panel.querySelectorAll('input, select, textarea');
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        var name = el.getAttribute('name') || '';
        if (!name) continue;
        if (name === 'action' || name === 'submit_mode') continue;

        // Do not clear server-managed/readonly fields (e.g., date_recorded)
        if (el.hasAttribute('readonly')) continue;

        var tag = (el.tagName || '').toLowerCase();
        var type = (el.getAttribute('type') || '').toLowerCase();

        if (type === 'radio' || type === 'checkbox') {
          el.checked = false;
          continue;
        }
        if (type === 'file') {
          el.value = '';
          continue;
        }
        if (tag === 'select') {
          el.selectedIndex = 0;
          el.value = '';
          continue;
        }
        el.value = '';
      }

      // Clear GPS hidden fields (by name, IDs are dynamic)
      var lat = panel.querySelector('input[name="gps_lat"]');
      var lon = panel.querySelector('input[name="gps_lon"]');
      var acc = panel.querySelector('input[name="gps_acc"]');
      if (lat) lat.value = '';
      if (lon) lon.value = '';
      if (acc) acc.value = '';

      // Restore GPS status text if present
      var statusEl = panel.querySelector('.gps_status');
      if (statusEl) statusEl.textContent = 'Tap to capture location';
    } catch (e) {}
  };

  window.resetSelectedFields = function (typeKey) {
    // Clear only the fields listed in config.py object_types[...]['fields_to_reset']
    try {
      var panel = document.querySelector('.type-panel[data-type="' + typeKey + '"]');
      if (!panel) return;
      var raw = panel.getAttribute('data-reset-fields') || '[]';
      var fields = [];
      try { fields = JSON.parse(raw) || []; } catch (e) { fields = []; }
      if (!Array.isArray(fields) || fields.length === 0) return;

      fields.forEach(function(name){
        if (!name) return;
        var els = panel.querySelectorAll('[name="' + name + '"]');
        if (!els || !els.length) return;
        for (var i=0;i<els.length;i++) {
          var el = els[i];
          if (el.hasAttribute('readonly')) continue;
          var tag = (el.tagName || '').toLowerCase();
          var type = (el.getAttribute('type') || '').toLowerCase();
          if (type === 'radio' || type === 'checkbox') {
            el.checked = false;
            continue;
          }
          if (tag === 'select') {
            el.selectedIndex = 0;
            el.value = '';
            continue;
          }
          el.value = '';
        }
      });
    } catch (e) {}
  };




  // --- photo button labeling (mobile vs desktop) ---
  function isMobileCaptureDevice() {
    try {
      if (window.matchMedia && window.matchMedia('(pointer:coarse)').matches) return true;
      var ua = (navigator.userAgent || '').toLowerCase();
      return ua.includes('android') || ua.includes('iphone') || ua.includes('ipad') || ua.includes('ipod');
    } catch (e) {
      return false;
    }
  }

  window.updatePhotoFilename = function(typeKey, inputEl) {
    try {
      var nameEl = document.getElementById(typeKey + '__photo_name');
      if (!nameEl) return;
      var files = (inputEl && inputEl.files) ? inputEl.files : null;
      if (files && files.length) {
        nameEl.textContent = files[0].name;
      } else {
        nameEl.textContent = '';
      }
    } catch(e) {}
  };

  function initPhotoButtons() {
    var txt = isMobileCaptureDevice() ? 'Take photo' : 'Choose file';
    var nodes = document.querySelectorAll('.file-btn-text');
    for (var i=0;i<nodes.length;i++) nodes[i].textContent = txt;
  }

  // --- copy fields between object types ---
  window.copyFrom = function(targetType) {
    try {
      var targetPanel = document.querySelector('.type-panel[data-type="' + targetType + '"]');
      if (!targetPanel) return;
      var srcType = (targetPanel.getAttribute('data-copy-from') || '').trim();
      if (!srcType) return;
      var srcPanel = document.querySelector('.type-panel[data-type="' + srcType + '"]');
      if (!srcPanel) return;

      var raw = targetPanel.getAttribute('data-layout-fields') || '[]';
      var fields = [];
      try { fields = JSON.parse(raw) || []; } catch(e) { fields = []; }
      if (!Array.isArray(fields) || fields.length === 0) return;

      fields.forEach(function(name){
        if (!name) return;
        // Skip non-user controls
        if (name === 'action' || name === 'submit_mode' || name === 'object_type' || name === 'photo') return;

        var srcEls = srcPanel.querySelectorAll('[name="' + name + '"]');
        var tgtEls = targetPanel.querySelectorAll('[name="' + name + '"]');
        if (!srcEls || !srcEls.length || !tgtEls || !tgtEls.length) return;

        // If target is readonly, skip
        for (var j=0;j<tgtEls.length;j++) { if (tgtEls[j].hasAttribute('readonly')) return; }

        // Checkbox group
        var srcTypeAttr = (srcEls[0].getAttribute('type') || '').toLowerCase();
        var tgtTypeAttr = (tgtEls[0].getAttribute('type') || '').toLowerCase();
        if (srcTypeAttr === 'checkbox' || tgtTypeAttr === 'checkbox') {
          var selected = {};
          for (var i=0;i<srcEls.length;i++) {
            if (srcEls[i].checked) selected[srcEls[i].value] = true;
          }
          for (var k=0;k<tgtEls.length;k++) {
            tgtEls[k].checked = !!selected[tgtEls[k].value];
          }
          return;
        }

        // Radio group
        if (srcTypeAttr === 'radio' || tgtTypeAttr === 'radio') {
          var chosen = null;
          for (var i2=0;i2<srcEls.length;i2++) { if (srcEls[i2].checked) { chosen = srcEls[i2].value; break; } }
          for (var k2=0;k2<tgtEls.length;k2++) { tgtEls[k2].checked = (chosen !== null && tgtEls[k2].value === chosen); }
          return;
        }

        // Select
        if ((srcEls[0].tagName || '').toLowerCase() === 'select' || (tgtEls[0].tagName || '').toLowerCase() === 'select') {
          tgtEls[0].value = srcEls[0].value;
          return;
        }

        // Textarea / text / number etc
        tgtEls[0].value = srcEls[0].value;
      });
    } catch(e) {}
  };

  // Run small initializers
  document.addEventListener('DOMContentLoaded', function(){
    try { initPhotoButtons(); } catch(e) {}
  });

  // --- workflow helpers (New Record / Add image / Update Record) ---
  window.setAction = function(typeKey, action) {
    try {
      var panel = document.querySelector('.type-panel[data-type="' + typeKey + '"]');
      if (!panel) return;
      var hidden = panel.querySelector('input[type="hidden"][name="action"]');
      if (hidden) hidden.value = String(action || '');
    } catch(e) {}
  };

  const LAST_NEW_KEY = 'artifact_capture_last_new_v1';

  function loadLastNew() {
    try { return JSON.parse(localStorage.getItem(LAST_NEW_KEY) || '{}'); }
    catch(e) { return {}; }
  }
  function saveLastNew(obj) {
    try { localStorage.setItem(LAST_NEW_KEY, JSON.stringify(obj)); }
    catch(e) {}
  }

  function stableStringify(obj) {
    // Deterministic stringify with sorted keys; arrays are normalized to strings and sorted.
    if (obj === null || obj === undefined) return 'null';
    if (Array.isArray(obj)) {
      return '[' + obj.map(v => JSON.stringify(String(v))).sort().join(',') + ']';
    }
    if (typeof obj === 'object') {
      const keys = Object.keys(obj).sort();
      return '{' + keys.map(k => JSON.stringify(k) + ':' + stableStringify(obj[k])).join(',') + '}';
    }
    return JSON.stringify(String(obj));
  }

  function computeFormSignature(panel) {
    const data = {};
    // Collect all named inputs/selects/textareas except file + submit controls
    const fields = Array.from(panel.querySelectorAll('input, select, textarea'));
    // First handle checkbox groups
    const checkboxes = fields.filter(el => (el.getAttribute('type') || '').toLowerCase() === 'checkbox' && el.name);
    const checkboxNames = Array.from(new Set(checkboxes.map(el => el.name)));
    checkboxNames.forEach(name => {
      const group = checkboxes.filter(cb => cb.name === name);
      if (group.length > 1) {
        data[name] = group.filter(cb => cb.checked).map(cb => cb.value);
      } else {
        data[name] = group[0].checked ? 'true' : 'false';
      }
    });

    fields.forEach(el => {
      const name = el.getAttribute('name');
      if (!name) return;
      const typeAttr = (el.getAttribute('type') || '').toLowerCase();
      if (typeAttr === 'file') return;
      if (name === 'submit_mode' || name === 'action') return;
      if (typeAttr === 'hidden' && (name === 'gps_lat' || name === 'gps_lon' || name === 'gps_acc')) return;
      if (typeAttr === 'checkbox') return; // already handled
      if (typeAttr === 'radio') {
        if (el.checked) data[name] = el.value;
        return;
      }
      data[name] = el.value;
    });

    return stableStringify(data);
  }

  window.confirmDuplicateNewRecord = function(typeKey) {
    try {
      var panel = document.querySelector('.type-panel[data-type="' + typeKey + '"]');
      if (!panel) return true;
      var last = loadLastNew();
      var sig = computeFormSignature(panel);
      var prev = last[typeKey] || null;
      if (prev && prev === sig) {
        if (!window.confirm('Already Exists; Create a duplicate?')) {
          return false;
        }
      }
      last[typeKey] = sig;
      saveLastNew(last);
      return true;
    } catch(e) {
      return true;
    }
  };

  window.setSubmitMode = function(typeKey, mode) {
    try {
      var panel = document.querySelector('.type-panel[data-type="' + typeKey + '"]');
      if (!panel) return;
      var hidden = panel.querySelector('input[type="hidden"][name="submit_mode"]');
      if (hidden) hidden.value = String(mode || '');
    } catch(e) {}
  };

  window.handleNewRecordClick = function(typeKey, btn) {
    try {
      var panel = document.querySelector('.type-panel[data-type="' + typeKey + '"]');
      if (!panel) return true;
      var form = (btn && btn.closest) ? btn.closest('form') : null;
      if (!form) return true;

      // Prepare action + mode for server
      window.setAction(typeKey, 'new_record');
      window.setSubmitMode(typeKey, 'metadata');
      if (typeof requirePhoto === 'function') { try { requirePhoto(false); } catch(e) {} }

      var sig = computeFormSignature(panel);
      var last = loadLastNew();

      // Ask the server if this signature already exists
      if (btn) {
        btn.disabled = true;
        btn.dataset._oldText = btn.textContent;
        btn.textContent = 'Checking...';
      }

      var fd = new FormData(form);
      fetch('/exists', { method: 'POST', body: fd, headers: { 'X-Requested-With': 'fetch' } })
        .then(function(resp){ return resp.json(); })
        .then(function(data){
          var exists = !!(data && data.exists);
          if (exists) {
            if (!window.confirm('Already Exists; Create a duplicate?')) {
              return;
            }
          }
          // Remember last-click signature for this type
          last[typeKey] = sig;
          saveLastNew(last);
          form.submit();
        })
        .catch(function(){
          // Fail open: allow creating a new record
          last[typeKey] = sig;
          saveLastNew(last);
          form.submit();
        })
        .finally(function(){
          if (btn) {
            btn.disabled = false;
            if (btn.dataset._oldText) btn.textContent = btn.dataset._oldText;
          }
        });

      return false;
    } catch(e) {
      return true;
    }
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

  

  // ---- simple sortable tables (client-side) ----
  function initSortableTables() {
    const tables = $all("table[data-sortable='1']");
    if (!tables.length) return;

    function getCellValue(td) {
      if (!td) return "";
      const v = (td.getAttribute("data-sort") || td.textContent || "").trim();
      return v;
    }

    function isNumeric(val) {
      if (val === "") return false;
      return !isNaN(val) && isFinite(val);
    }

    tables.forEach((table) => {
      const thead = table.querySelector("thead");
      const tbody = table.querySelector("tbody");
      if (!thead || !tbody) return;

      const ths = Array.from(thead.querySelectorAll("th"));
      ths.forEach((th, idx) => {
        // Skip action columns (no sortkey)
        if (!th.getAttribute("data-sortkey")) return;

        th.style.cursor = "pointer";
        th.title = "Click to sort";

        th.addEventListener("click", () => {
          const current = th.getAttribute("data-sortdir") || "none";
          const dir = current === "asc" ? "desc" : "asc";

          // reset others
          ths.forEach((o) => { if (o !== th) o.removeAttribute("data-sortdir"); });
          th.setAttribute("data-sortdir", dir);

          const rows = Array.from(tbody.querySelectorAll("tr"));
          rows.sort((a, b) => {
            const av = getCellValue(a.children[idx]);
            const bv = getCellValue(b.children[idx]);

            const an = isNumeric(av) ? parseFloat(av) : null;
            const bn = isNumeric(bv) ? parseFloat(bv) : null;

            let cmp;
            if (an !== null && bn !== null) cmp = an - bn;
            else cmp = av.localeCompare(bv, undefined, { numeric: true, sensitivity: "base" });

            return dir === "asc" ? cmp : -cmp;
          });

          // Re-append in new order
          rows.forEach((r) => tbody.appendChild(r));
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initFormPersistence();
    initAdminMap();
    initGPSCapture();
    initSortableTables();
  });
})();
