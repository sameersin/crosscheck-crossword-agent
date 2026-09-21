/** Render the current grid, clue selection, candidate inspector, and progress. */
import { state } from "./state.js";
import { $, node, filledCell, cellUnit } from "./shared.js";

function fillCount() {
  let filled = 0;
  let total = 0;
  for (const row of state.grid) for (const value of row) {
    if (value !== "#") { total += 1; if (filledCell(value)) filled += 1; }
  }
  return { filled, total };
}

export function updateProgress(label) {
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
        const fixed = filledCell(state.puzzle.grid[row][col]);
        const key = `${row},${col}`;
        cell.dataset.cell = key;
        const number = numbers.get(key);
        if (selectedCells.has(key)) cell.classList.add("selected");
        if (fixed) cell.classList.add("fixed");
        else if (letter !== ".") cell.classList.add("proposed");
        if (number) cell.append(node("span", "cell-number", number));
        cell.append(node("span", "cell-letter", letter === "." ? "" : letter));
        cell.setAttribute("aria-label", `Row ${row + 1}, column ${col + 1}${number ? `, clue ${number}` : ""}: ${letter === "." ? "empty" : letter}${fixed ? `, given ${cellUnit()}` : ""}`);
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
      button.setAttribute("aria-label", `${entry.number} ${direction}: ${entry.clue}, ${entry.length} ${cellUnit()}s${state.assignments[entry.id] ? `, proposed answer ${state.assignments[entry.id]}` : ""}`);
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
    inspector.append(node("p", "muted", "Select a clue to inspect its cell pattern and candidate answers."));
    selected.append(node("span", "selected-clue-label", "A CROSSWORD IS A CONVERSATION"), node("p", "", "Select a clue to see its crossing cells."));
    return;
  }
  const label = `${entry.number} ${entry.direction.toUpperCase()}`;
  selected.append(node("span", "selected-clue-label", label));
  const clue = node("p", "", entry.clue);
  clue.append(node("span", "", `(${entry.length})`));
  selected.append(clue);
  inspector.append(node("span", "selected-clue-label", `${label} · ${entry.length} ${cellUnit().toUpperCase()}S`));
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
    inspector.append(list, node("p", "candidate-note", "Candidate scores rank suggestions; they are not calibrated correctness probabilities."));
  } else inspector.append(node("p", "muted", state.running ? "Candidates will be available with the final result." : "Solve the puzzle to see its candidate answers."));
}

export function renderWorkspace() { renderGrid(); renderClues(); renderInspector(); updateProgress(); }
