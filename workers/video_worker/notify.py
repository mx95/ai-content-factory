from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)


def send_video_notification(
    *,
    video_id: int,
    title: str,
    status: str,
    duration_seconds: float | None = None,
    error: str | None = None,
) -> None:
    if not settings.notify_email_to:
        logger.info("NOTIFY_EMAIL_TO not set; skipping email for video %s", video_id)
        return
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        logger.warning("SMTP not fully configured; skipping email for video %s", video_id)
        return

    app_url = settings.app_public_url.rstrip("/")
    subject = f"[AI Content Factory] Video {status}: {title}"
    lines = [
        f"Video #{video_id} is now {status}.",
        f"Title: {title}",
    ]
    if duration_seconds is not None:
        lines.append(f"Duration: {duration_seconds:.1f}s")
    if error:
        lines.append(f"Error: {error}")
    lines.extend(
        [
            "",
            f"Open dashboard: {app_url}",
            f"Preview (if ready): {app_url}/api/media/{video_id}/final.mp4",
        ]
    )
    body = "\n".join(lines)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = settings.notify_email_to
    message.set_content(body)

    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
        logger.info("Sent %s notification for video %s to %s", status, video_id, settings.notify_email_to)
    except Exception:
        logger.exception("Failed to send email notification for video %s", video_id)
