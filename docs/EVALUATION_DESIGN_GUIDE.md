# Crossword agent: requirements and evaluation design guide

This guide separates broad LLM evaluation options, requirements for this application, and a practical comparison with human solving. It is a design reference, not a claim that every proposed metric has been implemented or benchmarked.

A requirement says what a system must do or achieve. A metric measures performance against it. Example: preserve supplied letters is a functional rule; the percentage preserved is a metric; 100% preservation is its acceptance criterion. Accuracy can measure functional correctness as well as a quality goal. Metrics are not automatically all non-functional requirements.

## 1. A broad catalog of LLM evaluation metrics

There is no exhaustive, task-independent metric list. Select the families appropriate to the application; record their definitions and denominators before measuring.

| Family | Common metrics or scores | Meaning and applicability |
|---|---|---|
| Correctness | Exact match, accuracy, precision, recall, F1 | Correct outputs; precision measures how many proposed items are right, recall how many required items were recovered. |
| Text similarity | BLEU, ROUGE, chrF, BERTScore, semantic similarity | Overlap or similarity to reference text; useful for some translation/summarization tasks. Similar-looking words are not necessarily correct crossword answers. |
| Text extraction | Character error rate, word error rate, field precision/recall, exact transcription rate | Differences between extracted text and a trusted transcription. |
| Factuality and grounding | Supported-claim rate, factual precision, citation correctness, faithfulness | Whether claims are true or supported by supplied evidence; faithfulness to evidence does not prove that the evidence itself is true. |
| Instruction compliance | Required-condition pass rate, schema validity, format adherence | Whether the output follows specified requirements and can be consumed correctly. |
| Retrieval | Precision/recall at k, mean reciprocal rank, nDCG | Quality and ranking of retrieved evidence; applies when retrieval exists. |
| Reasoning, code and mathematics | Test-case pass rate, executable task success, exact or symbolic answer correctness | Whether the result actually works or is mathematically correct. |
| Agent behavior | End-to-end task success, tool-call correctness, recovery rate, intervention rate | Whether the system completes its goal using appropriate actions. |
| Reliability | Repeated-run success, output agreement, failure/timeout rates, robustness under input changes | Whether performance holds across attempts and changed conditions. Agreement alone can mean consistently wrong answers. |
| Uncertainty | Brier score, expected calibration error, accuracy versus coverage | Whether stated probabilities track correctness and whether abstaining improves reliability. Requires a defined confidence measure. |
| Safety and fairness | Unsafe-output rate, inappropriate refusal rate, leakage/injection success rate, group performance gaps | Application-specific harmful behavior and disparities. |
| Performance | End-to-end latency, median and 95th-percentile latency, throughput, time to first usable result | Speed and responsiveness. Time to first token mainly matters for streamed applications. |
| Resource use | Input/output tokens, calls/retries, monetary cost, memory/CPU, cost per successful task | Resources required to obtain useful results. Fewer tokens do not necessarily mean better quality. |
| Human experience | Task completion, acceptance/override rates, review time, satisfaction, pairwise preference | How people experience and correct the system. Acceptance is not proof of correctness. |
| Language modeling | Cross-entropy, perplexity | Predictive fit to text; not a direct measure of application correctness. |

Metric definitions such as exact match, F1, text similarity and character error rate are documented in the [Hugging Face metric catalog](https://huggingface.co/metrics). [HELM](https://crfm.stanford.edu/2022/11/17/helm.html) demonstrates multi-dimensional evaluation beyond accuracy. Retrieval and grounding require their own task-specific definitions; see the [Ragas metric catalog](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/).

Evaluation methods are different from metrics: code/reference graders, human review, LLM judges, paired comparisons, ablations, adversarial tests, and repeated trials are ways to produce or compare scores. Rubric scores from a model need validation against human judgments. See [agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## 2. Functional requirements: what Crosscheck must do

| Capability | Expected behavior / functional check |
|---|---|
| Input selection | Load samples and supported puzzle JSON. |
| Image upload | Accept supported PNG, JPEG and WebP files with grid and clue list. |
| Image transcription | Recover cell layout, blocks/absent space, supplied values, clue numbers, directions and text. |
| Review and correction | Show the source image and editable transcription; validate and require explicit acceptance. |
| Structural parsing | Derive entry starts, lengths, numbering and intersections. Reject unsupported or inconsistent inputs clearly. |
| Word candidate generation | Generate bounded alternatives for each requested clue; reject malformed or impossible fits. |
| Numeric clues | Support digit cells and calculate supported arithmetic exactly. Preserve zeroes and supplied digits. |
| Constraint solving | Enforce length, character, supplied-cell and crossing rules. |
| Repair and review | Revisit unresolved entries and perform bounded independent proposals for weakly crossed singleton entries. |
| Execution control | Start and cancel a solve; respect configured stopping limits. |
| Partial results | Return usable consistent progress when a full solve is unavailable. |
| User feedback | Show actual progress, proposed answers, unresolved entries, warnings and stop reason. |
| Export and inspection | Download result JSON and inspect recorded run history. |
| Evaluation | Compare outputs to separate references and report per-puzzle and aggregate measurements. |
| Invalid input and provider errors | Reject unsuitable inputs and surface actionable, sanitized errors. |

These capabilities exist in the current local app within its documented format boundaries. This does not establish accuracy for arbitrary images or puzzles. Rebus cells, arbitrary numbering, cryptic-specific parsing, languages beyond the supported alphabet, and public multi-user hosting are outside the demonstrated scope. Future capabilities could include additional formats, durable run history, accounts and batch import; they are not submission requirements unless chosen explicitly.

## 3. Non-functional requirements: how well it should operate

| Quality requirement | Measurements / checks | Current evidence or gap |
|---|---|---|
| Correctness | Cell, whole-answer, exact-puzzle accuracy; zero hard violations | Implemented reference scorer; small saved datasets only. |
| Transcription quality | Exact grid/clue mapping, clue-text accuracy, supplied-character preservation | Three assistant-referenced image cases; broader image benchmark needed. |
| Speed | Extraction time, solver time, end-to-end wall time, median/p95, first usable result | Stage runtimes recorded; broad latency distributions not benchmarked. |
| Cost efficiency | Tokens, calls, retries, priced cost per attempt and per verified success | Calls/tokens recorded; dollars unknown without explicit prices. |
| Bounded work | Time, call, round, candidate and search budgets; cancellation delay | Bounds and cooperative cancellation implemented/tested; an active request may take time to return. There is a per-response output-token cap, but no total-token/dollar ceiling or hard process kill. |
| Reliability | Successful request rate, timeout/error rate, recovery rate, no-crash rate | Error handling tested; no long-running availability claim. |
| Robustness | Quality changes under blur, skew, cropping, image compression, bad JSON and provider failures | Some structural/failure regression tests; broad real-image stress study proposed. |
| Repeatability | Success across repeated runs, score variance, worst cases, regression rate | Saved traces available; systematic repeated live evaluation proposed. |
| Privacy/security | Secret exposure, upload boundaries, local access controls, instruction-in-image handling | Relevant safeguards exist; no comprehensive security audit or production certification. |
| Usability | Time to import/review/solve, correction effort, confusing-error rate, accessibility checks | Browser walkthrough verified; no independent user study. |
| Observability | Trace completeness, attributable calls/tokens, understandable failure reasons | Events and results recorded; failed-call billed tokens may be unavailable. |
| Maintainability | Meaningful regression tests, module boundaries, reproducible setup | Separated modules, dependency locks and recorded 180-test run. Passing tests do not establish general model accuracy. |
| Scalability | Concurrency, throughput, latency under load, memory | Two local solving slots and one extraction slot; no production load benchmark. |
| Durability | Survival across restart, recovery of active work, retention rules | Runtime jobs are in memory. Selected saved artifacts persist; durable production jobs are not implemented. |
| Calibration | Whether confidence agrees with observed correctness | Candidate scores are ranking hints, not calibrated probabilities. |

## 4. Crossword-specific scorecard

### Core outcomes

| Metric | Definition |
|---|---|
| Cell accuracy | Correct letters/digits divided by all open cells; blanks are wrong and blocks are excluded. |
| Initially-empty-cell accuracy | Correct initially blank cells divided by all initially blank cells; supplied characters do not inflate it. |
| Answer accuracy | Entirely correct across/down entries divided by all entries. |
| Exact-puzzle accuracy | Fully correct, structurally valid puzzles divided by all attempted puzzles. One puzzle is a yes/no result. |
| Completion | Filled open cells divided by all open cells, regardless of correctness. |
| Constraint violations | Count of detected length, character, crossing, supplied-cell or output-consistency errors. |
| Complete-consistent rate | Filled, rule-compliant puzzles divided by all puzzles. It can exceed exact-puzzle accuracy. |

### Image extraction, before human edits

A reference for extraction contains what is printed, not solved crossword answers. Check dimensions and exact block/open-cell mask; entry numbering, direction and location; supplied characters; missing/extra clues; and clue text. The current harness records exact grid/mapping matches and normalized clue-text comparisons. It is not a semantic judge.

Proposed extensions: per-cell open/block precision/recall, clue transcription exact-match rate, character/word error rate, full-image transcription success, number of human corrections, review time, and fraction usable without edits. If dimensions differ, count exact-grid failure rather than aligning cells opportunistically. Missing clues count as failures. Character error rate counts substitutions, deletions and insertions divided by reference characters and can exceed 100%.

A human can approve reference transcriptions once; subsequent comparisons are automatic. Generated images with known source JSON provide additional reproducible test pairs. Assistant-created references remain fallible and must not be described as independently human-approved. A second vision model can flag discrepancies but cannot establish ground truth by agreement alone.

### Diagnosing why a solve failed

Candidate recall asks whether each correct answer appeared anywhere in the candidate pool. Top-choice accuracy tests ranking. Search gain compares initial first-choice accuracy with constraint-search accuracy. Repair gain compares initial-search accuracy with the final agent. Also record regressions where revisiting changes a correct answer to a wrong one. Candidate recall is implemented; aggregate gain/regression and intervention reports are further analysis, not established live improvements.

Record extraction failures, wrong/missing candidates, ranking mistakes, budget exhaustion, provider failures, and ambiguous references separately. Keep unsuccessful attempts in the denominator.

### Efficiency and stability

Report total extraction-plus-solving time as well as separate stages. Human review time is separate unless the experiment explicitly measures assisted end-to-end use. Record prompt/completion/total tokens, model calls, retries, and search nodes. Compare quality at matched budgets. If prices are known, cost per verified success is total cost across all attempts, including failures, divided by verified successes; it is undefined when none succeed. Never describe missing billed usage as zero.

Repeat runs with recorded model, settings and prompt version; report variability instead of selecting the best attempt. Best-of-k success means at least one success among k attempts, while all-k success measures reliability across every attempt; disclose attempts and total resources. Do not repeat the identical puzzle with the same human to estimate an unpracticed baseline, because they learn its answers.

## 5. Parallels with human solving

A verified real-world example is the **American Crossword Puzzle Tournament, 2026 in-person rules**: 10 points per correct entry, 25 per full minute early, a reduction of 25 in the time bonus per wrong or missing letter (bonus floored at zero), and 150 for a completely correct puzzle. This shows accuracy, speed and perfection as distinct considerations. The virtual event uses a different timing formula, so there is no universal tournament score. [Official in-person scoring](https://www.crosswordtournament.com/info/brochure.htm); [official virtual scoring](https://www.crosswordtournament.com/info/brochurev.htm).

We do not need to copy these point weights. Reporting separate correctness and speed measurements makes our trade-offs easier to inspect. The inspected ACPT brochure does not establish an aid policy for our experiment; we must declare our own allowed resources.

The following mapping proposes comparable measurements. Official competition practice and its source are recorded in the companion source note below; assistance, revision behavior and calibration are additional experimental measures, not universal tournament scoring rules.

| Human-solving question | Agent equivalent |
|---|---|
| How many letters were correct? | Cell accuracy. |
| How many whole answers were correct? | Answer accuracy. |
| Was the entire puzzle correct? | Exact-puzzle success. |
| How much was left blank? | Completion and unresolved entries. |
| How long did it take? | End-to-end time under a stated deadline. |
| Did crossing words agree? | Constraint violation count. |
| Did they use hints, a dictionary, a calculator or another person? | External tools, assistance and human-intervention rate. The model's pretrained knowledge is not measured as lookup use. |
| Could they fix an initially wrong guess? | Improvement and regression after targeted repair. |
| Did using crossings improve their answers? | Search-versus-first-choice comparison. |
| Could they read a poor printout correctly? | Extraction quality under blur, skew and layout changes. |
| Did they know when they were unsure? | Abstention/coverage and calibrated confidence, if measured. |
| Does skill hold on harder puzzles? | Results separated by size, clue difficulty, theme and image condition. |
| How much supervision was needed? | Correction count, review minutes and acceptance without edits. |
| How stable is performance? | Multiple comparable puzzles/human participants and repeated independent model attempts. |

Tokens have no direct human equivalent. Human time and model compute/cost can be reported side by side, but should not be converted into supposed units of thought or intelligence. Internal search-node counts likewise are not human mental steps.

## 6. A fair human-versus-agent experiment

1. Freeze a diverse test set and verified references before final tuning. Use multiple sources and fresh puzzles where possible; neither source diversity nor freshness proves absence from training data.
2. Define tracks: verified-JSON solving, raw-image end-to-end solving, and human-assisted solving. Do not merge their scores.
3. Give both sides equivalent visible information, a stated deadline and declared assistance rules. For arithmetic, a calculator available to humans is the closer match to the agent's exact arithmetic tool; otherwise report the resource difference explicitly.
4. Use multiple human participants and disclose experience. Randomize order and prevent answer sharing. Keep humans and the model away from the reference keys while solving.
5. Run each model condition repeatedly; preserve all trials, settings, inputs and traces. Score human finals and model finals with the same reference/rule evaluator.
6. Report correctness first, then completion, violations, time, assistance and resources. Show time among successful solves and the overall success/timeout rate so fast failures do not look efficient.
7. Have two reviewers independently check a subset of extraction labels and disputed answers; reconcile disagreements. Keep canonical key matching and any separately adjudicated alternative-answer score distinct.
8. Compare first-choice, search and full agent using shared initial candidates where the comparison is intended to isolate solver stages. Account for additional repair calls. Re-run equivalent difficulty strata and describe uncertainty; do not claim representativeness from a handful of cases.

## 7. Recommendation for this assessment

Primary grader: deterministic reference comparison plus independent rule checks. Human evaluation: approve transcription/reference quality and adjudicate ambiguous cases. Optional LLM judge: flag likely mistakes for review, after checking judge agreement with human labels. It should not replace a reliable answer key or be treated as proof by self-consistency. The agent's independent proposal pass is part of solving, not a separate evaluator.

Main results: cell accuracy, initially-empty-cell accuracy, answer accuracy, exact-puzzle accuracy, completion, constraint violations, stage/runtime totals, calls and tokens. Show extraction results separately. Use candidate recall to explain failures. Prioritize a challenging untouched test set and repeatable comparisons before adding a large menu of weakly justified scores.

Current evidence is limited: the earlier six-puzzle authored benchmark predates the latest image/numeric changes and all three approaches tied. The three supplied images are development case studies with assistant-created references. The later cocoa run already proposed its correct brand answer initially; its success does not establish a benefit from the review step. There is no independent human study or separate LLM judge in the current project.

## Existing implementation references

- [Scoring methodology](EVALUATION.md)
- [Earlier authored-puzzle results](RESULTS.md)
- [Three supplied image cases](../artifacts/user-puzzles/RESULTS.md)

This guide was prepared from inspected code, saved reports and the linked primary sources. No new paid model evaluation, human study, security audit or load test was run while preparing it.
