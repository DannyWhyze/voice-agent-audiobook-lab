from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    text: str
    voice: str | None = None


class CompressorParams(BaseModel):
    threshold_db: float
    ratio: float
    attack_ms: float
    release_ms: float
    knee_db: float = 0.0
    makeup_gain_db: float = 0.0
    detector: Literal["peak", "rms"] = "rms"
    rms_window_ms: float = 10.0


class ReverbParams(BaseModel):
    pre_delay_ms: float
    bandwidth: float
    input_diffusion_1: float
    input_diffusion_2: float
    decay: float
    decay_diffusion_1: float
    decay_diffusion_2: float
    damping: float
    excursion_rate: float
    excursion_depth: float
    wet_dry_mix: float


class EqParams(BaseModel):
    band_gains_db: list[float]


class TrimParams(BaseModel):
    start_ms: float
    end_ms: float


class FadeParams(BaseModel):
    fade_in_ms: float
    fade_out_ms: float


class NormalizeParams(BaseModel):
    mode: Literal["peak", "rms", "lufs"] = "rms"
    target_db: float = -20.0


class PitchParams(BaseModel):
    semitones: int = 0
    cents: float = 0.0


class FormantParams(BaseModel):
    semitones: int = 0
    cents: float = 0.0


class DelayParams(BaseModel):
    delay_time_ms: float
    feedback: float
    damping: float
    saturation: float
    wow_flutter_rate: float
    wow_flutter_depth: float
    wet_dry_mix: float


class ReorderChaptersRequest(BaseModel):
    order: list[str]


class RenameChapterRequest(BaseModel):
    new_name: str


class RenameProjectRequest(BaseModel):
    new_name: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    current_text: str
    context_text: str | None = None
    messages: list[ChatMessage]
    provider: Literal["ollama", "nvidia"] = "ollama"
    model: str | None = None
    allow_extend_recorded_roles: bool = False


class ProjectChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: Literal["ollama", "nvidia"] = "ollama"
    model: str | None = None


class SavePresetRequest(BaseModel):
    name: str
    params: dict


class SetVariantLockRequest(BaseModel):
    locked: bool


class SetVariantLabelRequest(BaseModel):
    label: str


class SetVoiceLockRequest(BaseModel):
    locked: bool


class SetVoiceActiveRequest(BaseModel):
    active: bool


class RenameVoiceRequest(BaseModel):
    new_name: str


class SaveSkillsFileRequest(BaseModel):
    content: str


class CreateSkillRequest(BaseModel):
    name: str
    description: str


class CreateMemoryFileRequest(BaseModel):
    name: str
