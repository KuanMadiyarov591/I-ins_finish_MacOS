(() => {
  const I = window.UwI18n;
  const t = (k, v) => I.t(k, v);

  const state = {
    token: localStorage.getItem("uw_token") || "",
    user: null,
    cases: [],
    renewals: [],
    selectedId: null,
    statusFilter: "",
    lineFilter: "",
    searchQ: "",
    statusCounts: {},
    dashboard: null,
    ragHistory: [],
    recoCaseId: null,
    lastReco: null,
  };

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const STATUS_LABEL = () => ({
    new: t("status_new"),
    in_review: t("status_in_review"),
    referred: t("status_referred"),
    approved: t("status_approved"),
    declined: t("status_declined"),
  });
  const REC_LABEL = () => ({
    approve: t("rec_approve"),
    refer: t("rec_refer"),
    decline: t("rec_decline"),
  });
  const LINE_LABEL = () => ({
    auto: t("line_auto"),
    fraud: t("line_fraud"),
    motor: t("line_motor"),
  });
  const LINE_LABEL_FULL = () => ({
    auto: t("line_auto_full"),
    fraud: t("line_fraud_full"),
    motor: t("line_motor_full"),
  });

  function money(n) {
    const v = Number(n) || 0;
    const loc = I.getLang() === "en" ? "en-US" : "ru-RU";
    return v.toLocaleString(loc, { maximumFractionDigits: 0 });
  }

  function scoreClass(score) {
    if (score >= 70) return "hi";
    if (score >= 45) return "mid";
    return "";
  }

  function applyI18n() {
    $$("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    $$("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
    });
    const la = $("#lang-auth");
    const lb = $("#lang-app");
    if (la) la.value = I.getLang();
    if (lb) lb.value = I.getLang();
    document.title = t("brand");
  }

  function onLangChange(sel) {
    I.setLang(sel.value);
    applyI18n();
    if (!state.token) return;
    renderStatusKpi();
    renderCasesTable();
    renderRenewalsTable();
    fillRecoCaseSelect();
    if (state.dashboard) renderDashboard();
    if (state.lastReco) {
      renderRecoCards(state.lastReco.recommendations || [], {
        caseId: state.recoCaseId,
        primary: state.lastReco.primary_risk,
      });
    } else {
      const box = $("#reco-out");
      if (box && !$("#reco-out .reco-table")) {
        box.innerHTML = "";
      }
    }
    if (state.selectedId && !$("#tab-detail")?.hidden) {
      openCase(state.selectedId).catch(console.warn);
    }
    renderRagThread();
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      logout(false);
      throw new Error(t("need_login"));
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : res.statusText;
      throw new Error(msg || t("error_generic"));
    }
    return data;
  }

  async function apiBlob(path) {
    const headers = {};
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(path, { headers });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* PDF/non-JSON response. */ }
      throw new Error(detail || "PDF download failed");
    }
    return res.blob();
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
    $("#pdf-title").textContent = source;
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
      window.alert(String(err.message || err));
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

  function showApp(on) {
    $("#auth").hidden = on;
    $("#app").hidden = !on;
  }

  function setTab(name) {
    $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    $$(".tab-panel").forEach((p) => {
      p.hidden = p.id !== `tab-${name}`;
    });
    if (name === "consultant") refreshRagStatus().catch(console.warn);
    if (name === "dashboard") loadDashboard().catch(console.warn);
    if (name === "recommend") {
      fillRecoCaseSelect();
    }
  }

  function logout(clear = true) {
    if (clear) localStorage.removeItem("uw_token");
    state.token = "";
    state.user = null;
    showApp(false);
  }

  function renderStatusKpi() {
    const order = ["new", "in_review", "referred", "approved", "declined"];
    const labels = STATUS_LABEL();
    const box = $("#status-kpi");
    if (!box) return;
    box.innerHTML = order
      .map((k) => {
        const n = state.statusCounts[k] || 0;
        const active = state.statusFilter === k ? "active" : "";
        return `<button type="button" class="stat ${active}" data-status="${k}">
          <div class="n">${n}</div><div class="l">${labels[k] || k}</div>
        </button>`;
      })
      .join("");
    box.querySelectorAll(".stat").forEach((el) => {
      el.addEventListener("click", () => {
        const v = el.dataset.status;
        state.statusFilter = state.statusFilter === v ? "" : v;
        $("#f-status").value = state.statusFilter;
        loadCases();
      });
    });
  }

  function rowHtml(c, { showRenewal = false } = {}) {
    const sc = scoreClass(c.risk_score);
    const lines = LINE_LABEL();
    const statuses = STATUS_LABEL();
    const recs = REC_LABEL();
    return `<tr data-id="${c.id}" class="${c.id === state.selectedId ? "selected" : ""}">
      <td><b>${esc(c.policy_number || c.external_id)}</b></td>
      <td>${esc(c.insured_name || "—")}</td>
      <td><span class="badge line-${esc(c.line)}">${lines[c.line] || c.line}</span></td>
      ${showRenewal ? `<td>${esc(c.renewal_date || "—")}</td>` : ""}
      <td>${money(c.premium)}</td>
      <td><span class="badge st-${esc(c.decision_status)}">${statuses[c.decision_status] || c.decision_status}</span></td>
      <td><span class="score-pill"><span class="score-dot ${sc}"></span>${esc(c.risk_score)}</span></td>
      <td><span class="badge rec-${esc(c.recommendation)}">${recs[c.recommendation] || c.recommendation}</span></td>
      ${showRenewal ? "" : `<td>${esc(c.days_open)}</td>`}
    </tr>`;
  }

  function bindTableRows(tableSel) {
    const table = $(tableSel);
    if (!table) return;
    table.querySelectorAll("tbody tr").forEach((tr) => {
      tr.addEventListener("click", () => openCase(Number(tr.dataset.id)));
    });
  }

  function renderCasesTable() {
    const tbody = $("#cases-table tbody");
    if (!tbody) return;
    if (!state.cases.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">${esc(t("no_cases"))}</td></tr>`;
      return;
    }
    tbody.innerHTML = state.cases.map((c) => rowHtml(c)).join("");
    bindTableRows("#cases-table");
  }

  function renderRenewalsTable() {
    const tbody = $("#renewals-table tbody");
    if (!tbody) return;
    if (!state.renewals.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">${esc(t("no_renewals"))}</td></tr>`;
      return;
    }
    tbody.innerHTML = state.renewals.map((c) => rowHtml(c, { showRenewal: true })).join("");
    bindTableRows("#renewals-table");
  }

  function renderDashboard() {
    const d = state.dashboard;
    if (!d) return;
    const ai = d.action_items || {};
    const book = d.book_of_business || {};
    const w = d.widgets || {};
    const statuses = STATUS_LABEL();
    const lines = LINE_LABEL_FULL();
    const recs = REC_LABEL();

    $("#action-kpi").innerHTML = [
      [t("kpi_up_renewal"), ai.up_for_renewal, ""],
      [t("kpi_lapse"), ai.about_to_lapse, "accent"],
      [t("kpi_opps"), ai.open_opportunities, ""],
      [t("kpi_payment"), ai.payment_due, "accent"],
    ]
      .map(
        ([l, n, cls]) =>
          `<div class="kpi-card ${cls}"><div class="n">${n ?? 0}</div><div class="l">${l}</div></div>`
      )
      .join("");

    $("#book-kpi").innerHTML = [
      [t("kpi_prem_pending"), money(book.premium_pending)],
      [t("kpi_prem_retained"), money(book.premium_retained)],
      [t("kpi_renewal_rate"), `${book.renewal_rate ?? 0}%`],
      [t("kpi_total"), book.total_cases ?? 0],
    ]
      .map(([l, n]) => `<div class="kpi-card"><div class="n">${n}</div><div class="l">${l}</div></div>`)
      .join("");

    const pvr = w.pending_vs_retained || {};
    const maxP = Math.max(pvr.pending || 0, pvr.retained || 0, 1);
    $("#bar-pending-retained").innerHTML = `
      <div class="bar-row">
        <div class="label"><span>${esc(t("bar_pending"))}</span><b>${money(pvr.pending)}</b></div>
        <div class="bar-track"><span style="width:${((pvr.pending || 0) / maxP) * 100}%"></span></div>
      </div>
      <div class="bar-row">
        <div class="label"><span>${esc(t("bar_retained"))}</span><b>${money(pvr.retained)}</b></div>
        <div class="bar-track retained"><span style="width:${((pvr.retained || 0) / maxP) * 100}%"></span></div>
      </div>`;

    const sc = w.policy_by_status || d.status_counts || {};
    const order = ["new", "in_review", "referred", "approved", "declined"];
    const colors = ["#0f766e", "#2563eb", "#c2410c", "#047857", "#b91c1c"];
    const total = order.reduce((s, k) => s + (sc[k] || 0), 0) || 1;
    const pcts = order.map((k) => ((sc[k] || 0) / total) * 100);
    const donut = $("#donut-status");
    donut.innerHTML = `
      <div class="donut" data-total="${order.reduce((s, k) => s + (sc[k] || 0), 0)}"
        style="--p1:${pcts[0]};--p2:${pcts[1]};--p3:${pcts[2]};--p4:${pcts[3]};--p5:${pcts[4]}"></div>
      <div class="legend">
        ${order
          .map(
            (k, i) =>
              `<div><span style="background:${colors[i]}"></span>${statuses[k]} · ${sc[k] || 0}</div>`
          )
          .join("")}
      </div>`;

    $("#risk-widgets").innerHTML = `
      <div class="mini-stat"><span>${esc(t("mini_high_risk"))}</span><b>${w.high_risk_count ?? 0}</b></div>
      <div class="mini-stat"><span>${esc(t("mini_decline"))}</span><b>${w.decline_do_not_renew ?? 0}</b></div>
      <div class="mini-stat"><span>${esc(t("mini_prem_declined"))}</span><b>${money(book.premium_declined)}</b></div>`;

    const ws = w.workstream || [];
    const maxC = Math.max(...ws.map((x) => x.count || 0), 1);
    $("#workstream").innerHTML = ws
      .map(
        (x) => `<div class="ws-row">
          <b>${esc(lines[x.line] || LINE_LABEL()[x.line] || x.line)}</b>
          <div class="ws-bar"><i style="width:${((x.count || 0) / maxC) * 100}%"></i></div>
          <span>${x.count} · ${money(x.premium)}</span>
        </div>`
      )
      .join("");

    const tbody = $("#submissions-table tbody");
    const subs = w.new_submissions || [];
    tbody.innerHTML = subs.length
      ? subs
          .map(
            (s) => `<tr data-id="${s.id}">
              <td><b>${esc(s.policy_number)}</b></td>
              <td>${esc(s.insured_name)}</td>
              <td><span class="badge line-${esc(s.line)}">${esc(LINE_LABEL()[s.line] || s.line)}</span></td>
              <td>${esc(s.days_open)}</td>
              <td>${money(s.premium)}</td>
              <td>${esc(s.risk_score)}</td>
              <td><span class="badge rec-${esc(s.recommendation)}">${esc(recs[s.recommendation] || s.recommendation)}</span></td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="7" class="muted">${esc(t("no_subs"))}</td></tr>`;
    bindTableRows("#submissions-table");
  }

  async function loadDashboard() {
    state.dashboard = await api("/api/dashboard/summary");
    renderDashboard();
  }

  async function loadCases() {
    const qs = new URLSearchParams();
    if (state.statusFilter) qs.set("status", state.statusFilter);
    if (state.lineFilter) qs.set("line", state.lineFilter);
    if (state.searchQ) qs.set("q", state.searchQ);
    const data = await api(`/api/cases?${qs.toString()}`);
    state.cases = data.items || [];
    state.statusCounts = data.status_counts || {};
    renderStatusKpi();
    renderCasesTable();
    fillRecoCaseSelect();
  }

  async function loadRenewals() {
    const qs = new URLSearchParams({ renewals_only: "true" });
    if (state.searchQ) qs.set("q", state.searchQ);
    const data = await api(`/api/cases?${qs.toString()}`);
    state.renewals = data.items || [];
    renderRenewalsTable();
  }

  function fillRecoCaseSelect() {
    const sel = $("#reco-case");
    if (!sel) return;
    const prev = sel.value;
    const pool = [...state.cases];
    if (!pool.length && state.renewals.length) pool.push(...state.renewals);
    const seen = new Set();
    const lines = LINE_LABEL();
    const opts = [`<option value="">${esc(t("reco_pick_case"))}</option>`];
    for (const c of pool) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      const lineLbl = lines[c.line] || c.line;
      const label = `${c.policy_number || c.external_id} · ${c.insured_name || "—"} · ${lineLbl}`;
      opts.push(`<option value="${c.id}">${esc(label)}</option>`);
    }
    sel.innerHTML = opts.join("");
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
    else if (state.selectedId) sel.value = String(state.selectedId);
  }

  function recoCtaLabel(action) {
    if (action === "approve") return t("reco_apply_approve");
    if (action === "refer") return t("reco_apply_refer");
    if (action === "decline") return t("reco_apply_decline");
    return "";
  }

  function recoDecisionTitle(action) {
    if (action === "approve") return t("reco_decision_approve");
    if (action === "refer") return t("reco_decision_refer");
    if (action === "decline") return t("reco_decision_decline");
    return REC_LABEL()[action] || action || "—";
  }

  function recoRowTitle(r) {
    if (r.category === "decision") return recoDecisionTitle(r.action);
    if (r.line) return LINE_LABEL_FULL()[r.line] || LINE_LABEL()[r.line] || r.line;
    if (r.action && ["approve", "refer", "decline"].includes(r.action)) return recoDecisionTitle(r.action);
    return "—";
  }

  function recoMatchKindLabel(r) {
    if (r.match_kind === "probability") return t("reco_prob");
    if (r.match_kind === "confidence") return t("reco_conf");
    return "";
  }

  function stripReasonBoilerplate(raw) {
    let s = String(raw || "").trim();
    if (!s) return "";
    if (/^Модель по цели/i.test(s)) return "";
    if (/^Оценка по признакам/i.test(s)) return "";
    if (/^Цель EDA:/i.test(s)) return "";
    if (/^Вероятность [«"]/i.test(s)) return "";
    if (/^Интегральный риск-скор/i.test(s)) {
      const m = s.match(/:\s*([\d.]+)/);
      return m ? `risk_score = ${m[1]}` : "";
    }
    const feat = s.match(/^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+)$/);
    if (feat) {
      let val = feat[2].trim();
      val = val.replace(/\s*\([^)]*\)\s*$/, "").trim();
      return `${feat[1]} = ${val}`;
    }
    return s;
  }

  function recoReasonsList(r, limit = 3) {
    const cleaned = (r.reasons || [])
      .map(stripReasonBoilerplate)
      .filter(Boolean)
      .slice(0, limit);
    if (!cleaned.length) return "<span class=\"muted\">—</span>";
    return `<ul class="reco-why">${cleaned.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  }

  function recoActionCell(r, caseId) {
    const action = r.action;
    if (!(action && ["approve", "refer", "decline"].includes(action))) return "";
    if (caseId) {
      return `<button type="button" class="btn primary rec-tile-cta" data-reco-action="${esc(action)}" data-reco-case="${esc(caseId)}">${esc(recoCtaLabel(action))}</button>`;
    }
    return `<button type="button" class="btn rec-tile-cta" disabled title="${esc(t("reco_apply_case_only"))}">${esc(t("reco_apply"))}</button>`;
  }

  function recoRowHtml(r, { caseId = null, compact = false } = {}) {
    const title = recoRowTitle(r);
    const kind = recoMatchKindLabel(r);
    const pct = r.match_pct != null ? `${esc(r.match_pct)}%` : "—";
    const pctHtml = `<span>${pct}</span>${kind ? `<small class="reco-pct-kind">${esc(kind)}</small>` : ""}`;
    const factors = recoReasonsList(r, 3);
    if (compact) {
      return `<tr>
        <td class="reco-line-cell">${esc(title)}</td>
        <td class="reco-col-pct">${pctHtml}</td>
        <td>${factors}</td>
      </tr>`;
    }
    const target =
      r.category === "decision" || !r.target ? "—" : `<code>${esc(r.target)}</code>`;
    const actionHtml = recoActionCell(r, caseId);
    return `<tr>
      <td class="reco-line-cell">${esc(title)}</td>
      <td class="reco-target">${target}</td>
      <td class="reco-col-pct">${pctHtml}</td>
      <td>${factors}</td>
      <td class="reco-col-action">${actionHtml}</td>
    </tr>`;
  }

  function renderRecoCards(items, { caseId = null, target = "#reco-out", compact = false, limit = null } = {}) {
    const box = $(target);
    if (!box) return;
    let list = Array.isArray(items) ? items.slice() : [];
    if (limit != null) list = list.slice(0, limit);
    if (!list.length) {
      box.innerHTML = `<p class="muted">${esc(t("reco_none"))}</p>`;
      return;
    }
    const rows = list.map((r) => recoRowHtml(r, { caseId, compact })).join("");
    const tableCls = compact ? "reco-table reco-table-compact" : "reco-table";
    const head = compact
      ? `<thead><tr>
          <th>${esc(t("reco_col_line"))}</th>
          <th class="reco-col-pct">${esc(t("reco_col_pct"))}</th>
          <th>${esc(t("reco_col_factors"))}</th>
        </tr></thead>`
      : `<thead><tr>
          <th>${esc(t("reco_col_line"))}</th>
          <th>${esc(t("reco_col_target"))}</th>
          <th class="reco-col-pct">${esc(t("reco_col_pct"))}</th>
          <th>${esc(t("reco_col_factors"))}</th>
          <th>${esc(t("reco_col_action"))}</th>
        </tr></thead>`;
    box.innerHTML = `<div class="reco-table-wrap"><table class="${tableCls}">${head}<tbody>${rows}</tbody></table></div>`;
    box.querySelectorAll("[data-reco-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = Number(btn.dataset.recoCase);
        const decision = btn.dataset.recoAction;
        if (!id || !decision) return;
        applyRecoDecision(id, decision, btn);
      });
    });
  }

  function setRecoToast(text) {
    const el = $("#reco-toast");
    if (el) el.textContent = text || "";
  }

  async function applyRecoDecision(caseId, decision, btn) {
    if (btn) btn.disabled = true;
    setRecoToast(t("applying"));
    try {
      await api(`/api/cases/${caseId}/decision`, {
        method: "PATCH",
        body: JSON.stringify({ decision, notes: "" }),
      });
      setRecoToast(`${t("applied")}: ${REC_LABEL()[decision] || decision}`);
      await Promise.all([loadCases(), loadRenewals(), loadDashboard()]);
      const onDetail = !$("#tab-detail")?.hidden;
      if (onDetail && state.selectedId === caseId) {
        await openCase(caseId);
        const msg = $("#dec-msg");
        if (msg) msg.textContent = `${t("decision_saved")}: ${REC_LABEL()[decision] || decision}`;
      }
    } catch (e) {
      setRecoToast(e.message || t("apply_error"));
      const msg = $("#dec-msg");
      if (msg) msg.textContent = e.message || t("error_generic");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function openRecommendForCase(caseId) {
    state.selectedId = caseId;
    state.recoCaseId = caseId;
    fillRecoCaseSelect();
    if ($("#reco-case")) $("#reco-case").value = String(caseId);
    setTab("recommend");
    runRecommend();
  }

  async function runRecommend() {
    const box = $("#reco-out");
    const caseId = ($("#reco-case") && $("#reco-case").value) || "";
    box.innerHTML = `<p class="muted">${esc(t("reco_loading"))}</p>`;
    setRecoToast("");
    try {
      let res;
      if (caseId) {
        state.recoCaseId = Number(caseId);
        res = await api(`/api/recommend/case/${caseId}`);
        state.lastReco = res;
        renderRecoCards(res.recommendations || [], {
          caseId: Number(caseId),
          primary: res.primary_risk,
        });
      } else {
        state.recoCaseId = null;
        const body = {
          line: ($("#reco-line") && $("#reco-line").value) || "auto",
          premium: Number(($("#reco-premium") && $("#reco-premium").value) || 0) || null,
          risk_hint: Number(($("#reco-risk-hint") && $("#reco-risk-hint").value) || 0) || null,
        };
        res = await api("/api/recommend/profile", {
          method: "POST",
          body: JSON.stringify(body),
        });
        state.lastReco = res;
        renderRecoCards(res.recommendations || [], {
          caseId: null,
          primary: res.primary_risk,
        });
      }
    } catch (e) {
      box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
    }
  }

  async function openCase(id) {
    state.selectedId = id;
    renderCasesTable();
    renderRenewalsTable();
    setTab("detail");
    const box = $("#case-detail");
    box.classList.remove("empty");
    box.innerHTML = `<p class="muted">${esc(t("loading"))}</p>`;
    try {
      const [c, reco] = await Promise.all([
        api(`/api/cases/${id}`),
        api(`/api/recommend/case/${id}`).catch(() => null),
      ]);
      if (reco) state.lastReco = reco;
      const reasons = (c.key_factors || []).map((r) => `<li>${esc(r)}</li>`).join("") || "<li>—</li>";
      const feats = Object.entries(c.raw_features || {})
        .slice(0, 18)
        .map(([k, v]) => `<div class="feat"><b>${esc(k)}</b>${esc(v)}</div>`)
        .join("");
      const stages = (c.stages || [])
        .map(
          (s) =>
            `<div class="stage ${s.done ? "done" : ""} ${s.active ? "active" : ""}">${esc(s.label)}</div>`
        )
        .join("");
      const recoItems = (reco && reco.recommendations) || [];
      const lines = LINE_LABEL();
      const recs = REC_LABEL();
      const statuses = STATUS_LABEL();

      box.innerHTML = `
        <div class="section-head row">
          <div>
            <h2>${esc(c.insured_name || c.title)}</h2>
            <p class="muted small">${esc(c.policy_number)} · ${esc(lines[c.line] || c.line)} · ${esc(t("renewal_label"))} ${esc(c.renewal_date || "—")}</p>
          </div>
          <button class="btn ghost" type="button" id="btn-back">${esc(t("back_list"))}</button>
        </div>
        <div class="detail-metrics">
          <div class="metric"><div class="k">${esc(t("metric_risk"))}</div><div class="v">${esc(c.risk_score)}</div></div>
          <div class="metric"><div class="k">${esc(t("metric_rec"))}</div><div class="v"><span class="badge rec-${esc(c.recommendation)}">${esc(recs[c.recommendation] || c.recommendation)}</span></div></div>
          <div class="metric"><div class="k">${esc(t("metric_prem"))}</div><div class="v">${money(c.premium)}</div></div>
          <div class="metric"><div class="k">${esc(t("metric_stage"))}</div><div class="v" style="font-size:1rem">${esc(c.stage_label || statuses[c.decision_status])}</div></div>
        </div>
        <div class="chevron-stages">${stages}</div>
        <div class="detail-grid">
          <div>
            <div class="panel-block" style="margin-bottom:14px">
              <h3>${esc(t("policy_details"))}</h3>
              <p>${esc(c.applicant_summary)}</p>
              <div class="meta" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
                ${c.fraud_signal ? `<span class="badge fraud-yes">${esc(t("fraud_badge"))}</span>` : ""}
                ${c.decision_by ? `<span class="badge">${esc(t("decided_by"))}: ${esc(c.decision_by)}</span>` : ""}
                <span class="badge">${esc(t("days_open"))}: ${esc(c.days_open)}</span>
              </div>
            </div>
            <div class="panel-block" style="margin-bottom:14px">
              <h3>${esc(t("risk_factors"))}</h3>
              <div class="feat-grid">${feats || '<span class="muted">—</span>'}</div>
            </div>
            <div class="panel-block">
              <h3>${esc(t("premium_block"))}</h3>
              <p><b>${money(c.premium)}</b> · ${esc(t("line_of"))} ${esc(lines[c.line] || c.line)}</p>
            </div>
          </div>
          <div class="ai-panel">
            <div class="detail-reco">
              <div class="detail-reco-head">
                <h3>${esc(t("reco_title"))}</h3>
                <button type="button" class="btn ghost" id="btn-open-all-reco">${esc(t("open_all_reco"))}</button>
              </div>
              <div id="detail-reco-out"></div>
            </div>
            <h3 style="margin-top:0">${esc(t("system_rec"))}</h3>
            <p><span class="badge rec-${esc(c.recommendation)}">${esc(recs[c.recommendation] || c.recommendation)}</span>
               · ${esc(t("score_label"))} <b>${esc(c.risk_score)}</b></p>
            <ul class="reasons">${reasons}</ul>
            <label style="margin-top:14px">${esc(t("notes"))}<textarea id="case-notes" rows="3">${esc(c.notes || "")}</textarea></label>
            <div class="actions">
              <button class="btn approve" type="button" data-dec="approve">${esc(t("rec_approve"))}</button>
              <button class="btn refer" type="button" data-dec="refer">${esc(t("rec_refer"))}</button>
              <button class="btn decline" type="button" data-dec="decline">${esc(t("rec_decline"))}</button>
            </div>
            <p id="dec-msg" class="small muted"></p>
          </div>
        </div>`;
      renderRecoCards(recoItems, {
        caseId: c.id,
        target: "#detail-reco-out",
        compact: true,
        limit: 3,
        primary: reco && reco.primary_risk,
      });
      box.querySelectorAll("[data-dec]").forEach((btn) => {
        btn.addEventListener("click", () => decide(c.id, btn.dataset.dec));
      });
      $("#btn-back").addEventListener("click", () => setTab("renewals"));
      $("#btn-open-all-reco")?.addEventListener("click", () => openRecommendForCase(c.id));
    } catch (e) {
      box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
    }
  }

  async function decide(id, decision) {
    const notes = ($("#case-notes") && $("#case-notes").value) || "";
    const msg = $("#dec-msg");
    try {
      await api(`/api/cases/${id}/decision`, {
        method: "PATCH",
        body: JSON.stringify({ decision, notes }),
      });
      if (msg) msg.textContent = `${t("decision_saved")}: ${REC_LABEL()[decision] || decision}`;
      await Promise.all([loadCases(), loadRenewals(), loadDashboard()]);
      await openCase(id);
    } catch (e) {
      if (msg) msg.textContent = e.message;
    }
  }

  function renderRagThread() {
    const thr = $("#rag-thread");
    if (!thr) return;
    if (!state.ragHistory.length) {
      thr.innerHTML = `<div class="bubble bot">${esc(t("rag_greeting"))}</div>`;
      return;
    }
    thr.innerHTML = state.ragHistory
      .map((m) => {
        const cls = m.role === "user" ? "user" : m.error ? "bot error" : "bot";
        const sources = Array.isArray(m.sources) ? m.sources : [];
        const sourcesHtml = sources.length
          ? `<div class="rag-sources">
              <div class="rag-sources-title">${esc(t("rag_sources"))}</div>
              ${sources.map((source, index) => `
                <button class="rag-source" type="button"
                  data-source="${esc(source.source || "")}" data-page="${esc(source.page_start || 1)}"
                  data-excerpt="${esc(source.excerpt || "")}" title="${esc(t("rag_open_document"))}">
                  <span class="rag-source-number">${index + 1}</span>
                  <span>${esc(source.citation || source.source || "—")}</span>
                </button>`).join("")}
            </div>`
          : "";
        return `<div class="bubble ${cls}"><div>${esc(m.text)}</div>${sourcesHtml}</div>`;
      })
      .join("");
    thr.scrollTop = thr.scrollHeight;
  }

  async function refreshRagStatus() {
    const badge = $("#rag-ollama");
    const modeSel = $("#rag-mode");
    try {
      const st = await api("/api/assistant/rag/status");
      const ready = !!(st.ollama && st.ollama.model_ready);
      if (badge) {
        badge.className = "chat-ollama-status " + (ready ? "is-ready" : "is-down");
        badge.textContent = ready ? t("rag_ollama_ready") : t("rag_ollama_down");
      }
      if (modeSel) {
        const ollamaOpt = modeSel.querySelector('option[value="ollama"]');
        if (ollamaOpt) ollamaOpt.disabled = !ready;
        const gigaReady = !!(st.gigachat && st.gigachat.available);
        const gigaOpt = modeSel.querySelector('option[value="gigachat"]');
        if (gigaOpt) gigaOpt.disabled = !gigaReady;
        if (!ready && modeSel.value === "ollama") modeSel.value = "auto";
        if (!gigaReady && modeSel.value === "gigachat") modeSel.value = "auto";
      }
    } catch {
      if (badge) {
        badge.className = "chat-ollama-status is-down";
        badge.textContent = t("rag_ollama_down");
      }
    }
  }

  async function afterLogin(user) {
    state.user = user;
    $("#user-chip").textContent = `${user.full_name || user.username}`;
    showApp(true);
    setTab("dashboard");
    await Promise.all([loadDashboard(), loadCases(), loadRenewals()]);
    renderRagThread();
  }

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const err = $("#auth-err");
    err.hidden = true;
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: fd.get("username"),
          password: fd.get("password"),
        }),
      });
      state.token = data.access_token;
      localStorage.setItem("uw_token", state.token);
      await afterLogin(data.user);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    }
  });

  $("#btn-logout").addEventListener("click", () => logout(true));
  $("#btn-refresh")?.addEventListener("click", () => loadCases());
  $("#btn-refresh-renewals")?.addEventListener("click", () => loadRenewals());
  $("#btn-reco")?.addEventListener("click", () => runRecommend());
  $("#reco-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    runRecommend();
  });
  $("#f-status")?.addEventListener("change", (e) => {
    state.statusFilter = e.target.value;
    loadCases();
  });
  $("#f-line")?.addEventListener("change", (e) => {
    state.lineFilter = e.target.value;
    loadCases();
  });

  let searchTimer = null;
  $("#global-search")?.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.searchQ = (e.target.value || "").trim();
      Promise.all([loadCases(), loadRenewals()]);
    }, 250);
  });

  $$(".tab").forEach((tab) => tab.addEventListener("click", () => setTab(tab.dataset.tab)));

  $("#rag-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = ($("#rag-input").value || "").trim();
    if (!q) return;
    const mode = ($("#rag-mode") && $("#rag-mode").value) || "auto";
    localStorage.setItem("uw_rag_mode", mode);
    state.ragHistory.push({ role: "user", text: q });
    renderRagThread();
    $("#rag-input").value = "";
    const thr = $("#rag-thread");
    thr.insertAdjacentHTML("beforeend", `<div class="bubble bot" id="rag-wait">${esc(t("rag_wait"))}</div>`);
    try {
      const res = await api("/api/assistant/ask", {
        method: "POST",
        body: JSON.stringify({ question: q, mode, lang: I.getLang(), top_k: 4 }),
      });
      const wait = $("#rag-wait");
      if (wait) wait.remove();
      state.ragHistory.push({ role: "bot", text: res.answer || "—", sources: res.chunks_used || [] });
      renderRagThread();
      refreshRagStatus().catch(() => {});
    } catch (err) {
      const wait = $("#rag-wait");
      if (wait) wait.remove();
      state.ragHistory.push({ role: "bot", text: err.message || String(err), error: true });
      renderRagThread();
    }
  });

  const savedRagMode = localStorage.getItem("uw_rag_mode") || "auto";
  if ($("#rag-mode")) $("#rag-mode").value = savedRagMode;
  $("#rag-input")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      $("#rag-form").requestSubmit();
    }
  });

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

  $("#lang-auth")?.addEventListener("change", (e) => onLangChange(e.target));
  $("#lang-app")?.addEventListener("change", (e) => onLangChange(e.target));

  I.setLang(I.getLang());
  applyI18n();

  (async () => {
    if (!state.token) {
      showApp(false);
      return;
    }
    try {
      const me = await api("/api/auth/me");
      await afterLogin(me);
    } catch {
      logout(true);
    }
  })();
})();
