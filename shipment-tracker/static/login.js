const form = document.getElementById("loginForm");
const err = document.getElementById("formError");
const btn = document.getElementById("submitBtn");
let redirecting = false;

fetch("/api/auth/me", { credentials: "same-origin" })
  .then((r) => { if (r.ok) { redirecting = true; location.replace("/"); } })
  .catch(() => {});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (redirecting) return;
  err.hidden = true;
  const username = form.username.value.trim();
  const password = form.password.value;
  if (!username || !password) {
    err.textContent = "Enter your username and password.";
    err.hidden = false;
    return;
  }
  btn.disabled = true;
  btn.textContent = "Signing in…";
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
      body: JSON.stringify({ username, password }),
    });
    if (res.ok) { redirecting = true; location.replace("/" + location.hash); return; }
    let msg = "Sign-in failed. Try again.";
    try { msg = (await res.json()).detail || msg; } catch { /* default */ }
    err.textContent = typeof msg === "string" ? msg : "Check your username and password.";
    err.hidden = false;
    form.password.select();
  } catch {
    err.textContent = "Cannot reach the server. Check your internet connection.";
    err.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
});

fetch("/api/public/contact").then((r) => (r.ok ? r.json() : null)).then((d) => {
  const contacts = d?.contacts || (d?.contact ? [d.contact] : []);
  if (!contacts.length) return;
  const help = document.getElementById("loginHelp");
  help.textContent = "";
  if (contacts.length === 1) {
    const c = contacts[0];
    help.textContent = `Forgot your password or need a login? Call ${c.label} on `;
    const a = document.createElement("a");
    a.href = `tel:${c.tel}`;
    a.textContent = c.phone;
    help.append(a, c.hours ? ` (${c.hours})` : ".");
    if (c.email) {
      const em = document.createElement("a");
      em.href = `mailto:${c.email}`;
      em.textContent = c.email;
      help.append(" Or email ", em, ".");
    }
    return;
  }
  help.append("Forgot your password or need a login? Contact our support team:");
  for (const c of contacts) {
    const row = document.createElement("span");
    row.className = "login-contact";
    const label = document.createElement("strong");
    label.textContent = c.label;
    const a = document.createElement("a");
    a.href = `tel:${c.tel}`;
    a.textContent = c.phone;
    row.append(label, " — ", a);
    if (c.email) {
      const em = document.createElement("a");
      em.href = `mailto:${c.email}`;
      em.textContent = c.email;
      row.append(" · ", em);
    }
    if (c.hours) row.append(` (${c.hours})`);
    help.append(row);
  }
}).catch(() => {});
