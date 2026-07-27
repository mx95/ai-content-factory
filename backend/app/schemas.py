from datetime import datetime

from pydantic import BaseModel, Field


class GenerateScriptRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    language: str = "English"
    duration_seconds: int = Field(default=45, ge=15, le=180)
    niche: str = "Did You Know"


class Scene(BaseModel):
    order: int
    narration: str
    visual_prompt: str


class VideoScriptResponse(BaseModel):
    id: int
    topic: str
    title: str
    description: str
    hashtags: list[str]
    scenes: list[Scene]
    status: str
    created_at: datetime
    video_id: int | None = None
    video_status: str | None = None

    model_config = {"from_attributes": True}


class VideoJobResponse(BaseModel):
    id: int
    script_id: int
    status: str
    error: str | None = None
    voice_path: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    srt_path: str | None = None
    duration_seconds: float | None = None
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    topic: str | None = None
    description: str | None = None
    hashtags: list[str] | None = None
    scenes: list[Scene] | None = None
    media_base: str | None = None

    model_config = {"from_attributes": True}
