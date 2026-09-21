"""Request schemas used only by the HTTP evaluation workflow."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_grid: list[str] = Field(min_length=1, max_length=25)
    source: Literal[
        "human_reviewed_agent_copy",
        "human_entered",
        "uploaded_json",
        "publisher_key",
        "uploaded_image",
    ]
    approved: StrictBool
    source_note: str = Field(default="", max_length=1000)
    puzzle_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    puzzle_id: str | None = Field(default=None, max_length=100)
