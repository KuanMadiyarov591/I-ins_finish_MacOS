/* Мини-библиотека графиков для кабинетов I-ins.
 *
 * Никаких CDN: программа работает офлайн, поэтому графики рисуются
 * вручную обычным SVG. Размер холста фиксированный, а ширину задаёт
 * страница — так подписи масштабируются вместе с картинкой и остаются
 * читаемыми на любом мониторе.
 */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const W = 640;
  const H = 360;

  function node(name, attrs, parent) {
    const n = document.createElementNS(NS, name);
    if (attrs) {
      Object.keys(attrs).forEach((k) => {
        if (attrs[k] === null || attrs[k] === undefined) return;
        n.setAttribute(k, String(attrs[k]));
      });
    }
    if (parent) parent.appendChild(n);
    return n;
  }

  function title(parent, text) {
    if (!text) return;
    const t = node("title", null, parent);
    t.textContent = String(text);
  }

  function fmt(v, digits) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    if (v === 0) return "0";
    const d = digits === undefined ? autoDigits(v) : digits;
    const s = Math.abs(v) >= 10000
      ? Math.round(v).toLocaleString("ru-RU")
      : v.toFixed(d);
    return s.replace(".", ",");
  }

  function autoDigits(v) {
    const a = Math.abs(v);
    if (a >= 1000) return 0;
    if (a >= 100) return 1;
    if (a >= 1) return 2;
    if (a >= 0.01) return 3;
    return 4;
  }

  function ticks(min, max, count) {
    if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
      return [min || 0];
    }
    const span = max - min;
    const raw = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    let step = mag;
    if (norm > 5) step = 10 * mag;
    else if (norm > 2) step = 5 * mag;
    else if (norm > 1) step = 2 * mag;
    const first = Math.ceil(min / step) * step;
    const out = [];
    for (let v = first; v <= max + step * 1e-6; v += step) out.push(v);
    return out.length ? out : [min, max];
  }

  /* Общая рамка: сетка, оси, подписи. Возвращает функции координат. */
  function frame(host, opt) {
    const o = opt || {};
    const w = o.w || W;
    const h = o.h || H;
    host.innerHTML = "";
    const svg = node("svg", {
      viewBox: `0 0 ${w} ${h}`,
      class: "chart-svg",
      preserveAspectRatio: "xMidYMid meet",
      role: "img",
    }, host);

    let x0 = o.xMin;
    let x1 = o.xMax;
    let y0 = o.yMin;
    let y1 = o.yMax;
    if (!Number.isFinite(x0) || !Number.isFinite(x1) || x0 === x1) { x0 = 0; x1 = 1; }
    if (!Number.isFinite(y0) || !Number.isFinite(y1) || y0 === y1) { y0 = 0; y1 = 1; }

    // Поле слева считаем по самой длинной подписи: иначе «5 500 000»
    // наезжает на название оси.
    const yTicksPre = o.yTicks || ticks(y0, y1, 5);
    let widest = 0;
    yTicksPre.forEach((v) => {
      const s = o.yFormat ? o.yFormat(v) : fmt(v);
      if (s.length > widest) widest = s.length;
    });
    const pad = Object.assign(
      { l: Math.max(52, Math.round(26 + widest * 6.2)), r: 18, t: 18, b: 44 },
      o.pad || {},
    );

    const pw = w - pad.l - pad.r;
    const ph = h - pad.t - pad.b;
    const X = (v) => pad.l + ((v - x0) / (x1 - x0)) * pw;
    const Y = (v) => pad.t + ph - ((v - y0) / (y1 - y0)) * ph;

    node("rect", {
      x: pad.l, y: pad.t, width: pw, height: ph, class: "chart-plot",
    }, svg);

    const xt = o.xTicks || ticks(x0, x1, 6);
    const yt = yTicksPre;

    yt.forEach((v) => {
      node("line", {
        x1: pad.l, x2: pad.l + pw, y1: Y(v), y2: Y(v), class: "chart-grid",
      }, svg);
      const lab = node("text", {
        x: pad.l - 8, y: Y(v) + 4, class: "chart-tick", "text-anchor": "end",
      }, svg);
      lab.textContent = o.yFormat ? o.yFormat(v) : fmt(v);
    });

    xt.forEach((v) => {
      node("line", {
        x1: X(v), x2: X(v), y1: pad.t, y2: pad.t + ph, class: "chart-grid",
      }, svg);
      const lab = node("text", {
        x: X(v), y: pad.t + ph + 20, class: "chart-tick", "text-anchor": "middle",
      }, svg);
      lab.textContent = o.xFormat ? o.xFormat(v) : fmt(v);
    });

    if (o.xLabel) {
      const l = node("text", {
        x: pad.l + pw / 2, y: h - 8, class: "chart-axis-label", "text-anchor": "middle",
      }, svg);
      l.textContent = o.xLabel;
    }
    if (o.yLabel) {
      const l = node("text", {
        x: 14, y: pad.t + ph / 2, class: "chart-axis-label",
        "text-anchor": "middle", transform: `rotate(-90 14 ${pad.t + ph / 2})`,
      }, svg);
      l.textContent = o.yLabel;
    }

    return { svg, X, Y, pad, pw, ph, x0, x1, y0, y1, w, h };
  }

  function legend(f, items) {
    if (!items || !items.length) return;
    const g = node("g", { class: "chart-legend" }, f.svg);
    let y = f.pad.t + 14;
    items.forEach((it) => {
      const x = f.pad.l + f.pw - 10;
      const t = node("text", {
        x: x - 20, y, class: "chart-legend-text", "text-anchor": "end",
      }, g);
      t.textContent = it.label;
      node("line", {
        x1: x - 16, x2: x, y1: y - 4, y2: y - 4,
        stroke: it.color, "stroke-width": 2.4,
        "stroke-dasharray": it.dash || null,
      }, g);
      y += 17;
    });
  }

  function path(points) {
    return points
      .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
      .map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)} ${p[1].toFixed(2)}`)
      .join(" ");
  }

  /* ---------------------------------------------------- гистограмма */
  function histogram(host, opt) {
    const values = (opt.values || []).filter(Number.isFinite);
    if (!values.length) { host.innerHTML = ""; return null; }
    const bins = Math.max(4, Math.min(60, opt.bins || 18));
    let lo = Number.isFinite(opt.xMin) ? opt.xMin : Math.min(...values);
    let hi = Number.isFinite(opt.xMax) ? opt.xMax : Math.max(...values);
    if (lo === hi) { lo -= 1; hi += 1; }
    const width = (hi - lo) / bins;
    const counts = new Array(bins).fill(0);
    values.forEach((v) => {
      let i = Math.floor((v - lo) / width);
      if (i < 0) i = 0;
      if (i >= bins) i = bins - 1;
      counts[i] += 1;
    });
    // Плотность, а не частота: только так столбцы сравнимы с кривой модели.
    const dens = counts.map((c) => c / (values.length * width));
    let yMax = Math.max(...dens);
    (opt.curves || []).forEach((c) => {
      for (let i = 0; i <= 120; i += 1) {
        const x = lo + ((hi - lo) * i) / 120;
        const y = c.fn(x);
        if (Number.isFinite(y) && y > yMax) yMax = y;
      }
    });
    yMax *= 1.12;

    const f = frame(host, {
      xMin: lo, xMax: hi, yMin: 0, yMax,
      xLabel: opt.xLabel, yLabel: opt.yLabel || "Плотность",
      xFormat: opt.xFormat, yFormat: opt.yFormat,
    });

    dens.forEach((d, i) => {
      const bx = lo + i * width;
      const x = f.X(bx);
      const w = Math.max(1, f.X(bx + width) - x - 1);
      const y = f.Y(d);
      const r = node("rect", {
        x, y, width: w, height: Math.max(0, f.pad.t + f.ph - y),
        class: "chart-bar-hist",
      }, f.svg);
      title(r, `${fmt(bx)} … ${fmt(bx + width)}: ${counts[i]} набл.`);
    });

    (opt.curves || []).forEach((c) => {
      const pts = [];
      for (let i = 0; i <= 180; i += 1) {
        const x = lo + ((hi - lo) * i) / 180;
        pts.push([f.X(x), f.Y(c.fn(x))]);
      }
      node("path", {
        d: path(pts), fill: "none", stroke: c.color, "stroke-width": c.width || 2.4,
        "stroke-dasharray": c.dash || null, class: "chart-line",
      }, f.svg);
    });

    (opt.markers || []).forEach((m) => {
      if (!Number.isFinite(m.x)) return;
      node("line", {
        x1: f.X(m.x), x2: f.X(m.x), y1: f.pad.t, y2: f.pad.t + f.ph,
        stroke: m.color, "stroke-width": 1.6, "stroke-dasharray": m.dash || "5 4",
      }, f.svg);
    });

    legend(f, (opt.curves || []).map((c) => ({ label: c.label, color: c.color, dash: c.dash }))
      .concat(opt.legendExtra || []));
    return f;
  }

  /* --------------------------------------------------------- кривые */
  function lines(host, opt) {
    const series = (opt.series || []).filter((s) => s.points && s.points.length);
    if (!series.length) { host.innerHTML = ""; return null; }
    let xMin = Infinity; let xMax = -Infinity; let yMin = Infinity; let yMax = -Infinity;
    series.forEach((s) => s.points.forEach((p) => {
      if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) return;
      if (p[0] < xMin) xMin = p[0];
      if (p[0] > xMax) xMax = p[0];
      if (p[1] < yMin) yMin = p[1];
      if (p[1] > yMax) yMax = p[1];
    }));
    if (Number.isFinite(opt.yMin)) yMin = opt.yMin;
    if (Number.isFinite(opt.yMax)) yMax = opt.yMax;
    const padY = (yMax - yMin) * 0.08 || 1;
    yMin -= padY;
    yMax += padY;

    const f = frame(host, {
      xMin, xMax, yMin, yMax,
      xLabel: opt.xLabel, yLabel: opt.yLabel,
      xFormat: opt.xFormat, yFormat: opt.yFormat,
    });

    if (opt.area) {
      series.forEach((s) => {
        if (!s.area) return;
        const pts = s.points.map((p) => [f.X(p[0]), f.Y(p[1])]);
        const d = `${path(pts)} L${f.X(s.points[s.points.length - 1][0]).toFixed(2)} ${f.Y(yMin).toFixed(2)} L${f.X(s.points[0][0]).toFixed(2)} ${f.Y(yMin).toFixed(2)} Z`;
        node("path", { d, fill: s.color, opacity: 0.12 }, f.svg);
      });
    }

    series.forEach((s) => {
      const pts = s.points.map((p) => [f.X(p[0]), f.Y(p[1])]);
      node("path", {
        d: path(pts), fill: "none", stroke: s.color,
        "stroke-width": s.width || 2.4, "stroke-dasharray": s.dash || null,
        class: "chart-line",
      }, f.svg);
    });

    (opt.markers || []).forEach((m, mi) => {
      if (!Number.isFinite(m.x)) return;
      const x = f.X(m.x);
      node("line", {
        x1: x, x2: x, y1: f.pad.t, y2: f.pad.t + f.ph,
        stroke: m.color, "stroke-width": 1.6, "stroke-dasharray": m.dash || "5 4",
      }, f.svg);
      if (Number.isFinite(m.y)) {
        const c = node("circle", {
          cx: x, cy: f.Y(m.y), r: 4.6, fill: m.color, class: "chart-dot",
        }, f.svg);
        title(c, `${m.label || ""} ${fmt(m.x)}`);
      }
      if (m.label) {
        // Метки разводим по высоте: при совпадении маркеров они сливаются.
        const right = x > f.pad.l + f.pw * 0.72;
        const t = node("text", {
          x: right ? x - 6 : x + 6,
          y: f.pad.t + 14 + mi * 16,
          class: "chart-marker-label",
          fill: m.color,
          "text-anchor": right ? "end" : "start",
        }, f.svg);
        t.textContent = m.label;
      }
    });

    legend(f, series.filter((s) => s.label).map((s) => ({
      label: s.label, color: s.color, dash: s.dash,
    })));
    return f;
  }

  /* ------------------------------------------------ столбцы по группам */
  function bars(host, opt) {
    const items = (opt.items || []).slice(0, opt.max || 16);
    if (!items.length) { host.innerHTML = ""; return null; }
    const keys = opt.series || [{ key: "value", label: "", color: "#2f6f4f" }];
    let yMax = 0;
    items.forEach((it) => keys.forEach((k) => {
      const v = Number(it[k.key]);
      if (Number.isFinite(v) && v > yMax) yMax = v;
    }));
    if (yMax <= 0) yMax = 1;
    yMax *= 1.1;

    const wide = items.length > 6;
    // Если все значения целые (счёт дел, число программ), не показываем
    // на оси «30,00» — это читается как деньги.
    let allInt = true;
    items.forEach((it) => keys.forEach((k) => {
      const v = Number(it[k.key]);
      if (Number.isFinite(v) && !Number.isInteger(v)) allInt = false;
    }));
    const f = frame(host, {
      xMin: 0, xMax: items.length, yMin: 0, yMax,
      xTicks: [], yLabel: opt.yLabel,
      yFormat: opt.yFormat || (allInt ? (v) => fmt(v, 0) : undefined),
      w: wide ? 1120 : W,
      h: wide ? 420 : H,
      pad: { l: 78, r: 18, t: 18, b: wide ? 76 : 62 },
    });

    const slot = f.pw / items.length;
    const inner = slot * 0.72;
    const bw = inner / keys.length;
    items.forEach((it, i) => {
      keys.forEach((k, j) => {
        const v = Number(it[k.key]) || 0;
        const x = f.pad.l + i * slot + (slot - inner) / 2 + j * bw;
        const y = f.Y(v);
        const r = node("rect", {
          x, y: Math.min(y, f.Y(0)), width: Math.max(1, bw - 2),
          height: Math.max(1, Math.abs(f.Y(0) - y)),
          fill: k.color, class: "chart-bar",
        }, f.svg);
        title(r, `${it.label}: ${k.label ? k.label + " " : ""}${fmt(v)}`);
      });
      const lab = node("text", {
        x: f.pad.l + i * slot + slot / 2,
        y: f.pad.t + f.ph + 18,
        class: "chart-tick",
        "text-anchor": "end",
        transform: `rotate(-38 ${(f.pad.l + i * slot + slot / 2).toFixed(1)} ${(f.pad.t + f.ph + 18).toFixed(1)})`,
      }, f.svg);
      lab.textContent = String(it.label).slice(0, 14);
    });

    legend(f, keys.filter((k) => k.label).map((k) => ({ label: k.label, color: k.color })));
    return f;
  }

  /* ----------------------------------------- горизонтальные столбцы */
  function hbars(host, opt) {
    const items = (opt.items || []).slice(0, opt.max || 14);
    host.innerHTML = "";
    if (!items.length) return null;
    const max = Math.max(...items.map((i) => Number(i.value) || 0), 1);
    const wrap = document.createElement("div");
    wrap.className = "hbar-list";
    items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "hbar-row";
      const share = Math.max(0, (Number(it.value) || 0) / max * 100);
      row.innerHTML =
        `<span class="hbar-label" title="${String(it.label).replace(/"/g, "&quot;")}">${String(it.label)}</span>` +
        `<span class="hbar-track"><span class="hbar-fill" style="width:${share.toFixed(1)}%;background:${it.color || opt.color || "#2f6f4f"}"></span></span>` +
        `<span class="hbar-value">${opt.format ? opt.format(it.value) : fmt(it.value)}</span>` +
        (it.hint ? `<span class="hbar-hint">${it.hint}</span>` : "");
      wrap.appendChild(row);
    });
    host.appendChild(wrap);
    return wrap;
  }

  /* ------------------------------------------------------ рассеяние */
  function scatter(host, opt) {
    const pts = (opt.points || []).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    if (!pts.length) { host.innerHTML = ""; return null; }
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const f = frame(host, {
      xMin: Math.min(...xs), xMax: Math.max(...xs),
      yMin: Math.min(...ys), yMax: Math.max(...ys),
      xLabel: opt.xLabel, yLabel: opt.yLabel,
      xFormat: opt.xFormat, yFormat: opt.yFormat,
    });
    pts.forEach((p) => {
      node("circle", {
        cx: f.X(p[0]), cy: f.Y(p[1]), r: opt.radius || 2.4,
        class: "chart-point", fill: opt.color || "#2f6f4f",
      }, f.svg);
    });
    if (opt.trend && opt.trend.length === 2) {
      const a = opt.trend[0];
      const b = opt.trend[1];
      const x0 = Math.min(...xs);
      const x1 = Math.max(...xs);
      node("path", {
        d: path([[f.X(x0), f.Y(a + b * x0)], [f.X(x1), f.Y(a + b * x1)]]),
        fill: "none", stroke: opt.trendColor || "#b4472f", "stroke-width": 2.2,
      }, f.svg);
    }
    return f;
  }

  /* ---------------------------------------------------------- кольцо */
  function donut(host, opt) {
    const items = (opt.items || []).filter((i) => Number(i.value) > 0);
    host.innerHTML = "";
    if (!items.length) return null;
    const total = items.reduce((s, i) => s + Number(i.value), 0);
    const svg = node("svg", {
      viewBox: "0 0 520 240", class: "chart-svg", preserveAspectRatio: "xMidYMid meet",
    }, host);
    const cx = 118;
    const cy = 120;
    const R = 84;
    const r = 50;
    let acc = -Math.PI / 2;
    items.forEach((it) => {
      const frac = Number(it.value) / total;
      const a0 = acc;
      const a1 = acc + frac * Math.PI * 2;
      acc = a1;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      const d = [
        `M${(cx + R * Math.cos(a0)).toFixed(2)} ${(cy + R * Math.sin(a0)).toFixed(2)}`,
        `A${R} ${R} 0 ${large} 1 ${(cx + R * Math.cos(a1)).toFixed(2)} ${(cy + R * Math.sin(a1)).toFixed(2)}`,
        `L${(cx + r * Math.cos(a1)).toFixed(2)} ${(cy + r * Math.sin(a1)).toFixed(2)}`,
        `A${r} ${r} 0 ${large} 0 ${(cx + r * Math.cos(a0)).toFixed(2)} ${(cy + r * Math.sin(a0)).toFixed(2)}`,
        "Z",
      ].join(" ");
      const p = node("path", { d, fill: it.color, class: "chart-slice" }, svg);
      title(p, `${it.label}: ${fmt(it.value)} (${(frac * 100).toFixed(1).replace(".", ",")} %)`);
    });
    const c = node("text", {
      x: cx, y: cy + 2, "text-anchor": "middle", class: "chart-donut-total",
    }, svg);
    c.textContent = fmt(total, 0);
    const cl = node("text", {
      x: cx, y: cy + 20, "text-anchor": "middle", class: "chart-tick",
    }, svg);
    cl.textContent = opt.totalLabel || "всего";

    let y = 46;
    items.forEach((it) => {
      node("rect", { x: 240, y: y - 9, width: 11, height: 11, rx: 2, fill: it.color }, svg);
      const t = node("text", { x: 257, y, class: "chart-legend-text" }, svg);
      t.textContent = `${it.label} — ${fmt(it.value, 0)}`;
      y += 22;
    });
    return svg;
  }

  window.IInsCharts = {
    histogram, lines, bars, hbars, scatter, donut, fmt, ticks,
  };
})();
