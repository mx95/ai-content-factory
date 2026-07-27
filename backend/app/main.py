from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import VideoScript
from app.schemas import GenerateScriptRequest, VideoScriptResponse
from app.script_generator import generate_script_payload

app = FastAPI(title="AI Content Factory API", version="0.1.0")

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/scripts", response_model=VideoScriptResponse)
def create_script(
    request: GenerateScriptRequest,
    db: Session = Depends(get_db),
) -> VideoScript:
    payload = generate_script_payload(request)
    script = VideoScript(
        topic=request.topic,
        title=payload["title"],
        description=payload["description"],
        hashtags=payload["hashtags"],
        scenes=payload["scenes"],
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    return script


@app.get("/scripts", response_model=list[VideoScriptResponse])
def list_scripts(db: Session = Depends(get_db)) -> list[VideoScript]:
    result = db.execute(select(VideoScript).order_by(VideoScript.created_at.desc()).limit(25))
    return list(result.scalars().all())
