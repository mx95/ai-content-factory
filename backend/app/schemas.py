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

    model_config = {"from_attributes": True}
