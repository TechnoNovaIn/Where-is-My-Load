import { $, h, svg, api, toast, when, ago, fmtTime, fmtDay, initHeader, currentTheme, contactBlock, contactList, PHONE_SVG } from "/static/common.js";

const STATUS_COLOR = {
  assigned: "--grey", loading: "--accent", dispatched: "--amber", in_transit: "--amber",
  near_destination: "--teal", arrived: "--teal", delivered: "--green",
};

const state = {
  me: null, isAdmin: false, multiParty: false,
  scope: "active", query: "", party: "", kpiFilter: "", since: "",
  items: [], hasMore: false, selectedId: null, detail: null,
  notifications: [], unread: 0, config: null,
  markers: new Map(), trail: null, fittedOnce: false, refreshTimer: null,
};

const tonnes = (t) => (t == null ? "" : `${Number(t).toLocaleString("en-IN", { maximumFractionDigits: 2 })} t`);
const plate = (no, large = false) => h("span", { class: large ? "plate large" : "plate" }, h("span", {}, no || "Unassigned"));
const pill = (s) => h("span", { class: `pill s-${s.status}` }, s.status_label);
const phoneDisplay = (p) => `${p.slice(0, 5)} ${p.slice(5)}`;
const placeOf = (s) => s.unload_site || s.destination || "destination";
const showParty = () => state.isAdmin || state.multiParty;

// ---------------------------------------------------------------- map (Ola Maps vector tiles via MapLibre)
let map = null;
const OLA = "https://api.olamaps.io/";
const TRAIL_SRC = "trail";

function styleFor(theme) { return theme === "light" ? state.config.map.style_light : state.config.map.style_dark; }

function mapUnavailable(msg) {
  $("mapOff").hidden = false;
  $("mapOffMsg").textContent = msg;
}

function initMap() {
  $("legend").open = window.matchMedia("(min-width: 861px)").matches; // collapsed on phones
  $("fitBtn").addEventListener("click", () => fitAll(true));
  if (!state.config.map.ready) {
    mapUnavailable("The Ola Maps key isn't configured on the server yet. Shipments, status and alerts still work.");
    return;
  }
  map = new maplibregl.Map({
    container: "map",
    style: styleFor(currentTheme()),
    center: [76.9, 14.2],
    zoom: 6,
    attributionControl: false,
    // Every Ola request goes through our server, which adds the API key.
    transformRequest: (url) => (url.startsWith(OLA)
      ? { url: `${location.origin}/olamaps/${url.slice(OLA.length)}`, credentials: "same-origin" }
      : { url }),
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: state.config.map.attribution }), "bottom-right");
  map.on("style.load", () => { if (state.detail) drawTrail(state.detail); });
  map.on("error", (e) => {
    const status = e?.error?.status;
    if (status === 401 || status === 403 || status === 503) {
      mapUnavailable("Ola Maps rejected the request. Check OLA_MAPS_API_KEY on the server.");
    }
  });
  document.addEventListener("themechange", (ev) => { map.setStyle(styleFor(ev.detail)); syncMarkers(true); });
}

function pinElement(s, selected) {
  // DOM + CSSOM only: the CSP forbids inline style attributes.
  const rot = s.position?.heading;
  const moving = rot != null && rot !== 0; // many units report 0 when parked
  const glyph = svg(moving
    ? `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l7 18-7-4-7 4z" fill="currentColor"/></svg>`
    : `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="7" width="13" height="9" rx="1" fill="currentColor"/><path d="M15 10h4l3 3v3h-7z" fill="currentColor"/></svg>`);
  if (moving) glyph.style.transform = `rotate(${Math.round(rot)}deg)`;
  const pin = h("div", { class: ["truck-pin", s.position?.stale ? "stale" : "", selected ? "selected" : ""].join(" ") }, glyph);
  pin.style.setProperty("--c", `var(${STATUS_COLOR[s.status] || "--accent"})`);
  return h("button", { class: "truck-marker", type: "button", "aria-label": `${s.vehicle_no}, ${s.status_label}`, title: s.vehicle_no },
    pin, selected ? h("span", { class: "truck-label" }, s.vehicle_no) : null);
}

function syncMarkers(force = false) {
  if (!map) return;
  const live = state.items.filter((s) => s.position);
  const show = state.selectedId ? live.filter((s) => s.id === state.selectedId) : live;
  const keep = new Set(show.map((s) => s.id));
  for (const [id, m] of state.markers) if (!keep.has(id)) { m.remove(); state.markers.delete(id); }
  for (const s of show) {
    const sel = s.id === state.selectedId;
    const el = pinElement(s, sel);
    el.addEventListener("click", (e) => { e.stopPropagation(); select(s.id); });
    let m = state.markers.get(s.id);
    if (!m) {
      m = new maplibregl.Marker({ element: h("div", { class: "marker-host" }, el), anchor: "center" });
      state.markers.set(s.id, m);
      m.setLngLat([s.position.lng, s.position.lat]).addTo(map);
    } else {
      m.getElement().replaceChildren(el);
      m.setLngLat([s.position.lng, s.position.lat]);
    }
    m.getElement().classList.toggle("on-top", sel);
  }
  if (!force && !state.fittedOnce && show.length) { fitAll(false); state.fittedOnce = true; }
}

function fitAll(animate) {
  if (!map) return;
  const pts = state.items.filter((s) => s.position).map((s) => [s.position.lng, s.position.lat]);
  if (!pts.length) return;
  if (pts.length === 1) { map.easeTo({ center: pts[0], zoom: 12, animate }); return; }
  const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
  for (const p of pts) b.extend(p);
  map.fitBounds(b, { padding: 56, maxZoom: 12, animate });
}

function focusOn(pos) {
  if (map && pos) map.easeTo({ center: [pos.lng, pos.lat], zoom: Math.max(map.getZoom(), 11) });
}

function clearTrail() {
  if (!map || !map.isStyleLoaded()) return;
  if (map.getLayer(TRAIL_SRC)) map.removeLayer(TRAIL_SRC);
  if (map.getSource(TRAIL_SRC)) map.removeSource(TRAIL_SRC);
}

function drawTrail(detail) {
  if (!map) return;
  if (!map.isStyleLoaded()) { map.once("idle", () => drawTrail(detail)); return; }
  clearTrail();
  const pts = (detail.trail || []).map(([lat, lng]) => [lng, lat]);
  if (detail.position) pts.push([detail.position.lng, detail.position.lat]);
  if (pts.length < 2) return;
  const color = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  map.addSource(TRAIL_SRC, { type: "geojson", data: { type: "Feature", geometry: { type: "LineString", coordinates: pts } } });
  map.addLayer({ id: TRAIL_SRC, type: "line", source: TRAIL_SRC, layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": color, "line-width": 4, "line-opacity": 0.85 } });
}

function resizeMap() { if (map) setTimeout(() => map.resize(), 60); }

// ---------------------------------------------------------------- list
function gpsLine(s) {
  if (s.status === "delivered") return [h("span", { class: "dot" }), `Delivered ${when(s.status_at)}`];
  if (!s.position) return [h("span", { class: "dot none" }), `No GPS signal, ${s.status_label.toLowerCase()} ${ago(s.status_at)}`];
  return [h("span", { class: s.position.stale ? "dot stale" : "dot" }),
    s.position.stale ? `Last GPS ${ago(s.position.at)}, weak signal` : `GPS ${ago(s.position.at)}`];
}

function renderList() {
  const list = $("shipList");
  list.replaceChildren();
  if (!state.items.length && !state.isAdmin && !(state.me.party_names || []).length) {
    list.append(h("li", { class: "empty" }, h("h3", {}, "Your login isn't linked to any party yet"),
      h("p", {}, "Ask Balaji Transports customer care to add your company's party names to this login."),
      contactList(state.me.contacts, { compact: true }) || contactBlock(state.me.contact, { compact: true })));
    return;
  }
  if (!state.items.length) {
    const searching = state.query.trim() || state.party;
    const kpiLabels = { loading: "at the plant", transit: "in transit", site: "at site", done_today: "delivered today" };
    const kpiMsg = kpiLabels[state.kpiFilter];
    list.append(h("li", { class: "empty" },
      h("h3", {}, searching ? "No matching shipments" : kpiMsg ? `No shipments ${kpiMsg}` : state.scope === "active" ? "Nothing on the way right now" : state.since ? `No deliveries from ${fmtDay.format(new Date(state.since + "T12:00:00+05:30"))}` : "No deliveries in the last 90 days"),
      h("p", {}, searching ? "Try a different truck number, product, site or party."
        : kpiMsg ? "Click the card again to clear the filter."
        : state.scope === "active" ? "New dispatches from JSW Toranagallu appear here as soon as a truck is assigned."
          : state.since ? "Try picking an earlier date or clear the filter."
          : "Delivered loads are listed here once unloaded.")));
    return;
  }
  for (const s of state.items) {
    const meta = [s.product, tonnes(s.net_weight)].filter(Boolean).join(", ");
    list.append(h("li", {},
      h("button", { class: "ship", type: "button", "aria-current": s.id === state.selectedId ? "true" : "false", onclick: () => select(s.id) },
        showParty() ? h("span", { class: "ship-party" }, s.party_name) : null,
        plate(s.vehicle_no), pill(s),
        h("span", { class: "ship-meta" }, meta, h("span", { class: "to" }, meta ? " to " : "To "), placeOf(s)),
        h("span", { class: "ship-when" }, gpsLine(s)))));
  }
  if (state.hasMore) {
    list.append(h("li", { class: "load-more-row" },
      h("button", { class: "btn ghost", type: "button", onclick: () => loadMore() }, "Load more")));
  }
}

async function loadList({ quiet = false, append = false } = {}) {
  try {
    const offset = append ? state.items.length : 0;
    const params = new URLSearchParams({ scope: state.scope, q: state.query.trim(), party: state.party, status_group: state.kpiFilter, since: state.since, limit: "100", offset: String(offset) });
    const data = await api(`/api/shipments?${params}`);
    if (append) { state.items = state.items.concat(data.items); } else { state.items = data.items; }
    state.hasMore = data.has_more;
    $("countActive").textContent = data.counts.active ? `(${data.counts.active})` : "";
    $("countDelivered").textContent = data.counts.delivered ? `(${data.counts.delivered})` : "";
    $("kLoading").textContent = data.summary.loading;
    $("kTransit").textContent = data.summary.in_transit;
    $("kSite").textContent = data.summary.at_site;
    $("kDone").textContent = data.summary.delivered_today;
    renderList();
    syncMarkers();
    setSyncNote(false);
    if (state.selectedId) refreshDetail();
  } catch (e) {
    if (!quiet) toast("Could not load shipments", e.message, { error: true });
    setSyncNote(true);
  }
}

async function loadMore() {
  const btn = $("shipList").querySelector(".load-more-row button");
  if (btn) { btn.disabled = true; btn.textContent = "Loading…"; }
  await loadList({ quiet: true, append: true });
}

function setSyncNote(failed) {
  const n = $("syncNote");
  n.classList.toggle("warn", failed);
  n.replaceChildren(h("span", { class: failed ? "dot stale" : "dot" }), failed
    ? "Connection problem. Showing last known positions, retrying."
    : `Live. Refreshes every ${state.config.refresh_seconds} s, last at ${fmtTime.format(new Date())}`);
}

// ---------------------------------------------------------------- detail
async function select(id) {
  state.selectedId = id;
  document.body.classList.add("detail-open");
  $("listView").hidden = true;
  const view = $("detailView");
  view.hidden = false;
  view.replaceChildren(detailHeader(null), h("div", { class: "detail-body" }, h("p", { class: "status-sub" }, "Loading shipment…")));
  renderList();
  syncMarkers();
  await refreshDetail(true);
  const s = state.detail;
  focusOn(s?.position);
  view.querySelector(".back")?.focus();
  history.replaceState(null, "", `#shipment-${id}`);
}

function closeDetail() {
  state.selectedId = null;
  state.detail = null;
  document.body.classList.remove("detail-open");
  clearTrail();
  $("detailView").hidden = true;
  $("listView").hidden = false;
  history.replaceState(null, "", location.pathname);
  renderList();
  syncMarkers(true);
  resizeMap();
}

function detailHeader(s) {
  return h("div", { class: "detail-head" },
    h("button", { class: "back", type: "button", onclick: closeDetail },
      svg(`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2"/></svg>`),
      "All shipments"),
    s ? h("span", { class: "status-sub" }, `#${s.id}`) : null);
}

async function refreshDetail(first = false) {
  const id = state.selectedId;
  if (!id) return;
  try {
    const d = await api(`/api/shipments/${id}`);
    if (state.selectedId !== id) return;
    state.detail = d;
    renderDetail(d);
    drawTrail(d);
  } catch (e) {
    if (first) { toast("Could not open shipment", e.message, { error: true }); closeDetail(); return; }
  }
  resizeMap();
}

function renderDetail(s) {
  const body = h("div", { class: "detail-body" });
  const add = (...nodes) => body.append(...nodes.filter((n) => n != null && n !== false)); // never append "null"
  add(
    h("div", { class: "detail-top" }, plate(s.vehicle_no, true), pill(s)),
    showParty() ? h("p", { class: "detail-party" }, s.party_name) : null,
    h("p", { class: "status-line" }, s.status_text),
    h("p", { class: "status-sub" }, `${s.status_label} ${s.status === "delivered" ? when(s.status_at) : ago(s.status_at)}`),
  );

  if (s.tracking) {
    const gps = s.position
      ? h("span", { class: s.position.stale ? "gps-stale" : "gps-ok" }, s.position.stale ? `Weak signal, last ${ago(s.position.at)}` : `Live, ${ago(s.position.at)}`)
      : h("span", { class: "gps-stale" }, "No signal yet");
    const phones = s.driver?.phones || [];  // present only for Balaji Transports staff
    add(h("div", { class: "card" },
      s.driver ? h("div", { class: "card-row" },
        h("div", { class: "card-label" }, "Driver (staff only)"),
        phones.length
          ? h("div", { class: "calls" }, phones.map((p) => h("a", { class: "call", href: `tel:+91${p}`, "aria-label": `Call the driver on ${p}` },
              svg(PHONE_SVG), phoneDisplay(p))))
          : h("small", {}, "Driver number not on record.")) : null,
      h("div", { class: "card-row" }, h("div", { class: "card-label" }, "GPS"), gps)));
  } else if (s.status === "delivered") {
    add(h("div", { class: "ended" }, "Delivered. Live tracking ends once a load is unloaded."));
  }
  if (!state.isAdmin) add(contactList(state.me.contacts, { shipmentId: s.id }) || contactBlock(state.me.contact, { shipmentId: s.id }));

  add(h("dl", { class: "facts" },
    h("dt", {}, "Load"), h("dd", {}, [s.product, tonnes(s.net_weight)].filter(Boolean).join(", ")),
    h("dt", {}, "From"), h("dd", {}, `JSW ${s.origin}`),
    h("dt", {}, "To"), h("dd", {}, s.unload_site ? `${s.unload_site}, ${s.destination}` : s.destination),
    h("dt", {}, "Dispatch date"), h("dd", {}, s.shipment_date ? fmtDay.format(new Date(`${s.shipment_date}T12:00:00+05:30`)) : "Not set"),
  ));
  add(h("h2", { class: "section-title" }, "Progress"));
  add(h("ol", { class: "timeline" }, (s.timeline || []).map((t) => h("li", { class: t.state },
    h("div", { class: "t-row" }, h("span", { class: "t-label" }, t.label),
      t.at ? h("span", { class: "t-time" }, when(t.at)) : t.state !== "pending" ? h("span", { class: "t-time" }, "Not recorded") : null),
    t.note ? h("div", { class: "t-note" }, t.note) : null))));

  $("detailView").replaceChildren(detailHeader(s), body);
}

// ---------------------------------------------------------------- notifications
function renderBell() {
  const b = $("bellBadge");
  b.hidden = state.unread === 0;
  b.textContent = state.unread > 99 ? "99+" : String(state.unread);
  $("bellBtn").setAttribute("aria-label", state.unread ? `Notifications, ${state.unread} unread` : "Notifications");
}

function renderNotifications() {
  const list = $("notifList");
  list.replaceChildren();
  if (!state.notifications.length) {
    list.append(h("li", { class: "empty" }, h("h3", {}, "No notifications yet"),
      h("p", {}, "You'll be alerted when a truck is assigned, dispatched, reaches your site and is unloaded.")));
    return;
  }
  for (const n of state.notifications) {
    list.append(h("li", {}, h("button", {
      class: n.read ? "notif" : "notif unread", type: "button",
      onclick: async () => { closePanel(); await markRead([n.id]); await openShipment(n.shipment_id); },
    }, h("span", { class: "n-title" }, n.title), h("span", { class: "n-body" }, n.body), h("span", { class: "n-time" }, ago(n.created_at)))));
  }
}

async function loadNotifications() {
  try {
    const d = await api("/api/notifications?limit=60");
    state.notifications = d.items;
    state.unread = d.unread;
    renderBell();
    renderNotifications();
  } catch { /* keep current */ }
}

async function markRead(ids) {
  try {
    await api("/api/notifications/read", { method: "POST", body: JSON.stringify(ids ? { ids } : {}) });
  } catch { return; }
  for (const n of state.notifications) if (!ids || ids.includes(n.id)) n.read = true;
  state.unread = state.notifications.filter((n) => !n.read).length;
  renderBell();
  renderNotifications();
}

function openPanel() {
  $("notifPanel").hidden = false;
  $("bellBtn").setAttribute("aria-expanded", "true");
  $("enableAlerts").hidden = !("Notification" in window) || Notification.permission !== "default";
  $("notifClose").focus();
}
function closePanel() { $("notifPanel").hidden = true; $("bellBtn").setAttribute("aria-expanded", "false"); }

async function openShipment(id) {
  if (!state.items.some((s) => s.id === id)) {
    setScope("active", false); state.party = ""; $("partySelect").value = "";
    await loadList({ quiet: true });
    if (!state.items.some((s) => s.id === id)) { setScope("delivered", false); await loadList({ quiet: true }); }
  }
  if (!state.items.some((s) => s.id === id)) {
    toast("Shipment not found", `#${id} may have been removed or isn't visible to your account.`, { error: true });
    return;
  }
  select(id);
}

function onNotification(n) {
  if (state.notifications.some((x) => x.id === n.id)) return;
  state.notifications.unshift(n);
  if (!n.read) state.unread += 1;
  renderBell();
  renderNotifications();
  toast(n.title, n.body, { onClick: () => openShipment(n.shipment_id) });
  if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    const sys = new Notification(n.title, { body: n.body, tag: `shipment-${n.shipment_id}`, icon: "/static/logo-192.png" });
    sys.onclick = () => { window.focus(); openShipment(n.shipment_id); sys.close(); };
  }
  loadList({ quiet: true });
}

let es;
function connectEvents() {
  es?.close();
  es = new EventSource("/api/events");
  es.addEventListener("notification", (ev) => { try { onNotification(JSON.parse(ev.data)); } catch { /* ignore */ } });
  es.addEventListener("session-expired", () => location.replace("/login"));
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) setTimeout(connectEvents, 10000); };
}
window.addEventListener("beforeunload", () => { es?.close(); });

// ---------------------------------------------------------------- controls
function updateFilterGrid() {
  const f = $("filters");
  const cols = [!$("partyWrap").hidden, !$("dateWrap").hidden].filter(Boolean).length;
  f.classList.remove("two", "three");
  if (cols === 2) f.classList.add("three");
  else if (cols === 1) f.classList.add("two");
}

function setScope(scope, reload = true) {
  state.scope = scope;
  for (const t of document.querySelectorAll(".tab")) t.setAttribute("aria-selected", String(t.dataset.scope === scope));
  const showDate = scope === "delivered";
  $("dateWrap").hidden = !showDate;
  if (!showDate) { state.since = ""; $("dateFilter").value = ""; }
  updateFilterGrid();
  if (reload) { if (state.selectedId) closeDetail(); loadList(); }
}

function setKpiFilter(filter) {
  state.kpiFilter = state.kpiFilter === filter ? "" : filter;
  for (const k of document.querySelectorAll(".kpi")) k.classList.toggle("active", k.dataset.filter === state.kpiFilter);
  if (state.kpiFilter) {
    if (state.kpiFilter === "done_today") setScope("delivered", false);
    else setScope("active", false);
  }
  if (state.selectedId) closeDetail();
  state.fittedOnce = false;
  loadList();
}

function wire() {
  for (const t of document.querySelectorAll(".tab")) t.addEventListener("click", () => { state.kpiFilter = ""; for (const k of document.querySelectorAll(".kpi")) k.classList.remove("active"); setScope(t.dataset.scope); });
  for (const k of document.querySelectorAll(".kpi")) k.addEventListener("click", () => setKpiFilter(k.dataset.filter));
  let debounce;
  $("search").addEventListener("input", (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { state.query = e.target.value; loadList(); }, 250);
  });
  $("partySelect").addEventListener("change", (e) => { state.party = e.target.value; if (state.selectedId) closeDetail(); state.fittedOnce = false; loadList(); });
  const onDateChange = (e) => { if (state.since !== e.target.value) { state.since = e.target.value; $("dateClear").hidden = !e.target.value; loadList(); } };
  $("dateFilter").addEventListener("change", onDateChange);
  $("dateFilter").addEventListener("input", onDateChange);
  $("dateClear").addEventListener("click", () => { state.since = ""; $("dateFilter").value = ""; $("dateClear").hidden = true; loadList(); });
  $("exportBtn").addEventListener("click", () => {
    const params = new URLSearchParams({ scope: state.scope, party: state.party, since: state.since });
    window.open(`/api/shipments/export.csv?${params}`, "_blank");
  });
  $("bellBtn").addEventListener("click", (e) => { e.stopPropagation(); $("notifPanel").hidden ? openPanel() : closePanel(); });
  $("notifClose").addEventListener("click", closePanel);
  $("markAllBtn").addEventListener("click", () => markRead(null));
  $("enableAlerts").addEventListener("click", async () => { await Notification.requestPermission(); $("enableAlerts").hidden = true; });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("notifPanel").hidden) { closePanel(); $("bellBtn").focus(); } else if (state.selectedId) closeDetail();
  });
  document.addEventListener("click", (e) => {
    const p = $("notifPanel");
    if (!p.hidden && !p.contains(e.target) && !$("bellBtn").contains(e.target)) closePanel();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { loadList({ quiet: true }); if (!state.isAdmin) loadNotifications(); } });
  window.addEventListener("offline", () => { $("offlineBanner").hidden = false; });
  window.addEventListener("online", () => { $("offlineBanner").hidden = true; loadList({ quiet: true }); if (!state.isAdmin) connectEvents(); });
}

// ---------------------------------------------------------------- boot
(async function boot(attempt = 0) {
  try {
    state.me = await initHeader("track");
    state.config = await api("/api/config");
  } catch (e) {
    if (e.message === "signed out") return;
    if (attempt < 2) { setTimeout(() => boot(attempt + 1), 1500); return; }
    document.body.setAttribute("data-boot-error", "");
    toast("Connection problem", "Couldn't load the page. Retrying…", { error: true });
    setTimeout(() => boot(0), 4000);
    return;
  }
  document.body.removeAttribute("data-boot-error");
  state.isAdmin = state.me.user.role === "admin";
  const names = state.me.party_names || [];
  state.multiParty = names.length > 1;
  if (state.multiParty) {
    $("partyWrap").hidden = false;
    updateFilterGrid();
    for (const n of names) $("partySelect").append(h("option", { value: n }, n));
  }
  $("bellBtn").hidden = state.isAdmin; // staff see everything; alerts are for parties
  initMap();
  wire();
  await Promise.all([loadList(), state.isAdmin ? null : loadNotifications()]);
  clearInterval(state.refreshTimer);
  state.refreshTimer = setInterval(() => { if (!document.hidden) loadList({ quiet: true }); }, state.config.refresh_seconds * 1000);
  if (!state.isAdmin) connectEvents();
  const m = location.hash.match(/^#shipment-(\d+)$/);
  if (m) openShipment(Number(m[1]));
})();
