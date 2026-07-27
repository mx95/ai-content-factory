import json
import logging

import pika

from app.config import settings

logger = logging.getLogger(__name__)

QUEUE_NAME = "video.render"


def enqueue_video_render(video_id: int, force: bool = False) -> None:
    params = pika.URLParameters(settings.rabbitmq_url)
    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        body = json.dumps({"video_id": video_id, "force": force})
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=body.encode("utf-8"),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        logger.info("Enqueued video.render for video_id=%s force=%s", video_id, force)
    finally:
        connection.close()
