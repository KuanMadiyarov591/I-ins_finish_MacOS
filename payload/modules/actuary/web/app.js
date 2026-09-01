(() => {
  const I = window.ActuaryI18n;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const state = {
    token: localStorage.getItem("ad_token") || "",
    user: null,
    premiums: [],
    assumptions: null,
    runs: null,
    options: null,
    lastReco: null,
    ragHistory: [],
    dash: null,
    ragOllamaReady: null,
  };

  const t = (k, vars) => I.t(k, vars);

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function localeTag() {
    const lang = I.getLang();
    if (lang === "en") return "en-US";
    if (lang === "kk") return "kk-KZ";
    return "ru-RU";
  }

  function money(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString(localeTag(), {
      maximumFractionDigits: 2,
    });
  }

  function userLabel(user) {
    if (!user) return "";
    if (user.role === "actuary") return t("role_actuary");
    if (user.role === "admin") return t("role_admin");
    return user.full_name || user.username || "";
  }

  function modelLabel(name) {
    return name === "selected_premium" ? t("model_selected_premium") : name;
  }

  function estimatorLabel(name) {
    return name === "HistGradientBoostingRegressor" ? t("estimator_hist_gradient_boosting") : name;
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      state.token = "";
      localStorage.removeItem("ad_token");
      showApp(false);
      throw new Error(t("err_session"));
    }
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail) || t("err_generic"));
    }
    return data;
  }

  async function apiBlob(path) {
    const headers = {};
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(path, { headers });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch { /* Non-JSON response. */ }
      throw new Error(detail || t("err_generic"));
    }
    return res.blob();
  }

  function showApp(on) {
    $("#auth").hidden = on;
    $("#app").hidden = !on;
  }

  function setTab(name) {
    $$(".tabs > .tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $$(".tab-panel").forEach((p) => {
      p.hidden = p.id !== `tab-${name}`;
    });
    if (name === "programs") renderPrograms();
    if (name === "assumptions") loadAssumptions();
    if (name === "runs") loadRuns();
    if (name === "recommend") {
      ensureRecoOptions().then(() => {
        if (state.lastReco) renderReco(state.lastReco);
      });
    }
    if (name === "reports") loadReportKinds();
    if (name === "aihub") {
      renderRagThread();
      refreshRagStatus();
    }
  }

  // ------------------------------------------------------------ отчёты
  async function loadReportKinds() {
    const sel = $("#rep-kind");
    if (!sel) return;
    try {
      const data = await api("/api/report/kinds");
      state.reportKinds = data.kinds || [];
      sel.innerHTML = state.reportKinds
        .map((k) => `<option value="${esc(k.id)}">${esc(k.title)}</option>`)
        .join("");
      paintReportDesc();
      renderRecentReports(data.recent || []);
    } catch (err) {
      $("#rep-status").textContent = String(err.message || err);
    }
  }

  function paintReportDesc() {
    const sel = $("#rep-kind");
    const box = $("#rep-desc");
    if (!sel || !box) return;
    const kind = (state.reportKinds || []).find((k) => k.id === sel.value);
    box.textContent = kind ? kind.description : "";
  }

  function renderRecentReports(items) {
    const box = $("#rep-recent");
    if (!box) return;
    if (!items.length) {
      box.textContent = t("rep_none");
      return;
    }
    box.innerHTML = items
      .map(
        (r) =>
          `<div class="row" style="justify-content:space-between;padding:4px 0">
             <span>${esc(r.created_at)} · ${esc(r.kind)} · ${Math.round(r.bytes / 1024)} КБ</span>
             <a class="btn ghost" href="${esc(r.pdf_url)}" target="_blank" rel="noopener">${esc(t("rep_open"))}</a>
           </div>`
      )
      .join("");
  }

  function renderReport(res) {
    const box = $("#rep-result");
    if (!box) return;
    const tables = (res.sections || [])
      .map((s) => {
        const rows = s.table
          ? `<table class="grid"><thead><tr>${s.table.columns
              .map((c) => `<th>${esc(c)}</th>`)
              .join("")}</tr></thead><tbody>${s.table.rows
              .map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`)
              .join("")}</tbody></table>`
          : "";
        const notes = (s.paragraphs || []).map((p) => `<p class="muted small">${esc(p)}</p>`).join("");
        return `<h4>${esc(s.heading)}</h4>${notes}${rows}`;
      })
      .join("");
    const interpretation = (res.interpretation || "")
      .split(/\n\s*\n/)
      .filter((p) => p.trim())
      .map((p) => `<p>${esc(p.trim())}</p>`)
      .join("");
    box.innerHTML = `
      <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:8px">
        <strong>${esc(res.title)}</strong>
        <a class="btn primary" href="${esc(res.pdf_url)}" target="_blank" rel="noopener">${esc(t("rep_pdf"))}</a>
      </div>
      <p class="muted small">${esc(t("rep_by"))}: ${esc(res.lm_model || "—")} · ${esc(res.lm_mode || "—")} · ${esc(res.created_at)}</p>
      ${tables}
      <h4>${esc(t("rep_interpretation"))}</h4>
      ${interpretation || `<p class="muted small">${esc(t("rep_no_text"))}</p>`}`;
  }

  async function buildReport() {
    const btn = $("#rep-build");
    const status = $("#rep-status");
    if (!btn) return;
    btn.disabled = true;
    status.textContent = t("rep_working");
    try {
      const res = await api("/api/report/build", {
        method: "POST",
        body: JSON.stringify({ kind: $("#rep-kind").value, mode: $("#rep-mode").value }),
      });
      renderReport(res);
      status.textContent = t("rep_done");
      const recent = await api("/api/report/recent");
      renderRecentReports(recent.recent || []);
    } catch (err) {
      status.textContent = String(err.message || err);
    } finally {
      btn.disabled = false;
    }
  }

  function applyI18nAndRerender() {
    I.applyDom();
    document.title = t("brand");
    if (state.user) $("#user-chip").textContent = userLabel(state.user);
    const modeSel = $("#rag-mode");
    if (modeSel) modeSel.setAttribute("aria-label", t("rag_mode_aria"));
    if (state.dash) renderDashboard(state.dash);
    renderPrograms();
    if (state.assumptions) renderAssumptions(state.assumptions);
    if (state.runs) renderRuns(state.runs);
    if (state.lastReco) renderReco(state.lastReco);
    else {
      const tb = $("#reco-table tbody");
      if (tb && !tb.querySelector("tr")) {
        tb.innerHTML = `<tr><td colspan="3" class="muted">${esc(t("reco_empty"))}</td></tr>`;
      }
      const fw = $("#reco-factors-wrap");
      if (fw) fw.hidden = true;
    }
    renderRagThread();
    paintRagOllamaBadge();
  }

  async function loadDashboard() {
    state.dash = await api("/api/dashboard/summary");
    renderDashboard(state.dash);
  }

  function renderDashboard(d) {
    const k = d.kpis || {};
    const cards = [
      [t("kpi_n"), k.n_premiums_sample ?? "—"],
      [t("kpi_mae"), k.mae != null ? k.mae : "—"],
      [t("kpi_r2"), k.r2 != null ? k.r2 : "—"],
      [t("kpi_terr"), k.territories_count ?? "—"],
      [t("kpi_cgr"), k.cgr_count ?? "—"],
    ];
    $("#action-kpi").innerHTML = cards
      .map(
        ([label, val]) =>
          `<div class="kpi-card"><div class="k">${esc(label)}</div><div class="v">${esc(val)}</div></div>`
      )
      .join("");

    $("#model-meta").innerHTML = [
      `${esc(t("dash_ready"))}: <b>${esc(d.model_ready ? t("dash_yes") : t("dash_no"))}</b>`,
      k.model_name ? `${esc(t("dash_estimator"))}: ${esc(k.model_name)}` : "",
      k.train_rows != null ? `${esc(t("dash_train_rows"))}: ${esc(k.train_rows)}` : "",
    ]
      .filter(Boolean)
      .join("<br/>");

    $("#avg-meta").innerHTML = [
      `${esc(t("dash_selected"))}: ${money(k.avg_selected_premium)}`,
      `${esc(t("dash_indicated"))}: ${money(k.avg_indicated_premium)}`,
      `${esc(t("dash_cgr_defs"))}: ${esc(k.cgr_definitions)} · ${esc(t("dash_terr_defs"))}: ${esc(k.territory_definitions)}`,
    ].join("<br/>");
  }

  async function loadPremiums() {
    const q = ($("#global-search")?.value || "").trim();
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    const data = await api(`/api/premiums${qs}`);
    state.premiums = data.items || [];
    renderPrograms();
  }

  function renderPrograms() {
    const tb = $("#programs-table tbody");
    if (!tb) return;
    const rows = state.premiums || [];
    if (!rows.length) {
      tb.innerHTML = `<tr><td colspan="10" class="muted">—</td></tr>`;
      return;
    }
    tb.innerHTML = rows
      .map(
        (c) => `<tr>
        <td>${esc(c.external_id || c.id)}</td>
        <td>${esc(c.territory)}</td>
        <td>${esc(genderLabel(c.gender))}</td>
        <td>${esc(c.age)}</td>
        <td>${esc(c.ypc)}</td>
        <td>${esc(c.cgr)}</td>
        <td>${money(c.indicated_premium)}</td>
        <td>${money(c.selected_premium)}</td>
        <td>${money(c.fixed_expenses)}</td>
        <td>${money(c.gap)}</td>
      </tr>`
      )
      .join("");
  }

  async function loadAssumptions() {
    state.assumptions = await api("/api/assumptions");
    renderAssumptions(state.assumptions);
  }

  function renderAssumptions(a) {
    const cgrTb = $("#cgr-table tbody");
    const terrTb = $("#terr-table tbody");
    if (cgrTb) {
      cgrTb.innerHTML = (a.cgr_definitions || [])
        .map(
          (r) => `<tr>
          <td>${esc(r.cgr)}</td><td>${esc(r.aa)}</td><td>${esc(r.bb)}</td><td>${esc(r.cc)}</td>
          <td>${esc(r.va)}</td><td>${esc(r.dd)}</td><td>${esc(r.hh)}</td><td>${esc(r.ss)}</td>
        </tr>`
        )
        .join("");
    }
    if (terrTb) {
      terrTb.innerHTML = (a.territory_definitions || [])
        .map(
          (r) => `<tr>
          <td>${esc(r.county)}</td><td>${esc(r.county_code)}</td><td>${esc(r.territory)}</td>
          <td>${esc(r.zipcode)}</td><td>${esc(r.town)}</td><td>${esc(r.area)}</td>
        </tr>`
        )
        .join("");
    }
  }

  function setAssumptionsSub(name) {
    $$("#assumptions-subtabs .tab").forEach((b) => b.classList.toggle("active", b.dataset.sub === name));
    $("#assumptions-cgr").hidden = name !== "cgr";
    $("#assumptions-terr").hidden = name !== "terr";
  }

  async function loadRuns() {
    state.runs = await api("/api/runs/status");
    renderRuns(state.runs);
  }

  function renderRuns(r) {
    const ready = !!r.model_ready;
    $("#runs-status").textContent = ready ? "" : t("runs_missing");
    const board = r.leaderboard || (r.metrics && (r.metrics.models || r.metrics.leaderboard)) || [];
    const tb = $("#runs-table tbody");
    if (!tb) return;
    if (!board.length) {
      tb.innerHTML = `<tr><td colspan="6" class="muted">—</td></tr>`;
      return;
    }
    tb.innerHTML = board
      .map(
        (m) => `<tr>
        <td>${esc(modelLabel(m.name))}</td>
        <td>${esc(estimatorLabel(m.estimator) || "—")}</td>
        <td>${esc(m.n_rows)}</td>
        <td>${esc(m.mae)}</td>
        <td>${esc(m.r2)}</td>
        <td class="small">${esc((m.features || []).map(featureLabel).join(", "))}</td>
      </tr>`
      )
      .join("");
  }

  async function ensureRecoOptions() {
    if (state.options) return state.options;
    state.options = await api("/api/recommend/options");
    const terrSel = $("#reco-territory");
    const cgrSel = $("#reco-cgr");
    if (terrSel) {
      terrSel.innerHTML = (state.options.territories || [])
        .map((x) => `<option value="${esc(x)}">${esc(x)}</option>`)
        .join("");
    }
    if (cgrSel) {
      cgrSel.innerHTML = (state.options.cgrs || [])
        .map((x) => `<option value="${esc(x)}">${esc(x)}</option>`)
        .join("");
    }
    const genders = state.options.genders || ["M", "F"];
    const gSel = $("#reco-gender");
    if (gSel && genders.length) {
      gSel.innerHTML = genders.map((x) => `<option value="${esc(x)}">${esc(genderLabel(x))}</option>`).join("");
    }
    return state.options;
  }

  const FEATURE_LABEL_KEYS = {
    estimator: "factor_label_estimator",
    pred: "factor_label_pred",
    predicted: "factor_label_pred",
    selected_premium: "factor_label_pred",
    indicated: "factor_label_indicated",
    indicated_premium: "factor_label_indicated",
    gap: "factor_label_gap",
    age: "factor_label_age",
    ypc: "factor_label_ypc",
    fixed_expenses: "factor_label_fixed_expenses",
    territory: "factor_label_territory",
    gender: "factor_label_gender",
    cgr: "factor_label_cgr",
    leakage: "factor_label_leakage",
    current_premium: "factor_label_leakage",
  };

  function genderLabel(value) {
    const code = String(value || "").trim().toUpperCase();
    if (code === "F") return t("gender_female");
    if (code === "M") return t("gender_male");
    return value == null || value === "" ? "—" : String(value);
  }

  function featureLabel(name) {
    const key = FEATURE_LABEL_KEYS[String(name || "").toLowerCase()];
    return key ? t(key) : String(name || "—");
  }

  function factorRow(f) {
    if (!f || typeof f !== "object" || !f.code) {
      if (typeof f === "string" && (/^[\w.]+=/.test(f) || /^[A-Za-z0-9_./+-]+$/.test(f))) {
        const eq = f.indexOf("=");
        if (eq > 0) return { label: featureLabel(f.slice(0, eq)), value: f.slice(eq + 1) };
        return { label: f, value: "—" };
      }
      return null;
    }
    const p = f.params || {};
    switch (f.code) {
      case "factor_estimator":
        return { label: t("factor_label_estimator"), value: estimatorLabel(p.name) ?? "—" };
      case "factor_pred_selected":
        return { label: t("factor_label_pred"), value: p.value != null ? money(p.value) : "—" };
      case "factor_indicated":
        return { label: t("factor_label_indicated"), value: p.value != null ? money(p.value) : "—" };
      case "factor_gap": {
        const n = Number(p.value);
        return {
          label: t("factor_label_gap"),
          value: p.value != null ? money(p.value) : "—",
          gapClass: Number.isFinite(n) ? (n >= 0 ? "is-pos" : "is-neg") : "",
        };
      }
      case "factor_feature":
        return {
          label: featureLabel(p.name),
          value: p.name === "gender"
            ? genderLabel(p.value)
            : (p.value != null && p.value !== "" ? String(p.value) : "—"),
          tech: p.name,
        };
      case "factor_leakage_excluded":
        return {
          label: t("factor_label_leakage"),
          value: p.name === "current_premium" ? t("field_current_premium") : (p.name != null ? String(p.name) : "—"),
        };
      case "factor_no_model":
        return { label: t("factor_label_status"), value: t("factor_no_model") };
      case "factor_heuristic":
        return { label: t("factor_label_method"), value: t("factor_heuristic") };
      default:
        return { label: f.code, value: t(f.code, p) };
    }
  }

  let recoToastTimer = null;

  function setRecoToast(msg, kind) {
    const el = $("#reco-toast");
    if (!el) return;
    if (recoToastTimer) {
      clearTimeout(recoToastTimer);
      recoToastTimer = null;
    }
    el.classList.remove("is-ok", "is-error", "is-flash");
    el.textContent = msg || "";
    if (!msg) return;
    if (kind === "ok") {
      el.classList.add("is-ok", "is-flash");
      recoToastTimer = setTimeout(() => {
        el.textContent = "";
        el.classList.remove("is-ok", "is-flash");
        recoToastTimer = null;
      }, 1400);
    } else if (kind === "error") {
      el.classList.add("is-error");
    }
  }

  function renderReco(payload) {
    const rows = payload.rows || payload.results || [];
    const tb = $("#reco-table tbody");
    const factorsWrap = $("#reco-factors-wrap");
    const factorsTb = $("#reco-factors-table tbody");
    if (!tb) return;

    if (!rows.length) {
      tb.innerHTML = `<tr><td colspan="3" class="muted">${esc(t("reco_empty"))}</td></tr>`;
      if (factorsWrap) factorsWrap.hidden = true;
      if (factorsTb) factorsTb.innerHTML = "";
      return;
    }

    // Primary metrics: one summary row (first result)
    const r = rows[0];
    const gapN = Number(r.gap);
    const gapClass = Number.isFinite(gapN) ? (gapN >= 0 ? "is-pos" : "is-neg") : "";
    tb.innerHTML = `<tr>
      <td class="reco-metric">${esc(money(r.predicted_selected_premium))}</td>
      <td class="reco-metric">${esc(money(r.indicated_premium))}</td>
      <td class="reco-metric reco-gap ${gapClass}">${esc(money(r.gap))}</td>
    </tr>`;

    // Factors table: structured Признак | Значение
    const factorRows = (r.factors || []).map(factorRow).filter(Boolean);
    if (factorsTb) {
      factorsTb.innerHTML = factorRows.length
        ? factorRows
            .map((fr) => {
              const valClass = fr.gapClass ? ` class="reco-gap ${fr.gapClass}"` : "";
              const title = fr.tech ? ` title="${esc(fr.tech)}"` : "";
              return `<tr>
                <td class="reco-factor-attr"${title}>${esc(fr.label)}</td>
                <td${valClass}>${esc(fr.value)}</td>
              </tr>`;
            })
            .join("")
        : `<tr><td colspan="2" class="muted">—</td></tr>`;
    }
    if (factorsWrap) factorsWrap.hidden = false;
  }

  async function runRecommend() {
    setRecoToast(t("reco_loading"));
    try {
      await ensureRecoOptions();
      const body = {
        territory: $("#reco-territory").value,
        gender: $("#reco-gender").value,
        cgr: $("#reco-cgr").value,
        age: Number($("#reco-age").value),
        ypc: Number($("#reco-ypc").value),
        indicated_premium: Number($("#reco-indicated").value),
        fixed_expenses: Number($("#reco-fixed").value),
      };
      const res = await api("/api/recommend/profile", { method: "POST", body: JSON.stringify(body) });
      state.lastReco = res;
      renderReco(res);
      setRecoToast(t("reco_ok"), "ok");
    } catch (err) {
      setRecoToast(String(err.message || err || t("err_generic")), "error");
    }
  }

  function paintRagOllamaBadge() {
    const el = $("#rag-ollama");
    if (!el) return;
    if (state.ragOllamaReady == null) {
      el.textContent = t("rag_offline");
      el.classList.add("is-down");
      el.classList.remove("is-up");
      return;
    }
    el.textContent = state.ragOllamaReady ? t("rag_ollama_ready") : t("rag_ollama_down");
    el.classList.toggle("is-down", !state.ragOllamaReady);
    el.classList.toggle("is-up", !!state.ragOllamaReady);
  }

  function renderRagThread() {
    const box = $("#rag-thread");
    if (!box) return;
    if (!state.ragHistory.length) {
      box.innerHTML = `<div class="muted small">${esc(t("rag_greeting"))}</div>`;
      return;
    }
    box.innerHTML = state.ragHistory
      .map((m) => {
        const sources = Array.isArray(m.sources) ? m.sources : [];
        const sourcesHtml = sources.length
          ? `<div class="rag-sources">
              <div class="rag-sources-title">${esc(t("rag_sources"))}</div>
              ${sources.map((source, index) => `
                <button class="rag-source" type="button"
                  data-source="${esc(source.source || "")}" data-page="${esc(source.pageStart || 1)}"
                  data-excerpt="${esc(source.excerpt || "")}" title="${esc(t("rag_open_document"))}">
                  <span class="rag-source-number">${index + 1}</span>
                  <span>${esc(source.citation || source.source || "—")}</span>
                </button>`).join("")}
            </div>`
          : "";
        return `<div class="chat-msg ${m.role}">
        <div class="chat-role">${esc(m.role === "user" ? t("rag_you") : t("rag_bot"))}</div>
        <div class="chat-bubble">${esc(m.text)}</div>
        ${sourcesHtml}
      </div>`;
      })
      .join("");
    box.scrollTop = box.scrollHeight;
  }

  function paintRagModeOptions() {
    const sel = $("#rag-mode");
    if (!sel) return;
    const qwen = sel.querySelector('option[value="ollama"]');
    if (qwen) qwen.disabled = !state.ragOllamaReady;
    const giga = sel.querySelector('option[value="gigachat"]');
    if (giga) giga.disabled = !state.ragGigaReady;
    if (qwen && qwen.disabled && sel.value === "ollama") sel.value = "auto";
    if (giga && giga.disabled && sel.value === "gigachat") sel.value = "auto";
  }

  async function refreshRagStatus() {
    try {
      const st = await api("/api/assistant/rag/status");
      state.ragOllamaReady = !!(st.ollama && st.ollama.model_ready);
      state.ragGigaReady = !!(st.gigachat && st.gigachat.available);
      paintRagOllamaBadge();
      paintRagModeOptions();
    } catch {
      state.ragOllamaReady = false;
      state.ragGigaReady = false;
      paintRagOllamaBadge();
      paintRagModeOptions();
    }
  }

  async function askRag(ev) {
    ev.preventDefault();
    const q = ($("#rag-input").value || "").trim();
    if (!q) return;
    state.ragHistory.push({ role: "user", text: q });
    state.ragHistory.push({ role: "bot", text: t("rag_thinking"), pending: true });
    renderRagThread();
    $("#rag-input").value = "";
    try {
      const res = await api("/api/assistant/ask", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          mode: $("#rag-mode").value || "auto",
          lang: I.getLang(),
        }),
      });
      state.ragHistory = state.ragHistory.filter((m) => !m.pending);
      const uniqueSources = [];
      const seenSources = new Set();
      for (const item of (res.chunks_used || [])) {
        const key = item.citation || `${item.source || ""}:${item.page_start || ""}:${item.page_end || ""}`;
        if (!key || seenSources.has(key)) continue;
        seenSources.add(key);
        uniqueSources.push({
          citation: item.citation,
          source: item.source,
          pageStart: item.page_start,
          pageEnd: item.page_end,
          excerpt: item.excerpt,
        });
      }
      state.ragHistory.push({ role: "bot", text: res.answer || "—", sources: uniqueSources });
    } catch (err) {
      state.ragHistory = state.ragHistory.filter((m) => !m.pending);
      state.ragHistory.push({ role: "bot", text: String(err.message || err || t("err_generic")) });
    }
    renderRagThread();
  }

  let pdfObjectUrl = "";

  function closePdfViewer() {
    const modal = $("#pdf-modal");
    if (modal) modal.hidden = true;
    $("#pdf-frame")?.removeAttribute("src");
    if (pdfObjectUrl) URL.revokeObjectURL(pdfObjectUrl);
    pdfObjectUrl = "";
  }

  async function openPdfViewer(source, page, excerpt) {
    if (!source) return;
    const modal = $("#pdf-modal");
    const frame = $("#pdf-frame");
    if (!modal || !frame) return;
    $("#pdf-title").textContent = `${source} · ${t("rag_open_document")}`;
    $("#pdf-match").textContent = excerpt || "—";
    modal.hidden = false;
    frame.removeAttribute("src");
    try {
      const blob = await apiBlob(`/api/assistant/rag/document/${encodeURIComponent(source)}`);
      if (pdfObjectUrl) URL.revokeObjectURL(pdfObjectUrl);
      pdfObjectUrl = URL.createObjectURL(blob);
      frame.src = `${pdfObjectUrl}#page=${Math.max(1, Number(page) || 1)}&zoom=page-width`;
    } catch (err) {
      closePdfViewer();
      window.alert(String(err.message || err || t("err_generic")));
    }
  }

  function enablePdfWindowDrag() {
    const handle = $("#pdf-drag-handle");
    const win = $("#pdf-modal .pdf-window");
    if (!handle || !win) return;
    handle.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button")) return;
      const rect = win.getBoundingClientRect();
      const dx = event.clientX - rect.left;
      const dy = event.clientY - rect.top;
      handle.setPointerCapture(event.pointerId);
      const move = (e) => {
        win.style.left = `${Math.max(0, Math.min(window.innerWidth - win.offsetWidth, e.clientX - dx))}px`;
        win.style.top = `${Math.max(0, Math.min(window.innerHeight - 48, e.clientY - dy))}px`;
      };
      const stop = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
        handle.removeEventListener("pointercancel", stop);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
      handle.addEventListener("pointercancel", stop);
    });
  }

  async function boot() {
    applyI18nAndRerender();
    if (!state.token) {
      showApp(false);
      return;
    }
    try {
      state.user = await api("/api/auth/me");
      $("#user-chip").textContent = userLabel(state.user);
      showApp(true);
      await loadDashboard();
      await loadPremiums();
    } catch {
      state.token = "";
      localStorage.removeItem("ad_token");
      showApp(false);
    }
  }

  $("#login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    $("#auth-err").hidden = true;
    try {
      const res = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: String(fd.get("username") || ""),
          password: String(fd.get("password") || ""),
        }),
      });
      state.token = res.access_token;
      localStorage.setItem("ad_token", state.token);
      state.user = res.user;
      $("#user-chip").textContent = userLabel(state.user);
      showApp(true);
      await loadDashboard();
      await loadPremiums();
    } catch (err) {
      $("#auth-err").hidden = false;
      $("#auth-err").textContent = String(err.message || err || t("err_generic"));
    }
  });

  $("#btn-logout")?.addEventListener("click", () => {
    state.token = "";
    localStorage.removeItem("ad_token");
    showApp(false);
  });

  $("#rep-build")?.addEventListener("click", buildReport);
  $("#rep-kind")?.addEventListener("change", paintReportDesc);

  $$(".tabs > .tab").forEach((btn) => {
    btn.addEventListener("click", () => setTab(btn.dataset.tab));
  });

  $$("#assumptions-subtabs .tab").forEach((btn) => {
    btn.addEventListener("click", () => setAssumptionsSub(btn.dataset.sub));
  });

  $("#btn-refresh-programs")?.addEventListener("click", () => loadPremiums());
  $("#global-search")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadPremiums();
  });

  $("#reco-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    runRecommend();
  });

  $("#rag-form")?.addEventListener("submit", askRag);
  $("#rag-thread")?.addEventListener("click", (event) => {
    const source = event.target.closest(".rag-source");
    if (source) openPdfViewer(source.dataset.source, source.dataset.page, source.dataset.excerpt);
  });
  $("#pdf-close")?.addEventListener("click", closePdfViewer);
  $("#pdf-modal")?.addEventListener("click", (event) => {
    if (event.target.id === "pdf-modal") closePdfViewer();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#pdf-modal")?.hidden) closePdfViewer();
  });
  enablePdfWindowDrag();

  $("#btn-retrain")?.addEventListener("click", async () => {
    $("#runs-status").textContent = t("runs_retraining");
    try {
      const res = await api("/api/runs/retrain", { method: "POST", body: "{}" });
      state.runs = res.status || (await api("/api/runs/status"));
      renderRuns(state.runs);
      $("#runs-status").textContent = t("runs_done");
      await loadDashboard();
    } catch (err) {
      $("#runs-status").textContent = String(err.message || err || t("err_generic"));
    }
  });

  $("#lang-auth")?.addEventListener("change", (e) => {
    I.setLang(e.target.value);
    applyI18nAndRerender();
  });
  $("#lang-app")?.addEventListener("change", (e) => {
    I.setLang(e.target.value);
    applyI18nAndRerender();
  });

  boot();
})();
