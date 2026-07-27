from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import textwrap
import urllib.parse
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import edge_tts
import httpx
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from config import settings, video_dir

logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920


@dataclass
class OpenAIGate:
    """Skip further OpenAI calls after the first quota/billing failure in a job."""

    disabled: bool = False
    reason: str = ""
    failures: list[str] = field(default_factory=list)

    def note_failure(self, exc: Exception) -> None:
        message = str(exc)
        self.failures.append(message[:300])
        lowered = message.lower()
        if any(
            token in lowered
            for token in (
                "insufficient_quota",
                "exceeded your current quota",
                "billing",
                "rate_limit",
                "429",
            )
        ):
            self.disabled = True
            self.reason = message[:240]
            logger.warning("OpenAI disabled for remainder of this job: %s", self.reason)

    @property
    def enabled(self) -> bool:
        return bool(settings.openai_api_key) and not self.disabled


def _openai_client() -> OpenAI | None:
    if not settings.openai_api_key:
        return None
    return OpenAI(api_key=settings.openai_api_key)


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


def _fit_cover(image: Image.Image, width: int, height: int) -> Image.Image:
    image = image.convert("RGB")
    src_w, src_h = image.size
    scale = max(width / src_w, height / src_h)
    resized = image.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))), Image.Resampling.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _synthesize_with_openai(text: str, output: Path) -> None:
    client = _openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    with client.audio.speech.with_streaming_response.create(
        model=settings.openai_tts_model,
        voice=settings.openai_tts_voice,
        input=text,
        response_format="mp3",
    ) as response:
        response.stream_to_file(output)
    if output.stat().st_size <= 0:
        raise RuntimeError("OpenAI TTS produced empty audio")


WordTiming = tuple[str, float, float]  # word, start_sec, end_sec


async def _synthesize_with_edge(text: str, output: Path, voice: str) -> list[WordTiming]:
    """Synthesize audio and return real word timestamps from Edge WordBoundary events."""
    communicate = edge_tts.Communicate(text=text, voice=voice, boundary="WordBoundary")
    boundaries: list[WordTiming] = []
    with output.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = float(chunk["offset"]) / 10_000_000
                end = start + (float(chunk["duration"]) / 10_000_000)
                word = str(chunk.get("text") or "").strip()
                if word:
                    boundaries.append((word, start, max(end, start + 0.08)))
    if output.stat().st_size <= 0:
        raise RuntimeError("edge-tts produced empty audio")
    if not boundaries:
        return []
    # Prefer script tokens (keeps punctuation) when counts match Edge boundaries.
    script_words = " ".join(text.split()).split()
    if len(script_words) == len(boundaries):
        return [
            (script_word, start, end)
            for script_word, (_edge_word, start, end) in zip(script_words, boundaries)
        ]
    return boundaries


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


def _align_words_with_whisper(audio_path: Path, gate: OpenAIGate) -> list[WordTiming]:
    """Force-align generated speech with Whisper word timestamps."""
    if not gate.enabled:
        raise RuntimeError("OpenAI unavailable for whisper alignment")
    client = _openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    with audio_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
    words_payload = getattr(result, "words", None) or []
    timed: list[WordTiming] = []
    for item in words_payload:
        if isinstance(item, dict):
            word = str(item.get("word") or "").strip()
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or start)
        else:
            word = str(getattr(item, "word", "") or "").strip()
            start = float(getattr(item, "start", 0.0) or 0.0)
            end = float(getattr(item, "end", start) or start)
        if word:
            timed.append((word, start, max(end, start + 0.08)))
    if not timed:
        raise RuntimeError("Whisper returned no word timestamps")
    return timed


def _estimate_words(text: str, duration: float) -> list[WordTiming]:
    words = " ".join(text.split()).split()
    if not words:
        return []
    weights = [max(len(re.sub(r"[^\w]", "", w)), 1) for w in words]
    total = sum(weights) or 1
    timed: list[WordTiming] = []
    local = 0.0
    for word, weight in zip(words, weights):
        word_dur = duration * (weight / total)
        start = local
        end = start + max(word_dur, 0.08)
        timed.append((word, start, min(duration, end)))
        local += word_dur
    return timed


def _pad_audio_to_duration(path: Path, target: float) -> float:
    """Pad short clips with silence so video segments match the narration timeline."""
    current = _probe_duration(path)
    if current >= target - 0.02:
        return current
    padded = path.with_name(f"{path.stem}_padded{path.suffix}")
    pad = max(target - current, 0.01)
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-af",
            f"apad=pad_dur={pad:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(padded),
        ]
    )
    padded.replace(path)
    return _probe_duration(path)


async def _synthesize_scene(
    text: str, output: Path, edge_voice: str, gate: OpenAIGate
) -> list[WordTiming]:
    """Generate scene audio and return per-word timings relative to this clip."""
    if gate.enabled:
        try:
            await asyncio.to_thread(_synthesize_with_openai, text, output)
            try:
                return await asyncio.to_thread(_align_words_with_whisper, output, gate)
            except Exception as exc:
                gate.note_failure(exc)
                logger.warning("Whisper word-align failed (%s); using edge-tts for sync", exc)
        except Exception as exc:
            gate.note_failure(exc)
            logger.warning("OpenAI TTS failed (%s); trying edge-tts", exc)

    try:
        words = await _synthesize_with_edge(text, output, edge_voice)
        if words:
            return words
        duration = max(_probe_duration(output), 0.4)
        return _estimate_words(text, duration)
    except Exception as exc:
        logger.warning("edge-tts failed (%s); falling back to espeak-ng", exc)
        await asyncio.to_thread(_synthesize_with_espeak, text, output)
        duration = max(_probe_duration(output), 0.4)
        return _estimate_words(text, duration)


def _pick_edge_voice(language: str | None = None) -> str:
    mapping = {
        "english": "en-US-JennyNeural",
        "greek": "el-GR-AthinaNeural",
        "spanish": "es-ES-ElviraNeural",
        "german": "de-DE-KatjaNeural",
    }
    if language:
        return mapping.get(language.strip().lower(), settings.edge_tts_voice)
    return settings.edge_tts_voice


def _download_image(url: str) -> Image.Image:
    response = httpx.get(url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def _generate_openai_scene(prompt: str, title: str) -> Image.Image:
    client = _openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    full_prompt = (
        "Vertical 9:16 cinematic still for a YouTube Short. Photoreal or premium illustrated look, "
        "dramatic lighting, rich detail, NO text, NO watermark, NO logos, NO UI. "
        f"Title context: {title}. Scene: {prompt}"
    )[:3900]

    # Prefer modern image model, then older variants that some accounts still have.
    model_attempts: list[tuple[str, dict]] = [
        (
            settings.openai_image_model,
            {"prompt": full_prompt, "size": "1024x1792", "n": 1},
        ),
        (
            "gpt-image-1",
            {"prompt": full_prompt, "size": "1024x1536", "n": 1},
        ),
        (
            "dall-e-2",
            {"prompt": full_prompt[:1000], "size": "1024x1024", "n": 1},
        ),
    ]

    last_error: Exception | None = None
    for model, kwargs in model_attempts:
        try:
            params = {"model": model, **kwargs}
            if model.startswith("dall-e-3"):
                params["quality"] = "standard"
                params["size"] = "1024x1792"
            result = client.images.generate(**params)
            item = result.data[0]
            if getattr(item, "b64_json", None):
                image = Image.open(BytesIO(__import__("base64").b64decode(item.b64_json))).convert("RGB")
            elif getattr(item, "url", None):
                image = _download_image(item.url)
            else:
                raise RuntimeError("OpenAI image response missing url/b64_json")
            return _fit_cover(image, WIDTH, HEIGHT)
        except Exception as exc:
            last_error = exc
            logger.warning("OpenAI image model %s failed: %s", model, exc)
            continue
    raise RuntimeError(str(last_error) if last_error else "OpenAI image generation failed")


def _generate_pollinations_scene(prompt: str, title: str) -> Image.Image:
    # Free image endpoint used when OpenAI images are unavailable.
    query = urllib.parse.quote(
        f"{prompt}, cinematic vertical composition, dramatic lighting, no text, no watermark, {title}"
    )
    url = (
        f"https://image.pollinations.ai/prompt/{query}"
        f"?width={WIDTH}&height={HEIGHT}&nologo=true&enhance=true"
    )
    image = _download_image(url)
    return _fit_cover(image, WIDTH, HEIGHT)


def _generate_pillow_scene(prompt: str, title: str, order: int) -> Image.Image:
    """Appealing abstract fallback — never dump the full prompt as a wall of text."""
    palette = [
        ((12, 24, 48), (34, 120, 180), (240, 180, 90)),
        ((20, 10, 40), (120, 40, 140), (40, 200, 180)),
        ((8, 40, 30), (20, 120, 90), (220, 220, 120)),
        ((30, 10, 20), (160, 40, 70), (240, 160, 80)),
    ]
    c1, c2, accent = palette[(order - 1) % len(palette)]
    image = Image.new("RGBA", (WIDTH, HEIGHT), (*c1, 255))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(int(c1[i] * (1 - ratio) + c2[i] * ratio) for i in range(3)) + (255,)
        draw.line([(0, y), (WIDTH, y)], fill=color)

    for idx, offset in enumerate((0, 180, 360)):
        bbox = (80 + offset // 2, 420 + offset, WIDTH - 80 - offset // 3, 980 + offset // 2)
        draw.ellipse(bbox, fill=(*accent, 45 + idx * 18))

    image = image.filter(ImageFilter.GaussianBlur(radius=0.8))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 120, WIDTH - 64, 250), radius=28, fill=(0, 0, 0, 150))
    draw.text((96, 155), f"SCENE {order:02d}", fill=(*accent, 255), font=_font(44))

    short_title = textwrap.fill(title[:48], width=18)
    draw.multiline_text((96, 300), short_title, fill=(250, 250, 250, 255), font=_font(58), spacing=10)

    hint = textwrap.fill((prompt or title)[:70], width=28)
    draw.rounded_rectangle((64, HEIGHT - 320, WIDTH - 64, HEIGHT - 140), radius=24, fill=(0, 0, 0, 130))
    draw.multiline_text((96, HEIGHT - 280), hint, fill=(230, 230, 230, 255), font=_font(32), spacing=6)
    return image.convert("RGB")


def generate_scene_image(prompt: str, title: str, order: int, output: Path, gate: OpenAIGate) -> None:
    image: Image.Image | None = None

    if gate.enabled:
        try:
            image = _generate_openai_scene(prompt, title)
            logger.info("Scene %s image source=openai", order)
        except Exception as exc:
            gate.note_failure(exc)
            logger.warning("OpenAI image failed for scene %s (%s)", order, exc)

    if image is None:
        try:
            image = _generate_pollinations_scene(prompt, title)
            logger.info("Scene %s image source=pollinations", order)
        except Exception as exc:
            logger.warning("Pollinations image failed for scene %s (%s); using styled fallback", order, exc)
            image = _generate_pillow_scene(prompt, title, order)
            logger.info("Scene %s image source=pillow", order)

    # Mild contrast boost so frames feel less flat on phone screens.
    image = ImageEnhance.Contrast(image).enhance(1.08)
    image = ImageEnhance.Color(image).enhance(1.06)
    image.save(output, format="PNG")


def _caption_chunks(narration: str, max_words: int = 6) -> list[str]:
    """Split narration into short bottom captions that track the voice."""
    cleaned = " ".join((narration or "").split())
    if not cleaned:
        return []

    pieces: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
        words = sentence.split()
        if not words:
            continue
        for i in range(0, len(words), max_words):
            chunk = " ".join(words[i : i + max_words]).strip()
            if chunk:
                pieces.append(chunk)
    return pieces or [cleaned]


def _offset_words(words: list[WordTiming], offset: float) -> list[WordTiming]:
    return [(word, start + offset, end + offset) for word, start, end in words]


def _flatten_timed_words(scene_words: list[list[WordTiming]], durations: list[float]) -> list[WordTiming]:
    """Combine per-scene word timings onto the concatenated narration timeline."""
    timed: list[WordTiming] = []
    cursor = 0.0
    for words, duration in zip(scene_words, durations):
        if words:
            timed.extend(_offset_words(words, cursor))
        cursor += duration
    return timed


def _display_windows(timed: list[WordTiming]) -> list[WordTiming]:
    """Show each word from its spoken start until the next word begins."""
    if not timed:
        return []
    windows: list[WordTiming] = []
    for index, (word, start, end) in enumerate(timed):
        if index + 1 < len(timed):
            display_end = timed[index + 1][1]
        else:
            display_end = max(end, start + 0.2)
        if display_end <= start:
            display_end = start + 0.08
        windows.append((word, start, display_end))
    return windows


def write_srt(timed_words: list[WordTiming], output: Path) -> None:
    lines: list[str] = []
    cue_index = 1
    for word, start, end in _display_windows(timed_words):
        lines.append(str(cue_index))
        lines.append(f"{_ts(start)} --> {_ts(end)}")
        lines.append(word)
        lines.append("")
        cue_index += 1
    output.write_text("\n".join(lines), encoding="utf-8")


def _ass_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "\\\\").replace("\n", " ")


def write_ass_karaoke(timed_words: list[WordTiming], output: Path) -> None:
    """Word-by-word pop captions timed to real speech timestamps."""
    header = """[Script Info]
Title: AI Content Factory Karaoke
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: WordPop,DejaVu Sans,64,&H00FFFFFF,&H0000E5FF,&HDC000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,60,60,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for word, start, end in _display_windows(timed_words):
        clean = _ass_escape(word)
        # Pop-in scale so each spoken word feels punchy and easy to follow.
        text = (
            r"{\fad(40,60)\t(0,90,\fscx130\fscy130)\t(90,160,\fscx100\fscy100)\bord4}"
            + clean
        )
        events.append(
            f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},WordPop,,0,0,0,,{text}"
        )
    output.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


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
    timed_words: list[WordTiming],
    output_path: Path,
) -> None:
    work_name = "segments_demo" if output_path.name != "final.mp4" else "segments"
    work = output_path.parent / work_name
    work.mkdir(parents=True, exist_ok=True)
    segment_files: list[Path] = []

    for index, (image, duration) in enumerate(zip(scene_images, durations), start=1):
        segment = work / f"seg_{index:03d}.mp4"
        # Gentle Ken Burns zoom so still images feel more like video.
        frames = max(int(duration * 30), 45)
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image),
                "-vf",
                (
                    f"scale=1200:2133,"
                    f"zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    f":d={frames}:s={WIDTH}x{HEIGHT}:fps=30,"
                    f"format=yuv420p"
                ),
                "-t",
                f"{max(duration, 0.4):.3f}",
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

    captions_stem = "captions_demo" if output_path.name != "final.mp4" else "captions"
    ass_path = output_path.parent / f"{captions_stem}.ass"
    write_ass_karaoke(timed_words, ass_path)
    write_srt(timed_words, output_path.parent / f"{captions_stem}.srt")
    ass_abs = ass_path.resolve().as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(narration_path),
            "-vf",
            f"ass={ass_abs}",
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


async def build_video_assets(
    video_id: int,
    title: str,
    scenes: list[dict],
    language: str | None = None,
    *,
    max_scenes: int | None = None,
    output_filename: str = "final.mp4",
) -> dict:
    out_dir = video_dir(video_id)
    edge_voice = _pick_edge_voice(language)
    gate = OpenAIGate()
    ordered = sorted(scenes, key=lambda item: int(item.get("order", 0)))
    if max_scenes is not None:
        ordered = ordered[: max(1, max_scenes)]
    if not ordered:
        raise RuntimeError("Script has no scenes")

    scene_audio_paths: list[Path] = []
    durations: list[float] = []
    scene_images: list[Path] = []
    scene_words: list[list[WordTiming]] = []

    for scene in ordered:
        order = int(scene.get("order", len(scene_audio_paths) + 1))
        narration = (scene.get("narration") or "").strip()
        prompt = (scene.get("visual_prompt") or narration or title).strip()
        if not narration:
            raise RuntimeError(f"Scene {order} is missing narration")

        audio_path = out_dir / f"scene_{order:03d}.mp3"
        image_path = out_dir / f"scene_{order:03d}.png"
        logger.info("TTS scene %s", order)
        words = await _synthesize_scene(narration, audio_path, edge_voice, gate)
        # Keep audio/video/caption clocks identical — pad short clips instead of stretching words.
        duration = _pad_audio_to_duration(audio_path, max(_probe_duration(audio_path), 1.5))
        logger.info("Image scene %s (%d timed words, %.2fs)", order, len(words), duration)
        await asyncio.to_thread(generate_scene_image, prompt, title, order, image_path, gate)
        scene_audio_paths.append(audio_path)
        durations.append(duration)
        scene_images.append(image_path)
        scene_words.append(words)

    timed_words = _flatten_timed_words(scene_words, durations)

    narration_path = out_dir / ("demo_narration.mp3" if output_filename != "final.mp4" else "narration.mp3")
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
    # Re-encode can slightly change length — scale word clocks to the final narration.
    expected = sum(durations) or 1.0
    actual = max(_probe_duration(narration_path), 0.4)
    if abs(actual - expected) > 0.05:
        scale = actual / expected
        timed_words = [(word, start * scale, end * scale) for word, start, end in timed_words]
        logger.info(
            "Scaled caption timings by %.4f (expected=%.2fs actual=%.2fs)",
            scale,
            expected,
            actual,
        )

    srt_path = out_dir / "captions.srt"
    write_srt(timed_words, srt_path)

    video_path = out_dir / output_filename
    logger.info("Compositing %s for video %s", output_filename, video_id)
    render_video(scene_images, durations, narration_path, timed_words, video_path)

    thumb_path = out_dir / ("demo_thumb.png" if output_filename != "final.mp4" else "thumb.png")
    generate_thumbnail(scene_images[0], title, thumb_path)

    total_duration = _probe_duration(video_path)
    return {
        "voice_path": f"videos/{video_id}/{narration_path.name}",
        "video_path": f"videos/{video_id}/{output_filename}",
        "thumbnail_path": f"videos/{video_id}/{thumb_path.name}",
        "srt_path": f"videos/{video_id}/captions.srt",
        "duration_seconds": total_duration,
    }


def run_pipeline(
    video_id: int,
    title: str,
    scenes: list[dict],
    language: str | None = None,
    *,
    max_scenes: int | None = None,
    output_filename: str = "final.mp4",
) -> dict:
    return asyncio.run(
        build_video_assets(
            video_id,
            title,
            scenes,
            language,
            max_scenes=max_scenes,
            output_filename=output_filename,
        )
    )
