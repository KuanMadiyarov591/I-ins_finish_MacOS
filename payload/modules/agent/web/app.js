(() => {
  const I = window.AgentI18n;
  const t = (k, v) => I.t(k, v);

  const state = {
    token: localStorage.getItem("ad_token") || "",
    user: null,
    clients: [],
    products: [],
    selectedId: null,
    selectedAppId: null,
    tags: [],
    priorityFilter: "",
    appStatusFilter: "draft",
    priorityCounts: { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 },
    apps: [],
    ragHistory: [],
  };

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  const money = (n) => Number(n || 0).toLocaleString(I.getLang() === "en" ? "en-US" : "ru-RU");
  const prioLabel = (n) => t("priority_n", { n });
  const statusLabel = (s) => t("status_" + s) || s;
  const catLabel = (c) => t("cat_" + c) || c;
  const payLabel = (s) => t("pay_" + (s || "unpaid")) || s;
  const payMethodLabel = (m) => t("pay_method_" + (m || "none")) || m || "—";

  function applyI18n() {
    $$("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    $$("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
    });
    const fp = $("#f-priority");
    if (fp) {
      [...fp.options].forEach((opt) => {
        if (!opt.value) opt.textContent = t("all_priorities");
        else opt.textContent = prioLabel(opt.value);
      });
    }
    $("#lang-auth").value = I.getLang();
    $("#lang-app").value = I.getLang();
    syncFilterButtons();
  }

  function syncFilterButtons() {
    const clearPrio = $("#btn-clear-prio");
    if (clearPrio) clearPrio.hidden = !state.priorityFilter;
    const clearApp = $("#btn-clear-app-status");
    if (clearApp) clearApp.hidden = !state.appStatusFilter;
  }

  function setPriorityFilter(value) {
    const next = value ? String(value) : "";
    if (next && state.priorityFilter === next) {
      state.priorityFilter = "";
    } else {
      state.priorityFilter = next;
    }
    $("#f-priority").value = state.priorityFilter;
    loadClients();
  }

  function setAppStatusFilter(value) {
    const next = value ? String(value) : "";
    if (next && state.appStatusFilter === next) {
      state.appStatusFilter = "";
    } else {
      state.appStatusFilter = next;
    }
    $("#f-app-status").value = state.appStatusFilter;
    state.selectedAppId = null;
    const detail = $("#app-detail");
    if (detail) {
      detail.classList.add("empty");
      detail.innerHTML = `<p class="muted">${esc(t("pick_app"))}</p>`;
    }
    loadApps();
  }

  function appStatusLabel(st) {
    if (st === "draft" || st === "checklist" || st === "submitted") return t(st);
    return st;
  }

  function showApp(on) {
    $("#auth").hidden = on;
    $("#app").hidden = !on;
  }

  function setTab(name) {
    $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    ["clients", "apps", "reco", "assistant", "profile"].forEach((k) => {
      const panel = $("#tab-" + k);
      if (panel) panel.hidden = k !== name;
    });
    if (name === "assistant") refreshRagStatus().catch(console.warn);
  }

  async function refreshRagStatus() {
    const badge = $("#rag-ollama");
    const modeSel = $("#rag-mode");
    try {
      const st = await api("/api/assistant/rag/status");
      const ready = !!(st.ollama && st.ollama.model_ready);
      if (badge) {
        badge.className = "chat-ollama-status " + (ready ? "is-ready" : "is-down");
        badge.textContent = ready
          ? t("rag_ollama_ready") + (st.ollama.model ? " · " + st.ollama.model : "")
          : t("rag_ollama_down");
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
    } catch (ex) {
      if (badge) {
        badge.className = "chat-ollama-status is-down";
        badge.textContent = t("rag_ollama_down");
      }
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
        return `<div class="bubble ${m.role === "user" ? "user" : "bot"}${m.error ? " error" : ""}">
          <div>${esc(m.text)}</div>${sourcesHtml}
        </div>`;
      })
      .join("");
    thr.scrollTop = thr.scrollHeight;
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers.Authorization = "Bearer " + state.token;
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  async function apiBlob(path) {
    const headers = {};
    if (state.token) headers.Authorization = "Bearer " + state.token;
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

  function renderRecCards(list, mountId, clientId) {
    const mount = $(mountId);
    if (!mount) return;
    if (!list || !list.length) {
      mount.innerHTML = "";
      return;
    }
    mount.innerHTML = list
      .map(
        (r) => `<article class="rec-tile">
        <div class="rec-tile-top">
          <b class="rec-tile-name">${esc(r.policy_name)}</b>
          <span class="rec-tile-cat">${esc(r.category_label || catLabel(r.category))}</span>
        </div>
        <div class="rec-tile-meta">
          <span class="rec-tile-premium">${money(r.premium)}</span>
          <span class="rec-match">${r.match_pct || Math.round((r.score || 0) * 100)}%</span>
        </div>
        <p class="rec-tile-why">${esc((r.reasons || [])[0] || "")}</p>
        <button class="btn sm primary rec-tile-btn" type="button" data-rec-quote="${r.product_id}" data-client="${clientId}">
          ${esc(t("reco_quote"))}
        </button>
      </article>`
      )
      .join("");

    mount.querySelectorAll("[data-rec-quote]").forEach((btn) => {
      btn.onclick = () => {
        const cid = Number(btn.getAttribute("data-client"));
        const pid = Number(btn.getAttribute("data-rec-quote"));
        $("#quote-form").client_id.value = cid;
        $("#quote-products").value = String(pid);
        $("#dlg-quote").showModal();
      };
    });
  }

  async function loadMeta() {
    const [tags, products] = await Promise.all([api("/api/tags"), api("/api/products")]);
    state.tags = tags.tags || [];
    state.products = products.products || [];
    $("#f-tag").innerHTML =
      `<option value="">${esc(t("all_tags"))}</option>` +
      state.tags.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("");
    $("#quote-products").innerHTML = state.products
      .map((p) => `<option value="${p.id}">${esc(p.name)} (${esc(catLabel(p.category))}) · ${money(p.premium)}</option>`)
      .join("");
  }

  function fillClientSelects() {
    const reco = $("#reco-client");
    if (!reco) return;
    const opts = state.clients
      .map((c) => `<option value="${c.id}">${esc(c.full_name)} · ${esc(prioLabel(c.priority))}</option>`)
      .join("");
    reco.innerHTML = opts;
    if (state.selectedId) {
      reco.value = String(state.selectedId);
    }
  }

  async function loadClients() {
    const q = new URLSearchParams();
    const priority = state.priorityFilter || $("#f-priority").value;
    const tag = $("#f-tag").value;
    const status = $("#f-status").value;
    const search = $("#q-clients").value.trim();
    if (priority) q.set("priority", priority);
    if (tag) q.set("tag", tag);
    if (status) q.set("status", status);
    if (search) q.set("q", search);
    q.set("limit", "120");
    const data = await api("/api/clients?" + q.toString());
    state.clients = data.clients || [];
    const counts = data.priority_counts || {};
    state.priorityCounts = counts;
    $("#prio-kpi").innerHTML = [1, 2, 3, 4, 5]
      .map((i) => {
        const active = String(state.priorityFilter) === String(i) ? " active" : "";
        return `<button type="button" class="stat p${i}${active}" data-prio="${i}">
          <span class="muted">${esc(prioLabel(i))}</span>
          <b>${counts[i] || counts[String(i)] || 0}</b>
        </button>`;
      })
      .join("");
    $$("#prio-kpi [data-prio]").forEach((btn) => {
      btn.onclick = () => setPriorityFilter(btn.getAttribute("data-prio"));
    });

    $("#client-list").innerHTML =
      state.clients
        .map((c) => {
          const active = c.id === state.selectedId ? " active" : "";
          const tags = (c.tags || []).slice(0, 3);
          return `<article class="tile${active}" data-id="${c.id}" title="${esc(c.full_name)}">
          <div class="tile-top">
            <span class="prio p${c.priority}">${esc(prioLabel(c.priority))}</span>
          </div>
          <h4 class="tile-name">${esc(c.full_name)}</h4>
          <div class="tile-meta">
            <span>${esc(c.phone || c.external_id || "—")}</span>
            <span>${esc(statusLabel(c.status))}</span>
          </div>
          <div class="tags">${tags.map((name) => `<span class="tag">${esc(name)}</span>`).join("")}</div>
        </article>`;
        })
        .join("") || `<p class="muted">${esc(t("no_clients"))}</p>`;

    $("#client-list").querySelectorAll("[data-id]").forEach((el) => {
      el.onclick = () => openClient(Number(el.dataset.id));
    });
    syncFilterButtons();
    fillClientSelects();
  }

  async function openClient(id) {
    state.selectedId = id;
    fillClientSelects();
    const c = await api("/api/clients/" + id);
    $$("#client-list .tile").forEach((el) => el.classList.toggle("active", Number(el.dataset.id) === id));

    $("#client-detail").classList.remove("empty");
    $("#client-detail").innerHTML = `
      <h2>${esc(c.full_name)}</h2>
      <div class="muted small">${esc(c.external_id)} · ${esc(c.priority_short || prioLabel(c.priority))}</div>
      <p>${esc(c.phone || "—")} · ${esc(c.email || "—")} · ${esc(String(c.age || "—"))} · ${money(c.annual_income)}</p>
      <div class="tags">${(c.tags || []).map((name) => `<span class="tag">${esc(name)}</span>`).join("")}</div>
      ${c.coverage_change ? `<p><b>${esc(t("coverage_flag"))}</b></p>` : ""}
      <div id="client-recs" class="rec-list"></div>
      <label>${esc(t("notes"))}<textarea id="c-notes" rows="3">${esc(c.notes || "")}</textarea></label>
      <label class="check"><input id="c-cov" type="checkbox"${c.coverage_change ? " checked" : ""} /> ${esc(t("coverage_flag"))}</label>
      <div class="row">
        <button class="btn sm" type="button" id="btn-save-client">${esc(t("save"))}</button>
        <button class="btn sm" type="button" id="btn-refresh-prio">${esc(t("refresh_prio"))}</button>
        <button class="btn sm primary" type="button" id="btn-new-quote">${esc(t("new_quote"))}</button>
      </div>
      <h3 style="margin-top:16px">${esc(t("client_apps"))}</h3>
      <div id="c-apps" class="list"></div>
    `;

    $("#btn-save-client").onclick = async () => {
      await api("/api/clients/" + id, {
        method: "PATCH",
        body: JSON.stringify({
          notes: $("#c-notes").value,
          coverage_change: $("#c-cov").checked,
        }),
      });
      await loadClients();
      await openClient(id);
    };
    $("#btn-refresh-prio").onclick = async () => {
      await api("/api/clients/" + id + "/refresh-priority", { method: "POST", body: "{}" });
      await loadClients();
      await openClient(id);
    };
    $("#btn-new-quote").onclick = () => {
      $("#quote-form").client_id.value = id;
      $("#dlg-quote").showModal();
    };

    const apps = c.applications || [];
    $("#c-apps").innerHTML = apps.length
      ? apps
          .map(
            (a) =>
              `<div class="item"><b>#${a.id}</b> · ${esc(String(a.product_id))} · ${esc(a.status)} · ${money(a.quoted_premium || 0)}</div>`
          )
          .join("")
      : `<p class="muted">${esc(t("no_apps"))}</p>`;

    try {
      const reco = await api(`/api/recommend/client/${id}?top_k=3&lang=${I.getLang()}`);
      renderRecCards(reco.recommendations || [], "#client-recs", id);
    } catch (ex) {
      console.warn(ex);
    }
  }

  async function loadApps() {
    const st = state.appStatusFilter || $("#f-app-status").value;
    const q = st ? "?status=" + encodeURIComponent(st) : "";
    const data = await api("/api/applications" + q);
    state.apps = data.applications || [];
    const counts = data.status_counts || { draft: 0, checklist: 0, submitted: 0 };

    $("#apps-kpi").innerHTML = ["draft", "checklist", "submitted"]
      .map((key) => {
        const active = state.appStatusFilter === key ? " active" : "";
        return `<button type="button" class="stat s-${key}${active}" data-app-st="${key}">
          <span class="muted">${esc(t(key))}</span>
          <b>${counts[key] || 0}</b>
        </button>`;
      })
      .join("");
    $$("#apps-kpi [data-app-st]").forEach((btn) => {
      btn.onclick = () => setAppStatusFilter(btn.getAttribute("data-app-st"));
    });

    $("#apps-list").innerHTML =
      state.apps
        .map((a) => {
          const active = a.id === state.selectedAppId ? " active" : "";
          return `<article class="tile app-tile${active}" data-app-id="${a.id}">
          <div class="tile-top">
            <span class="badge-st ${esc(a.status)}">${esc(appStatusLabel(a.status))}</span>
            <span class="badge-pay ${esc(a.payment_status || "unpaid")}">${esc(payLabel(a.payment_status))}</span>
          </div>
          <h4 class="tile-name">${esc(a.product_name || "—")}</h4>
          <div class="tile-meta">
            <span>${esc(a.client_name || "—")}</span>
            <span>${money(a.quoted_premium)} · ${a.checklist_ready ? t("ready") : t("not_ready")}</span>
          </div>
          <div class="tile-meta muted small">${esc(t("pay_commission"))}: ${money(a.commission_amount)} (${Number(a.commission_pct || 0).toFixed(0)}%)</div>
        </article>`;
        })
        .join("") || `<p class="muted">${esc(t("no_apps"))}</p>`;

    $("#apps-list").querySelectorAll("[data-app-id]").forEach((el) => {
      el.onclick = () => openApp(Number(el.dataset.appId));
    });
    syncFilterButtons();
    if (state.selectedAppId) {
      const still = state.apps.find((a) => a.id === state.selectedAppId);
      if (still) openApp(state.selectedAppId);
    }
  }

  function openApp(id) {
    const a = state.apps.find((x) => x.id === id);
    if (!a) return;
    state.selectedAppId = id;
    $$("#apps-list .tile").forEach((el) => el.classList.toggle("active", Number(el.dataset.appId) === id));

    const chk = a.checklist || {};
    const detail = $("#app-detail");
    detail.classList.remove("empty");
    detail.innerHTML = `
      <h2>#${a.id} · ${esc(a.product_name || "—")}</h2>
      <div class="muted small">${esc(a.client_name || "—")} · <span class="badge-st ${esc(a.status)}">${esc(appStatusLabel(a.status))}</span></div>
      <p>${esc(t("premium"))}: <b>${money(a.quoted_premium)}</b> · ${a.checklist_ready ? t("ready") : t("not_ready")}</p>
      ${a.notes ? `<p class="muted small">${esc(a.notes)}</p>` : ""}
      <div class="pay-box" id="pay-box">
        <div class="pay-box-title">${esc(t("pay_block"))}</div>
        <div class="pay-grid">
          <label>${esc(t("pay_status"))}
            <select id="pay-status">
              <option value="unpaid">${esc(t("pay_unpaid"))}</option>
              <option value="pending">${esc(t("pay_pending"))}</option>
              <option value="paid">${esc(t("pay_paid"))}</option>
              <option value="overdue">${esc(t("pay_overdue"))}</option>
            </select>
          </label>
          <label>${esc(t("pay_method"))}
            <select id="pay-method">
              <option value="">${esc(t("pay_method_none"))}</option>
              <option value="card">${esc(t("pay_method_card"))}</option>
              <option value="cash">${esc(t("pay_method_cash"))}</option>
              <option value="transfer">${esc(t("pay_method_transfer"))}</option>
              <option value="installment">${esc(t("pay_method_installment"))}</option>
            </select>
          </label>
          <label>${esc(t("pay_next"))}<input id="pay-next" type="date" value="${esc(a.next_payment_date || "")}" /></label>
          <label>${esc(t("pay_commission"))} %
            <input id="pay-pct" type="number" min="0" max="50" step="0.5" value="${esc(String(a.commission_pct ?? 10))}" />
          </label>
        </div>
        <div class="pay-summary">
          <span class="badge-pay ${esc(a.payment_status || "unpaid")}">${esc(payLabel(a.payment_status))}</span>
          <span>${esc(t("pay_commission"))}: <b id="pay-comm-amt">${money(a.commission_amount)}</b></span>
        </div>
        <button class="btn sm" type="button" id="btn-save-pay">${esc(t("pay_save"))}</button>
      </div>
      <div class="checklist" data-app="${a.id}">
        <label class="check"><input type="checkbox" data-k="chk_contact_ok"${chk.chk_contact_ok ? " checked" : ""} /> ${esc(t("chk_contact"))}</label>
        <label class="check"><input type="checkbox" data-k="chk_consent_ok"${chk.chk_consent_ok ? " checked" : ""} /> ${esc(t("chk_consent"))}</label>
        <label class="check"><input type="checkbox" data-k="chk_docs_ok"${chk.chk_docs_ok ? " checked" : ""} /> ${esc(t("chk_docs"))}</label>
        <label class="check"><input type="checkbox" data-k="chk_prefs_ok"${chk.chk_prefs_ok ? " checked" : ""} /> ${esc(t("chk_prefs"))}</label>
      </div>
      <div class="row">
        <button class="btn sm" type="button" id="btn-save-app-chk">${esc(t("save_chk"))}</button>
        <button class="btn sm primary" type="button" id="btn-submit-app" ${a.checklist_ready && a.status !== "submitted" ? "" : "disabled"}>${esc(t("submit_app"))}</button>
      </div>
    `;

    const payStatus = $("#pay-status");
    const payMethod = $("#pay-method");
    if (payStatus) payStatus.value = a.payment_status || "unpaid";
    if (payMethod) payMethod.value = a.payment_method || "";

    const syncCommPreview = () => {
      const pct = Number($("#pay-pct").value || 0);
      const prem = Number(a.quoted_premium || 0);
      $("#pay-comm-amt").textContent = money(Math.round((prem * pct) / 100));
    };
    $("#pay-pct").oninput = syncCommPreview;

    $("#btn-save-pay").onclick = async () => {
      await api("/api/applications/" + id + "/finance", {
        method: "PATCH",
        body: JSON.stringify({
          payment_status: $("#pay-status").value,
          payment_method: $("#pay-method").value,
          next_payment_date: $("#pay-next").value || "",
          commission_pct: Number($("#pay-pct").value || 0),
        }),
      });
      await loadApps();
    };

    $("#btn-save-app-chk").onclick = async () => {
      const box = detail.querySelector(".checklist");
      const body = {};
      box.querySelectorAll("input[data-k]").forEach((inp) => {
        body[inp.getAttribute("data-k")] = inp.checked;
      });
      await api("/api/applications/" + id + "/checklist", { method: "PATCH", body: JSON.stringify(body) });
      await loadApps();
      await loadClients();
    };
    $("#btn-submit-app").onclick = async () => {
      await api("/api/applications/" + id + "/submit", { method: "POST", body: "{}" });
      await loadApps();
      await loadClients();
    };
  }

  async function loadProfile() {
    const p = await api("/api/agent/profile");
    const f = $("#profile-form");
    f.display_name.value = p.display_name || "";
    f.phone.value = p.phone || "";
    f.email.value = p.email || "";
    f.product_prefs.value = p.product_prefs || "";
    f.sales_ready.checked = !!p.sales_ready;
    $("#compliance").textContent = p.compliance_note || "";
  }

  async function runRecommend() {
    const id = $("#reco-client").value;
    if (!id) return;
    $("#reco-out").innerHTML = `<p class="muted">${esc(t("reco_loading"))}</p>`;
    const res = await api(`/api/recommend/client/${id}?top_k=5&lang=${I.getLang()}`);
    const cats = Object.entries(res.category_scores || {});
    $("#reco-cats").innerHTML =
      `<div class="rec-cats-title">${esc(t("reco_cats"))}</div>` +
      cats
        .map(([name, p]) => {
          const pct = Math.round(Number(p) * 100);
          return `<div class="rec-cat-row"><span>${esc(name)}</span><strong>${pct}%</strong>
            <div class="rec-cat-bar"><span style="width:${Math.min(100, pct)}%"></span></div></div>`;
        })
        .join("");
    renderRecCards(res.recommendations || [], "#reco-out", Number(id));
  }

  async function boot() {
    if (!state.token) {
      showApp(false);
      return;
    }
    try {
      state.user = await api("/api/auth/me");
      showApp(true);
      setTab("clients");
      state.priorityFilter = state.priorityFilter || "1";
      state.appStatusFilter = state.appStatusFilter || "draft";
      $("#f-priority").value = state.priorityFilter;
      $("#f-app-status").value = state.appStatusFilter;
      await loadMeta();
      await loadClients();
      await loadApps();
      await loadProfile();
    } catch (ex) {
      console.error("boot failed", ex);
      state.token = "";
      localStorage.removeItem("ad_token");
      showApp(false);
      const err = $("#auth-err");
      err.textContent = t("session_fail") + ": " + (ex.message || ex);
      err.hidden = false;
    }
  }

  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const err = $("#auth-err");
    const btn = e.target.querySelector('button[type="submit"]');
    err.hidden = true;
    if (btn) {
      btn.disabled = true;
      btn.textContent = t("signing_in");
    }
    try {
      const res = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: fd.get("username"), password: fd.get("password") }),
      });
      state.token = res.access_token;
      localStorage.setItem("ad_token", state.token);
      await boot();
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = t("sign_in");
      }
    }
  };

  $("#btn-logout").onclick = () => {
    state.token = "";
    localStorage.removeItem("ad_token");
    showApp(false);
  };

  $$(".tab").forEach((tab) => (tab.onclick = () => setTab(tab.dataset.tab)));
  $("#btn-refresh-clients").onclick = () => loadClients();
  $("#f-priority").onchange = () => {
    state.priorityFilter = $("#f-priority").value;
    loadClients();
  };
  $("#btn-clear-prio").onclick = () => {
    state.priorityFilter = "";
    $("#f-priority").value = "";
    loadClients();
  };
  $("#f-tag").onchange = () => loadClients();
  $("#f-status").onchange = () => loadClients();
  $("#q-clients").onkeydown = (e) => {
    if (e.key === "Enter") loadClients();
  };
  $("#btn-refresh-apps").onclick = () => loadApps();
  $("#f-app-status").onchange = () => {
    state.appStatusFilter = $("#f-app-status").value;
    loadApps();
  };
  $("#btn-clear-app-status").onclick = () => {
    state.appStatusFilter = "";
    $("#f-app-status").value = "";
    loadApps();
  };
  $("#btn-reco").onclick = () => runRecommend().catch((ex) => alert(ex.message));
  $("#rag-form").onsubmit = async (e) => {
    e.preventDefault();
    const q = $("#rag-input").value.trim();
    if (!q) return;
    const mode = ($("#rag-mode") && $("#rag-mode").value) || "auto";
    localStorage.setItem("ad_rag_mode", mode);
    state.ragHistory.push({ role: "user", text: q });
    renderRagThread();
    $("#rag-input").value = "";
    const thr = $("#rag-thread");
    thr.insertAdjacentHTML("beforeend", `<div class="bubble bot" id="rag-wait">${esc(t("rag_wait"))}</div>`);
    thr.scrollTop = thr.scrollHeight;
    try {
      const body = {
        question: q,
        top_k: 4,
        lang: I.getLang(),
        mode,
      };
      const cid = state.selectedId;
      if (cid) body.client_id = Number(cid);
      const res = await api("/api/assistant/ask", {
        method: "POST",
        body: JSON.stringify(body),
      });
      const wait = $("#rag-wait");
      if (wait) wait.remove();
      const answer = res.answer || "";
      state.ragHistory.push({ role: "bot", text: answer, sources: res.chunks_used || [] });
      renderRagThread();
    } catch (err) {
      const wait = $("#rag-wait");
      if (wait) wait.remove();
      state.ragHistory.push({ role: "bot", text: err.message || String(err), error: true });
      renderRagThread();
    }
  };

  const savedRagMode = localStorage.getItem("ad_rag_mode") || "auto";
  if ($("#rag-mode")) $("#rag-mode").value = savedRagMode;
  const ragInput = $("#rag-input");
  if (ragInput) {
    ragInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        $("#rag-form").requestSubmit();
      }
    });
  }
  renderRagThread();

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

  $("#profile-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await api("/api/agent/profile", {
      method: "PATCH",
      body: JSON.stringify({
        display_name: fd.get("display_name"),
        phone: fd.get("phone"),
        email: fd.get("email"),
        product_prefs: fd.get("product_prefs"),
        sales_ready: fd.get("sales_ready") === "on",
      }),
    });
    alert(t("saved"));
  };

  $("#btn-create-quote").onclick = async () => {
    const f = $("#quote-form");
    const clientId = Number(f.client_id.value);
    const productId = Number(f.product_id.value);
    await api("/api/applications", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, product_id: productId, notes: f.notes.value || "" }),
    });
    $("#dlg-quote").close();
    await loadApps();
    await loadClients();
    if (state.selectedId) await openClient(state.selectedId);
    setTab("apps");
  };

  function onLangChange(sel) {
    I.setLang(sel.value);
    applyI18n();
    if (state.token) {
      loadClients().catch(console.error);
      loadApps().catch(console.error);
      if (state.selectedId) openClient(state.selectedId).catch(console.error);
    }
  }
  $("#lang-auth").onchange = (e) => onLangChange(e.target);
  $("#lang-app").onchange = (e) => onLangChange(e.target);

  I.setLang(I.getLang());
  applyI18n();
  boot();
})();
