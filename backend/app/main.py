import asyncio
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings, video_dir
from app.database import Base, engine, get_db
from app.models import VideoJob, VideoScript
from app.queue import enqueue_video_render
from app.schemas import GenerateScriptRequest, VideoJobResponse, VideoScriptResponse
from app.script_generator import generate_script_payload

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Content Factory API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def _script_response(script: VideoScript) -> VideoScriptResponse:
    video = script.video
    return VideoScriptResponse(
        id=script.id,
        topic=script.topic,
        title=script.title,
        description=script.description,
        hashtags=script.hashtags,
        scenes=script.scenes,
        status=script.status,
        created_at=script.created_at,
        video_id=video.id if video else None,
        video_status=video.status if video else None,
    )


def _video_response(job: VideoJob) -> VideoJobResponse:
    script = job.script
    return VideoJobResponse(
        id=job.id,
        script_id=job.script_id,
        status=job.status,
        error=job.error,
        voice_path=job.voice_path,
        video_path=job.video_path,
        thumbnail_path=job.thumbnail_path,
        srt_path=job.srt_path,
        duration_seconds=job.duration_seconds,
        created_at=job.created_at,
        updated_at=job.updated_at,
        title=script.title if script else None,
        topic=script.topic if script else None,
        description=script.description if script else None,
        hashtags=script.hashtags if script else None,
        scenes=script.scenes if script else None,
        media_base=f"/api/media/{job.id}" if job.video_path else None,
    )


def _enqueue(job: VideoJob, db: Session, force: bool = False) -> VideoJob:
    job.status = "queued"
    job.error = None
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        enqueue_video_render(job.id, force=force)
    except Exception as exc:
        logger.exception("Failed to enqueue video %s", job.id)
        job.status = "failed"
        job.error = f"Queue publish failed: {exc}"
        db.add(job)
        db.commit()
        db.refresh(job)
    return job


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "script_engine": "cursor" if settings.cursor_api_key else "mock",
        "pipeline": "openai+ffmpeg" if settings.openai_api_key else "edge-tts+ffmpeg",
        "openai_media": bool(settings.openai_api_key),
    }


@app.post("/scripts", response_model=VideoScriptResponse)
async def create_script(
    request: GenerateScriptRequest,
    db: Session = Depends(get_db),
) -> VideoScriptResponse:
    try:
        payload = await asyncio.to_thread(generate_script_payload, request)
    except Exception as exc:
        logger.exception("Script generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    script = VideoScript(
        topic=request.topic,
        title=payload["title"],
        description=payload["description"],
        hashtags=payload["hashtags"],
        scenes=payload["scenes"],
        status="script_ready",
    )
    db.add(script)
    db.commit()
    db.refresh(script)

    job = VideoJob(script_id=script.id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    _enqueue(job, db)

    result = db.execute(
        select(VideoScript).options(joinedload(VideoScript.video)).where(VideoScript.id == script.id)
    )
    script = result.unique().scalar_one()
    return _script_response(script)


@app.get("/scripts", response_model=list[VideoScriptResponse])
def list_scripts(db: Session = Depends(get_db)) -> list[VideoScriptResponse]:
    result = db.execute(
        select(VideoScript)
        .options(joinedload(VideoScript.video))
        .order_by(VideoScript.created_at.desc())
        .limit(25)
    )
    return [_script_response(script) for script in result.unique().scalars().all()]


@app.get("/scripts/{script_id}", response_model=VideoScriptResponse)
def get_script(script_id: int, db: Session = Depends(get_db)) -> VideoScriptResponse:
    result = db.execute(
        select(VideoScript).options(joinedload(VideoScript.video)).where(VideoScript.id == script_id)
    )
    script = result.unique().scalar_one_or_none()
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return _script_response(script)


@app.get("/videos", response_model=list[VideoJobResponse])
def list_videos(db: Session = Depends(get_db)) -> list[VideoJobResponse]:
    result = db.execute(
        select(VideoJob)
        .options(joinedload(VideoJob.script))
        .order_by(VideoJob.created_at.desc())
        .limit(25)
    )
    return [_video_response(job) for job in result.unique().scalars().all()]


@app.get("/videos/{video_id}", response_model=VideoJobResponse)
def get_video(video_id: int, db: Session = Depends(get_db)) -> VideoJobResponse:
    result = db.execute(
        select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")
    return _video_response(job)


@app.post("/videos/{video_id}/render", response_model=VideoJobResponse)
def render_video(video_id: int, db: Session = Depends(get_db)) -> VideoJobResponse:
    result = db.execute(
        select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")
    job = _enqueue(job, db, force=True)
    result = db.execute(
        select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
    )
    return _video_response(result.unique().scalar_one())


@app.post("/videos/{video_id}/approve", response_model=VideoJobResponse)
def approve_video(video_id: int, db: Session = Depends(get_db)) -> VideoJobResponse:
    result = db.execute(
        select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")
    if job.status != "ready":
        raise HTTPException(status_code=400, detail=f"Cannot approve video in status={job.status}")
    job.status = "approved"
    db.add(job)
    db.commit()
    db.refresh(job)
    return _video_response(job)


@app.post("/videos/{video_id}/reject", response_model=VideoJobResponse)
def reject_video(video_id: int, db: Session = Depends(get_db)) -> VideoJobResponse:
    result = db.execute(
        select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")
    if job.status not in {"ready", "approved"}:
        raise HTTPException(status_code=400, detail=f"Cannot reject video in status={job.status}")
    job.status = "rejected"
    db.add(job)
    db.commit()
    db.refresh(job)
    return _video_response(job)


@app.get("/media/{video_id}/{filename}")
def get_media(video_id: int, filename: str) -> FileResponse:
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = video_dir(video_id) / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    media_types = {
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".png": "image/png",
        ".srt": "application/x-subrip",
    }
    return FileResponse(path, media_type=media_types.get(path.suffix.lower(), "application/octet-stream"))
