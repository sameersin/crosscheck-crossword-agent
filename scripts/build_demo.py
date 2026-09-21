"""Build a sub-minute narrated walkthrough from actual captured browser states.

Requires Windows System.Speech and FFmpeg. This is explicitly a captured-screen
walkthrough with synthetic narration, not a continuous live screen recording.
"""

import json
import shutil
import subprocess
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENES = [
    (
        "01-workspace.png",
        "01  INPUT",
        "Crosscheck solves English crosswords from a sample, a JSON file, or a picture.",
    ),
    (
        "02-image-review.png",
        "02  REVIEW THE TRANSCRIPTION",
        "For pictures, it extracts the grid and clues. The user reviews and corrects the transcription before solving.",
    ),
    (
        "03-solved-grid.png",
        "03  PROPOSE AND CHECK",
        "Nebius G L M proposes answers. Python checks their lengths and crossing letters, then searches for a compatible grid.",
    ),
    (
        "03-run-evidence.png",
        "04  OBSERVE AND REPAIR",
        "The controller revisits blocked clues when needed. Calls, time, and search work are bounded, with partial results on failure.",
    ),
    (
        "04-evaluation.png",
        "05  MEASURE AGAINST ANSWER KEYS",
        "An earlier development evaluation matched separate answer keys on six small puzzles, but the simple baseline tied. Broader accuracy remains unproven.",
    ),
    (
        "05-architecture.png",
        "06  SEPARATE RESPONSIBILITIES",
        "The code separates the model, search, controller, interface, and evaluation. Reference comparisons measure correct letters, whole answers, and fully correct puzzles.",
    ),
]


def main():
    private = ROOT / "artifacts/private/demo"
    output = ROOT / "artifacts/demo"
    private.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    manifest = [
        {
            "image": image,
            "title": title,
            "narration": narration,
            "audio": str(private / f"scene-{index}.wav"),
        }
        for index, (image, title, narration) in enumerate(SCENES)
    ]
    manifest_path = private / "scenes.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    speech = private / "speech.ps1"
    speech.write_text(
        """param([string]$Manifest)
Add-Type -AssemblyName System.Speech
$taskScenes = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$taskVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$taskVoice.SelectVoice('Microsoft David Desktop')
$taskVoice.Rate = 1
foreach ($taskScene in $taskScenes) {
    $taskVoice.SetOutputToWaveFile($taskScene.audio)
    $taskVoice.Speak($taskScene.narration)
}
$taskVoice.Dispose()
""",
        encoding="utf-8",
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-File", str(speech), "-Manifest", str(manifest_path)],
        check=True,
    )
    shutil.copyfile("C:/Windows/Fonts/arial.ttf", private / "font.ttf")
    lengths = []
    for index, scene in enumerate(manifest):
        with wave.open(scene["audio"]) as audio:
            duration = audio.getnframes() / audio.getframerate() + 0.4
        lengths.append(duration)
        caption = private / f"title-{index}.txt"
        caption.write_text(scene["title"], encoding="utf-8")
        label = private / "label.txt"
        label.write_text(
            "Captured app screens  |  Synthetic narration  |  Local assessment walkthrough",
            encoding="utf-8",
        )
        font = (private / "font.ttf").relative_to(ROOT).as_posix()
        title = caption.relative_to(ROOT).as_posix()
        label_path = label.relative_to(ROOT).as_posix()
        filters = (
            f"scale=1760:890:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:82:color=0xf6f4ee,setsar=1,"
            f"drawtext=fontfile={font}:textfile={title}:fontcolor=0x163f40:fontsize=30:x=80:y=28,"
            f"drawtext=fontfile={font}:textfile={label_path}:fontcolor=0x657570:fontsize=23:x=80:y=1020"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-i",
                str(ROOT / "artifacts/screenshots" / scene["image"]),
                "-i",
                scene["audio"],
                "-vf",
                filters,
                "-af",
                "apad",
                "-t",
                str(duration),
                "-r",
                "24",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(private / f"scene-{index}.mp4"),
            ],
            check=True,
            cwd=ROOT,
        )
    if sum(lengths) > 60:
        raise RuntimeError("Narration exceeded the assignment's one-minute limit.")
    concat = private / "concat.txt"
    concat.write_text(
        "\n".join(f"file 'scene-{i}.mp4'" for i in range(len(SCENES))), encoding="utf-8"
    )
    final = output / "crosscheck-walkthrough.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(final),
        ],
        check=True,
    )
    (output / "walkthrough.json").write_text(
        json.dumps(
            {
                "type": "captured-screen walkthrough",
                "synthetic_narration": True,
                "duration_seconds": sum(lengths),
                "scenes": [
                    {
                        "image": item[0],
                        "title": item[1],
                        "narration": item[2],
                        "duration_seconds": duration,
                    }
                    for item, duration in zip(SCENES, lengths, strict=True)
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Created {final}; duration {sum(lengths):.1f}s (under 60s).")


if __name__ == "__main__":
    main()
