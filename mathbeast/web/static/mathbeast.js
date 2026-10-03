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

  document.addEventListener("DOMContentLoaded", markPlanned);
})();