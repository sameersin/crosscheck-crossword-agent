/** Recorded-run selection, a separate editable key, approval, and measured results. */
import { state, grading } from "./state.js";
import { $, node, api, post, errorMessage, formatNumber, formatTime, numericPuzzle, cellUnit, filledCell, download, percentage } from "./shared.js";

const keySources = {
  human_reviewed_agent_copy: "Human-reviewed copy of agent answers", human_entered: "Human-entered answer key",
  uploaded_json: "Uploaded JSON · human review required", uploaded_image: "Extracted image · human review required",
  publisher_key: "Publisher answer key · supplied by you",
};
const approvedEvaluation = (run) => run?.latest_evaluation?.approved === true ? run.latest_evaluation : null;
const displayDate = (value) => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Date unavailable";
const entryAnswer = (grid, entry) => entry.cells.map(([row, col]) => grid[row]?.[col] || ".").join("");
const keyEntry = () => grading.entries.find((entry) => entry.id === grading.selectedEntry);

function evaluationMessage(text, kind = "error") {
  $("evaluation-message").textContent = text;
  $("evaluation-message").className = `notice ${kind}`;
  $("evaluation-message").hidden = !text;
}

function attemptLabels() {
  const count = new Map();
  const labels = new Map();
  for (const run of [...grading.runs].reverse()) {
    if (run.source === "saved_import") {
      labels.set(run.run_id, `${run.title || run.puzzle_id} · ${/\.first-run\./i.test(run.source_label || "") ? "saved first run" : "saved run"}`);
      continue;
    }
    const next = (count.get(run.puzzle_id) || 0) + 1;
    count.set(run.puzzle_id, next);
    labels.set(run.run_id, `${run.title || run.puzzle_id} · attempt ${next}`);
  }
  return labels;
}

// Recorded run selection.
export async function loadRunHistory(preferredId) {
  if (grading.loading) { if (preferredId) grading.preferredRunId = preferredId; return; }
  grading.loading = true;
  $("refresh-runs").disabled = true;
  try {
    const response = await api("/api/runs?limit=500");
    const runs = response.runs || [];
    while (runs.length < (response.total_count || 0)) {
      const page = await api(`/api/runs?limit=500&offset=${runs.length}`);
      if (!page.runs?.length) break;
      runs.push(...page.runs);
    }
    grading.runs = runs;
    grading.loaded = true;
    const labels = attemptLabels();
    const select = $("evaluation-run-select");
    select.replaceChildren();
    for (const run of grading.runs) {
      const grade = approvedEvaluation(run);
      const suffix = grade ? `${grade.metrics.correct_entries}/${grade.metrics.total_entries} answers` : "Not graded";
      select.append(new Option(`${labels.get(run.run_id)} · ${displayDate(run.created_at)} · ${suffix}`, run.run_id));
    }
    if (!grading.runs.length) select.append(new Option("No recorded runs yet", ""));
    const id = grading.preferredRunId || preferredId || grading.run?.run_id || grading.runs[0]?.run_id;
    grading.preferredRunId = null;
    select.value = id || "";
    renderRunChart();
    if (id && id !== grading.run?.run_id) await selectEvaluationRun(id);
    else if (!id) showEmptyRun("A score starts with a saved solve.", "Complete a puzzle in Workspace, then choose its recorded attempt here. An answer key is required to measure accuracy.");
  } catch (error) {
    evaluationMessage(`Recorded runs could not be loaded. ${error.message}`);
    if (!grading.run) showEmptyRun("Run history is unavailable.", "Use Refresh runs to retry. Your Workspace puzzle is unaffected.");
  } finally { grading.loading = false; $("refresh-runs").disabled = grading.busy; }
}

function showEmptyRun(title, description) {
  $("evaluation-empty").replaceChildren(node("h2", "", title), node("p", "", description));
  $("evaluation-empty").hidden = false;
  $("key-editor-panel").hidden = true;
  $("key-upload-panel").hidden = true;
  $("run-score-panel").hidden = true;
}

async function selectEvaluationRun(id) {
  if (!id || grading.busy) return;
  const version = ++grading.requestVersion;
  grading.selecting = true;
  evaluationMessage("");
  showEmptyRun("Loading the recorded solve…", "The original output and its answer-key history are kept separately.");
  try {
    const run = await api(`/api/runs/${encodeURIComponent(id)}`);
    const validated = run.original_result ? await post("/api/validate", run.puzzle) : null;
    if (version !== grading.requestVersion) return;
    grading.run = run;
    grading.entries = validated?.entries || [];
    grading.selectedEntry = grading.entries[0]?.id || null;
    grading.dirty = false;
    $("evaluation-run-select").value = id;
    const timeKind = run.source === "saved_import" ? "Imported" : "Recorded";
    $("evaluation-run-meta").textContent = `${run.puzzle.title || run.puzzle.id} · ${timeKind} ${displayDate(run.created_at)} · ${run.original_result?.model || "No model result"} · Run ${run.run_id.slice(0, 12)}. Original output is preserved.`;
    renderRunChart();
    if (!run.original_result) {
      showEmptyRun("This attempt has no result to grade.", `${run.status || "Failed"}${run.error ? `: ${run.error}` : ". No original grid was recorded."} The attempt stays visible in the run history.`);
      return;
    }
    const recorded = approvedEvaluation(run);
    grading.draft = [...(recorded?.reference_grid || run.original_result.grid)];
    grading.source = recorded?.source || "human_reviewed_agent_copy";
    $("approve-answer-key").checked = false;
    $("key-entry-select").replaceChildren(...grading.entries.map((entry) => new Option(`${entry.number} ${entry.direction} · ${entry.length} ${cellUnit(run.puzzle)}s`, entry.id)));
    $("evaluation-empty").hidden = true;
    $("key-editor-panel").hidden = false;
    $("key-upload-panel").hidden = false;
    $("key-entry-answer").inputMode = numericPuzzle(run.puzzle) ? "numeric" : "text";
    $("key-entry-feedback").textContent = "";
    renderKeyGrid(); renderKeyEntry(); renderRunScore(); updateKeyStatus();
  } catch (error) {
    if (version !== grading.requestVersion) return;
    evaluationMessage(error.message);
    showEmptyRun("This run could not be opened.", "Select another attempt or refresh the run history.");
  } finally { if (version === grading.requestVersion) grading.selecting = false; }
}

// Reference-key validation and editable grid.
function checkReferenceGrid(rows, complete = false) {
  const puzzle = grading.run?.puzzle;
  if (!puzzle) throw new Error("Select a recorded run first.");
  if (!Array.isArray(rows) || rows.length !== puzzle.grid.length || rows.some((row) => typeof row !== "string" || row.length !== puzzle.grid[0].length)) throw new Error(`The key must contain ${puzzle.grid.length} rows of exactly ${puzzle.grid[0].length} cells.`);
  let filled = 0; let total = 0;
  for (let row = 0; row < rows.length; row += 1) for (let col = 0; col < rows[row].length; col += 1) {
    const given = puzzle.grid[row][col]; const value = rows[row][col];
    const where = `Row ${row + 1}, column ${col + 1}`;
    if ((given === "#") !== (value === "#")) throw new Error(`${where}: blocked cells must match the selected puzzle.`);
    if (given === "#") continue;
    total += 1;
    if (filledCell(given, puzzle) && given !== value) throw new Error(`${where}: the given ${cellUnit(puzzle)} ${given} is locked.`);
    if (filledCell(value, puzzle)) filled += 1;
    else if (value !== ".") throw new Error(`${where}: enter ${numericPuzzle(puzzle) ? "a digit 0–9" : "an uppercase letter A–Z"}, or a dot for a blank.`);
  }
  if (complete && filled !== total) throw new Error(`The answer key is incomplete: fill the remaining ${total - filled} cells before evaluating.`);
  return { filled, total };
}

function parseReferenceJSON(text) {
  let data;
  try { data = JSON.parse(text); } catch (error) { throw new Error(`The answer key is not valid JSON: ${error.message}`); }
  if (data && !Array.isArray(data)) {
    if (data.puzzle_id != null && data.puzzle_id !== grading.run.puzzle.id) throw new Error("This answer key belongs to a different puzzle ID. Select the matching original run.");
    if (data.puzzle_fingerprint != null && data.puzzle_fingerprint !== grading.run.puzzle_fingerprint) throw new Error("This answer key does not match the selected puzzle’s fingerprint. Its grid or clues belong to a different puzzle.");
  }
  const rows = Array.isArray(data) ? data : data?.reference_grid || data?.grid;
  checkReferenceGrid(rows);
  return [...rows];
}

function updateKeyStatus() {
  if (!grading.run?.original_result) return;
  let counts; let invalid = "";
  try { counts = checkReferenceGrid(grading.draft); } catch (error) { invalid = error.message; }
  let changes = 0;
  for (let row = 0; row < grading.draft.length; row += 1) for (let col = 0; col < grading.draft[row].length; col += 1) {
    if (grading.draft[row][col] !== "#" && grading.draft[row][col] !== grading.run.original_result.grid[row][col]) changes += 1;
  }
  $("key-change-count").textContent = `${changes} ${changes === 1 ? "cell" : "cells"} corrected`;
  const sourceLabel = keySources[grading.source] || grading.source;
  const savedKey = !grading.dirty && approvedEvaluation(grading.run);
  $("key-source-label").textContent = grading.source === "human_reviewed_agent_copy" && !savedKey ? "Copy of agent answers · awaiting your review" : savedKey ? sourceLabel.replace(" · human review required", " · reviewed") : sourceLabel;
  $("key-draft-status").textContent = grading.dirty ? "Draft · edits not scored" : approvedEvaluation(grading.run) ? `Saved key · v${grading.run.latest_evaluation.reference_version}` : "Draft key · not graded";
  const full = counts && counts.filled === counts.total;
  $("key-completeness").textContent = invalid || `${counts.filled}/${counts.total} cells filled${full ? " · ready for your review" : ` · ${counts.total - counts.filled} still need answers`}`;
  $("key-completeness").className = `key-completeness${full ? "" : " incomplete"}`;
  $("evaluate-key-button").disabled = grading.busy || !full || !$("approve-answer-key").checked;
  $("evaluate-key-button").textContent = grading.busy ? "Saving evaluation…" : "Approve key & evaluate →";
  const ids = ["evaluation-run-select", "refresh-runs", "key-reset-copy", "key-clear", "apply-entry-key", "undo-entry-key", "key-entry-select", "key-entry-answer", "approve-answer-key", "browse-answer-key", "paste-answer-key", "review-pasted-key", "publisher-key-source"];
  for (const id of ids) $(id).disabled = grading.busy;
  $("answer-key-grid").querySelectorAll("input").forEach((input) => { input.disabled = grading.busy; });
}

function changedKey() {
  grading.dirty = true;
  $("approve-answer-key").checked = false;
  updateKeyStatus();
  renderRunScore();
}

function renderKeyGrid() {
  if (!grading.run?.original_result) return;
  const grid = $("answer-key-grid"); const original = $("original-answer-grid");
  const focused = grid.contains(document.activeElement) ? document.activeElement.dataset.keyCell : null;
  grid.replaceChildren(); original.replaceChildren();
  const width = grading.run.puzzle.grid[0].length;
  for (const target of [grid, original]) target.style.gridTemplateColumns = `repeat(${width}, minmax(0, 1fr))`;
  grid.style.setProperty("--key-font", `${Math.min(27, Math.max(10, 360 / width))}px`);
  const selected = new Set((keyEntry()?.cells || []).map(([row, col]) => `${row},${col}`));
  const numbers = new Map(grading.entries.map((entry) => [`${entry.row},${entry.col}`, entry.number]));
  for (let row = 0; row < grading.draft.length; row += 1) for (let col = 0; col < width; col += 1) {
    const value = grading.draft[row][col]; const given = grading.run.puzzle.grid[row][col];
    const originalValue = grading.run.original_result.grid[row][col]; const key = `${row},${col}`;
    const block = given === "#"; const fixed = filledCell(given, grading.run.puzzle);
    const corrected = value !== originalValue;
    const cell = node("div", `key-grid-cell${block ? " block" : ""}${fixed ? " given" : ""}${selected.has(key) ? " selected" : ""}${corrected ? " corrected" : ""}`);
    if (!block) {
      const input = node("input"); input.type = "text"; input.value = value === "." ? "" : value;
      input.maxLength = 1; input.readOnly = fixed; input.dataset.keyCell = key;
      input.inputMode = numericPuzzle(grading.run.puzzle) ? "numeric" : "text";
      input.autocomplete = "off"; input.spellcheck = false;
      input.setAttribute("aria-label", `Answer key row ${row + 1}, column ${col + 1}${numbers.has(key) ? `, clue ${numbers.get(key)}` : ""}${fixed ? `, given ${given}, locked` : ""}${corrected ? ", corrected" : ""}`);
      input.addEventListener("focus", () => {
        const entries = grading.entries.filter((entry) => entry.cells.some(([r, c]) => r === row && c === col));
        if (!entries.some((entry) => entry.id === grading.selectedEntry) && entries.length) {
          grading.selectedEntry = entries[0].id; highlightKeyEntry(); renderKeyEntry();
        }
        input.select();
      });
      input.addEventListener("input", () => {
        if (grading.busy || fixed) return;
        const next = input.value.toUpperCase();
        if (next && !filledCell(next, grading.run.puzzle)) { input.value = value === "." ? "" : value; return; }
        setDraftCell(row, col, next || "."); changedKey(); renderKeyGrid(); renderKeyEntry();
      });
      input.addEventListener("keydown", (event) => moveKeyFocus(event, row, col));
      input.addEventListener("paste", (event) => pasteEntryAtCell(event, row, col));
      cell.append(input);
      if (numbers.has(key)) cell.append(node("span", "cell-number", numbers.get(key)));
    } else cell.setAttribute("aria-hidden", "true");
    grid.append(cell);
    original.append(node("div", `original-cell${block ? " block" : ""}`, block || originalValue === "." ? "" : originalValue));
  }
  if (focused) grid.querySelector(`[data-key-cell="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
}

function highlightKeyEntry() {
  const cells = new Set((keyEntry()?.cells || []).map(([row, col]) => `${row},${col}`));
  $("answer-key-grid").querySelectorAll("input").forEach((input) => input.parentElement.classList.toggle("selected", cells.has(input.dataset.keyCell)));
}

function renderKeyEntry() {
  const entry = keyEntry(); if (!entry) return;
  $("key-entry-select").value = entry.id;
  $("key-entry-clue").textContent = entry.clue;
  $("key-agent-answer").textContent = entryAnswer(grading.run.original_result.grid, entry).replaceAll(".", "_");
  $("key-entry-answer").value = entryAnswer(grading.draft, entry).replaceAll(".", "_");
  $("key-entry-answer").maxLength = entry.length;
  $("key-entry-answer").setAttribute("aria-label", `Answer key for ${entry.number} ${entry.direction}, ${entry.length} ${cellUnit(grading.run.puzzle)}s`);
}

function setDraftCell(row, col, value) {
  const given = grading.run.puzzle.grid[row][col];
  if (given === "#" || filledCell(given, grading.run.puzzle)) return;
  grading.draft[row] = `${grading.draft[row].slice(0, col)}${value}${grading.draft[row].slice(col + 1)}`;
}

function moveKeyFocus(event, row, col) {
  const movement = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[event.key];
  if (!movement) return;
  event.preventDefault();
  let r = row + movement[0]; let c = col + movement[1];
  while (r >= 0 && r < grading.draft.length && c >= 0 && c < grading.draft[0].length) {
    const next = $("answer-key-grid").querySelector(`[data-key-cell="${r},${c}"]`);
    if (next) { next.focus(); return; }
    r += movement[0]; c += movement[1];
  }
}

function applyEntryAnswer(answer, cells = keyEntry()?.cells) {
  if (!cells || grading.busy) return false;
  const normalized = answer.toUpperCase().replaceAll("_", ".");
  if (normalized.length !== cells.length) throw new Error(`Enter exactly ${cells.length} ${cellUnit(grading.run.puzzle)}s; use _ for a blank.`);
  for (let i = 0; i < cells.length; i += 1) {
    const [row, col] = cells[i]; const given = grading.run.puzzle.grid[row][col]; const value = normalized[i];
    if (value !== "." && !filledCell(value, grading.run.puzzle)) throw new Error(`Use ${numericPuzzle(grading.run.puzzle) ? "digits 0–9" : "letters A–Z"} only, or _ for a blank.`);
    if (filledCell(given, grading.run.puzzle) && value !== given) throw new Error(`The given ${cellUnit(grading.run.puzzle)} ${given} at position ${i + 1} is locked.`);
  }
  cells.forEach(([row, col], i) => setDraftCell(row, col, normalized[i]));
  changedKey(); renderKeyGrid(); renderKeyEntry();
  $("key-entry-feedback").textContent = "Answer key updated. Crossing cells update together.";
  return true;
}

function pasteEntryAtCell(event, row, col) {
  if (grading.busy) return;
  const text = event.clipboardData?.getData("text/plain").trim() || "";
  if (text.length <= 1) return;
  event.preventDefault(); event.stopPropagation();
  const entry = keyEntry(); const offset = entry?.cells.findIndex(([r, c]) => r === row && c === col);
  const cells = offset >= 0 ? entry.cells.slice(offset, offset + text.length) : null;
  try { applyEntryAnswer(text, cells); } catch (error) { $("key-entry-feedback").textContent = error.message; }
}

function resetAnswerKey(blank = false) {
  if (!grading.run?.original_result || grading.busy) return;
  grading.draft = [...(blank ? grading.run.puzzle.grid : grading.run.original_result.grid)];
  grading.source = blank ? "human_entered" : "human_reviewed_agent_copy";
  $("key-entry-feedback").textContent = "";
  changedKey(); renderKeyGrid(); renderKeyEntry();
}

// Recorded scores and per-run comparisons.
function renderRunScore() {
  const evaluation = approvedEvaluation(grading.run);
  $("run-score-panel").hidden = !evaluation;
  if (!evaluation) return;
  const metrics = evaluation.metrics; const result = grading.run.original_result;
  $("run-score-title").textContent = `${grading.run.puzzle.title || grading.run.puzzle.id} · recorded score`;
  $("run-score-context").textContent = `${result.model || "Model unrecorded"} · Run ${grading.run.run_id.slice(0, 12)} · approved reference v${evaluation.reference_version} · ${keySources[evaluation.source]?.replace(" · human review required", "") || evaluation.source} · evaluated ${displayDate(evaluation.created_at)}.${grading.dirty ? " Current key edits have not been scored; these metrics use the saved reference." : ""}`;
  const cards = $("run-score-cards"); cards.replaceChildren();
  const values = [
    ["Cell accuracy", percentage(metrics.cell_accuracy ?? metrics.letter_accuracy, 2), `${metrics.correct_cells}/${metrics.total_cells} cells correct`],
    ["Answer accuracy", percentage(metrics.answer_accuracy, 2), `${metrics.correct_entries}/${metrics.total_entries} whole answers correct`],
    ["Completion", percentage(metrics.completion), `${metrics.filled_cells}/${metrics.total_cells} cells filled`],
    ["Exact puzzle", metrics.exact_puzzle ? "Yes" : "No", "Every cell correct, no violations"],
    ["Constraint violations", formatNumber(metrics.constraint_violation_count), "Lengths, crossings and given cells"],
  ];
  for (const [label, value, detail] of values) {
    const card = node("div", "score-card"); card.append(node("span", "", label), node("strong", "", value), node("small", "", detail)); cards.append(card);
  }
  const usage = result.usage || {}; const usageRow = node("div", "score-run-usage");
  usageRow.append(node("span", "", `Original solve: ${formatTime(result.elapsed_seconds)}`), node("span", "", `${formatNumber(usage.model_calls)} model calls`), node("span", "", `${formatNumber(usage.total_tokens)} tokens`), node("span", "", "Answer-key extraction usage is separate."));
  cards.append(usageRow);
  const differences = grading.entries.map((entry) => ({ entry, actual: result.assignments?.[entry.id] || entryAnswer(result.grid, entry), expected: entryAnswer(evaluation.reference_grid, entry) })).filter((entry) => entry.actual !== entry.expected);
  const detail = $("run-score-differences"); detail.replaceChildren(); detail.hidden = !differences.length;
  if (differences.length) {
    detail.append(node("h3", "", `${differences.length} ${differences.length === 1 ? "answer differs" : "answers differ"} from this key`), node("p", "", "These comparisons use the preserved original run and the approved reference above."));
    const table = node("table", "evaluation-table"); const heading = node("tr");
    for (const label of ["Clue", "Agent answer", "Answer key"]) heading.append(node("th", "", label));
    const head = node("thead"); head.append(heading); table.append(head); const body = node("tbody");
    for (const item of differences) {
      const row = node("tr"); row.append(node("td", "", `${item.entry.number} ${item.entry.direction}: ${item.entry.clue}`), node("td", "answer-value", item.actual.replaceAll(".", "_")), node("td", "answer-value", item.expected)); body.append(row);
    }
    table.append(body); const wrap = node("div", "evaluation-table-wrap"); wrap.append(table); detail.append(wrap);
  }
}

async function evaluateAnswerKey() {
  if (!grading.run?.original_result || grading.busy || !$("approve-answer-key").checked) return;
  try { checkReferenceGrid(grading.draft, true); } catch (error) { evaluationMessage(error.message); return; }
  grading.busy = true; updateKeyStatus(); evaluationMessage("");
  try {
    const evaluation = await post(`/api/runs/${encodeURIComponent(grading.run.run_id)}/evaluate`, { reference_grid: [...grading.draft], source: grading.source, approved: true, puzzle_id: grading.run.puzzle.id, puzzle_fingerprint: grading.run.puzzle_fingerprint });
    grading.run.latest_evaluation = evaluation;
    grading.run.evaluations = [...(grading.run.evaluations || []).filter((entry) => entry.evaluation_id !== evaluation.evaluation_id), evaluation];
    grading.dirty = false; $("approve-answer-key").checked = false;
    renderRunScore();
    await loadRunHistory();
    evaluationMessage(`Evaluation saved against approved reference v${evaluation.reference_version}. The original solver output is unchanged.`, "success");
    $("run-score-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { evaluationMessage(error.message); }
  finally { grading.busy = false; updateKeyStatus(); }
}

function renderRunChart() {
  const labels = attemptLabels(); const evaluated = grading.runs.filter((run) => approvedEvaluation(run));
  const rows = $("run-chart-filter").value === "evaluated" ? evaluated : grading.runs;
  const chart = $("run-accuracy-chart"); chart.replaceChildren();
  if (!rows.length) chart.append(node("p", "muted", grading.runs.length ? "No attempts have an approved answer key yet." : "Recorded attempts will appear here."));
  else {
    const axis = node("div", "chart-axis"); for (const tick of [0, 25, 50, 75, 100]) axis.append(node("span", "", `${tick}%`)); chart.append(axis);
    for (const run of rows) {
      const evaluation = approvedEvaluation(run); const metrics = evaluation?.metrics;
      const row = node("button", `accuracy-row${grading.run?.run_id === run.run_id ? " selected" : ""}`);
      const label = node("span", "accuracy-run-label", labels.get(run.run_id));
      label.append(node("small", "", `${run.source === "saved_import" ? "Imported " : ""}${displayDate(run.created_at)} · ${run.model || "Model unrecorded"}`));
      const track = node("span", `accuracy-track${evaluation ? "" : " ungraded"}`); track.setAttribute("aria-hidden", "true");
      if (metrics) { const bar = node("span", "accuracy-bar"); bar.style.width = `${Math.max(0, Math.min(100, Number(metrics.answer_accuracy) * 100))}%`; track.append(bar); }
      const value = node("span", `accuracy-value${evaluation ? "" : " ungraded"}`, metrics ? percentage(metrics.answer_accuracy) : "Not graded");
      value.append(node("small", "", metrics ? `${metrics.correct_entries}/${metrics.total_entries} answers` : run.gradeable === false ? "No solver result" : "Key not approved"));
      row.append(label, track, value); row.setAttribute("aria-label", `${labels.get(run.run_id)}. ${metrics ? `${metrics.correct_entries} of ${metrics.total_entries} answers correct, ${percentage(metrics.answer_accuracy)}` : "Not graded"}. Select this run.`);
      row.addEventListener("click", () => selectEvaluationRun(run.run_id)); chart.append(row);
    }
  }
  const perfect = evaluated.filter((run) => approvedEvaluation(run).metrics.exact_puzzle).length;
  const failed = grading.runs.filter((run) => run.gradeable === false).length;
  $("run-chart-summary").textContent = `${perfect}/${evaluated.length} graded attempts are exact puzzles · ${grading.runs.length - evaluated.length} attempts not graded · ${new Set(evaluated.map((run) => run.puzzle_id)).size} distinct puzzles graded.${failed ? ` ${failed} attempts have no result to grade.` : ""}`;
  const table = node("table", "evaluation-table"); const head = node("thead"); const header = node("tr");
  for (const title of ["Attempt", "Recorded model", "Status", "Key / grade", "Time", "Calls", "Tokens"]) header.append(node("th", "", title)); head.append(header); table.append(head);
  const body = node("tbody");
  for (const run of rows) {
    const row = node("tr"); const name = node("td"); const link = node("button", "run-table-select", labels.get(run.run_id)); link.addEventListener("click", () => selectEvaluationRun(run.run_id)); name.append(link); row.append(name);
    const evaluation = approvedEvaluation(run);
    for (const value of [run.model || "—", run.status || "—", evaluation ? `v${evaluation.reference_version} · ${evaluation.source.replaceAll("_", " ")}` : "Not graded", run.elapsed_seconds != null ? formatTime(run.elapsed_seconds) : "—", formatNumber(run.usage?.model_calls), formatNumber(run.usage?.total_tokens)]) row.append(node("td", "", value));
    body.append(row);
  }
  table.append(body); $("run-history-table").replaceChildren(table);
}

// Answer-key file and clipboard review.
function closeReferenceImport() {
  grading.importVersion += 1; grading.importAbort?.abort(); grading.importAbort = null; grading.preview = null;
  $("reference-import-dialog").close();
  if (grading.imageUrl) { URL.revokeObjectURL(grading.imageUrl); grading.imageUrl = null; }
}

function beginReferenceImport(source, title) {
  if (!grading.run?.original_result || grading.busy) return null;
  closeReferenceImport();
  grading.importSource = $("publisher-key-source").checked ? "publisher_key" : source;
  grading.importRunId = grading.run.run_id;
  $("reference-import-title").textContent = title;
  $("reference-grid-editor").value = ""; $("reference-grid-editor").disabled = false;
  $("reference-image-wrap").hidden = true; $("reference-import-busy").hidden = true;
  $("reference-import-warnings").hidden = true; $("reference-import-validation").hidden = true;
  $("reference-image-reviewed").checked = false; $("reference-image-reviewed").disabled = false;
  $("use-reference-draft").disabled = true; $("validate-reference-draft").disabled = false;
  $("reference-import-dialog").showModal();
  return grading.importVersion;
}

function referenceValidation(text, invalid = false) {
  $("reference-import-validation").textContent = text;
  $("reference-import-validation").className = `import-validation${invalid ? " error" : ""}`;
  $("reference-import-validation").hidden = false;
}

function validateReferenceDraft() {
  grading.preview = null;
  try {
    if (grading.importRunId !== grading.run?.run_id) throw new Error("The selected run changed. Reopen this key for the intended run.");
    const rows = parseReferenceJSON($("reference-grid-editor").value);
    const counts = checkReferenceGrid(rows);
    grading.preview = rows;
    referenceValidation(`Grid structure matches this puzzle: ${counts.filled}/${counts.total} cells filled. ${counts.filled === counts.total ? "Compare every answer with your source, then use this draft." : "You can use this draft, but complete every empty cell in the editor before grading."}`);
  } catch (error) { referenceValidation(error.message, true); }
  $("use-reference-draft").disabled = !grading.preview || !$("reference-image-reviewed").checked;
}

async function importReferenceFile(file) {
  if (!file || !grading.run?.original_result || grading.busy) return;
  const json = file.type === "application/json" || /\.json$/i.test(file.name);
  if (json) {
    if (file.size > 1024 * 1024) { evaluationMessage("Answer-key JSON must be smaller than 1 MB."); return; }
    const version = beginReferenceImport("uploaded_json", "Review your JSON answer key");
    try { const text = await file.text(); if (version !== grading.importVersion) return; $("reference-grid-editor").value = text; validateReferenceDraft(); }
    catch (error) { if (version === grading.importVersion) referenceValidation(error.message, true); }
    return;
  }
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) { evaluationMessage("Choose a PNG, JPEG, WebP, or JSON answer key."); return; }
  if (file.size > (state.config?.limits?.max_image_bytes || 10 * 1024 * 1024)) { evaluationMessage("The answer-key image exceeds the server’s image-size limit."); return; }
  const version = beginReferenceImport("uploaded_image", "Review extracted answer-key cells");
  grading.imageUrl = URL.createObjectURL(file); $("reference-image").src = grading.imageUrl;
  $("reference-image-link").href = grading.imageUrl;
  $("reference-image-wrap").hidden = false; $("reference-import-busy").hidden = false;
  $("reference-grid-editor").disabled = true; $("validate-reference-draft").disabled = true; $("reference-image-reviewed").disabled = true;
  grading.importAbort = new AbortController(); const form = new FormData(); form.append("file", file);
  try {
    const response = await api(`/api/runs/${encodeURIComponent(grading.importRunId)}/reference-image`, { method: "POST", body: form, signal: grading.importAbort.signal });
    if (version !== grading.importVersion) return;
    const extractionRecord = { ...response, model: response.model || state.config?.vision_model, usage_scope: "reference_image_extraction", approved: false };
    grading.run.reference_extractions = [...(grading.run.reference_extractions || []), extractionRecord];
    try {
      const refreshed = await api(`/api/runs/${encodeURIComponent(grading.importRunId)}`);
      if (version !== grading.importVersion) return;
      grading.run.reference_extractions = refreshed.reference_extractions || grading.run.reference_extractions;
    } catch { /* The returned extraction usage remains available if history refresh fails. */ }
    $("reference-grid-editor").value = JSON.stringify({ puzzle_id: response.puzzle_id || grading.run.puzzle.id, puzzle_fingerprint: response.puzzle_fingerprint || grading.run.puzzle_fingerprint, reference_grid: response.reference_grid }, null, 2);
    const warnings = ["Image reading can make mistakes. Check the draft against the visible source before accepting it.", ...(response.warnings || [])];
    if (response.validation_errors?.length) warnings.push(errorMessage(response.validation_errors));
    if (response.usage) warnings.push(`This key extraction used ${formatNumber(response.usage.model_calls)} model calls and ${formatNumber(response.usage.total_tokens)} tokens, separately from the original solve.`);
    $("reference-import-warnings").textContent = warnings.join("\n"); $("reference-import-warnings").hidden = false;
    validateReferenceDraft();
  } catch (error) { if (version === grading.importVersion && error.name !== "AbortError") referenceValidation(error.message, true); }
  finally { if (version === grading.importVersion) { $("reference-import-busy").hidden = true; $("reference-grid-editor").disabled = false; $("validate-reference-draft").disabled = false; $("reference-image-reviewed").disabled = false; grading.importAbort = null; } }
}

function importReferenceText(text) {
  if (!text.trim()) { evaluationMessage("Paste answer-key JSON into the text box first."); return; }
  if (text.length > 1024 * 1024) { evaluationMessage("Answer-key JSON must be smaller than 1 MB."); return; }
  if (beginReferenceImport("uploaded_json", "Review your pasted answer key") === null) return;
  $("reference-grid-editor").value = text;
  validateReferenceDraft();
}

function acceptReferenceDraft() {
  validateReferenceDraft();
  if (!grading.preview || !$("reference-image-reviewed").checked) return;
  grading.draft = [...grading.preview]; grading.source = grading.importSource;
  changedKey(); renderKeyGrid(); renderKeyEntry(); closeReferenceImport();
  evaluationMessage("The imported key is now a draft in the editor. Check every answer and approve it before evaluation.", "success");
  $("key-editor-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function pasteReferenceClipboard() {
  if (!grading.run?.original_result || grading.busy) return;
  $("clipboard-help").hidden = true;
  try {
    if (!navigator.clipboard?.read) throw new Error("Clipboard reading is unavailable in this browser.");
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const type = item.types.find((value) => ["image/png", "image/jpeg", "image/webp"].includes(value));
      if (type) { await importReferenceFile(new File([await item.getType(type)], `clipboard-key.${type.split("/")[1]}`, { type })); return; }
    }
    for (const item of items) if (item.types.includes("text/plain")) { importReferenceText(await (await item.getType("text/plain")).text()); return; }
    throw new Error("The clipboard has no supported image or JSON text.");
  } catch (error) {
    $("clipboard-help").textContent = `${error.message} Use Ctrl+V on this page, paste JSON in the text box below, or browse files.`;
    $("clipboard-help").hidden = false; document.querySelector(".key-json-paste").open = true;
  }
}

// Historical benchmark report.
export async function loadBenchmark() {
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
    for (const title of ["Method", "Cells", "Answers", "Exact puzzles", "Candidate recall", "Time / puzzle"]) header.append(node("th", "", title));
    head.append(header);
    table.append(head);
    const body = node("tbody");
    const names = { baseline_first_choice: "First answers", baseline_search: "Answers + search", agent: "Full agent" };
    for (const [method, metrics] of Object.entries(report.summary)) {
      if (!metrics || typeof metrics !== "object") continue;
      const row = node("tr");
      const elapsed = metrics.mean_elapsed_seconds ?? metrics.avg_elapsed_seconds ?? metrics.elapsed_seconds;
      const cells = [names[method] || method.replaceAll("_", " "), percentage(metrics.cell_accuracy ?? metrics.letter_accuracy), percentage(metrics.entry_accuracy ?? metrics.answer_accuracy), percentage(metrics.exact_puzzle_accuracy ?? metrics.puzzle_accuracy ?? metrics.exact_accuracy), percentage(metrics.candidate_recall), elapsed != null ? formatTime(elapsed) : "—"];
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
    retry.addEventListener("click", loadBenchmark);
    panel.append(retry);
    container.append(panel);
  }
}

// Page controls: bind once from app.js.
export function bindEvaluationControls() {
  $("evaluation-run-select").addEventListener("change", (event) => selectEvaluationRun(event.target.value));
  $("refresh-runs").addEventListener("click", () => loadRunHistory());
  $("run-chart-filter").addEventListener("change", renderRunChart);
  $("key-entry-select").addEventListener("change", (event) => { grading.selectedEntry = event.target.value; $("key-entry-feedback").textContent = ""; highlightKeyEntry(); renderKeyEntry(); });
  $("apply-entry-key").addEventListener("click", () => { try { applyEntryAnswer($("key-entry-answer").value); } catch (error) { $("key-entry-feedback").textContent = error.message; } });
  $("key-entry-answer").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); $("apply-entry-key").click(); } });
  $("undo-entry-key").addEventListener("click", () => { const entry = keyEntry(); if (entry) { try { applyEntryAnswer(entryAnswer(grading.run.original_result.grid, entry)); } catch (error) { $("key-entry-feedback").textContent = error.message; } } });
  $("key-reset-copy").addEventListener("click", () => resetAnswerKey());
  $("key-clear").addEventListener("click", () => resetAnswerKey(true));
  $("approve-answer-key").addEventListener("change", updateKeyStatus);
  $("evaluate-key-button").addEventListener("click", evaluateAnswerKey);
  $("download-answer-key").addEventListener("click", () => { if (grading.run) download({ puzzle_id: grading.run.puzzle.id, puzzle_fingerprint: grading.run.puzzle_fingerprint, reference_grid: [...grading.draft] }, `${grading.run.puzzle.id}-answer-key.json`); });
  $("download-run-evaluation").addEventListener("click", () => { if (approvedEvaluation(grading.run)) download({ run_id: grading.run.run_id, puzzle_id: grading.run.puzzle.id, puzzle_fingerprint: grading.run.puzzle_fingerprint, model: grading.run.original_result.model, original_result: grading.run.original_result, evaluation: approvedEvaluation(grading.run), reference_extractions: grading.run.reference_extractions || [] }, `${grading.run.puzzle.id}-${grading.run.run_id.slice(0, 8)}-evaluation.json`); });
  $("browse-answer-key").addEventListener("click", () => { if (!grading.busy) $("answer-key-file").click(); });
  $("answer-key-file").addEventListener("change", (event) => { importReferenceFile(event.target.files[0]); event.target.value = ""; });
  $("paste-answer-key").addEventListener("click", pasteReferenceClipboard);
  $("review-pasted-key").addEventListener("click", () => importReferenceText($("answer-key-paste-text").value));
  $("close-reference-import").addEventListener("click", closeReferenceImport);
  $("reference-import-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeReferenceImport(); });
  $("reference-grid-editor").addEventListener("input", () => { grading.preview = null; $("reference-image-reviewed").checked = false; $("use-reference-draft").disabled = true; $("reference-import-validation").hidden = true; });
  $("reference-image-reviewed").addEventListener("change", () => { $("use-reference-draft").disabled = !grading.preview || !$("reference-image-reviewed").checked; });
  $("validate-reference-draft").addEventListener("click", validateReferenceDraft);
  $("use-reference-draft").addEventListener("click", acceptReferenceDraft);
  const dropzone = $("answer-key-dropzone");
  dropzone.addEventListener("click", () => { if (!grading.busy) $("answer-key-file").click(); });
  dropzone.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); if (!grading.busy) $("answer-key-file").click(); } });
  for (const type of ["dragenter", "dragover"]) dropzone.addEventListener(type, (event) => { event.preventDefault(); if (!grading.busy) dropzone.classList.add("drag-over"); });
  for (const type of ["dragleave", "drop"]) dropzone.addEventListener(type, (event) => { event.preventDefault(); dropzone.classList.remove("drag-over"); });
  dropzone.addEventListener("drop", (event) => { if (!grading.busy) importReferenceFile(event.dataTransfer?.files[0]); });
  document.addEventListener("paste", (event) => {
    if ($("view-evaluation").hidden || grading.busy || !grading.run?.original_result || $("reference-import-dialog").open) return;
    const imageItem = [...(event.clipboardData?.items || [])].find((item) => item.type.startsWith("image/"));
    if (imageItem) { event.preventDefault(); importReferenceFile(imageItem.getAsFile()); return; }
    if (event.target.closest("input,textarea,[contenteditable='true']")) return;
    const text = event.clipboardData?.getData("text/plain")?.trim();
    if (text && /^[\[{]/.test(text)) { event.preventDefault(); importReferenceText(text); }
  });
}
