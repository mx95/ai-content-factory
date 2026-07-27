from __future__ import annotations

import asyncio
import logging
import subprocess
import textwrap
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

from config import settings, video_dir

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or result.stdout[-2000:] or "ffmpeg failed")


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


async def _synthesize_scene(text: str, output: Path, voice: str) -> None:
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(output))
        if output.stat().st_size > 0:
            return
        raise RuntimeError("edge-tts produced empty audio")
    except Exception as exc:
        logger.warning("edge-tts failed (%s); falling back to espeak-ng", exc)
        _synthesize_with_espeak(text, output)


def _synthesize_with_espeak(text: str, output: Path) -> None:
    wav_path = output.with_suffix(".wav")
    subprocess.run(
        ["espeak-ng", "-w", str(wav_path), text],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(output),
        ]
    )
    wav_path.unlink(missing_ok=True)


def _pick_voice(language: str | None = None) -> str:
    mapping = {
        "english": "en-US-JennyNeural",
        "greek": "el-GR-AthinaNeural",
        "spanish": "es-ES-ElviraNeural",
        "german": "de-DE-KatjaNeural",
    }
    if language:
        return mapping.get(language.strip().lower(), settings.edge_tts_voice)
    return settings.edge_tts_voice


def generate_scene_image(prompt: str, title: str, order: int, output: Path) -> None:
    top = (16, 48, 41)
    bottom = (46, 194, 142)
    image = Image.new("RGB", (WIDTH, HEIGHT), top)
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    draw.rounded_rectangle((72, 120, WIDTH - 72, 220), radius=28, fill=(12, 35, 28))
    draw.text((110, 145), f"SCENE {order:02d}", fill=(93, 224, 166), font=_font(42))

    wrapped_title = textwrap.fill(title[:80], width=22)
    draw.multiline_text((96, 280), wrapped_title, fill=(247, 251, 248), font=_font(64), spacing=12)

    draw.rounded_rectangle((72, 720, WIDTH - 72, 1500), radius=36, fill=(15, 35, 29))
    wrapped_prompt = textwrap.fill(prompt[:280], width=28)
    draw.multiline_text((110, 760), wrapped_prompt, fill=(236, 248, 242), font=_font(44), spacing=10)
    draw.text((96, HEIGHT - 160), "AI Content Factory", fill=(204, 224, 215), font=_font(36))
    image.save(output, format="PNG")


def write_srt(scenes: list[dict], durations: list[float], output: Path) -> None:
    lines: list[str] = []
    cursor = 0.0
    for index, (scene, duration) in enumerate(zip(scenes, durations), start=1):
        start = cursor
        end = cursor + duration
        lines.append(str(index))
        lines.append(f"{_ts(start)} --> {_ts(end)}")
        lines.append(scene.get("narration", "").strip())
        lines.append("")
        cursor = end
    output.write_text("\n".join(lines), encoding="utf-8")


def _ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def generate_thumbnail(scene_image: Path, title: str, output: Path) -> None:
    base = Image.open(scene_image).convert("RGB").resize((1280, 720))
    draw = ImageDraw.Draw(base)
    draw.rectangle((0, 420, 1280, 720), fill=(12, 35, 28))
    wrapped = textwrap.fill(title[:90], width=28)
    draw.multiline_text((48, 460), wrapped, fill=(255, 255, 255), font=_font(48), spacing=8)
    base.save(output, format="PNG")


def render_video(
    scene_images: list[Path],
    durations: list[float],
    narration_path: Path,
    srt_path: Path,
    output_path: Path,
) -> None:
    work = output_path.parent / "segments"
    work.mkdir(parents=True, exist_ok=True)
    segment_files: list[Path] = []

    for index, (image, duration) in enumerate(zip(scene_images, durations), start=1):
        segment = work / f"seg_{index:03d}.mp4"
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image),
                "-vf",
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                "-t",
                f"{max(duration, 1.5):.3f}",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(segment),
            ]
        )
        segment_files.append(segment)

    concat_list = work / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in segment_files) + "\n",
        encoding="utf-8",
    )
    silent_video = work / "silent.mp4"
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(silent_video),
        ]
    )

    # Absolute path without spaces for the subtitles filter.
    srt_abs = srt_path.resolve().as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(narration_path),
            "-vf",
            (
                f"subtitles={srt_abs}:"
                "force_style='FontName=DejaVu Sans,Fontsize=18,PrimaryColour=&H00FFFFFF&,"
                "OutlineColour=&H0010231D&,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=90'"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


async def build_video_assets(video_id: int, title: str, scenes: list[dict], language: str | None = None) -> dict:
    out_dir = video_dir(video_id)
    voice = _pick_voice(language)
    ordered = sorted(scenes, key=lambda item: int(item.get("order", 0)))
    if not ordered:
        raise RuntimeError("Script has no scenes")

    scene_audio_paths: list[Path] = []
    durations: list[float] = []
    scene_images: list[Path] = []

    for scene in ordered:
        order = int(scene.get("order", len(scene_audio_paths) + 1))
        narration = (scene.get("narration") or "").strip()
        prompt = (scene.get("visual_prompt") or narration or title).strip()
        if not narration:
            raise RuntimeError(f"Scene {order} is missing narration")

        audio_path = out_dir / f"scene_{order:03d}.mp3"
        image_path = out_dir / f"scene_{order:03d}.png"
        logger.info("TTS scene %s", order)
        await _synthesize_scene(narration, audio_path, voice)
        duration = max(_probe_duration(audio_path), 1.5)
        generate_scene_image(prompt, title, order, image_path)
        scene_audio_paths.append(audio_path)
        durations.append(duration)
        scene_images.append(image_path)

    narration_path = out_dir / "narration.mp3"
    concat_audio = out_dir / "audio_concat.txt"
    concat_audio.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in scene_audio_paths) + "\n",
        encoding="utf-8",
    )
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_audio),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(narration_path),
        ]
    )

    srt_path = out_dir / "captions.srt"
    write_srt(ordered, durations, srt_path)

    video_path = out_dir / "final.mp4"
    logger.info("Compositing final.mp4 for video %s", video_id)
    render_video(scene_images, durations, narration_path, srt_path, video_path)

    thumb_path = out_dir / "thumb.png"
    generate_thumbnail(scene_images[0], title, thumb_path)

    total_duration = _probe_duration(video_path)
    return {
        "voice_path": f"videos/{video_id}/narration.mp3",
        "video_path": f"videos/{video_id}/final.mp4",
        "thumbnail_path": f"videos/{video_id}/thumb.png",
        "srt_path": f"videos/{video_id}/captions.srt",
        "duration_seconds": total_duration,
    }


def run_pipeline(video_id: int, title: str, scenes: list[dict], language: str | None = None) -> dict:
    return asyncio.run(build_video_assets(video_id, title, scenes, language))
