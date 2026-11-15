// Small progressive enhancements. Every page also works without JavaScript.
(function () {
  // Flash messages: dismiss on click, fade out after a few seconds.
  document.querySelectorAll(".flash").forEach(function (el, i) {
    el.querySelector("[data-dismiss]").addEventListener("click", function () { el.remove(); });
    setTimeout(function () { el.classList.add("hide"); setTimeout(function () { el.remove(); }, 400); }, 4500 + i * 600);
  });

  // Quantity steppers (+ / −), respecting min/max. In the cart, a change submits the form.
  document.querySelectorAll("[data-qty]").forEach(function (box) {
    var input = box.querySelector("input");
    var form = box.closest("form[data-autosubmit]");
    var timer;
    function submitSoon() { if (form) { clearTimeout(timer); timer = setTimeout(function () { form.submit(); }, 450); } }
    box.querySelectorAll("[data-step]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var min = Number(input.min || 0), max = Number(input.max || 99);
        var next = Math.min(max, Math.max(min, (Number(input.value) || 0) + Number(btn.dataset.step)));
        if (next !== Number(input.value)) { input.value = next; submitSoon(); }
      });
    });
    input.addEventListener("change", submitSoon);
  });

  // Confirmation before destructive actions.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) { if (!confirm(form.dataset.confirm)) e.preventDefault(); });
  });

  // Copy a link to the clipboard.
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var done = function () { var t = btn.textContent; btn.textContent = "Copied!"; setTimeout(function () { btn.textContent = t; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(btn.dataset.copy).then(done);
      else { window.prompt("Copy this link:", btn.dataset.copy); }
    });
  });

  // Image preview on the admin product form.
  document.querySelectorAll("input[type=file][data-preview]").forEach(function (input) {
    var img = document.getElementById(input.dataset.preview);
    var original = img ? img.src : "";
    var error = input.parentElement.querySelector("[data-file-error]");
    var allowed = (input.getAttribute("accept") || "").split(",");
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      var problem = "";
      if (file && allowed.indexOf(file.type) === -1) problem = "This file type isn't supported. Use JPG, PNG, WEBP, GIF or AVIF.";
      else if (file && input.dataset.maxBytes && file.size > Number(input.dataset.maxBytes)) problem = "This image is " + (file.size / 1048576).toFixed(1) + " MB. The limit is 5 MB.";
      if (error) { error.textContent = problem; error.hidden = !problem; }
      if (problem) { input.value = ""; if (img) img.src = original; return; }
      if (img && file) { img.src = URL.createObjectURL(file); img.hidden = false; }
    });
  });

  // Sort select submits on change.
  document.querySelectorAll("select[data-autosubmit-select]").forEach(function (sel) {
    sel.addEventListener("change", function () { sel.form.submit(); });
  });

  // Categories dropdown: also opens on tap (touch screens have no hover).
  document.querySelectorAll("[data-dropdown] > button").forEach(function (btn) {
    btn.addEventListener("click", function (e) { e.stopPropagation(); btn.parentElement.classList.toggle("open"); });
  });
  document.addEventListener("click", function () {
    document.querySelectorAll("[data-dropdown].open").forEach(function (d) { d.classList.remove("open"); });
  });

  // Admin sidebar on small screens.
  var shell = document.querySelector("[data-admin-shell]");
  var toggle = document.querySelector("[data-menu-toggle]");
  if (shell && toggle) {
    toggle.addEventListener("click", function (e) { e.stopPropagation(); shell.classList.toggle("nav-open"); });
    document.addEventListener("click", function (e) {
      if (shell.classList.contains("nav-open") && !e.target.closest(".sidebar")) shell.classList.remove("nav-open");
    });
  }

  // Home hero slider: arrows, dots, auto-advance (paused while hovered).
  document.querySelectorAll("[data-slider]").forEach(function (slider) {
    var slides = slider.querySelectorAll(".slide");
    var dots = slider.querySelector("[data-dots]");
    if (slides.length < 2) { slider.querySelectorAll(".slider-arrow").forEach(function (b) { b.hidden = true; }); return; }
    var current = 0, timer;
    slides.forEach(function (_, i) {
      var b = document.createElement("button");
      b.type = "button"; b.setAttribute("aria-label", "Slide " + (i + 1));
      b.addEventListener("click", function () { go(i); restart(); });
      dots.appendChild(b);
    });
    function go(i) {
      current = (i + slides.length) % slides.length;
      slides.forEach(function (s, j) { s.classList.toggle("active", j === current); });
      dots.querySelectorAll("button").forEach(function (d, j) { d.classList.toggle("active", j === current); });
    }
    function restart() { clearInterval(timer); timer = setInterval(function () { go(current + 1); }, 6000); }
    slider.querySelector("[data-prev]").addEventListener("click", function () { go(current - 1); restart(); });
    slider.querySelector("[data-next]").addEventListener("click", function () { go(current + 1); restart(); });
    slider.addEventListener("mouseenter", function () { clearInterval(timer); });
    slider.addEventListener("mouseleave", restart);
    go(0); restart();
  });

  // KHQR payment page: count down and poll the server until the order is paid or expires.
  window.startPaymentWatch = function (statusUrl, pageUrl) {
    var countdown = document.querySelector("[data-countdown]");
    var text = document.querySelector("[data-pay-text]");
    var warning = document.querySelector("[data-warning]");
    var left = Number(countdown ? countdown.dataset.countdown : 0);
    function tick() {
      if (!countdown) return;
      var m = Math.floor(left / 60), s = left % 60;
      countdown.textContent = m + ":" + (s < 10 ? "0" : "") + s;
      if (left <= 0) { window.location.href = pageUrl; return; }
      left -= 1;
    }
    tick(); setInterval(tick, 1000);

    function poll() {
      fetch(statusUrl, { headers: { Accept: "application/json" }, cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.redirect) { if (text) text.textContent = "Payment received! Redirecting…"; window.location.href = data.redirect; return; }
          if (data.status !== "pending") { window.location.href = pageUrl; return; }
          if (warning) { warning.hidden = !data.warning; warning.textContent = data.warning || ""; }
          setTimeout(poll, 3000);
        })
        .catch(function () { setTimeout(poll, 5000); });
    }
    setTimeout(poll, 3000);
  };
})();
