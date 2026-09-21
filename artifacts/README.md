# Development evidence

These files are saved development outputs, not live service state or proof that
the latest revision has passed every check.

| Directory | Contents |
|---|---|
| `evaluation/` | Historical authored test-split reports and robustness checks |
| `evaluation-dev/` | Historical development-split reports |
| `user-puzzles/` | Saved Pets, Cocoa and Math case studies, draft references and results used by the dashboard |
| `screenshots/` | Captured application screens; layouts may predate the latest UI |
| `demo/` | Earlier narrated screenshot walkthrough, with a scene manifest |
| `verification/` | Dated development verification records; read their scope and limitations |
| `live/` | Saved development solve output |

`private/` stores the local SQLite history and temporary working files. It is
created automatically when needed and is never published. `submission/` contains
locally generated ZIP files and is also excluded from Git.

The source-organization refactor was reviewed statically. Automated tests and
live model evaluations were not rerun for it, at the project owner's request.
GitHub checks are manual: use **Actions → Manual offline checks → Run workflow**
if you choose to run them. See [development instructions](../docs/DEVELOPMENT.md).

Model names, timestamps, dataset size and reference provenance belong alongside
reported scores. Existing GLM-5.3-Flash measurements are not a benchmark of
GLM-5.3. The three supplied internet puzzles are development cases rather than
an independently held-out dataset; their draft keys still require review.
