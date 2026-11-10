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
  goal: ["Describe a goal", "Describe the change. Review the evidence", "One supported goal, a reversible edit, and an honest result."],
  overview: [
    "Overview",
    "A window into the weights",
    "Explore the network. Change a connection. See what happens.",
  ],
  workbench: [
    "Tensor lab",
    "Make a deliberate change",
    "Read the computation, write a hypothesis, and branch the network.",
  ],
  evaluate: [
    "Evaluations",
    "Let behavior be the evidence",
    "Compare two checkpoints under the same experimental conditions.",
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
  if (name !== "overview") stopReplay();
  state.view = name;
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
  dot.textContent = ".";
  $("page-title").append(dot);
  $("page-description").textContent = viewInfo[name][2];
  document.querySelector(".page-heading > .primary").hidden =
    name === "workbench" || name === "goal";
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
    throw new Error(
      (data.error || "Request failed") +
        (data.issues
          ? ": " + data.issues.map((i) => i.field + " " + i.message).join("; ")
          : ""),
    );
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
  for (const id of ["apply", "preview-patch", "evaluate"]) {
    $(id).disabled = recorded;
    $(id).title = recorded ? "Start the local lab to use this operation" : "";
  }
  document.querySelector(".eval-footer > span").textContent = recorded
    ? "Recorded demo · execution disabled"
    : "Ready for local execution";
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
async function refresh() {
  const data = await api("/api/state");
  state.checkpoints = data.checkpoints;
  configureMode(data);
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
}
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
    button.innerHTML = "Create checkpoint <span>↗</span>";
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
async function loadHistory() {
  const runs = await api("/api/runs");
  state.runs = runs;
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
  state.job = job.id;
  $("evaluate").disabled = true;
  $("job-progress-wrap").hidden = false;
  $("cancel-job").disabled = false;
  try {
    while (true) {
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
    $("evaluate").disabled = state.mode === "recorded-demo";
    $("job-progress-wrap").hidden = true;
    await loadJobs();
  }
}
async function loadJobs() {
  try {
    const jobs = await api("/api/v1/jobs");
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
async function initialize() {
  drawArchitecture();
  updateLineNumbers();
  showView(location.hash.slice(1) || "goal");
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
  } catch (e) {
    $("environment-label").textContent = "Local lab unavailable";
    $("connection-label").textContent = "Disconnected";
    $("execution-label").textContent = "Local engine unavailable · mock goal flow available";
    message("overview-status", "Cannot reach the local lab. Check the server and connection settings, then reload. The mock goal workflow remains available.", true);
  }
}
// Goal workflow: mock-only boundary. No api(), fetch(), provider profiles, or keys.
(() => {
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
    showView("workbench");
    $("preset-ablate").click();
    message("patch-result", "Guided example: preview the known four-weight edit, apply it as a new checkpoint, then open Evaluations to compare against paper. No AI programmer is involved.");
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
initialize();
