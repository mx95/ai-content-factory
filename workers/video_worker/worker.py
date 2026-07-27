from __future__ import annotations

import json
import logging
import time
from datetime import datetime

import pika
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from config import settings
from models import SessionLocal, VideoJob
from notify import send_video_notification
from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("video_worker")

QUEUE_NAME = "video.render"


def process_video(video_id: int) -> None:
    db = SessionLocal()
    try:
        result = db.execute(
            select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
        )
        job = result.unique().scalar_one_or_none()
        if not job:
            logger.error("VideoJob %s not found", video_id)
            return
        if not job.script:
            logger.error("VideoJob %s has no script", video_id)
            return

        job.status = "rendering"
        job.error = None
        job.updated_at = datetime.utcnow()
        db.add(job)
        db.commit()

        logger.info("Rendering video_id=%s title=%s", video_id, job.script.title)
        assets = run_pipeline(
            video_id=job.id,
            title=job.script.title,
            scenes=job.script.scenes,
            language=None,
        )

        job.voice_path = assets["voice_path"]
        job.video_path = assets["video_path"]
        job.thumbnail_path = assets["thumbnail_path"]
        job.srt_path = assets["srt_path"]
        job.duration_seconds = assets["duration_seconds"]
        job.status = "ready"
        job.error = None
        job.updated_at = datetime.utcnow()
        db.add(job)
        db.commit()
        logger.info("Video %s ready (%.1fs)", video_id, job.duration_seconds or 0)
        send_video_notification(
            video_id=job.id,
            title=job.script.title,
            status="ready",
            duration_seconds=job.duration_seconds,
        )
    except Exception as exc:
        logger.exception("Render failed for video_id=%s", video_id)
        db.rollback()
        result = db.execute(
            select(VideoJob).options(joinedload(VideoJob.script)).where(VideoJob.id == video_id)
        )
        job = result.unique().scalar_one_or_none()
        if job:
            job.status = "failed"
            job.error = str(exc)[:4000]
            job.updated_at = datetime.utcnow()
            db.add(job)
            db.commit()
            send_video_notification(
                video_id=job.id,
                title=job.script.title if job.script else f"Video {video_id}",
                status="failed",
                error=job.error,
            )
    finally:
        db.close()


def on_message(channel, method, properties, body) -> None:  # noqa: ANN001
    try:
        payload = json.loads(body.decode("utf-8"))
        video_id = int(payload["video_id"])
    except Exception:
        logger.exception("Invalid message: %s", body)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    process_video(video_id)
    channel.basic_ack(delivery_tag=method.delivery_tag)


def main() -> None:
    logger.info("Video worker starting; queue=%s", QUEUE_NAME)
    while True:
        try:
            params = pika.URLParameters(settings.rabbitmq_url)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)
            logger.info("Connected to RabbitMQ, waiting for jobs")
            channel.start_consuming()
        except Exception:
            logger.exception("Worker connection error; retrying in 5s")
            time.sleep(5)


if __name__ == "__main__":
    main()
