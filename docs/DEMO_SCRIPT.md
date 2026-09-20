# One-minute demonstration

A **48.5-second narrated walkthrough** is available at [artifacts/demo/crosscheck-walkthrough.mp4](../artifacts/demo/crosscheck-walkthrough.mp4). It uses actual captured application screens and explicitly labeled synthetic narration; it is not a continuous live recording or the applicant's recorded voice. Review it before submission, or use the script below to record your own live demonstration. The screen captures show genuine browser runs and measured evaluation results.

Aim for 55–58 seconds. Rehearse using the saved measured report and an actual run. If a live response is slow, show a clearly labeled recording of that run; do not present sped-up or replayed activity as live. Never show `.env`, provider credentials, or a terminal containing secrets.

| Time | Screen/action | Suggested narration |
| --- | --- | --- |
| 0–8 seconds | Open the application and select a small sample, or upload a prepared screenshot. | “This agent solves English crosswords from structured input or a picture. With pictures, I review the extracted grid and clues before solving.” |
| 8–18 seconds | Show the verified grid and clues; start Solve. | “The language model proposes several answers. Python checks their lengths, supplied letters, and intersections.” |
| 18–33 seconds | Show actual progress events and the resulting grid. | “Search combines compatible answers and undoes guesses that lead to conflicts. If the candidates cannot complete the puzzle, the agent asks targeted clues again within a fixed budget.” |
| 33–44 seconds | Open the architecture explanation or diagram. | “The model handles clue meaning. Deterministic code enforces the rules. The controller manages retries, cancellation, and time limits.” |
| 44–58 seconds | Show the saved evaluation comparison and its dataset label. | “I evaluate against separate answer keys using letter, answer, and exact-puzzle accuracy, alongside cost and time. This is a small authored smoke suite. A filled, consistent grid is not automatically a correct solution.” |

Only claim that a retry happened if that run's actual event log shows it. A puzzle solved in the first pass is a valid demonstration; describe retry behavior as a supported mechanism rather than inventing an observed correction. Use the report's real values if stating numbers. Keep the dataset limitations visible.

Before recording, check that the local app opens, the configured provider is available, the chosen sample solves, the evaluated report matches the model being demonstrated, and the final video is no longer than one minute. Repository publication and video capture remain separate delivery steps; this script is not itself a video submission.
