/* Вкладка «Анализ» кабинета андеррайтера.
 *
 * Смысл вкладки в том, чтобы порог был не строчкой в регламенте,
 * а величиной, у которой видна цена: сдвинули — и сразу понятно,
 * сколько дел уходит на ручной разбор, сколько премии остаётся
 * в портфеле и какая доля сигналов мошенничества попадает
 * под отказ. Всё считается на странице, без обращений к серверу.
 */
(() => {
  const I = window.UnderwriterI18n || window.UwI18n;
  const C = window.IInsCharts;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const t = (k, v) => (I && I.t ? I.t(k, v) : k);

  // Цвета берём из темы кабинета, чтобы графики не выпадали из оформления.
  let INK = "#14333a";
  let GREEN = "#0f766e";
  let RUST = "#b91c1c";
  let BLUE = "#2563eb";
  let SAND = "#c2410c";

  function readPalette() {
    const cs = getComputedStyle(document.documentElement);
    const v = (name, fb) => (cs.getPropertyValue(name) || "").trim() || fb;
    INK = v("--ink", INK);
    GREEN = v("--teal", GREEN);
    RUST = v("--decline", RUST);
    BLUE = v("--sky", BLUE);
    SAND = v("--refer", SAND);
  }

  const state = {
    data: null,
    loading: false,
    view: "threshold",
    refer: 45,
    decline: 75,
    weight: "count",
    bookMetric: "n",
    factorSort: "n",
  };

  const num = (v, d) => C.fmt(v, d);

  async function apiGet(path) {
    const headers = {};
    const token = localStorage.getItem("uw_token") || "";
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
      if (status) {
        status.textContent = t("an_source", {
          n: (state.data.totals && state.data.totals.n) || 0,
        });
      }
      render();
    } catch (err) {
      if (status) status.textContent = `${t("an_err")}: ${err.message || err}`;
    } finally {
      state.loading = false;
    }
  }

  /* --------------------------------------------------- разбор порога */
  function split(refer, decline) {
    const cases = (state.data && state.data.cases) || [];
    const bands = {
      approve: { n: 0, premium: 0, fraud: 0 },
      refer: { n: 0, premium: 0, fraud: 0 },
      decline: { n: 0, premium: 0, fraud: 0 },
    };
    let fraudTotal = 0;
    cases.forEach((c) => {
      const key = c.risk >= decline ? "decline" : (c.risk >= refer ? "refer" : "approve");
      const b = bands[key];
      b.n += 1;
      b.premium += c.premium;
      if (c.fraud) { b.fraud += 1; fraudTotal += 1; }
    });
    const n = cases.length || 1;
    return {
      bands,
      n: cases.length,
      fraudTotal,
      workload: (bands.refer.n + bands.decline.n) / n,
      fraudCaught: fraudTotal ? bands.decline.fraud / fraudTotal : 0,
      fraudSeen: fraudTotal ? (bands.decline.fraud + bands.refer.fraud) / fraudTotal : 0,
      kept: bands.approve.premium + bands.refer.premium,
      lost: bands.decline.premium,
      missed: bands.approve.fraud,
    };
  }

  function liftCurve() {
    const cases = (state.data && state.data.cases) || [];
    if (!cases.length) return [];
    const fraudTotal = cases.filter((c) => c.fraud).length;
    const pts = [];
    for (let tau = 0; tau <= 100; tau += 1) {
      const hit = cases.filter((c) => c.risk >= tau);
      const share = hit.length / cases.length;
      const caught = fraudTotal ? hit.filter((c) => c.fraud).length / fraudTotal : 0;
      pts.push([share, caught]);
    }
    pts.sort((a, b) => a[0] - b[0]);
    return pts;
  }

  /* ------------------------------------------------------ отрисовка */
  function render() {
    if (!state.data) return;
    $$(".an-view").forEach((v) => { v.hidden = v.dataset.view !== state.view; });
    $$("#analysis-subtabs .subtab").forEach((b) => {
      b.classList.toggle("active", b.dataset.an === state.view);
    });
    if (state.view === "threshold") renderThreshold();
    if (state.view === "book") renderBook();
    if (state.view === "factors") renderFactors();
  }

  function renderThreshold() {
    const cases = state.data.cases || [];
    if (!cases.length) {
      $("#an-risk-hist").innerHTML = `<p class="muted small">${t("an_no_data")}</p>`;
      return;
    }
    if (state.refer > state.decline) state.refer = state.decline;
    $("#an-refer-val").textContent = num(state.refer, 0);
    $("#an-decline-val").textContent = num(state.decline, 0);

    C.histogram($("#an-risk-hist"), {
      values: cases.map((c) => c.risk),
      bins: 24,
      xMin: 0,
      xMax: 100,
      xLabel: t("an_risk"),
      yLabel: t("an_hist_y"),
      markers: [
        { x: state.refer, color: BLUE },
        { x: state.decline, color: RUST },
      ],
      legendExtra: [
        { label: t("an_thr_refer"), color: BLUE, dash: "5 4" },
        { label: t("an_thr_decline"), color: RUST, dash: "5 4" },
      ],
    });

    const pts = liftCurve();
    const r = split(state.refer, state.decline);
    const hit = cases.filter((c) => c.risk >= state.decline);
    C.lines($("#an-lift"), {
      series: [
        { points: pts, color: GREEN, width: 2.6, label: t("an_curve_lift"), area: true },
        { points: [[0, 0], [1, 1]], color: INK, width: 1.4, dash: "5 4", label: t("an_curve_random") },
      ],
      area: true,
      markers: [{
        x: cases.length ? hit.length / cases.length : 0,
        y: r.fraudCaught,
        color: RUST,
        label: t("an_marker_current"),
      }],
      xLabel: t("an_curve_x"),
      yLabel: t("an_curve_y"),
      yMin: 0,
      yMax: 1,
    });

    const b = r.bands;
    C.bars($("#an-band-bars"), {
      items: [
        { label: t("an_approve"), n: b.approve.n, premium: b.approve.premium },
        { label: t("an_refer"), n: b.refer.n, premium: b.refer.premium },
        { label: t("an_decline"), n: b.decline.n, premium: b.decline.premium },
      ],
      series: state.weight === "premium"
        ? [{ key: "premium", label: t("an_premium"), color: GREEN }]
        : [{ key: "n", label: t("an_cases"), color: GREEN }],
      yLabel: state.weight === "premium" ? t("an_premium") : t("an_cases"),
    });

    const rows = [
      [t("an_approve"), `${b.approve.n} · ${num(b.approve.premium, 0)}`],
      [t("an_refer"), `${b.refer.n} · ${num(b.refer.premium, 0)}`],
      [t("an_decline"), `${b.decline.n} · ${num(b.decline.premium, 0)}`],
      [t("an_workload"), `${num(r.workload * 100, 1)} %`],
      [t("an_fraud_caught"), `${num(r.fraudCaught * 100, 1)} %`],
      [t("an_fraud_seen"), `${num(r.fraudSeen * 100, 1)} %`],
      [t("an_fraud_missed"), String(r.missed)],
      [t("an_kept"), num(r.kept, 0)],
      [t("an_lost"), num(r.lost, 0)],
    ];
    $("#an-thr-metrics").innerHTML = rows
      .map(([k, v]) => `<div class="metric-row"><span>${k}</span><b>${v}</b></div>`)
      .join("");

    const hint = $("#an-thr-hint");
    if (hint) {
      hint.textContent = t("an_thr_hint", {
        missed: r.missed,
        workload: num(r.workload * 100, 1),
      });
    }
  }

  function renderBook() {
    const d = state.data;
    C.donut($("#an-status-donut"), {
      items: (d.by_status || []).map((s, i) => ({
        label: s.label,
        value: s.n,
        color: [GREEN, BLUE, SAND, RUST, INK][i % 5],
      })),
      totalLabel: t("an_cases"),
    });

    // Считать вместе число дел и средний балл нельзя: у них разный
    // порядок, столбцы перестают быть сравнимыми. Показываем по одному.
    const bookLabel = {
      n: t("an_cases"),
      premium: t("an_premium"),
      avg_risk: t("an_avg_risk"),
    }[state.bookMetric] || t("an_cases");
    C.bars($("#an-line-bars"), {
      items: (d.by_line || []).map((l) => ({
        label: l.label, value: l[state.bookMetric],
      })),
      series: [{ key: "value", label: bookLabel, color: GREEN }],
      yLabel: bookLabel,
    });

    const cases = d.cases || [];
    C.scatter($("#an-risk-premium"), {
      points: cases.map((c) => [c.risk, c.premium]),
      xLabel: t("an_risk"),
      yLabel: t("an_premium"),
      color: GREEN,
      radius: 3,
    });

    const tot = d.totals || {};
    const rows = [
      [t("an_cases"), String(tot.n || 0)],
      [t("an_premium"), num(tot.premium, 0)],
      [t("an_open"), String(tot.open || 0)],
      [t("an_fraud_total"), `${tot.fraud || 0} · ${num((tot.fraud_share || 0) * 100, 1)} %`],
      [t("an_risk_mean"), num((d.risk_summary || {}).mean, 1)],
      [t("an_risk_sd"), num((d.risk_summary || {}).sd, 1)],
      [t("an_premium_median"), num((d.premium_summary || {}).median, 0)],
    ];
    $("#an-book-metrics").innerHTML = rows
      .map(([k, v]) => `<div class="metric-row"><span>${k}</span><b>${v}</b></div>`)
      .join("");
  }

  function renderFactors() {
    const items = (state.data.factors || []).slice();
    if (!items.length) {
      $("#an-factor-bars").innerHTML = `<p class="muted small">${t("an_no_data")}</p>`;
      $("#an-factor-table").innerHTML = "";
      return;
    }
    const key = state.factorSort;
    items.sort((a, b) => (b[key] || 0) - (a[key] || 0));

    C.hbars($("#an-factor-bars"), {
      items: items.map((f) => ({
        label: f.label,
        value: key === "n" ? f.n : (key === "avg_risk" ? f.avg_risk : f.fraud_share * 100),
        color: key === "fraud_share" ? RUST : (key === "avg_risk" ? SAND : GREEN),
        hint: t("an_hint_row", { n: f.n, risk: num(f.avg_risk, 1) }),
      })),
      format: (v) => (key === "n"
        ? num(v, 0)
        : (key === "fraud_share" ? `${num(v, 1)} %` : num(v, 1))),
    });

    const head = `<tr><th>${t("an_factor")}</th><th>${t("an_cases")}</th>` +
      `<th>${t("an_avg_risk")}</th><th>${t("an_avg_premium")}</th><th>${t("an_fraud_share")}</th></tr>`;
    const body = items.map((f) => (
      `<tr><td>${f.label}</td><td>${f.n}</td><td>${num(f.avg_risk, 1)}</td>` +
      `<td>${num(f.avg_premium, 0)}</td><td>${num(f.fraud_share * 100, 1)} %</td></tr>`
    )).join("");
    $("#an-factor-table").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  }

  /* -------------------------------------------------------- события */
  function bind() {
    if (!$("#tab-analysis")) return;
    readPalette();

    $$("#analysis-subtabs .subtab").forEach((b) => {
      b.addEventListener("click", () => { state.view = b.dataset.an; render(); });
    });

    const on = (sel, ev, fn) => {
      const el = $(sel);
      if (el) el.addEventListener(ev, fn);
    };

    on("#an-refer", "input", (e) => {
      state.refer = Number(e.target.value);
      if (state.refer > state.decline) {
        state.decline = state.refer;
        const d = $("#an-decline");
        if (d) d.value = String(state.decline);
      }
      render();
    });
    on("#an-decline", "input", (e) => {
      state.decline = Number(e.target.value);
      if (state.decline < state.refer) {
        state.refer = state.decline;
        const r = $("#an-refer");
        if (r) r.value = String(state.refer);
      }
      render();
    });
    on("#an-thr-reset", "click", () => {
      state.refer = 45;
      state.decline = 75;
      const r = $("#an-refer");
      const d = $("#an-decline");
      if (r) r.value = "45";
      if (d) d.value = "75";
      render();
    });
    on("#an-weight", "change", (e) => { state.weight = e.target.value; render(); });
    on("#an-book-metric", "change", (e) => { state.bookMetric = e.target.value; render(); });
    on("#an-factor-sort", "change", (e) => { state.factorSort = e.target.value; render(); });

    // Общий переключатель вкладок снимает класс active со всех .tab,
    // поэтому после его работы перерисовываем свою подсветку сами.
    $$('.tabs > .tab[data-tab="analysis"]').forEach((b) => {
      b.addEventListener("click", () => { ensureData(); render(); });
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
