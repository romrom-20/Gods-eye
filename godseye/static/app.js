const staticDemo = document.documentElement.dataset.staticDemo === "true";
const $ = (id) => document.getElementById(id);
const state = {
  checkpoints: [],
  runs: [],
  tensor: "W1",
  values: [],
  run: null,
  timer: null,
  view: "goal",
  mode: "local",
  token: "",
  job: null,
  maxForwards: 250000,
};
const actions = ["no-op", "left", "up", "right", "down", "fire"];
const fmt = (v, digits = 1) =>
  v == null
    ? "n/a"
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
const label = (id) => state.checkpoints.find((c) => c.id === id)?.name || id;
const viewInfo = {
  "language-model": ["Qwen workspace", "A question. A measured change", "A bounded local Qwen experiment."],
  goal: ["Describe a goal", "What should the Breakout player do better?", "Request a supported improvement, review the limits, then measure what changed."],
  overview: [
    "Start here",
    "Change a few numbers. See what happens",
    "A hands-on experiment with a tiny game-playing neural network.",
  ],
  workbench: [
    "Edit weights",
    "Make your own change",
    "Weights are the numbers inside the model. Save a new version without replacing the original.",
  ],
  evaluate: [
    "Compare",
    "Did your change help",
    "Play both versions under matching conditions, then compare their scores.",
  ],
  history: [
    "Run history",
    "Every change leaves a trace",
    "Return to the evidence. Revisit the decisions. Keep exploring.",
  ],
};
function shortLabel(id) {
  if (id === "paper") return "Original policy";
  if (id === "zero") return "Zero initialization";
  const c = state.checkpoints.find((c) => c.id === id);
  if (c?.patch?.includes("W3[0:8:2, 1] = 0")) return "Left circuit ablated";
  if (c?.patch?.includes("W3[0:8:2, 1] = 30")) return "Left circuit restored";
  if (c?.parent === "zero" && c.patch?.includes("W1[540:600:6, 0]"))
    return "Reactive ball-chaser";
  return c?.name || id;
}
function showView(name) {
  if (!viewInfo[name]) name = "overview";
  if (staticDemo && name === "evaluate") name = "history";
  if (name !== "overview") stopReplay();
  state.view = name;
  document.body.classList.toggle("lm-active", name === "language-model");
  window.lmWorkspace?.view(name === "language-model");
  for (const section of document.querySelectorAll("[data-view]"))
    section.hidden = section.dataset.view !== name;
  for (const nav of document.querySelectorAll("[data-nav]")) {
    nav.classList.toggle("active", nav.dataset.nav === name);
    if (nav.dataset.nav === name) nav.setAttribute("aria-current", "page");
    else nav.removeAttribute("aria-current");
  }
  $("breadcrumb-view").textContent = viewInfo[name][0];
  $("page-title").replaceChildren(document.createTextNode(viewInfo[name][1]));
  const dot = document.createElement("span");
  dot.textContent = name === "goal" ? "" : ".";
  $("page-title").append(dot);
  $("page-description").textContent = viewInfo[name][2];
  document.querySelector(".page-heading > .primary").hidden =
    staticDemo || name === "workbench" || name === "goal";
  if (location.hash !== `#${name}`)
    window.history.replaceState(null, "", `#${name}`);
}
for (const button of document.querySelectorAll("[data-nav], [data-go]"))
  button.onclick = () => {
    showView(button.dataset.nav || button.dataset.go);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

let demoPayload;
async function api(path, body) {
  if (document.documentElement.dataset.staticDemo === "true") {
    if (body !== undefined)
      throw new Error(
        "Recorded demo is read-only. Run the local lab to create experiments.",
      );
    if (!demoPayload)
      demoPayload = fetch("demo.json").then((r) => {
        if (!r.ok) throw new Error("Demo data unavailable");
        return r.json();
      });
    const data = await demoPayload,
      url = new URL(path, location.origin);
    if (url.pathname === "/api/state") return data.state;
    if (url.pathname === "/api/runs") return data.runs;
    if (url.pathname === "/api/tensor")
      return data.tensors[url.searchParams.get("id")][
        url.searchParams.get("name")
      ];
    if (url.pathname.startsWith("/api/run/"))
      return data.traces[url.pathname.split("/").pop()];
    if (url.pathname === "/api/preset/ball-chaser") return data.preset;
    if (url.pathname === "/api/v1/jobs") return [];
    throw new Error("This operation requires the local server.");
  }
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = "Bearer " + state.token;
  const response = await fetch(path, {
    headers,
    ...(body === undefined
      ? {}
      : { method: "POST", body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      $("connection-panel").hidden = false;
      $("connection-panel").open = true;
    }
    const error = new Error(
      (data.error || "Request failed") +
        (data.issues
          ? ": " + data.issues.map((i) => i.field + " " + i.message).join("; ")
          : ""),
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
function configureMode(data) {
  state.mode = data.mode;
  state.maxForwards = data.limits?.max_forwards || 250000;
  const recorded = state.mode === "recorded-demo";
  $("mode-banner").hidden = !recorded;
  $("mode-banner").replaceChildren(
    document.createTextNode(
      "RECORDED DEMO · Real tensors and saved gameplay. New edits and evaluations require the local lab. ",
    ),
  );
  const link = document.createElement("a");
  link.href = "./#start";
  link.textContent = "Run it locally →";
  $("mode-banner").append(link);
  $("environment-label").textContent = recorded
    ? "Recorded demo"
    : "Local CPU environment";
  $("connection-label").textContent = recorded
    ? "Recorded evidence"
    : "Local connection";
  $("execution-label").textContent = recorded
    ? "Playback of recorded experiments"
    : "Experiments run on your CPU";
  for (const id of ["apply", "preview-patch", "evaluate", "quick-experiment"]) {
    $(id).disabled = recorded;
    $(id).title = recorded ? "Start the local lab to use this operation" : "";
  }
  document.querySelector(".eval-footer > span").textContent = recorded
    ? "Recorded demo · execution disabled"
    : "Ready for local execution";
  $("quick-experiment").disabled = recorded || !!state.quickBusy;
  $("quick-hint").textContent = recorded
    ? "You’re viewing saved results. Run the local lab to try your own changes."
    : "Runs on your computer · no API key or paid AI calls · 4 games per version, up to 1,000 steps each.";
  if (recorded) {
    viewInfo.goal = ["Recorded demo", "Explore a recorded experiment", "Two saved comparisons, four checkpoints, and real tensor values. No live service is connected."];
    viewInfo.overview = ["Replay evidence", "Watch the recorded comparisons", "Saved gameplay and paired measurements from bundled public examples."];
    viewInfo.workbench = ["Inspect tensors", "Read the saved weights", "Select any of four checkpoints. Creating edits requires the local lab."];
    document.querySelector('[data-nav="goal"]').textContent = "Recorded demo";
    document.querySelector('[data-nav="workbench"]').textContent = "Inspect tensors";
    document.querySelector('.workbench-intro .tag').textContent = "READ-ONLY TENSOR INSPECTION";
    document.querySelector('.workbench-intro p').textContent = "Explore any bundled checkpoint. Run the local lab to create a new version.";
    document.querySelector('.editor.panel').hidden = true;
    document.querySelector('.workspace').style.gridTemplateColumns = "1fr";
    document.querySelector('[data-nav="evaluate"]').hidden = true;
    $("connection-settings").hidden = true;
    $("quick-experiment").hidden = true;
    $("cancel-job").disabled = true;
    $("first-title").textContent = "Watch what four changed connections did";
    document.querySelector(".simple-steps").hidden = true;
    document.querySelector('[data-view="overview"] .first-experiment > p').textContent = "These are saved comparisons of a tiny Breakout policy, not games running in your browser. Choose a recording below and press Play.";
    for (const control of document.querySelectorAll('[data-go="evaluate"]')) control.hidden = true;
    showView(state.view);
  }
  updateBudget();
}
$("connection-settings").onclick = () => {
  $("connection-panel").hidden = false;
  $("connection-panel").open = true;
  $("api-token").focus();
};
$("connect-token").onclick = async () => {
  state.token = $("api-token").value;
  $("api-token").value = "";
  await initialize();
  if (state.view === "language-model") window.lmWorkspace?.connect();
};

function message(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", error);
}
function option(select, value, text) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = text;
  select.append(el);
}
function drawArchitecture() {
  const svg = $("network-diagram"),
    xs = [80, 292, 504, 716],
    ys = [31, 49, 67, 85, 103, 121, 139];
  const layers = [ys, ys, ys, [40, 58, 76, 94, 112, 130]];
  const layerNames = [
    "BOARD STATE",
    "HIDDEN LAYER 01",
    "HIDDEN LAYER 02",
    "ACTION LOGITS",
  ];
  const counts = ["600 inputs", "32 neurons", "32 neurons", "6 actions"];
  let content = "";
  for (let layer = 0; layer < 3; layer++)
    for (let a = 0; a < layers[layer].length; a++)
      for (let b = 0; b < layers[layer + 1].length; b++) {
        if ((a + b) % 3 === 0 || a === b)
          content += `<path d="M ${xs[layer] + 4} ${layers[layer][a]} C ${xs[layer] + 92} ${layers[layer][a]}, ${xs[layer + 1] - 92} ${layers[layer + 1][b]}, ${xs[layer + 1] - 4} ${layers[layer + 1][b]}" fill="none" stroke="#d8ddd0" stroke-width=".65" opacity=".8"/>`;
      }
  for (const [layer, a, b] of [
    [0, 1, 3],
    [0, 5, 3],
    [1, 3, 2],
    [1, 3, 4],
    [2, 2, 1],
    [2, 4, 5],
  ])
    content += `<path d="M ${xs[layer] + 4} ${layers[layer][a]} C ${xs[layer] + 92} ${layers[layer][a]}, ${xs[layer + 1] - 92} ${layers[layer + 1][b]}, ${xs[layer + 1] - 4} ${layers[layer + 1][b]}" fill="none" stroke="#df612f" stroke-width="1.1" opacity=".6"/>`;
  xs.forEach((x, i) => {
    content += `<text x="${x}" y="12" text-anchor="middle" fill="#8e9881" font-family="'IBM Plex Mono',monospace" font-size="7" letter-spacing=".7">${layerNames[i]}</text>`;
    layers[i].forEach((y, j) => {
      const active =
        (i === 0 && (j === 1 || j === 5)) ||
        (i === 1 && j === 3) ||
        (i === 2 && (j === 2 || j === 4)) ||
        (i === 3 && (j === 1 || j === 5));
      content += `<circle cx="${x}" cy="${y}" r="${active ? 4.2 : 3.2}" fill="${active ? "#f8e1d2" : "#fffefa"}" stroke="${active ? "#df612f" : "#bbc8ad"}" stroke-width="1.1"/>`;
    });
    content += `<text x="${x}" y="170" text-anchor="middle" fill="#6e7f5c" font-family="'IBM Plex Mono',monospace" font-size="9">${counts[i]}</text>`;
  });
  svg.innerHTML = content;
}
function sidebarCheckpoints() {
  $("checkpoint-count").textContent = state.checkpoints.length;
  $("branch-total").textContent = fmt(state.checkpoints.length, 0);
  $("checkpoint-list").replaceChildren();
  const parents = state.checkpoints.filter((c) => !c.parent),
    branches = state.checkpoints
      .filter((c) => c.parent)
      .slice(-5)
      .reverse();
  for (const checkpoint of [...parents, ...branches]) {
    const b = document.createElement("button");
    b.className = "checkpoint-link";
    b.classList.toggle("current", checkpoint.id === $("inspect-model").value);
    b.title = `${checkpoint.name}\n${checkpoint.id}`;
    const mark = document.createElement("span");
    mark.className = "branch-icon";
    mark.textContent = checkpoint.parent ? "↳" : "◇";
    const name = document.createElement("span");
    name.textContent = shortLabel(checkpoint.id);
    b.append(mark, name);
    b.onclick = () => {
      $("inspect-model").value = checkpoint.id;
      $("patch-base").value = checkpoint.id;
      showView("workbench");
      loadTensor(true);
      sidebarCheckpoints();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
    $("checkpoint-list").append(b);
  }
}
async function refresh(data = null) {
  data = data || await api(staticDemo ? "/api/state" : "/api/v1/state");
  state.checkpoints = data.checkpoints;
  configureMode(data);
  configureImport(data);
  for (const id of ["inspect-model", "patch-base", "base", "candidate"]) {
    const select = $(id),
      value = select.value;
    select.replaceChildren();
    for (const c of data.checkpoints)
      option(
        select,
        c.id,
        (c.parent ? "↳ " : "") +
          shortLabel(c.id) +
          (c.parent ? ` · ${c.id.slice(0, 6)}` : ""),
      );
    select.value = data.checkpoints.some((c) => c.id === value)
      ? value
      : id === "base"
        ? "zero"
        : "paper";
  }
  sidebarCheckpoints();
  renderImportMetadata();
  renderExperimentBoard();
}
// Local checkpoint import: explicit writes only; uncertain writes require reconciliation.
const checkpointImport = {supported: false, busy: false, uncertain: false, importedId: null};
function configureImport(data) {
  const recorded = staticDemo || data.mode === "recorded-demo";
  checkpointImport.supported = !recorded && data.mode === "local" &&
    data.backend === "minatar-breakout-v1" && Array.isArray(data.capabilities) &&
    data.capabilities.includes("checkpoint_import");
  for (const id of ["import-open", "import-sidebar"]) {
    $(id).hidden = recorded;
  }
  $("import-form").hidden = recorded || !checkpointImport.supported ||
    $("import-open").getAttribute("aria-expanded") !== "true";
  $("import-support").textContent = recorded
    ? "Recorded demo is read-only. Run a local writable Breakout server to import checkpoints."
    : checkpointImport.supported
      ? "Import local weights into Saved versions. Bundled Original policy and Zero initialization remain available."
      : "Checkpoint import is unsupported by this server. Use a local writable Breakout server with checkpoint_import capability.";
  lockImport();
}
function lockImport() {
  const busy = checkpointImport.busy;
  for (const id of ["import-open", "import-sidebar"])
    $(id).disabled = busy || !checkpointImport.supported;
  for (const id of ["import-file", "import-name", "import-provenance", "import-refresh"])
    $(id).disabled = busy || !checkpointImport.supported;
  $("import-submit").disabled = busy || !checkpointImport.supported || checkpointImport.uncertain || !!checkpointImport.importedId;
  $("import-form").setAttribute("aria-busy", String(busy));
}
function openImport() {
  if (!checkpointImport.supported || checkpointImport.busy) return;
  showView("workbench");
  $("import-form").hidden = false;
  $("import-open").setAttribute("aria-expanded", "true");
  $("import-file").focus();
}
function importNotice(text, error = false, field = "import-status") {
  message("import-status", text, error);
  $(field).focus();
  if (field !== "import-status") $(field).setAttribute("aria-invalid", "true");
}
function renderImportMetadata() {
  const c = state.checkpoints.find(c => c.id === $("inspect-model").value);
  const imported = c?.parent == null && typeof c?.source_sha256 === "string";
  $("import-metadata").hidden = !imported;
  $("import-metadata").textContent = imported
    ? `Imported original · ${c.name}\nSource file SHA256: ${c.source_sha256}\nSource / license notes (user-provided, unverified): ${c.provenance || "None provided."}`
    : "";
}
async function selectImported() {
  const id = checkpointImport.importedId;
  if (!id || !state.checkpoints.some(c => c.id === id)) return false;
  $("inspect-model").value = id;
  $("patch-base").value = id;
  $("base").value = id;
  $("candidate").value = "paper";
  renderImportMetadata();
  sidebarCheckpoints();
  $("import-compare").hidden = false;
  await loadTensor(true);
  return true;
}
async function submitImport(event) {
  event.preventDefault();
  if (!checkpointImport.supported || checkpointImport.busy || checkpointImport.uncertain || checkpointImport.importedId) return;
  for (const id of ["import-file", "import-name", "import-provenance"]) $(id).removeAttribute("aria-invalid");
  const file = $("import-file").files?.[0];
  const name = $("import-name").value.trim(), provenance = $("import-provenance").value;
  if (!file || !/\.npz$/i.test(file.name)) return importNotice("Choose a local .npz checkpoint file.", true, "import-file");
  // Bound the raw file before reading it or allocating a base64 representation.
  if (!Number.isInteger(file.size) || file.size <= 0 || file.size > 128 * 1024)
    return importNotice("Choose a nonempty .npz file no larger than 128 KiB (131,072 bytes).", true, "import-file");
  if (!name || [...name].length > 80) return importNotice("Enter a display name of 1–80 characters.", true, "import-name");
  if ([...provenance].length > 2000) return importNotice("Source / license notes must be at most 2,000 characters.", true, "import-provenance");
  checkpointImport.busy = true;
  lockImport();
  let posted = false;
  message("import-status", "Reading checkpoint…");
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (bytes.length !== file.size || bytes.length > 128 * 1024) throw new Error("File size changed; choose the file again.");
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    message("import-status", "Importing checkpoint…");
    posted = true;
    const record = await api("/api/v1/checkpoints/import", {name, provenance, npz_base64: btoa(binary)});
    if (!record || typeof record.id !== "string" || !record.id || record.parent !== null) throw new Error("Invalid import acknowledgment.");
    checkpointImport.importedId = record.id;
    try {
      await refresh();
      if (!await selectImported()) throw new Error("Imported checkpoint is not visible yet.");
      importNotice("Imported original saved and selected for inspection and editing. Compare uses this original against the bundled policy; choose either version in Compare. No AI run started.");
    } catch (_) {
      importNotice("Import acknowledged, but saved versions could not be refreshed. Use Refresh saved versions to select the imported original. Do not import it again.", true);
    }
  } catch (error) {
    checkpointImport.uncertain = posted && !(error.status >= 400 && error.status < 500);
    importNotice(checkpointImport.uncertain
      ? "Import outcome is unknown; the checkpoint may have been saved. No automatic retry was made. Refresh saved versions and check them before deciding whether to submit again."
      : posted ? `Import rejected by the server: ${error.message}` : "Could not read this file. Choose the file again.", true);
  } finally {
    checkpointImport.busy = false;
    lockImport();
  }
}
$("import-open").onclick = openImport;
$("import-sidebar").onclick = openImport;
$("import-form").onsubmit = submitImport;
for (const id of ["import-file", "import-name", "import-provenance"]) $(id).addEventListener("input", () => {
  // Editing a form never clears an uncertain write; refresh explicitly first.
  if (!checkpointImport.busy && !checkpointImport.uncertain) {
    checkpointImport.importedId = null;
    $("import-compare").hidden = true;
  }
  $(id).removeAttribute("aria-invalid");
  lockImport();
});
$("import-refresh").onclick = async () => {
  if (!checkpointImport.supported || checkpointImport.busy) return;
  checkpointImport.busy = true;
  lockImport();
  try {
    await refresh();
    const selected = await selectImported();
    checkpointImport.uncertain = false;
    importNotice(selected ? "Saved versions refreshed. Imported original selected for inspection and editing. No AI run started."
      : "Saved versions refreshed. Check the saved-version selector for your import before submitting again; a lost acknowledgment can still mean it was saved.");
  } catch (_) {
    importNotice("Could not refresh saved versions. Your form is preserved. Check the server connection and refresh again; no import was retried.", true);
  } finally {
    checkpointImport.busy = false;
    lockImport();
  }
};
$("import-compare").onclick = () => {
  if (!checkpointImport.importedId) return;
  $("base").value = checkpointImport.importedId;
  $("candidate").value = "paper";
  showView("evaluate");
  $("base").focus();
};
// End local checkpoint import.
function matrix() {
  return Array.isArray(state.values[0])
    ? state.values
    : state.values.map((v) => [v]);
}
function paintTensor() {
  const canvas = $("heatmap"),
    ctx = canvas.getContext("2d"),
    rows = matrix();
  const start = Number($("row-start").value),
    visible = rows.slice(start, start + 60);
  if (!visible.length) return;
  const cols = visible[0].length,
    cw = canvas.width / cols,
    ch = canvas.height / visible.length;
  let max = 0;
  for (const row of rows) for (const v of row) max = Math.max(max, Math.abs(v));
  ctx.fillStyle = "#f2f2e9";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  visible.forEach((row, r) =>
    row.forEach((v, c) => {
      const strength = max ? Math.log1p(Math.abs(v)) / Math.log1p(max) : 0;
      const color = v < 0 ? [104, 138, 161] : [223, 97, 47];
      const neutral = [228, 232, 218];
      ctx.fillStyle = `rgb(${color.map((a, i) => Math.round(neutral[i] * (1 - strength) + a * strength)).join(",")})`;
      ctx.fillRect(c * cw, r * ch, Math.max(1, cw - 2), Math.max(1, ch - 2));
    }),
  );
  $("tensor-context").textContent =
    `Rows ${start}–${start + visible.length - 1} ↓ · ${cols} columns →. Brightness is log(1 + |weight|), normalized to this tensor’s maximum.`;
}
let tensorRequest = 0;
async function loadTensor(reset = false) {
  renderImportMetadata();
  renderCheckpointDetail();
  const request = ++tensorRequest;
  try {
    const model = $("inspect-model").value,
      name = state.tensor;
    const data = await api(
      `/api/tensor?id=${encodeURIComponent(model)}&name=${name}`,
    );
    if (request !== tensorRequest) return;
    state.values = data.values;
    const summary = data.summary.find((s) => s.name === name),
      count = data.values.length;
    $("row-start").max = Math.max(0, count - 60);
    if (reset) $("row-start").value = 0;
    $("row-start").disabled = count <= 60;
    $("tensor-info").replaceChildren();
    const left = document.createElement("span");
    left.textContent = `${name} [${summary.shape.join(" × ")}]`;
    const right = document.createElement("span");
    right.textContent = `${fmt(summary.nonzero, 0)} nonzero / ${fmt(summary.parameters, 0)}`;
    $("tensor-info").append(left, right);
    $("hash").textContent = `SHA256 / ${data.sha256}`;
    $("tensor-tabs").replaceChildren();
    for (const s of data.summary) {
      const b = document.createElement("button");
      b.textContent = s.name;
      b.className = s.name === name ? "active" : "";
      b.setAttribute("aria-pressed", String(s.name === name));
      b.onclick = () => {
        state.tensor = s.name;
        loadTensor(true);
      };
      $("tensor-tabs").append(b);
    }
    paintTensor();
    sidebarCheckpoints();
    message("heatmap-detail", "Hover a cell to inspect its value.");
  } catch (e) {
    message("heatmap-detail", e.message, true);
  }
}
$("heatmap").onmousemove = (event) => {
  if (!state.values.length) return;
  const rows = matrix(),
    bounds = event.target.getBoundingClientRect(),
    start = Number($("row-start").value);
  const row = Math.max(
    0,
    Math.min(
      rows.length - 1,
      start +
        Math.floor(
          ((event.clientY - bounds.top) / bounds.height) *
            Math.min(60, rows.length - start),
        ),
    ),
  );
  const col = Math.max(
    0,
    Math.min(
      rows[0].length - 1,
      Math.floor(
        ((event.clientX - bounds.left) / bounds.width) * rows[0].length,
      ),
    ),
  );
  $("heatmap-detail").textContent =
    `${state.tensor}[${row}${Array.isArray(state.values[0]) ? ", " + col : ""}] = ${rows[row][col]}`;
};
$("inspect-model").onchange = () => loadTensor(true);
$("row-start").oninput = paintTensor;
function updateLineNumbers() {
  const count = $("patch").value.split("\n").length;
  $("line-numbers").replaceChildren();
  for (let i = 1; i <= count; i++) {
    $("line-numbers").append(document.createTextNode(String(i)));
    if (i < count) $("line-numbers").append(document.createElement("br"));
  }
}
$("patch").oninput = () => {
  updateLineNumbers();
  message("preview-result", "");
};
$("patch-base").addEventListener("change", () => message("preview-result", ""));
$("hypothesis").addEventListener("input", () => message("preview-result", ""));
$("patch").onscroll = () => {
  $("line-numbers").style.transform = `translateY(-${$("patch").scrollTop}px)`;
};
function activatePreset(id) {
  message("preview-result", "");
  for (const p of document.querySelectorAll(".preset-button"))
    p.classList.toggle("selected", p.id === id);
  updateLineNumbers();
}
$("preset-ablate").onclick = () => {
  $("patch-base").value = "paper";
  $("hypothesis").value =
    "Removing the left-action output connections should pin the paddle to the left and reduce its score.";
  $("patch").value =
    "# Disable the four left-action connections.\nW3[0:8:2, 1] = 0";
  activatePreset("preset-ablate");
};
$("preset-repair").onclick = () => {
  const checkpoint = [...state.checkpoints]
    .reverse()
    .find((c) => c.patch?.includes("W3[0:8:2, 1] = 0"));
  if (checkpoint) $("patch-base").value = checkpoint.id;
  $("hypothesis").value =
    "Restoring the four left-action connections to 30 should recover the original action circuit.";
  $("patch").value =
    "# Branch from an ablated checkpoint before applying.\nW3[0:8:2, 1] = 30";
  activatePreset("preset-repair");
};
$("preset-write").onclick = async () => {
  try {
    const data = await api("/api/preset/ball-chaser");
    $("patch-base").value = "zero";
    $("hypothesis").value =
      "A network that directly computes ball column minus paddle column and moves toward the ball should outperform zero initialization, but may miss catches because it ignores velocity.";
    $("patch").value = data.patch;
    activatePreset("preset-write");
  } catch (e) {
    message("patch-result", e.message, true);
  }
};
$("preview-patch").onclick = async () => {
  $("preview-patch").disabled = true;
  try {
    const result = await api("/api/v1/patches/preview", {
      base_id: $("patch-base").value,
      patch: $("patch").value,
      hypothesis: $("hypothesis").value,
    });
    message(
      "preview-result",
      `${result.changed} / ${result.parameters.toLocaleString()} weights would change.\n` +
        result.diff
          .map(
            (d) =>
              `${d.tensor}: ${d.changed} changed · maximum |Δ| ${d.max_delta}`,
          )
          .join("\n") +
        "\nPreview only. No checkpoint saved.",
    );
  } catch (e) {
    message("preview-result", e.message, true);
  } finally {
    $("preview-patch").disabled = state.mode === "recorded-demo";
  }
};
$("apply").onclick = async () => {
  const button = $("apply");
  button.disabled = true;
  button.textContent = "Creating checkpoint…";
  try {
    const base = $("patch-base").value;
    const report = await api("/api/v1/checkpoints", {
      base_id: base,
      patch: $("patch").value,
      hypothesis: $("hypothesis").value,
    });
    await refresh();
    message("preview-result", "");
    $("inspect-model").value = report.id;
    $("patch-base").value = report.id;
    $("base").value = base;
    $("candidate").value = report.id;
    const changed = report.diff.reduce((n, d) => n + d.changed, 0);
    message(
      "patch-result",
      `Checkpoint ${report.id.slice(0, 8)} created.\n${changed} / 20,486 weights changed (${((100 * changed) / 20486).toFixed(3)}%). Parent preserved.`,
    );
    $("compare-patch").hidden = false;
    await loadTensor();
  } catch (e) {
    message("patch-result", e.message, true);
  } finally {
    button.disabled = false;
    button.innerHTML = "Save edited version <span>↗</span>";
  }
};
$("compare-patch").onclick = () => {
  showView("evaluate");
  window.scrollTo({ top: 0, behavior: "smooth" });
};
function drawBoard(id, frame, ended = false) {
  const canvas = $(id),
    ctx = canvas.getContext("2d"),
    size = canvas.width / 10;
  ctx.fillStyle = "#202c30";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#2a373b";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 10; i++) {
    ctx.beginPath();
    ctx.moveTo(i * size, 0);
    ctx.lineTo(i * size, canvas.height);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i * size);
    ctx.lineTo(canvas.width, i * size);
    ctx.stroke();
  }
  if (!frame) return;
  for (const [channel, color] of [
    [3, "#91a59a"],
    [2, "#405553"],
    [0, "#ece3ca"],
    [1, "#ef9569"],
  ]) {
    for (const [row, col] of frame.cells[channel]) {
      ctx.fillStyle =
        channel === 3 ? ["#8ea29a", "#9aaca2", "#a6b6a9"][row % 3] : color;
      const inset = channel === 1 ? size * 0.24 : 3;
      ctx.fillRect(
        col * size + inset,
        row * size + inset,
        size - 2 * inset,
        size - 2 * inset,
      );
    }
  }
  if (ended) {
    ctx.fillStyle = "#202c30cf";
    ctx.fillRect(0, canvas.height / 2 - 27, canvas.width, 54);
    ctx.fillStyle = "#e5dfca";
    ctx.font = '13px "IBM Plex Mono",monospace';
    ctx.textAlign = "center";
    ctx.fillText("EPISODE FINISHED", canvas.width / 2, canvas.height / 2 + 5);
  }
}
function stopReplay() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  $("play").textContent = "Play";
  $("play").classList.remove("is-playing");
}
function startReplay() {
  if (!state.run) return;
  if (Number($("frame").value) >= Number($("frame").max)) $("frame").value = 0;
  $("play").textContent = "Pause";
  $("play").classList.add("is-playing");
  state.timer = setInterval(
    () => {
      const next = Number($("frame").value) + 1;
      if (next > Number($("frame").max)) {
        stopReplay();
        return;
      }
      $("frame").value = next;
      renderFrame();
    },
    Number($("replay-speed").value),
  );
}
function renderFrame() {
  const run = state.run;
  if (!run) return;
  const index = Number($("frame").value);
  for (const key of ["base", "candidate"]) {
    const trace = run[key].trace,
      frame = trace[Math.min(index, trace.length - 1)];
    drawBoard("replay-" + key, frame, index >= trace.length);
    $("replay-" + key + "-caption").textContent =
      `Step ${frame.step} / Score ${frame.score} / ${actions[frame.action]}`;
  }
  $("frame-label").textContent = `${index} / ${$("frame").max}`;
  const frames = run.candidate.trace,
    frame = frames[Math.min(index, frames.length - 1)];
  $("action-probs").replaceChildren();
  frame.probabilities.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "prob";
    row.classList.toggle("selected", frame.action === i);
    const name = document.createElement("span");
    name.textContent = actions[i];
    const track = document.createElement("div");
    track.className = "track";
    const fill = document.createElement("div");
    fill.className = "fill";
    fill.style.width = 100 * p + "%";
    track.append(fill);
    const value = document.createElement("span");
    value.textContent = (100 * p).toFixed(0) + "%";
    row.append(name, track, value);
    $("action-probs").append(row);
  });
  $("activations").replaceChildren();
  frame.h1.forEach((v, i) => {
    const cell = document.createElement("div");
    cell.className = "activation";
    cell.textContent = `h${i}`;
    const value = document.createElement("span");
    value.textContent = v.toFixed(3);
    cell.append(value);
    $("activations").append(cell);
  });
}
function showRun(run) {
  stopReplay();
  state.run = run;
  $("results").hidden = false;
  $("overview-empty").hidden = true;
  $("overview-run").value = run.id;
  for (const key of ["base", "candidate"]) {
    $(key + "-score").textContent = fmt(run[key].mean);
    $(key + "-se").textContent =
      run[key].se === null
        ? "SE needs 2+ episodes"
        : `Standard error ±${fmt(run[key].se, 2)}`;
    $("replay-" + key + "-title").textContent = shortLabel(run[key + "_id"]);
    $("replay-" + key + "-title").title = label(run[key + "_id"]);
  }
  $("delta").textContent =
    (run.paired_mean_delta > 0 ? "+" : "") + fmt(run.paired_mean_delta);
  $("paired-se").textContent =
    run.paired_se === null
      ? "SE needs 2+ episodes"
      : `Paired SE ±${fmt(run.paired_se, 2)}`;
  $("forward-calls").textContent = fmt(
    run.base.forward_calls + run.candidate.forward_calls,
    0,
  );
  $("elapsed").textContent =
    `${fmt(run.seconds, 2)}s ${state.mode === "recorded-demo" ? "recorded" : "local"} execution`;
  $("frame").max =
    Math.max(run.base.trace.length, run.candidate.trace.length) - 1;
  $("frame").value = Math.min(12, Number($("frame").max));
  const cutoffs = [run.base, run.candidate].map(
    (m) => m.episodes.filter((e) => e.truncated).length,
  );
  $("replay-settings").textContent =
    `Seed ${run.seed} · ${run.episodes} episodes`;
  $("run-caption").textContent =
    `First paired episode · ${fmt(run.max_steps, 0)}-step cap · ${cutoffs[0]} baseline / ${cutoffs[1]} candidate episodes truncated. Exploratory measurement. Run ${run.id.slice(0, 8)}.`;
  $("episode-rows").replaceChildren();
  run.base.episodes.forEach((a, i) => {
    const b = run.candidate.episodes[i],
      row = document.createElement("div");
    row.className = "episode-row";
    for (const text of [
      `Seed ${a.seed}`,
      `A: ${a.score}${a.truncated ? " (cap)" : ""}`,
      `B: ${b.score}${b.truncated ? " (cap)" : ""}`,
      `Δ ${b.score - a.score}`,
    ]) {
      const span = document.createElement("span");
      span.textContent = text;
      row.append(span);
    }
    $("episode-rows").append(row);
  });
  renderFrame();
  renderExperimentBoard();
  message("overview-status", "");
}
let runRequest = 0;
async function openRun(id, navigate = false) {
  const request = ++runRequest;
  message("overview-status", "Loading recorded experiment…");
  try {
    const run = await api("/api/run/" + id);
    if (request !== runRequest) return;
    showRun(run);
    if (navigate) {
      showView("overview");
      $("results").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (e) {
    if (request === runRequest) message("overview-status", e.message, true);
  }
}
$("overview-run").onchange = () => {
  if ($("overview-run").value) openRun($("overview-run").value);
};
$("frame").oninput = () => {
  stopReplay();
  renderFrame();
};
$("play").onclick = () => {
  if (state.timer) stopReplay();
  else startReplay();
};
$("replay-speed").onchange = () => {
  if (state.timer) {
    stopReplay();
    startReplay();
  }
};
$("download").onclick = () => {
  if (!state.run) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(state.run, null, 2)], {
      type: "application/json",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `godseye-run-${state.run.id}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
async function loadHistory(runs = null) {
  runs = runs || await api("/api/runs");
  state.runs = runs;
  $("watch-example").disabled = !runs.length;
  $("history").replaceChildren();
  $("history-empty").hidden = !!runs.length;
  $("run-count").textContent = runs.length;
  $("overview-run").replaceChildren();
  if (!runs.length) option($("overview-run"), "", "No recorded runs yet");
  for (const run of runs) {
    option(
      $("overview-run"),
      run.id,
      `${shortLabel(run.base_id)} → ${shortLabel(run.candidate_id)} · ${run.id.slice(0, 6)}`,
    );
    const row = document.createElement("div");
    row.className = "history-row";
    const names = document.createElement("div");
    names.className = "history-checkpoints";
    const title = document.createElement("strong");
    title.textContent = `${shortLabel(run.base_id)} → ${shortLabel(run.candidate_id)}`;
    const subtitle = document.createElement("span");
    subtitle.textContent = `${run.id.slice(0, 8)} · ${run.episodes} episodes · ${fmt(run.max_steps, 0)} steps`;
    names.append(title, subtitle);
    const score = document.createElement("div");
    score.className = "history-scores";
    score.textContent = `${fmt(run.base.mean)} → ${fmt(run.candidate.mean)}`;
    const delta = document.createElement("span");
    delta.textContent = `${run.paired_mean_delta > 0 ? "+" : ""}${fmt(run.paired_mean_delta)} paired difference`;
    score.append(delta);
    const date = document.createElement("span");
    date.className = "mono";
    date.textContent = new Date(run.created * 1000).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    const button = document.createElement("button");
    button.className = "quiet";
    button.textContent = "View ↗";
    button.onclick = () => openRun(run.id, true);
    row.append(names, score, date, button);
    $("history").append(row);
  }
  if (state.run) $("overview-run").value = state.run.id;
  $("overview-empty").hidden = !!runs.length;
  renderExperimentBoard();
  return runs;
}
function updateBudget() {
  const forwards =
    2 * Number($("episodes").value) * Number($("max-steps").value);
  $("eval-budget").textContent =
    `At most ${forwards.toLocaleString()} forward calls · limit ${state.maxForwards.toLocaleString()} · 1 CPU worker · no provider charges`;
  $("eval-budget").classList.toggle("error", forwards > state.maxForwards);
}
for (const id of ["episodes", "max-steps"])
  $(id).addEventListener("input", updateBudget);
let pollingJob = false;
async function followJob(job) {
  if (pollingJob) return;
  pollingJob = true;
  $("quick-experiment").disabled = true;
  state.job = job.id;
  $("evaluate").disabled = true;
  $("job-progress-wrap").hidden = false;
  $("cancel-job").disabled = false;
  try {
    while (true) {
      state.jobs = [job, ...(state.jobs || []).filter(j => j.id !== job.id)];
      renderExperimentBoard();
      $("job-progress").max = job.total;
      $("job-progress").value = job.completed;
      message(
        "eval-status",
        `${job.status.toUpperCase()} · ${job.completed}/${job.total} episodes · job ${job.id.slice(0, 8)}`,
      );
      if (job.status === "succeeded") {
        await loadHistory();
        await openRun(job.run_id);
        showView("overview");
        message("eval-status", "Evaluation completed and saved.");
        $("results").scrollIntoView({behavior: "smooth", block: "start"});
        break;
      }
      if (["cancelled", "failed", "interrupted"].includes(job.status)) {
        message(
          "eval-status",
          job.error || "Evaluation cancelled. No partial result was published.",
          job.status !== "cancelled",
        );
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 350));
      job = await api("/api/v1/jobs/" + job.id);
    }
  } catch (e) {
    message(
      "eval-status",
      e.message + " Reopen Evaluations or reload to reconnect to the job.",
      true,
    );
  } finally {
    state.job = null;
    pollingJob = false;
    $("quick-experiment").disabled = state.mode === "recorded-demo" || !!state.quickBusy;
    $("evaluate").disabled = state.mode === "recorded-demo";
    $("job-progress-wrap").hidden = true;
    await loadJobs();
  }
}
async function loadJobs(jobs = null) {
  try {
    jobs = jobs || await api("/api/v1/jobs");
    state.jobs = jobs;
    renderExperimentBoard();
    $("recent-jobs").replaceChildren();
    for (const job of jobs.slice(0, 5)) {
      const row = document.createElement("div"),
        text = document.createElement("span");
      row.className = "job-row";
      text.textContent = `${job.id.slice(0, 8)} · ${job.status} · ${job.completed}/${job.total} episodes`;
      row.append(text);
      if (["queued", "running", "cancelling"].includes(job.status)) {
        const button = document.createElement("button");
        button.className = "quiet";
        button.textContent = "Follow";
        button.disabled = pollingJob;
        button.onclick = () => followJob(job);
        row.append(button);
      } else if (job.run_id) {
        const button = document.createElement("button");
        button.className = "quiet";
        button.textContent = "View result";
        button.onclick = () => openRun(job.run_id, true);
        row.append(button);
      }
      $("recent-jobs").append(row);
    }
  } catch (e) {
    message("eval-status", e.message, true);
  }
}
$("cancel-job").onclick = async () => {
  if (!state.job) return;
  $("cancel-job").disabled = true;
  try {
    await api("/api/v1/jobs/" + state.job + "/cancel", {});
  } catch (e) {
    message("eval-status", e.message, true);
    $("cancel-job").disabled = false;
  }
};
$("evaluate").onclick = async () => {
  for (const id of ["episodes", "seed", "max-steps"])
    if (!$(id).reportValidity()) return;
  $("evaluate").disabled = true;
  stopReplay();
  try {
    const job = await api("/api/v1/jobs", {
      base_id: $("base").value,
      candidate_id: $("candidate").value,
      episodes: Number($("episodes").value),
      seed: Number($("seed").value),
      max_steps: Number($("max-steps").value),
    });
    await followJob(job);
  } catch (e) {
    message("eval-status", e.message, true);
  } finally {
    $("evaluate").disabled = state.mode === "recorded-demo";
  }
};
$("watch-example").onclick = async () => {
  if (!state.runs.length) return;
  await openRun(state.run?.id || state.runs[0].id, true);
  if (state.run) startReplay();
};
$("quick-experiment").onclick = async () => {
  if (state.quickBusy || pollingJob || state.mode === "recorded-demo") return;
  state.quickBusy = true;
  $("quick-experiment").disabled = true;
  message("quick-status", "Saving a copy with four connections switched off…");
  try {
    const checkpoint = await api("/api/v1/checkpoints", {
      base_id: "paper", patch: "W3[0:8:2, 1] = 0",
      hypothesis: "Switching off four left-action connections may reduce the game score.",
    });
    await refresh();
    $("base").value = "paper";
    $("candidate").value = checkpoint.id;
    $("episodes").value = "4";
    $("seed").value = "1000";
    $("max-steps").value = "1000";
    updateBudget();
    message("quick-status", "Edited version saved. The original is unchanged.");
    showView("evaluate");
    message("eval-status", "Starting four games per version…");
    const job = await api("/api/v1/jobs", {
      base_id: "paper", candidate_id: checkpoint.id, episodes: 4, seed: 1000, max_steps: 1000,
    });
    await followJob(job);
  } catch (error) {
    message("quick-status", error.message, true);
    message("eval-status", error.message, true);
  } finally {
    state.quickBusy = false;
    $("quick-experiment").disabled = state.mode === "recorded-demo";
  }
};
async function initialize() {
  drawArchitecture();
  updateLineNumbers();
  showView(location.hash.slice(1) || (staticDemo ? "overview" : "goal"));
  try {
    await refresh();
    await loadJobs();
    await loadTensor();
    const runs = await loadHistory();
    const featured =
      runs.find(
        (r) =>
          r.base_id === "paper" &&
          state.checkpoints
            .find((c) => c.id === r.candidate_id)
            ?.patch?.includes("W3[0:8:2, 1] = 0"),
      ) || runs[0];
    if (featured) await openRun(featured.id);
    fitExperimentBoard();
    startWorkspaceWatch();
  } catch (e) {
    renderExperimentBoard();
    $("board-scope").textContent = "CONNECTION UNAVAILABLE";
    $("environment-label").textContent = "Local lab unavailable";
    $("connection-label").textContent = "Disconnected";
    $("execution-label").textContent = "Local engine unavailable";
    message("overview-status", "Cannot reach the local lab. Check the server and connection settings, then reload. The goal service may also be unavailable; your draft is preserved.", true);
  }
}
// Persisted-object board: rendering and selection never submit an experiment.
let boardZoom = 1, selectedBoardObject = null;
let boardDragging = false, boardRenderPending = false, boardLayoutKey = null;
let boardPositions = new Map();
const boardPositionLimit = 6000;
function boardLayoutStorageKey() {
  return "godseye.board-layout.v1:" + (staticDemo || state.mode === "recorded-demo" ? "recorded:" : "local:") + (location.pathname || "/").replace(/lab(?:\.html)?$/, "");
}
function readBoardLayout() {
  const key = boardLayoutStorageKey();
  if (boardLayoutKey === key) return;
  boardLayoutKey = key; boardPositions = new Map();
  try {
    const raw = localStorage.getItem(key);
    if (!raw || raw.length > 65536) return;
    const saved = JSON.parse(raw);
    if (saved.version !== 1 || !saved.positions || typeof saved.positions !== "object" || Array.isArray(saved.positions)) return;
    const entries = Object.entries(saved.positions);
    if (entries.length > 256) return;
    for (const [id,p] of entries) {
      if (/^[a-zA-Z0-9_:-]{1,100}$/.test(id) && p && Number.isFinite(p.x) && Number.isFinite(p.y)
          && p.x >= 0 && p.y >= 0 && p.x <= boardPositionLimit && p.y <= boardPositionLimit)
        boardPositions.set(id,{x:p.x,y:p.y});
    }
  } catch { /* Layout storage is optional; inspection remains usable. */ }
}
function saveBoardLayout() {
  try {
    while (boardPositions.size > 256) boardPositions.delete(boardPositions.keys().next().value);
    localStorage.setItem(boardLayoutKey,JSON.stringify({version:1,positions:Object.fromEntries(boardPositions)}));
    $("board-layout-status").textContent = "Layout saved in this browser. Model weights are unchanged.";
  } catch { $("board-layout-status").textContent = "Layout kept for this visit; browser storage is unavailable. Model weights are unchanged."; }
}

function boardElement(tag, className, text) {
  const el = document.createElement(tag); el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function renderExperimentBoard() {
  if (boardDragging) { boardRenderPending = true; return; }
  readBoardLayout();
  const graph = $("board-graph"); if (!graph) return;
  graph.replaceChildren(); $("board-list").replaceChildren();
  const recorded = staticDemo || state.mode === "recorded-demo";
  $("board-scope").textContent = recorded ? "RECORDED / READ ONLY" : "LOCAL / CPU";
  $("board-request").textContent = recorded ? "Explore saved evidence ↗" : "Describe a goal ↗";
  $("agent-brief").textContent = (recorded ? "First clone and install God's Eye using the API guide, then start godseye serve. Open the local lab URL it prints. " : "Use my running local God's Eye API at " + location.origin + ". ") + "Read /api/v1/state and /api/v1/openapi.json. Target: fixed MinAtar Breakout (600 → 32 → 32 → 6). Inspect the paper checkpoint (or my supplied compatible NPZ), propose one numeric edit and show its preview. Ask me to approve the edit before saving a child. Preserve the original. After approval compare original and child once, 2 episodes per version, max_steps=100, seed=1000, with a unique saved idempotency key. Retain the job ID; reconcile uncertain writes without automatic resubmission. Report hashes, exact patch, paired scores, uncertainty and regressions. Do not read provider keys or hidden evaluation files, call paid services, or claim improvement without evidence. I can watch saved changes in the local browser board.";

  $("board-counts").textContent = `${state.checkpoints.length} checkpoints · ${state.runs.length} comparisons`;
  const pendingJobs = (state.jobs || []).filter(j => !j.run_id || !state.runs.some(r => r.id === j.run_id));
  const positions = new Map(), visiting = new Set();
  function depth(c) {
    if (!c.parent) return 0;
    if (visiting.has(c.id)) return 0;
    const parent = state.checkpoints.find(p => p.id === c.parent);
    if (!parent) return 0;
    visiting.add(c.id); const d = depth(parent) + 1; visiting.delete(c.id); return Math.min(d, 20);
  }
  const occupied = new Set();
  const columns = new Map(), compact = $("board-viewport").clientWidth < 800;
  for (const c of state.checkpoints) {
    const d = depth(c), row = columns.get(d) || 0; columns.set(d,row+1);
    const col=compact?d%2:d; let slot=compact?Math.floor(d/2)*2+row:row;
    while(occupied.has(col+":"+slot))slot++;
    occupied.add(col+":"+slot);
    positions.set(c.id, {x:28+col*260,y:36+slot*170});
  }
  const maxDepth = Math.max(0, ...state.checkpoints.map(depth));
  const bottomRow = Math.max(0,...[...positions.values()].map(p=>(p.y-36)/170));
  let evidenceRow=bottomRow;
  state.runs.forEach((r,i) => {while(occupied.has("1:"+evidenceRow))evidenceRow++;
    positions.set("run:"+r.id,compact?{x:288,y:36+evidenceRow*170}:{x:28+(maxDepth+1)*260,y:36+i*170});evidenceRow++;});
  const jobStart = Math.max(0,...[...positions.values()].map(p=>(p.y-36)/170))+1;
  pendingJobs.forEach((j,i)=>positions.set("job:"+j.id,{x:compact?288:28+(maxDepth+1)*260,y:36+(jobStart+i)*170}));
  for (const [key,p] of boardPositions) if (positions.has(key)) positions.set(key,{...p});
  const width = Math.max(540,...[...positions.values()].map(p=>p.x+248)), height = Math.max(350,...[...positions.values()].map(p=>p.y+185));
  graph.style.width = width+"px"; graph.style.height = height+"px";
  const svg = document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("width",width); svg.setAttribute("height",height); svg.setAttribute("aria-hidden","true"); svg.classList.add("board-connections"); graph.append(svg);
  const edges = [];
  function paintEdge({from,to,path}) {
    const a=positions.get(from),b=positions.get(to); if(!a||!b)return;
    const fromNode=[...graph.children].find(e=>e.dataset?.objectId===from);
    const h=fromNode?.offsetHeight || 140;
    if(a.x===b.x) path.setAttribute("d",`M ${a.x+109} ${a.y+h} C ${a.x+109} ${a.y+h+20}, ${b.x+109} ${b.y-20}, ${b.x+109} ${b.y}`);
    else {const right=b.x>a.x,ax=a.x+(right?218:0),bx=b.x+(right?0:218),bend=right?26:-26;
      path.setAttribute("d",`M ${ax} ${a.y+58} C ${ax+bend} ${a.y+58}, ${bx-bend} ${b.y+58}, ${bx} ${b.y+58}`); }
  }
  function edge(from,to,kind) {
    if(!positions.has(from)||!positions.has(to))return;
    const path=document.createElementNS(svg.namespaceURI,"path");
    path.setAttribute("class",kind); svg.append(path);
    const entry={from,to,path}; edges.push(entry); paintEdge(entry);
  }
  function moveNode(key,button,x,y) {
    const p={x:Math.round(Math.max(0,Math.min(boardPositionLimit,x))),y:Math.round(Math.max(0,Math.min(boardPositionLimit,y)))};
    positions.set(key,p);boardPositions.set(key,p);
    button.style.left=p.x+"px";button.style.top=p.y+"px";
    const w=Math.max(540,...[...positions.values()].map(p=>p.x+248));
    const h=Math.max(350,...[...positions.values()].map(p=>p.y+185));
    graph.style.width=w+"px";graph.style.height=h+"px";svg.setAttribute("width",w);svg.setAttribute("height",h);
    edges.forEach(paintEdge);
  }
  function node(key,kind,title,description,select) {
    const p=positions.get(key),button=boardElement("button","experiment-node "+kind);
    button.dataset.objectId=key; button.setAttribute("aria-pressed",String(selectedBoardObject===key));
    button.append(boardElement("span","node-kind",kind==="job"?"◷ EVALUATION / JOB":kind==="evidence"?"◉ EVALUATION / SAVED":kind==="edit"?"↳ CHECKPOINT / EDIT":"◇ CHECKPOINT / ROOT"),boardElement("strong","node-title",title),boardElement("span","node-description",description),boardElement("span","node-open",kind==="job"?"View progress →":kind==="evidence"?"Inspect evidence →":"Inspect tensors →"));
    button.style.left=p.x+"px";button.style.top=p.y+"px";
    const choose=async()=>{selectedBoardObject=key; $("board-selection").textContent=title+" · "+description; await select(); renderExperimentBoard(); focusBoardInspector();};
    button.setAttribute("aria-describedby","board-layout-help");
    let drag=null, suppressClick=false;
    button.onpointerdown=e=>{
      if(e.button!==0 || e.isPrimary===false) return;
      const p=positions.get(key),viewport=$("board-viewport");
      drag={id:e.pointerId,x:e.clientX,y:e.clientY,original:{...p},scrollX:viewport.scrollLeft,scrollY:viewport.scrollTop,moved:false};
      suppressClick=false;boardDragging=true;
      button.setPointerCapture(e.pointerId);
    };
    button.onpointermove=e=>{
      if(!drag || e.pointerId!==drag.id) return;
      const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
      if(!drag.moved && Math.hypot(dx,dy)<6) return;
      drag.moved=true;suppressClick=true;button.classList.add("dragging");
      const viewport=$("board-viewport");
      moveNode(key,button,drag.original.x+(dx+viewport.scrollLeft-drag.scrollX)/boardZoom,drag.original.y+(dy+viewport.scrollTop-drag.scrollY)/boardZoom);
    };
    const finishDrag=(e,cancel=false)=>{
      if(!drag || e.pointerId!==drag.id) return;
      const moved=drag.moved,original=drag.original,id=drag.id;drag=null;
      if(cancel && moved) moveNode(key,button,original.x,original.y);
      button.classList.remove("dragging");
      if(button.hasPointerCapture(id))button.releasePointerCapture(id);
      boardDragging=false;
      if(moved)saveBoardLayout();
      if(boardRenderPending){boardRenderPending=false;renderExperimentBoard();}
    };
    button.onpointerup=e=>finishDrag(e);
    button.onpointercancel=e=>finishDrag(e,true);
    button.onlostpointercapture=e=>finishDrag(e,true);
    button.onclick=()=>{if(suppressClick){suppressClick=false;return;}return choose();};
    button.onkeydown=e=>{
      const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[e.key];
      if(!e.altKey || !delta)return;
      e.preventDefault();const p=positions.get(key),speed=e.shiftKey?3:1;
      moveNode(key,button,p.x+delta[0]*speed,p.y+delta[1]*speed);saveBoardLayout();
    };
    graph.append(button);
    const item=boardElement("button","board-list-item",title+" — "+description); item.onclick=choose;item.setAttribute("aria-pressed",String(selectedBoardObject===key));$("board-list").append(item);
  }
  for(const c of state.checkpoints){
    if(c.parent) edge(c.parent,c.id,"lineage-edge");
    const missing=c.parent&&!positions.has(c.parent);
    let description=missing?"Parent unavailable · saved checkpoint":c.parent?"Parent: "+shortLabel(c.parent):c.source_sha256||c.provenance?"Imported original · source unverified":"Original · no parent";
    if(!state.runs.some(r=>r.base_id===c.id||r.candidate_id===c.id))description+=" · no saved evaluation";
    node(c.id,c.parent?"edit":"root",shortLabel(c.id),description,async()=>{
      $("inspect-model").value=c.id;$("patch-base").value=c.id;
      showView("workbench");await loadTensor(true);sidebarCheckpoints();

    });
  }
  for(const r of state.runs){edge(r.base_id,"run:"+r.id,"evidence-edge"); if(r.candidate_id!==r.base_id)edge(r.candidate_id,"run:"+r.id,"evidence-edge");
    node("run:"+r.id,"evidence",`${shortLabel(r.base_id)} → ${shortLabel(r.candidate_id)}`,`Δ ${fmt(r.paired_mean_delta)} · ${r.episodes} paired games · SE ${fmt(r.paired_se,2)}`,async()=>{await openRun(r.id);showView("overview");});
  }
  for(const job of pendingJobs) {
    const key="job:"+job.id;
    edge(job.settings?.base_id,key,"evidence-edge");
    edge(job.settings?.candidate_id,key,"evidence-edge");
    node(key,"job",`Evaluation · ${job.status}`,`${job.completed}/${job.total} episodes · ${job.status==="succeeded"?"loading saved evidence":"no completed result"}`,async()=>showView("evaluate"));
  }
  if(!state.checkpoints.length)graph.append(boardElement("p","board-empty","No saved checkpoints loaded. Check your local connection; no experiment has been inferred."));
  $("board-activity").replaceChildren();
  for(const r of state.runs.slice(0,3)){const b=boardElement("button","activity-record",`◉ Saved comparison · Δ ${fmt(r.paired_mean_delta)}`); b.onclick=()=>{const target=graph.querySelector(`[data-object-id="run:${CSS.escape(r.id)}"]`);target?.click();};$("board-activity").append(b);}
  for(const job of pendingJobs.slice(0,3)){
    const b=boardElement("button","activity-record",`${job.status} · ${job.completed}/${job.total} episodes · ${job.status === "succeeded" ? "loading saved evidence" : "no completed evidence"}`);
    b.onclick=()=>{showView("evaluate");$("board-selection").textContent=`Evaluation job ${job.id} · ${job.status}`;$("board-selection").focus();};$("board-activity").append(b);
  }
  if(!state.runs.length&&!(state.jobs||[]).length)$("board-activity").textContent="No saved comparisons yet. Job and agent status remain in their detail views.";
  graph.style.transform=`scale(${boardZoom})`;graph.style.transformOrigin="top left";
}
function focusBoardInspector() {
  $("board-selection").focus({preventScroll:true});
  if (typeof matchMedia === "function" && matchMedia("(max-width: 1150px)").matches)
    $("board-selection").scrollIntoView({block:"start",behavior:"auto"});
}
// Observe local API changes only. Never submit a write or initialize in an export.
function startWorkspaceWatch() {
  if (staticDemo || state.mode === "recorded-demo") return;
  let delay = 4000;
  const tick = async () => {
    try {
      if (!document.hidden && !pollingJob && !checkpointImport.busy) {
        const [data,runs,jobs] = await Promise.all([api("/api/v1/state"),api("/api/runs"),api("/api/v1/jobs")]);
        const focused = document.activeElement;
        const key = focused?.dataset?.objectId;
        if (JSON.stringify(data.checkpoints) !== JSON.stringify(state.checkpoints)) await refresh(data);
        if (JSON.stringify(runs) !== JSON.stringify(state.runs)) await loadHistory(runs);
        if (JSON.stringify(jobs) !== JSON.stringify(state.jobs)) await loadJobs(jobs);
        if (key && !focused.isConnected) {
          const replacement = [...$("board-graph").querySelectorAll("[data-object-id]")].find(e=>e.dataset.objectId===key);
          replacement?.focus({preventScroll:true});
        }
        $("board-sync").textContent = "Watching local changes · every 4s";
        delay = 4000;
      }
    } catch {
      $("board-sync").textContent = "Updates paused · retrying connection";
      delay = Math.min(delay * 2, 30000);
    }
    setTimeout(tick, delay);
  };
  $("board-sync").textContent = "Watching local changes · every 4s";
  setTimeout(tick, delay);
}
function renderCheckpointDetail(){
  $("board-checkpoint-metadata")?.remove();
  const c=state.checkpoints.find(c=>c.id===$("inspect-model").value);if(!c)return;
  const detail=boardElement("div","board-checkpoint-metadata");detail.id="board-checkpoint-metadata";
  detail.append(boardElement("p","mono",c.id));
  if(c.patch)detail.append(boardElement("pre","saved-patch",c.patch));
  document.querySelector(".weights").prepend(detail);
}
function fitExperimentBoard(){const graph=$("board-graph");boardZoom=Math.min(1,($("board-viewport").clientWidth-12)/(parseFloat(graph.style.width)||520));graph.style.transform=`scale(${boardZoom})`;$("board-viewport").style.height=Math.max(240,(parseFloat(graph.style.height)||350)*boardZoom+15)+"px";}
$("board-reset").onclick=()=>{
  if(boardDragging)return;
  boardPositions.clear();
  try{localStorage.removeItem(boardLayoutKey);}catch{}
  renderExperimentBoard();fitExperimentBoard();
  $("board-layout-status").textContent="Automatic layout restored. Model weights are unchanged.";
};
$("board-fit").onclick=fitExperimentBoard;
$("board-zoom-in").onclick=()=>{boardZoom=Math.min(1.5,boardZoom+.15);renderExperimentBoard();};
$("board-zoom-out").onclick=()=>{boardZoom=Math.max(.35,boardZoom-.15);renderExperimentBoard();};
$("board-list-toggle").onclick=()=>{const list=$("board-list");list.hidden=!list.hidden;$("board-viewport").hidden=!list.hidden;$("board-list-toggle").setAttribute("aria-pressed",String(!list.hidden));};
$("board-request").onclick=()=>{showView(staticDemo?"overview":"goal");$("board-selection").textContent=staticDemo?"Recorded evidence · select a saved comparison for paired playback.":"Request · review the supported goal and exact limits before Start."; (staticDemo?$("overview-run"):$("goal-draft")).focus();};
$("copy-agent-brief").onclick=async()=>{try{await navigator.clipboard.writeText($("agent-brief").textContent);$("copy-brief-status").textContent=" Brief copied.";}catch{$("copy-brief-status").textContent=" Select and copy the brief above.";}};

// Goal workflow: mock-only boundary. No api(), fetch(), provider profiles, or keys.
(() => {
  if (typeof staticDemo !== "undefined" && staticDemo) return;
  if (typeof location !== "undefined" && new URLSearchParams(location.search).get("goalMode") !== "mock") return;
  const sampleGoal = "Improve Breakout score without control regressions.";
  const storageKey = "godseye.goal-draft.v1";
  const limitFields = ["requests", "tokens", "output", "seconds", "rounds", "calls", "reply"];
  const controls = ["goal-draft", "goal-provider", "goal-model", "goal-routing", ...limitFields.map(key => "goal-" + key), "goal-scenario"];
  let plan = null;
  let phase = -1;
  let active = false;
  let disconnected = false;
  function status(text) {
    $("goal-status").textContent = text;
  }
  function step(number) {
    for (let i = 1; i <= 4; i++) {
      if (i === number) $("goal-step-" + i).setAttribute("aria-current", "step");
      else $("goal-step-" + i).removeAttribute("aria-current");
    }
  }
  function saveDraft() {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({
        draft: $("goal-draft").value,
        provider: $("goal-provider").value, model: $("goal-model").value, routing: $("goal-routing").value,
        ...Object.fromEntries(limitFields.map(key => [key, $("goal-" + key).value])),
        active,
      }));
    } catch {
      $("goal-storage").textContent = "Tab storage unavailable. Your draft stays on this page; copy it before reloading.";
    }
  }
  function lock(locked) {
    for (const id of [...controls, "goal-example", "goal-plan"]) $(id).disabled = locked;
  }
  function invalidate() {
    plan = null;
    $("goal-consent").checked = false;
    $("goal-start").disabled = true;
    $("goal-review").hidden = true;
    $("goal-result").hidden = true;
    $("goal-comparison").hidden = true;
    step(1);
    status("Draft changed. Review the goal and limits again before starting.");
    saveDraft();
  }
  function finish(title, text) {
    active = false;
    disconnected = false;
    lock(false);
    $("goal-progress").hidden = true;
    $("goal-result").hidden = false;
    $("goal-result-title").textContent = title;
    $("goal-result-text").textContent = text + " This is a sample response. No experiment ran and the original is preserved.";
    $("goal-comparison").hidden = true;
    $("goal-compare").disabled = false;
    step(4);
    status(title + " · Mock only. Your draft is preserved.");
    saveDraft();
  }
  for (const id of controls) $(id).addEventListener(id === "goal-scenario" ? "change" : "input", invalidate);
  $("goal-example").onclick = () => {
    $("goal-draft").value = sampleGoal;
    invalidate();
    $("goal-draft").focus();
  };
  $("goal-form").onsubmit = (event) => {
    event.preventDefault();
    if (active || !$("goal-form").reportValidity()) return;
    invalidate();
    const draft = $("goal-draft").value.trim();
    const scenario = $("goal-scenario").value;
    if (!draft) {
      status("Describe a measurable goal first. Your draft is preserved.");
      return;
    }
    const normalized = draft.toLowerCase().replace(/\s+/g, " ").replace(/\.$/, "");
    const recognized = ["improve breakout score", "improve the breakout score", "improve breakout score without control regressions"].includes(normalized);
    if (scenario === "unsupported" || !/breakout/i.test(draft)) {
      status("Unsupported sample request. Only the bundled Breakout policy is an editable target here. A programmer provider does not make its own model weights editable. Your draft is preserved; use the sample goal to explore the workflow.");
      return;
    }
    if (scenario === "ambiguous" || !recognized) {
      status("Clarification needed. This mock cannot interpret arbitrary goals. Name the target, measurable change, and behavior to preserve; or use the sample goal to review the fixed Breakout plan. Your draft is preserved.");
      return;
    }
    if (scenario === "rate") {
      status("Sample planning service rate limit. No plan created or experiment started. Wait for the service’s retry guidance, then review again. Your draft is preserved.");
      return;
    }
    if ($("goal-model").value.includes("://") || ($("goal-provider").value !== "openrouter" && $("goal-routing").value !== "price")) {
      status("Review the programmer selection. Model IDs cannot be URLs; latency and throughput routing apply only to OpenRouter. Your draft is preserved.");
      return;
    }
    plan = Object.freeze({ draft, scenario, provider: $("goal-provider").value, model: $("goal-model").value, routing: $("goal-routing").value,
      ...Object.fromEntries(limitFields.map(key => [key, Number($("goal-" + key).value)])) });
    $("goal-programmer").textContent = `${plan.provider} / ${plan.model} · routing: ${plan.routing}. Dummy selection; availability, tool compatibility, usage, and charges are unknown. No provider contact or saved-key access.`;
    $("goal-request").textContent = "Your request: “" + plan.draft + "”";
    $("goal-limits").textContent = `${plan.requests} programmer requests, ${plan.tokens.toLocaleString()} reported input tokens, ${plan.output.toLocaleString()} reported output tokens, ${plan.seconds} seconds, ${plan.rounds} rounds, ${plan.calls} tool calls, ${plan.reply} output tokens per response maximum. Illustrative only; no real usage authorized. No automatic retries or provider fallback.`;
    $("goal-review").hidden = false;
    step(2);
    status("Sample plan ready for review. Planning has not started an experiment.");
    $("goal-status").focus();
  };
  $("goal-consent").onchange = () => {
    $("goal-start").disabled = !plan || !$("goal-consent").checked || active;
  };
  $("goal-edit").onclick = () => {
    invalidate();
    $("goal-draft").focus();
  };
  $("goal-start").onclick = () => {
    if (!plan || active || !$("goal-consent").checked) return;
    active = true;
    phase = 0;
    lock(true);
    $("goal-start").disabled = true;
    $("goal-consent").checked = false;
    $("goal-review").hidden = true;
    $("goal-result").hidden = true;
    $("goal-progress").hidden = false;
    $("goal-next").hidden = false;
    $("goal-reconnect").hidden = true;
    $("goal-phase").textContent = "Sample step 1 of 3: Checking the original policy.";
    step(3);
    status("Mock walkthrough started explicitly. No execution or provider request has started.");
    saveDraft();
  };
  $("goal-next").onclick = () => {
    if (!active || disconnected) return;
    if (plan.scenario === "budget") {
      finish("Sample budget stop", "The illustrated limit was reached. No further attempt is allowed without reviewing a new plan and limits. No improvement demonstrated.");
    } else if (plan.scenario === "unavailable") {
      finish("Sample programmer unavailable", "The illustrated worker could not use the selected programmer. No automatic retry or provider fallback occurred. No improvement was demonstrated; review availability and a new plan before trying again.");
    } else if (plan.scenario === "failure") {
      finish("Sample execution failure", "The illustrated worker failed. There is no verified edited artifact or result. Review the failure before starting a new attempt.");
    } else if (plan.scenario === "disconnect") {
      disconnected = true;
      $("goal-next").hidden = true;
      $("goal-reconnect").hidden = false;
      $("goal-phase").textContent = "Sample connection lost. Execution status would be unknown; a lost connection does not prove a worker stopped or charges ended.";
      status("Mock disconnect. Reconnect to status without launching a duplicate experiment, or cancel this mock walkthrough.");
    } else {
      phase++;
      if (phase === 1) $("goal-phase").textContent = "Sample step 2 of 3: Trying an edit on a separate checkpoint.";
      else if (phase === 2) $("goal-phase").textContent = "Sample step 3 of 3: Testing the result and checking regressions.";
      else finish("Sample execution completed · improvement unproven", "The sample says execution completed. Completion is not evidence of improvement. There are no measured scores, regression checks, or edited artifacts in this walkthrough.");
    }
  };
  $("goal-reconnect").onclick = () => {
    if (!active || !disconnected) return;
    finish("Sample interrupted execution", "The illustrated status lookup reports interruption. No automatic relaunch was attempted. Review a new plan to try again.");
  };
  $("goal-cancel").onclick = () => {
    if (!active) return;
    finish("Mock walkthrough cancelled", "Only this walkthrough stopped. In a real experiment, cancellation needs a worker acknowledgment before execution can be called stopped.");
  };
  $("goal-compare").onclick = () => {
    $("goal-comparison").hidden = false;
    $("goal-compare").disabled = true;
  };
  $("goal-keep").onclick = () => {
    status("Original kept. No model was changed by this mock. Your draft is preserved.");
  };
  $("goal-again").onclick = () => {
    invalidate();
    $("goal-draft").focus();
  };
  $("goal-guided").onclick = () => {
    showView("overview");
    $("first-title").scrollIntoView({ behavior: "smooth", block: "start" });
    $("quick-experiment").focus();
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    if (saved && typeof saved.draft === "string") {
      $("goal-draft").value = saved.draft.slice(0, 2000);
      for (const key of limitFields) {
        if (Number.isFinite(Number(saved[key]))) $("goal-" + key).value = saved[key];
      }
      if (["openai", "openrouter", "huggingface"].includes(saved.provider)) $("goal-provider").value = saved.provider;
      if (typeof saved.model === "string") $("goal-model").value = saved.model.slice(0, 128);
      if (["price", "latency", "throughput"].includes(saved.routing)) $("goal-routing").value = saved.routing;
      if (saved.active) status("Previous mock walkthrough interrupted by reload. Your draft is restored. Nothing was resumed or relaunched; review again to start a new mock.");
    }
  } catch {
    $("goal-storage").textContent = "Draft recovery unavailable. Your draft stays on this page; copy it before reloading.";
  }
})();
// End goal workflow.
// Generated from godseye.experiment_spec; refresh when contract v1 changes.
const experimentContract = {"schemas":{"spec":{"type":"object","properties":{"schema_version":{"enum":[1]},"target":{"enum":["breakout"]},"goal":{"enum":["improve_score"]},"baseline":{"type":"object","properties":{"id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"sha256":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"}},"required":["id","sha256"],"additionalProperties":false},"evaluation":{"type":"object","properties":{"suite_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"revision":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"episodes":{"type":"integer","minimum":2,"maximum":8},"max_steps":{"type":"integer","minimum":1,"maximum":1000},"probes_per_case":{"type":"integer","minimum":2,"maximum":100},"forwards_per_case":{"type":"integer","minimum":1,"maximum":1000000},"development":{"enum":["selection_only"]},"held_out":{"enum":["once_after_all_freezes"]}},"required":["suite_id","revision","episodes","max_steps","probes_per_case","forwards_per_case","development","held_out"],"additionalProperties":false},"success":{"enum":["positive_paired_mean_2se_and_no_control_regression"]},"editing":{"enum":["numeric_tensor_assignments_v1"]},"provider":{"type":"object","properties":{"name":{"enum":["openai","openrouter","huggingface"]},"model":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"},"routing":{"enum":["price","latency","throughput"]}},"required":["name","model","routing"],"additionalProperties":false},"limits":{"type":"object","properties":{"max_requests":{"type":"integer","minimum":1},"max_input_tokens":{"type":"integer","minimum":1},"max_total_output_tokens":{"type":"integer","minimum":1},"max_seconds":{"type":"integer","minimum":1},"max_rounds":{"type":"integer","minimum":1},"max_calls":{"type":"integer","minimum":1},"max_output_tokens":{"type":"integer","minimum":1}},"required":["max_requests","max_input_tokens","max_total_output_tokens","max_seconds","max_rounds","max_calls","max_output_tokens"],"additionalProperties":false}},"required":["schema_version","target","goal","baseline","evaluation","success","editing","provider","limits"],"additionalProperties":false},"plan_request":{"type":"object","properties":{"schema_version":{"enum":[1]},"text":{"type":"string","minLength":1,"maxLength":2000},"provider":{"type":"object","properties":{"name":{"enum":["openai","openrouter","huggingface"]},"model":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"},"routing":{"enum":["price","latency","throughput"]}},"required":["name","model","routing"],"additionalProperties":false},"limits":{"type":"object","properties":{"max_requests":{"type":"integer","minimum":1},"max_input_tokens":{"type":"integer","minimum":1},"max_total_output_tokens":{"type":"integer","minimum":1},"max_seconds":{"type":"integer","minimum":1},"max_rounds":{"type":"integer","minimum":1},"max_calls":{"type":"integer","minimum":1},"max_output_tokens":{"type":"integer","minimum":1}},"required":["max_requests","max_input_tokens","max_total_output_tokens","max_seconds","max_rounds","max_calls","max_output_tokens"],"additionalProperties":false}},"required":["schema_version","text","provider","limits"],"additionalProperties":false},"plan_response":{"type":"object","properties":{"schema_version":{"enum":[1]},"outcome":{"enum":["ready","clarification_required","rejected"]},"draft_id":{"anyOf":[{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},{"type":"null"}]},"spec":{"anyOf":[{"type":"object","properties":{"schema_version":{"enum":[1]},"target":{"enum":["breakout"]},"goal":{"enum":["improve_score"]},"baseline":{"type":"object","properties":{"id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"sha256":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"}},"required":["id","sha256"],"additionalProperties":false},"evaluation":{"type":"object","properties":{"suite_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"revision":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"episodes":{"type":"integer","minimum":2,"maximum":8},"max_steps":{"type":"integer","minimum":1,"maximum":1000},"probes_per_case":{"type":"integer","minimum":2,"maximum":100},"forwards_per_case":{"type":"integer","minimum":1,"maximum":1000000},"development":{"enum":["selection_only"]},"held_out":{"enum":["once_after_all_freezes"]}},"required":["suite_id","revision","episodes","max_steps","probes_per_case","forwards_per_case","development","held_out"],"additionalProperties":false},"success":{"enum":["positive_paired_mean_2se_and_no_control_regression"]},"editing":{"enum":["numeric_tensor_assignments_v1"]},"provider":{"type":"object","properties":{"name":{"enum":["openai","openrouter","huggingface"]},"model":{"type":"string","minLength":1,"maxLength":128,"pattern":"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"},"routing":{"enum":["price","latency","throughput"]}},"required":["name","model","routing"],"additionalProperties":false},"limits":{"type":"object","properties":{"max_requests":{"type":"integer","minimum":1},"max_input_tokens":{"type":"integer","minimum":1},"max_total_output_tokens":{"type":"integer","minimum":1},"max_seconds":{"type":"integer","minimum":1},"max_rounds":{"type":"integer","minimum":1},"max_calls":{"type":"integer","minimum":1},"max_output_tokens":{"type":"integer","minimum":1}},"required":["max_requests","max_input_tokens","max_total_output_tokens","max_seconds","max_rounds","max_calls","max_output_tokens"],"additionalProperties":false}},"required":["schema_version","target","goal","baseline","evaluation","success","editing","provider","limits"],"additionalProperties":false},{"type":"null"}]},"spec_hash":{"anyOf":[{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},{"type":"null"}]},"issues":{"type":"array","items":{"type":"object","properties":{"code":{"enum":["invalid_json","invalid_schema","unsupported_version","policy_violation","clarification_required","unsupported_goal","spec_conflict","state_conflict","idempotency_conflict","not_found","result_not_ready","not_authorized","unavailable","rate_limited","queue_full","worker_unavailable","internal_error"]},"field":{"type":"string","minLength":1,"maxLength":200},"message":{"type":"string","minLength":1,"maxLength":500}},"required":["code","field","message"],"additionalProperties":false},"minItems":0,"maxItems":10}},"required":["schema_version","outcome","draft_id","spec","spec_hash","issues"],"additionalProperties":false},"start_request":{"type":"object","properties":{"schema_version":{"enum":[1]},"draft_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"spec_hash":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},"idempotency_key":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"confirmed":{"const":true}},"required":["schema_version","draft_id","spec_hash","idempotency_key","confirmed"],"additionalProperties":false},"start_response":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"spec_hash":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},"status":{"enum":["queued","running","cancelling","completed","failed","cancelled","interrupted"]}},"required":["schema_version","experiment_id","spec_hash","status"],"additionalProperties":false},"status_request":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}},"required":["schema_version","experiment_id"],"additionalProperties":false},"cancel_request":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}},"required":["schema_version","experiment_id"],"additionalProperties":false},"results_request":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}},"required":["schema_version","experiment_id"],"additionalProperties":false},"status_response":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"spec_hash":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},"status":{"enum":["draft","ready","queued","running","cancelling","completed","failed","cancelled","interrupted"]},"phase":{"type":"object","properties":{"name":{"enum":["unknown","checking_original","trying_edit","testing"]},"event_sequence":{"anyOf":[{"type":"integer","minimum":1},{"type":"null"}]}},"required":["name","event_sequence"],"additionalProperties":false},"verdict":{"enum":["not_evaluated","improved","no_improvement","inconclusive"]},"reason":{"anyOf":[{"enum":["budget_exhausted","provider_error","evaluation_error","provider_rate_limited","provider_unavailable","agent_incomplete","runtime_failure","user_cancelled","process_lost"]},{"type":"null"}]},"usage":{"type":"object","properties":{"requests":{"type":"integer","minimum":0},"input_tokens":{"type":"integer","minimum":0},"output_tokens":{"type":"integer","minimum":0},"tool_calls":{"type":"integer","minimum":0},"elapsed_seconds":{"type":"number","minimum":0},"usage_complete":{"type":"boolean"},"request_in_flight":{"type":"boolean"}},"required":["requests","input_tokens","output_tokens","tool_calls","elapsed_seconds","usage_complete","request_in_flight"],"additionalProperties":false}},"required":["schema_version","experiment_id","spec_hash","status","phase","verdict","reason","usage"],"additionalProperties":false},"cancel_response":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"spec_hash":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},"status":{"enum":["draft","ready","queued","running","cancelling","completed","failed","cancelled","interrupted"]},"phase":{"type":"object","properties":{"name":{"enum":["unknown","checking_original","trying_edit","testing"]},"event_sequence":{"anyOf":[{"type":"integer","minimum":1},{"type":"null"}]}},"required":["name","event_sequence"],"additionalProperties":false},"verdict":{"enum":["not_evaluated","improved","no_improvement","inconclusive"]},"reason":{"anyOf":[{"enum":["budget_exhausted","provider_error","evaluation_error","provider_rate_limited","provider_unavailable","agent_incomplete","runtime_failure","user_cancelled","process_lost"]},{"type":"null"}]},"usage":{"type":"object","properties":{"requests":{"type":"integer","minimum":0},"input_tokens":{"type":"integer","minimum":0},"output_tokens":{"type":"integer","minimum":0},"tool_calls":{"type":"integer","minimum":0},"elapsed_seconds":{"type":"number","minimum":0},"usage_complete":{"type":"boolean"},"request_in_flight":{"type":"boolean"}},"required":["requests","input_tokens","output_tokens","tool_calls","elapsed_seconds","usage_complete","request_in_flight"],"additionalProperties":false}},"required":["schema_version","experiment_id","spec_hash","status","phase","verdict","reason","usage"],"additionalProperties":false},"results_response":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"spec_hash":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},"status":{"enum":["draft","ready","queued","running","cancelling","completed","failed","cancelled","interrupted"]},"phase":{"type":"object","properties":{"name":{"enum":["unknown","checking_original","trying_edit","testing"]},"event_sequence":{"anyOf":[{"type":"integer","minimum":1},{"type":"null"}]}},"required":["name","event_sequence"],"additionalProperties":false},"verdict":{"enum":["not_evaluated","improved","no_improvement","inconclusive"]},"reason":{"anyOf":[{"enum":["budget_exhausted","provider_error","evaluation_error","provider_rate_limited","provider_unavailable","agent_incomplete","runtime_failure","user_cancelled","process_lost"]},{"type":"null"}]},"usage":{"type":"object","properties":{"requests":{"type":"integer","minimum":0},"input_tokens":{"type":"integer","minimum":0},"output_tokens":{"type":"integer","minimum":0},"tool_calls":{"type":"integer","minimum":0},"elapsed_seconds":{"type":"number","minimum":0},"usage_complete":{"type":"boolean"},"request_in_flight":{"type":"boolean"}},"required":["requests","input_tokens","output_tokens","tool_calls","elapsed_seconds","usage_complete","request_in_flight"],"additionalProperties":false},"evidence":{"anyOf":[{"type":"object","properties":{"baseline_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"candidate_manifest_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"delta_artifact_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"report_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"paired_samples":{"type":"integer","minimum":2},"mean_delta":{"type":"number"},"paired_se":{"type":"number","minimum":0},"min_control_delta":{"type":"number"},"limitations":{"type":"array","items":{"type":"string","minLength":1,"maxLength":500},"minItems":1,"maxItems":10}},"required":["baseline_id","candidate_manifest_id","delta_artifact_id","report_id","paired_samples","mean_delta","paired_se","min_control_delta","limitations"],"additionalProperties":false},{"type":"null"}]}},"required":["schema_version","experiment_id","spec_hash","status","phase","verdict","reason","usage","evidence"],"additionalProperties":false},"error_response":{"type":"object","properties":{"schema_version":{"enum":[1]},"error":{"type":"object","properties":{"code":{"enum":["invalid_json","invalid_schema","unsupported_version","policy_violation","spec_conflict","state_conflict","idempotency_conflict","not_found","result_not_ready","not_authorized","unavailable","rate_limited","queue_full","worker_unavailable","internal_error"]},"field":{"type":"string","minLength":1,"maxLength":200},"message":{"type":"string","minLength":1,"maxLength":500}},"required":["code","field","message"],"additionalProperties":false},"retry":{"type":"object","properties":{"action":{"enum":["none","same_request","poll_status"]},"after_seconds":{"anyOf":[{"type":"integer","minimum":1,"maximum":5},{"type":"null"}]},"max_attempts":{"type":"integer","minimum":0,"maximum":3}},"required":["action","after_seconds","max_attempts"],"additionalProperties":false}},"required":["schema_version","error","retry"],"additionalProperties":false},"phase_event":{"type":"object","properties":{"schema_version":{"enum":[1]},"experiment_id":{"type":"string","minLength":1,"maxLength":64,"pattern":"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},"spec_hash":{"type":"string","minLength":64,"maxLength":64,"pattern":"^[0-9a-f]{64}$"},"sequence":{"type":"integer","minimum":1},"kind":{"enum":["root_probe_reserved","edit_started","candidate_probe_reserved","held_out_reserved","activity_finished","activity_failed","activity_unknown"]}},"required":["schema_version","experiment_id","spec_hash","sequence","kind"],"additionalProperties":false}},"messages":{"invalid_json":"Expected bounded, unambiguous UTF-8 JSON.","invalid_schema":"Message does not match experiment contract v1.","unsupported_version":"Unsupported experiment contract version.","policy_violation":"Specification exceeds or differs from trusted policy.","clarification_required":"Use an explicit supported Breakout score-improvement request.","unsupported_goal":"Only the existing Breakout score-improvement goal is supported.","spec_conflict":"The reviewed specification has changed.","state_conflict":"Operation is unavailable in the current state.","idempotency_conflict":"Idempotency key is already bound to another submission.","not_found":"Experiment is unavailable in this scope.","result_not_ready":"The experiment has no terminal result yet.","not_authorized":"Operation is not authorized.","unavailable":"Experiment service is unavailable.","rate_limited":"Too many requests. Wait before retrying the same action.","queue_full":"Experiment queue is full. No new experiment was admitted.","worker_unavailable":"No compatible worker is available. No new experiment was admitted.","internal_error":"Experiment service failed. Admission state may be unknown."},"paths":["$","$.baseline","$.baseline.id","$.baseline.sha256","$.confirmed","$.draft_id","$.editing","$.error","$.error.code","$.error.field","$.error.message","$.evaluation","$.evaluation.development","$.evaluation.episodes","$.evaluation.forwards_per_case","$.evaluation.held_out","$.evaluation.max_steps","$.evaluation.probes_per_case","$.evaluation.revision","$.evaluation.suite_id","$.evidence","$.evidence.baseline_id","$.evidence.candidate_manifest_id","$.evidence.delta_artifact_id","$.evidence.limitations","$.evidence.limitations[]","$.evidence.mean_delta","$.evidence.min_control_delta","$.evidence.paired_samples","$.evidence.paired_se","$.evidence.report_id","$.experiment_id","$.goal","$.idempotency_key","$.issues","$.issues[]","$.issues[].code","$.issues[].field","$.issues[].message","$.kind","$.limits","$.limits.max_calls","$.limits.max_input_tokens","$.limits.max_output_tokens","$.limits.max_requests","$.limits.max_rounds","$.limits.max_seconds","$.limits.max_total_output_tokens","$.outcome","$.phase","$.phase.event_sequence","$.phase.name","$.provider","$.provider.model","$.provider.name","$.provider.routing","$.reason","$.retry","$.retry.action","$.retry.after_seconds","$.retry.max_attempts","$.schema_version","$.sequence","$.spec","$.spec.baseline","$.spec.baseline.id","$.spec.baseline.sha256","$.spec.editing","$.spec.evaluation","$.spec.evaluation.development","$.spec.evaluation.episodes","$.spec.evaluation.forwards_per_case","$.spec.evaluation.held_out","$.spec.evaluation.max_steps","$.spec.evaluation.probes_per_case","$.spec.evaluation.revision","$.spec.evaluation.suite_id","$.spec.goal","$.spec.limits","$.spec.limits.max_calls","$.spec.limits.max_input_tokens","$.spec.limits.max_output_tokens","$.spec.limits.max_requests","$.spec.limits.max_rounds","$.spec.limits.max_seconds","$.spec.limits.max_total_output_tokens","$.spec.provider","$.spec.provider.model","$.spec.provider.name","$.spec.provider.routing","$.spec.schema_version","$.spec.success","$.spec.target","$.spec_hash","$.status","$.success","$.target","$.text","$.usage","$.usage.elapsed_seconds","$.usage.input_tokens","$.usage.output_tokens","$.usage.request_in_flight","$.usage.requests","$.usage.tool_calls","$.usage.usage_complete","$.verdict"],"retries":{"invalid_json":{"action":"none","after_seconds":null,"max_attempts":0},"invalid_schema":{"action":"none","after_seconds":null,"max_attempts":0},"unsupported_version":{"action":"none","after_seconds":null,"max_attempts":0},"policy_violation":{"action":"none","after_seconds":null,"max_attempts":0},"clarification_required":{"action":"none","after_seconds":null,"max_attempts":0},"unsupported_goal":{"action":"none","after_seconds":null,"max_attempts":0},"spec_conflict":{"action":"none","after_seconds":null,"max_attempts":0},"state_conflict":{"action":"none","after_seconds":null,"max_attempts":0},"idempotency_conflict":{"action":"none","after_seconds":null,"max_attempts":0},"not_found":{"action":"none","after_seconds":null,"max_attempts":0},"result_not_ready":{"action":"poll_status","after_seconds":2,"max_attempts":3},"not_authorized":{"action":"none","after_seconds":null,"max_attempts":0},"unavailable":{"action":"none","after_seconds":null,"max_attempts":0},"rate_limited":{"action":"same_request","after_seconds":5,"max_attempts":3},"queue_full":{"action":"same_request","after_seconds":5,"max_attempts":3},"worker_unavailable":{"action":"same_request","after_seconds":5,"max_attempts":3},"internal_error":{"action":"none","after_seconds":null,"max_attempts":0}}};

// Live goal transport. Mock controller and storage are deliberately separate.
(() => {
  if ((typeof staticDemo !== 'undefined' && staticDemo) || new URLSearchParams(location.search).get('goalMode') === 'mock') return;
  const C = experimentContract, key = 'godseye.goal-live.v1';
  const fields = {requests:'max_requests', tokens:'max_input_tokens', output:'max_total_output_tokens', seconds:'max_seconds', rounds:'max_rounds', calls:'max_calls', reply:'max_output_tokens'};
  const ids = ['draft','provider','model','routing', ...Object.keys(fields)].map(x => 'goal-' + x);
  const terminal = s => ['completed','failed','cancelled','interrupted'].includes(s);
  let plan = null, pending = null, run = null, busy = false, timer = null, epoch = 0, durable = true;
  const say = text => { $('goal-status').textContent = text; };
  const canonical = v => JSON.stringify(v && typeof v === 'object' ? (Array.isArray(v) ? v.map(x => JSON.parse(canonical(x))) : Object.fromEntries(Object.keys(v).sort().map(k => [k, JSON.parse(canonical(v[k]))]))) : v).replace(/[\u007f-\uffff]/g, c => '\\u' + c.charCodeAt(0).toString(16).padStart(4,'0'));
  function shape(v, s) {
    if (s.anyOf) return s.anyOf.some(x => shape(v,x));
    if (s.enum && !s.enum.includes(v) || 'const' in s && v !== s.const) return false;
    if (s.type === 'null') return v === null;
    if (s.type === 'object') return v !== null && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === s.required.length && s.required.every(k => Object.hasOwn(v,k) && shape(v[k],s.properties[k]));
    if (s.type === 'array') return Array.isArray(v) && v.length >= s.minItems && v.length <= s.maxItems && v.every(x => shape(x,s.items));
    if (s.type === 'string') return typeof v === 'string' && v.length >= s.minLength && v.length <= s.maxLength && (!s.pattern || new RegExp(s.pattern).test(v));
    if (['integer','number'].includes(s.type)) return typeof v === 'number' && Number.isFinite(v) && (s.type !== 'integer' || Number.isSafeInteger(v)) && (s.minimum === undefined || v >= s.minimum) && (s.maximum === undefined || v <= s.maximum);
    return s.type !== 'boolean' || typeof v === 'boolean';
  }
  function valid(kind, v) {
    if (!shape(v,C.schemas[kind])) throw Error('invalid');
    if (kind === 'error_response') {
      if (C.messages[v.error.code] !== v.error.message || !C.paths.includes(v.error.field) || canonical(v.retry) !== canonical(C.retries[v.error.code])) throw Error('invalid');
    }
    if (kind === 'plan_response') {
      if (v.outcome === 'ready') {
        if (!v.spec || !v.draft_id || !v.spec_hash || v.issues.length) throw Error('invalid');
      } else {
        const expected = v.outcome === 'rejected' ? 'unsupported_goal' : 'clarification_required';
        if (v.spec !== null || v.draft_id !== null || v.spec_hash !== null || !v.issues.length || v.issues.some(i => i.code !== expected || i.message !== C.messages[i.code] || !C.paths.includes(i.field))) throw Error('invalid');
      }
    }
    if (v.phase) {
      if (v.phase.name !== 'unknown' && (!['running','cancelling'].includes(v.status) || v.phase.event_sequence === null)) throw Error('invalid');
      if ((v.status === 'completed') !== (v.verdict !== 'not_evaluated')) throw Error('invalid');
      const reasons = {failed:['budget_exhausted','provider_error','provider_rate_limited','provider_unavailable','evaluation_error','agent_incomplete','runtime_failure'],cancelled:['user_cancelled'],interrupted:['process_lost']};
      if (!(reasons[v.status] || [null]).includes(v.reason)) throw Error('invalid');
    }
    if (kind === 'results_response') {
      if (!terminal(v.status) || (v.status === 'completed') !== (v.evidence !== null)) throw Error('invalid');
      if (v.evidence) {
        const e = v.evidence, verdict = e.mean_delta <= 0 || e.min_control_delta < 0 ? 'no_improvement' : e.mean_delta - 2*e.paired_se > 0 ? 'improved' : 'inconclusive';
        if (verdict !== v.verdict || e.baseline_id !== pending.baseline_id) throw Error('invalid');
      }
    }
    return v;
  }
  function save() {
    try { sessionStorage.setItem(key, JSON.stringify({draft:Object.fromEntries(ids.map(id => [id,$(id).value])),pending,run})); durable = true; return true; }
    catch { durable = false; $('goal-storage').textContent = 'Tab recovery unavailable. Copy your draft before reload. Start is disabled until storage works.'; return false; }
  }
  function lock() {
    $('goal-request-layout').hidden = !!plan || !!pending;
    $('goal-onboarding').hidden = !!plan || !!pending;
    const current = run && terminal(run.status) ? 4 : pending ? 3 : plan ? 2 : 1;
    for (let i = 1; i <= 4; i++) {
      if (i === current) $('goal-step-' + i).setAttribute('aria-current', 'step');
      else $('goal-step-' + i).removeAttribute('aria-current');
    }
    const active = !!pending;
    ids.forEach(id => $(id).disabled = active || busy);
    $('goal-plan').disabled = active || busy; $('goal-example').disabled = active || busy;
    $('goal-edit').disabled = active || busy;
    $('goal-consent').disabled = active || busy;
    $('goal-start').disabled = active || busy || !plan || !$('goal-consent').checked || !durable;
    $('goal-cancel').disabled = busy || !run || terminal(run.status) || run.status === 'cancelling';
    $('goal-review-again').hidden = !pending?.rejected || !!pending.uncertain || !!run;
    $('goal-review-again').disabled = busy;
    $('goal-reconnect').disabled = busy; $('goal-again').disabled = busy || !!pending && (!run || !terminal(run.status));
  }
  function invalidate() {
    if (pending) return;
    epoch++; clearTimeout(timer); plan = null; $('goal-consent').checked = false;
    $('goal-review').hidden = true; $('goal-result').hidden = true; save(); lock();
  }
  function parseResponse(raw) {
    if (new TextEncoder().encode(raw).length > 65536) throw Error('invalid');
    const value = JSON.parse(raw), stack = [];
    // JSON.parse accepts duplicate keys. Reject those before interpreting a message.
    for (const token of raw.match(/"(?:\\.|[^"\\])*"|[{}\[\],:]/g) || []) {
      if (token === '{' || token === '[') {
        stack.push({object:token === '{', keys:new Set(), key:true});
        if (stack.length > 16) throw Error('invalid');
      } else if (token === '}' || token === ']') stack.pop();
      else if (token === ',' && stack.at(-1)?.object) stack.at(-1).key = true;
      else if (token[0] === '"' && stack.at(-1)?.object && stack.at(-1).key) {
        const frame = stack.at(-1), key = JSON.parse(token);
        if (frame.keys.has(key)) throw Error('invalid');
        frame.keys.add(key); frame.key = false;
      }
    }
    return value;
  }
  async function request(op, body, action = {retries:0}, generation = epoch) {
    for (;;) {
      const abort = new AbortController(), timeout = setTimeout(() => abort.abort(), 15000);
      let response, v;
      try {
        const headers = {'Content-Type':'application/json'};
        if (state.token) headers.Authorization = 'Bearer ' + state.token;
        response = await fetch('/api/v1/experiments/' + op, {method:'POST',headers,body:JSON.stringify(body),cache:'no-store',signal:abort.signal});
        v = parseResponse(await response.text());
      } finally { clearTimeout(timeout); }
      if (generation !== epoch) throw Error('superseded');
      if (response.ok) return valid(op + '_response',v);
      valid('error_response',v);
      const retry = v.retry;
      if (retry.action === 'same_request' && action.retries < 3 && !action.noAuto) {
        const delay = retry.after_seconds * 1000 * 2**action.retries++;
        save(); say('Service busy. Retrying the same request (' + action.retries + '/3).');
        await new Promise(resolve => setTimeout(resolve,delay));
        if (generation !== epoch) throw Error('superseded');
        continue;
      }
      if (v.error.code === 'result_not_ready') { const e = Error('result_not_ready'); e.poll = true; throw e; }
      const e = Error(v.error.code); e.safe = true;
      // Only these exact contract responses confirm that this request admitted nothing.
      const preAdmissionStatus = {spec_conflict:409, rate_limited:429, queue_full:503, worker_unavailable:503};
      e.confirmedNonAdmission = op === 'start' && Object.hasOwn(preAdmissionStatus, v.error.code) && response.status === preAdmissionStatus[v.error.code];
      throw e;
    }
  }
  function render(v) {
    run = {schema_version:1,experiment_id:v.experiment_id,spec_hash:v.spec_hash,status:v.status}; save();
    $('goal-progress').hidden = false; $('goal-review').hidden = true;
    const phase = {unknown:'Activity unavailable',checking_original:'Checking the original',trying_edit:'Trying an edit',testing:'Testing the result'};
    $('goal-phase').textContent = v.status + ' · ' + phase[v.phase.name];
    const u = v.usage;
    $('goal-usage').textContent = `${u.requests} requests · ${u.input_tokens} known input tokens · ${u.output_tokens} known output tokens · ${u.tool_calls} tool calls · ${u.elapsed_seconds.toFixed(1)}s. ${u.usage_complete ? 'Reported usage complete.' : 'Additional usage and charges unknown.'} ${u.request_in_flight ? 'Request in flight; remote execution or billing may continue.' : ''}`;
    say('Execution: ' + v.status + '. Verdict: ' + v.verdict + (v.reason ? '. Reason: ' + v.reason : '') + '.');
    if ('evidence' in v) {
      $('goal-result').hidden = false;
      const outcomes = {improved:'Measured improvement', no_improvement:'No measured improvement', inconclusive:'Evidence is inconclusive', not_evaluated:'No measured result'};
      $('goal-result-title').textContent = outcomes[v.verdict] + ' · ' + v.status + ' · ' + v.verdict;
      downloadTarget = v.status === 'completed' && v.evidence ? {schema_version:1,experiment_id:v.experiment_id,artifact_id:v.evidence.candidate_manifest_id} : null;
      if ($('goal-download')) { $('goal-download').hidden = !downloadTarget; $('goal-download').disabled = !downloadTarget || downloadBusy; }
      $('goal-result-text').textContent = v.evidence ? `Paired samples: ${v.evidence.paired_samples}. Mean score change: ${v.evidence.mean_delta}. Sample standard error: ${v.evidence.paired_se}. Minimum control mean change: ${v.evidence.min_control_delta}. The original is preserved; selected checkpoints are separate copies. A negative control change indicates a regression. This sample does not guarantee future performance. Limitations: ${v.evidence.limitations.join(' ')}` : 'No complete measured evidence available. The original is preserved.';
    }
    lock();
    if ('evidence' in v) $('goal-result-title').focus();
  }
  // Explicit checkpoint download: no inference or automatic retry.
  let downloadTarget = null, downloadBusy = false;
  async function downloadCheckpoint() {
    if (!downloadTarget || downloadBusy) return;
    downloadBusy = true;
    const target = {...downloadTarget}, button = $('goal-download');
    button.disabled = true; $('goal-download-status').textContent = 'Preparing checkpoint download…';
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(),30000);
    let url = null;
    try {
      const headers = {'Content-Type':'application/json'};
      if (state.token) headers.Authorization = 'Bearer ' + state.token;
      const response = await fetch('/api/v1/experiments/export',{method:'POST',headers,body:JSON.stringify(target),cache:'no-store',signal:abort.signal});
      if (!response.ok) {
        const error = valid('error_response',parseResponse(await response.text()));
        throw Error('Download unavailable: ' + error.error.message + ' Refresh the result, then retry the download explicitly.');
      }
      if (!response.headers.get('Content-Type')?.includes('application/json')) throw Error('Checkpoint response unavailable. Refresh the result and retry explicitly.');
      const blob = await response.blob();
      url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = 'godseye-checkpoint-' + target.experiment_id + '.json';
      document.body.append(link); link.click(); link.remove();
      $('goal-download-status').textContent = 'Checkpoint download requested. The original remains preserved.';
    } catch (error) {
      $('goal-download-status').textContent = error.message.startsWith('Download unavailable:') ? error.message : 'Download failed or disconnected. Refresh the result and retry the download explicitly.';
    } finally {
      if (url) URL.revokeObjectURL(url);
      clearTimeout(timeout); downloadBusy = false; button.disabled = !downloadTarget;
    }
  }
  if ($('goal-download')) $('goal-download').onclick = downloadCheckpoint;
  // Activity is an optional additive API. Never called in recorded or mock mode.
  let activityRun = null, activityCursor = 0, activityFence = 0, activityBusy = false, activityHadGap = false;
  const activityKinds = new Set(['worker_started','worker_finished','worker_failed','worker_cancelled','operation_started','activity_finished','activity_failed','activity_unknown','root_probe_reserved','candidate_probe_reserved','edit_started','held_out_reserved','selection_frozen']);
  const activityOps = new Set(['worker','list','read','patch','evaluate','freeze','report']);
  const activityArms = new Set(['agent','unchanged','heuristic','administrator','worker']);
  function activityLabel(e) {
    const names = {list:'Case listing',read:'Tensor inspection',patch:'Numeric edit',evaluate:'Development evaluation',freeze:'Selection freeze',report:'Held-out evaluation',worker:'Worker'};
    const kinds = {worker_started:'Worker started',worker_finished:'Worker finished',worker_failed:'Worker failed or interrupted',worker_cancelled:'Worker cancellation acknowledged',root_probe_reserved:'Original policy probe reserved',candidate_probe_reserved:'Edited candidate probe reserved',held_out_reserved:'Held-out rollout reserved after all selections froze',selection_frozen:'Selection frozen',activity_unknown:'Observation unavailable'};
    return kinds[e.kind] || names[e.operation] + ({operation_started:' requested',edit_started:' admitted',activity_finished:' completed',activity_failed:' failed'}[e.kind] || '') + (e.count === null ? '' : ' · ' + e.count + ' values');
  }
  async function observeActivity() {
    const panel = $('goal-activity');
    if (!panel || !run || activityBusy) return;
    activityBusy = true;
    panel.hidden = false;
    if (activityRun !== run.experiment_id) {
      activityRun = run.experiment_id; activityCursor = 0; activityFence = 0; activityHadGap = false;
      $('goal-activity-events').replaceChildren();
    }
    const identity = activityRun, generation = epoch, cursor = activityCursor;
    const abort = new AbortController(), timeout = setTimeout(() => abort.abort(),15000);
    try {
      const headers = {'Content-Type':'application/json'};
      if (state.token) headers.Authorization = 'Bearer ' + state.token;
      const response = await fetch('/api/v1/experiments/activity',{method:'POST',headers,cache:'no-store',signal:abort.signal,body:JSON.stringify({schema_version:1,experiment_id:identity,spec_hash:run.spec_hash,after:cursor,limit:50})});
      if (!response.ok) throw Error('unavailable');
      const v = parseResponse(await response.text());
      if (generation !== epoch || identity !== activityRun) return;
      const integer = x => Number.isSafeInteger(x) && x >= 0;
      const keys = ['schema_version','experiment_id','spec_hash','available','status','phase','events','next_cursor','high_water','gap','has_more'];
      if (Object.keys(v).sort().join() !== keys.sort().join() || v.schema_version !== 1 || v.experiment_id !== identity || v.spec_hash !== run.spec_hash || v.status !== run.status || typeof v.available !== 'boolean' || typeof v.gap !== 'boolean' || typeof v.has_more !== 'boolean' || !integer(v.next_cursor) || !integer(v.high_water) || !Array.isArray(v.events) || v.events.length > 50 || v.high_water < activityFence) throw Error('invalid');
      let previous = cursor;
      for (const e of v.events) {
        if (Object.keys(e).sort().join() !== 'arm,count,kind,operation,sequence' || !integer(e.sequence) || e.sequence !== previous + 1 || !activityKinds.has(e.kind) || !activityOps.has(e.operation) || !activityArms.has(e.arm) || !(e.count === null || integer(e.count) && e.count <= 256)) throw Error('gap');
        previous = e.sequence;
      }
      if (!v.available || v.gap) {
        if (v.gap) activityHadGap = true;
        if (v.events.length || v.next_cursor < cursor || v.next_cursor > v.high_water) throw Error('gap');
        activityCursor = v.next_cursor; activityFence = Math.max(activityFence,v.high_water);
        throw Error('unavailable');
      }
      if (previous !== v.next_cursor || previous > v.high_water || v.has_more !== (previous < v.high_water)) throw Error('gap');
      activityFence = Math.max(activityFence,v.high_water);
      for (const e of v.events) {
        const item = document.createElement('li');
        item.textContent = '#' + e.sequence + ' · ' + e.arm + ' · ' + activityLabel(e);
        $('goal-activity-events').append(item);
      }
      // Keep browser memory bounded as well as each HTTP read.
      const list = $('goal-activity-events');
      while (list.children.length > 200) list.firstElementChild.remove();
      activityCursor = v.next_cursor;
      $('goal-activity-notice').textContent = (activityHadGap ? 'Some earlier observations are missing. ' : '') + 'Observed operations only. Showing up to 200 recent loaded events. ' + (v.has_more ? 'More history available.' : 'History caught up.');
      $('goal-activity-more').hidden = !v.has_more;
    } catch (_) {
      if (generation !== epoch || identity !== activityRun) return;
      $('goal-activity-notice').textContent = 'Activity unavailable. Earlier observations remain; refresh status to reconnect. No work is restarted.';
      $('goal-activity-more').hidden = true;
      $('goal-phase').textContent = run.status + ' · Activity unavailable';
    } finally { clearTimeout(timeout); activityBusy = false; }
  }
  if ($('goal-activity-more')) $('goal-activity-more').onclick = () => observeActivity();
  function bound(v) {
    if (v.spec_hash !== pending.spec_hash || run && v.experiment_id !== run.experiment_id) throw Error('invalid');
    return v;
  }
  async function observe(action = {retries:0}) {
    const body = {schema_version:1,experiment_id:run.experiment_id};
    const v = bound(await request('status',body,action)); render(v);
    await observeActivity();
    if (terminal(v.status)) {
      try { render(bound(await request('results',body,action))); }
      catch (e) {
        if (!e.poll || action.noAuto || action.retries >= 3) throw e;
        schedule(action, 2000 * 2**action.retries++);
      }
    } else schedule();
  }
  function schedule(action, delay = 2000) { clearTimeout(timer); timer = setTimeout(() => perform(() => observe(action)),delay); }
  async function reconcile(action = pending) {
    if (!run) {
      try {
        pending.inFlight = true; pending.rejected = false;
        if (!save()) throw Error('recovery_unavailable');
        const v = bound(await request('start',pending.body,action));
        pending.inFlight = false; run = v; save();
      } catch (e) {
        // A later rejection cannot erase an earlier uncertain admission.
        pending.inFlight = false;
        if (!e.confirmedNonAdmission) pending.uncertain = true;
        pending.rejected = !pending.uncertain && e.confirmedNonAdmission && e.message === 'spec_conflict';
        save();
        throw e;
      }
    }
    await observe(action);
  }
  function reviewAgain() {
    if (busy || run || !pending?.rejected || pending.uncertain) return;
    pending = null;
    $('goal-progress').hidden = true;
    invalidate();
    say('Start was rejected before admission. Review the goal again and confirm the new plan before starting.');
  }
  async function perform(fn) {
    if (busy) return; busy = true; clearTimeout(timer); lock();
    try { await fn(); $('goal-setup-help').hidden = true; } catch (e) {
      if (e.message !== 'superseded' && (!e.safe || ['unavailable','worker_unavailable'].includes(e.message))) $('goal-setup-help').hidden = false;
      if (e.message !== 'superseded') say(e.safe ? 'Service: ' + e.message + '. Draft and identity preserved. Use Refresh / reconcile to retry explicitly.' : 'Service state unavailable. Admission may have committed. Draft and identity preserved. Use Refresh / reconcile; do not start another run.');
      if (!pending && e.safe && e.message === 'unavailable') say('Service: unavailable. Your draft is preserved. Read the setup guide or open the no-key CPU example below.');
      if (pending?.rejected) say('Start rejected before admission: the reviewed plan expired or changed. Choose Review again to obtain a fresh plan. No new experiment has been started.');
      if (pending) {
        $('goal-progress').hidden = false;
        $('goal-phase').textContent = (run ? 'Last observed execution: ' + run.status : pending.rejected ? 'Not admitted' : 'Admission unknown') + ' · Activity unavailable';
      }
    } finally { busy = false; lock(); }
  }
  // Replace sample-only copy without sharing mock state or confirmation.
  $('goal-notice').textContent = 'Live experiment controls · requires operator setup. Review first, explicitly start once. Provider credentials stay on the server.';
  const mockLink = document.createElement('a'); mockLink.href = '?goalMode=mock#goal'; mockLink.textContent = 'Open separate mock walkthrough'; $('goal-notice').append(' ',mockLink);
  const setupLink = document.createElement('a'); setupLink.href = 'https://github.com/romrom-20/Gods-eye/blob/main/docs/local-operator-setup.md'; setupLink.textContent = 'Experiment service setup guide'; $('goal-notice').append(' · ',setupLink);
  $('goal-advanced').querySelector('summary').textContent = 'Advanced options · routing and seven usage limits';
  $('goal-advanced').querySelector('p').textContent = 'Finite usage limits apply to the confirmed experiment. Charges are unknown; these limits are not a hard dollar cap.';
  document.querySelector('.goal-context dd:last-child').textContent = 'Select the programmer provider and model explicitly beside your request. Its own weights are not the editable target. Availability is checked by the service at admission.';
  $('goal-interpretation').textContent = 'Supported interpretation';
  document.querySelector('#goal-programmer').previousElementSibling.textContent = 'AI programmer';
  $('goal-scenario').hidden = true; document.querySelector('label[for="goal-scenario"]').hidden = true;
  document.querySelector('label[for="goal-provider"]').textContent = 'AI programmer provider';
  document.querySelector('label[for="goal-model"]').textContent = 'AI programmer model ID (explicit selection required)';
  $('goal-model').value = ''; $('goal-model').placeholder = 'Enter your chosen tool-capable model ID';
  $('goal-plan').textContent = 'Review experiment plan'; $('goal-start').textContent = 'Start experiment';
  document.querySelector('.goal-consent').lastChild.textContent = ' I reviewed this exact specification and authorize this bounded experiment.';
  document.querySelector('#goal-review .overline').textContent = 'SERVER PLAN · REVIEW BEFORE START';
  document.querySelector('#goal-review dl + p').textContent = 'Confirm the exact server specification above, including provider, limits, registered baseline and evaluation rules. No hard dollar cap or automatic provider fallback.';
  document.querySelector('#goal-progress .overline').textContent = 'SERVICE STATUS'; $('goal-progress-title').textContent = 'Follow the experiment';
  $('goal-phase').nextElementSibling.textContent = 'Activity is shown only when observed by the service. Closing this tab does not cancel work. Cancellation requires worker acknowledgment; remote charges may continue.';
  const usage = document.createElement('p'); usage.id = 'goal-usage'; $('goal-phase').after(usage);
  $('goal-next').hidden = true; $('goal-cancel').textContent = 'Request cancellation';
  $('goal-reconnect').hidden = false; $('goal-reconnect').textContent = 'Refresh / reconcile';
  $('goal-compare').hidden = true; $('goal-comparison').hidden = true;
  document.querySelector('#goal-result .overline').textContent = 'SERVICE OUTCOME';

  ids.forEach(id => $(id).addEventListener('input',invalidate));
  $('goal-example').onclick = () => { $('goal-draft').value = 'Improve Breakout score without control regressions'; invalidate(); };
  $('goal-consent').onchange = lock; $('goal-edit').onclick = () => { invalidate(); $('goal-draft').focus(); };
  $('goal-form').addEventListener('invalid', event => {
    const options = event.target.closest('details');
    if (options) options.open = true;
    say('Choose your programmer model and check the highlighted options before reviewing the plan.');
  }, true);
  $('goal-form').onsubmit = event => {
    event.preventDefault(); if (busy || pending || !$('goal-form').reportValidity()) return;
    invalidate();
    const body = {schema_version:1,text:$('goal-draft').value,provider:{name:$('goal-provider').value,model:$('goal-model').value,routing:$('goal-routing').value},limits:Object.fromEntries(Object.entries(fields).map(([id,name]) => [name,Number($('goal-'+id).value)]))};
    perform(async () => {
      const p = await request('plan',body);
      if (p.outcome !== 'ready') {
        if (p.spec !== null || p.draft_id !== null || p.spec_hash !== null || !p.issues.length) throw Error('invalid');
        say(p.outcome === 'rejected' ? 'Unsupported goal. Draft preserved.' : 'Clarification required. Try “Improve Breakout score”. Draft preserved.'); return;
      }
      if (!p.spec || !p.draft_id || p.issues.length) throw Error('invalid');
      const s = p.spec, model = s.provider.model;
      if (model.includes('//') || model.split('/').some(x => x === '.' || x === '..') || /^[A-Za-z]:/.test(model) || s.provider.name !== 'openrouter' && s.provider.routing !== 'price') throw Error('invalid');
      const e = s.evaluation;
      if (e.forwards_per_case < e.episodes*e.max_steps*e.probes_per_case || canonical(s.provider) !== canonical(body.provider) || canonical(s.limits) !== canonical(body.limits)) throw Error('invalid');
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(s))))).map(x => x.toString(16).padStart(2,'0')).join('');
      if (digest !== p.spec_hash) throw Error('invalid');
      plan = p; $('goal-request').textContent = body.text; $('goal-canonical').textContent = JSON.stringify(s,null,2) + '\nSpecification SHA-256: ' + p.spec_hash;
      $('goal-programmer').textContent = `${s.provider.name} / ${s.provider.model} · ${s.provider.routing}`;
      const limitNames = {max_requests:'Programmer requests',max_input_tokens:'Reported input tokens',max_total_output_tokens:'Total reported output tokens',max_seconds:'Elapsed seconds',max_rounds:'Programmer rounds',max_calls:'Tool calls',max_output_tokens:'Output tokens per response'};
      const list = document.createElement('ul'); list.className = 'goal-limit-list';
      for (const [key,value] of Object.entries(s.limits)) { const item = document.createElement('li'); item.textContent = `${limitNames[key]}: ${value.toLocaleString()}`; list.append(item); }
      $('goal-limits').replaceChildren(list);
      $('goal-evaluation').textContent = `MinAtar Breakout · unchanged case roots: ${s.baseline.id}. Suite: ${e.suite_id} / ${e.revision}. ${e.episodes} episodes, up to ${e.max_steps} steps each; ${e.probes_per_case} development probes and ${e.forwards_per_case} forward passes per case. Select using development results; test held-out episodes once after all selections freeze.`;
      $('goal-review').hidden = false; say('Plan ready. Review the exact specification and explicitly authorize Start.'); $('goal-review-title').focus();
    });
  };
  $('goal-start').onclick = () => {
    if (busy || pending || !plan || !$('goal-consent').checked) return;
    pending = {body:{schema_version:1,draft_id:plan.draft_id,spec_hash:plan.spec_hash,idempotency_key:crypto.randomUUID(),confirmed:true},spec_hash:plan.spec_hash,baseline_id:plan.spec.baseline.id,retries:0,uncertain:false,rejected:false};
    if (!save()) { pending = null; lock(); return; }
    $('goal-consent').checked = false; perform(() => reconcile());
  };
  $('goal-review-again').onclick = reviewAgain;
  $('goal-reconnect').onclick = () => perform(() => pending ? reconcile({...pending,retries:0,noAuto:true}) : Promise.resolve());
  $('goal-cancel').onclick = () => {
    if (!run || terminal(run.status)) return;
    perform(async () => { render(bound(await request('cancel',{schema_version:1,experiment_id:run.experiment_id}))); schedule(); });
  };
  $('goal-keep').onclick = () => say('Original preserved. No checkpoint was applied by this page.');
  $('goal-again').onclick = () => { if (run && terminal(run.status)) { pending = null; run = null; $('goal-progress').hidden = true; invalidate(); $('goal-draft').focus(); } };
  $('goal-guided').onclick = $('goal-setup-example').onclick = () => { showView('overview'); $('quick-experiment').focus(); };
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (saved?.draft) ids.forEach(id => { if (typeof saved.draft[id] === 'string') $(id).value = saved.draft[id]; });
    if (saved?.pending) {
      const p = saved.pending; valid('start_request',p.body);
      if (p.spec_hash !== p.body.spec_hash || !shape(p.baseline_id,C.schemas.spec.properties.baseline.properties.id)) throw Error('invalid');
      pending = {...p,noAuto:true,rejected:false,uncertain:p.uncertain !== false || p.inFlight === true};
      if (saved.run) { valid('start_response',saved.run); run = bound(saved.run); }
      $('goal-progress').hidden = false;
      if (run) perform(() => observe({noAuto:true,retries:3}));
      else say('Previous Start acknowledgment unavailable. Use Refresh / reconcile to recover the same admission. No new key will be created.');
    }
  } catch { say('Saved recovery data unavailable. Review again before starting.'); }
  $('goal-consent').checked = false; lock();
})();

// Local Qwen workspace: contract v1; injected transport is used only by scripted tests.
function createLmWorkspace(env) {
  const { $, document: doc, storage, transport, uuid, token, staticMode, clock } = env;
  const root = '/api/v1/lm', storeKey = 'godseye.lm.recovery.v1';
  const terminal = j => ['completed','failed','cancelled','interrupted'].includes(j?.status);
  const hash = v => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
  const id = v => typeof v === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(v);
  const integer = v => Number.isSafeInteger(v) && v >= 0;
  const verdictLabels = {not_evaluated:'Not evaluated',no_improvement:'No improvement',inconclusive:'Inconclusive',improved_on_public_fixture:'Improved on this public fixture'};
  const plain = value => String(value).replaceAll('_',' ');
  const names = {unchanged:'Unchanged original',prompt:'Prompt prefix',decoding:'Repetition penalty 1.1','weight-0':'Column 0 × 0','weight-1':'Column 1 × 0.5'};
  let cap = null, plan = null, pending = null, job = null, result = null;
  let active = false, connected = false, busy = false, epoch = 0, timer = null, failures = 0, polls = 0, retryAllowed = false;
  const say = text => { $('lm-notice').textContent = text; };
  const node = (tag,text) => { const n = doc.createElement(tag); n.textContent = text; return n; };
  function invalid() { throw Error('The local service returned an unsupported response. Check the service version and setup.'); }
  function envelope(v) { if (!v || v.schema_version !== 1) invalid(); return v; }
  function validJob(v) {
    if (!v || !id(v.id) || !hash(v.spec_sha256) || !['queued','running','cancelling','completed','failed','cancelled','interrupted'].includes(v.status)
      || !['queued','verifying','development','freeze','heldout','finalizing','unknown'].includes(v.phase)
      || !Number.isFinite(Date.parse(v.created_at)) || !Number.isFinite(Date.parse(v.updated_at)) || !(v.reason === null || typeof v.reason === 'string')
      || typeof v.result_available !== 'boolean' || typeof v.selected_delta_available !== 'boolean'
      || !integer(v.progress?.reserved_attempts) || !integer(v.progress?.finished_attempts) || v.progress.max_attempts !== 126
      || v.progress.finished_attempts > v.progress.reserved_attempts || v.progress.reserved_attempts > 126
      || v.selected_delta_available && v.status !== 'completed') invalid();
    return v;
  }
  async function request(path, body, attachment = false) {
    if (staticMode) throw Error('Qwen execution requires the local lab.');
    const controller = new AbortController(), timeout = clock.setTimeout(() => controller.abort(),15000);
    try {
      const headers = {'Content-Type':'application/json'};
      if (token()) headers.Authorization = 'Bearer ' + token();
      const r = await transport(root + path,{headers,signal:controller.signal,...(body === undefined ? {} : {method:'POST',body:JSON.stringify(body)})});
      const raw = await r.text(); if (raw.length > 4 * 1024 * 1024) invalid();
      let v; try { v = JSON.parse(raw); } catch { invalid(); }
      if (!r.ok) {
        const e = Error(r.status === 401 ? 'Authentication required. Open Connection settings and enter the local API token.'
          : r.status === 404 ? 'This route is unavailable. Check that the local server supports Qwen contract v1.'
          : typeof v.error === 'string' ? v.error : 'Local service request failed.');
        e.status = r.status; e.code = v.schema_version === 1 ? v.code : undefined; throw e;
      }
      if (attachment) { if (!v || typeof v !== 'object') invalid(); return v; }
      return envelope(v);
    } finally { clock.clearTimeout(timeout); }
  }
  function save() {
    // Persist only identities; never requests, credentials, specifications or output.
    try { storage.setItem(storeKey,JSON.stringify({pending,job_id:job?.id || null})); return true; }
    catch { say('Tab recovery storage is unavailable. Start is disabled until session storage works.'); return false; }
  }
  function stop() { if (timer !== null) clock.clearTimeout(timer); timer = null; }
  function controls() {
    const taskSupported = !$('lm-task').value || $('lm-task').value === 'json';
    const usable = cap?.available && !cap.readonly && !staticMode;
    $('lm-controls').hidden = !usable && !pending;
    $('lm-plan').disabled = busy || !usable || !taskSupported || !!pending || !!job && !terminal(job);
    $('lm-task').disabled = busy || !!pending || !!job && !terminal(job);
    $('lm-request').disabled = busy || !!pending;
    $('lm-sample').disabled = busy || !!pending || !taskSupported;
    $('lm-start').disabled = busy || !usable || !plan || !!pending || !$('lm-consent').checked;
    $('lm-resolve').disabled = busy;
    $('lm-retry').hidden = !retryAllowed;
    $('lm-retry').disabled = busy || !usable;
    $('lm-recovery').hidden = !pending;
    $('lm-discard').hidden = !(retryAllowed && pending?.rejected);
    $('lm-discard').disabled = busy;
    $('lm-cancel').hidden = !job || terminal(job);
    $('lm-cancel').disabled = busy || job?.status === 'cancelling' || !usable;
    $('lm-refresh').disabled = busy;
    $('lm-history-refresh').disabled = busy || !!pending;
  }
  async function perform(fn) {
    if (busy || staticMode) return;
    busy = true; controls();
    try { await fn(); } catch(e) { say(e.message || 'Connection lost. No automatic execution retry was made.'); }
    finally { busy = false; controls(); }
  }
  function schedule(delay = 3000) {
    stop(); if (!active || doc.hidden || !job || terminal(job) || polls >= 200) return;
    timer = clock.setTimeout(() => observe(),delay);
  }
  function renderJob(v) {
    job = v; save(); $('lm-job').hidden = false;
    $('lm-job-title').textContent = `${v.status} · ${v.id}`;
    $('lm-progress').textContent = `Phase: ${v.phase === 'unknown' ? 'unknown — no phase reported' : v.phase}. ${v.progress.finished_attempts} finished / ${v.progress.reserved_attempts} reserved attempts; ceiling ${v.progress.max_attempts}. This is not percent complete.${v.reason ? ' Reason: ' + v.reason + '.' : ''}`;
    $('lm-map').replaceChildren(node('span','Reviewed specification · ' + v.spec_sha256.slice(0,12)),node('span','→ Job · ' + v.id),node('span','→ ' + (v.result_available ? 'Recorded evidence available' : 'Evidence not yet available')));
    if (v.status === 'cancelling') say('Cancellation requested. Waiting for the owned process to exit; cancellation is not yet confirmed.');
    else if (terminal(v)) say(v.status === 'cancelled' ? 'Cancellation confirmed by the service. No automatic resume or retry.' : 'Job ' + v.status + '. Inspect the recorded evidence and its separate evaluation verdict.');
    controls();
  }
  function accept(v, expectedId, expectedHash) {
    validJob(v);
    if (expectedId && v.id !== expectedId || expectedHash && v.spec_sha256 !== expectedHash) invalid();
    if (job?.id === v.id && (terminal(job) && !terminal(v) || Date.parse(v.updated_at) < Date.parse(job.updated_at))) return false;
    renderJob(v); return true;
  }
  async function observe() {
    if (!job || staticMode || doc.hidden || !active) return;
    stop(); const fence = epoch, current = job.id, spec = job.spec_sha256; polls++;
    try {
      const v = await request('/jobs/' + encodeURIComponent(current));
      if (fence !== epoch) return;
      if (!accept(v.job,current,spec)) return;
      failures = 0;
      if (terminal(job)) { await loadResult(fence); }
      else { say('Observing the local job. Status checks never run inference.'); schedule(); }
    } catch(e) {
      if (fence !== epoch) return;
      const delay = [5000,10000,20000][failures++];
      say(`${e.message} ${delay ? 'Read-only status check in ' + delay/1000 + ' seconds.' : 'Automatic polling paused. Use Refresh status to check again.'}`);
      if (delay) schedule(delay);
    }
    if (polls >= 200) say('Automatic observation limit reached. The job may still be running. Use Refresh status for a read-only check.');
  }
  function invalidatePlan() { plan = null; $('lm-review').hidden = true; $('lm-consent').checked = false; controls(); }
  function reviewFacts(p) {
    const s = p.spec;
    $('lm-review-facts').replaceChildren();
    for (const [label,value] of [
      ['Target',s.model.id + ' · local CPU · no provider fee'],
      ['Public fixture','28 cases · 10 JSON targets + 4 text controls per split'],
      ['Weight edits',s.operations.parameter + ': column 0 × 0; column 1 × 0.5. Each starts from the untouched original.'],
      ['Alternatives','Unchanged original; JSON-target-only prompt prefix; repetition penalty 1.1.'],
      ['Finite ceilings',`${s.budgets.max_attempts} attempts · ${s.budgets.max_output_tokens_per_attempt} output tokens each · ${s.budgets.max_worker_seconds / 60} minutes total · 1 worker · no retries. These are ceilings, not a time estimate.`],
      ['Evaluation','Development selects once; heldout only after persisted freeze. Zero allowed text-control regressions.'],
      ['Plan expiry',p.expires_at]
    ]) $('lm-review-facts').append(node('dt',label),node('dd',value));
    $('lm-spec').textContent = JSON.stringify(s,null,2) + '\nSpecification SHA256: ' + p.spec_sha256;
  }
  function canonical(v, key = '') {
    // TaskSpec v1 uses Python float spelling at these two fixed recipe fields.
    // JSON numbers lose that distinction after parsing in JavaScript.
    if (Array.isArray(v)) return '[' + v.map(x=>canonical(x)).join(',') + ']';
    if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map(k=>canonical(k)+':'+canonical(v[k],k)).join(',') + '}';
    if (typeof v === 'number' && Number.isInteger(v) && ['scale','repetition_penalty'].includes(key)) return v.toFixed(1);
    return JSON.stringify(v).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  }
  async function review() {
    if ($('lm-task').value && $('lm-task').value !== 'json' || pending || job && !terminal(job)) return;
    invalidatePlan();
    const v = await request('/plan',{schema_version:1,request:$('lm-request').value});
    if (!['ready','unsupported','clarification_required'].includes(v.outcome) || typeof v.message !== 'string') invalid();
    say(v.message);
    if (v.outcome !== 'ready') {
      if ([v.plan_id,v.spec_sha256,v.spec,v.expires_at].some(x=>x!==null)) invalid();
      return;
    }
    const s = v.spec;
    if (!id(v.plan_id) || !hash(v.spec_sha256) || typeof v.expires_at !== 'string' || !s
      || s.model?.id !== 'Qwen/Qwen2.5-0.5B-Instruct' || !/^[a-f0-9]{40}$/.test(s.model.revision)
      || s.budgets?.max_attempts !== 126 || s.budgets?.max_output_tokens_per_attempt !== 96 || s.budgets?.max_worker_seconds !== 1800
      || s.operations?.parameter !== 'model.layers.0.mlp.down_proj.weight'
      || JSON.stringify(s.operations.candidates) !== JSON.stringify([{column:0,scale:0},{column:1,scale:0.5}])
      || s.baselines?.prompt?.scope !== 'json_targets_only' || s.baselines?.decoding?.repetition_penalty !== 1.1) invalid();
    if (await env.digest(canonical(s)) !== v.spec_sha256) invalid();
    plan = v; reviewFacts(v); $('lm-plan-message').textContent = v.message;
    $('lm-review').hidden = false; $('lm-review-title').focus();
    say('Plan ready. Review the exact specification, then explicitly Start. No inference has run.');
  }
  async function start(retry = false) {
    if (!retry) {
      if (!plan || pending || !$('lm-consent').checked) return;
      pending = {schema_version:1,plan_id:plan.plan_id,spec_sha256:plan.spec_sha256,idempotency_key:uuid()};
    } else if (!pending || !retryAllowed) return;
    retryAllowed = false;
    if (!save()) return;
    const tuple = {schema_version:1,plan_id:pending.plan_id,spec_sha256:pending.spec_sha256,idempotency_key:pending.idempotency_key};
    epoch++; stop(); result = null; $('lm-result').hidden = true;
    try {
      const v = await request('/jobs',tuple);
      if (!accept(v.job,null,tuple.spec_sha256)) invalid();
      pending = null; save(); invalidatePlan(); polls = 0;
      say('Start admitted. Observing this job; no second execution was submitted.');
      if (terminal(job)) await loadResult(epoch); else schedule();
    } catch(e) {
      // Even a failed transport or malformed acknowledgment can follow admission.
      if (!pending) { say(e.message + ' The job was admitted; use Refresh status to read its evidence.'); return; }
      pending.rejected = ['plan_expired','invalid_request','conflict'].includes(e.code);
      save(); say(e.message + ' Start outcome is uncertain. Check pending start before any explicit same-key retry.');
    }
  }
  async function resolve() {
    if (!pending) return;
    retryAllowed = false;
    try {
      const v = await request('/resolve',{schema_version:1,spec_sha256:pending.spec_sha256,idempotency_key:pending.idempotency_key});
      epoch++; stop(); accept(v.job,null,pending.spec_sha256); pending = null; save(); invalidatePlan(); polls = 0;
      say('The pending start was admitted. Reopened its original job.');
      if (terminal(job)) await loadResult(epoch); else schedule();
    } catch(e) {
      if (e.status === 404 && e.code === 'not_found' && pending) { retryAllowed = true; say('No admission found for this exact key and specification. You may explicitly retry the same start; its original identity will be retained.'); }
      else throw e;
    }
  }
  async function select(v) {
    if (pending) return;
    epoch++; stop(); result = null; $('lm-result').hidden = true; invalidatePlan();
    accept(v); polls = 0;
    if (terminal(job)) await loadResult(epoch); else schedule();
  }
  function validResult(v) {
    if (!Array.isArray(v.attempts) || !integer(v.interrupted_attempts) || !(v.report === null || typeof v.report === 'object')) invalid();
    const fields = ['attempt_id','spec_sha256','case_id','split','variant','status','output','input_tokens','output_tokens','elapsed_seconds'].sort().join(',');
    if (v.attempts.length > 126 || new Set(v.attempts.map(a=>a?.attempt_id)).size !== v.attempts.length) invalid();
    for (const a of v.attempts) if (!a || Object.keys(a).sort().join(',') !== fields || a.spec_sha256 !== job.spec_sha256
      || typeof a.output !== 'string' || a.output.length > 16384 || !id(a.attempt_id) || !['complete','failed','budget_limited','cancelled','incomplete'].includes(a.status)
      || !['dev','heldout'].includes(a.split) || !names[a.variant] || typeof a.case_id !== 'string') invalid();
    if (v.report?.spec_sha256 && v.report.spec_sha256 !== job.spec_sha256) invalid();
    return v;
  }
  async function loadResult(fence) {
    if (!job.result_available) {
      $('lm-result').hidden = false; $('lm-result-content').hidden = true; $('lm-verdict').textContent = 'No recorded result available';
      $('lm-result-reason').textContent = `${plain(job.reason || job.status)}. No selected result is available. Review the stop reason before explicitly reviewing a new plan.`;
      $('lm-evidence').hidden = true; $('lm-delta').hidden = true; return;
    }
    const current = job.id, spec = job.spec_sha256;
    const v = await request('/jobs/' + encodeURIComponent(current) + '/result');
    if (fence !== epoch) return;
    validJob(v.job); if (v.job.id !== current || v.job.spec_sha256 !== spec || !terminal(v.job)) invalid();
    validResult(v); result = v; renderResult();
  }
  function renderResult() {
    const r = result.report, attempts = result.attempts;
    $('lm-result').hidden = false; $('lm-result-content').hidden = false;
    $('lm-verdict').textContent = verdictLabels[r?.verdict] || 'Not evaluated';
    const dev = attempts.filter(a=>a.split === 'dev').length, heldout = attempts.filter(a=>a.split === 'heldout').length;
    const capped = attempts.filter(a=>a.status === 'budget_limited' || ['token_cap','max_new_tokens','length'].includes(a.termination)).length;
    $('lm-result-reason').textContent = `${dev} development attempts · ${heldout} heldout attempts · ${result.interrupted_attempts} interrupted reservations. ${job.reason === 'budget_limited' ? 'A finite execution or token limit stopped evaluation. Development output is partial evidence; heldout evaluation and selection were not completed.' : (job.reason ? plain(job.reason) : null) || 'Read the verdict with the public fixture limitations.'} ${job.selected_delta_available ? 'Server reports a verified selected delta available.' : 'No verified selected delta is available. Unchanged or unused candidates are not selected edits.'}${capped ? ' Token-capped responses remain partial.' : ''}`;
    $('lm-report').textContent = JSON.stringify({job:result.job,report:r,interrupted_attempts:result.interrupted_attempts},null,2);
    $('lm-counts').replaceChildren();
    // Counts come from recomputed service arms; never invent missing evaluations.
    for (const [split,arms] of [['Development',r?.development],['Heldout',r?.heldout]]) {
      for (const [variant,a] of Object.entries(arms || {})) {
        const c = r?.comparisons?.[variant];
        const card = node('article',''); card.append(node('h3',`${split} · ${names[variant] || variant}`));
        if (a.attempts === 0) {
          card.append(node('p','No recorded attempts. Schema, semantics and text controls were not evaluated.'));
          $('lm-counts').append(card); continue;
        }
        card.append(node('p',`Schema-valid: ${a.schema_successes ?? 'unknown'}/${a.target_n ?? 'unknown'} · Semantically correct: ${a.semantic_successes ?? 'unknown'}/${a.target_n ?? 'unknown'}`));
        card.append(node('p',`Text controls correct: ${a.regression_successes ?? 'unknown'}/${a.regression_n ?? 'unknown'} · Arm ${a.complete ? 'complete' : 'incomplete'}`));
        if (split === 'Development') {
          const original = r?.development?.unchanged?.records || [];
          const controls = (a.records || []).filter(x=>x.task === 'regression');
          const paired = controls.map(x=>[x,original.find(b=>b.case_id === x.case_id)]);
          const known = paired.length === 4 && paired.every(([x,b])=>b && x.status === 'complete' && b.status === 'complete');
          card.append(node('p','Observed control regressions: ' + (known ? paired.filter(([x,b])=>b.correct && !x.correct).length + '/4' : 'unknown')));
        }
        if (split === 'Heldout' && c) card.append(node('p',`Control regressions: ${c.regression_failures ?? 'unknown'} · Semantic regressions: ${c.semantic_regressions ?? 'unknown'} · ${verdictLabels[c.verdict] || 'Not evaluated'}`));
        $('lm-counts').append(card);
      }
    }
    if (!r) $('lm-counts').append(node('p','No recomputed report is available. Inspect recorded responses; scores and regressions remain unknown.'));
    $('lm-evidence').hidden = false;
    $('lm-delta').hidden = !job.selected_delta_available;
    $('lm-rollback').hidden = !job.selected_delta_available;
    choices($('lm-variant'),Object.keys(names).map(value=>[value,names[value]]));
    if (attempts.some(a=>a.variant === 'weight-0')) $('lm-variant').value = 'weight-0';
    updateCases();
  }
  function choices(el,entries) {
    el.replaceChildren(); for (const [value,label] of entries) { const o = node('option',label); o.value = value; el.append(o); }
    if (entries.length) el.value = entries[0][0];
  }
  function updateCases() {
    if (!result) return;
    const a = result.attempts.filter(a=>a.split === $('lm-split').value);
    choices($('lm-case'),[...new Set(a.map(a=>a.case_id))].map(x=>[x,x])); compare();
  }
  function compare() {
    if (!result) return;
    const split = $('lm-split').value, variant = $('lm-variant').value, caseId = $('lm-case').value;
    const score = a => !a ? 'No recorded attempt' : `${plain(a.status)} · ${a.output_tokens ?? 'unknown'} output tokens · schema-valid: ${a.schema_ok ?? 'unknown / text control'} · semantically correct: ${a.correct ?? 'unknown'}`;
    for (const [prefix,v] of [['original','unchanged'],['candidate',variant]]) {
      const a = result.attempts.find(a=>a.split === split && a.variant === v && a.case_id === caseId);
      // Attempt scores may be absent in the public record; use recomputed arm records if present.
      const arm = (split === 'dev' ? result.report?.development : result.report?.heldout)?.[v];
      const scored = arm?.records?.find(r=>r.case_id === caseId) || a;
      $('lm-' + prefix).textContent = a?.output ?? 'No output was recorded for this case and variant.';
      $('lm-' + prefix + '-score').textContent = score(scored);
    }
    $('lm-candidate-title').textContent = names[variant] || 'Candidate';
  }
  async function history() {
    const v = await request('/jobs'); if (!Array.isArray(v.jobs) || v.jobs.length > 20) invalid();
    v.jobs.forEach(validJob); $('lm-history').replaceChildren();
    if (!v.jobs.length) $('lm-history').append(node('p','No saved local Qwen jobs. Review a supported request to begin.'));
    for (const j of v.jobs) { const b = node('button',`${j.status} · ${j.id} · ${j.created_at}`); b.className = 'secondary'; b.disabled = !!pending; b.onclick = () => perform(()=>select(j)); $('lm-history').append(b); }
  }
  async function connect() {
    if (staticMode) return;
    try {
      const v = await request('/capabilities');
      if (typeof v.available !== 'boolean' || typeof v.readonly !== 'boolean' || v.execution !== 'local_cpu'
        || v.model?.id !== 'Qwen/Qwen2.5-0.5B-Instruct' || v.supported_goal !== 'correct_bounded_json'
        || v.limits?.max_attempts !== 126 || v.limits?.max_new_tokens !== 96 || v.limits?.max_worker_seconds !== 1800 || v.limits?.max_concurrency !== 1) invalid();
      cap = v; connected = true;
      $('lm-setup').hidden = v.available && !v.readonly;
      say(v.readonly ? 'This server is read-only. Local Qwen execution is disabled. See local service setup.' : v.available ? 'Local Qwen service ready for review. Model hashes are checked only after explicit Start.' : 'Qwen runtime unavailable. ' + (v.reason || 'Configure the local service using the setup links.'));
      await history();
      if (pending) await resolve();
      else if (job) { const current = job.id; const r = await request('/jobs/' + encodeURIComponent(current)); validJob(r.job); if (r.job.id !== current) invalid(); await select(r.job); }
    } catch(e) { $('lm-setup').hidden = false; say(e.message + ' See local service setup below.'); }
    controls();
  }
  async function download(kind) {
    if (!job || !terminal(job) || !job.result_available || kind === 'selected_delta' && !job.selected_delta_available) return;
    const fence = epoch, current = job.id;
    const v = await request('/jobs/' + encodeURIComponent(current) + '/export',{schema_version:1,kind},true);
    if (fence !== epoch) return;
    env.download(v,`${current}-${kind}.json`); say('Downloaded ' + kind.replace('_',' ') + ' JSON.');
  }
  function view(visible) {
    active = visible; if (!visible) { stop(); return; }
    if (!staticMode && !connected) perform(connect); else if (job && !terminal(job)) schedule();
  }
  if (staticMode) {
    $('lm-notice').textContent = 'Qwen experiments run only in the local lab. This static export contains no executable Qwen controls and never contacts the API, including with mock flags.';
    $('lm-setup').hidden = false; $('lm-connect').hidden = true; $('lm-history-refresh').hidden = true;
    $('lm-controls').hidden = true;
    return {view,connect:async()=>{}};
  }
  try {
    const saved = JSON.parse(storage.getItem(storeKey) || 'null');
    if (saved?.pending) {
      const p = saved.pending;
      if (p.schema_version !== 1 || !id(p.plan_id) || !hash(p.spec_sha256) || !/^[0-9a-f-]{36}$/i.test(p.idempotency_key)) invalid();
      pending = {schema_version:1,plan_id:p.plan_id,spec_sha256:p.spec_sha256,idempotency_key:p.idempotency_key,...(p.rejected ? {rejected:true} : {})};
    }
    if (saved?.job_id && id(saved.job_id)) job = {id:saved.job_id};
  } catch { say('Saved identity could not be read. Check session storage before starting.'); $('lm-setup').hidden = false; busy = true; }
  $('lm-sample').onclick = () => { $('lm-request').value = cap?.sample_request || 'Improve JSON schema adherence'; invalidatePlan(); $('lm-request').focus(); };
  $('lm-task').onchange = () => {
    invalidatePlan();
    const messages = {
      json:'The JSON experiment uses bundled examples and two fixed weight edits. It does not discover edits from an arbitrary request.',
      math:'Not implemented: a math experiment needs example problems with verified answers, a separate heldout set, and a scorer for mathematical correctness. The current JSON score does not measure math ability. Your request is kept below; no experiment has started.',
      driving:'Not implemented: a driving experiment needs a compatible policy model, simulator, observations/actions, and tests for collisions and task completion. This Qwen text runtime cannot evaluate a vehicle controller. Your request is kept below; no experiment has started.'
    };
    $('lm-task-help').textContent = messages[$('lm-task').value] || 'Unsupported task. No experiment has started.';
    say($('lm-task').value === 'json' ? 'JSON benchmark selected. Review the request before Start.' : 'This task is not executable yet. See what is missing below.');
  };
  $('lm-request').oninput = invalidatePlan;
  $('lm-consent').onchange = controls;
  $('lm-plan').onclick = () => perform(review);
  $('lm-start').onclick = () => perform(()=>start());
  $('lm-resolve').onclick = () => perform(resolve);
  $('lm-retry').onclick = () => perform(()=>start(true));
  $('lm-discard').onclick = () => { if (!busy && pending?.rejected && retryAllowed) { pending = null; save(); invalidatePlan(); say('Rejected, unadmitted plan released. Review a fresh plan before Start.'); } };
  $('lm-connect').onclick = () => perform(connect);
  $('lm-refresh').onclick = () => { failures = 0; polls = 0; observe(); };
  $('lm-history-refresh').onclick = () => perform(history);
  $('lm-cancel').onclick = () => perform(async()=>{
    if (!job || terminal(job)) return;
    epoch++; stop(); const current = job.id, spec = job.spec_sha256;
    try {
      const v = await request('/jobs/' + encodeURIComponent(current) + '/cancel',{schema_version:1});
      accept(v.job,current,spec); if (terminal(job)) await loadResult(epoch);
    } finally { schedule(); }
  });
  $('lm-split').onchange = updateCases; $('lm-case').onchange = compare; $('lm-variant').onchange = compare;
  $('lm-evidence').onclick = () => perform(()=>download('evidence'));
  $('lm-delta').onclick = () => perform(()=>download('selected_delta'));
  doc.addEventListener('visibilitychange',()=>{ if (doc.hidden) stop(); else if(active) { failures = 0; polls = 0; schedule(); } });
  controls();
  return {view,connect:()=>perform(connect)};
}
// End local Qwen controller.
if (typeof window !== "undefined" && typeof document !== "undefined") window.lmWorkspace = createLmWorkspace({ $, document, staticMode:staticDemo,
  digest:async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join(''),
  storage:{getItem:key=>sessionStorage.getItem(key),setItem:(key,value)=>sessionStorage.setItem(key,value)}, transport:(...args)=>fetch(...args), uuid:()=>crypto.randomUUID(), token:()=>state.token,
  clock:{setTimeout:(fn,ms)=>setTimeout(fn,ms),clearTimeout:id=>clearTimeout(id)},
  download:(value,name)=>{ const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
});


initialize();
