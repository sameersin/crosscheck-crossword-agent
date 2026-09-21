/** Puzzle selection, saved results, and the bounded solve-job lifecycle. */
import { state, grading } from "./state.js";
import { $, node, api, post, message, formatNumber, formatTime, numericPuzzle, cellUnit, download } from "./shared.js";
import { renderWorkspace, updateProgress } from "./puzzle-view.js";

export function setStatus(label, kind = "") {
  $("solve-status").textContent = label;
  $("solve-status").className = `state-pill ${kind}`;
}

export function updateControls() {
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
  $("evaluate-run-button").disabled = locked || !state.result || !state.resultRunId;
  document.querySelectorAll(".options-grid input").forEach((input) => { input.disabled = locked; });
}

function resetRun() {
  if (state.running || !state.puzzle) return;
  state.grid = [...state.puzzle.grid];
  state.assignments = {};
  state.candidates = {};
  state.result = null;
  state.resultRunId = null;
  state.events = [];
  state.jobId = null;
  state.lastEvent = 0;
  state.pollFailures = 0;
  state.savedSource = null;
  $("reference-verification").hidden = true;
  $("reference-verification").replaceChildren();
  if (state.sourceDescription) $("sample-description").textContent = state.sourceDescription;
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

export function adoptPuzzle(validated, source) {
  state.puzzle = validated.puzzle;
  state.entries = validated.entries;
  state.selected = state.entries[0]?.id || null;
  $("puzzle-title").textContent = state.puzzle.title || "Untitled crossword";
  $("puzzle-meta").textContent = `${state.puzzle.grid.length} × ${state.puzzle.grid[0].length} GRID / ${state.entries.length} CLUES / ${numericPuzzle() ? "DIGITS" : "LETTERS"}${state.puzzle.author ? ` / ${state.puzzle.author}` : ""}`;
  $("given-cell-label").textContent = `Given ${cellUnit()}`;
  state.sourceDescription = source || "Imported puzzle.";
  $("sample-description").textContent = state.sourceDescription;
  resetRun();
  message("");
}

export async function loadSample(id) {
  if (!id || state.running) return;
  state.loading = true;
  updateControls();
  try {
    const puzzle = await api(`/api/samples/${encodeURIComponent(id)}`);
    const validated = await post("/api/validate", puzzle);
    adoptPuzzle(validated, state.samples.find((sample) => sample.id === id)?.description || "An authored sample puzzle. Its reference answer is not supplied to the solver.");
    state.loadedSelection = `sample:${id}`;
    $("sample-select").value = state.loadedSelection;
  } catch (error) { $("sample-select").value = state.loadedSelection; message(error.message); }
  finally { state.loading = false; updateControls(); }
}

export async function loadUserPuzzle(id) {
  if (!id || state.running) return;
  state.loading = true;
  updateControls();
  try {
    const saved = await api(`/api/user-puzzles/${encodeURIComponent(id)}`);
    const validated = await post("/api/validate", saved.puzzle);
    const sourceName = saved.source_name || "your image";
    adoptPuzzle(validated, `Your image puzzle · ${sourceName}`);
    state.loadedSelection = `user:${id}`;
    $("sample-select").value = state.loadedSelection;
    if (saved.result) {
      finishRun(saved.result, "completed");
      state.resultRunId = saved.run_id || null;
      state.savedSource = sourceName;
      const complete = saved.result.status === "complete_consistent";
      const failed = saved.result.status === "provider_error";
      setStatus(complete ? "Saved run · complete" : failed ? "Saved run · error" : "Saved run · partial", complete ? "complete" : failed ? "error" : "partial");
      $("live-label").replaceChildren(node("span", "status-dot"), document.createTextNode(" Saved run"));
      $("sample-description").textContent = `${state.sourceDescription}. Showing a saved result; no new model call was made.`;
      $("result-notice").textContent = `Saved run from ${sourceName}. The statistics and events shown were recorded during that run. Select “Solve puzzle” to start a fresh attempt. ${$("result-notice").textContent}`;
      if (renderReferenceVerification(saved.verification, saved.result)) $("result-notice").textContent = `Saved run from ${sourceName}. The statistics and events shown were recorded during that run. Its separate reference check appears beneath the grid. Select “Solve puzzle” to start a fresh attempt; the saved verification will not be applied to the new run.`;
      $("result-notice").hidden = false;
    }
  } catch (error) { $("sample-select").value = state.loadedSelection; message(error.message); }
  finally { state.loading = false; updateControls(); }
}

function renderReferenceVerification(verification, result) {
  const panel = $("reference-verification");
  if (!verification?.metrics_against_reference) return false;
  const metrics = verification.metrics_against_reference;
  const records = verification.entries;
  if (!Array.isArray(records) || !records.length || records.some((entry) => entry.actual !== result.assignments?.[entry.entry_id])) return false;
  const counts = [metrics.correct_entries, metrics.total_entries, metrics.correct_cells, metrics.total_cells];
  if (!counts.every((value) => Number.isInteger(value) && value >= 0)) return false;
  panel.replaceChildren();
  panel.className = `reference-verification${metrics.exact_puzzle ? "" : " has-mismatch"}`;
  panel.append(node("strong", "", `Reference check: ${metrics.correct_entries}/${metrics.total_entries} answers · ${metrics.correct_cells}/${metrics.total_cells} cells`));
  const names = { manual_reference_with_official_publisher_confirmation: "Manual reference with publisher confirmation", independent_arithmetic_reference: "Independently calculated arithmetic reference", independent_manual_visual_transcription: "Independent visual transcription", independent_manual_reference: "Independent manual reference", manual_reference: "Manual reference" };
  const kind = verification.reference?.kind || "recorded reference";
  panel.append(node("p", "", `${names[kind] || kind.replaceAll("_", " ")}. This check applies only to the saved run shown.`));
  const failures = records.filter((entry) => entry.matches === false);
  if (failures.length) panel.append(node("p", "verification-mismatch", `Answers that differ: ${failures.map((entry) => `${entry.entry_id}: ${entry.actual || "blank"} (reference: ${entry.expected})`).join("; ")}.`));
  const details = node("details");
  details.append(node("summary", "", "How this result was checked"));
  for (const text of [verification.reference?.basis, verification.semantic_note, verification.review_evidence?.causal_limit, verification.scope]) if (typeof text === "string" && text) details.append(node("p", "", text));
  if (verification.reference?.publisher_key_url) {
    try {
      const url = new URL(verification.reference.publisher_key_url);
      if (["https:", "http:"].includes(url.protocol)) {
        const link = node("a", "", `Open publisher answer key${verification.reference.publisher_key_page ? ` · page ${verification.reference.publisher_key_page}` : ""}`);
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        details.append(link);
      }
    } catch { /* A malformed reference URL is not made into a link. */ }
  }
  panel.append(details);
  panel.hidden = false;
  return true;
}

function loadSelection(value) {
  if (value.startsWith("user:")) return loadUserPuzzle(value.slice(5));
  if (value.startsWith("sample:")) return loadSample(value.slice(7));
  return Promise.resolve();
}

export function populatePuzzleOptions() {
  const select = $("sample-select");
  select.replaceChildren();
  if (state.userPuzzles.length) {
    const group = node("optgroup");
    group.label = "Your image puzzles";
    for (const puzzle of state.userPuzzles) {
      const format = puzzle.answer_type === "digits" ? " · numbers" : "";
      const saved = puzzle.has_result ? " · saved run" : "";
      group.append(new Option(`${puzzle.title} · ${puzzle.rows} × ${puzzle.cols}${format}${saved}`, `user:${puzzle.id}`));
    }
    select.append(group);
  }
  if (state.samples.length) {
    const group = node("optgroup");
    group.label = "Authored sample puzzles";
    for (const sample of state.samples) group.append(new Option(`${sample.title} · ${sample.rows} × ${sample.cols}`, `sample:${sample.id}`));
    select.append(group);
  }
  if (!state.userPuzzles.length && !state.samples.length) select.append(new Option("Upload a puzzle to begin", ""));
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
    if (event.kind.includes("search")) updateProgress("Checking shared crossing cells");
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
    if (["completed", "failed", "cancelled"].includes(job.status)) {
      state.resultRunId = job.run_id || null;
      grading.loaded = false;
      finishRun(job.result, job.status, job.error);
      if (job.history_error) message(`The solve finished, but its history could not be saved. Download the result to keep a copy. ${job.history_error}`, "warning");
      return;
    }
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

export function bindWorkspaceControls() {
  $("sample-select").addEventListener("change", (event) => loadSelection(event.target.value));
  $("solve-button").addEventListener("click", startSolve);
  $("cancel-button").addEventListener("click", cancelSolve);
  $("reset-button").addEventListener("click", resetRun);

  $("download-button").addEventListener("click", () => { if (state.result) download(state.result, `${state.puzzle.id}-result.json`); });

  window.addEventListener("beforeunload", (event) => { if (state.running) { event.preventDefault(); event.returnValue = ""; } });
}
