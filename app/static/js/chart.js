// Sales overview line chart: this period (brand green, with area) vs the previous period (gray).
// Plain SVG, redrawn on resize, with a crosshair + tooltip on hover/touch.
(function () {
  var el = document.querySelector("[data-line-chart]");
  var dataEl = document.querySelector("[data-chart-data]");
  if (!el || !dataEl) return;
  var data = JSON.parse(dataEl.textContent);
  var NS = "http://www.w3.org/2000/svg";
  var GREEN = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim() || "#17823c";
  var GRAY = "#b8c2bb";
  var money = function (v) { return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  var short = function (v) { return v >= 1000 ? "$" + (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "k" : "$" + Math.round(v); };

  function niceMax(v) {
    if (v <= 0) return 10;
    var p = Math.pow(10, Math.floor(Math.log10(v)));
    var steps = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * p >= v) return steps[i] * p;
    return 10 * p;
  }
  function node(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  var tip = document.createElement("div");
  tip.className = "chart-tip";
  el.appendChild(tip);

  function draw() {
    var old = el.querySelector("svg");
    if (old) old.remove();
    var W = el.clientWidth, H = el.clientHeight;
    var m = { top: 12, right: 12, bottom: 28, left: 46 };
    var w = W - m.left - m.right, h = H - m.top - m.bottom;
    var n = data.labels.length;
    var max = niceMax(Math.max.apply(null, data.current.concat(data.previous)));
    var x = function (i) { return m.left + (n === 1 ? w / 2 : (i / (n - 1)) * w); };
    var y = function (v) { return m.top + h - (v / max) * h; };

    var svg = node("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": el.getAttribute("aria-label") });
    el.insertBefore(svg, tip);
    var defs = node("defs", {}, svg);
    var grad = node("linearGradient", { id: "area", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    node("stop", { offset: 0, "stop-color": GREEN, "stop-opacity": 0.18 }, grad);
    node("stop", { offset: 1, "stop-color": GREEN, "stop-opacity": 0 }, grad);

    // Recessive grid + y labels.
    var grid = node("g", { class: "grid" }, svg), axis = node("g", { class: "axis" }, svg);
    for (var t = 0; t <= 4; t++) {
      var v = (max / 4) * t, yy = y(v);
      node("line", { x1: m.left, x2: m.left + w, y1: yy, y2: yy }, grid);
      node("text", { x: m.left - 10, y: yy + 4, "text-anchor": "end" }, axis).textContent = short(v);
    }
    // ~5 x labels, evenly spaced.
    var every = Math.max(1, Math.ceil(n / 6));
    for (var i = 0; i < n; i += every) {
      node("text", { x: x(i), y: H - 6, "text-anchor": i === 0 ? "start" : "middle" }, axis).textContent = data.labels[i];
    }

    function path(values) {
      return values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); }).join("");
    }
    node("path", { d: path(data.current) + "L" + x(n - 1) + "," + y(0) + "L" + x(0) + "," + y(0) + "Z", fill: "url(#area)" }, svg);
    node("path", { d: path(data.previous), fill: "none", stroke: GRAY, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    node("path", { d: path(data.current), fill: "none", stroke: GREEN, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    // End-of-line marker on the current series.
    node("circle", { cx: x(n - 1), cy: y(data.current[n - 1]), r: 4, fill: GREEN, stroke: "#fff", "stroke-width": 2 }, svg);

    // Hover layer.
    var cross = node("line", { y1: m.top, y2: m.top + h, stroke: "#9aa69f", "stroke-dasharray": "3 3", opacity: 0 }, svg);
    var dotPrev = node("circle", { r: 4, fill: GRAY, stroke: "#fff", "stroke-width": 2, opacity: 0 }, svg);
    var dotCur = node("circle", { r: 4.5, fill: GREEN, stroke: "#fff", "stroke-width": 2, opacity: 0 }, svg);
    var hit = node("rect", { x: m.left, y: 0, width: w, height: H, fill: "transparent" }, svg);

    function show(evt) {
      var rect = svg.getBoundingClientRect();
      var px = ((evt.touches ? evt.touches[0].clientX : evt.clientX) - rect.left) * (W / rect.width);
      var i = Math.round(((px - m.left) / w) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      var cx = x(i);
      cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.setAttribute("opacity", 1);
      dotCur.setAttribute("cx", cx); dotCur.setAttribute("cy", y(data.current[i])); dotCur.setAttribute("opacity", 1);
      dotPrev.setAttribute("cx", cx); dotPrev.setAttribute("cy", y(data.previous[i])); dotPrev.setAttribute("opacity", 1);
      tip.innerHTML = '<div class="d">' + data.labels[i] + "</div>" +
        '<div class="row"><span><i style="background:' + GREEN + '"></i>This period</span><b>' + money(data.current[i]) + "</b></div>" +
        '<div class="row"><span><i style="background:' + GRAY + '"></i>Previous</span><b>' + money(data.previous[i]) + "</b></div>";
      tip.style.opacity = 1;
      var left = (cx / W) * el.clientWidth + 14;
      if (left + tip.offsetWidth > el.clientWidth) left = (cx / W) * el.clientWidth - tip.offsetWidth - 14;
      tip.style.left = left + "px";
      tip.style.top = "8px";
    }
    function hide() {
      [cross, dotCur, dotPrev].forEach(function (n) { n.setAttribute("opacity", 0); });
      tip.style.opacity = 0;
    }
    hit.addEventListener("mousemove", show);
    hit.addEventListener("touchstart", show, { passive: true });
    hit.addEventListener("touchmove", show, { passive: true });
    hit.addEventListener("mouseleave", hide);
  }

  draw();
  var timer;
  window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(draw, 120); });
})();
