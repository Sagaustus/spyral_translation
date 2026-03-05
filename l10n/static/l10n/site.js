(function () {
  "use strict";

  function setActiveNavLink() {
    var nav = document.querySelector(".site-nav");
    if (!nav) return;

    var currentPath = window.location.pathname;
    var links = nav.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      try {
        var url = new URL(link.getAttribute("href"), window.location.origin);
        if (url.pathname === currentPath) {
          link.classList.add("is-active");
          link.setAttribute("aria-current", "page");
        }
      } catch (_e) {
        // Ignore malformed URLs.
      }
    }
  }

  function copyTextToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }

    // Fallback for older browsers.
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error("copy failed"));
      } catch (e) {
        reject(e);
      }
    });
  }

  function getTextFromTarget(selector) {
    if (!selector) return "";
    var el = document.querySelector(selector);
    if (!el) return "";
    return (el.textContent || "").trim();
  }

  function getValueFromTarget(selector) {
    if (!selector) return "";
    var el = document.querySelector(selector);
    if (!el) return "";
    if (typeof el.value === "string") return el.value;
    return "";
  }

  function setupCopyButtons() {
    var buttons = document.querySelectorAll("[data-copy][data-copy-text]");
    var selectorButtons = document.querySelectorAll("[data-copy][data-copy-target]");
    var valueButtons = document.querySelectorAll("[data-copy][data-copy-from]");

    function wire(btn, getTextFn) {
      var original = btn.textContent;
      btn.addEventListener("click", function () {
        var text = getTextFn(btn);
        if (!text) return;

        copyTextToClipboard(text)
          .then(function () {
            btn.textContent = "Copied";
            window.setTimeout(function () {
              btn.textContent = original;
            }, 1200);
          })
          .catch(function () {
            btn.textContent = "Copy failed";
            window.setTimeout(function () {
              btn.textContent = original;
            }, 1200);
          });
      });
    }

    for (var i = 0; i < buttons.length; i++) {
      (function () {
        var btn = buttons[i];
        wire(btn, function (b) {
          return b.getAttribute("data-copy-text") || "";
        });
      })();
    }

    for (var j = 0; j < selectorButtons.length; j++) {
      (function () {
        var btn2 = selectorButtons[j];
        wire(btn2, function (b) {
          return getTextFromTarget(b.getAttribute("data-copy-target") || "");
        });
      })();
    }

    for (var k = 0; k < valueButtons.length; k++) {
      (function () {
        var btn3 = valueButtons[k];
        wire(btn3, function (b) {
          return getValueFromTarget(b.getAttribute("data-copy-from") || "");
        });
      })();
    }
  }

  function setupTextareaCounters() {
    var textareas = document.querySelectorAll("textarea");
    for (var i = 0; i < textareas.length; i++) {
      (function () {
        var ta = textareas[i];
        if (ta.hasAttribute("data-no-counter")) return;

        var counter = document.createElement("div");
        counter.className = "muted js-char-count";
        counter.setAttribute("aria-live", "polite");

        function update() {
          var val = ta.value || "";
          counter.textContent = val.length + " characters";
        }

        update();
        ta.addEventListener("input", update);

        // Insert after textarea.
        if (ta.parentNode) {
          if (ta.nextSibling) {
            ta.parentNode.insertBefore(counter, ta.nextSibling);
          } else {
            ta.parentNode.appendChild(counter);
          }
        }
      })();
    }
  }

  function setupDirtyFormWarning() {
    var forms = document.querySelectorAll("form.js-dirty-check");
    if (!forms.length) return;

    var dirty = false;

    function markDirty() {
      dirty = true;
    }

    function clearDirty() {
      dirty = false;
    }

    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      form.addEventListener("input", markDirty);
      form.addEventListener("change", markDirty);
      form.addEventListener("submit", clearDirty);
    }

    window.addEventListener("beforeunload", function (e) {
      if (!dirty) return;
      e.preventDefault();
      // Most browsers show a generic message; setting returnValue is still required.
      e.returnValue = "";
    });
  }

  function setupErrorFocus() {
    var lists = document.querySelectorAll(".errorlist");
    if (!lists.length) return;

    // Focus the first field that has a visible error list near it.
    for (var i = 0; i < lists.length; i++) {
      var list = lists[i];
      var container = list.closest("p") || list.parentElement;
      if (!container) continue;

      var field = container.querySelector("input, select, textarea");
      if (!field) continue;
      try {
        field.focus();
        field.scrollIntoView({ block: "center" });
      } catch (_e) {
        // ignore
      }
      break;
    }
  }

  function setupPasswordToggles() {
    var fields = document.querySelectorAll('input[type="password"]');
    for (var i = 0; i < fields.length; i++) {
      (function () {
        var input = fields[i];
        if (input.hasAttribute("data-no-toggle")) return;

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn btn-small js-inline-control";
        btn.textContent = "Show password";

        btn.addEventListener("click", function () {
          var isPassword = input.getAttribute("type") === "password";
          input.setAttribute("type", isPassword ? "text" : "password");
          btn.textContent = isPassword ? "Hide password" : "Show password";
          input.focus();
        });

        // Insert immediately after the input.
        var parent = input.parentNode;
        if (!parent) return;
        if (input.nextSibling) {
          parent.insertBefore(btn, input.nextSibling);
        } else {
          parent.appendChild(btn);
        }
      })();
    }
  }

  function setupFileInputLabels() {
    var fields = document.querySelectorAll('input[type="file"]');
    for (var i = 0; i < fields.length; i++) {
      (function () {
        var input = fields[i];
        var meta = document.createElement("div");
        meta.className = "muted file-meta";
        meta.setAttribute("aria-live", "polite");

        function update() {
          var files = input.files;
          if (!files || !files.length) {
            meta.textContent = "No file selected";
            return;
          }
          meta.textContent = "Selected: " + files[0].name;
        }

        update();
        input.addEventListener("change", update);

        var parent = input.parentNode;
        if (!parent) return;
        if (input.nextSibling) {
          parent.insertBefore(meta, input.nextSibling);
        } else {
          parent.appendChild(meta);
        }
      })();
    }
  }

  function setupReviewShortcuts() {
    var form = document.querySelector("form.js-dirty-check");
    if (!form) return;

    document.addEventListener("keydown", function (e) {
      // Ctrl+Enter: submit
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        var submit = form.querySelector('button[type="submit"], input[type="submit"]');
        if (submit) submit.click();
      }

      // Esc: go back
      if (e.key === "Escape") {
        var back = document.querySelector("[data-shortcut-back]");
        if (back && back.getAttribute("href")) {
          window.location.href = back.getAttribute("href");
        }
      }
    });
  }

  setActiveNavLink();
  setupCopyButtons();
  setupTextareaCounters();
  setupDirtyFormWarning();
  setupErrorFocus();
  setupPasswordToggles();
  setupFileInputLabels();
  setupReviewShortcuts();
})();
