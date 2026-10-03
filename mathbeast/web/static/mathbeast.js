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
  // It does not slide, and that is settled rather than forgotten. `hidden` is
  // what keeps the panel correct when this file fails to load or JS is off;
  // dropping it means a reflow hack to start a transition, or @starting-style,
  // which is newer than the browsers this app otherwise asks for. The states
  // that do exist move in the stylesheets instead -- see the motion tokens.
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

  // Click the greeting, type, Enter to keep it and Escape to change your mind.
  //
  // This is the one place on the surface that does not swap server markup, and
  // deliberately: the edit is a focus-management problem. The input has to
  // inherit the heading's exact width or the centred row reflows under the
  // cursor, and a pending request has to leave a sensible heading behind if it
  // never comes back. Splitting that between a template and a script would be
  // worse than either on its own. Everything the server decides -- stripping,
  // the length ceiling, what shows when the text ends up empty -- comes back
  // in the response and is written here, so the page never shows a heading the
  // file does not hold.
  function initTitleEditor() {
    var button = document.getElementById("stage-title-text");
    if (!button || button.dataset.ready) return;
    button.dataset.ready = "1";

    var errorEl = document.getElementById("stage-title-error");

    function showError(message) {
      if (!errorEl) return;
      errorEl.textContent = message;
      errorEl.hidden = false;
    }

    function clearError() {
      if (!errorEl) return;
      errorEl.textContent = "";
      errorEl.hidden = true;
    }

    function startEdit() {
      var original = button.textContent;
      var typed = original;

      clearError();

      var input = document.createElement("input");
      input.type = "text";
      input.className = "stage-title__input";
      input.value = original;
      input.setAttribute("aria-label", "Greeting");
      // Read from the server-rendered attribute rather than a constant here,
      // so the field cannot reject something the file would have accepted.
      input.maxLength = parseInt(button.dataset.maxTitle, 10) || 80;
      // The single line that keeps the swap invisible: without it the row is
      // as wide as the placeholder, the flex centres again, and the asterisk
      // slides sideways the moment you click.
      input.style.width = Math.max(button.offsetWidth, 1) + "px";

      button.replaceWith(input);
      input.focus();
      // Caret at the end, not select-all. A field that highlights everything
      // turns one stray keystroke into the loss of the sentence.
      input.setSelectionRange(input.value.length, input.value.length);

      var settled = false;

      function restore(text) {
        if (settled) return;
        settled = true;
        button.textContent = text;
        input.replaceWith(button);
        button.focus();
      }

      function save() {
        if (settled) return;
        typed = input.value;

        // Opening and closing the editor without touching it must not write.
        if (typed === original) {
          restore(original);
          return;
        }

        // Heading comes back first. If the request stalls or the backend is
        // unreachable, the page still shows a greeting rather than a field
        // the user cannot get out of.
        settled = true;
        button.textContent = typed;
        input.replaceWith(button);
        button.focus();

        fetch("/api/title", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: "title=" + encodeURIComponent(typed),
        })
          .then(function (response) {
            return response.json().then(function (data) {
              return { ok: response.ok, data: data };
            });
          })
          .then(function (result) {
            if (result.ok && result.data && result.data.ok) {
              // Not `typed`: the server strips, clamps, and falls back to the
              // placeholder when the result is empty. Showing the file's
              // contents is the only way the two cannot drift.
              button.textContent = result.data.title;
              clearError();
            } else {
              throw new Error(
                (result.data && result.data.error) || "the server refused it"
              );
            }
          })
          .catch(function (error) {
            button.textContent = original;
            showError("That greeting was not saved: " + error.message + ".");
          });
      }

      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          save();
        } else if (event.key === "Escape") {
          event.preventDefault();
          restore(original);
        }
      });
      // Clicking away commits. Reverting on blur would throw away a sentence
      // the moment somebody reaches for another window.
      input.addEventListener("blur", save);
    }

    button.addEventListener("click", startEdit);
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
    initTitleEditor();
    if (!drawerReady) {
      initDrawer();
      drawerReady = true;
    }
  });
})();