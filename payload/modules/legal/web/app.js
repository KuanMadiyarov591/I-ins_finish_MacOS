(() => {
  const I = window.LegalI18n;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const state = {
    token: localStorage.getItem("lh_token") || "",
    user: null,
    cases: [],
    selectedId: null,
    lastReco: null,
    recoCaseId: null,
    ragHistory: [],
    dash: null,
  };

  const t = (k) => I.t(k);

  function LINE_LABEL() {
    return { pi: t("line_pi_full"), imr: t("line_imr_full") };
  }
  function REC_LABEL() {
    return { accept: t("rec_accept"), escalate: t("rec_escalate"), decline: t("rec_decline"), approve: t("rec_accept"), refer: t("rec_escalate") };
  }
  function STATUS_LABEL() {
    return {
      new: t("status_new"),
      in_review: t("status_in_review"),
      escalated: t("status_escalated"),
      accepted: t("status_accepted"),
      declined: t("status_declined"),
    };
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(v) {
    const n = Number(v) || 0;
    return n.toLocaleString(I.getLang() === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 0 });
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(path, { ...opts, headers });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
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
    $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    $$(".tab-panel").forEach((p) => {
      p.hidden = p.id !== `tab-${name}`;
    });
    if (name === "recommend") {
      fillRecoCases();
      if (state.lastReco) {
        renderRecoCards(state.lastReco.recommendations || [], { caseId: state.recoCaseId });
      }
    }
    if (name === "aihub") {
      renderRagThread();
      refreshRagStatus();
    }
  }

  function applyI18nAndRerender() {
    I.applyDom();
    if (state.dash) renderDashboard(state.dash);
    renderCasesTable();
    if (state.lastReco) {
      renderRecoCards(state.lastReco.recommendations || [], { caseId: state.recoCaseId });
    }
    renderRagThread();
  }

  async function loadDashboard() {
    state.dash = await api("/api/dashboard/summary");
    renderDashboard(state.dash);
  }

  function renderDashboard(d) {
    const ai = d.action_items || {};
    const book = d.book_of_business || {};
    const w = d.widgets || {};
    $("#action-kpi").innerHTML = [
      kpi(t("kpi_open"), ai.open_queue ?? ai.up_for_renewal ?? 0),
      kpi(t("kpi_hearing"), ai.upcoming_hearings ?? ai.about_to_lapse ?? 0),
      kpi(t("kpi_opps"), ai.open_opportunities ?? 0),
      kpi(t("kpi_urgent"), ai.urgent ?? ai.payment_due ?? 0),
    ].join("");
    $("#book-kpi").innerHTML = [
      kpi(t("kpi_amt_pending"), money(book.amount_pending ?? book.premium_pending)),
      kpi(t("kpi_amt_accepted"), money(book.amount_accepted ?? book.premium_retained)),
      kpi(t("kpi_accept_rate"), `${book.accept_rate ?? book.renewal_rate ?? 0}%`),
      kpi(t("kpi_total"), book.total_cases ?? 0),
    ].join("");

    const pending = Number((w.pending_vs_retained || {}).pending || 0);
    const retained = Number((w.pending_vs_retained || {}).retained || 0);
    const max = Math.max(pending, retained, 1);
    $("#bar-pending-retained").innerHTML = `
      <div class="bar-row"><span>${esc(t("bar_pending"))}</span><div class="bar-track"><div class="bar-fill" style="width:${(pending / max) * 100}%"></div></div><span>${money(pending)}</span></div>
      <div class="bar-row"><span>${esc(t("bar_retained"))}</span><div class="bar-track"><div class="bar-fill" style="width:${(retained / max) * 100}%"></div></div><span>${money(retained)}</span></div>`;

    const statuses = w.policy_by_status || d.status_counts || {};
    $("#donut-status").innerHTML = Object.entries(statuses)
      .map(([k, v]) => `<div class="donut-item"><b>${esc(STATUS_LABEL()[k] || k)}</b>: ${esc(v)}</div>`)
      .join("") || `<span class="muted">—</span>`;

    $("#risk-widgets").innerHTML = `
      <div class="mini-stat"><span class="muted">${esc(t("mini_high_risk"))}</span><b>${esc(w.high_risk_count || 0)}</b></div>
      <div class="mini-stat"><span class="muted">${esc(t("mini_declined"))}</span><b>${esc(w.decline_do_not_renew || 0)}</b></div>`;

    const lines = LINE_LABEL();
    $("#workstream").innerHTML = (w.workstream || [])
      .map((x) => `<div class="ws-row"><span>${esc(lines[x.line] || x.line)}</span><span>${esc(x.count)} · ${money(x.amount ?? x.premium)}</span></div>`)
      .join("");

    const recs = REC_LABEL();
    const tb = $("#submissions-table tbody");
    tb.innerHTML = (w.new_submissions || [])
      .map(
        (s) => `<tr data-id="${esc(s.id)}">
          <td>${esc(s.case_number || s.policy_number)}</td>
          <td>${esc(s.party_name || s.insured_name)}</td>
          <td>${esc(lines[s.line] || s.line)}</td>
          <td>${esc(s.days_open)}</td>
          <td>${money(s.amount ?? s.premium)}</td>
          <td>${esc(s.risk_score)}</td>
          <td><span class="badge rec-${esc(s.recommendation)}">${esc(recs[s.recommendation] || s.recommendation)}</span></td>
        </tr>`
      )
      .join("");
    tb.querySelectorAll("tr").forEach((tr) => tr.addEventListener("click", () => openCase(Number(tr.dataset.id))));
  }

  function kpi(label, value) {
    return `<div class="kpi-card"><div class="k">${esc(label)}</div><div class="v">${esc(value)}</div></div>`;
  }

  async function loadCases() {
    const status = ($("#f-status") && $("#f-status").value) || "";
    const line = ($("#f-line") && $("#f-line").value) || "";
    const q = ($("#global-search") && $("#global-search").value) || "";
    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (line) qs.set("line", line);
    if (q) qs.set("q", q);
    const data = await api(`/api/cases?${qs}`);
    state.cases = data.items || [];
    const counts = data.status_counts || {};
    $("#status-kpi").innerHTML = Object.entries(counts)
      .map(([k, v]) => `<span class="badge">${esc(STATUS_LABEL()[k] || k)}: ${esc(v)}</span>`)
      .join(" ");
    renderCasesTable();
    fillRecoCases();
  }

  function renderCasesTable() {
    const lines = LINE_LABEL();
    const recs = REC_LABEL();
    const statuses = STATUS_LABEL();
    const tb = $("#cases-table tbody");
    if (!tb) return;
    tb.innerHTML = state.cases
      .map(
        (c) => `<tr data-id="${esc(c.id)}" class="${state.selectedId === c.id ? "active" : ""}">
          <td>${esc(c.case_number || c.external_id)}</td>
          <td>${esc(c.party_name || c.insured_name)}</td>
          <td>${esc(lines[c.line] || c.line)}</td>
          <td>${money(c.amount ?? c.premium)}</td>
          <td>${esc(statuses[c.decision_status] || c.decision_status)}</td>
          <td>${esc(c.risk_score)}</td>
          <td><span class="badge rec-${esc(c.recommendation)}">${esc(recs[c.recommendation] || c.recommendation)}</span></td>
          <td>${esc(c.days_open)}</td>
        </tr>`
      )
      .join("");
    tb.querySelectorAll("tr").forEach((tr) => tr.addEventListener("click", () => openCase(Number(tr.dataset.id))));
  }

  function fillRecoCases() {
    const sel = $("#reco-case");
    if (!sel) return;
    const opts = [`<option value="">${esc(t("reco_pick_case"))}</option>`];
    state.cases.forEach((c) => {
      opts.push(`<option value="${esc(c.id)}">${esc(c.case_number)} · ${esc(c.party_name || c.title)}</option>`);
    });
    const prev = sel.value;
    sel.innerHTML = opts.join("");
    if (prev) sel.value = prev;
  }

  function recoCtaLabel(action) {
    if (action === "accept" || action === "approve") return t("reco_apply_accept");
    if (action === "escalate" || action === "refer") return t("reco_apply_escalate");
    if (action === "decline") return t("reco_apply_decline");
    return t("reco_apply");
  }

  function recoDecisionTitle(action) {
    if (action === "accept" || action === "approve") return t("reco_decision_accept");
    if (action === "escalate" || action === "refer") return t("reco_decision_escalate");
    if (action === "decline") return t("reco_decision_decline");
    return action;
  }

  function recoRowTitle(r) {
    if (r.category === "decision") return recoDecisionTitle(r.action);
    if (r.action && ["accept", "escalate", "decline", "approve", "refer"].includes(r.action)) return recoDecisionTitle(r.action);
    return r.title || r.line_label || "—";
  }

  function recoMatchKindLabel(r) {
    if (r.match_kind === "probability") return t("reco_prob");
    if (r.match_kind === "confidence") return t("reco_conf");
    return r.match_label || "";
  }

  function recoReasonsList(r, limit = 3) {
    const cleaned = (r.reasons || []).slice(0, limit);
    if (!cleaned.length) return "—";
    return `<ul class="reco-why">${cleaned.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  }

  function recoActionCell(r, caseId) {
    const action = r.action;
    if (!action) return "—";
    if (caseId) {
      return `<button type="button" class="btn primary rec-tile-cta" data-reco-action="${esc(action)}" data-reco-case="${esc(caseId)}">${esc(recoCtaLabel(action))}</button>`;
    }
    return `<button type="button" class="btn rec-tile-cta" disabled title="${esc(t("reco_apply_case_only"))}">${esc(t("reco_apply"))}</button>`;
  }

  function recoRowHtml(r, { caseId = null, compact = false } = {}) {
    const title = recoRowTitle(r);
    const kind = recoMatchKindLabel(r);
    const pct = `${r.match_pct ?? "—"}%`;
    const pctHtml = `<span>${pct}</span>${kind ? `<small class="reco-pct-kind">${esc(kind)}</small>` : ""}`;
    const factors = recoReasonsList(r, 3);
    if (compact) {
      return `<tr>
        <td class="reco-line-cell">${esc(title)}</td>
        <td class="reco-col-pct">${pctHtml}</td>
        <td>${factors}</td>
      </tr>`;
    }
    const target = esc(r.target || r.category_label || "—");
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
    let list = items || [];
    if (limit) list = list.slice(0, limit);
    if (!list.length) {
      box.innerHTML = `<p class="muted">${esc(t("reco_none"))}</p>`;
      return;
    }
    const rows = list.map((r) => recoRowHtml(r, { caseId, compact })).join("");
    const tableCls = compact ? "reco-table reco-table-compact" : "reco-table";
    const head = compact
      ? `<thead><tr><th>${esc(t("reco_col_line"))}</th><th class="reco-col-pct">${esc(t("reco_col_pct"))}</th><th>${esc(t("reco_col_factors"))}</th></tr></thead>`
      : `<thead><tr>
          <th>${esc(t("reco_col_line"))}</th>
          <th>${esc(t("reco_col_target"))}</th>
          <th class="reco-col-pct">${esc(t("reco_col_pct"))}</th>
          <th>${esc(t("reco_col_factors"))}</th>
          <th>${esc(t("reco_col_action"))}</th>
        </tr></thead>`;
    box.innerHTML = `<div class="reco-table-wrap"><table class="${tableCls}">${head}<tbody>${rows}</tbody></table></div>`;
    box.querySelectorAll("[data-reco-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.recoCase);
        const decision = btn.dataset.recoAction;
        await decide(id, decision);
        showRecoToast(`${t("decision_saved")}: ${REC_LABEL()[decision] || decision}`);
      });
    });
  }

  function showRecoToast(msg) {
    const el = $("#reco-toast");
    if (el) el.textContent = msg;
  }

  async function runRecommend() {
    const box = $("#reco-out");
    const caseId = ($("#reco-case") && $("#reco-case").value) || "";
    box.innerHTML = `<p class="muted">${esc(t("reco_loading"))}</p>`;
    try {
      let res;
      if (caseId) {
        state.recoCaseId = Number(caseId);
        res = await api(`/api/recommend/case/${caseId}`);
        state.lastReco = res;
        renderRecoCards(res.recommendations || [], { caseId: Number(caseId) });
      } else {
        state.recoCaseId = null;
        const body = {
          line: ($("#reco-line") && $("#reco-line").value) || "pi",
          amount: Number(($("#reco-amount") && $("#reco-amount").value) || 0) || null,
          risk_hint: Number(($("#reco-risk-hint") && $("#reco-risk-hint").value) || 0) || null,
          appeal_type: ($("#reco-appeal") && $("#reco-appeal").value) || null,
        };
        res = await api("/api/recommend/profile", { method: "POST", body: JSON.stringify(body) });
        state.lastReco = res;
        renderRecoCards(res.recommendations || [], { caseId: null });
      }
    } catch (e) {
      box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
    }
  }

  async function openCase(id) {
    state.selectedId = id;
    renderCasesTable();
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
        .map(([k, v]) => `<div class="feat"><b>${esc(k)}</b>${esc(typeof v === "string" ? v.slice(0, 120) : v)}</div>`)
        .join("");
      const stages = (c.stages || [])
        .map((s) => `<div class="stage ${s.done ? "done" : ""} ${s.active ? "active" : ""}">${esc(s.label)}</div>`)
        .join("");
      const docs = (c.documents || [])
        .map(
          (d) => `<li><span>${esc(d.name)}</span>
            <span class="badge ${d.synced ? "sp-synced" : "sp-pending"}">${esc(d.synced ? t("sp_synced") : t("sp_pending"))}</span></li>`
        )
        .join("");
      const recoItems = (reco && reco.recommendations) || [];
      const lines = LINE_LABEL();
      const recs = REC_LABEL();
      const statuses = STATUS_LABEL();

      box.innerHTML = `
        <div class="section-head row">
          <div>
            <h2>${esc(c.party_name || c.insured_name || c.title)}</h2>
            <p class="muted small">${esc(c.case_number)} · ${esc(lines[c.line] || c.line)} · ${esc(t("hearing_label"))} ${esc(c.hearing_date || "—")}
              · <span class="badge sp-synced">${esc(t("sp_synced"))}</span></p>
          </div>
          <button class="btn" type="button" id="btn-back">${esc(t("back_list"))}</button>
        </div>
        <div class="detail-metrics">
          <div class="metric"><div class="k">${esc(t("metric_risk"))}</div><div class="v">${esc(c.risk_score)}</div></div>
          <div class="metric"><div class="k">${esc(t("metric_rec"))}</div><div class="v"><span class="badge rec-${esc(c.recommendation)}">${esc(recs[c.recommendation] || c.recommendation)}</span></div></div>
          <div class="metric"><div class="k">${esc(t("metric_amt"))}</div><div class="v">${money(c.amount)}</div></div>
          <div class="metric"><div class="k">${esc(t("metric_stage"))}</div><div class="v" style="font-size:1rem">${esc(c.stage_label || statuses[c.decision_status])}</div></div>
        </div>
        <div class="chevron-stages">${stages}</div>
        <div class="detail-grid">
          <div>
            <div class="panel-block" style="margin-bottom:14px">
              <h3>${esc(t("case_details"))}</h3>
              <p>${esc(c.applicant_summary)}</p>
              <div class="meta" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
                ${c.urgency_signal || c.fraud_signal ? `<span class="badge urgent">${esc(t("urgent_badge"))}</span>` : ""}
                ${c.decision_by ? `<span class="badge">${esc(t("decided_by"))}: ${esc(c.decision_by)}</span>` : ""}
                <span class="badge">${esc(t("days_open"))}: ${esc(c.days_open)}</span>
              </div>
            </div>
            <div class="panel-block" style="margin-bottom:14px">
              <h3>${esc(t("docs_title"))}</h3>
              <ul class="doc-list">${docs || "<li>—</li>"}</ul>
            </div>
            <div class="panel-block" style="margin-bottom:14px">
              <h3>${esc(t("risk_factors"))}</h3>
              <div class="feat-grid">${feats || '<span class="muted">—</span>'}</div>
            </div>
            <div class="panel-block">
              <h3>${esc(t("amount_block"))}</h3>
              <p><b>${money(c.amount)}</b> · ${esc(t("line_of"))} ${esc(lines[c.line] || c.line)}</p>
            </div>
          </div>
          <div class="ai-panel">
            <div class="detail-reco">
              <div class="detail-reco-head section-head row">
                <h3 style="margin:0">${esc(t("reco_title"))}</h3>
                <button type="button" class="btn ghost" id="btn-open-all-reco" style="color:var(--navy);border-color:var(--line)">${esc(t("open_all_reco"))}</button>
              </div>
              <div id="detail-reco-out"></div>
            </div>
            <h3 style="margin-top:14px">${esc(t("system_rec"))}</h3>
            <p><span class="badge rec-${esc(c.recommendation)}">${esc(recs[c.recommendation] || c.recommendation)}</span>
               · ${esc(t("score_label"))} <b>${esc(c.risk_score)}</b></p>
            <ul class="reasons">${reasons}</ul>
            <label style="margin-top:14px">${esc(t("notes"))}<textarea id="case-notes" rows="3">${esc(c.notes || "")}</textarea></label>
            <div class="actions">
              <button class="btn accept" type="button" data-dec="accept">${esc(t("rec_accept"))}</button>
              <button class="btn escalate" type="button" data-dec="escalate">${esc(t("rec_escalate"))}</button>
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
      });
      box.querySelectorAll("[data-dec]").forEach((btn) => {
        btn.addEventListener("click", () => decide(c.id, btn.dataset.dec));
      });
      $("#btn-back").addEventListener("click", () => setTab("requests"));
      $("#btn-open-all-reco")?.addEventListener("click", () => {
        state.recoCaseId = c.id;
        if ($("#reco-case")) $("#reco-case").value = String(c.id);
        setTab("recommend");
        runRecommend();
      });
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
      await Promise.all([loadCases(), loadDashboard()]);
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
    await Promise.all([loadDashboard(), loadCases()]);
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
      localStorage.setItem("lh_token", state.token);
      await afterLogin(data.user);
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    }
  });

  $("#btn-logout")?.addEventListener("click", () => {
    state.token = "";
    localStorage.removeItem("lh_token");
    showApp(false);
  });

  $$(".tab").forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.tab)));
  $("#btn-refresh")?.addEventListener("click", () => loadCases());
  $("#f-status")?.addEventListener("change", () => loadCases());
  $("#f-line")?.addEventListener("change", () => loadCases());
  $("#global-search")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadCases();
  });
  $("#reco-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    runRecommend();
  });
  $("#btn-reco")?.addEventListener("click", (e) => {
    e.preventDefault();
    runRecommend();
  });

  $("#rag-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#rag-input");
    const q = (input.value || "").trim();
    if (!q) return;
    state.ragHistory.push({ role: "user", text: q });
    input.value = "";
    renderRagThread();
    state.ragHistory.push({ role: "bot", text: t("rag_thinking") });
    renderRagThread();
    try {
      const res = await api("/api/assistant/ask", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          mode: ($("#rag-mode") && $("#rag-mode").value) || "auto",
          lang: I.getLang(),
        }),
      });
      state.ragHistory.pop();
      state.ragHistory.push({ role: "bot", text: res.answer || "—", sources: res.chunks_used || [] });
    } catch (ex) {
      state.ragHistory.pop();
      state.ragHistory.push({ role: "bot", text: ex.message, error: true });
    }
    renderRagThread();
  });

  $("#lang-auth")?.addEventListener("change", (e) => I.setLang(e.target.value));
  $("#lang-app")?.addEventListener("change", (e) => I.setLang(e.target.value));
  window.addEventListener("lh:lang", () => applyI18nAndRerender());

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

  I.applyDom();

  (async () => {
    if (!state.token) {
      showApp(false);
      return;
    }
    try {
      const me = await api("/api/auth/me");
      await afterLogin(me);
    } catch {
      state.token = "";
      localStorage.removeItem("lh_token");
      showApp(false);
    }
  })();
})();
