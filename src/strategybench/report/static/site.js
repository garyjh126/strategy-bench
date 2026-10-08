// Tooltips for chart marks (hover and keyboard focus) and the colour-theme toggle.
(function () {
  "use strict";
  var tip = document.querySelector(".tooltip");

  function place(x, y) {
    var pad = 12;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(pad, x + 14), window.innerWidth - w - pad);
    var top = y - h - 12;
    if (top < pad) top = y + 18;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function show(el, x, y) {
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
    place(x, y);
  }

  function hide() {
    tip.hidden = true;
  }

  if (tip) {
    document.addEventListener("pointermove", function (e) {
      var el = e.target.closest && e.target.closest("[data-tip]");
      if (el) show(el, e.clientX, e.clientY);
      else if (!tip.hidden && document.activeElement && !document.activeElement.hasAttribute("data-tip")) hide();
    });
    document.addEventListener("pointerleave", hide);
    document.addEventListener("focusin", function (e) {
      var el = e.target.closest && e.target.closest("[data-tip]");
      if (!el) return hide();
      var r = el.getBoundingClientRect();
      show(el, r.left + Math.min(r.width / 2, 160), r.top);
    });
    document.addEventListener("focusout", hide);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") hide();
    });
    window.addEventListener("scroll", hide, { passive: true });
  }

  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var root = document.documentElement;
      var current = root.dataset.theme ||
        (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      var next = current === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try {
        localStorage.setItem("sb-theme", next);
      } catch (err) {
        /* storage unavailable: the choice lasts for this page only */
      }
    });
  }
})();
