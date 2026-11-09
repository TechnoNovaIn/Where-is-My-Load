// Shared helpers for the tracker and the admin console.
export const TZ = "Asia/Kolkata";
export const $ = (id) => document.getElementById(id);

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "value") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function svg(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim(); // static markup only, never data
  return t.content.firstChild;
}

export const fmtTime = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
export const fmtDay = new Intl.DateTimeFormat("en-IN", { timeZone: TZ, day: "numeric", month: "short", year: "numeric" });
export const when = (iso) => (iso ? fmtTime.format(new Date(iso)) : "");
export function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return when(iso);
}

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...opts,
    headers: {
      Accept: "application/json", "X-Requested-With": "fetch",
      ...(opts.body ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}),
    },
  });
  if (res.status === 401) { location.replace("/login"); throw new Error("signed out"); }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const d = (await res.json()).detail;
      msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg?.replace(/^Value error, /, "")).join("; ") : msg;
    } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

export function toast(title, body, { onClick, error = false } = {}) {
  const t = h("button", { class: error ? "toast error" : "toast", type: "button", onclick: () => { t.remove(); onClick?.(); } },
    h("b", {}, title), body || "");
  $("toasts").append(t);
  setTimeout(() => t.remove(), error ? 9000 : 7000);
}

export function currentTheme() { return document.documentElement.getAttribute("data-theme") || "dark"; }
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("bt-theme", t); } catch { /* ignore */ }
  $("themeLabel").textContent = t === "dark" ? "Light theme" : "Dark theme";
  document.dispatchEvent(new CustomEvent("themechange", { detail: t }));
}

export const PHONE_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11 11 0 0 0 3.6.6 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1 11 11 0 0 0 .6 3.6 1 1 0 0 1-.25 1z" fill="currentColor"/></svg>`;
export const WA_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 0 0-7.8 13.5L3 21l4.6-1.2A9 9 0 1 0 12 3zm4.6 12.6c-.2.6-1.1 1.1-1.6 1.1-.4.1-1 .1-3.1-.8-2.6-1.1-4.3-3.8-4.4-4-.1-.2-1-1.4-1-2.7s.7-1.9.9-2.2c.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.5l.8 1.9c.1.2.1.4 0 .5l-.3.5-.4.4c-.1.1-.3.3-.1.6.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.4 2.4 1.5.3.1.5.1.6-.1l.8-1c.2-.3.4-.2.6-.1l1.8.9c.3.1.4.2.5.3 0 .1 0 .7-.2 1.3z" fill="currentColor"/></svg>`;
export const MAIL_SVG = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M22 6l-10 7L2 6" fill="none" stroke="currentColor" stroke-width="2"/></svg>`;

/** Contact card for customer care (CRM). context: "shipment" adds the shipment number to quote. */
export function contactBlock(c, { shipmentId = null, compact = false } = {}) {
  if (!c) return null;
  const actions = [h("a", { class: "call", href: `tel:${c.tel}`, "aria-label": `Call ${c.label} on ${c.phone}` }, svg(PHONE_SVG), c.phone)];
  if (c.alt_phone) actions.push(h("a", { class: "btn", href: `tel:${c.alt_tel}`, "aria-label": `Call ${c.label} on ${c.alt_phone}` }, svg(PHONE_SVG), c.alt_phone));
  if (c.whatsapp) {
    const text = shipmentId ? `?text=${encodeURIComponent(`Hello, about shipment #${shipmentId}`)}` : "";
    actions.push(h("a", { class: "btn wa", href: `${c.whatsapp}${text}`, target: "_blank", rel: "noopener" }, svg(WA_SVG), "WhatsApp"));
  }
  return h("div", { class: compact ? "crm-card compact" : "crm-card" },
    h("div", { class: "crm-card-head" },
      h("div", { class: "card-label" }, c.label),
      h("div", { class: "crm-card-sub" }, shipmentId ? `For updates or follow-up, quote shipment #${shipmentId}` : "For updates, follow-up or account help"),
      c.hours ? h("div", { class: "crm-card-sub" }, c.hours) : null),
    h("div", { class: "crm-card-actions" }, actions),
    c.email ? h("a", { class: "crm-mail", href: `mailto:${c.email}${shipmentId ? `?subject=${encodeURIComponent(`Shipment #${shipmentId}`)}` : ""}` }, c.email) : null);
}

export function contactList(contacts, opts = {}) {
  if (!contacts || !contacts.length) return null;
  if (contacts.length === 1) return contactBlock(contacts[0], opts);
  return h("div", { class: "crm-list-user" }, ...contacts.map((c) => contactBlock(c, opts)));
}

export function renderCrmChip(contacts) {
  const chip = $("crmChip");
  if (!chip) return;
  if (!contacts || !contacts.length) { chip.hidden = true; return; }
  chip.hidden = false;

  if (contacts.length === 1) {
    const c = contacts[0];
    chip.href = `tel:${c.tel}`;
    chip.onclick = null;
    chip.setAttribute("aria-label", `${c.label}: call ${c.phone}`);
    chip.title = c.hours ? `${c.label}, ${c.hours}` : c.label;
    $("crmLabel").textContent = c.label;
    $("crmNumber").textContent = c.phone;
    const old = $("crmDropdown");
    if (old) old.remove();
    return;
  }

  chip.removeAttribute("href");
  chip.style.cursor = "pointer";
  chip.setAttribute("aria-label", `${contacts.length} support contacts`);
  chip.title = `${contacts.length} support contacts`;
  $("crmLabel").textContent = "Support team";
  $("crmNumber").textContent = `${contacts.length} contacts`;

  let dd = $("crmDropdown");
  if (!dd) {
    dd = h("div", { class: "crm-dropdown", id: "crmDropdown" });
    chip.parentElement.style.position = "relative";
    chip.after(dd);
    chip.addEventListener("click", (e) => { e.preventDefault(); dd.hidden = !dd.hidden; });
    document.addEventListener("click", (e) => {
      if (!chip.contains(e.target) && !dd.contains(e.target)) dd.hidden = true;
    });
  }
  dd.hidden = true;
  dd.replaceChildren(
    ...contacts.map((ct) =>
      h("div", { class: "crm-dd-item" },
        h("strong", {}, ct.label),
        h("div", { class: "crm-dd-links" },
          h("a", { href: `tel:${ct.tel}` }, svg(PHONE_SVG), ct.phone),
          ct.alt_phone ? h("a", { href: `tel:${ct.alt_tel}` }, svg(PHONE_SVG), ct.alt_phone) : null,
          ct.whatsapp ? h("a", { href: ct.whatsapp, target: "_blank", rel: "noopener" }, svg(WA_SVG), "WhatsApp") : null,
          ct.email ? h("a", { href: `mailto:${ct.email}` }, svg(MAIL_SVG), ct.email) : null),
        ct.hours ? h("small", {}, ct.hours) : null))
  );
}

/** Fill the shared header, wire the user menu, return /api/auth/me (plus .contact for party users). */
export async function initHeader(page) {
  const me = await api("/api/auth/me");
  const u = me.user;
  const isAdmin = u.role === "admin";
  me.contact = null;
  me.contacts = [];
  if (!isAdmin) {
    try {
      const cd = await api("/api/contact");
      me.contact = cd.contact;
      me.contacts = cd.contacts || (cd.contact ? [cd.contact] : []);
    } catch { /* header works without it */ }
    renderCrmChip(me.contacts);
  }
  $("userName").textContent = u.display_name;
  $("avatar").textContent = (u.display_name || u.username).trim().slice(0, 1).toUpperCase();
  $("menuName").textContent = u.display_name;
  $("menuCompany").textContent = [u.company, isAdmin ? "Administrator" : ""].filter(Boolean).join(", ") || u.username;
  $("brandSub").textContent = isAdmin ? "Operations console" : (u.company || "by Balaji Transports");
  $("navAdmin").hidden = !isAdmin;
  document.querySelector(".nav").hidden = !isAdmin; // parties only have the tracking page
  (page === "admin" ? $("navAdmin") : $("navTrack")).setAttribute("aria-current", "page");
  $("themeLabel").textContent = currentTheme() === "dark" ? "Light theme" : "Dark theme";

  const menu = $("userMenu");
  const btn = $("userBtn");
  const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; btn.setAttribute("aria-expanded", String(!menu.hidden)); });
  document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { close(); btn.focus(); } });
  $("themeBtn").addEventListener("click", () => { applyTheme(currentTheme() === "dark" ? "light" : "dark"); close(); });
  $("pwBtn").addEventListener("click", () => { close(); openPasswordDialog({ username: u.username }); });
  if (me.must_change_password) openPasswordDialog({ username: u.username, forced: true });
  $("logoutBtn").addEventListener("click", async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } finally { location.replace("/login"); }
  });
  return me;
}

/** Change-password dialog. forced=true: shown after an admin-issued password; cannot be dismissed. */
export function openPasswordDialog({ username, forced = false }) {
  if (document.getElementById("pwDialog")) return;
  const field = (label, auto) => {
    const input = h("input", { class: "input", type: "password", autocomplete: auto, required: true });
    return [input, h("label", { class: "field" }, h("span", {}, label), input)];
  };
  const [cur, curField] = field(forced ? "Temporary password" : "Current password", "current-password");
  const [next, nextField] = field("New password", "new-password");
  const [again, againField] = field("Repeat new password", "new-password");
  const show = h("input", { type: "checkbox" });
  show.addEventListener("change", () => { for (const i of [cur, next, again]) i.type = show.checked ? "text" : "password"; });
  const err = h("p", { class: "form-error", role: "alert", hidden: true });
  const save = h("button", { class: "btn primary", type: "submit" }, "Change password");
  const cancel = forced ? null : h("button", { class: "btn ghost", type: "button", onclick: () => close() }, "Cancel");
  const form = h("form", { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "pwTitle", novalidate: true },
    h("h2", { id: "pwTitle" }, forced ? "Set your own password" : "Change password"),
    h("p", {}, forced
      ? "You signed in with a temporary password from Balaji Transports. Choose your own to continue."
      : "You stay signed in here; other devices will be signed out."),
    curField, nextField,
    h("small", { class: "u-sub" }, "At least 10 characters, not containing your username."),
    againField,
    h("label", { class: "switch" }, show, "Show passwords"),
    err,
    h("div", { class: "modal-actions" },
      forced ? h("button", { class: "btn ghost", type: "button", onclick: async () => {
        try { await api("/api/auth/logout", { method: "POST" }); } finally { location.replace("/login"); }
      } }, "Sign out") : cancel, save));
  const back = h("div", { class: "modal-backdrop", id: "pwDialog" }, form);
  const onKey = (e) => { if (e.key === "Escape" && !forced) close(); };
  function close() { back.remove(); document.removeEventListener("keydown", onKey); }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    const problem = !cur.value ? "Enter your current password."
      : next.value.length < 10 ? "The new password needs at least 10 characters."
        : username && next.value.toLowerCase().includes(username.toLowerCase()) ? "The password must not contain your username."
          : next.value !== again.value ? "The new passwords don't match."
            : next.value === cur.value ? "Choose a password different from the current one." : null;
    if (problem) { err.textContent = problem; err.hidden = false; return; }
    save.disabled = true;
    try {
      await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: cur.value, new_password: next.value }) });
      close();
      toast("Password changed", forced ? "Welcome. Your new password is active." : "Other devices have been signed out.");
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      save.disabled = false;
    }
  });
  document.body.append(back);
  document.addEventListener("keydown", onKey);
  cur.focus();
}
