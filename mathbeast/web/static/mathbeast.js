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

  // The top bar's height stops being a constant the moment the status row
  // wraps -- it becomes however tall that row's text makes it, which depends on
  // what the backend is reporting and no stylesheet can compute. The sidenav
  // sticks under it and takes its own height from it, so the one script that
  // exists measures it and hands it over. Until then the CSS falls back to 54,
  // the unwrapped height, which is the desktop number from the capture.
  function syncTopbarHeight() {
    var bar = document.querySelector(".topbar");
    if (!bar) return;
    document.documentElement.style.setProperty("--topbar-h", bar.offsetHeight + "px");
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
    // What the panel can hold. Disabled controls are left out so the tab order
    // never lands on something that would swallow the key press and do nothing.
    var FOCUSABLE = "a[href], button:not([disabled]), input, select, textarea";

    function setOpen(open) {
      if (open === !drawer.hidden) return;
      if (open) {
        // Where Tab was before the panel opened. A click does not move focus
        // in every browser, so falling back to the toggle itself beats handing
        // close back to a document with nothing to give it to.
        var from = document.activeElement;
        lastFocus = from && from !== document.body ? from : (toggles[0] || null);
      }

      drawer.hidden = !open;
      if (scrim) scrim.hidden = !open;
      toggles.forEach(function (button) {
        button.setAttribute("aria-expanded", String(open));
      });

      // Without this the tab order carries on from the button that opened the
      // panel, one row behind the pointer, and Escape is the only way back.
      if (open) {
        var first = drawer.querySelector(FOCUSABLE);
        if (first) first.focus();
      } else if (lastFocus) {
        // The node can be gone by the time it is needed -- a swap, a
        // re-render -- and focusing a detached element silently does nothing,
        // which reads as focus falling off the page entirely.
        if (document.contains(lastFocus)) lastFocus.focus();
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
      if (drawer.hidden) return;
      if (event.key === "Escape") {
        setOpen(false);
        return;
      }
      if (event.key !== "Tab") return;

      // The scrim already makes the page behind unreachable to the pointer;
      // this is the keyboard agreeing with it. Tab past the last control wraps
      // to the first, so focus walks the panel and never walks out of it.
      var items = drawer.querySelectorAll(FOCUSABLE);
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      var active = document.activeElement;

      if (!drawer.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
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

  // The status bar polls itself every four seconds and is swapped as one
  // fragment, so most polls bring back markup that matches what is already on
  // the page. Rewriting it anyway moves nothing the eye can see, clears the
  // live region for no announcement, and drops focus out of any control
  // inside. The guard reads the incoming markup and stops the swap when it is
  // identical.
  //
  // innerHTML rather than outerHTML or textContent, and deliberately: the
  // element carries htmx-request for the length of this request, so outerHTML
  // would differ on every poll including the no-op ones; and the model picker
  // reports its choice as a `selected` attribute on an option, which changes
  // the markup without changing a single character of text, so textContent
  // would miss the one change worth announcing.
  document.body.addEventListener("htmx:beforeSwap", function (event) {
    var target = event.target;
    var incoming = event.detail && event.detail.serverResponse;
    if (!target || !target.classList || !target.classList.contains("statusbar")) return;
    if (typeof incoming !== "string") return;

    var probe = document.createElement("div");
    probe.innerHTML = incoming;
    var next = probe.firstElementChild;
    if (next && next.innerHTML === target.innerHTML) {
      event.detail.shouldSwap = false;
    }
  });

  document.body.addEventListener("htmx:afterSwap", function () {
    markPlanned();
    // A poll that brings longer status text rewraps the row, so the bar
    // underneath it is no longer the height that was published last time.
    syncTopbarHeight();
  });

  var drawerReady = false;

  document.addEventListener("DOMContentLoaded", function () {
    markPlanned();
    initTitleEditor();
    syncTopbarHeight();
    window.addEventListener("resize", syncTopbarHeight);
    if (!drawerReady) {
      initDrawer();
      drawerReady = true;
    }
  });
})();