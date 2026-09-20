"""Render an input-only puzzle image for exercising the screenshot-upload path."""

import argparse
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from crossword_agent.domain import parse_entries
from crossword_agent.models import Puzzle


def font(size: int):
    for name in ("DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def render(puzzle: Puzzle, destination: Path):
    entries = parse_entries(puzzle)
    image = Image.new("RGB", (1300, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 50), puzzle.title, fill="#162b32", font=font(40))
    draw.text(
        (70, 110),
        "Original assessment puzzle - fill one letter per square",
        fill="#465257",
        font=font(21),
    )
    side = min(90, 490 // max(len(puzzle.grid), len(puzzle.grid[0])))
    starts = {(entry.row, entry.col): entry.number for entry in entries}
    for row, line in enumerate(puzzle.grid):
        for col, value in enumerate(line):
            x, y = 70 + col * side, 200 + row * side
            draw.rectangle(
                (x, y, x + side, y + side),
                fill="#17262b" if value == "#" else "white",
                outline="black",
                width=2,
            )
            if value != "#":
                if (row, col) in starts:
                    draw.text((x + 6, y + 4), str(starts[row, col]), fill="black", font=font(16))
                if value != ".":
                    draw.text((x + side // 3, y + side // 3), value, fill="black", font=font(30))
    for direction, x in (("across", 650), ("down", 970)):
        y = 185
        draw.text((x, y), direction.upper(), fill="#162b32", font=font(25))
        y += 55
        for entry in entries:
            if entry.direction != direction:
                continue
            for line in textwrap.wrap(f"{entry.number}. {entry.clue}", width=23):
                draw.text((x, y), line, fill="#162b32", font=font(21))
                y += 29
            y += 22
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("puzzle", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(Puzzle.model_validate_json(args.puzzle.read_text(encoding="utf-8")), args.output)
