/** JSON/photo import, editable transcription preview, and structural acceptance. */
import { state } from "./state.js";
import { $, api, post, errorMessage, message, cellUnit } from "./shared.js";
import { adoptPuzzle } from "./workspace.js";

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
    const warnings = ["Review the extracted grid and clues alongside your image. Structural validation runs automatically; your confirmation is still required before solving.", ...(result.warnings || [])];
    if (result.geometry_repaired) warnings.push("The extraction service repaired the grid structure before returning this preview.");
    if (Array.isArray(result.validation_errors) && result.validation_errors.length) {
      warnings.push(`Extraction checks reported:\n${errorMessage(result.validation_errors)}`);
    }
    $("import-warnings").textContent = warnings.join("\n");
    $("import-warnings").hidden = false;
    await validateImport();
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
    showImportValidation(`Structure validated: ${validated.puzzle.grid.length} × ${validated.puzzle.grid[0].length} grid, ${validated.entries.length} entries, one ${cellUnit(validated.puzzle)} per cell. Clue numbers and crossings are valid. Confirm the transcription, then select “Use this puzzle”.`);
    $("accept-import").disabled = false;
  } catch (error) { if (version === state.importVersion) showImportValidation(error.message, true); }
  finally { if (version === state.importVersion) $("validate-import").disabled = false; }
}

function acceptImport() {
  if (!state.preview) return;
  adoptPuzzle(state.preview, "Your imported puzzle. Structure validated; transcription reviewed by you.");
  state.loadedSelection = "";
  $("sample-select").value = "";
  if (!$("sample-select").querySelector('option[value=""]')) $("sample-select").prepend(new Option("Your imported puzzle", ""));
  $("sample-select").value = "";
  closeImport();
}

export function bindPuzzleImportControls() {
  $("json-import").addEventListener("click", () => $("json-file").click());
  $("image-import").addEventListener("click", () => $("image-file").click());
  $("json-file").addEventListener("change", (event) => { importJSON(event.target.files[0]); event.target.value = ""; });
  $("image-file").addEventListener("change", (event) => { importImage(event.target.files[0]); event.target.value = ""; });
  $("close-import").addEventListener("click", closeImport);
  $("import-dialog").addEventListener("cancel", (event) => { event.preventDefault(); closeImport(); });
  $("puzzle-editor").addEventListener("input", () => { state.preview = null; $("accept-import").disabled = true; $("import-validation").hidden = true; });
  $("validate-import").addEventListener("click", validateImport);
  $("accept-import").addEventListener("click", acceptImport);

  document.addEventListener("paste", (event) => {
    if (state.running || state.loading || $("import-dialog").open || !state.config?.provider_ready || $("view-solver").hidden) return;
    const item = [...(event.clipboardData?.items || [])].find((entry) => entry.type.startsWith("image/"));
    if (item) { event.preventDefault(); importImage(item.getAsFile()); }
  });
}
