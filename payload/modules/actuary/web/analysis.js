/* Вкладка «Анализ» кабинета актуария.
 *
 * Работает поверх одного пакета данных: сервер отдаёт совокупность
 * значений и срезы, а подгонка распределения, правдоподобие и
 * чувствительность тарифа считаются здесь. Ползунок должен отзываться
 * сразу, иначе смотреть на него бессмысленно.
 */
(() => {
  const I = window.ActuaryI18n;
  const C = window.IInsCharts;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const t = (k, v) => (I ? I.t(k, v) : k);

  // Цвета берём из темы кабинета, чтобы графики не выпадали из оформления.
  let INK = "#13294b";
  let GREEN = "#0f6b6b";
  let RUST = "#c2410c";
  let BLUE = "#2563eb";
  let SAND = "#1e3a5f";

  function readPalette() {
    const cs = getComputedStyle(document.documentElement);
    const v = (name, fb) => (cs.getPropertyValue(name) || "").trim() || fb;
    INK = v("--navy", INK);
    GREEN = v("--teal", GREEN);
    RUST = v("--escalate", RUST);
    BLUE = v("--sky", BLUE);
    SAND = v("--navy-soft", SAND);
  }

  const state = {
    data: null,
    loading: false,
    view: "fit",
    field: "selected",
    family: "normal",
    n: 200,
    seed: 1,
    sample: [],
    p1: null,
    p2: null,
    profile: "p1",
    group: "territory",
    metric: "avg",
    base: 1,
    expShare: 0,
    cgrShift: 0,
  };

  /* ------------------------------------------------------ математика */
  const LOG_2PI = Math.log(2 * Math.PI);

  function lgamma(x) {
    // Приближение Ланцоша: точности с избытком хватает для правдоподобия.
    const g = [
      676.5203681218851, -1259.1392167224028, 771.32342877765313,
      -176.61502916214059, 12.507343278686905, -0.13857109526572012,
      9.9843695780195716e-6, 1.5056327351493116e-7,
    ];
    if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - lgamma(1 - x);
    const z = x - 1;
    let a = 0.99999999999980993;
    for (let i = 0; i < g.length; i += 1) a += g[i] / (z + i + 1);
    const tt = z + g.length - 0.5;
    return 0.5 * LOG_2PI + (z + 0.5) * Math.log(tt) - tt + Math.log(a);
  }

  function digamma(x) {
    let v = x;
    let r = 0;
    while (v < 6) { r -= 1 / v; v += 1; }
    const f = 1 / (v * v);
    return r + Math.log(v) - 0.5 / v
      - f * (1 / 12 - f * (1 / 120 - f * (1 / 252 - f * (1 / 240))));
  }

  function trigamma(x) {
    let v = x;
    let r = 0;
    while (v < 6) { r += 1 / (v * v); v += 1; }
    const f = 1 / (v * v);
    return r + (1 / v) * (1 + 0.5 / v + f * (1 / 6 - f * (1 / 30 - f / 42)));
  }

  function erf(x) {
    // Формула Абрамовица — Стигана 7.1.26, ошибка ниже 1,5·10⁻⁷.
    const s = x < 0 ? -1 : 1;
    const a = Math.abs(x);
    const tt = 1 / (1 + 0.3275911 * a);
    const y = 1 - ((((1.061405429 * tt - 1.453152027) * tt + 1.421413741) * tt
      - 0.284496736) * tt + 0.254829592) * tt * Math.exp(-a * a);
    return s * y;
  }

  function normCdf(z) { return 0.5 * (1 + erf(z / Math.SQRT2)); }

  function gammaP(a, x) {
    // Регуляризованная неполная гамма: ряд при малых x, дробь при больших.
    if (x <= 0) return 0;
    if (x < a + 1) {
      let ap = a;
      let sum = 1 / a;
      let del = sum;
      for (let i = 0; i < 300; i += 1) {
        ap += 1;
        del *= x / ap;
        sum += del;
        if (Math.abs(del) < Math.abs(sum) * 1e-12) break;
      }
      return sum * Math.exp(-x + a * Math.log(x) - lgamma(a));
    }
    let b = x + 1 - a;
    let c = 1e30;
    let d = 1 / b;
    let h = d;
    for (let i = 1; i < 300; i += 1) {
      const an = -i * (i - a);
      b += 2;
      d = an * d + b;
      if (Math.abs(d) < 1e-30) d = 1e-30;
      c = b + an / c;
      if (Math.abs(c) < 1e-30) c = 1e-30;
      d = 1 / d;
      const del = d * c;
      h *= del;
      if (Math.abs(del - 1) < 1e-12) break;
    }
    return 1 - Math.exp(-x + a * Math.log(x) - lgamma(a)) * h;
  }

  const FAMILIES = {
    normal: {
      key: "normal",
      label: () => t("an_family_normal"),
      p1: () => "μ",
      p2: () => "σ",
      support: () => true,
      fit(xs) {
        const n = xs.length;
        if (n < 2) return null;
        const mu = xs.reduce((s, v) => s + v, 0) / n;
        const sd = Math.sqrt(xs.reduce((s, v) => s + (v - mu) ** 2, 0) / n);
        return [mu, Math.max(sd, 1e-9)];
      },
      logpdf(x, mu, sd) {
        if (!(sd > 0)) return -Infinity;
        return -0.5 * LOG_2PI - Math.log(sd) - ((x - mu) ** 2) / (2 * sd * sd);
      },
      pdf(x, mu, sd) { return Math.exp(FAMILIES.normal.logpdf(x, mu, sd)); },
      cdf(x, mu, sd) { return normCdf((x - mu) / sd); },
      range(fit, pop) {
        const sd = fit ? fit[1] : 1;
        const mu = fit ? fit[0] : 0;
        return [mu - 4 * sd, mu + 4 * sd, pop];
      },
      bounds(fit) {
        const mu = fit[0];
        const sd = fit[1];
        return [[mu - 3 * sd, mu + 3 * sd], [Math.max(sd / 4, 1e-6), sd * 3]];
      },
    },
    lognormal: {
      key: "lognormal",
      label: () => t("an_family_lognormal"),
      p1: () => t("an_p_mu_log"),
      p2: () => t("an_p_sigma_log"),
      support: (x) => x > 0,
      fit(xs) {
        const pos = xs.filter((v) => v > 0);
        if (pos.length < 2) return null;
        const logs = pos.map(Math.log);
        const mu = logs.reduce((s, v) => s + v, 0) / logs.length;
        const sd = Math.sqrt(logs.reduce((s, v) => s + (v - mu) ** 2, 0) / logs.length);
        return [mu, Math.max(sd, 1e-9)];
      },
      logpdf(x, mu, sd) {
        if (!(x > 0) || !(sd > 0)) return -Infinity;
        const l = Math.log(x);
        return -l - 0.5 * LOG_2PI - Math.log(sd) - ((l - mu) ** 2) / (2 * sd * sd);
      },
      pdf(x, mu, sd) { return x > 0 ? Math.exp(FAMILIES.lognormal.logpdf(x, mu, sd)) : 0; },
      cdf(x, mu, sd) { return x > 0 ? normCdf((Math.log(x) - mu) / sd) : 0; },
      bounds(fit) {
        const mu = fit[0];
        const sd = fit[1];
        return [[mu - 3 * sd, mu + 3 * sd], [Math.max(sd / 4, 1e-6), sd * 3]];
      },
    },
    gamma: {
      key: "gamma",
      label: () => t("an_family_gamma"),
      p1: () => t("an_p_shape"),
      p2: () => t("an_p_scale"),
      support: (x) => x > 0,
      fit(xs) {
        const pos = xs.filter((v) => v > 0);
        if (pos.length < 2) return null;
        const mean = pos.reduce((s, v) => s + v, 0) / pos.length;
        const logMean = pos.reduce((s, v) => s + Math.log(v), 0) / pos.length;
        const s = Math.log(mean) - logMean;
        if (!(s > 0)) return [1e6, mean / 1e6];
        // Стартовая точка Тома, затем несколько шагов Ньютона.
        let k = (3 - s + Math.sqrt((3 - s) ** 2 + 24 * s)) / (12 * s);
        for (let i = 0; i < 60; i += 1) {
          const f = Math.log(k) - digamma(k) - s;
          const fp = 1 / k - trigamma(k);
          if (!Number.isFinite(fp) || Math.abs(fp) < 1e-14) break;
          const next = k - f / fp;
          if (!Number.isFinite(next) || next <= 0) break;
          if (Math.abs(next - k) < 1e-10) { k = next; break; }
          k = next;
        }
        return [k, mean / k];
      },
      logpdf(x, k, th) {
        if (!(x > 0) || !(k > 0) || !(th > 0)) return -Infinity;
        return (k - 1) * Math.log(x) - x / th - k * Math.log(th) - lgamma(k);
      },
      pdf(x, k, th) { return x > 0 ? Math.exp(FAMILIES.gamma.logpdf(x, k, th)) : 0; },
      cdf(x, k, th) { return x > 0 ? gammaP(k, x / th) : 0; },
      bounds(fit) {
        const k = fit[0];
        const th = fit[1];
        return [[Math.max(k / 4, 0.05), k * 3], [Math.max(th / 4, 1e-6), th * 3]];
      },
    },
  };

  function logLik(xs, fam, a, b) {
    let s = 0;
    for (let i = 0; i < xs.length; i += 1) {
      const v = fam.logpdf(xs[i], a, b);
      if (!Number.isFinite(v)) return -Infinity;
      s += v;
    }
    return s;
  }

  function ksDistance(xs, fam, a, b) {
    const sorted = xs.filter((v) => fam.support(v)).slice().sort((p, q) => p - q);
    const n = sorted.length;
    if (!n) return null;
    let d = 0;
    for (let i = 0; i < n; i += 1) {
      const F = fam.cdf(sorted[i], a, b);
      d = Math.max(d, Math.abs(F - i / n), Math.abs((i + 1) / n - F));
    }
    return d;
  }

  /* Простой воспроизводимый генератор: одна и та же выборка при том же seed. */
  function rng(seed) {
    let s = seed >>> 0 || 1;
    return () => {
      s ^= s << 13; s >>>= 0;
      s ^= s >> 17;
      s ^= s << 5; s >>>= 0;
      return s / 4294967296;
    };
  }

  function drawSample(pop, n, seed) {
    if (!pop.length) return [];
    if (n >= pop.length) return pop.slice();
    const rand = rng(seed * 2654435761 + 12345);
    const idx = pop.map((_, i) => i);
    for (let i = idx.length - 1; i > 0; i -= 1) {
      const j = Math.floor(rand() * (i + 1));
      const tmp = idx[i]; idx[i] = idx[j]; idx[j] = tmp;
    }
    return idx.slice(0, n).map((i) => pop[i]);
  }

  const num = (v, d) => C.fmt(v, d);

  /* ------------------------------------------------------------ данные */
  async function apiGet(path) {
    const headers = {};
    const token = localStorage.getItem("ad_token") || "";
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(path, { headers });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
      throw new Error(detail);
    }
    return res.json();
  }

  async function ensureData() {
    if (state.data || state.loading) return;
    state.loading = true;
    const status = $("#an-status");
    if (status) status.textContent = t("an_loading");
    try {
      state.data = await apiGet("/api/analysis/data");
      initControls();
      render();
    } catch (err) {
      if (status) status.textContent = `${t("an_err")}: ${err.message || err}`;
    } finally {
      state.loading = false;
    }
  }

  function paintStatus() {
    const status = $("#an-status");
    if (!status || !state.data) return;
    const kind = { csv: "an_src_csv", db: "an_src_db" }[state.data.source_kind];
    status.textContent = kind
      ? t("an_source", { src: t(kind), n: state.data.source_rows || 0 })
      : t("an_no_data");
  }

  function population() {
    const s = (state.data && state.data.samples && state.data.samples[state.field]) || [];
    const fam = FAMILIES[state.family];
    return s.filter((v) => Number.isFinite(v) && fam.support(v));
  }

  /* --------------------------------------------------------- элементы */
  function initControls() {
    paintFieldOptions();
    resample(true);
  }

  function paintFieldOptions() {
    const sel = $("#an-field");
    if (!sel) return;
    sel.innerHTML = (state.data.fields || [])
      .map((f) => `<option value="${f.id}">${fieldName(f)}</option>`)
      .join("");
    sel.value = state.field;
  }

  function fieldName(f) {
    const s = f.key ? t(f.key) : "";
    return s && s !== f.key ? s : (f.label || f.id);
  }

  function resample(keepSeed) {
    if (!keepSeed) state.seed += 1;
    const pop = population();
    const maxN = Math.max(10, pop.length);
    const nSlider = $("#an-n");
    if (nSlider) {
      nSlider.max = String(Math.min(1000, maxN));
      if (Number(nSlider.value) > Number(nSlider.max)) nSlider.value = nSlider.max;
      state.n = Number(nSlider.value) || Math.min(200, maxN);
    }
    state.sample = drawSample(pop, Math.min(state.n, pop.length), state.seed);
    resetToMle();
  }

  function resetToMle() {
    const fam = FAMILIES[state.family];
    const fit = fam.fit(state.sample);
    if (!fit) return;
    state.p1 = fit[0];
    state.p2 = fit[1];
    syncSliders(fit);
  }

  function syncSliders(fit) {
    const fam = FAMILIES[state.family];
    const bounds = fam.bounds(fit || fam.fit(state.sample) || [state.p1, state.p2]);
    const s1 = $("#an-p1");
    const s2 = $("#an-p2");
    if (s1) {
      s1.min = String(bounds[0][0]);
      s1.max = String(bounds[0][1]);
      s1.step = String((bounds[0][1] - bounds[0][0]) / 400 || 0.001);
      s1.value = String(state.p1);
    }
    if (s2) {
      s2.min = String(bounds[1][0]);
      s2.max = String(bounds[1][1]);
      s2.step = String((bounds[1][1] - bounds[1][0]) / 400 || 0.001);
      s2.value = String(state.p2);
    }
  }

  /* ------------------------------------------------------ отрисовка */
  function render() {
    if (!state.data) return;
    paintStatus();
    paintFieldOptions();
    $$(".an-view").forEach((v) => { v.hidden = v.dataset.view !== state.view; });
    $$("#analysis-subtabs .tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.an === state.view);
    });
    if (state.view === "fit") renderFit();
    if (state.view === "slices") renderSlices();
    if (state.view === "sens") renderSens();
  }

  function renderFit() {
    const fam = FAMILIES[state.family];
    const xs = state.sample;
    const pop = population();
    if (!xs.length) {
      $("#an-hist").innerHTML = `<p class="muted small">${t("an_no_data")}</p>`;
      $("#an-ll").innerHTML = "";
      return;
    }
    const mle = fam.fit(xs) || [state.p1, state.p2];
    const popFit = fam.fit(pop) || mle;
    const ll = logLik(xs, fam, state.p1, state.p2);
    const llMle = logLik(xs, fam, mle[0], mle[1]);

    $("#an-p1-name").textContent = fam.p1();
    $("#an-p2-name").textContent = fam.p2();
    const prof = $("#an-profile");
    if (prof && prof.options.length >= 2) {
      prof.options[0].textContent = fam.p1();
      prof.options[1].textContent = fam.p2();
    }
    $("#an-p1-val").textContent = num(state.p1, 3);
    $("#an-p2-val").textContent = num(state.p2, 3);
    $("#an-n-val").textContent = String(xs.length);

    const lo = Math.min(...xs);
    const hi = Math.max(...xs);
    const padX = (hi - lo) * 0.12 || 1;
    C.histogram($("#an-hist"), {
      values: xs,
      bins: Math.max(8, Math.min(34, Math.round(Math.sqrt(xs.length) * 1.6))),
      xMin: Math.max(fam.support(0) ? lo - padX : 1e-9, fam.key === "normal" ? lo - padX : lo * 0.6),
      xMax: hi + padX,
      xLabel: fieldLabel(),
      yLabel: t("an_hist_y"),
      curves: [
        {
          fn: (x) => fam.pdf(x, state.p1, state.p2),
          color: RUST, label: t("an_curve_current"), width: 2.6,
        },
        {
          fn: (x) => fam.pdf(x, popFit[0], popFit[1]),
          color: BLUE, label: t("an_curve_pop"), dash: "6 4", width: 2.2,
        },
      ],
    });

    // Профиль правдоподобия: второй параметр держим на текущем значении.
    const which = state.profile;
    const bounds = fam.bounds(mle);
    const rangeIdx = which === "p1" ? 0 : 1;
    const [a, b] = bounds[rangeIdx];
    const pts = [];
    for (let i = 0; i <= 160; i += 1) {
      const v = a + ((b - a) * i) / 160;
      const val = which === "p1"
        ? logLik(xs, fam, v, state.p2)
        : logLik(xs, fam, state.p1, v);
      if (Number.isFinite(val)) pts.push([v, val]);
    }
    const cur = which === "p1" ? state.p1 : state.p2;
    const best = which === "p1" ? mle[0] : mle[1];
    const bestVal = which === "p1"
      ? logLik(xs, fam, best, state.p2)
      : logLik(xs, fam, state.p1, best);
    C.lines($("#an-ll"), {
      series: [{ points: pts, color: GREEN, width: 2.6, label: `L(${which === "p1" ? fam.p1() : fam.p2()})`, area: true }],
      area: true,
      markers: [
        { x: cur, y: ll, color: RUST, label: t("an_marker_current") },
        { x: best, y: bestVal, color: INK, label: t("an_marker_mle"), dash: "3 3" },
      ],
      xLabel: which === "p1" ? fam.p1() : fam.p2(),
      yLabel: t("an_card_ll"),
    });

    const ks = ksDistance(xs, fam, state.p1, state.p2);
    const aic = Number.isFinite(ll) ? 2 * 2 - 2 * ll : null;
    const rows = [
      [t("an_ll_current"), num(ll, 2)],
      [`${t("an_mle")}: ${fam.p1()}`, num(mle[0], 4)],
      [`${t("an_mle")}: ${fam.p2()}`, num(mle[1], 4)],
      [`${t("an_ll_at_mle")}`, num(llMle, 2)],
      [`${t("an_population")}: ${fam.p1()}`, num(popFit[0], 4)],
      [`${t("an_population")}: ${fam.p2()}`, num(popFit[1], 4)],
      [t("an_aic"), num(aic, 2)],
      [t("an_ks"), num(ks, 4)],
      [t("an_pop_size"), String(pop.length)],
    ];
    $("#an-metrics").innerHTML = rows
      .map(([k, v]) => `<div class="metric-row"><span>${k}</span><b>${v}</b></div>`)
      .join("");

    const hint = $("#an-fit-hint");
    if (hint) {
      const gap = Number.isFinite(ll) && Number.isFinite(llMle) ? llMle - ll : null;
      // Пока ползунки стоят в МП-оценке, подсказке нечего сообщать.
      hint.textContent = gap === null || Math.abs(gap) < 0.01
        ? ""
        : t("an_fit_hint", { gap: num(gap, 2) });
    }
  }

  function fieldLabel() {
    const f = (state.data.fields || []).find((x) => x.id === state.field);
    return f ? fieldName(f) : state.field;
  }

  /* ------------------------------------------------- срезы портфеля */
  function currentGroup() {
    const d = state.data;
    if (state.group === "cgr") return d.by_cgr || [];
    if (state.group === "age") return d.by_age || [];
    if (state.group === "gender") return d.by_gender || [];
    return d.by_territory || [];
  }

  function renderSlices() {
    const items = currentGroup();
    const host = $("#an-bars");
    if (!items.length) { host.innerHTML = `<p class="muted small">${t("an_no_data")}</p>`; return; }

    if (state.metric === "ratio") {
      C.bars(host, {
        items: items.map((i) => ({ label: i.label, value: i.ratio })),
        series: [{ key: "value", label: t("an_metric_ratio"), color: SAND }],
        yLabel: t("an_metric_ratio"),
      });
    } else if (state.metric === "count") {
      C.bars(host, {
        items: items.map((i) => ({ label: i.label, value: i.n })),
        series: [{ key: "value", label: t("an_metric_count"), color: BLUE }],
        yLabel: t("an_metric_count"),
      });
    } else {
      C.bars(host, {
        items: items.map((i) => ({ label: i.label, selected: i.selected, indicated: i.indicated })),
        series: [
          { key: "selected", label: t("an_sel"), color: GREEN },
          { key: "indicated", label: t("an_ind"), color: SAND },
        ],
        yLabel: t("an_money"),
      });
    }

    const head = `<tr><th>${t("an_table_group")}</th><th>${t("an_table_n")}</th>` +
      `<th>${t("an_sel")}</th><th>${t("an_ind")}</th><th>${t("an_metric_ratio")}</th></tr>`;
    const body = items.map((i) => (
      `<tr><td>${i.label}</td><td>${i.n}</td><td>${num(i.selected)}</td>` +
      `<td>${num(i.indicated)}</td><td>${i.ratio === null || i.ratio === undefined ? "—" : num(i.ratio, 3)}</td></tr>`
    )).join("");
    $("#an-slice-table").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;

    const sc = state.data.scatter || [];
    const tr = state.data.scatter_trend || {};
    C.scatter($("#an-scatter"), {
      points: sc,
      xLabel: t("an_group_age"),
      yLabel: t("an_sel"),
      color: GREEN,
      trend: Number.isFinite(tr.a) && Number.isFinite(tr.b) ? [tr.a, tr.b] : null,
      trendColor: RUST,
    });
    const note = $("#an-scatter-note");
    if (note) {
      note.textContent = Number.isFinite(tr.b)
        ? t("an_trend", { b: num(tr.b, 3), r2: tr.r2 === null || tr.r2 === undefined ? "—" : num(tr.r2, 3), n: tr.n })
        : "";
    }
  }

  /* ------------------------------------------ чувствительность тарифа */
  function sensitivity(base, expShare, cgrShift) {
    const d = state.data;
    const sel = d.samples.selected || [];
    const ind = d.samples.indicated || [];
    const fix = d.samples.fixed || [];
    let sumNew = 0;
    let sumInd = 0;
    let sumSel = 0;
    let below = 0;
    const changes = [];
    for (let i = 0; i < ind.length; i += 1) {
      const indicated = ind[i] || 0;
      const fixed = fix[i] || 0;
      const nw = base * indicated * (1 + cgrShift) + expShare * fixed;
      sumNew += nw;
      sumInd += indicated;
      sumSel += sel[i] || 0;
      if (nw < indicated) below += 1;
      if (sel[i]) changes.push((nw - sel[i]) / sel[i] * 100);
    }
    return {
      n: ind.length,
      sumNew, sumInd, sumSel, below, changes,
      balance: sumNew - sumInd,
      balanceRel: sumInd ? (sumNew - sumInd) / sumInd : null,
      vsCurrent: sumSel ? (sumNew - sumSel) / sumSel : null,
      belowShare: ind.length ? below / ind.length : 0,
    };
  }

  function renderSens() {
    if (!state.data.samples || !(state.data.samples.indicated || []).length) {
      $("#an-sens-curve").innerHTML = `<p class="muted small">${t("an_no_data")}</p>`;
      return;
    }
    const r = sensitivity(state.base, state.expShare, state.cgrShift);

    $("#an-base-val").textContent = num(state.base, 3);
    $("#an-exp-val").textContent = `${num(state.expShare * 100, 0)} %`;
    $("#an-cgr-val").textContent = `${state.cgrShift >= 0 ? "+" : ""}${num(state.cgrShift * 100, 1)} %`;

    const rows = [
      [t("an_sens_total"), num(r.sumNew, 0)],
      [t("an_sens_change"), r.vsCurrent === null ? "—" : `${r.vsCurrent >= 0 ? "+" : ""}${num(r.vsCurrent * 100, 2)} %`],
      [t("an_sens_balance"), num(r.balance, 0)],
      [t("an_sens_balance_rel"), r.balanceRel === null ? "—" : `${r.balanceRel >= 0 ? "+" : ""}${num(r.balanceRel * 100, 2)} %`],
      [t("an_sens_negative"), `${num(r.belowShare * 100, 1)} %`],
      [t("an_table_n"), String(r.n)],
    ];
    $("#an-sens-metrics").innerHTML = rows
      .map(([k, v]) => `<div class="metric-row"><span>${k}</span><b>${v}</b></div>`)
      .join("");

    const pts = [];
    const zero = [];
    for (let i = 0; i <= 60; i += 1) {
      const k = 0.8 + (0.4 * i) / 60;
      const s = sensitivity(k, state.expShare, state.cgrShift);
      pts.push([k, s.sumNew]);
      zero.push([k, s.sumInd]);
    }
    C.lines($("#an-sens-curve"), {
      series: [
        { points: pts, color: GREEN, width: 2.6, label: t("an_sens_total") },
        { points: zero, color: BLUE, width: 2, dash: "6 4", label: t("an_sens_indicated_sum") },
      ],
      markers: [{ x: state.base, y: r.sumNew, color: RUST, label: t("an_marker_current") }],
      xLabel: t("an_sens_x"),
      yLabel: t("an_money"),
    });

    C.histogram($("#an-sens-hist"), {
      values: r.changes,
      bins: 26,
      xLabel: t("an_sens_hist_x"),
      yLabel: t("an_hist_y"),
      markers: [{ x: 0, color: INK }],
    });
  }

  /* -------------------------------------------------------- события */
  function bind() {
    const panel = $("#tab-analysis");
    if (!panel) return;
    readPalette();

    $$("#analysis-subtabs .tab").forEach((b) => {
      b.addEventListener("click", () => { state.view = b.dataset.an; render(); });
    });

    const on = (sel, ev, fn) => {
      const el = $(sel);
      if (el) el.addEventListener(ev, fn);
    };

    on("#an-field", "change", (e) => {
      state.field = e.target.value;
      resample(true);
      render();
    });
    on("#an-family", "change", (e) => {
      state.family = e.target.value;
      resample(true);
      render();
    });
    on("#an-profile", "change", (e) => { state.profile = e.target.value; render(); });
    on("#an-n", "input", (e) => {
      state.n = Number(e.target.value);
      $("#an-n-val").textContent = String(state.n);
      resample(true);
      render();
    });
    on("#an-p1", "input", (e) => { state.p1 = Number(e.target.value); render(); });
    on("#an-p2", "input", (e) => { state.p2 = Number(e.target.value); render(); });
    on("#an-resample", "click", () => { resample(false); render(); });
    on("#an-reset", "click", () => { resetToMle(); render(); });

    on("#an-group", "change", (e) => { state.group = e.target.value; render(); });
    on("#an-metric", "change", (e) => { state.metric = e.target.value; render(); });

    on("#an-base", "input", (e) => { state.base = Number(e.target.value); render(); });
    on("#an-exp", "input", (e) => { state.expShare = Number(e.target.value); render(); });
    on("#an-cgr-shift", "input", (e) => { state.cgrShift = Number(e.target.value); render(); });
    on("#an-sens-reset", "click", () => {
      state.base = 1; state.expShare = 0; state.cgrShift = 0;
      $("#an-base").value = "1";
      $("#an-exp").value = "0";
      $("#an-cgr-shift").value = "0";
      render();
    });

    // Вкладка открывается тем же обработчиком, что и остальные; здесь
    // только подгружаем данные при первом заходе.
    $$('.tabs > .tab[data-tab="analysis"]').forEach((b) => {
      b.addEventListener("click", () => { ensureData(); });
    });

    ["#lang-app", "#lang-auth"].forEach((sel) => {
      const el = $(sel);
      if (el) el.addEventListener("change", () => { if (state.data) render(); });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
