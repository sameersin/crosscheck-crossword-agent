"""Geometry checks use generated fixtures; local worksheet regressions are optional."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from crossword_agent.vision import detect_grid

ROOT = Path(__file__).resolve().parents[1]


def worksheet_image(grid, *, sparse=False, fixed=None, decoration=False):
    """Draw new test input; never modify or redistribute user worksheet images."""
    pitch, margin = 32, 65
    image = Image.new(
        "RGB", (len(grid[0]) * pitch + 2 * margin, len(grid) * pitch + 2 * margin), "white"
    )
    draw = ImageDraw.Draw(image)
    for row, line in enumerate(grid):
        for col, char in enumerate(line):
            if sparse and char == "#":
                continue
            x, y = margin + col * pitch, margin + row * pitch
            draw.rectangle(
                (x, y, x + pitch, y + pitch),
                fill="black" if char == "#" else "white",
                outline="black",
                width=2,
            )
            if fixed and (row, col) in fixed:
                draw.text(
                    (x + 8, y + 5),
                    fixed[row, col],
                    font=ImageFont.load_default(size=20),
                    fill="black",
                )
    if decoration:
        # Isolated non-cell artwork of a different size, outside the crossword.
        draw.rounded_rectangle((10, 12, 34, 34), radius=5, outline="black", width=2)
        draw.rectangle((image.width - 45, 10, image.width - 10, 30), outline="black", width=2)
        draw.ellipse((12, image.height - 42, 38, image.height - 12), outline="black", width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_detects_dense_clean_cell_geometry():
    expected = ["...."] * 4
    geometry = detect_grid(worksheet_image(expected))
    assert geometry is not None
    assert geometry.grid == expected
    assert geometry.detected_cells == 16
    assert geometry.pitch_x == pytest.approx(32, abs=1)
    assert geometry.pitch_y == pytest.approx(32, abs=1)


def test_solid_black_cells_are_not_open_squares():
    expected = ["....", ".#..", "..#.", "...."]
    geometry = detect_grid(worksheet_image(expected))
    assert geometry is not None
    assert geometry.grid == expected
    assert geometry.detected_cells == 14


def test_sparse_background_is_absent_even_when_white():
    expected = [
        "####.######",
        "###...#####",
        "#.##.######",
        "#.##.#.....",
        "#.##.#.####",
        ".......####",
        "#.####...##",
        "#.#########",
    ]
    geometry = detect_grid(worksheet_image(expected, sparse=True, decoration=True))
    assert geometry is not None
    assert geometry.grid == expected
    assert geometry.detected_cells == sum(row.count(".") for row in expected)


def test_fixed_letters_and_zero_do_not_remove_outlined_cells():
    expected = ["...."] * 4
    geometry = detect_grid(worksheet_image(expected, fixed={(0, 0): "A", (1, 1): "0", (2, 2): "H"}))
    assert geometry is not None
    # Geometry detects cells; reading the supplied characters belongs to OCR.
    assert geometry.grid == expected


def test_non_grid_cartoon_shapes_and_invalid_bytes_return_none():
    image = Image.new("RGB", (360, 360), "white")
    draw = ImageDraw.Draw(image)
    for x, y, size in [
        (15, 16, 22),
        (78, 93, 31),
        (139, 24, 39),
        (30, 201, 25),
        (250, 238, 29),
        (210, 74, 44),
    ]:
        draw.rounded_rectangle((x, y, x + size, y + size), radius=6, outline="black", width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    assert detect_grid(buffer.getvalue()) is None
    assert detect_grid(b"not an encoded image") is None


@pytest.mark.parametrize(
    "name,filename",
    [
        ("pets", "EasyPetsCrosswordPuzzle.jpg"),
        ("cocoa", "printable-easy-crossword-puzzles-cocoa.jpg"),
        ("math", "math-crossword-1-1200.png"),
    ],
)
def test_local_user_worksheet_matches_independent_visual_reference(name, filename):
    image_path = Path.home() / "Downloads" / filename
    reference_path = ROOT / "artifacts" / "user-puzzles" / f"{name}-reference.json"
    if not image_path.is_file() or not reference_path.is_file():
        pytest.skip(
            "Optional local worksheet/reference unavailable; portable tests use generated images."
        )
    reference = json.loads(reference_path.read_text(encoding="utf-8"))["puzzle"]["grid"]
    geometry = detect_grid(image_path.read_bytes())
    assert geometry is not None
    assert geometry.grid == reference
