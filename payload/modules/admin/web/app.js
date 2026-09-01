(() => {
  "use strict";

  const I = window.InsuraI18n;
  const t = (k) => I.t(k);
  const statusLabel = (s) => I.statusLabel(s);

  const state = {
    surface: "client",
    meta: null,
    token: "",
    role: "",
    username: "",
    fullName: "",
    view: "dashboard",
    recDraft: null,
    ragHistory: [],
  };

  const $ = (sel) => document.querySelector(sel);
  const viewEl = () => $("#view");
  const sk = (name) =>
    (state.surface === "admin" ? "ins_admin_" : "ins_client_") + name;

  function loadSessionFromStorage() {
    state.token = localStorage.getItem(sk("token")) || "";
    state.role = localStorage.getItem(sk("role")) || "";
    state.username = localStorage.getItem(sk("user")) || "";
    state.fullName = localStorage.getItem(sk("name")) || "";
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function attr(s) {
    return esc(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function money(n) {
    return new Intl.NumberFormat(I.getLang() === "en" ? "en-US" : "ru-RU").format(n) + " ₽";
  }

  function captureRecDraft() {
    const form = document.getElementById("rec-form");
    if (!form) return state.recDraft;
    const fd = new FormData(form);
    return {
      age: fd.get("age"),
      sex: fd.get("sex"),
      bmi: fd.get("bmi"),
      children: fd.get("children"),
      income: fd.get("income"),
      region: fd.get("region"),
      smoker: fd.get("smoker") === "on",
      has_home: fd.get("has_home") === "on",
      has_auto: fd.get("has_auto") === "on",
      travels: fd.get("travels") === "on",
      building_value: fd.get("building_value"),
      contents_value: fd.get("contents_value"),
      prior_claims: fd.get("prior_claims"),
      coverage_level: fd.get("coverage_level"),
      flood_risk: fd.get("flood_risk"),
      fire_risk: fd.get("fire_risk"),
      vehicle_type: fd.get("vehicle_type"),
      vehicle_usage: fd.get("vehicle_usage"),
      vehicle_value: fd.get("vehicle_value"),
      vehicle_age: fd.get("vehicle_age"),
      vehicle_seats: fd.get("vehicle_seats"),
      engine_ccm: fd.get("engine_ccm"),
      driving_experience: fd.get("driving_experience"),
      annual_mileage: fd.get("annual_mileage"),
      past_accidents: fd.get("past_accidents"),
      speeding_violations: fd.get("speeding_violations"),
      credit_score: fd.get("credit_score"),
      employment_type: fd.get("employment_type"),
      graduate: fd.get("graduate") === "on",
      family_members: fd.get("family_members"),
      chronic_diseases: fd.get("chronic_diseases") === "on",
      frequent_flyer: fd.get("frequent_flyer") === "on",
      ever_travelled_abroad: fd.get("ever_travelled_abroad") === "on",
      travel_duration: fd.get("travel_duration"),
      hadResults: !!(document.getElementById("rec-out") && document.getElementById("rec-out").dataset.ready === "1"),
    };
  }

  function applyRecDraft(form, draft) {
    if (!form || !draft) return;
    const set = (name, val) => {
      const el = form.elements.namedItem(name);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!val;
      else el.value = val;
    };
    [
      "age",
      "sex",
      "bmi",
      "children",
      "income",
      "region",
      "smoker",
      "has_home",
      "has_auto",
      "travels",
      "building_value",
      "contents_value",
      "prior_claims",
      "coverage_level",
      "flood_risk",
      "fire_risk",
      "vehicle_type",
      "vehicle_usage",
      "vehicle_value",
      "vehicle_age",
      "vehicle_seats",
      "engine_ccm",
      "driving_experience",
      "annual_mileage",
      "past_accidents",
      "speeding_violations",
      "credit_score",
      "employment_type",
      "graduate",
      "family_members",
      "chronic_diseases",
      "frequent_flyer",
      "ever_travelled_abroad",
      "travel_duration",
    ].forEach((k) => set(k, draft[k]));
  }

  function refreshChrome() {
    I.applyStatic();
    ["lang-select", "lang-select-auth"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = I.getLang();
    });
    if (state.token) {
      showApp(false);
      renderTabs();
      renderView();
    } else {
      showAuth();
    }
  }

  function bindLangSelects() {
    ["lang-select", "lang-select-auth"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el || el.dataset.bound) return;
      el.dataset.bound = "1";
      el.value = I.getLang();
      el.onchange = () => {
        state.recDraft = captureRecDraft();
        I.setLang(el.value);
        refreshChrome();
      };
    });
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (state.token) headers.Authorization = "Bearer " + state.token;
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = { detail: text }; }
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
      const blob = await apiBlob(`/api/rag/document/${encodeURIComponent(source)}`);
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

  function ragBubbleHtml(message) {
    const sources = Array.isArray(message.sources) ? message.sources : [];
    const sourcesHtml = sources.length
      ? `<div class="rag-sources">
          <div class="rag-sources-title">${esc(t("rag_sources"))}</div>
          ${sources.map((source, index) => `
            <button class="rag-source" type="button"
              data-source="${attr(source.source || "")}" data-page="${attr(source.page_start || 1)}"
              data-excerpt="${attr(source.excerpt || "")}" title="${attr(t("rag_open_document"))}">
              <span class="rag-source-number">${index + 1}</span>
              <span>${esc(source.citation || source.source || "—")}</span>
            </button>`).join("")}
        </div>`
      : "";
    return `<div class="bubble ${message.role === "user" ? "user" : "bot"}${message.error ? " error" : ""}">
      <div>${esc(message.text)}</div>${sourcesHtml}
    </div>`;
  }

  function saveSession(tok) {
    state.token = tok.access_token;
    state.role = tok.role;
    state.username = tok.username;
    state.fullName = tok.full_name;
    localStorage.setItem(sk("token"), state.token);
    localStorage.setItem(sk("role"), state.role);
    localStorage.setItem(sk("user"), state.username);
    localStorage.setItem(sk("name"), state.fullName);
  }

  function clearSession() {
    state.token = "";
    state.role = "";
    state.username = "";
    state.fullName = "";
    state.ragHistory = [];
    state.recDraft = null;
    ["token", "role", "user", "name"].forEach((k) => localStorage.removeItem(sk(k)));
  }

  function applySurfaceUi() {
    const isAdmin = state.surface === "admin";
    document.title = isAdmin ? "InsuraDesk · Админ" : "InsuraDesk";
    const brand = document.querySelector("#landing .brand");
    if (brand) brand.textContent = isAdmin ? "InsuraDesk · Компания" : "InsuraDesk";
    const signupCol = $("#signup-form") && $("#signup-form").closest("div");
    if (signupCol) signupCol.hidden = isAdmin;
    const demoAdmin = $("#demo-admin-btn");
    const demoClient = $("#demo-client-btn");
    if (demoAdmin) demoAdmin.hidden = !isAdmin;
    if (demoClient) demoClient.hidden = isAdmin;
    const loginHeading = document.querySelector("#auth-panel .auth-heading");
    if (loginHeading) {
      loginHeading.textContent = isAdmin ? t("login_title_admin") : t("login_title");
      loginHeading.title = isAdmin ? t("login_hint_admin") : t("login_hint_client");
    }
  }

  function showApp(rerender = true) {
    $("#landing").classList.add("hidden");
    $("#auth-panel").classList.add("hidden");
    $("#app-panel").classList.remove("hidden");
    const name = I.displayFirstName(state.fullName, state.username);
    $("#welcome").textContent = t("hello") + " " + name;
    const roleLine = $("#role-line");
    if (state.role === "admin") {
      roleLine.classList.remove("hidden");
      roleLine.textContent = t("role_admin");
    } else {
      roleLine.textContent = "";
      roleLine.classList.add("hidden");
    }
    I.applyStatic();
    bindLangSelects();
    renderTabs();
    if (rerender) renderView();
  }

  function showAuth() {
    $("#landing").classList.remove("hidden");
    $("#auth-panel").classList.remove("hidden");
    $("#app-panel").classList.add("hidden");
    I.applyStatic();
    bindLangSelects();
  }

  function renderTabs() {
    const tabs =
      state.role === "admin"
        ? [
            ["dashboard", "tab_dashboard"],
            ["customers", "tab_customers"],
            ["categories", "tab_categories"],
            ["policies", "tab_policies"],
            ["applications", "tab_applications"],
            ["claims", "tab_claims"],
            ["agents", "tab_agents"],
            ["companydb", "tab_companydb"],
            ["questions", "tab_questions"],
            ["recommend", "tab_recommend"],
            ["rag", "tab_rag"],
          ]
        : [
            ["dashboard", "tab_dashboard"],
            ["policies", "tab_catalog"],
            ["myPolicies", "tab_my_policies"],
            ["claims", "tab_claims"],
            ["payments", "tab_payments"],
            ["agent", "tab_agent"],
            ["documents", "tab_documents"],
            ["notifications", "tab_notifications"],
            ["recommend", "tab_recommend"],
            ["history", "tab_applications"],
            ["questions", "tab_questions"],
            ["rag", "tab_rag"],
          ];
    $("#nav-tabs").innerHTML = tabs
      .map(
        ([id, key]) =>
          `<button type="button" class="tab ${state.view === id ? "active" : ""}" data-view="${id}">${esc(t(key))}</button>`
      )
      .join("");
    $("#nav-tabs").querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.view = btn.dataset.view;
        renderTabs();
        renderView();
      });
    });
  }

  async function renderView() {
    const el = viewEl();
    el.innerHTML = `<p class='muted'>${esc(t("loading"))}</p>`;
    try {
      if (state.role === "admin") {
        if (state.view === "dashboard") return void (el.innerHTML = await adminDashboard());
        if (state.view === "customers") return void (el.innerHTML = await adminCustomers());
        if (state.view === "categories") return void (el.innerHTML = await adminCategories());
        if (state.view === "policies") return void (el.innerHTML = await adminPolicies());
        if (state.view === "applications") return void (el.innerHTML = await adminApplications());
        if (state.view === "claims") return void (el.innerHTML = await adminClaims());
        if (state.view === "agents") return void (el.innerHTML = await adminAgents());
        if (state.view === "companydb") return void (el.innerHTML = await adminCompanyDb());
        if (state.view === "questions") return void (el.innerHTML = await adminQuestions());
        if (state.view === "recommend") return void renderRecommend();
        if (state.view === "rag") return void renderRag();
      } else {
        if (state.view === "dashboard") return void (el.innerHTML = await customerDashboard());
        if (state.view === "policies") return void (el.innerHTML = await customerPolicies());
        if (state.view === "myPolicies") return void (el.innerHTML = await customerMyPolicies());
        if (state.view === "claims") return void (el.innerHTML = await customerClaims());
        if (state.view === "payments") return void (el.innerHTML = await customerPayments());
        if (state.view === "agent") return void (el.innerHTML = await customerAgent());
        if (state.view === "documents") return void (el.innerHTML = await customerDocuments());
        if (state.view === "notifications") return void (el.innerHTML = await customerNotifications());
        if (state.view === "recommend") return void renderRecommend();
        if (state.view === "history") return void (el.innerHTML = await customerHistory());
        if (state.view === "questions") return void (el.innerHTML = await customerQuestions());
        if (state.view === "rag") return void renderRag();
      }
    } catch (err) {
      el.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  }

  function statsHtml(items) {
    return `<div class="grid-stats">${items
      .map(([v, l]) => `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`)
      .join("")}</div>`;
  }

  async function adminDashboard() {
    const s = await api("/api/admin/dashboard");
    const notes = await api("/api/admin/notifications");
    const noteHtml = notes.length
      ? `<ul>${notes
          .slice(0, 8)
          .map(
            (n) =>
              `<li>${esc(n.message)} <span class="muted">${n.is_read ? "" : esc(t("new_mark"))}</span></li>`
          )
          .join("")}</ul><button class="btn btn-secondary" id="read-notes" type="button">${esc(t("mark_read"))}</button>`
      : `<p class='muted'>${esc(t("no_notifications"))}</p>`;
    setTimeout(() => {
      const btn = $("#read-notes");
      if (btn)
        btn.onclick = async () => {
          await api("/api/admin/notifications/read-all", { method: "POST" });
          renderView();
        };
    }, 0);
    return (
      statsHtml([
        [s.total_customers, t("dash_customers")],
        [s.total_policies, t("dash_policies")],
        [s.total_categories, t("dash_categories")],
        [s.total_applications, t("dash_apps")],
        [s.approved_applications, t("dash_approved")],
        [s.disapproved_applications, t("dash_rejected")],
        [s.pending_applications, t("dash_pending")],
        [s.unread_notifications, t("dash_unread")],
      ]) + `<h3 style="font-family:var(--font-display)">${esc(t("notifications_title"))}</h3>${noteHtml}`
    );
  }

  async function adminCustomers() {
    const rows = await api("/api/admin/customers");
    setTimeout(() => bindCustomerAdmin(rows), 0);
    return `
      <div class="hint">Администратор может добавлять, редактировать и удалять клиентов.</div>
      <form class="stack" id="add-customer" style="margin:14px 0">
        <strong>Новый клиент</strong>
        <label>Логин <input name="username" required /></label>
        <label>Пароль <input name="password" type="password" required /></label>
        <label>Имя <input name="first_name" /></label>
        <label>Фамилия <input name="last_name" /></label>
        <label>Телефон <input name="mobile" /></label>
        <button class="btn btn-primary" type="submit">Добавить</button>
      </form>
      <table><thead><tr><th>ID</th><th>Клиент</th><th>Контакты</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (u) => `<tr>
          <td>${u.id}</td>
          <td>${esc(u.first_name)} ${esc(u.last_name)}<br><span class="muted">${esc(u.username)}</span></td>
          <td>${esc(u.mobile)}<br>${esc(u.address)}</td>
          <td class="row-actions">
            <button class="btn btn-secondary" data-edit="${u.id}" type="button">Изм.</button>
            <button class="btn btn-danger" data-del="${u.id}" type="button">Удал.</button>
          </td></tr>`
        )
        .join("")}</tbody></table>`;
  }

  function bindCustomerAdmin(rows) {
    const form = $("#add-customer");
    if (form)
      form.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        await api("/api/admin/customers", {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(fd.entries())),
        });
        renderView();
      };
    viewEl().querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        if (!confirm("Удалить клиента?")) return;
        await api("/api/admin/customers/" + btn.dataset.del, { method: "DELETE" });
        renderView();
      };
    });
    viewEl().querySelectorAll("[data-edit]").forEach((btn) => {
      btn.onclick = async () => {
        const u = rows.find((x) => String(x.id) === btn.dataset.edit);
        const first_name = prompt("Имя", u.first_name || "");
        if (first_name == null) return;
        const last_name = prompt("Фамилия", u.last_name || "");
        if (last_name == null) return;
        const mobile = prompt("Телефон", u.mobile || "");
        if (mobile == null) return;
        const address = prompt("Адрес", u.address || "");
        if (address == null) return;
        await api("/api/admin/customers/" + u.id, {
          method: "PUT",
          body: JSON.stringify({ first_name, last_name, mobile, address }),
        });
        renderView();
      };
    });
  }

  async function adminCategories() {
    const rows = await api("/api/admin/categories");
    setTimeout(() => {
      const form = $("#add-cat");
      if (form)
        form.onsubmit = async (e) => {
          e.preventDefault();
          const name = new FormData(form).get("name");
          await api("/api/admin/categories", { method: "POST", body: JSON.stringify({ name }) });
          renderView();
        };
      viewEl().querySelectorAll("[data-ren]").forEach((btn) => {
        btn.onclick = async () => {
          const name = prompt("Новое название");
          if (!name) return;
          await api("/api/admin/categories/" + btn.dataset.ren, {
            method: "PUT",
            body: JSON.stringify({ name }),
          });
          renderView();
        };
      });
      viewEl().querySelectorAll("[data-del]").forEach((btn) => {
        btn.onclick = async () => {
          if (!confirm("Удалить категорию и связанные полисы?")) return;
          await api("/api/admin/categories/" + btn.dataset.del, { method: "DELETE" });
          renderView();
        };
      });
    }, 0);
    return `
      <form class="stack" id="add-cat" style="max-width:420px;margin-bottom:14px">
        <label>Категория (жизнь, мед, авто, туризм…) <input name="name" required /></label>
        <button class="btn btn-primary" type="submit">Добавить категорию</button>
      </form>
      <table><thead><tr><th>ID</th><th>Название</th><th>Дата</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (c) => `<tr><td>${c.id}</td><td>${esc(c.name)}</td><td>${esc(c.creation_date)}</td>
          <td class="row-actions">
            <button class="btn btn-secondary" data-ren="${c.id}" type="button">Изм.</button>
            <button class="btn btn-danger" data-del="${c.id}" type="button">Удал.</button>
          </td></tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function adminPolicies() {
    const [policies, categories] = await Promise.all([
      api("/api/admin/policies"),
      api("/api/admin/categories"),
    ]);
    setTimeout(() => bindPolicyAdmin(policies, categories), 0);
    return `
      <form class="stack" id="add-policy" style="margin-bottom:14px">
        <strong>Новый полис</strong>
        <label>Категория
          <select name="category_id">${categories
            .map((c) => `<option value="${c.id}">${esc(c.name)}</option>`)
            .join("")}</select>
        </label>
        <label>Название <input name="name" required /></label>
        <label>Сумма страхования <input name="sum_assurance" type="number" min="0" required /></label>
        <label>Премия <input name="premium" type="number" min="0" required /></label>
        <label>Срок (лет) <input name="tenure" type="number" min="1" value="1" required /></label>
        <label>Описание <textarea name="description"></textarea></label>
        <button class="btn btn-primary" type="submit">Добавить полис</button>
      </form>
      <table><thead><tr><th>Полис</th><th>Категория</th><th>Сумма / премия</th><th></th></tr></thead>
      <tbody>${policies
        .map(
          (p) => `<tr>
          <td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.description || "")}</span></td>
          <td>${esc(p.category_name)}</td>
          <td>${money(p.sum_assurance)} / ${money(p.premium)}<br><span class="muted">${p.tenure} лет</span></td>
          <td class="row-actions">
            <button class="btn btn-secondary" data-edit="${p.id}" type="button">Изм. название</button>
            <button class="btn btn-danger" data-del="${p.id}" type="button">Удал.</button>
          </td></tr>`
        )
        .join("")}</tbody></table>`;
  }

  function bindPolicyAdmin(policies, categories) {
    const form = $("#add-policy");
    if (form)
      form.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const body = Object.fromEntries(fd.entries());
        body.category_id = Number(body.category_id);
        body.sum_assurance = Number(body.sum_assurance);
        body.premium = Number(body.premium);
        body.tenure = Number(body.tenure);
        await api("/api/admin/policies", { method: "POST", body: JSON.stringify(body) });
        renderView();
      };
    viewEl().querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        if (!confirm("Удалить полис?")) return;
        await api("/api/admin/policies/" + btn.dataset.del, { method: "DELETE" });
        renderView();
      };
    });
    viewEl().querySelectorAll("[data-edit]").forEach((btn) => {
      btn.onclick = async () => {
        const p = policies.find((x) => String(x.id) === btn.dataset.edit);
        const name = prompt("Новое название полиса", p.name);
        if (!name) return;
        await api("/api/admin/policies/" + p.id, {
          method: "PUT",
          body: JSON.stringify({
            category_id: p.category_id,
            name,
            sum_assurance: p.sum_assurance,
            premium: p.premium,
            tenure: p.tenure,
            description: p.description || "",
          }),
        });
        renderView();
      };
    });
  }

  async function adminApplications() {
    const rows = await api("/api/admin/applications");
    setTimeout(() => {
      viewEl().querySelectorAll("[data-decide]").forEach((btn) => {
        btn.onclick = async () => {
          const status = btn.dataset.decide;
          const admin_comment = prompt("Комментарий администратора", "") || "";
          await api("/api/admin/applications/" + btn.dataset.id + "/decide", {
            method: "POST",
            body: JSON.stringify({ status, admin_comment }),
          });
          renderView();
        };
      });
    }, 0);
    return `<table><thead><tr><th>Клиент</th><th>Полис</th><th>Статус</th><th>Комментарий</th><th>Дата</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (a) => `<tr>
          <td>${esc(a.customer_name)}</td>
          <td>${esc(a.policy_name)}</td>
          <td><span class="badge ${esc(a.status)}">${esc(statusRu(a.status))}</span></td>
          <td class="cell-note">${esc(a.admin_comment || "—")}</td>
          <td>${esc(a.creation_date)}</td>
          <td class="row-actions">
            ${
              a.status === "Pending"
                ? `<button class="btn btn-secondary" data-decide="Approved" data-id="${a.id}" type="button">${esc(t("approve"))}</button>
                   <button class="btn btn-danger" data-decide="Disapproved" data-id="${a.id}" type="button">${esc(t("reject"))}</button>`
                : ""
            }
          </td></tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function adminQuestions() {
    const rows = await api("/api/admin/questions");
    setTimeout(() => {
      viewEl().querySelectorAll("[data-ans]").forEach((btn) => {
        btn.onclick = async () => {
          const admin_comment = prompt("Ответ клиенту");
          if (!admin_comment) return;
          await api("/api/admin/questions/" + btn.dataset.ans, {
            method: "PUT",
            body: JSON.stringify({ admin_comment }),
          });
          renderView();
        };
      });
    }, 0);
    return `<table><thead><tr><th>Клиент</th><th>Вопрос</th><th>Ответ / статус</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (q) => `<tr>
          <td>${esc(q.customer_name)}</td>
          <td>${esc(q.description)}<br><span class="muted">${esc(q.asked_date)}</span></td>
          <td><span class="badge ${esc(q.status)}">${esc(q.status === "Answered" ? "Отвечен" : "Ожидает")}</span>
            <div>${esc(q.admin_comment)}</div></td>
          <td><button class="btn btn-secondary" data-ans="${q.id}" type="button">Ответить</button></td>
        </tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function customerDashboard() {
    const s = await api("/api/customer/dashboard");
    return (
      statsHtml([
        [s.active_policies || 0, t("dash_active")],
        [s.open_claims || 0, t("dash_open_claims")],
        [s.due_payments || 0, t("dash_due_pay")],
        [s.available_policies, t("dash_catalog")],
        [s.applied_policies, t("dash_apps_short")],
        [s.pending_applications, t("dash_pending")],
        [s.total_questions, t("dash_questions")],
        [s.unread_notifications || 0, t("dash_unread")],
      ])
    );
  }

  async function customerMyPolicies() {
    const rows = await api("/api/customer/my-policies");
    if (!rows.length) {
      return `<p class='muted'>${esc(t("no_my_policies"))}</p>`;
    }
    return `<table><thead><tr><th>${esc(t("col_number"))}</th><th>${esc(t("col_product"))}</th><th>${esc(t("col_period"))}</th><th>${esc(t("rec_col_premium"))}</th><th>${esc(t("col_status"))}</th></tr></thead>
      <tbody>${rows
        .map(
          (p) => `<tr>
          <td><b>${esc(p.policy_number)}</b></td>
          <td>${esc(p.catalog_policy_name)}<br><span class="muted">${esc(p.category_name)}</span></td>
          <td>${esc(p.start_date)} — ${esc(p.end_date)}</td>
          <td>${money(p.premium)} / ${money(p.sum_assurance)}</td>
          <td><span class="badge ${esc(p.status)}">${esc(statusLabel(p.status))}</span></td>
        </tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function customerClaims() {
    const [claims, policies] = await Promise.all([
      api("/api/customer/claims"),
      api("/api/customer/my-policies"),
    ]);
    const active = policies.filter((p) => p.status === "Active");
    setTimeout(() => {
      const form = $("#claim-form");
      if (form)
        form.onsubmit = async (e) => {
          e.preventDefault();
          const fd = new FormData(form);
          await api("/api/customer/claims", {
            method: "POST",
            body: JSON.stringify({
              customer_policy_id: Number(fd.get("customer_policy_id")),
              claim_type: fd.get("claim_type"),
              description: fd.get("description"),
              claim_amount: Number(fd.get("claim_amount") || 0),
            }),
          });
          renderView();
        };
    }, 0);
    const formHtml = active.length
      ? `<form class="stack" id="claim-form" style="max-width:560px;margin-bottom:14px">
          <strong>${esc(t("claim_form"))}</strong>
          <label>${esc(t("col_policy"))}
            <select name="customer_policy_id">${active
              .map(
                (p) =>
                  `<option value="${p.id}">${esc(p.policy_number)} — ${esc(p.catalog_policy_name)}</option>`
              )
              .join("")}</select>
          </label>
          <label>${esc(t("col_type"))}
            <select name="claim_type">
              <option value="accident">${esc(t("claim_accident"))}</option>
              <option value="theft">${esc(t("claim_theft"))}</option>
              <option value="fire">${esc(t("claim_fire"))}</option>
              <option value="other">${esc(t("claim_other"))}</option>
            </select>
          </label>
          <label>${esc(t("claim_amount"))} <input name="claim_amount" type="number" min="0" value="0" /></label>
          <label>${esc(t("claim_desc"))} <textarea name="description" required minlength="5"></textarea></label>
          <button class="btn btn-primary" type="submit">${esc(t("claim_submit"))}</button>
        </form>`
      : `<p class='muted'>${esc(t("need_policy_claim"))}</p>`;
    const claimTypeLabel = (v) =>
      ({ accident: t("claim_accident"), theft: t("claim_theft"), fire: t("claim_fire"), other: t("claim_other") }[
        v
      ] || v);
    return (
      formHtml +
      `<table><thead><tr><th>${esc(t("col_policy"))}</th><th>${esc(t("col_type"))}</th><th>${esc(t("col_amount"))}</th><th>${esc(t("col_status"))}</th><th>${esc(t("col_date"))}</th></tr></thead>
      <tbody>${
        claims.length
          ? claims
              .map(
                (c) => `<tr>
            <td>${esc(c.policy_number)}</td>
            <td>${esc(claimTypeLabel(c.claim_type))}<br><span class="muted">${esc(c.description)}</span></td>
            <td>${money(c.claim_amount)}</td>
            <td><span class="badge ${esc(c.status)}">${esc(statusLabel(c.status))}</span>
              <div class="muted">${esc(c.admin_comment || "")}</div></td>
            <td>${esc(c.claim_date)}</td>
          </tr>`
              )
              .join("")
          : `<tr><td colspan='5' class='muted'>${esc(t("no_claims"))}</td></tr>`
      }</tbody></table>`
    );
  }

  async function customerPayments() {
    const rows = await api("/api/customer/payments");
    setTimeout(() => {
      viewEl().querySelectorAll("[data-pay]").forEach((btn) => {
        btn.onclick = async () => {
          await api("/api/customer/payments/" + btn.dataset.pay + "/pay", { method: "POST" });
          renderView();
        };
      });
    }, 0);
    if (!rows.length) return `<p class='muted'>${esc(t("no_payments"))}</p>`;
    return `<table><thead><tr><th>${esc(t("col_policy"))}</th><th>${esc(t("col_amount"))}</th><th>${esc(t("col_due"))}</th><th>${esc(t("col_status"))}</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (p) => `<tr>
          <td>${esc(p.policy_number)}</td>
          <td>${money(p.amount)}</td>
          <td>${esc(p.due_date)}</td>
          <td><span class="badge ${esc(p.status)}">${esc(statusLabel(p.status))}</span></td>
          <td>${
            p.status === "Paid"
              ? ""
              : `<button class="btn btn-primary" data-pay="${p.id}" type="button">${esc(t("pay"))}</button>`
          }</td>
        </tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function customerAgent() {
    const a = await api("/api/customer/agent");
    if (!a) {
      return `<p class='muted'>${esc(t("no_agent"))}</p>`;
    }
    return `<div class="hint">
      <h3 style="font-family:var(--font-display);margin-top:0">${esc(a.first_name)}</h3>
      <p>${esc(t("specialization"))} ${esc(a.specialization || t("dash"))}</p>
      <p>${esc(t("phone"))}: <b>${esc(a.phone || t("dash"))}</b></p>
      <p>${esc(t("email"))} <b>${esc(a.email || t("dash"))}</b></p>
    </div>`;
  }

  async function customerDocuments() {
    const [docs, policies] = await Promise.all([
      api("/api/customer/documents"),
      api("/api/customer/my-policies"),
    ]);
    setTimeout(() => {
      const form = $("#doc-form");
      if (form)
        form.onsubmit = async (e) => {
          e.preventDefault();
          const fd = new FormData(form);
          await api("/api/customer/documents", {
            method: "POST",
            body: JSON.stringify({
              title: fd.get("title"),
              kind: fd.get("kind"),
              note: fd.get("note") || "",
              customer_policy_id: fd.get("customer_policy_id")
                ? Number(fd.get("customer_policy_id"))
                : null,
            }),
          });
          renderView();
        };
    }, 0);
    return `
      <form class="stack" id="doc-form" style="max-width:560px;margin-bottom:14px">
        <strong>${esc(t("doc_add"))}</strong>
        <label>${esc(t("doc_title"))} <input name="title" required /></label>
        <label>${esc(t("doc_type"))}
          <select name="kind">
            <option value="policy">${esc(t("doc_policy"))}</option>
            <option value="claim">${esc(t("doc_claim"))}</option>
            <option value="payment">${esc(t("doc_payment"))}</option>
            <option value="other">${esc(t("doc_other"))}</option>
          </select>
        </label>
        <label>${esc(t("doc_policy_opt"))}
          <select name="customer_policy_id">
            <option value="">${esc(t("dash"))}</option>
            ${policies.map((p) => `<option value="${p.id}">${esc(p.policy_number)}</option>`).join("")}
          </select>
        </label>
        <label>${esc(t("doc_note"))} <textarea name="note"></textarea></label>
        <button class="btn btn-primary" type="submit">${esc(t("save"))}</button>
      </form>
      <table><thead><tr><th>${esc(t("col_name"))}</th><th>${esc(t("col_type"))}</th><th>${esc(t("col_path"))}</th><th>${esc(t("col_date"))}</th></tr></thead>
      <tbody>${
        docs.length
          ? docs
              .map((d) => {
                const kindMap = {
                  policy: t("doc_policy"),
                  claim: t("doc_claim"),
                  payment: t("doc_payment"),
                  other: t("doc_other"),
                };
                return `<tr>
            <td>${esc(d.title)}</td>
            <td>${esc(kindMap[d.kind] || d.kind)}</td>
            <td class="muted">${esc(d.file_path)}</td>
            <td>${esc(d.uploaded_at)}</td>
          </tr>`;
              })
              .join("")
          : `<tr><td colspan='4' class='muted'>${esc(t("no_docs"))}</td></tr>`
      }</tbody></table>`;
  }

  async function customerNotifications() {
    const rows = await api("/api/customer/notifications");
    setTimeout(() => {
      const btn = $("#read-cust-notes");
      if (btn)
        btn.onclick = async () => {
          await api("/api/customer/notifications/read-all", { method: "POST" });
          renderView();
        };
    }, 0);
    return (
      `<button class="btn btn-secondary" id="read-cust-notes" type="button">${esc(t("mark_read"))}</button>` +
      (rows.length
        ? `<ul>${rows
            .map(
              (n) =>
                `<li>${esc(n.message)} <span class="muted">${n.is_read ? "" : esc(t("new_mark"))}</span></li>`
            )
            .join("")}</ul>`
        : `<p class='muted'>${esc(t("no_notifications"))}</p>`)
    );
  }

  async function adminClaims() {
    const rows = await api("/api/admin/claims");
    setTimeout(() => {
      viewEl().querySelectorAll("[data-cdecide]").forEach((btn) => {
        btn.onclick = async () => {
          const admin_comment = prompt("Комментарий", "") || "";
          await api("/api/admin/claims/" + btn.dataset.id + "/decide", {
            method: "POST",
            body: JSON.stringify({ status: btn.dataset.cdecide, admin_comment }),
          });
          renderView();
        };
      });
    }, 0);
    return `<table><thead><tr><th>${esc(t("col_client"))}</th><th>${esc(t("col_policy"))}</th><th>${esc(t("col_claim"))}</th><th>${esc(t("col_status"))}</th><th></th></tr></thead>
      <tbody>${
        rows.length
          ? rows
              .map(
                (c) => `<tr>
            <td>${esc((c.customer_name || "").split(/\s+/)[0] || c.customer_name)}</td>
            <td>${esc(c.policy_number)}</td>
            <td>${esc(c.claim_type)} · ${money(c.claim_amount)}<br><span class="muted">${esc(
                  c.description
                )}</span></td>
            <td><span class="badge ${esc(c.status)}">${esc(statusLabel(c.status))}</span></td>
            <td class="row-actions">
              <button class="btn btn-secondary" data-cdecide="Approved" data-id="${c.id}" type="button">${esc(t("approve"))}</button>
              <button class="btn btn-danger" data-cdecide="Denied" data-id="${c.id}" type="button">${esc(t("reject"))}</button>
              <button class="btn btn-primary" data-cdecide="Paid" data-id="${c.id}" type="button">${esc(t("settled"))}</button>
            </td>
          </tr>`
              )
              .join("")
          : `<tr><td colspan='5' class='muted'>${esc(t("no_claims_admin"))}</td></tr>`
      }</tbody></table>`;
  }

  async function adminAgents() {
    const [agents, customers] = await Promise.all([
      api("/api/admin/agents"),
      api("/api/admin/customers"),
    ]);
    setTimeout(() => {
      const add = $("#add-agent");
      if (add)
        add.onsubmit = async (e) => {
          e.preventDefault();
          const fd = new FormData(add);
          await api("/api/admin/agents", {
            method: "POST",
            body: JSON.stringify(Object.fromEntries(fd.entries())),
          });
          renderView();
        };
      const asg = $("#assign-agent");
      if (asg)
        asg.onsubmit = async (e) => {
          e.preventDefault();
          const fd = new FormData(asg);
          await api("/api/admin/agents/assign", {
            method: "POST",
            body: JSON.stringify({
              customer_id: Number(fd.get("customer_id")),
              agent_id: Number(fd.get("agent_id")),
            }),
          });
          alert(t("agent_assigned"));
          renderView();
        };
    }, 0);
    return `
      <form class="stack" id="add-agent" style="max-width:480px;margin-bottom:14px">
        <strong>${esc(t("new_agent"))}</strong>
        <label>${esc(t("first_name"))} <input name="first_name" required /></label>
        <label>${esc(t("last_name"))} <input name="last_name" /></label>
        <label>${esc(t("email")).replace(":", "")} <input name="email" /></label>
        <label>${esc(t("phone"))} <input name="phone" /></label>
        <label>${esc(t("col_spec"))} <input name="specialization" /></label>
        <button class="btn btn-primary" type="submit">${esc(t("add"))}</button>
      </form>
      <form class="stack" id="assign-agent" style="max-width:480px;margin-bottom:14px">
        <strong>${esc(t("assign_agent"))}</strong>
        <label>${esc(t("col_client"))}
          <select name="customer_id">${customers
            .map(
              (c) =>
                `<option value="${c.id}">${esc(c.username)} — ${esc(c.first_name)}</option>`
            )
            .join("")}</select>
        </label>
        <label>${esc(t("col_agent"))}
          <select name="agent_id">${agents
            .map((a) => `<option value="${a.id}">${esc(a.first_name)}</option>`)
            .join("")}</select>
        </label>
        <button class="btn btn-secondary" type="submit">${esc(t("assign"))}</button>
      </form>
      <table><thead><tr><th>ID</th><th>${esc(t("col_agent"))}</th><th>${esc(t("col_contacts"))}</th><th>${esc(t("col_spec"))}</th></tr></thead>
      <tbody>${agents
        .map(
          (a) => `<tr>
          <td>${a.id}</td>
          <td>${esc(a.first_name)}</td>
          <td>${esc(a.phone)}<br>${esc(a.email)}</td>
          <td>${esc(a.specialization)}</td>
        </tr>`
        )
        .join("")}</tbody></table>`;
  }

  function cdbTableLabel(key) {
    const k = "cdb_t_" + key;
    const v = t(k);
    return v === k ? key : v;
  }

  function cdbFieldLabel(key) {
    const k = "cdb_f_" + key;
    const v = t(k);
    return v === k ? key : v;
  }

  async function adminCompanyDb() {
    let health;
    try {
      health = await api("/api/admin/company/health");
    } catch (err) {
      return `<p class="error">${esc(err.message)}</p>
        <p class="muted">${esc(t("cdb_up_hint"))}</p>`;
    }
    let overview = null;
    let errMsg = "";
    if (health.ok) {
      try {
        overview = await api("/api/admin/company/overview");
      } catch (err) {
        errMsg = err.message;
      }
    }
    const tables = (overview && overview.tables) || {};
    const tableRows = Object.keys(tables)
      .sort()
      .map((k) => `<tr><td>${esc(cdbTableLabel(k))}</td><td>${tables[k]}</td></tr>`)
      .join("");

    async function loadEntity(path) {
      const res = await api("/api/admin/company/" + path);
      const items = res.items || [];
      if (!items.length) return `<p class="muted">${esc(t("cdb_no_rows"))}</p>`;
      const cols = Object.keys(items[0]);
      return `<p class="muted">${esc(t("cdb_total"))}: ${res.total ?? items.length}</p>
        <table><thead><tr>${cols.map((c) => `<th>${esc(cdbFieldLabel(c))}</th>`).join("")}</tr></thead>
        <tbody>${items
          .map(
            (r) =>
              `<tr>${cols.map((c) => `<td>${esc(r[c] == null ? "" : String(r[c]))}</td>`).join("")}</tr>`
          )
          .join("")}</tbody></table>`;
    }

    setTimeout(() => {
      const refreshBtn = $("#company-refresh");
      if (refreshBtn)
        refreshBtn.onclick = async () => {
          refreshBtn.disabled = true;
          refreshBtn.classList.add("is-spinning");
          try {
            await renderView();
          } catch (e) {
            alert(e.message);
            refreshBtn.disabled = false;
            refreshBtn.classList.remove("is-spinning");
          }
        };
      const sel = $("#company-entity");
      const box = $("#company-entity-box");
      const show = async () => {
        if (!sel || !box) return;
        box.innerHTML = `<p class="muted">${esc(t("cdb_loading"))}</p>`;
        try {
          box.innerHTML = await loadEntity(sel.value);
        } catch (e) {
          box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
        }
      };
      if (sel) {
        sel.onchange = show;
        if (health.ok) show();
      }
    }, 0);

    const refreshIcon = `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false"><path fill="currentColor" d="M17.65 6.35A7.95 7.95 0 0 0 12 4V1L7 6l5 5V7c2.76 0 5 2.24 5 5a5 5 0 0 1-8.66 3.54l-1.42 1.42A6.97 6.97 0 0 0 12 19c3.87 0 7-3.13 7-7 0-1.93-.78-3.68-2.05-4.95zM6 12c0-.7.13-1.37.35-2H3.26A7.98 7.98 0 0 0 4 12c0 3.87 3.13 7 7 7v-2a5 5 0 0 1-5-5z"/></svg>`;

    return `
      <div class="stack" style="gap:14px">
        ${errMsg ? `<p class="error">${esc(errMsg)}</p>` : !health.ok ? `<p class="error">${esc(health.message || t("cdb_db_down"))}</p>` : ""}
        <div>
          <div class="company-db-head">
            <strong>${esc(t("cdb_tables"))}</strong>
            <button class="btn-icon" type="button" id="company-refresh" title="${esc(t("cdb_refresh"))}" aria-label="${esc(t("cdb_refresh"))}">${refreshIcon}</button>
          </div>
          <table><thead><tr><th>${esc(t("cdb_col_table"))}</th><th>${esc(t("cdb_col_rows"))}</th></tr></thead><tbody>${tableRows || `<tr><td colspan="2" class="muted">${esc(t("cdb_no_data"))}</td></tr>`}</tbody></table>
        </div>
        <div>
          <label>${esc(t("cdb_entity"))}
            <select id="company-entity">
              <option value="clients">${esc(t("cdb_t_client"))}</option>
              <option value="employees">${esc(t("cdb_t_employee"))}</option>
              <option value="branches">${esc(t("cdb_t_branch"))}</option>
              <option value="phones">${esc(t("cdb_t_phone"))}</option>
              <option value="insurances">${esc(t("cdb_t_insurance"))}</option>
              <option value="claims">${esc(t("cdb_t_claim"))}</option>
              <option value="payments">${esc(t("cdb_t_payment"))}</option>
            </select>
          </label>
          <div id="company-entity-box" style="margin-top:10px"></div>
        </div>
      </div>`;
  }

  async function customerPolicies() {
    const rows = await api("/api/customer/policies");
    setTimeout(() => {
      viewEl().querySelectorAll("[data-apply]").forEach((btn) => {
        btn.onclick = async () => {
          await api("/api/customer/applications/" + btn.dataset.apply, { method: "POST" });
          alert(t("applied_pending"));
          state.view = "history";
          renderTabs();
          renderView();
        };
      });
    }, 0);
    return `<table><thead><tr><th>${esc(t("col_policy"))}</th><th>${esc(t("col_category"))}</th><th>${esc(t("col_sum_prem"))}</th><th></th></tr></thead>
      <tbody>${rows
        .map(
          (p) => `<tr>
          <td><b>${esc(p.name)}</b><br><span class="muted">${esc(p.description || "")}</span></td>
          <td>${esc(p.category_name)}</td>
          <td>${money(p.sum_assurance)} / ${money(p.premium)} · ${p.tenure} ${esc(t("years"))}</td>
          <td><button class="btn btn-primary" data-apply="${p.id}" type="button">${esc(t("apply"))}</button></td>
        </tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function customerHistory() {
    const rows = await api("/api/customer/history");
    if (!rows.length) return `<p class='muted'>${esc(t("no_apps"))}</p>`;
    return `<table><thead><tr><th>${esc(t("col_policy"))}</th><th>${esc(t("col_status"))}</th><th>${esc(t("col_comment"))}</th><th>${esc(t("col_date"))}</th></tr></thead>
      <tbody>${rows
        .map(
          (a) => `<tr>
          <td>${esc(a.policy_name)}</td>
          <td><span class="badge ${esc(a.status)}">${esc(statusRu(a.status))}</span></td>
          <td>${esc(a.admin_comment || t("dash"))}</td>
          <td>${esc(a.creation_date)}</td>
        </tr>`
        )
        .join("")}</tbody></table>`;
  }

  async function customerQuestions() {
    const rows = await api("/api/customer/questions");
    setTimeout(() => {
      const form = $("#ask-q");
      if (form)
        form.onsubmit = async (e) => {
          e.preventDefault();
          const description = new FormData(form).get("description");
          await api("/api/customer/questions", {
            method: "POST",
            body: JSON.stringify({ description }),
          });
          renderView();
        };
    }, 0);
    return `
      <form class="stack" id="ask-q" style="max-width:560px;margin-bottom:14px">
        <label>${esc(t("ask_admin"))}
          <textarea name="description" required minlength="3"></textarea>
        </label>
        <button class="btn btn-primary" type="submit">${esc(t("send_question"))}</button>
      </form>
      <table><thead><tr><th>${esc(t("col_question"))}</th><th>${esc(t("col_answer"))}</th><th>${esc(t("col_date"))}</th></tr></thead>
      <tbody>${rows
        .map(
          (q) => `<tr>
          <td>${esc(q.description)}</td>
          <td><span class="badge ${esc(q.status)}">${esc(q.status === "Answered" ? t("answered") : t("waiting"))}</span>
            <div>${esc(q.admin_comment)}</div></td>
          <td>${esc(q.asked_date)}</td>
        </tr>`
        )
        .join("") || `<tr><td colspan='3' class='muted'>${esc(t("no_questions"))}</td></tr>`}</tbody></table>`;
  }

  function statusRu(s) {
    return statusLabel(s);
  }

  async function renderRecommend() {
    const el = viewEl();
    let st;
    try {
      st = await api("/api/recommender/status");
    } catch (err) {
      el.innerHTML = `<p class="error">${esc(err.message)}</p>`;
      return;
    }
    const isAdmin = state.role === "admin";
    const d = state.recDraft || {
      age: "35",
      sex: "male",
      bmi: "26",
      children: "1",
      income: "90000",
      region: "southeast",
      smoker: false,
      has_home: true,
      has_auto: false,
      travels: false,
      building_value: "400000",
      contents_value: "80000",
      prior_claims: "0",
      coverage_level: "Silver",
      flood_risk: "0.3",
      fire_risk: "0.3",
      vehicle_type: "Automobile",
      vehicle_usage: "Private",
      vehicle_value: "280000",
      vehicle_age: "8",
      vehicle_seats: "4",
      engine_ccm: "1600",
      driving_experience: "10-19y",
      annual_mileage: "12000",
      past_accidents: "0",
      speeding_violations: "0",
      credit_score: "0.55",
      employment_type: "private",
      graduate: true,
      family_members: "2",
      chronic_diseases: false,
      frequent_flyer: false,
      ever_travelled_abroad: false,
      travel_duration: "7",
      hadResults: true,
    };
    const opt = (name, val, labelKey) =>
      `<option value="${esc(val)}"${String(d[name]) === String(val) ? " selected" : ""}>${esc(t(labelKey))}</option>`;

    el.innerHTML = `
      <form class="rec-form" id="rec-form">
        <div class="rec-checks">
          <label class="check-row"><input name="smoker" type="checkbox"${d.smoker ? " checked" : ""} /> ${esc(t("smoker"))}</label>
          <label class="check-row"><input name="has_home" type="checkbox" id="rec-has-home"${d.has_home ? " checked" : ""} /> ${esc(t("has_home"))}</label>
          <label class="check-row"><input name="has_auto" type="checkbox" id="rec-has-auto"${d.has_auto ? " checked" : ""} /> ${esc(t("has_auto"))}</label>
          <label class="check-row"><input name="travels" type="checkbox" id="rec-travels"${d.travels ? " checked" : ""} /> ${esc(t("travels"))}</label>
        </div>

        <table class="rec-table" id="rec-columns">
          <thead>
            <tr>
              <th scope="col">${esc(t("rec_sec_profile"))}</th>
              <th scope="col" class="rec-home-only"${d.has_home ? "" : " hidden"}>${esc(t("rec_sec_home"))}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><label>${esc(t("age"))}<input name="age" type="number" value="${esc(String(d.age ?? "35"))}" min="18" max="100" /></label></td>
              <td class="rec-home-only"${d.has_home ? "" : " hidden"}><label>${esc(t("building_value"))}<input name="building_value" type="number" value="${esc(String(d.building_value ?? "400000"))}" min="0" /></label></td>
            </tr>
            <tr>
              <td><label>${esc(t("sex"))}
                <select name="sex">
                  <option value="male"${d.sex === "male" ? " selected" : ""}>${esc(t("sex_male"))}</option>
                  <option value="female"${d.sex === "female" ? " selected" : ""}>${esc(t("sex_female"))}</option>
                </select>
              </label></td>
              <td class="rec-home-only"${d.has_home ? "" : " hidden"}><label>${esc(t("contents_value"))}<input name="contents_value" type="number" value="${esc(String(d.contents_value ?? "80000"))}" min="0" /></label></td>
            </tr>
            <tr>
              <td><label>${esc(t("bmi"))}<input name="bmi" type="number" step="0.1" value="${esc(String(d.bmi ?? "26"))}" /></label></td>
              <td class="rec-home-only"${d.has_home ? "" : " hidden"}><label>${esc(t("prior_claims"))}<input name="prior_claims" type="number" value="${esc(String(d.prior_claims ?? "0"))}" min="0" max="20" /></label></td>
            </tr>
            <tr>
              <td><label>${esc(t("children"))}<input name="children" type="number" value="${esc(String(d.children ?? "1"))}" min="0" /></label></td>
              <td class="rec-home-only"${d.has_home ? "" : " hidden"}><label>${esc(t("coverage_level"))}
                <select name="coverage_level">
                  ${opt("coverage_level", "Bronze", "cov_bronze")}
                  ${opt("coverage_level", "Silver", "cov_silver")}
                  ${opt("coverage_level", "Gold", "cov_gold")}
                  ${opt("coverage_level", "Platinum", "cov_platinum")}
                </select>
              </label></td>
            </tr>
            <tr>
              <td><label>${esc(t("income"))}<input name="income" type="number" value="${esc(String(d.income ?? "90000"))}" min="0" /></label></td>
              <td class="rec-home-only"${d.has_home ? "" : " hidden"}><label>${esc(t("flood_risk"))}<input name="flood_risk" type="number" step="0.01" min="0" max="1" value="${esc(String(d.flood_risk ?? "0.3"))}" /></label></td>
            </tr>
            <tr>
              <td><label>${esc(t("region"))}
                <select name="region">
                  ${opt("region", "northeast", "region_northeast")}
                  ${opt("region", "northwest", "region_northwest")}
                  ${opt("region", "southeast", "region_southeast")}
                  ${opt("region", "southwest", "region_southwest")}
                </select>
              </label></td>
              <td class="rec-home-only"${d.has_home ? "" : " hidden"}><label>${esc(t("fire_risk"))}<input name="fire_risk" type="number" step="0.01" min="0" max="1" value="${esc(String(d.fire_risk ?? "0.3"))}" /></label></td>
            </tr>
          </tbody>
        </table>

        <div class="rec-travel" id="rec-auto-block"${d.has_auto ? "" : " hidden"}>
          <div class="rec-travel-title">${esc(t("rec_sec_auto"))}</div>
          <div class="rec-travel-grid">
            <label>${esc(t("vehicle_type"))}
              <select name="vehicle_type">
                ${opt("vehicle_type", "Automobile", "vtype_auto")}
                ${opt("vehicle_type", "Pick-up", "vtype_pickup")}
                ${opt("vehicle_type", "Station Wagones", "vtype_station")}
                ${opt("vehicle_type", "Motor-cycle", "vtype_moto")}
              </select>
            </label>
            <label>${esc(t("vehicle_usage"))}
              <select name="vehicle_usage">
                ${opt("vehicle_usage", "Private", "vusage_private")}
                ${opt("vehicle_usage", "Own Goods", "vusage_goods")}
              </select>
            </label>
            <label>${esc(t("vehicle_value"))}<input name="vehicle_value" type="number" value="${esc(String(d.vehicle_value ?? "280000"))}" min="0" /></label>
            <label>${esc(t("vehicle_age"))}<input name="vehicle_age" type="number" value="${esc(String(d.vehicle_age ?? "8"))}" min="0" max="40" /></label>
            <label>${esc(t("driving_experience"))}
              <select name="driving_experience">
                ${opt("driving_experience", "0-9y", "drive_0_9")}
                ${opt("driving_experience", "10-19y", "drive_10_19")}
                ${opt("driving_experience", "20-29y", "drive_20_29")}
                ${opt("driving_experience", "30y+", "drive_30")}
              </select>
            </label>
            <label>${esc(t("annual_mileage"))}<input name="annual_mileage" type="number" value="${esc(String(d.annual_mileage ?? "12000"))}" min="0" /></label>
            <label>${esc(t("past_accidents"))}<input name="past_accidents" type="number" value="${esc(String(d.past_accidents ?? "0"))}" min="0" max="20" /></label>
            <label>${esc(t("speeding_violations"))}<input name="speeding_violations" type="number" value="${esc(String(d.speeding_violations ?? "0"))}" min="0" max="50" /></label>
            <label>${esc(t("vehicle_seats"))}<input name="vehicle_seats" type="number" value="${esc(String(d.vehicle_seats ?? "4"))}" min="1" max="60" /></label>
            <label>${esc(t("engine_ccm"))}<input name="engine_ccm" type="number" value="${esc(String(d.engine_ccm ?? "1600"))}" min="0" /></label>
            <label>${esc(t("credit_score"))}<input name="credit_score" type="number" step="0.01" min="0" max="1" value="${esc(String(d.credit_score ?? "0.55"))}" /></label>
          </div>
        </div>

        <div class="rec-travel" id="rec-travel-block"${d.travels ? "" : " hidden"}>
          <div class="rec-travel-title">${esc(t("rec_sec_travel"))}</div>
          <div class="rec-travel-grid">
            <label>${esc(t("employment_type"))}
              <select name="employment_type">
                ${opt("employment_type", "private", "emp_private")}
                ${opt("employment_type", "government", "emp_government")}
              </select>
            </label>
            <label>${esc(t("family_members"))}<input name="family_members" type="number" value="${esc(String(d.family_members ?? "2"))}" min="1" max="20" /></label>
            <label>${esc(t("travel_duration"))}<input name="travel_duration" type="number" value="${esc(String(d.travel_duration ?? "7"))}" min="1" /></label>
            <label class="check-row"><input name="graduate" type="checkbox"${d.graduate ? " checked" : ""} /> ${esc(t("graduate"))}</label>
            <label class="check-row"><input name="chronic_diseases" type="checkbox"${d.chronic_diseases ? " checked" : ""} /> ${esc(t("chronic_diseases"))}</label>
            <label class="check-row"><input name="frequent_flyer" type="checkbox"${d.frequent_flyer ? " checked" : ""} /> ${esc(t("frequent_flyer"))}</label>
            <label class="check-row"><input name="ever_travelled_abroad" type="checkbox"${d.ever_travelled_abroad ? " checked" : ""} /> ${esc(t("ever_travelled_abroad"))}</label>
          </div>
        </div>

        <div class="rec-form-actions">
          <button class="btn btn-primary" type="submit"${st.ready ? "" : " disabled"}>${esc(t("rec_submit"))}</button>
        </div>
      </form>
      <div id="rec-out" style="margin-top:14px"></div>`;

    const form = $("#rec-form");
    if (!form) return;

    const syncBlocks = () => {
      const table = $("#rec-columns");
      const travel = $("#rec-travel-block");
      const auto = $("#rec-auto-block");
      const hasHome = form.elements.namedItem("has_home");
      const hasAuto = form.elements.namedItem("has_auto");
      const travelsEl = form.elements.namedItem("travels");
      const showHome = !!(hasHome && hasHome.checked);
      document.querySelectorAll(".rec-home-only").forEach((node) => {
        node.hidden = !showHome;
      });
      if (travel && travelsEl) travel.hidden = !travelsEl.checked;
      if (auto && hasAuto) auto.hidden = !hasAuto.checked;
      if (table) table.classList.toggle("is-single", !showHome);
    };
    syncBlocks();
    ["rec-has-home", "rec-has-auto", "rec-travels"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.onchange = syncBlocks;
    });

    function qualityFooter(_res, stSnap) {
      const models = stSnap.metrics && stSnap.metrics.models ? stSnap.metrics.models : {};
      const cat = models.category_recommender || {};
      const labels = {
        medical_premium: "мед.",
        home_premium: "имущество",
        travel_premium: "туризм",
        auto_premium: "авто",
        travel_propensity: t("model_travel_propensity"),
        auto_claim_risk: t("model_auto_claim_risk"),
      };
      const bits = [];
      if (cat.n_rows != null && cat.accuracy != null) {
        bits.push(`категории: ${cat.n_rows} пр., точность ${Number(cat.accuracy).toFixed(3)}`);
      }
      ["travel_propensity", "auto_claim_risk"].forEach((k) => {
        const m = models[k];
        if (m && m.roc_auc != null) bits.push(`${labels[k]} AUC=${Number(m.roc_auc).toFixed(2)}`);
      });
      Object.keys(labels).forEach((k) => {
        if (k === "travel_propensity" || k === "auto_claim_risk") return;
        const m = models[k];
        if (!m || m.r2 == null || Number(m.r2) < 0.2) return;
        bits.push(`${labels[k]} R²=${Number(m.r2).toFixed(2)}`);
      });
      return bits.length ? `<p class="rec-quality">${esc(bits.join(" · "))}</p>` : "";
    }

    async function runRecommend() {
      state.recDraft = captureRecDraft();
      const fd = new FormData(form);
      const body = {
        age: Number(fd.get("age")),
        sex: fd.get("sex"),
        bmi: Number(fd.get("bmi")),
        children: Number(fd.get("children")),
        income: Number(fd.get("income")),
        region: fd.get("region") || "southeast",
        smoker: fd.get("smoker") === "on",
        has_home: fd.get("has_home") === "on",
        has_auto: fd.get("has_auto") === "on",
        travels: fd.get("travels") === "on",
        building_value: Number(fd.get("building_value") || 400000),
        contents_value: Number(fd.get("contents_value") || 80000),
        prior_claims: Number(fd.get("prior_claims") || 0),
        coverage_level: fd.get("coverage_level") || "Silver",
        flood_risk: Number(fd.get("flood_risk") || 0.3),
        fire_risk: Number(fd.get("fire_risk") || 0.3),
        vehicle_type: fd.get("vehicle_type") || "Automobile",
        vehicle_usage: fd.get("vehicle_usage") || "Private",
        vehicle_value: Number(fd.get("vehicle_value") || 280000),
        vehicle_age: Number(fd.get("vehicle_age") || 8),
        vehicle_seats: Number(fd.get("vehicle_seats") || 4),
        engine_ccm: Number(fd.get("engine_ccm") || 1600),
        driving_experience: fd.get("driving_experience") || "10-19y",
        annual_mileage: Number(fd.get("annual_mileage") || 12000),
        past_accidents: Number(fd.get("past_accidents") || 0),
        speeding_violations: Number(fd.get("speeding_violations") || 0),
        credit_score: Number(fd.get("credit_score") || 0.55),
        employment_type: fd.get("employment_type") || "private",
        graduate: fd.get("graduate") === "on",
        family_members: Number(fd.get("family_members") || Number(fd.get("children") || 0) + 1),
        chronic_diseases: fd.get("chronic_diseases") === "on" ? 1 : 0,
        frequent_flyer: fd.get("frequent_flyer") === "on",
        ever_travelled_abroad: fd.get("ever_travelled_abroad") === "on",
        travel_duration: Number(fd.get("travel_duration") || 7),
        top_k: 5,
        lang: I.getLang(),
      };
      const out = $("#rec-out");
      out.innerHTML = `<p class='muted'>${esc(t("rec_loading"))}</p>`;
      try {
        const res = await api("/api/recommender/recommend", {
          method: "POST",
          body: JSON.stringify(body),
        });

        const recCards = (res.recommendations || [])
          .map(
            (r) => `<article class="rec-card">
              <div class="rec-card-main">
                <div class="rec-card-title">
                  <b>${esc(r.policy_name)}</b>
                  <span class="muted">${esc(r.category)}</span>
                </div>
                <div class="rec-card-meta">
                  <span>${money(r.premium)}</span>
                  <span class="rec-match">${(r.score * 100).toFixed(0)}%</span>
                </div>
                <div class="rec-card-why muted">${esc((r.reasons || [])[0] || "")}</div>
              </div>
              ${
                state.role === "customer"
                  ? `<button class="btn btn-primary rec-card-btn" data-apply="${r.policy_id}" type="button">${esc(t("rec_apply"))}</button>`
                  : ""
              }
            </article>`
          )
          .join("");

        let adminExtras = "";
        if (isAdmin) {
          const cats = Object.entries(res.category_probabilities || {}).filter(([, p]) => Number(p) >= 0.08);
          const catHtml = cats
            .map(([name, p]) => {
              const pct = Math.round(Number(p) * 1000) / 10;
              return `<div class="rec-cat-row"><span>${esc(name)}</span><strong>${pct}%</strong>
                <div class="rec-cat-bar"><span style="width:${Math.min(100, pct)}%"></span></div></div>`;
            })
            .join("");
          const tpLine =
            res.travel_propensity != null || res.auto_claim_risk != null
              ? `<p class="muted" style="margin:0 0 8px">${
                  res.travel_propensity != null
                    ? `${esc(t("travel_propensity_label"))}: <b>${(Number(res.travel_propensity) * 100).toFixed(0)}%</b>`
                    : ""
                }${
                  res.travel_propensity != null && res.auto_claim_risk != null ? " · " : ""
                }${
                  res.auto_claim_risk != null
                    ? `${esc(t("auto_claim_risk_label"))}: <b>${(Number(res.auto_claim_risk) * 100).toFixed(0)}%</b>`
                    : ""
                }</p>`
              : "";
          adminExtras = `${tpLine}<div class="rec-cats" style="margin-bottom:10px">${catHtml}</div>`;
        }

        out.dataset.ready = "1";
        if (state.recDraft) state.recDraft.hadResults = true;
        out.innerHTML = `
          ${isAdmin ? adminExtras : ""}
          <div class="rec-list">${recCards || `<p class="muted">—</p>`}</div>
          ${isAdmin ? qualityFooter(res, st) : ""}`;

        out.querySelectorAll("[data-apply]").forEach((btn) => {
          btn.onclick = async () => {
            await api("/api/customer/applications/" + btn.dataset.apply, { method: "POST" });
            alert(t("applied_ok"));
            state.view = "history";
            renderTabs();
            renderView();
          };
        });
      } catch (err) {
        out.dataset.ready = "0";
        out.innerHTML = `<p class="error">${esc(err.message)}</p>`;
      }
    }

    form.onsubmit = async (e) => {
      e.preventDefault();
      await runRecommend();
    };
    if (st.ready) await runRecommend();
  }

  async function renderRag() {
    const el = viewEl();
    let status = {};
    try {
      status = await api("/api/rag/status");
    } catch (err) {
      el.innerHTML = `<p class="error">${esc(err.message)}</p>`;
      return;
    }
    const ollamaReady = !!(status.ollama && status.ollama.model_ready);
    const gigaReady = !!(status.gigachat && status.gigachat.available);
    const savedMode = localStorage.getItem("ins_rag_mode") || "auto";
    const history = Array.isArray(state.ragHistory) ? state.ragHistory : [];
    const threadHtml = history.length
      ? history
          .map(ragBubbleHtml)
          .join("")
      : `<div class="bubble bot">${esc(t("rag_greeting"))}</div>`;

    el.innerHTML = `
      <div class="chat">
        <div class="chat-thread" id="rag-thread">${threadHtml}</div>
        <form class="chat-composer" id="rag-form">
          <textarea id="rag-input" rows="2" required placeholder="${esc(t("rag_placeholder"))}"></textarea>
          <div class="chat-composer-bar">
            <select id="rag-mode" title="${esc(t("rag_mode"))}" aria-label="${esc(t("rag_mode"))}">
              <option value="auto">${esc(t("rag_mode_auto"))}</option>
              <option value="extractive">${esc(t("rag_mode_extractive"))}</option>
              <option value="ollama"${ollamaReady ? "" : " disabled"}>${esc(t("rag_mode_ollama"))}</option>
              <option value="gigachat"${gigaReady ? "" : " disabled"}>${esc(t("rag_mode_gigachat"))}</option>
            </select>
            <div class="chat-composer-actions">
              <span class="chat-ollama-status ${ollamaReady ? "is-ready" : "is-down"}" title="${esc(
                ollamaReady
                  ? t("rag_ollama_ready") + (status.ollama.model ? ` · ${status.ollama.model}` : "")
                  : t("rag_ollama_down")
              )}">${esc(
                ollamaReady
                  ? (status.ollama.model || t("rag_ollama_ready"))
                  : t("rag_ollama_down")
              )}</span>
              <button class="btn btn-primary" type="submit">${esc(t("rag_ask"))}</button>
            </div>
          </div>
        </form>
      </div>`;

    const thread = $("#rag-thread");
    if (thread) thread.scrollTop = thread.scrollHeight;

    const modeSel = $("#rag-mode");
    if (modeSel) {
      const modeReady = { auto: true, extractive: true, ollama: ollamaReady, gigachat: gigaReady };
      modeSel.value = modeReady[savedMode] ? savedMode : "auto";
      modeSel.onchange = () => localStorage.setItem("ins_rag_mode", modeSel.value);
    }

    const input = $("#rag-input");
    if (input) {
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && !ev.shiftKey) {
          ev.preventDefault();
          $("#rag-form").requestSubmit();
        }
      });
    }

    $("#rag-form").onsubmit = async (e) => {
      e.preventDefault();
      const q = $("#rag-input").value.trim();
      if (!q) return;
      const mode = ($("#rag-mode") && $("#rag-mode").value) || "auto";
      localStorage.setItem("ins_rag_mode", mode);
      if (!Array.isArray(state.ragHistory)) state.ragHistory = [];
      state.ragHistory.push({ role: "user", text: q });
      const thr = $("#rag-thread");
      thr.insertAdjacentHTML("beforeend", `<div class="bubble user">${esc(q)}</div>`);
      $("#rag-input").value = "";
      thr.insertAdjacentHTML(
        "beforeend",
        `<div class="bubble bot" id="rag-wait">${esc(t("rag_wait"))}</div>`
      );
      thr.scrollTop = thr.scrollHeight;
      try {
        const res = await api("/api/rag/ask", {
          method: "POST",
          body: JSON.stringify({ question: q, top_k: 4, lang: I.getLang(), mode }),
        });
        const wait = $("#rag-wait");
        if (wait) wait.remove();
        const answer = res.answer || "";
        const message = { role: "bot", text: answer, sources: res.chunks_used || [] };
        state.ragHistory.push(message);
        thr.insertAdjacentHTML("beforeend", ragBubbleHtml(message));
        thr.scrollTop = thr.scrollHeight;
      } catch (err) {
        const wait = $("#rag-wait");
        if (wait) wait.remove();
        const msg = err.message || String(err);
        state.ragHistory.push({ role: "bot", text: msg, error: true });
        thr.insertAdjacentHTML(
          "beforeend",
          `<div class="bubble bot error">${esc(msg)}</div>`
        );
        thr.scrollTop = thr.scrollHeight;
      }
    };
  }

  document.addEventListener("click", (event) => {
    const source = event.target.closest && event.target.closest(".rag-source");
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

  // auth forms
  async function doLogin(username, password) {
    const err = $("#login-error");
    err.classList.add("hidden");
    try {
      const tok = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      saveSession(tok);
      state.view = "dashboard";
      showApp();
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
    }
  }

  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await doLogin(String(fd.get("username") || "").trim(), String(fd.get("password") || ""));
  };

  const demoAdmin = $("#demo-admin-btn");
  if (demoAdmin) {
    demoAdmin.onclick = async () => {
      const u = $("#login-username");
      const p = $("#login-password");
      if (u) u.value = "admin";
      if (p) p.value = "admin123";
      await doLogin("admin", "admin123");
    };
  }
  const demoClient = $("#demo-client-btn");
  if (demoClient) {
    demoClient.onclick = async () => {
      const u = $("#login-username");
      const p = $("#login-password");
      if (u) u.value = "client";
      if (p) p.value = "client123";
      await doLogin("client", "client123");
    };
  }

  $("#signup-form").onsubmit = async (e) => {
    e.preventDefault();
    const err = $("#signup-error");
    err.classList.add("hidden");
    try {
      const fd = new FormData(e.target);
      const tok = await api("/api/auth/signup", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(fd.entries())),
      });
      saveSession(tok);
      state.view = "dashboard";
      showApp();
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
    }
  };

  $("#logout-btn").onclick = () => {
    clearSession();
    showAuth();
  };

  document.querySelectorAll("[data-scroll]").forEach((btn) => {
    btn.onclick = () => {
      const t = document.getElementById(btn.dataset.scroll);
      if (t) t.scrollIntoView({ behavior: "smooth" });
    };
  });

  bindLangSelects();
  I.applyStatic();

  (async () => {
    try {
      state.meta = await api("/api/meta");
      state.surface = state.meta.surface === "admin" ? "admin" : "client";
    } catch (_) {
      state.surface = "client";
      state.meta = {
        surface: "client",
        client_url: "http://127.0.0.1:8000/",
        admin_url: "http://127.0.0.1:8003/",
      };
    }
    loadSessionFromStorage();
    applySurfaceUi();
    if (!state.token) return showAuth();
    try {
      const me = await api("/api/auth/me");
      if (state.surface === "admin" && me.role !== "admin") {
        clearSession();
        return showAuth();
      }
      if (state.surface === "client" && me.role === "admin") {
        clearSession();
        return showAuth();
      }
      showApp();
    } catch (_) {
      clearSession();
      showAuth();
    }
  })();
})();
