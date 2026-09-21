"""Answer-key transcription must remain a draft, independent of clue solving.

All completions are mocked. These tests exercise routing and data boundaries,
not the model's ability to read a real answer-key image.
"""

import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from crossword_agent.config import Settings
from crossword_agent.domain import parse_entries
from crossword_agent.evaluation import validate_reference
from crossword_agent.models import Puzzle
from crossword_agent.providers.base import ProviderError
from crossword_agent.providers.nebius import NebiusProvider

SOLVE_MODEL = "zai-org/GLM-5.3"
VISION_MODEL = "zai-org/GLM-5.3-Flash"


@pytest.fixture
def provider(monkeypatch):
    settings = Settings(
        _env_file=None,
        nebius_api_key="test-reference-placeholder",
        nebius_model=SOLVE_MODEL,
        nebius_vision_model=VISION_MODEL,
    )
    value = NebiusProvider(settings)

    def unexpected_request(**_kwargs):
        pytest.fail("Every provider request in these tests must be explicitly mocked.")

    monkeypatch.setattr(value.client.chat.completions, "create", unexpected_request)
    monkeypatch.setattr("crossword_agent.providers.nebius.detect_grid", lambda _: None)
    yield value
    value.close()


@pytest.fixture
def puzzle():
    return Puzzle(
        id="reference-test",
        grid=["...", "...", "..."],
        clues={
            "across": {"1": "CLUE_SENTINEL_A", "4": "CLUE_SENTINEL_B", "5": "CLUE_SENTINEL_C"},
            "down": {"1": "CLUE_SENTINEL_D", "2": "CLUE_SENTINEL_E", "3": "CLUE_SENTINEL_F"},
        },
    )


@pytest.fixture
def image_bytes():
    image = Image.new("RGB", (101, 101), "white")
    draw = ImageDraw.Draw(image)
    for boundary in (5, 35, 65, 95):
        draw.line((boundary, 5, boundary, 95), fill="black", width=2)
        draw.line((5, boundary, 95, boundary), fill="black", width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def mock_completion(provider, monkeypatch, content):
    calls = []
    text = content if isinstance(content, str) else json.dumps(content)

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=13, completion_tokens=7),
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=text))],
        )

    monkeypatch.setattr(provider.client.chat.completions, "create", create)
    return calls


def test_reference_draft_routes_to_vision_and_preserves_usage(
    provider, monkeypatch, puzzle, image_bytes
):
    calls = mock_completion(
        provider,
        monkeypatch,
        {"grid": ["CAT", "APE", "RYE"], "warnings": ["Review the faint final E."]},
    )
    original = puzzle.model_dump()

    grid, warnings, usage = provider.extract_reference_image(puzzle, image_bytes)

    assert grid == ["CAT", "APE", "RYE"]
    assert "Review the faint final E." in warnings
    assert usage.model_calls == 1
    assert usage.prompt_tokens == 13
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 20
    assert puzzle.model_dump() == original
    assert len(calls) == 1
    assert calls[0]["model"] == VISION_MODEL
    image_parts = [
        part
        for message in calls[0]["messages"]
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "image_url"
    ]
    assert len(image_parts) == 1
    assert image_parts[0]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    )


def test_reference_transcription_does_not_receive_clues(provider, monkeypatch, puzzle, image_bytes):
    calls = mock_completion(provider, monkeypatch, {"grid": ["...", "...", "..."]})

    grid, _, _ = provider.extract_reference_image(puzzle, image_bytes)

    payload = json.dumps(calls[0]["messages"])
    assert "CLUE_SENTINEL" not in payload
    assert grid == ["...", "...", "..."]


def test_reference_unknown_cells_stay_unknown_and_cannot_be_graded(
    provider, monkeypatch, puzzle, image_bytes
):
    mock_completion(provider, monkeypatch, {"grid": ["C.T", "APE", "RY."]})

    grid, warnings, _ = provider.extract_reference_image(puzzle, image_bytes)

    assert grid == ["C.T", "APE", "RY."]
    assert warnings, "Incomplete answer-key drafts must visibly require review."
    with pytest.raises(ValueError, match="Every open reference cell"):
        validate_reference(puzzle, grid)


def test_unknown_fixed_cell_is_not_filled_from_the_puzzle(
    provider, monkeypatch, puzzle, image_bytes
):
    puzzle = puzzle.model_copy(update={"grid": ["C..", "...", "..."]})
    mock_completion(provider, monkeypatch, {"grid": [".AT", "APE", "RYE"]})

    grid, warnings, _ = provider.extract_reference_image(puzzle, image_bytes)

    assert grid[0] == ".AT"
    assert warnings


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        "[]",
        {},
        {"grid": None},
        {"grid": "CAT\nAPE\nRYE"},
        {"grid": ["CAT", "APE"]},
        {"grid": ["CAT", "APE", "RY"]},
        {"grid": ["CAT", ["A", "P", "E"], "RYE"]},
        {"grid": ["CAT", "A1E", "RYE"]},
        {"grid": ["CAT", "A?E", "RYE"]},
        {"grid": ["CAT", "A#E", "RYE"]},
    ],
)
def test_reference_rejects_malformed_transcriptions_without_hiding_usage(
    provider, monkeypatch, puzzle, image_bytes, content
):
    mock_completion(provider, monkeypatch, content)

    with pytest.raises(ProviderError) as error:
        provider.extract_reference_image(puzzle, image_bytes)

    assert error.value.usage.model_calls == 1
    assert error.value.usage.total_tokens == 20
    assert "test-reference-placeholder" not in str(error.value)


def test_reference_does_not_silently_repair_changed_blocks(
    provider, monkeypatch, puzzle, image_bytes
):
    puzzle = puzzle.model_copy(update={"grid": ["...", ".#.", "..."]})
    mock_completion(provider, monkeypatch, {"grid": ["CAT", "APE", "RYE"]})

    with pytest.raises(ProviderError):
        provider.extract_reference_image(puzzle, image_bytes)


def test_reference_rejects_conflict_with_given_letter(provider, monkeypatch, puzzle, image_bytes):
    puzzle = puzzle.model_copy(update={"grid": ["C..", "...", "..."]})
    mock_completion(provider, monkeypatch, {"grid": ["BAT", "APE", "RYE"]})

    with pytest.raises(ProviderError) as error:
        provider.extract_reference_image(puzzle, image_bytes)

    assert error.value.usage.total_tokens == 20


def test_numeric_reference_preserves_zero_and_unreadable_cells(
    provider, monkeypatch, puzzle, image_bytes
):
    puzzle = puzzle.model_copy(update={"answer_type": "digits"})
    mock_completion(provider, monkeypatch, {"grid": ["102", "0.0", "301"]})

    grid, warnings, _ = provider.extract_reference_image(puzzle, image_bytes)

    assert grid == ["102", "0.0", "301"]
    assert warnings


@pytest.mark.parametrize("middle", ["1-2", "1A2", "1 2", "1,2"])
def test_numeric_reference_rejects_signs_letters_and_punctuation(
    provider, monkeypatch, puzzle, image_bytes, middle
):
    puzzle = puzzle.model_copy(update={"answer_type": "digits"})
    mock_completion(provider, monkeypatch, {"grid": ["102", middle, "301"]})

    with pytest.raises(ProviderError):
        provider.extract_reference_image(puzzle, image_bytes)


def test_solving_still_routes_to_text_model(provider, monkeypatch, puzzle):
    calls = mock_completion(provider, monkeypatch, {"entries": []})

    provider.generate(parse_entries(puzzle), patterns={}, previous={}, limit=3, timeout=10)

    assert calls[0]["model"] == SOLVE_MODEL


def test_puzzle_image_extraction_routes_to_vision_model(provider, monkeypatch, puzzle, image_bytes):
    monkeypatch.setattr("crossword_agent.providers.nebius.detect_grid", lambda _: None)
    calls = mock_completion(provider, monkeypatch, {"puzzle": puzzle.model_dump()})

    provider.extract_image(image_bytes)

    assert calls[0]["model"] == VISION_MODEL


@pytest.mark.parametrize(
    "vision_input,vision_output,expected",
    [
        (None, None, None),
        (1.5, None, None),
        (None, 4, None),
        (1.5, 4, (13 * 1.5 + 7 * 4) / 1_000_000),
        (0, 0, 0),
    ],
)
def test_reference_vision_cost_never_uses_solving_prices(
    provider,
    monkeypatch,
    puzzle,
    image_bytes,
    vision_input,
    vision_output,
    expected,
):
    provider.settings.input_price_per_million = 50
    provider.settings.output_price_per_million = 100
    provider.settings.vision_input_price_per_million = vision_input
    provider.settings.vision_output_price_per_million = vision_output
    mock_completion(provider, monkeypatch, {"grid": ["CAT", "APE", "RYE"]})

    _, _, vision_usage = provider.extract_reference_image(puzzle, image_bytes)

    if expected is None:
        assert vision_usage.estimated_cost_usd is None
    else:
        assert vision_usage.estimated_cost_usd == pytest.approx(expected)

    mock_completion(provider, monkeypatch, {"entries": []})
    generation = provider.generate(
        parse_entries(puzzle), patterns={}, previous={}, limit=3, timeout=10
    )
    assert generation.usage.estimated_cost_usd == pytest.approx((13 * 50 + 7 * 100) / 1_000_000)


def test_reference_rejects_unsupported_mime_before_request(provider, puzzle, image_bytes):
    with pytest.raises(ProviderError, match="Unsupported") as error:
        provider.extract_reference_image(puzzle, image_bytes, mime="image/svg+xml")

    assert error.value.usage.model_calls == 0


@pytest.fixture
def sparse_puzzle():
    return Puzzle(
        id="sparse-reference-test",
        grid=["..#..", "#####", "..#.."],
        clues={
            "across": {"1": "First", "2": "Second", "3": "Third", "4": "Fourth"},
            "down": {},
        },
    )


def test_open_rows_rebuilds_only_original_blocks(provider, monkeypatch, sparse_puzzle, image_bytes):
    mock_completion(provider, monkeypatch, {"open_rows": ["CATO", "", "MICE"]})

    grid, _, usage = provider.extract_reference_image(sparse_puzzle, image_bytes)

    assert grid == ["CA#TO", "#####", "MI#CE"]
    assert usage.total_tokens == 20
    validate_reference(sparse_puzzle, grid)


def test_open_rows_preserves_unknown_cells_and_given_positions(
    provider, monkeypatch, sparse_puzzle, image_bytes
):
    puzzle = sparse_puzzle.model_copy(update={"grid": ["C.#..", "#####", "..#.."]})
    mock_completion(provider, monkeypatch, {"open_rows": [".ATO", "", "M.C."]})

    grid, warnings, _ = provider.extract_reference_image(puzzle, image_bytes)

    assert grid == [".A#TO", "#####", "M.#C."]
    assert warnings
    with pytest.raises(ValueError, match="Every open reference cell"):
        validate_reference(puzzle, grid)


def test_numeric_open_rows_keeps_leading_and_internal_zeros(
    provider, monkeypatch, sparse_puzzle, image_bytes
):
    puzzle = sparse_puzzle.model_copy(update={"answer_type": "digits"})
    mock_completion(provider, monkeypatch, {"open_rows": ["0010", "", "2030"]})

    grid, _, _ = provider.extract_reference_image(puzzle, image_bytes)

    assert grid == ["00#10", "#####", "20#30"]
    validate_reference(puzzle, grid)


@pytest.mark.parametrize(
    "open_rows",
    [
        None,
        "CATO\n\nMICE",
        [],
        ["CATO", "MICE"],
        ["CATO", "", "MICE", ""],
        ["CAT", "", "MICE"],
        ["CATOX", "", "MICE"],
        ["CATO", ".", "MICE"],
        ["CATO", "", ["M", "I", "C", "E"]],
        ["CATO", "", 1234],
        ["CA#O", "", "MICE"],
        ["CA O", "", "MICE"],
    ],
)
def test_open_rows_rejects_missing_extra_or_malformed_cells(
    provider, monkeypatch, sparse_puzzle, image_bytes, open_rows
):
    mock_completion(provider, monkeypatch, {"open_rows": open_rows})

    with pytest.raises(ProviderError) as error:
        provider.extract_reference_image(sparse_puzzle, image_bytes)

    assert error.value.usage.total_tokens == 20


def test_reference_rejects_ambiguous_grid_and_open_rows(
    provider, monkeypatch, sparse_puzzle, image_bytes
):
    mock_completion(
        provider,
        monkeypatch,
        {"grid": ["CA#TO", "#####", "MI#CE"], "open_rows": ["CATO", "", "MICE"]},
    )

    with pytest.raises(ProviderError):
        provider.extract_reference_image(sparse_puzzle, image_bytes)


def test_open_rows_still_rejects_changed_given_letter(
    provider, monkeypatch, sparse_puzzle, image_bytes
):
    puzzle = sparse_puzzle.model_copy(update={"grid": ["C.#..", "#####", "..#.."]})
    mock_completion(provider, monkeypatch, {"open_rows": ["BATO", "", "MICE"]})

    with pytest.raises(ProviderError):
        provider.extract_reference_image(puzzle, image_bytes)


@pytest.mark.parametrize("matching_geometry", [True, False])
def test_reference_uses_cell_centers_only_for_exactly_matching_geometry(
    provider, monkeypatch, sparse_puzzle, image_bytes, matching_geometry
):
    from crossword_agent.vision import GridGeometry

    detected_mask = sparse_puzzle.grid if matching_geometry else ["..#..", "##.##", "..#.."]
    geometry = GridGeometry(detected_mask, [10, 30, 50, 70, 90], [10, 30, 50], 20, 20, 8)
    monkeypatch.setattr("crossword_agent.providers.nebius.detect_grid", lambda _: geometry)
    calls = mock_completion(provider, monkeypatch, {"open_rows": ["CATO", "", "MICE"]})

    provider.extract_reference_image(sparse_puzzle, image_bytes)

    text_parts = [
        part["text"]
        for message in calls[0]["messages"]
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "text"
    ]
    payload = json.loads(text_parts[0])
    assert [(row["row"], row["open_columns"]) for row in payload["rows"]] == [
        (1, [1, 2, 4, 5]),
        (2, []),
        (3, [1, 2, 4, 5]),
    ]
    centers = payload.get("detected_cell_centers_in_image_pixels")
    image_url = next(
        part["image_url"]["url"]
        for message in calls[0]["messages"]
        if isinstance(message["content"], list)
        for part in message["content"]
        if part.get("type") == "image_url"
    )
    supplied_image = base64.b64decode(image_url.split(",", 1)[1])
    if matching_geometry:
        assert centers == {"columns": [30, 90, 150, 210, 270], "rows": [30, 90, 150]}
        with Image.open(io.BytesIO(supplied_image)) as focused:
            assert focused.size == (303, 183)
            assert all(0 <= x < focused.width for x in centers["columns"])
            assert all(0 <= y < focused.height for y in centers["rows"])
    else:
        assert centers is None
        assert supplied_image == image_bytes


@pytest.mark.parametrize("token_limit,time_limit", [(10000, 180), (1024, 10)])
def test_reference_transcription_respects_its_cap_and_tighter_global_limits(
    provider, monkeypatch, puzzle, image_bytes, token_limit, time_limit
):
    provider.settings.model_max_tokens = token_limit
    provider.settings.model_timeout_seconds = time_limit
    calls = mock_completion(provider, monkeypatch, {"open_rows": ["CAT", "APE", "RYE"]})

    provider.extract_reference_image(puzzle, image_bytes)

    assert calls[0]["max_tokens"] == min(token_limit, 4000)
    assert calls[0]["timeout"] == min(time_limit, 90)


def test_focused_reference_image_preserves_cell_pixels_at_transformed_centers():
    from crossword_agent.vision import GridGeometry, focus_reference_grid

    original = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(original)
    colors = [(220, 30, 40), (40, 170, 60), (30, 60, 220), (240, 180, 20)]
    points = [(30, 30), (50, 30), (30, 50), (50, 50)]
    for (x, y), color in zip(points, colors, strict=True):
        draw.rectangle((x - 5, y - 5, x + 5, y + 5), fill=color)
    raw = io.BytesIO()
    original.save(raw, format="PNG")
    geometry = GridGeometry(["..", ".."], [30, 50], [30, 50], 20, 20, 4)

    result = focus_reference_grid(raw.getvalue(), geometry)

    assert result is not None
    encoded, transformed = result
    assert transformed.grid == geometry.grid
    assert transformed.x_centers == [33, 93]
    assert transformed.y_centers == [33, 93]
    assert transformed.pitch_x == transformed.pitch_y == 60
    with Image.open(io.BytesIO(encoded)) as focused:
        assert focused.size == (126, 126)
        retained = [
            focused.getpixel((int(x), int(y)))
            for y in transformed.y_centers
            for x in transformed.x_centers
        ]
        assert retained == colors


def test_focused_reference_crop_clamps_to_image_bounds_without_padding():
    from crossword_agent.vision import GridGeometry, focus_reference_grid

    color = (123, 45, 67)
    original = Image.new("RGB", (31, 32), color)
    raw = io.BytesIO()
    original.save(raw, format="PNG")
    geometry = GridGeometry(["..", ".."], [3, 23], [4, 24], 20, 20, 4)

    result = focus_reference_grid(raw.getvalue(), geometry)

    assert result is not None
    encoded, transformed = result
    assert transformed.x_centers == [9, 69]
    assert transformed.y_centers == [12, 72]
    with Image.open(io.BytesIO(encoded)) as focused:
        assert focused.size == (93, 96)
        for point in ((0, 0), (92, 0), (0, 95), (92, 95)):
            assert focused.getpixel(point) == color
