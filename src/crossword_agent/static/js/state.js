/** Mutable state is separate for solving and reference-key review. */
export const state = {
  config: null, samples: [], userPuzzles: [], puzzle: null, entries: [], grid: [], assignments: {},
  candidates: {}, selected: null, result: null, events: [], jobId: null,
  running: false, loading: false, startedAt: null, timer: null, pollTimer: null,
  lastEvent: 0, pollFailures: 0, preview: null, imageUrl: null, extraction: null,
  importVersion: 0, evaluationLoaded: false, loadedSelection: "", sourceDescription: "", savedSource: null, resultRunId: null,
};
export const grading = {
  runs: [], run: null, entries: [], draft: [], source: "human_reviewed_agent_copy",
  selectedEntry: null, loaded: false, loading: false, selecting: false, busy: false,
  requestVersion: 0, dirty: false, importVersion: 0, importAbort: null,
  imageUrl: null, preview: null, importSource: null, importRunId: null,
};
