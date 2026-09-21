/** Browser entry point: load configuration, wire controllers, and switch views. */
import { state, grading } from "./js/state.js";
import { $, api, message } from "./js/shared.js";
import { loadSample, loadUserPuzzle, populatePuzzleOptions, setStatus, updateControls, bindWorkspaceControls } from "./js/workspace.js";
import { bindPuzzleImportControls } from "./js/puzzle-import.js";
import { loadRunHistory, loadBenchmark, bindEvaluationControls } from "./js/evaluation.js";

function setView(view) {
  const valid = ["solver", "evaluation", "architecture"].includes(view) ? view : "solver";
  document.querySelectorAll(".view").forEach((section) => { section.hidden = section.id !== `view-${valid}`; });
  document.querySelectorAll(".nav-button").forEach((button) => {
    const active = button.dataset.view === valid;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  if (valid === "evaluation") {
    if (!grading.loaded && !grading.loading) loadRunHistory();
    if (!state.evaluationLoaded) loadBenchmark();
  }
}

async function initialize() {
  const [config, samples, userPuzzles] = await Promise.allSettled([api("/api/config"), api("/api/samples"), api("/api/user-puzzles")]);
  if (config.status === "fulfilled") {
    state.config = config.value;
    $("provider-status").textContent = state.config.provider_ready ? "Model configured" : "Model not configured";
    $("provider-indicator").className = `provider-indicator ${state.config.provider_ready ? "ready" : "error"}`;
    $("model-label").textContent = `Agent: ${state.config.model || "Not configured"} · Image reading: ${state.config.vision_model || "Not configured"}`;
    $("agent-model-name").value = state.config.model || "Not configured";
    $("image-model-name").textContent = state.config.vision_model || "Not configured";
    if (!state.config.provider_ready) message("The model provider is not configured. Add NEBIUS_API_KEY to the server environment and restart the app. You can still inspect sample puzzles and the methodology.", "warning");
  } else { $("provider-status").textContent = "Server unavailable"; message(config.reason.message); }
  if (samples.status === "fulfilled") state.samples = samples.value.samples || [];
  if (userPuzzles.status === "fulfilled") state.userPuzzles = userPuzzles.value.puzzles || [];
  populatePuzzleOptions();
  if (state.userPuzzles.length) await loadUserPuzzle(state.userPuzzles[0].id);
  else if (state.samples.length) await loadSample(state.samples[0].id);
  else setStatus("No puzzle loaded");
  if (samples.status === "rejected") message(`Sample puzzles could not be loaded. ${samples.reason.message}`);
  if (userPuzzles.status === "rejected" && userPuzzles.reason.status !== 404) message(`Your saved image puzzles could not be loaded. ${userPuzzles.reason.message}`);
  updateControls();
  if (state.config && !state.config.provider_ready) message("The model provider is not configured. Add NEBIUS_API_KEY to the server environment and restart the app. You can still inspect sample puzzles and the methodology.", "warning");
  setView(location.hash.slice(1));
}

document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => { location.hash = button.dataset.view; setView(button.dataset.view); }));
window.addEventListener("hashchange", () => setView(location.hash.slice(1)));

$("evaluate-run-button").addEventListener("click", () => { if (state.resultRunId) { location.hash = "evaluation"; setView("evaluation"); loadRunHistory(state.resultRunId); } });

bindWorkspaceControls();
bindPuzzleImportControls();
bindEvaluationControls();
initialize();
