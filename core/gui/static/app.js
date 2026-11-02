/* ModularGS web UI - vanilla JS, no build step. */
"use strict";

/* ---------------- helpers ---------------- */

function $(sel, root) { return (root || document).querySelector(sel); }

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (typeof v === "boolean") { if (v) el.setAttribute(k, ""); }
      else if (v !== null && v !== undefined) el.setAttribute(k, v);
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const err = new Error((data && data.detail) || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

const getJSON = (p) => api(p);
const postJSON = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const putJSON = (p, body) => api(p, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const delJSON = (p) => api(p, { method: "DELETE" });

function fmtBytes(n) {
  if (!n && n !== 0) return "--";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(i ? 2 : 0) + " " + units[i];
}

function fmtDuration(s) {
  s = Math.round(s || 0);
  const d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  const pad = (x) => String(x).padStart(2, "0");
  return `${pad(d)}:${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg, type) {
  const box = $("#toasts");
  const t = h("div", { class: "toast " + (type || "") }, msg);
  box.append(t);
  setTimeout(() => t.remove(), 5000);
}

function confirmModal({ title, message, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const backdrop = $("#modal-backdrop");
    const modal = $("#modal");
    modal.innerHTML = "";
    modal.append(
      h("h3", null, title),
      h("div", { class: "modal-msg" }, message),
      h("div", { class: "modal-actions" },
        h("button", { class: "btn", onclick: () => { backdrop.classList.add("hidden"); resolve(false); } }, "Cancel"),
        h("button", { class: "btn " + (danger ? "danger" : "primary"), onclick: () => { backdrop.classList.remove("hidden"); resolve(true); } }, confirmLabel),
      ),
    );
    backdrop.classList.remove("hidden");
  });
}

/* Handle the 409 needs_force signature flow: returns response data or null if user cancelled. */
async function withSignatureCheck(err, retryFn) {
  if (!err.data || !err.data.needs_force) throw err;
  const ok = await confirmModal({
    title: "Signature verification FAILED",
    message: `${esc(err.data.detail || "")} This file may have been modified or comes from an untrusted source. Proceed anyway?`,
    confirmLabel: "Proceed anyway",
    danger: true,
  });
  if (!ok) return null;
  return retryFn();
}

/* ---------------- log console (WebSocket) ---------------- */

function classifyLine(line) {
  if (/error|failed|exception|traceback/i.test(line)) return "err";
  if (/success|completed|ok$|valid/i.test(line)) return "ok";
  if (/warning|warn|deprecated/i.test(line)) return "warn";
  return "";
}

function attachLogConsole(container, jobId, opts) {
  const onDone = (opts && opts.onDone) || (() => {});
  container.innerHTML = "";
  const consoleEl = h("div", { class: "log-console" });
  const statusLine = h("div", { class: "row", style: "margin-bottom:8px" });
  container.append(statusLine, consoleEl);

  let autoscroll = true;
  consoleEl.addEventListener("scroll", () => {
    autoscroll = consoleEl.scrollTop + consoleEl.clientHeight >= consoleEl.scrollHeight - 30;
  });

  function appendLine(line) {
    consoleEl.append(h("div", { class: "log-line " + classifyLine(line) }, line));
    if (autoscroll) consoleEl.scrollTop = consoleEl.scrollHeight;
  }

  function renderStatus(job) {
    statusLine.innerHTML = "";
    if (job.status === "running") {
      statusLine.append(h("span", { class: "spinner" }), h("span", { style: "margin-left:8px" }, ` Running (pid ${job.pid}, ${fmtDuration(job.duration_s)})`));
    } else {
      const label = { success: "Finished successfully", failed: `Finished with errors (exit code ${job.returncode})`, stopped: "Stopped by user" }[job.status] || job.status;
      statusLine.append(h("span", { class: "badge " + (job.status === "success" ? "ok" : "err") }, label));
    }
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/jobs/${jobId}`);

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "log") msg.lines.forEach(appendLine);
    if (msg.type === "status") {
      renderStatus(msg.job);
      if (msg.job.status !== "running") onDone(msg.job);
    }
    if (msg.type === "error") toast(msg.detail, "error");
  };
  ws.onerror = () => { toast("Log stream error", "error"); };
  return ws;
}

/* ---------------- view: Run Pipeline (home) ---------------- */

async function viewHome(view) {
  view.append(h("h2", null, "Run a Pipeline"), h("p", { class: "subtitle" }, "Select a pipeline, tweak parameters and launch it. Logs stream live."));

  let pipelines;
  try { pipelines = (await getJSON("/api/pipelines")).pipelines; }
  catch (e) { view.append(h("div", { class: "card" }, "Failed to load pipelines: " + e.message)); return; }

  if (!pipelines.length) { view.append(h("div", { class: "empty-state" }, "No pipelines found in pipelines/.")); return; }

  const card = h("div", { class: "card" });
  view.append(card);

  const runnable = pipelines.filter((p) => p.runnable);
  const select = h("select", null,
    h("option", { value: "" }, "-- select a pipeline --"),
    pipelines.map((p) => h("option", {
      value: p.name,
      disabled: !p.runnable,
    }, `${p.title || p.name}${p.runnable ? "" : " (missing: " + p.missing_methods.join(", ") + ")"}`)),
  );

  const refreshBtn = h("button", { class: "btn", onclick: () => renderHomeBody(card, null) }, "Refresh");
  card.append(h("div", { class: "row" }, h("div", { style: "flex:1" }, h("div", { class: "field" }, h("label", null, "Pipeline"), select)), refreshBtn));

  const body = h("div");
  card.append(body);
  select.addEventListener("change", () => renderHomeBody(body, select.value || null));

  // Default: first runnable pipeline
  if (runnable.length) { select.value = runnable[0].name; renderHomeBody(body, runnable[0].name); }

  async function renderHomeBody(container, name) {
    container.innerHTML = "";
    if (!name) return;
    let p;
    try { p = await getJSON("/api/pipelines/" + encodeURIComponent(name)); }
    catch (e) { container.append(h("div", { class: "badge err" }, "Load error: " + e.message)); return; }

    if (p.description) container.append(h("p", { class: "muted", style: "margin-bottom:14px" }, p.description));

    const state = {
      overrides: {},
      filterEnabled: "filter_opacity_threshold" in (p.global_options || {}),
      filterThreshold: (p.global_options || {}).filter_opacity_threshold ?? 0.1,
    };

    // Global options (opacity filter)
    if ("filter_opacity_threshold" in p.global_options || true) {
      const go = h("details", { style: "margin-bottom:14px" }, h("summary", null, "Global Options"));
      const cb = h("input", { type: "checkbox", id: "use-filter" });
      cb.checked = state.filterEnabled;
      cb.addEventListener("change", () => { state.filterEnabled = cb.checked; thrWrap.style.display = cb.checked ? "" : "none"; });
      const num = h("input", { type: "number", min: "0", max: "1", step: "0.01", id: "filter-thr" });
      num.value = state.filterThreshold;
      num.addEventListener("input", () => { state.filterThreshold = parseFloat(num.value); });
      const thrWrap = h("div", { class: "field" }, h("label", null, "Opacity Threshold"), num);
      go.append(h("div", { class: "field" }, h("label", { class: "row", style: "gap:8px" }, cb, "Use opacity filter")), thrWrap);
      thrWrap.style.display = state.filterEnabled ? "" : "none";
      container.append(go);
    }

    // Override parameters
    const overKeys = Object.keys(p.overrides || {});
    if (overKeys.length) {
      const ov = h("div", { style: "margin-bottom:14px" }, h("h4", null, "Override Parameters"));
      for (const key of overKeys) {
        const def = p.overrides[key];
        let input;
        if (typeof def === "boolean") {
          input = h("input", { type: "checkbox" });
          input.checked = def;
          input.dataset.type = "bool";
        } else if (typeof def === "number") {
          input = h("input", { type: "number", step: "any" });
          input.value = def;
          input.dataset.type = "number";
        } else {
          input = h("input", { type: "text" });
          input.value = def;
          input.dataset.type = "string";
        }
        input.dataset.key = key;
        state.overrides[key] = input;
        ov.append(h("div", { class: "field" }, h("label", null, key), input));
      }
      container.append(ov);
    } else {
      container.append(h("p", { class: "muted" }, "No parameters found in the pipeline steps to override."));
    }

    // Input selection
    let inputs;
    try { inputs = (await getJSON("/api/inputs")).groups; } catch (e) { inputs = []; }
    const inputSel = h("select", null, h("option", { value: "" }, "-- none --"));
    for (const g of inputs) {
      inputSel.append(h("option", { value: g.folder }, `${g.folder || "/"} (${g.type}, ${g.total_size_readable}, ${g.files.length} files)`));
    }
    container.append(h("div", { class: "field" }, h("label", null, "Input data (from inputs/)"), inputSel));

    // Output name + status check
    const outInput = h("input", { type: "text" });
    const outStatus = h("div", { style: "margin:6px 0" });
    const modeRow = h("div", { class: "field", style: "display:none" });

    function updateOutStatus() {
      const val = outInput.value.trim();
      modeRow.style.display = "none";
      outStatus.innerHTML = "";
      if (!val) return;
      getJSON("/api/outputs/status?path=" + encodeURIComponent(val)).then((st) => {
        if (!st.exists) { outStatus.append(h("span", { class: "muted" }, "Output path does not exist yet. It will be created.")); return; }
        if (st.empty) { outStatus.append(h("span", { class: "badge warn" }, "Exists, empty")); return; }
        modeRow.style.display = "";
        outStatus.append(h("span", { class: "badge warn" }, `Exists with ${st.entries_count} entries${st.detected_steps.length ? " (steps: " + st.detected_steps.join(", ") + ")" : ""}`));
      }).catch(() => {});
    }
    let deb;
    outInput.addEventListener("input", () => { clearTimeout(deb); deb = setTimeout(updateOutStatus, 300); });

    outInput.addEventListener("input", () => { outInput.dataset.auto = "false"; });

    const modeRestart = h("input", { type: "radio", name: "run-mode", value: "restart" });
    const modeResume = h("input", { type: "radio", name: "run-mode", value: "resume" });
    modeResume.checked = true;
    modeRow.append(
      h("label", null, modeRestart, " Restart (overwrite existing output)"),
      h("label", null, modeResume, " Resume (skip completed steps)"),
    );

    outInput.value = inputSel.value ? `output/${inputSel.value.replace(/[^\w-]/g, "_")}_${name}` : "";
    container.append(
      h("div", { class: "field" }, h("label", null, "Output name (relative to project root)"), outInput, outStatus),
      modeRow,
    );
    updateOutStatus();

    // Auto-suggest output name when the input changes
    inputSel.addEventListener("change", () => {
      if (outInput.dataset.auto !== "false") {
        const base = inputSel.value ? inputSel.value.replace(/[^\w-]/g, "_") : "input";
        outInput.value = `output/${base}_${name}`;
        updateOutStatus();
      }
    });

    // Start button + job panel
    const jobPanel = h("div", { style: "margin-top:14px" });
    const startBtn = h("button", { class: "btn primary" }, "Start Pipeline");
    startBtn.addEventListener("click", async () => {
      const overrides = {};
      for (const [key, input] of Object.entries(state.overrides)) {
        if (input.dataset.type === "bool") overrides[key] = input.checked;
        else if (input.dataset.type === "number") overrides[key] = input.value === "" ? null : parseFloat(input.value);
        else {
          let v = input.value;
          if (v.toLowerCase() === "true") overrides[key] = true;
          else if (v.toLowerCase() === "false") overrides[key] = false;
          else overrides[key] = v;
        }
      }
      const payload = {
        pipeline: name,
        input: inputSel.value || null,
        output: outInput.value.trim() || null,
        overrides,
        filter_enabled: state.filterEnabled,
        filter_threshold: state.filterThreshold,
        run_mode: modeRestart.checked ? "restart" : "resume",
        force: false,
      };
      try {
        let resp;
        try { resp = await postJSON("/api/pipelines/run", payload); }
        catch (e) {
          const retried = await withSignatureCheck(e, () => postJSON("/api/pipelines/run", { ...payload, force: true }));
          if (!retried) return;
          resp = retried;
        }
        renderJobPanel(jobPanel, resp.job_id, name, () => setTimeout(() => renderHomeBody(container, name), 800));
        toast("Pipeline started", "success");
      } catch (e) { toast("Failed to start: " + e.message, "error"); }
    });
    container.append(h("div", { class: "row" }, startBtn), jobPanel);
  }
}

/* Shared job panel: log console + stop button. */
function renderJobPanel(container, jobId, label, onDone) {
  container.innerHTML = "";
  const logWrap = h("div", { style: "margin-top:10px" });
  const stopBtn = h("button", { class: "btn danger" }, "Stop");
  stopBtn.addEventListener("click", async () => {
    stopBtn.disabled = true;
    try { await postJSON(`/api/jobs/${jobId}/stop`); toast("Stopping job...", "warn"); }
    catch (e) { toast("Stop failed: " + e.message, "error"); stopBtn.disabled = false; }
  });
  container.append(
    h("div", { class: "row", style: "margin-top:16px" }, h("strong", null, `Job: ${label} `), h("span", { class: "muted mono" }, jobId), stopBtn),
    logWrap,
  );
  attachLogConsole(logWrap, jobId, { onDone: (job) => { stopBtn.disabled = true; onDone && onDone(job); } });
}

/* ---------------- view: Manage Methods ---------------- */

async function viewMethods(view) {
  view.append(h("h2", null, "Manage Methods"), h("p", { class: "subtitle" }, "Install, validate and uninstall methods. Operations run as background jobs with live logs."));

  let data;
  try { data = await getJSON("/api/methods"); }
  catch (e) { view.append(h("div", { class: "card" }, "Failed to load methods: " + e.message)); return; }

  const s = data.summary;
  view.append(h("div", { class: "card row" },
    h("span", null, `Total: `, h("strong", null, s.total)),
    h("span", null, `Installed: `, h("strong", null, s.installed)),
    h("span", null, `Disk usage: `, h("strong", null, s.disk_usage)),
  ));

  const jobPanel = h("div");
  view.append(jobPanel);

  for (const [category, methods] of Object.entries(data.categories)) {
    const card = h("div", { class: "card" }, h("h3", null, "📂 " + category.toUpperCase()));
    for (const m of methods) card.append(methodRow(m));
    view.append(card);
  }

  function methodRow(m) {
    const actions = h("div", { class: "m-actions" });
    const refresh = () => setTimeout(() => viewMethods(view), 600);

    if (!m.installed) {
      actions.append(h("button", {
        class: "btn primary small",
        onclick: () => runMethodAction(m, "install", refresh),
      }, "Install"));
    } else {
      actions.append(
        h("button", { class: "btn small", onclick: () => runMethodAction(m, "validate", refresh) }, "Validate"),
        h("button", { class: "btn danger small", onclick: async () => {
          const ok = await confirmModal({ title: "Uninstall method", message: `Remove '${m.title}'? This deletes its environment and cloned repositories.`, confirmLabel: "Uninstall", danger: true });
          if (ok) runMethodAction(m, "uninstall", refresh);
        } }, "Uninstall"),
      );
    }
    if (m.installed && m.has_help) {
      actions.append(h("button", { class: "btn small", onclick: () => runMethodAction(m, "help") }, "Show Arguments"));
    }

    return h("div", { class: "method-row" },
      h("div", { class: "m-info" },
        h("div", { class: "m-title" }, m.title, " ",
          m.installed ? h("span", { class: "badge ok" }, "Installed") : h("span", { class: "badge err" }, "Not installed"),
          !m.signature_valid ? h("span", { class: "badge warn", title: "Signature verification failed" }, "unsigned") : null,
        ),
        h("div", { class: "m-desc" }, m.description),
        m.url ? h("a", { class: "link", href: m.url, target: "_blank", rel: "noopener" }, m.url) : null,
      ),
      actions,
    );
  }

  async function runMethodAction(m, action, refresh) {
    try {
      const endpoint = `/api/methods/${encodeURIComponent(m.id)}/${action}`;
      let resp;
      try { resp = await postJSON(endpoint, { force: false }); }
      catch (e) {
        const retried = await withSignatureCheck(e, () => postJSON(endpoint, { force: true }));
        if (!retried) return;
        resp = retried;
      }
      if (action === "help") {
        renderJobPanel(jobPanel, resp.job_id, `${action} ${m.id}`, () => toast("Done", "success"));
      } else {
        renderJobPanel(jobPanel, resp.job_id, `${action} ${m.id}`, () => { toast(`${action} completed`, "success"); refresh(); });
      }
    } catch (e) { toast(`${action} failed: ` + e.message, "error"); }
  }
}

/* ---------------- view: Pipeline Manager ---------------- */

async function viewPipelines(view) {
  view.append(h("h2", null, "Pipeline Manager"), h("p", { class: "subtitle" }, "Inspect and edit pipeline definitions. Saving a pipeline invalidates its TOML signature."));

  let data;
  try { data = (await getJSON("/api/pipelines")).pipelines; }
  catch (e) { view.append(h("div", { class: "card" }, "Failed to load: " + e.message)); return; }

  for (const p of data) {
    const card = h("div", { class: "card" });
    const head = h("div", { class: "row", style: "justify-content:space-between; margin-bottom:8px" },
      h("strong", null, p.parse_error ? p.name + " (parse error)" : (p.title || p.name)),
      p.parse_error
        ? h("span", { class: "badge err" }, "Parse error")
        : (p.runnable ? h("span", { class: "badge ok" }, "Ready") : h("span", { class: "badge err" }, "Missing: " + p.missing_methods.join(", "))),
    );
    card.append(head);

    // Tool chain: Step1 → Step2 → ... with per-method install state
    if (!p.parse_error && p.steps && p.steps.length) {
      const chain = h("div", { class: "row", style: "margin-bottom:10px; align-items:center" });
      p.steps.forEach((s, i) => {
        if (i > 0) chain.append(h("span", { class: "muted" }, " → "));
        chain.append(h("span", {
          class: "badge " + (s.installed ? "ok" : "err"),
          title: s.installed ? `${s.method_id} installed` : `${s.method_id} NOT installed`,
        }, `${s.name}: ${s.method_id || "?"}`));
      });
      card.append(chain);
    }

    const details = h("details", null, h("summary", null, "Details / edit"));
    card.append(details);
    view.append(card);
    if (p.parse_error) { details.append(h("p", { class: "badge err" }, p.parse_error)); continue; }

    if (p.description) details.append(h("p", { class: "muted", style: "margin-bottom:10px" }, p.description));

    // Step kwargs editor
    const stepInputs = {};
    for (const step of p.steps || []) {
      const block = h("div", { class: "step-block" }, h("h4", null, `${step.name} — ${step.method_id || ""}`));
      const kv = {};
      for (const [k, v] of Object.entries(step.overridable)) {
        let input;
        if (typeof v === "boolean") {
          input = h("input", { type: "checkbox" });
          input.checked = v;
          input.dataset.type = "bool";
        } else if (typeof v === "number") {
          input = h("input", { type: "number", step: "any" });
          input.value = v;
          input.dataset.type = "number";
        } else {
          input = h("input", { type: "text" });
          input.value = v;
          input.dataset.type = "string";
        }
        kv[k] = input;
        block.append(h("div", { class: "field" }, h("label", null, k), input));
      }
      const addBtn = h("button", { class: "btn small" }, "+ Add parameter");
      const newKey = h("input", { type: "text", placeholder: "parameter name", style: "width:180px" });
      const newVal = h("input", { type: "text", placeholder: "value", style: "width:120px" });
      addBtn.addEventListener("click", () => {
        const key = newKey.value.trim();
        if (!key || key in kv) return;
        const input = h("input", { type: "text" });
        input.dataset.type = "string";
        kv[key] = input;
        block.insertBefore(h("div", { class: "field" }, h("label", null, key), input), addBtn.parentElement);
      });
      block.append(h("div", { class: "field row" }, newKey, newVal, addBtn));
      stepInputs[step.name] = kv;
      details.append(block);
    }

    // Global options editor
    let filterCb = null, filterThr = null;
    const goDetails = h("details", null, h("summary", null, "Global Options"));
    if (p.global_options && ("filter_opacity_threshold" in p.global_options || Object.keys(p.global_options).length === 0)) {
      filterCb = h("input", { type: "checkbox" });
      filterCb.checked = "filter_opacity_threshold" in p.global_options;
      filterThr = h("input", { type: "number", min: "0", max: "1", step: "0.01" });
      filterThr.value = p.global_options.filter_opacity_threshold ?? 0.1;
      const wrap = h("div", { class: "field" }, h("label", null, "Opacity Threshold"), filterThr);
      filterCb.addEventListener("change", () => { wrap.style.display = filterCb.checked ? "" : "none"; });
      wrap.style.display = filterCb.checked ? "" : "none";
      goDetails.append(h("div", { class: "field" }, h("label", { class: "row", style: "gap:8px" }, filterCb, "Use opacity filter")), wrap);
      details.append(goDetails);
    }

    details.append(h("div", { class: "field" }, h("button", { class: "btn primary", onclick: () => savePipeline(p, stepInputs, filterCb, filterThr) }, "Save changes to " + p.file)));
  }

  async function savePipeline(p, stepInputs, filterCb, filterThr) {
    const step_kwargs = {};
    for (const [stepName, kv] of Object.entries(stepInputs)) {
      const vals = {};
      for (const [k, input] of Object.entries(kv)) {
        if (input.dataset.type === "bool") vals[k] = input.checked;
        else if (input.dataset.type === "number") vals[k] = input.value === "" ? 0 : parseFloat(input.value);
        else {
          const v = input.value;
          vals[k] = v.toLowerCase() === "true" ? true : v.toLowerCase() === "false" ? false : v;
        }
      }
      step_kwargs[stepName] = vals;
    }
    const body = {
      step_kwargs,
      filter_enabled: filterCb ? filterCb.checked : null,
      filter_threshold: filterThr ? parseFloat(filterThr.value) : null,
    };
    try {
      await putJSON("/api/pipelines/" + encodeURIComponent(p.name), body);
      toast("Pipeline saved (signature invalidated)", "success");
      setTimeout(() => viewPipelines(view), 500);
    } catch (e) { toast("Save failed: " + e.message, "error"); }
  }
}

/* ---------------- view: Inputs ---------------- */

async function viewInputs(view) {
  view.append(h("h2", null, "Inputs"), h("p", { class: "subtitle" }, "Upload files or manage the inputs/ folder contents. Each input should live in its own subfolder."));

  const card = h("div", { class: "card" });

  // Upload zone
  const folderInput = h("input", { type: "text", placeholder: "destination subfolder (optional)" });
  const fileInput = h("input", { type: "file", multiple: true, style: "display:none" });
  const progress = h("div", { class: "progress-bar", style: "display:none" }, h("div"));
  const zone = h("div", { class: "upload-zone" },
    h("div", null, "Drag & drop files here, or click to select"),
    h("div", { class: "muted", style: "margin-top:4px; font-size:12px" }, "Uploads to: inputs/ + folder above"),
    progress,
  );
  zone.addEventListener("click", () => fileInput.click());
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    uploadFiles([...e.dataTransfer.files]);
  });
  fileInput.addEventListener("change", () => uploadFiles([...fileInput.files]));

  function uploadFiles(files) {
    if (!files.length) return;
    const folder = folderInput.value.trim();
    let done = 0;
    const bar = progress.firstChild;
    progress.style.display = "";
    for (const f of files) {
      const xhr = new XMLHttpRequest();
      const fd = new FormData();
      fd.append("file", f);
      xhr.upload.addEventListener("progress", (e) => {
        const total = files.reduce((a, x) => a + x.size, 0);
        bar.style.width = `${Math.min(100, ((done + e.loaded / (f.size || 1)) / files.length) * 100)}%`;
      });
      xhr.addEventListener("load", () => {
        if (xhr.status >= 400) { toast(`Upload failed: ${f.name}`, "error"); return; }
        done++;
        if (done === files.length) {
          toast(`Uploaded ${done} file(s)`, "success");
          progress.style.display = "none";
          bar.style.width = "0";
          fileInput.value = "";
          setTimeout(() => viewInputs(view), 400);
        }
      });
      xhr.addEventListener("error", () => toast(`Upload failed: ${f.name}`, "error"));
      xhr.open("POST", `/api/inputs/upload?folder=${encodeURIComponent(folder)}`);
      xhr.send(fd);
    }
  }

  card.append(
    h("div", { class: "upload-zone-wrap" }, zone, fileInput),
    h("div", { class: "field", style: "margin-top:10px" }, h("label", null, "Destination subfolder"), folderInput),
    h("div", { class: "row" },
      h("button", { class: "btn", onclick: () => postJSON("/api/inputs/open", { path: "" }).catch((e) => toast(e.message, "error")) }, "📂 Open Inputs Folder"),
    ),
  );
  view.append(card);

  let data;
  try { data = (await getJSON("/api/inputs")).groups; }
  catch (e) { view.append(h("div", { class: "card" }, "Failed to load inputs: " + e.message)); return; }
  if (!data.length) { view.append(h("div", { class: "empty-state" }, "No files in inputs/.")); return; }

  for (const g of data) {
    const cardG = h("div", { class: "card" });
    cardG.append(
      h("div", { class: "row", style: "justify-content:space-between" },
        h("div", null,
          h("strong", null, "/" + (g.folder || "")),
          h("div", { class: "muted", style: "font-size:12px" }, `${g.type} — ${g.total_size_readable} — ${g.files.length} files`),
        ),
        h("div", { class: "row" },
          h("button", { class: "btn small", onclick: () => postJSON("/api/inputs/open", { path: g.folder }).catch((e) => toast(e.message, "error")) }, "📂 Open"),
          h("button", { class: "btn danger small", onclick: async () => {
            const ok = await confirmModal({ title: "Delete input", message: `Delete '/${g.folder || ""}' and all its files?`, confirmLabel: "Delete", danger: true });
            if (!ok) return;
            try { await delJSON("/api/inputs?folder=" + encodeURIComponent(g.folder)); toast("Deleted", "success"); viewInputs(view); }
            catch (e) { toast("Delete failed: " + e.message, "error"); }
          } }, "🗑 Delete"),
        ),
      ),
      h("details", null, h("summary", null, "Files"),
        h("div", { class: "mono" }, g.files.map((f) => `${f.name} (${fmtBytes(f.size)})`)),
      ),
    );
    view.append(cardG);
  }
}

/* ---------------- view: Outputs ---------------- */

async function viewOutputs(view) {
  view.append(
    h("h2", null, "Outputs"),
    h("p", { class: "subtitle" },
      "Preview splats and sparse reconstructions with the integrated viewers. For editing, use the ",
      h("a", { class: "link", href: "https://superspl.at/editor", target: "_blank", rel: "noopener" }, "Supersplat editor"),
      ".",
    ),
  );

  let data;
  try { data = (await getJSON("/api/outputs")).runs; }
  catch (e) { view.append(h("div", { class: "card" }, "Failed to load outputs: " + e.message)); return; }
  if (!data.length) { view.append(h("div", { class: "empty-state" }, "No runs in output/.")); return; }

  for (const run of data) {
    const card = h("div", { class: "card" });
    card.append(h("div", { class: "row", style: "justify-content:space-between; margin-bottom:6px" },
      h("div", null, h("strong", null, run.name), h("div", { class: "muted mono" }, run.path)),
      h("div", { class: "row" },
        h("button", { class: "btn small", onclick: () => openPath(run.path) }, "📂 Project Folder"),
        run.ply_path ? h("button", { class: "btn small", onclick: () => openViewer("viewer_splat.html", run.name) }, "👁 Splat") : null,
        h("button", {
          class: "btn small",
          disabled: !run.sfm_points,
          title: run.sfm_points ? "View sparse point cloud" : "No points3D.ply/.bin found in this run",
          onclick: () => openViewer("viewer_sfm.html", run.name),
        }, "👁 SfM"),
        run.sfm_path ? h("button", { class: "btn small", onclick: () => openPath(run.sfm_path) }, "📂 SFM Files") : null,
        h("button", { class: "btn danger small", onclick: async () => {
          const ok = await confirmModal({ title: "Delete run", message: `Delete '${run.name}' and all its outputs? This cannot be undone.`, confirmLabel: "Delete", danger: true });
          if (!ok) return;
          try { await delJSON("/api/outputs/" + encodeURIComponent(run.name)); toast("Deleted", "success"); viewOutputs(view); }
          catch (e) { toast("Delete failed: " + e.message, "error"); }
        } }, "🗑 Delete"),
      ),
    ));

    if (run.summary && run.summary._pipeline_summary) {
      const s = run.summary._pipeline_summary;
      const det = h("details", { class: "run-summary" }, h("summary", null, "Pipeline Summary"));
      const rows = [];
      if (s.end_time) rows.push(h("div", null, `End time: ${s.end_time}`));
      rows.push(h("div", null, `Total duration: ${s.total_duration || fmtDuration(s.total_duration_s)}`));
      if (s.original_splats != null) rows.push(h("div", null, `Original splats: ${s.original_splats}`));
      if (s.filtered_splats != null) rows.push(h("div", null, `Filtered splats: ${s.filtered_splats}`));
      for (const m of s.methods_used || []) rows.push(h("div", null, `${m.step}: ${m.method}`));
      det.append(...rows);
      if (s.overrides_applied) {
        det.append(h("details", null, h("summary", null, "Overrides applied"), h("pre", { class: "mono" }, JSON.stringify(s.overrides_applied, null, 2))));
      }
      card.append(det);
    }
    view.append(card);
  }

  async function openPath(path) {
    try { await postJSON("/api/outputs/open", { path }); }
    catch (e) { toast("Open failed: " + e.message, "error"); }
  }

  function openViewer(page, runName) {
    window.open(`/${page}?run=${encodeURIComponent(runName)}`, "_blank");
  }
}

/* ---------------- router ---------------- */

const VIEWS = {
  home: viewHome,
  methods: viewMethods,
  pipelines: viewPipelines,
  inputs: viewInputs,
  outputs: viewOutputs,
};

function route() {
  const name = (location.hash || "#home").slice(1) || "home";
  const view = $("#view");
  view.innerHTML = "";
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  (VIEWS[name] || viewHome)(view);
}

window.addEventListener("hashchange", route);

async function checkConn() {
  const dot = $("#conn-dot");
  try {
    await getJSON("/api/pipelines");
    dot.classList.remove("off");
  } catch (e) {
    dot.classList.add("off");
  }
}

route();
checkConn();
setInterval(checkConn, 15000);
