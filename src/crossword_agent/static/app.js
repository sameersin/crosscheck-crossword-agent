/* Crosscheck browser client. API responses are data: never insert them as HTML. */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    config: null, samples: [], puzzle: null, entries: [], grid: [], assignments: {},
    candidates: {}, selected: null, result: null, events: [], jobId: null,
    running: false, loading: false, startedAt: null, timer: null, pollTimer: null,
    lastEvent: 0, pollFailures: 0, preview: null, imageUrl: null, extraction: null,
    importVersion: 0, evaluationLoaded: false,
  };

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function errorMessage(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => {
        if (typeof item === "string") return item;
        const where = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(" → ") : "";
        return `${where ? `${where}: ` : ""}${item.msg || "Invalid value"}`;
      }).join("\n");
    }
    return "The request could not be completed. Please try again.";
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { Accept: "application/json", ...options.headers } });
    let body;
    try { body = await response.json(); }
    catch { throw new Error(`The server returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const error = new Error(errorMessage(body.detail || body.error));
      error.status = response.status;
      throw error;
    }
    return body;
  }

  const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const formatNumber = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : "—";
  const formatTime = (seconds) => seconds < 60 ? `${Number(seconds).toFixed(1)}s` : `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;

  function message(text, kind = "error") {
    $("global-message").textContent = text;
    $("global-message").className = `notice ${kind}`;
    $("global-message").hidden = !text;
  }

  function setStatus(label, kind = "") {
    $("solve-status").textContent = label;
    $("solve-status").className = `state-pill ${kind}`;
  }

  function updateControls() {
    const locked = state.running || state.loading;
    $("sample-select").disabled = locked;
    $("json-import").disabled = locked;
    $("image-import").disabled = locked || !state.config?.provider_ready;
    $("solve-button").disabled = locked || !state.puzzle || !state.config?.provider_ready;
    $("solve-button").hidden = state.running;
    $("cancel-button").hidden = !state.running;
    $("cancel-button").disabled = state.running && !state.jobId;
    $("reset-button").disabled = locked || !state.puzzle;
    $("download-button").disabled = !state.result;
    document.querySelectorAll(".options-grid input").forEach((input) => { input.disabled = locked; });
  }

  function setView(view) {
    const valid = ["solver", "evaluation", "architecture"].includes(view) ? view : "solver";
    document.querySelectorAll(".view").forEach((section) => { section.hidden = section.id !== `view-${valid}`; });
    document.querySelectorAll(".nav-button").forEach((button) => {
      const active = button.dataset.view === valid;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    if (valid === "evaluation" && !state.evaluationLoaded) loadEvaluation();
  }

  function fillCount() {
    let filled = 0;
    let total = 0;
    for (const row of state.grid) for (const letter of row) {
      if (letter !== "#") { total += 1; if (/[A-Z]/.test(letter)) filled += 1; }
    }
    return { filled, total };
  }

  function updateProgress(label) {
    const { filled, total } = fillCount();
    $("progress-count").textContent = `${filled} / ${total} cells`;
    $("progress-fill").style.width = `${total ? filled / total * 100 : 0}%`;
    if (label) $("progress-label").textContent = label;
  }

  function selectedEntry() { return state.entries.find((entry) => entry.id === state.selected); }

  function renderGrid() {
    const grid = $("crossword-grid");
    const focusedCell = document.activeElement?.dataset.cell;
    grid.replaceChildren();
    if (!state.grid.length) return;
    const width = state.grid[0].length;
    const height = state.grid.length;
    grid.style.gridTemplateColumns = `repeat(${width}, minmax(0, 1fr))`;
    grid.setAttribute("aria-label", `${height} row by ${width} column crossword. Select a cell or clue to highlight an entry.`);
    grid.style.maxWidth = `${Math.min(440, Math.max(290, width * 74))}px`;
    const numbers = new Map(state.entries.map((entry) => [`${entry.row},${entry.col}`, entry.number]));
    const chosen = selectedEntry();
    const selectedCells = new Set((chosen?.cells || []).map(([row, col]) => `${row},${col}`));
    for (let row = 0; row < height; row += 1) {
      for (let col = 0; col < width; col += 1) {
        const letter = state.grid[row][col];
        const block = letter === "#";
        const cell = node(block ? "div" : "button", `grid-cell${block ? " block" : ""}`);
        if (block) cell.setAttribute("aria-hidden", "true");
        else {
          const fixed = /[A-Z]/.test(state.puzzle.grid[row][col]);
          const key = `${row},${col}`;
          cell.dataset.cell = key;
          const number = numbers.get(key);
          if (selectedCells.has(key)) cell.classList.add("selected");
          if (fixed) cell.classList.add("fixed");
          else if (letter !== ".") cell.classList.add("proposed");
          if (number) cell.append(node("span", "cell-number", number));
          cell.append(node("span", "cell-letter", letter === "." ? "" : letter));
          cell.setAttribute("aria-label", `Row ${row + 1}, column ${col + 1}${number ? `, clue ${number}` : ""}: ${letter === "." ? "empty" : letter}${fixed ? ", given letter" : ""}`);
          cell.setAttribute("aria-pressed", String(selectedCells.has(key)));
          if (width > 9) {
            cell.style.fontSize = `clamp(10px, ${38 / width}vw, ${Math.max(13, 155 / width)}px)`;
            const numberNode = cell.querySelector(".cell-number");
            if (numberNode) { numberNode.style.fontSize = width > 16 ? "5px" : "7px"; numberNode.style.left = "2px"; numberNode.style.top = "2px"; }
          }
          cell.addEventListener("click", () => {
            const entries = state.entries.filter((entry) => entry.cells.some(([r, c]) => r === row && c === col));
            const current = entries.findIndex((entry) => entry.id === state.selected);
            selectEntry(entries[(current + 1) % entries.length]?.id);
          });
        }
        grid.append(cell);
      }
    }
    if (focusedCell) grid.querySelector(`[data-cell="${CSS.escape(focusedCell)}"]`)?.focus({ preventScroll: true });
  }

  function renderClues() {
    for (const direction of ["across", "down"]) {
      const list = $(`${direction}-clues`);
      const entries = state.entries.filter((entry) => entry.direction === direction);
      const scrollTop = list.scrollTop;
      const focusedEntry = document.activeElement?.dataset.entry;
      list.replaceChildren();
      $(`${direction}-count`).textContent = `${entries.length} ${entries.length === 1 ? "clue" : "clues"}`;
      for (const entry of entries) {
        const li = node("li");
        const button = node("button", `clue-button${entry.id === state.selected ? " selected" : ""}`);
        button.dataset.entry = entry.id;
        button.setAttribute("aria-pressed", String(entry.id === state.selected));
        button.setAttribute("aria-label", `${entry.number} ${direction}: ${entry.clue}, ${entry.length} letters${state.assignments[entry.id] ? `, proposed answer ${state.assignments[entry.id]}` : ""}`);
        button.append(node("span", "clue-number", entry.number));
        const text = node("span", "clue-text", entry.clue);
        text.append(node("span", "clue-length", `(${entry.length})`));
        if (state.assignments[entry.id]) text.append(node("span", "clue-answer", state.assignments[entry.id]));
        button.append(text);
        button.addEventListener("click", () => selectEntry(entry.id));
        li.append(button);
        list.append(li);
      }
      list.scrollTop = scrollTop;
      if (focusedEntry) list.querySelector(`[data-entry="${CSS.escape(focusedEntry)}"]`)?.focus({ preventScroll: true });
    }
  }

  function selectEntry(id) {
    if (!id) return;
    state.selected = id;
    renderGrid();
    renderClues();
    renderInspector();
  }

  function renderInspector() {
    const entry = selectedEntry();
    const inspector = $("candidate-inspector");
    const selected = $("selected-clue");
    inspector.replaceChildren();
    selected.replaceChildren();
    if (!entry) {
      inspector.append(node("p", "muted", "Select a clue to inspect its letter pattern and candidate answers."));
      selected.append(node("span", "selected-clue-label", "A CROSSWORD IS A CONVERSATION"), node("p", "", "Select a clue to see its crossing cells."));
      return;
    }
    const label = `${entry.number} ${entry.direction.toUpperCase()}`;
    selected.append(node("span", "selected-clue-label", label));
    const clue = node("p", "", entry.clue);
    clue.append(node("span", "", `(${entry.length})`));
    selected.append(clue);
    inspector.append(node("span", "selected-clue-label", `${label} · ${entry.length} LETTERS`));
    inspector.append(node("p", "inspector-clue", entry.clue));
    const pattern = entry.cells.map(([row, col]) => state.grid[row]?.[col] || ".").join("").replaceAll(".", "_");
    inspector.append(node("div", "pattern", pattern));
    const candidates = state.candidates[entry.id] || [];
    if (candidates.length) {
      const list = node("ul", "candidate-list");
      for (const candidate of candidates) {
        const chosen = candidate.answer === state.assignments[entry.id];
        const item = node("li", chosen ? "chosen" : "");
        item.append(node("span", "", candidate.answer), node("span", "", chosen ? "Current answer" : `Rank score ${Number(candidate.score).toFixed(2)}`));
        list.append(item);
      }
      inspector.append(list, node("p", "candidate-note", "Model scores rank suggestions; they are not calibrated probabilities."));
    } else inspector.append(node("p", "muted", state.running ? "Candidates will be available with the final result." : "Solve the puzzle to see the model’s candidate answers."));
  }

  function renderWorkspace() { renderGrid(); renderClues(); renderInspector(); updateProgress(); }

  function resetRun() {
    if (state.running || !state.puzzle) return;
    state.grid = [...state.puzzle.grid];
    state.assignments = {};
    state.candidates = {};
    state.result = null;
    state.events = [];
    state.jobId = null;
    state.lastEvent = 0;
    state.pollFailures = 0;
    $("result-notice").hidden = true;
    for (const key of ["time", "calls", "tokens", "nodes"]) $(`metric-${key}`).textContent = "—";
    $("live-label").className = "live-label";
    $("live-label").replaceChildren(node("span", "status-dot"), document.createTextNode(" Waiting"));
    const empty = node("div", "timeline-empty");
    empty.append(node("span", "empty-icon", "≋"), node("p", "", "The thinking becomes visible here."), node("span", "", "Actual model calls, crossing checks, and repair steps will appear during the solve."));
    $("event-timeline").replaceChildren(empty);
    setStatus("Ready to solve");
    renderWorkspace();
    updateProgress("Ready when you are");
    updateControls();
  }

  function adoptPuzzle(validated, source) {
    state.puzzle = validated.puzzle;
    state.entries = validated.entries;
    state.selected = state.entries[0]?.id || null;
    $("puzzle-title").textContent = state.puzzle.title || "Untitled crossword";
    $("puzzle-meta").textContent = `${state.puzzle.grid.length} × ${state.puzzle.grid[0].length} GRID / ${state.entries.length} CLUES${state.puzzle.author ? ` / ${state.puzzle.author}` : ""}`;
    if (source) $("sample-description").textContent = source;
    resetRun();
    message("");
  }

  async function loadSample(id) {
    if (!id || state.running) return;
    state.loading = true;
    updateControls();
    try {
      const puzzle = await api(`/api/samples/${encodeURIComponent(id)}`);
      const validated = await post("/api/validate", puzzle);
      adoptPuzzle(validated, state.samples.find((sample) => sample.id === id)?.description || "An authored sample puzzle. Its reference answer is not supplied to the solver.");
    } catch (error) { message(error.message); }
    finally { state.loading = false; updateControls(); }
  }

  function appendEvents(events) {
    const fresh = events.filter((event) => event.sequence > state.lastEvent);
    if (!fresh.length) return;
    const timeline = $("event-timeline");
    timeline.querySelector(".timeline-empty")?.remove();
    let changed = false;
    for (const event of fresh) {
      state.lastEvent = Math.max(state.lastEvent, event.sequence);
      state.events.push(event);
      const row = node("div", "event-row");
      row.append(node("span", "event-time", formatTime(event.elapsed_seconds)));
      const text = node("div");
      text.append(node("strong", "", event.kind.replaceAll("_", " ")), node("p", "", event.message));
      row.append(text);
      timeline.prepend(row);
      const data = event.data || {};
      if (Array.isArray(data.grid)) { state.grid = data.grid; changed = true; }
      if (data.assignments && typeof data.assignments === "object") { state.assignments = data.assignments; changed = true; }
      if (data.candidates && typeof data.candidates === "object") { Object.assign(state.candidates, data.candidates); changed = true; }
      if (Number.isFinite(data.model_calls)) $("metric-calls").textContent = formatNumber(data.model_calls);
      else if (event.kind === "generating" && Number.isFinite(data.call)) $("metric-calls").textContent = formatNumber(data.call);
      if (Number.isFinite(data.search_nodes ?? data.nodes)) $("metric-nodes").textContent = formatNumber(data.search_nodes ?? data.nodes);
      if (data.usage) updateUsage(data.usage);
      if (event.kind.includes("search")) updateProgress("Checking crossing letters");
      else if (event.kind.includes("repair") || event.kind.includes("retry")) updateProgress("Revisiting unresolved clues");
      else if (event.kind.includes("candidate") || event.kind.includes("model") || event.kind === "generating") updateProgress("Interpreting clues and proposing answers");
    }
    while (timeline.childElementCount > 100) timeline.lastElementChild.remove();
    if (changed) renderWorkspace();
  }

  function updateUsage(usage) {
    if (usage.model_calls !== undefined) $("metric-calls").textContent = formatNumber(usage.model_calls);
    if (usage.total_tokens !== undefined) $("metric-tokens").textContent = formatNumber(usage.total_tokens);
  }

  function finishRun(result, jobStatus, error) {
    state.running = false;
    clearInterval(state.timer);
    clearTimeout(state.pollTimer);
    state.timer = null;
    $("cancel-button").disabled = false;
    $("cancel-button").textContent = "Stop solve";
    $("live-label").className = "live-label";
    $("live-label").replaceChildren(node("span", "status-dot"), document.createTextNode(" Finished"));
    if (result) {
      state.result = result;
      state.grid = result.grid;
      state.assignments = result.assignments || {};
      state.candidates = result.candidates || {};
      appendEvents(result.events || []);
      $("metric-time").textContent = formatTime(result.elapsed_seconds);
      $("metric-nodes").textContent = formatNumber(result.search_nodes);
      updateUsage(result.usage || {});
      renderWorkspace();
      const complete = result.status === "complete_consistent";
      const providerError = result.status === "provider_error";
      setStatus(complete ? "Complete · consistent" : providerError ? "Provider error" : result.status === "cancelled" ? "Stopped · partial" : "Partial result", complete ? "complete" : providerError ? "error" : "partial");
      updateProgress(complete ? "Every crossing is consistent" : `${(result.unresolved_entries || []).length} entries unresolved`);
      const reasons = { complete_consistent: "All entries fit the crossing constraints.", call_budget: "The model call limit was reached.", time_budget: "The time limit was reached.", search_budget: "The search limit was reached.", round_budget: "The maximum number of rounds was reached.", cancelled: "You stopped this solve.", provider_error: "The model provider could not complete this run.", no_progress: "No further progress was found." };
      const reason = reasons[result.stop_reason] || (result.stop_reason ? `${result.stop_reason.replaceAll("_", " ")}.` : "Run finished.");
      $("result-notice").textContent = `${reason}${complete ? " Correctness has not been checked against a reference answer." : " The best available consistent partial result is shown."}${result.constraint_violations?.length ? ` Constraint issues: ${result.constraint_violations.join("; ")}` : ""}`;
      $("result-notice").hidden = false;
    } else {
      setStatus(jobStatus === "cancelled" ? "Stopped" : "Run failed", jobStatus === "cancelled" ? "partial" : "error");
      updateProgress(jobStatus === "cancelled" ? "Solve stopped" : "Solve could not finish");
    }
    if (error) message(error);
    updateControls();
  }

  async function pollJob() {
    if (!state.running || !state.jobId) return;
    const jobId = state.jobId;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (state.jobId !== jobId || !state.running) return;
      if (state.pollFailures) message("");
      state.pollFailures = 0;
      appendEvents(job.events || []);
      if (["completed", "failed", "cancelled"].includes(job.status)) { finishRun(job.result, job.status, job.error); return; }
      state.pollTimer = setTimeout(pollJob, 850);
    } catch (error) {
      if (state.jobId !== jobId || !state.running) return;
      if (error.status === 404) { finishRun(null, "failed", error.message); return; }
      state.pollFailures += 1;
      if (state.pollFailures >= 3) message(`Connection interrupted. The server may still be solving; retrying automatically. ${error.message}`);
      state.pollTimer = setTimeout(pollJob, Math.min(5000, 1000 * state.pollFailures));
    }
  }

  function readOptions() {
    const fields = { max_seconds: "option-seconds", max_rounds: "option-rounds", candidates_per_clue: "option-candidates", max_calls: "option-calls" };
    const options = {};
    for (const [name, id] of Object.entries(fields)) {
      const input = $(id);
      if (!input.checkValidity() || input.value === "") { input.reportValidity(); throw new Error("Choose solver limits within the allowed ranges."); }
      options[name] = Number(input.value);
    }
    return options;
  }

  async function startSolve() {
    if (state.running || !state.puzzle) return;
    let options;
    try { options = readOptions(); } catch (error) { message(error.message); return; }
    resetRun();
    message("");
    state.running = true;
    state.startedAt = performance.now();
    setStatus("Solving", "running");
    updateProgress("Starting the agent");
    updateControls();
    $("live-label").className = "live-label running";
    $("live-label").replaceChildren(node("span", "status-dot"), document.createTextNode(" Live"));
    $("metric-calls").textContent = "0";
    $("metric-tokens").textContent = "—";
    $("metric-nodes").textContent = "0";
    state.timer = setInterval(() => { $("metric-time").textContent = formatTime((performance.now() - state.startedAt) / 1000); }, 200);
    try {
      const response = await post("/api/solve", { puzzle: state.puzzle, options });
      state.jobId = response.job_id;
      updateControls();
      pollJob();
    } catch (error) { finishRun(null, "failed", error.message); }
  }

  async function cancelSolve() {
    if (!state.running || !state.jobId) return;
    $("cancel-button").disabled = true;
    $("cancel-button").textContent = "Stopping…";
    try {
      await post(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`, {});
      updateProgress("Stopping after the current operation");
    } catch (error) { message(error.message); $("cancel-button").disabled = false; $("cancel-button").textContent = "Stop solve"; }
  }

  function beginImport(title) {
    state.importVersion += 1;
    state.preview = null;
    $("import-title").textContent = title;
    $("puzzle-editor").value = "";
    $("puzzle-editor").disabled = false;
    $("accept-import").disabled = true;
    $("validate-import").disabled = false;
    $("import-validation").hidden = true;
    $("import-warnings").hidden = true;
    $("import-busy").hidden = true;
    $("import-image-wrap").hidden = true;
    if (state.imageUrl) { URL.revokeObjectURL(state.imageUrl); state.imageUrl = null; }
    if (!$("import-dialog").open) $("import-dialog").showModal();
    return state.importVersion;
  }

  function closeImport() {
    state.importVersion += 1;
    state.extraction?.abort();
    state.extraction = null;
    $("import-dialog").close();
    if (state.imageUrl) { URL.revokeObjectURL(state.imageUrl); state.imageUrl = null; }
  }

  function showImportValidation(text, error = false) {
    $("import-validation").textContent = text;
    $("import-validation").className = `import-validation${error ? " error" : ""}`;
    $("import-validation").hidden = false;
  }

  async function importJSON(file) {
    if (!file) return;
    if (file.size > 1024 * 1024) { message("JSON input must be smaller than 1 MB."); return; }
    const version = beginImport("Review your JSON puzzle");
    try {
      const text = await file.text();
      if (version !== state.importVersion) return;
      try { $("puzzle-editor").value = JSON.stringify(JSON.parse(text), null, 2); }
      catch { $("puzzle-editor").value = text; showImportValidation("This file is not valid JSON yet. Correct it below, then validate.", true); }
    } catch (error) { showImportValidation(error.message, true); }
  }

  async function importImage(file) {
    if (!file || state.running || state.loading) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) { message("Choose a PNG, JPEG, or WebP image."); return; }
    const maximum = state.config?.limits?.max_image_bytes || 10 * 1024 * 1024;
    if (file.size > maximum) { message(`Image must be smaller than ${Math.round(maximum / 1024 / 1024)} MB.`); return; }
    const version = beginImport("Review your screenshot");
    state.imageUrl = URL.createObjectURL(file);
    $("import-image").src = state.imageUrl;
    $("import-image-wrap").hidden = false;
    $("import-busy").hidden = false;
    $("puzzle-editor").disabled = true;
    $("validate-import").disabled = true;
    state.extraction = new AbortController();
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await api("/api/extract", { method: "POST", body: form, signal: state.extraction.signal });
      if (version !== state.importVersion) return;
      $("puzzle-editor").value = JSON.stringify(result.puzzle, null, 2);
      const warnings = ["Compare the extracted grid and clues with your image. Correct any transcription errors before validating.", ...(result.warnings || [])];
      $("import-warnings").textContent = warnings.join("\n");
      $("import-warnings").hidden = false;
    } catch (error) {
      if (version !== state.importVersion || error.name === "AbortError") return;
      showImportValidation(error.message, true);
    } finally {
      if (version === state.importVersion) {
        $("import-busy").hidden = true;
        $("puzzle-editor").disabled = false;
        $("validate-import").disabled = false;
        state.extraction = null;
      }
    }
  }

  async function validateImport() {
    const original = $("puzzle-editor").value;
    const version = state.importVersion;
    let puzzle;
    try { puzzle = JSON.parse(original); }
    catch (error) { showImportValidation(`JSON could not be parsed: ${error.message}`, true); return; }
    $("validate-import").disabled = true;
    $("accept-import").disabled = true;
    state.preview = null;
    try {
      const validated = await post("/api/validate", puzzle);
      if (version !== state.importVersion || original !== $("puzzle-editor").value) return;
      state.preview = validated;
      showImportValidation(`Structure validated: ${validated.puzzle.grid.length} × ${validated.puzzle.grid[0].length} grid, ${validated.entries.length} entries. Clue numbers and crossings are valid. Confirm the transcription, then select “Use this puzzle”.`);
      $("accept-import").disabled = false;
    } catch (error) { if (version === state.importVersion) showImportValidation(error.message, true); }
    finally { if (version === state.importVersion) $("validate-import").disabled = false; }
  }

  function acceptImport() {
    if (!state.preview) return;
    adoptPuzzle(state.preview, "Your imported puzzle. Structure validated; transcription reviewed by you.");
    $("sample-select").value = "";
    if (!$("sample-select").querySelector('option[value=""]')) $("sample-select").prepend(new Option("Your imported puzzle", ""));
    $("sample-select").value = "";
    closeImport();
  }

  function download(value, filename) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    const anchor = node("a");
    anchor.href = url;
    anchor.download = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function percentage(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
    return `${(Number(value) * 100).toFixed(1)}%`;
  }

  async function loadEvaluation() {
    const container = $("evaluation-summary");
    try {
      const report = await api("/api/evaluation");
      state.evaluationLoaded = true;
      container.replaceChildren();
      const panel = node("div", "panel");
      if (report.available === false || !report.summary) {
        panel.append(node("p", "eyebrow", "NO MEASURED RESULTS YET"), node("h2", "", "A score has to be earned."), node("p", "muted", "No evaluation report is available yet. Run the evaluation command described in the README to compare outputs against separate reference answers. The methodology below is ready; it is not a claim of measured performance."));
        container.append(panel);
        return;
      }
      const dataset = report.dataset || {};
      panel.append(node("p", "eyebrow", "MEASURED RESULTS"), node("h2", "", dataset.name || "Crossword evaluation"));
      const description = [dataset.puzzle_count != null ? `${dataset.puzzle_count} puzzles` : null, dataset.split ? `Split: ${dataset.split}` : null, report.model, report.generated_at ? `Run: ${report.generated_at}` : null].filter(Boolean).join(" · ");
      panel.append(node("p", "muted", description));
      const wrap = node("div", "evaluation-table-wrap");
      const table = node("table", "evaluation-table");
      const head = node("thead");
      const header = node("tr");
      for (const title of ["Method", "Letters", "Answers", "Exact puzzles", "Candidate recall", "Time / puzzle"]) header.append(node("th", "", title));
      head.append(header);
      table.append(head);
      const body = node("tbody");
      const names = { baseline_first_choice: "First answers", baseline_search: "Answers + search", agent: "Full agent" };
      for (const [method, metrics] of Object.entries(report.summary)) {
        if (!metrics || typeof metrics !== "object") continue;
        const row = node("tr");
        const elapsed = metrics.mean_elapsed_seconds ?? metrics.avg_elapsed_seconds ?? metrics.elapsed_seconds;
        const cells = [names[method] || method.replaceAll("_", " "), percentage(metrics.letter_accuracy), percentage(metrics.entry_accuracy ?? metrics.answer_accuracy), percentage(metrics.exact_puzzle_accuracy ?? metrics.puzzle_accuracy ?? metrics.exact_accuracy), percentage(metrics.candidate_recall), elapsed != null ? formatTime(elapsed) : "—"];
        for (const value of cells) row.append(node("td", "", value));
        body.append(row);
      }
      table.append(body);
      wrap.append(table);
      panel.append(wrap);
      const caveats = dataset.limitations || report.limitations;
      if (caveats) panel.append(node("p", "evaluation-caveat", Array.isArray(caveats) ? caveats.join(" ") : caveats));
      const details = node("details");
      details.append(node("summary", "", "Inspect the full evaluation report"), node("pre", "", JSON.stringify(report, null, 2)));
      const button = node("button", "button secondary", "Download evaluation report ↓");
      button.style.marginTop = "18px";
      button.addEventListener("click", () => download(report, "crosscheck-evaluation.json"));
      panel.append(details, button);
      container.append(panel);
    } catch (error) {
      container.replaceChildren();
      const panel = node("div", "panel");
      panel.append(node("h2", "", "Evaluation could not be loaded."), node("p", "muted", error.message));
      const retry = node("button", "button secondary", "Try again");
      retry.style.marginTop = "15px";
      retry.addEventListener("click", loadEvaluation);
      panel.append(retry);
      container.append(panel);
    }
  }

  async function initialize() {
    const [config, samples] = await Promise.allSettled([api("/api/config"), api("/api/samples")]);
    if (config.status === "fulfilled") {
      state.config = config.value;
      $("provider-status").textContent = state.config.provider_ready ? "Model configured" : "Model not configured";
      $("provider-indicator").className = `provider-indicator ${state.config.provider_ready ? "ready" : "error"}`;
      $("model-label").textContent = `${state.config.model || "Language model"} · local application`;
      if (!state.config.provider_ready) message("The model provider is not configured. Add NEBIUS_API_KEY to the server environment and restart the app. You can still inspect sample puzzles and the methodology.", "warning");
    } else { $("provider-status").textContent = "Server unavailable"; message(config.reason.message); }
    if (samples.status === "fulfilled") {
      state.samples = samples.value.samples || [];
      const select = $("sample-select");
      select.replaceChildren();
      if (!state.samples.length) { select.append(new Option("Upload a puzzle to begin", "")); setStatus("No puzzle loaded"); }
      else {
        for (const sample of state.samples) select.append(new Option(`${sample.title} · ${sample.rows} × ${sample.cols}`, sample.id));
        await loadSample(state.samples[0].id);
      }
    } else { $("sample-select").replaceChildren(new Option("Samples unavailable", "")); setStatus("Unable to load", "error"); message(samples.reason.message); }
    updateControls();
    if (state.config && !state.config.provider_ready) message("The model provider is not configured. Add NEBIUS_API_KEY to the server environment and restart the app. You can still inspect sample puzzles and the methodology.", "warning");
    setView(location.hash.slice(1));
  }

  document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => { location.hash = button.dataset.view; setView(button.dataset.view); }));
  window.addEventListener("hashchange", () => setView(location.hash.slice(1)));
  $("sample-select").addEventListener("change", (event) => loadSample(event.target.value));
  $("solve-button").addEventListener("click", startSolve);
  $("cancel-button").addEventListener("click", cancelSolve);
  $("reset-button").addEventListener("click", resetRun);
  $("json-import").addEventListener("click", () => $("json-file").click());
  $("image-import").addEventListener("click", () => $("image-file").click());
  $("json-file").addEventListener("change", (event) => { importJSON(event.target.files[0]); event.target.value = ""; });
  $("image-file").addEventListener("change", (event) => { importImage(event.target.files[0]); event.target.value = ""; });
  $("close-import").addEventListener("click", closeImport);
  $("import-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeImport(); });
  $("puzzle-editor").addEventListener("input", () => { state.preview = null; $("accept-import").disabled = true; $("import-validation").hidden = true; });
  $("validate-import").addEventListener("click", validateImport);
  $("accept-import").addEventListener("click", acceptImport);
  $("download-button").addEventListener("click", () => { if (state.result) download(state.result, `${state.puzzle.id}-result.json`); });
  window.addEventListener("beforeunload", (event) => { if (state.running) { event.preventDefault(); event.returnValue = ""; } });
  document.addEventListener("paste", (event) => {
    if (state.running || state.loading || $("import-dialog").open || !state.config?.provider_ready || $("view-solver").hidden) return;
    const item = [...(event.clipboardData?.items || [])].find((entry) => entry.type.startsWith("image/"));
    if (item) { event.preventDefault(); importImage(item.getAsFile()); }
  });
  initialize();
})();
