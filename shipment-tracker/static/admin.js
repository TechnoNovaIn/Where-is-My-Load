import { $, h, svg, api, toast, when, ago, initHeader, contactBlock } from "/static/common.js";

const state = { me: null, users: [], parties: [], view: "users" };
const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");

function confirmAction(message, { confirmLabel = "Confirm", danger = false } = {}) {
  return new Promise((resolve) => {
    const yes = h("button", { class: danger ? "btn danger" : "btn primary", type: "button", onclick: () => { back.remove(); resolve(true); } }, confirmLabel);
    const no = h("button", { class: "btn ghost", type: "button", onclick: () => { back.remove(); resolve(false); } }, "Cancel");
    const onKey = (e) => { if (e.key === "Escape") { back.remove(); document.removeEventListener("keydown", onKey); resolve(false); } };
    const back = h("div", { class: "modal-backdrop" }, h("div", { class: "modal", role: "alertdialog", "aria-modal": "true", "aria-label": "Confirm action" },
      h("h2", {}, danger ? "Are you sure?" : "Confirm"),
      h("p", {}, message),
      h("div", { class: "modal-actions" }, no, yes)));
    document.body.append(back);
    document.addEventListener("keydown", onKey);
    yes.focus();
  });
}

// ---------------------------------------------------------------- data
async function loadUsers() {
  const d = await api("/api/admin/users");
  state.users = d.items;
  renderUsers();
  renderStats();
}
async function loadParties() {
  const d = await api("/api/admin/party-names");
  state.parties = d.items;
  renderParties();
  renderStats();
}

function renderStats() {
  $("sUsers").textContent = state.users.filter((u) => u.role === "party" && u.active).length;
  $("sAdmins").textContent = state.users.filter((u) => u.role === "admin").length;
  $("sNames").textContent = state.parties.length || "–";
  $("sUnassigned").textContent = state.parties.length ? state.parties.filter((p) => !p.users.length).length : "–";
}

// ---------------------------------------------------------------- users table
function chips(names, max = 3) {
  if (!names.length) return h("span", { class: "tag warn" }, "None assigned");
  const shown = names.slice(0, max).map((n) => h("span", { class: "chip", title: n }, h("span", {}, n)));
  if (names.length > max) shown.push(h("span", { class: "chip more" }, `+${names.length - max} more`));
  return h("div", { class: "chips" }, shown);
}

function renderUsers() {
  const q = norm($("userSearch").value);
  const f = $("userFilter").value;
  const rows = state.users.filter((u) => {
    if (f === "active" && !u.active) return false;
    if (f === "disabled" && u.active) return false;
    if (f === "admin" && u.role !== "admin") return false;
    if (!q) return true;
    return [u.username, u.display_name, u.company, ...u.party_names].some((x) => norm(x).includes(q));
  });
  const body = $("userRows");
  body.replaceChildren();
  if (!rows.length) {
    body.append(h("tr", {}, h("td", { colspan: "5", class: "empty" }, state.users.length ? "No users match this filter." : "No users yet. Create the first party login.")));
    return;
  }
  for (const u of rows) {
    const tr = h("tr", { class: "clickable", tabindex: "0", onclick: () => openEditor(u), onkeydown: (e) => { if (e.key === "Enter") openEditor(u); } },
      h("td", {}, h("div", { class: "u-name" }, u.display_name || u.username),
        h("div", { class: "u-sub" }, [u.username, u.company].filter(Boolean).join(", "))),
      h("td", {}, u.role === "admin" ? h("span", { class: "u-sub" }, "All shipments") : chips(u.party_names)),
      h("td", {}, h("span", { class: u.role === "admin" ? "tag admin" : "tag off" }, u.role === "admin" ? "Admin" : "Party")),
      h("td", {}, h("span", { class: u.active ? "tag on" : "tag off" }, u.active ? "Active" : "Disabled")),
      h("td", { class: "u-sub" }, u.last_login_at ? ago(u.last_login_at) : "Never"));
    body.append(tr);
  }
}

// ---------------------------------------------------------------- party names table
function renderParties() {
  const q = norm($("partySearch").value);
  const only = $("onlyUnassigned").checked;
  const rows = state.parties.filter((p) => (!q || norm(p.party_name).includes(q)) && (!only || !p.users.length));
  const body = $("partyRows");
  body.replaceChildren();
  if (!rows.length) {
    body.append(h("tr", {}, h("td", { colspan: "6", class: "empty" }, "No party names match.")));
    return;
  }
  for (const p of rows) {
    body.append(h("tr", {},
      h("td", {}, h("span", { class: "u-name" }, p.party_name)),
      h("td", { class: "num" }, p.active || "–"),
      h("td", { class: "num" }, p.shipments),
      h("td", { class: "u-sub" }, p.last_shipment || ""),
      h("td", {}, p.users.length ? h("div", { class: "chips" }, p.users.map((u) => h("span", { class: "chip" }, h("span", {}, u)))) : h("span", { class: "tag warn" }, "No login")),
      h("td", { class: "num" }, h("button", { class: "btn", type: "button", onclick: () => openEditor(null, [p.party_name]) }, "Create login"))));
  }
}

// ---------------------------------------------------------------- audit
const AUDIT_LABEL = { "settings.contact": "Changed customer care contact", "user.change_password": "Changed own password", "user.create": "Created user", "user.update": "Updated user", "user.reset_password": "Reset password", "user.delete": "Deleted user" };

async function loadAudit(before = 0) {
  const d = await api(`/api/admin/audit?limit=50${before ? `&before=${before}` : ""}`);
  const body = $("auditRows");
  if (!before) body.replaceChildren();
  const old = body.querySelector(".audit-more-row");
  if (old) old.remove();
  if (!d.items.length && !before) { body.append(h("tr", {}, h("td", { colspan: "5", class: "empty" }, "No changes recorded yet."))); return; }
  for (const a of d.items) {
    body.append(h("tr", {},
      h("td", { class: "u-sub" }, when(a.at)), h("td", {}, a.actor), h("td", {}, AUDIT_LABEL[a.action] || a.action),
      h("td", { class: "u-name" }, a.target), h("td", { class: "audit-detail" }, describe(a.detail))));
  }
  if (d.has_more) {
    const last = d.items[d.items.length - 1].id;
    body.append(h("tr", { class: "audit-more-row" }, h("td", { colspan: "5", style: "text-align:center" },
      h("button", { class: "btn ghost", type: "button", onclick: () => loadAudit(last) }, "Load more"))));
  }
}
function describe(d) {
  if (!d || !Object.keys(d).length) return "";
  const parts = [];
  if (d.party_names?.added?.length) parts.push(`added ${d.party_names.added.join(", ")}`);
  if (d.party_names?.removed?.length) parts.push(`removed ${d.party_names.removed.join(", ")}`);
  if (Array.isArray(d.party_names)) parts.push(`party names: ${d.party_names.join(", ") || "none"}`);
  for (const [k, v] of Object.entries(d)) if (k !== "party_names") parts.push(`${k.replace("_", " ")}: ${v}`);
  return parts.join("; ");
}

// ---------------------------------------------------------------- editor drawer
function openEditor(user, preset = []) {
  const isNew = !user;
  const selected = new Map(); // key -> display name
  for (const n of user?.party_names || preset) selected.set(norm(n), n);
  const self = user && user.username === state.me.user.username;

  const f = {
    username: h("input", { class: "input", value: user?.username || "", readonly: !isNew, autocomplete: "off", autocapitalize: "none", spellcheck: "false", required: true }),
    display: h("input", { class: "input", value: user?.display_name || "" }),
    company: h("input", { class: "input", value: user?.company || preset[0] || "" }),
    email: h("input", { class: "input", type: "email", value: user?.email || "" }),
    phone: h("input", { class: "input", type: "tel", value: user?.phone || "" }),
    role: h("select", { class: "select", disabled: self }, h("option", { value: "party" }, "Party (sees assigned party names)"), h("option", { value: "admin" }, "Administrator (sees everything, manages users)")),
    active: h("input", { type: "checkbox", checked: user ? user.active : true, disabled: self }),
    whatsapp: h("input", { type: "checkbox", checked: user ? user.whatsapp_alerts : true }),
    pickSearch: h("input", { type: "search", placeholder: "Search party names from shipments", autocomplete: "off" }),
    custom: h("input", { class: "input", placeholder: "Or type an exact PartyName not seen yet" }),
  };
  f.role.value = user?.role || "party";
  const chipBox = h("div", { class: "chips" });
  const picker = h("div", { class: "picker", role: "group", "aria-label": "Party names" });
  const err = h("p", { class: "form-error", role: "alert", hidden: true });
  const namesBlock = h("fieldset", { class: "fieldset" },
    h("legend", {}, "Party names this login can track"),
    chipBox,
    h("label", { class: "search" }, svg(`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 16l4 4" stroke="currentColor" stroke-width="2"/></svg>`), f.pickSearch),
    picker,
    h("div", { class: "add-row" }, f.custom, h("button", { class: "btn", type: "button", onclick: addCustom }, "Add")),
    h("small", { class: "u-sub" }, "Shipments whose PartyName matches any of these appear for this user. Case and punctuation are ignored."));

  function renderChips() {
    chipBox.replaceChildren(...(selected.size ? [...selected.entries()].map(([k, n]) => h("span", { class: "chip" }, h("span", { title: n }, n),
      h("button", { type: "button", "aria-label": `Remove ${n}`, onclick: () => { selected.delete(k); renderChips(); renderPicker(); } }, "×")))
      : [h("span", { class: "tag warn" }, "No party names yet. This login will see no shipments.")]));
  }
  function renderPicker() {
    const q = norm(f.pickSearch.value);
    const rows = state.parties.filter((p) => !q || norm(p.party_name).includes(q)).slice(0, 200);
    picker.replaceChildren(...(rows.length ? rows.map((p) => {
      const key = norm(p.party_name);
      const box = h("input", { type: "checkbox", checked: selected.has(key), onchange: (e) => {
        if (e.target.checked) {
          selected.set(key, p.party_name);
          if (!f.company.value.trim()) f.company.value = p.party_name; // sensible default
        } else selected.delete(key);
        renderChips();
      } });
      const others = p.users.filter((u) => u !== user?.username);
      return h("label", { class: "pick" }, box, h("span", { class: "pick-name", title: p.party_name }, p.party_name),
        h("span", { class: "pick-meta" }, `${p.shipments} shipments${others.length ? `, ${others.length} login${others.length > 1 ? "s" : ""}` : ""}`));
    }) : [h("div", { class: "pick" }, h("span", {}), h("span", { class: "u-sub" }, "No party name matches. Add it below if it's new."), h("span", {}))]));
  }
  function addCustom() {
    const v = f.custom.value.trim();
    if (!v) return;
    selected.set(norm(v), v);
    f.custom.value = "";
    renderChips(); renderPicker();
  }
  f.custom.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addCustom(); } });
  f.pickSearch.addEventListener("input", renderPicker);
  const syncRole = () => { const isAdmin = f.role.value === "admin"; namesBlock.hidden = isAdmin; if (waBlock) waBlock.hidden = isAdmin; };
  f.role.addEventListener("change", syncRole);

  const saveBtn = h("button", { class: "btn primary", type: "submit" }, isNew ? "Create user" : "Save changes");
  const form = h("form", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": isNew ? "New user" : `Edit ${user.username}`, novalidate: true },
    h("div", { class: "drawer-head" }, h("h2", {}, isNew ? "New user" : user.display_name || user.username),
      h("button", { class: "icon-btn small", type: "button", "aria-label": "Close", onclick: close },
        svg(`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2"/></svg>`))),
    h("div", { class: "drawer-body" },
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", {}, "Username"), f.username, isNew ? h("small", {}, "Lowercase letters, digits, dot, dash. Cannot be changed later.") : null),
        h("label", { class: "field" }, h("span", {}, "Contact name"), f.display)),
      h("label", { class: "field" }, h("span", {}, "Company"), f.company),
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", {}, "Email"), f.email),
        h("label", { class: "field" }, h("span", {}, "Phone"), f.phone)),
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", {}, "Role"), f.role),
        h("div", { class: "field" }, h("span", {}, "Status"), h("label", { class: "switch" }, f.active, "Can sign in"))),
      h("div", { class: "field", id: "waBlock" }, h("span", {}, "WhatsApp alerts"), h("label", { class: "switch" }, f.whatsapp, "Send shipment updates via WhatsApp"),
        h("small", {}, "Requires a valid phone number above. Messages go to +91 followed by the number.")),
      namesBlock, err),
    h("div", { class: "drawer-foot" },
      isNew ? h("span", {}) : h("div", { class: "right" },
        h("button", { class: "btn", type: "button", onclick: resetPassword }, "Reset password"),
        self ? null : h("button", { class: "btn danger", type: "button", onclick: remove }, "Delete")),
      h("div", { class: "right" }, h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"), saveBtn)));
  const backdrop = h("div", { class: "drawer-backdrop", onclick: close });
  const waBlock = form.querySelector("#waBlock");
  syncRole();
  const onKey = (e) => { if (e.key === "Escape") close(); };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    saveBtn.disabled = true;
    const payload = {
      display_name: f.display.value.trim(), company: f.company.value.trim(), email: f.email.value.trim(),
      phone: f.phone.value.trim(), role: f.role.value, whatsapp_alerts: f.whatsapp.checked,
      party_names: f.role.value === "admin" ? [] : [...selected.values()],
    };
    try {
      if (isNew) {
        const d = await api("/api/admin/users", { method: "POST", body: JSON.stringify({ ...payload, username: f.username.value.trim() }) });
        if (!f.active.checked) await api(`/api/admin/users/${d.user.id}`, { method: "PATCH", body: JSON.stringify({ active: false }) });
        close();
        showPassword(d.user.username, d.password, "User created");
      } else {
        await api(`/api/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ ...payload, active: f.active.checked }) });
        close();
        toast("Saved", `${user.username} updated.`);
      }
      await Promise.all([loadUsers(), loadParties()]);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      saveBtn.disabled = false;
    }
  });

  async function resetPassword() {
    if (!await confirmAction(`Reset the password for ${user.username}? They will be signed out everywhere.`, { confirmLabel: "Reset password" })) return;
    try {
      const d = await api(`/api/admin/users/${user.id}/reset-password`, { method: "POST" });
      showPassword(user.username, d.password, "Password reset");
    } catch (ex) { toast("Could not reset password", ex.message, { error: true }); }
  }
  async function remove() {
    if (!await confirmAction(`Delete ${user.username}? This cannot be undone. Disabling keeps the record instead.`, { confirmLabel: "Delete", danger: true })) return;
    try {
      await api(`/api/admin/users/${user.id}`, { method: "DELETE" });
      close();
      toast("Deleted", `${user.username} removed.`);
      await Promise.all([loadUsers(), loadParties()]);
    } catch (ex) { toast("Could not delete", ex.message, { error: true }); }
  }
  function close() { form.remove(); backdrop.remove(); document.removeEventListener("keydown", onKey); }

  document.body.append(backdrop, form);
  document.addEventListener("keydown", onKey);
  renderChips(); renderPicker(); syncRole();
  (isNew ? f.username : f.display).focus();
}

function showPassword(username, password, title) {
  const code = h("code", {}, password);
  const copy = h("button", { class: "btn", type: "button", onclick: async () => {
    try { await navigator.clipboard.writeText(password); copy.textContent = "Copied"; } catch { copy.textContent = "Select and copy"; }
  } }, "Copy");
  const done = h("button", { class: "btn primary", type: "button", onclick: () => back.remove() }, "Done");
  const back = h("div", { class: "modal-backdrop" }, h("div", { class: "modal", role: "alertdialog", "aria-modal": "true", "aria-label": title },
    h("h2", {}, title),
    h("p", {}, `Temporary password for ${username}. It is shown only once; share it with the user securely.`),
    h("div", { class: "secret" }, code, copy), done));
  document.body.append(back);
  done.focus();
}

// ---------------------------------------------------------------- customer care (CRM) contacts
let crmContacts = [];

function crmMeta(d) {
  $("crmMeta").textContent = d.updated_at ? `Last changed ${ago(d.updated_at)} by ${d.updated_by}` : "";
}
function renderContacts() {
  const list = $("crmList");
  list.replaceChildren();
  $("crmEmpty").hidden = crmContacts.length > 0;
  for (const c of crmContacts) {
    const preview = contactBlock(c._preview || null, { shipmentId: 123456 });
    const card = h("div", { class: "crm-admin-card" },
      h("div", { class: "crm-admin-head" },
        h("strong", {}, c.label || "Customer care"),
        h("div", { class: "crm-admin-actions" },
          h("button", { class: "btn small", type: "button", onclick: () => openContactEditor(c) }, "Edit"),
          h("button", { class: "btn small danger", type: "button", onclick: () => deleteContact(c) }, "Remove"))),
      h("div", { class: "crm-admin-details" },
        h("span", {}, c.phone || "No phone"),
        c.alt_phone ? h("span", { class: "u-sub" }, ` / ${c.alt_phone}`) : null,
        c.email ? h("span", { class: "u-sub" }, ` · ${c.email}`) : null,
        c.hours ? h("span", { class: "u-sub" }, ` · ${c.hours}`) : null,
        c.whatsapp ? h("span", { class: "tag ok" }, "WhatsApp") : null),
      preview ? h("div", { class: "crm-admin-preview" }, h("small", { class: "u-sub" }, "User preview:"), preview) : null);
    list.append(card);
  }
}

function openContactEditor(existing) {
  const isNew = !existing;
  const c = existing || { label: "Customer care", phone: "", alt_phone: "", whatsapp: false, email: "", hours: "" };
  const f = {
    label: h("input", { class: "input", value: c.label || "", maxlength: 60, placeholder: "Customer care" }),
    phone: h("input", { class: "input", type: "tel", value: c.phone || "", maxlength: 32, placeholder: "98765 43210", required: true }),
    alt_phone: h("input", { class: "input", type: "tel", value: c.alt_phone || "", maxlength: 32 }),
    email: h("input", { class: "input", type: "email", value: c.email || "", maxlength: 120 }),
    hours: h("input", { class: "input", value: c.hours || "", maxlength: 80, placeholder: "Mon to Sat, 9 am to 7 pm" }),
    whatsapp: h("input", { type: "checkbox", checked: !!c.whatsapp }),
  };
  const err = h("p", { class: "form-error", role: "alert", hidden: true });
  const saveBtn = h("button", { class: "btn primary", type: "submit" }, isNew ? "Add contact" : "Save changes");

  function close() { form.remove(); backdrop.remove(); document.removeEventListener("keydown", onKey); }
  const form = h("form", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": isNew ? "New contact" : `Edit ${c.label}`, novalidate: true },
    h("div", { class: "drawer-head" }, h("h2", {}, isNew ? "Add support contact" : `Edit: ${c.label}`),
      h("button", { class: "icon-btn small", type: "button", "aria-label": "Close", onclick: close },
        svg(`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2"/></svg>`))),
    h("div", { class: "drawer-body" },
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", {}, "Label / Name"), f.label),
        h("label", { class: "field" }, h("span", {}, "Phone number"), f.phone)),
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", {}, "Alternate number"), f.alt_phone),
        h("label", { class: "field" }, h("span", {}, "Email"), f.email)),
      h("div", { class: "grid-2" },
        h("label", { class: "field" }, h("span", {}, "Hours"), f.hours),
        h("div", { class: "field" }, h("span", {}, "WhatsApp"), h("label", { class: "switch" }, f.whatsapp, "Main number is on WhatsApp"))),
      err),
    h("div", { class: "drawer-foot" },
      h("div", { class: "right" }, h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"), saveBtn)));
  const backdrop = h("div", { class: "drawer-backdrop", onclick: close });
  const onKey = (e) => { if (e.key === "Escape") close(); };

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    saveBtn.disabled = true;
    const body = {
      label: f.label.value.trim() || "Customer care",
      phone: f.phone.value.trim(), alt_phone: f.alt_phone.value.trim(),
      email: f.email.value.trim(), hours: f.hours.value.trim(), whatsapp: f.whatsapp.checked,
    };
    try {
      let d;
      if (isNew) {
        d = await api("/api/admin/contact", { method: "POST", body: JSON.stringify(body) });
      } else {
        d = await api(`/api/admin/contact/${c.id}`, { method: "PUT", body: JSON.stringify(body) });
      }
      applyCrmData(d);
      close();
      toast("Saved", isNew ? `${body.label} added to support contacts.` : `${body.label} updated.`);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      saveBtn.disabled = false;
    }
  });
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop, form);
  f.label.focus();
}

async function deleteContact(c) {
  if (!await confirmAction(`Remove "${c.label || "Customer care"}" from support contacts?`, { confirmLabel: "Remove", danger: true })) return;
  try {
    const d = await api(`/api/admin/contact/${c.id}`, { method: "DELETE" });
    applyCrmData(d);
    toast("Removed", `${c.label || "Contact"} removed from support team.`);
  } catch (ex) {
    toast("Error", ex.message, { error: true });
  }
}

function applyCrmData(d) {
  crmContacts = (d.contacts || []).map((c, i) => ({ ...c, _preview: d.previews?.[i] || null }));
  renderContacts();
  crmMeta({ updated_at: new Date().toISOString(), updated_by: state.me.user.username });
}

async function loadContact() {
  const d = await api("/api/admin/contact");
  crmContacts = (d.contacts || []).map((c, i) => ({ ...c, _preview: d.previews?.[i] || null }));
  renderContacts();
  crmMeta(d);
}

// ---------------------------------------------------------------- wiring
function setView(v) {
  state.view = v;
  for (const b of document.querySelectorAll(".subnav button")) b.setAttribute("aria-selected", String(b.dataset.view === v));
  for (const id of ["users", "parties", "audit", "settings"]) $(`view-${id}`).hidden = id !== v;
  if (v === "audit") loadAudit().catch((e) => toast("Could not load activity", e.message, { error: true }));
  if (v === "settings") loadContact().catch((e) => toast("Could not load customer care settings", e.message, { error: true }));
}

(async function boot(attempt = 0) {
  try {
    state.me = await initHeader("admin");
  } catch (e) {
    if (e.message === "signed out") return;
    if (attempt < 2) { setTimeout(() => boot(attempt + 1), 1500); return; }
    toast("Connection problem", "Couldn't load the page. Retrying…", { error: true });
    setTimeout(() => boot(0), 4000);
    return;
  }
  if (state.me.user.role !== "admin") { location.replace("/"); return; }
  for (const b of document.querySelectorAll(".subnav button")) b.addEventListener("click", () => setView(b.dataset.view));
  $("newUserBtn").addEventListener("click", () => openEditor(null));
  $("crmAddBtn")?.addEventListener("click", () => openContactEditor(null));
  $("userSearch").addEventListener("input", renderUsers);
  $("userFilter").addEventListener("change", renderUsers);
  $("partySearch").addEventListener("input", renderParties);
  $("onlyUnassigned").addEventListener("change", renderParties);
  try {
    await Promise.all([loadUsers(), loadParties()]);
  } catch (e) {
    toast("Could not load the user master", e.message, { error: true });
  }
})();
