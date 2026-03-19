(function () {
  "use strict";

  /* ── Accessibility ──────────────────────────────────────────
     Respect prefers-reduced-motion for all animation-heavy code.
  ──────────────────────────────────────────────────────────── */
  var reducedMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── Toast notification ─────────────────────────────────────
     Slide-up toast from bottom-right for non-blocking feedback.
  ──────────────────────────────────────────────────────────── */
  function showToast(message, durationMs) {
    durationMs = durationMs || 2200;

    var existing = document.querySelector(".toast");
    if (existing) existing.remove();

    var toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    document.body.appendChild(toast);

    // Double rAF so the browser paints the initial hidden state first.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        toast.classList.add("is-visible");
      });
    });

    setTimeout(function () {
      toast.classList.remove("is-visible");
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 380);
    }, durationMs);
  }

  /* ── Active nav link ────────────────────────────────────────
     Marks the current page's nav anchor with .is-active.
  ──────────────────────────────────────────────────────────── */
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

  /* ── Clipboard ──────────────────────────────────────────────
     Copy to clipboard with async API + execCommand fallback.
  ──────────────────────────────────────────────────────────── */
  function copyTextToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }

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
      btn.addEventListener("click", function () {
        var text = getTextFn(btn);
        if (!text) return;

        copyTextToClipboard(text)
          .then(function () { showToast("Copied to clipboard"); })
          .catch(function () { showToast("Copy failed \u2014 please try again"); });
      });
    }

    for (var i = 0; i < buttons.length; i++) {
      (function () {
        var btn = buttons[i];
        wire(btn, function (b) { return b.getAttribute("data-copy-text") || ""; });
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

  /* ── Textarea char counters ──────────────────────────────── */
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

        if (ta.parentNode) {
          ta.nextSibling
            ? ta.parentNode.insertBefore(counter, ta.nextSibling)
            : ta.parentNode.appendChild(counter);
        }
      })();
    }
  }

  /* ── Dirty form warning ──────────────────────────────────── */
  function setupDirtyFormWarning() {
    var forms = document.querySelectorAll("form.js-dirty-check");
    if (!forms.length) return;

    var dirty = false;
    function markDirty()  { dirty = true;  }
    function clearDirty() { dirty = false; }

    for (var i = 0; i < forms.length; i++) {
      forms[i].addEventListener("input",  markDirty);
      forms[i].addEventListener("change", markDirty);
      forms[i].addEventListener("submit", clearDirty);
    }

    window.addEventListener("beforeunload", function (e) {
      if (!dirty) return;
      e.preventDefault();
      e.returnValue = "";
    });
  }

  /* ── Error focus ─────────────────────────────────────────── */
  function setupErrorFocus() {
    var lists = document.querySelectorAll(".errorlist");
    if (!lists.length) return;

    for (var i = 0; i < lists.length; i++) {
      var list = lists[i];
      var container = list.closest("p") || list.parentElement;
      if (!container) continue;

      var field = container.querySelector("input, select, textarea");
      if (!field) continue;
      try {
        field.focus();
        field.scrollIntoView({ block: "center" });
      } catch (_e) {}
      break;
    }
  }

  /* ── Password toggles ────────────────────────────────────── */
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

        var parent = input.parentNode;
        if (!parent) return;
        input.nextSibling
          ? parent.insertBefore(btn, input.nextSibling)
          : parent.appendChild(btn);
      })();
    }
  }

  /* ── File input labels ───────────────────────────────────── */
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
        input.nextSibling
          ? parent.insertBefore(meta, input.nextSibling)
          : parent.appendChild(meta);
      })();
    }
  }

  /* ── Review keyboard shortcuts ───────────────────────────── */
  function setupReviewShortcuts() {
    var form = document.querySelector("form.js-dirty-check");
    if (!form) return;

    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        var submit = form.querySelector('button[type="submit"], input[type="submit"]');
        if (submit) submit.click();
      }

      if (e.key === "Escape") {
        var back = document.querySelector("[data-shortcut-back]");
        if (back && back.getAttribute("href")) {
          window.location.href = back.getAttribute("href");
        }
      }
    });
  }

  /* ── Scroll reveal ───────────────────────────────────────── *
   *  IntersectionObserver fades + slides elements into view.   *
   *  Grid children get staggered transition-delay via          *
   *  data-reveal-delay="1..5".                                 *
   * ─────────────────────────────────────────────────────────── */
  function setupScrollReveal() {
    if (!window.IntersectionObserver || reducedMotion) return;

    // Tag everything that should animate in
    document.querySelectorAll(".card, .section-label, .page-heading").forEach(function (el) {
      el.setAttribute("data-reveal", "");
    });

    // Stagger children inside grid wrappers
    document.querySelectorAll(".grid").forEach(function (grid) {
      grid.querySelectorAll(".card").forEach(function (card, i) {
        if (i < 5) card.setAttribute("data-reveal-delay", String(i + 1));
      });
    });

    // Stagger stat cards
    var statRow = document.querySelector(".stat-row");
    if (statRow) {
      statRow.querySelectorAll(".stat-card").forEach(function (card, i) {
        card.setAttribute("data-reveal", "");
        if (i < 5) card.setAttribute("data-reveal-delay", String(i + 1));
      });
    }

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0, rootMargin: "0px 0px -28px 0px" }
    );

    document.querySelectorAll("[data-reveal]").forEach(function (el) {
      observer.observe(el);
    });
  }

  /* ── Stat counter animation ──────────────────────────────── *
   *  When a .stat-card__number scrolls into view it counts up  *
   *  from 0 to its value using an ease-out cubic easing.       *
   * ─────────────────────────────────────────────────────────── */
  function setupStatCounters() {
    if (!window.IntersectionObserver || reducedMotion) return;

    var numbers = document.querySelectorAll(".stat-card__number");
    if (!numbers.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;

          var el = entry.target;
          var target = parseInt(el.textContent.replace(/[^0-9]/g, ""), 10);
          if (isNaN(target) || target === 0) return;

          el.classList.add("is-animating");

          // Scale duration to magnitude (50ms base + 8ms per unit, cap at 1800ms)
          var duration = Math.min(500 + target * 8, 1800);
          var startTime = null;

          function step(ts) {
            if (!startTime) startTime = ts;
            var progress = Math.min((ts - startTime) / duration, 1);
            // Ease-out cubic
            var eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.round(eased * target);
            if (progress < 1) requestAnimationFrame(step);
          }

          requestAnimationFrame(step);
          observer.unobserve(el);
        });
      },
      { threshold: 0.6 }
    );

    numbers.forEach(function (n) { observer.observe(n); });
  }

  /* ── Button ripple ───────────────────────────────────────── *
   *  On click, a .btn-ripple span expands from the click point *
   *  and fades out, creating a tactile wave effect.            *
   * ─────────────────────────────────────────────────────────── */
  function setupRipple() {
    if (reducedMotion) return;

    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".btn, button, input[type='submit']");
      if (!btn) return;
      // Skip if button is disabled
      if (btn.disabled || btn.getAttribute("aria-disabled") === "true") return;

      var rect = btn.getBoundingClientRect();
      var size = Math.max(rect.width, rect.height) * 1.3;
      var x = e.clientX - rect.left  - size / 2;
      var y = e.clientY - rect.top   - size / 2;

      var ripple = document.createElement("span");
      ripple.className = "btn-ripple";
      ripple.style.cssText =
        "width:"  + size + "px;" +
        "height:" + size + "px;" +
        "left:"   + x    + "px;" +
        "top:"    + y    + "px;";
      btn.appendChild(ripple);

      ripple.addEventListener("animationend", function () {
        if (ripple.parentNode) ripple.parentNode.removeChild(ripple);
      });
    });
  }

  /* ── Card 3D tilt ────────────────────────────────────────── *
   *  Mouse-move on feature + stat cards warps them in 3D.     *
   *  Max ±5deg rotation. Smooth spring-back on mouse-leave.   *
   * ─────────────────────────────────────────────────────────── */
  function setupCardTilt() {
    if (reducedMotion) return;

    var cards = document.querySelectorAll(".card.feature-card, .stat-card");

    cards.forEach(function (card) {
      card.addEventListener("mousemove", function (e) {
        var rect = card.getBoundingClientRect();
        var x  = e.clientX - rect.left;
        var y  = e.clientY - rect.top;
        var cx = rect.width  / 2;
        var cy = rect.height / 2;

        var rotX = ((y - cy) / cy) * -5;
        var rotY = ((x - cx) / cx) *  5;

        card.style.transition = "transform 0.06s ease, box-shadow 0.06s ease";
        card.style.transform  =
          "perspective(700px) rotateX(" + rotX + "deg) rotateY(" + rotY + "deg) translateZ(6px)";
        card.style.boxShadow  = "0 18px 40px rgba(0,0,0,0.15)";
      });

      card.addEventListener("mouseleave", function () {
        card.style.transition = "transform 0.5s ease, box-shadow 0.5s ease";
        card.style.transform  = "";
        card.style.boxShadow  = "";
      });
    });
  }

  /* ── Sticky header compact ───────────────────────────────── *
   *  Adds .is-scrolled after 50px, triggering padding shrink  *
   *  and backdrop-filter blur via CSS.                         *
   * ─────────────────────────────────────────────────────────── */
  function setupHeaderScroll() {
    var header = document.querySelector(".site-header");
    if (!header) return;

    var ticking = false;

    window.addEventListener(
      "scroll",
      function () {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(function () {
          header.classList.toggle("is-scrolled", window.scrollY > 50);
          ticking = false;
        });
      },
      { passive: true }
    );
  }

  /* ── Hero floating orbs ──────────────────────────────────── *
   *  Injects three amber glow blobs that drift on independent  *
   *  orbFloat keyframe cycles, creating depth behind hero text.*
   * ─────────────────────────────────────────────────────────── */
  function setupHeroOrbs() {
    if (reducedMotion) return;

    var hero = document.querySelector(".hero-banner");
    if (!hero) return;

    var orbData = [
      { size: 240, x: 4,  y: 5,  delay: 0, dur: 10, clr: "rgba(245,158,11,0.20)" },
      { size: 170, x: 60, y: 50, delay: 3, dur:  8, clr: "rgba(232,99,10,0.16)"  },
      { size: 130, x: 42, y: 72, delay: 5, dur: 13, clr: "rgba(245,158,11,0.13)" },
    ];

    orbData.forEach(function (o) {
      var orb = document.createElement("div");
      orb.className = "hero-orb";
      orb.style.cssText = [
        "width:"       + o.size  + "px",
        "height:"      + o.size  + "px",
        "left:"        + o.x     + "%",
        "top:"         + o.y     + "%",
        "--orb-dur:"   + o.dur   + "s",
        "--orb-delay:" + o.delay + "s",
        "background:radial-gradient(circle," + o.clr + " 0%,transparent 70%)",
      ].join(";");
      hero.insertBefore(orb, hero.firstChild);
    });
  }

  /* ── Hero rotating word ──────────────────────────────────── *
   *  #js-hero-word cycles through African language names with  *
   *  a slide-fade effect: old word exits up, new word enters   *
   *  from below — no layout shift (inline-block, min-width).   *
   * ─────────────────────────────────────────────────────────── */
  function setupHeroWordRotation() {
    if (reducedMotion) return;

    var el = document.getElementById("js-hero-word");
    if (!el) return;

    var words = [
      "African languages",
      "Yoruba",
      "Hausa",
      "Swahili",
      "Igbo",
      "Zulu",
      "Amharic",
      "Somali",
      "Wolof",
      "Twi",
    ];
    var index = 0;

    setInterval(function () {
      index = (index + 1) % words.length;

      // Phase 1: slide the current word out (upward, fade out)
      el.classList.add("is-leaving");

      setTimeout(function () {
        // Phase 2: snap new word to below with no transition
        el.textContent = words[index];
        el.classList.remove("is-leaving");
        el.classList.add("is-entering"); // translateY(14px), opacity 0, no transition

        // Phase 3: double rAF forces a paint, then removing .is-entering
        //          triggers the CSS transition to slide it to final position
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            el.classList.remove("is-entering");
          });
        });
      }, 295);
    }, 2800);
  }

  /* ── Progress bar animation ──────────────────────────────── *
   *  When a .progress-bar-fill[data-width] enters the viewport, *
   *  its width animates from 0 to the data-width percentage.    *
   * ─────────────────────────────────────────────────────────── */
  function setupProgressBars() {
    var bars = document.querySelectorAll(".progress-bar-fill[data-width]");
    if (!bars.length) return;

    if (reducedMotion) {
      bars.forEach(function (bar) {
        bar.style.width = bar.getAttribute("data-width") + "%";
      });
      return;
    }

    if (!window.IntersectionObserver) {
      bars.forEach(function (bar) {
        bar.style.width = bar.getAttribute("data-width") + "%";
      });
      return;
    }

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var bar = entry.target;
          var target = parseFloat(bar.getAttribute("data-width")) || 0;
          // CSS transition handles the animation (width 1.1s ease); just set the value.
          bar.style.width = Math.min(target, 100) + "%";
          observer.unobserve(bar);
        });
      },
      { threshold: 0.1, rootMargin: "0px 0px -20px 0px" }
    );

    bars.forEach(function (bar) { observer.observe(bar); });
  }

  /* ── Smooth scroll for in-page anchor links ──────────────── */
  function setupSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
      anchor.addEventListener("click", function (e) {
        var id = anchor.getAttribute("href").slice(1);
        if (!id) return;
        var target = document.getElementById(id);
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  /* ── Initialise ──────────────────────────────────────────── */
  setActiveNavLink();
  setupCopyButtons();
  setupTextareaCounters();
  setupDirtyFormWarning();
  setupErrorFocus();
  setupPasswordToggles();
  setupFileInputLabels();
  setupReviewShortcuts();
  setupSmoothScroll();

  // Visual / animation features (all guard against reducedMotion)
  setupHeaderScroll();
  setupHeroOrbs();
  setupHeroWordRotation();
  setupScrollReveal();
  setupStatCounters();
  setupProgressBars();
  setupRipple();
  setupCardTilt();
})();
