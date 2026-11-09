// Runs before first paint (external file: the CSP forbids inline scripts). Dark is the default.
(function () {
  var t = "dark";
  try { t = localStorage.getItem("bt-theme") || "dark"; } catch (e) { /* storage blocked */ }
  document.documentElement.setAttribute("data-theme", t === "light" ? "light" : "dark");
})();
