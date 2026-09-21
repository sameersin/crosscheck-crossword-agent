/** Safe DOM, HTTP, formatting, and local-download helpers. */
import { state } from "./state.js";

export const $ = (id) => document.getElementById(id);

export function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

export function errorMessage(detail) {
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

export async function api(path, options = {}) {
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

export const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const formatNumber = (value) => value != null && Number.isFinite(Number(value)) ? Number(value).toLocaleString() : "—";
export const formatTime = (seconds) => seconds < 60 ? `${Number(seconds).toFixed(1)}s` : `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
export const numericPuzzle = (puzzle = state.puzzle) => puzzle?.answer_type === "digits";
export const cellUnit = (puzzle = state.puzzle) => numericPuzzle(puzzle) ? "digit" : "letter";
export const filledCell = (value, puzzle = state.puzzle) => (numericPuzzle(puzzle) ? /^[0-9]$/ : /^[A-Z]$/).test(value);

export function message(text, kind = "error") {
  $("global-message").textContent = text;
  $("global-message").className = `notice ${kind}`;
  $("global-message").hidden = !text;
}

export function download(value, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = node("a");
  anchor.href = url;
  anchor.download = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function percentage(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}
