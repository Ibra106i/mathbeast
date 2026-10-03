// MathBeast front end.
//
// Deliberately almost empty. The server renders every fragment, HTMX swaps them,
// and the status bar polls itself. The only thing this file owns is behaviour
// that has no server-side equivalent yet.

(function () {
  "use strict";

  // Highlight the nav item for views not yet built, which the server marks with
  // a "soon" badge. Without this the shell looks like a normal working app.
  function markPlanned() {
    document.querySelectorAll(".navitem.is-planned").forEach(function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        var url = link.getAttribute("href");
        fetch(url)
          .then(function (r) { return r.text(); })
          .then(function (html) {
            var main = document.querySelector(".content");
            if (main) {
              main.innerHTML = html;
              document.title = "MathBeast · " + url.split("/").pop();
              markPlanned();
            }
          })
          .catch(function () { window.location.href = url; });
      });
    });
  }

  // The off-canvas menu on the home surface.
  //
  // No animation yet: `hidden` is what makes the panel correct when the script
  // fails to load or JS is off, and trading that for a transition would need a
  // frame-delay hack. Motion belongs in the states pass, not here.
  function initDrawer() {
    var drawer = document.getElementById("drawer");
    if (!drawer) return;

    var toggles = Array.prototype.slice.call(document.querySelectorAll("[data-drawer-toggle]"));
    var closers = Array.prototype.slice.call(document.querySelectorAll("[data-drawer-close]"));
    var scrim = document.querySelector(".scrim");
    var lastFocus = null;

    function setOpen(open) {
      if (open === !drawer.hidden) return;
      if (open) lastFocus = document.activeElement;

      drawer.hidden = !open;
      if (scrim) scrim.hidden = !open;
      toggles.forEach(function (button) {
        button.setAttribute("aria-expanded", String(open));
      });

      // Without this the tab order carries on from the button that opened the
      // panel, one row behind the pointer, and Escape is the only way back.
      if (open) {
        var first = drawer.querySelector("button, a, input, select");
        if (first) first.focus();
      } else if (lastFocus) {
        lastFocus.focus();
        lastFocus = null;
      }
    }

    toggles.forEach(function (button) {
      button.addEventListener("click", function () {
        setOpen(drawer.hidden);
      });
    });
    closers.forEach(function (button) {
      button.addEventListener("click", function () { setOpen(false); });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !drawer.hidden) setOpen(false);
    });
  }

  // While a measurement is running, say so. A silent button that takes eight
  // seconds on a CPU model reads as a broken page.
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var elt = event.detail.elt;
    if (elt && elt.tagName === "BUTTON") {
      elt.dataset.label = elt.textContent;
      elt.textContent = "measuring…";
      elt.disabled = true;
    }
  });

  document.body.addEventListener("htmx:afterSwap", function () {
    markPlanned();
  });

  var drawerReady = false;

  document.addEventListener("DOMContentLoaded", function () {
    markPlanned();
    if (!drawerReady) {
      initDrawer();
      drawerReady = true;
    }
  });
})();