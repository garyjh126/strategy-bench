// Apply a saved colour theme before first paint (a separate file so the page can forbid inline scripts).
try {
  var t = localStorage.getItem("sb-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) {
  /* storage unavailable: follow the system theme */
}
