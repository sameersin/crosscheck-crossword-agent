"""Detect axis-aligned crossword cell geometry without guessing clue answers.

This supports clean printable grids and sparse worksheets. A missing square is
background, even when it is white. Uncertain/nonrectilinear photos fall back to
the vision model and structural validation rather than invented geometry.
"""

import io
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class GridGeometry:
    grid: list[str]
    x_centers: list[float]
    y_centers: list[float]
    pitch_x: float
    pitch_y: float
    detected_cells: int

    def prompt_hint(self) -> dict:
        return {
            "grid": self.grid,
            "rows": len(self.grid),
            "columns": len(self.grid[0]),
            "note": "Cell borders were detected in pixels. '.' is an actual outlined cell; '#' is a block OR absent background. Preserve this geometry; transcribe only printed clue text and any clearly supplied cell characters.",
        }


def focus_reference_grid(
    image_bytes: bytes, geometry: GridGeometry
) -> tuple[bytes, GridGeometry] | None:
    """Focus OCR on a detected grid without changing or guessing its contents.

    The caller must first establish that this detected mask matches the selected
    puzzle. Scaling only improves the model's view of small source characters;
    it does not add missing image information or establish answer correctness.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            left = max(0, math.floor(geometry.x_centers[0] - geometry.pitch_x * 0.55))
            top = max(0, math.floor(geometry.y_centers[0] - geometry.pitch_y * 0.55))
            right = min(source.width, math.ceil(geometry.x_centers[-1] + geometry.pitch_x * 0.55))
            bottom = min(source.height, math.ceil(geometry.y_centers[-1] + geometry.pitch_y * 0.55))
            if right <= left or bottom <= top:
                return None
            scale = max(1, min(4, math.ceil(48 / min(geometry.pitch_x, geometry.pitch_y))))
            focused = source.convert("RGB").crop((left, top, right, bottom))
            if scale > 1:
                focused = focused.resize(
                    (focused.width * scale, focused.height * scale), Image.Resampling.LANCZOS
                )
            output = io.BytesIO()
            focused.save(output, format="PNG")
            return output.getvalue(), GridGeometry(
                geometry.grid,
                [(x - left) * scale for x in geometry.x_centers],
                [(y - top) * scale for y in geometry.y_centers],
                geometry.pitch_x * scale,
                geometry.pitch_y * scale,
                geometry.detected_cells,
            )
    except (OSError, ValueError):
        return None


def _axis(centers: list[float], size: float) -> tuple[list[float], float] | None:
    groups: list[list[float]] = []
    for center in sorted(centers):
        if not groups or center - float(np.mean(groups[-1])) > size * 0.35:
            groups.append([center])
        else:
            groups[-1].append(center)
    points = np.array([np.median(group) for group in groups])
    if len(points) < 2:
        return None
    differences = np.diff(points)
    near = differences[(differences > size * 0.65) & (differences < size * 1.4)]
    if not len(near):
        return None
    pitch = float(np.median(near))
    indexes = np.rint((points - points[0]) / pitch).astype(int)
    if len(set(indexes)) != len(indexes) or indexes[-1] >= 25:
        return None
    slope, origin = np.polyfit(indexes, points, 1)
    if max(abs(points - (origin + slope * indexes))) > max(2.0, pitch * 0.12):
        return None
    return [float(origin + slope * i) for i in range(int(indexes[-1]) + 1)], float(slope)


def detect_grid(image_bytes: bytes) -> GridGeometry | None:
    gray = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    dark = gray < 190
    contours, _ = cv2.findContours(
        dark.astype(np.uint8) * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    boxes = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if not (10 <= width <= min(gray.shape) * 0.2 and 10 <= height <= min(gray.shape) * 0.2):
            continue
        if not 0.8 <= width / height <= 1.2 or cv2.contourArea(contour) < 0.65 * width * height:
            continue
        polygon = cv2.approxPolyDP(contour, 0.035 * cv2.arcLength(contour, True), True)
        if len(polygon) == 4:
            boxes.append((x, y, width, height))
    if len(boxes) < 6:
        return None
    # Select the repeated cell size, discarding decorative rectangles and letters.
    seed = max(
        boxes,
        key=lambda a: sum(
            abs(b[2] - a[2]) <= max(2, a[2] * 0.1) and abs(b[3] - a[3]) <= max(2, a[3] * 0.1)
            for b in boxes
        ),
    )
    boxes = [
        b
        for b in boxes
        if abs(b[2] - seed[2]) <= max(2, seed[2] * 0.1)
        and abs(b[3] - seed[3]) <= max(2, seed[3] * 0.1)
    ]
    if len(boxes) < 6:
        return None
    x_axis = _axis(
        [x + (w - 1) / 2 for x, _, w, _ in boxes], float(np.median([b[2] for b in boxes]))
    )
    y_axis = _axis(
        [y + (h - 1) / 2 for _, y, _, h in boxes], float(np.median([b[3] for b in boxes]))
    )
    if x_axis is None or y_axis is None:
        return None
    xs, px = x_axis
    ys, py = y_axis
    if not 0.8 <= px / py <= 1.2:
        return None

    def border_support(cx: float, cy: float) -> bool:
        radius = max(1, min(3, round(min(px, py) * 0.05)))
        sides = []
        for sign in (-1, 1):
            x = round(cx + sign * px / 2)
            y0, y1 = round(cy - py * 0.35), round(cy + py * 0.35)
            patch = dark[max(0, y0) : y1 + 1, max(0, x - radius) : x + radius + 1]
            sides.append(float(patch.any(axis=1).mean()) if patch.size else 0)
            y = round(cy + sign * py / 2)
            x0, x1 = round(cx - px * 0.35), round(cx + px * 0.35)
            patch = dark[max(0, y - radius) : y + radius + 1, max(0, x0) : x1 + 1]
            sides.append(float(patch.any(axis=0).mean()) if patch.size else 0)
        interior = dark[
            max(0, round(cy - py * 0.2)) : round(cy + py * 0.2) + 1,
            max(0, round(cx - px * 0.2)) : round(cx + px * 0.2) + 1,
        ]
        return min(sides) >= 0.85 and bool(interior.size) and float(interior.mean()) < 0.1

    observed = {
        (round((y + (h - 1) / 2 - ys[0]) / py), round((x + (w - 1) / 2 - xs[0]) / px))
        for x, y, w, h in boxes
    }
    grid = [
        "".join(
            "." if (r, c) in observed or border_support(x, y) else "#" for c, x in enumerate(xs)
        )
        for r, y in enumerate(ys)
    ]
    count = sum(row.count(".") for row in grid)
    # A large mismatch means the lattice or cell style is not understood reliably.
    if count < max(6, len(boxes) * 0.85) or count > len(boxes) * 1.3:
        return None
    return GridGeometry(grid, xs, ys, px, py, count)
