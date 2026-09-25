"""Pydantic contracts for the ComicReels API."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

class BBox(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

class PanelPatch(BaseModel):
    display_order: int | None = Field(default=None, ge=0)
    bbox: BBox | None = None

class DialogueInput(BaseModel):
    id: str | None = None
    sequence: int = Field(ge=0)
    speaker_id: str | None = None
    speaker_name: str | None = None
    verbatim_text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    bbox: BBox | None = None
    user_verified: bool = False

class DialogueBatch(BaseModel):
    dialogues: list[DialogueInput]

class MaskBox(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

class MaskRequest(BaseModel):
    boxes: list[MaskBox] | None = None
    padding: int = Field(default=8, ge=0, le=100)
    inpaint_radius: int = Field(default=5, ge=1, le=50)

class AnalyzeRequest(BaseModel):
    use_vision: bool = True
    replace_existing: bool = False

class ApprovalRequest(BaseModel):
    expected_sha256: str

class ShotPlanRequest(BaseModel):
    model_family: Literal["omni_flash", "veo"] = "omni_flash"
    allowed_durations: list[int] | None = None
    words_per_second: float = Field(default=2.6, gt=0.5, le=8)

class GenerationRequest(BaseModel):
    shot_id: str
    idempotency_key: str = Field(min_length=8, max_length=160)
    confirm_cost: bool = False
    model_family: Literal["omni_flash", "veo"] = "omni_flash"
    duration_s: int | None = None
    resolution: Literal["360p", "720p"] = "720p"
    flow_project_id: str | None = None

class BatchGenerationRequest(BaseModel):
    shot_ids: list[str]
    batch_key: str = Field(min_length=8, max_length=120)
    confirm_cost: bool = False
    model_family: Literal["omni_flash", "veo"] = "omni_flash"
    resolution: Literal["360p", "720p"] = "720p"
    flow_project_id: str | None = None

class ReviewRequest(BaseModel):
    review_status: Literal["APPROVED", "REJECTED", "PENDING"]

class CharacterInput(BaseModel):
    name: str
    stable_key: str | None = None
    description: str | None = None

class RestoreOptions(BaseModel):
    name_override: str | None = None

class ProjectSummary(BaseModel):
    id: str
    name: str
    status: str
    source_sha256: str
    source_width: int
    source_height: int
    panels: list[dict[str, Any]] = []
    characters: list[dict[str, Any]] = []
    generations: list[dict[str, Any]] = []
