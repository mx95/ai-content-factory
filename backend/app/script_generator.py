import json
import logging
import re

from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, CursorAgentError

from app.config import settings
from app.schemas import GenerateScriptRequest

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def generate_script_payload(request: GenerateScriptRequest) -> dict:
    if settings.cursor_api_key:
        return _generate_with_cursor(request)
    return _generate_mock(request)


def _generate_with_cursor(request: GenerateScriptRequest) -> dict:
    prompt = f"""
You are the script writer for AI Content Factory.

Create a short vertical video script and reply with ONLY a JSON object.
Do not edit files, do not run tools, do not write markdown fences, and do not add commentary.

Topic: {request.topic}
Niche: {request.niche}
Language: {request.language}
Target duration: {request.duration_seconds} seconds

Required JSON shape:
{{
  "title": "...",
  "description": "...",
  "hashtags": ["#...", "#..."],
  "scenes": [
    {{"order": 1, "narration": "...", "visual_prompt": "..."}}
  ]
}}

Rules:
- Start with a strong hook.
- Use short spoken sentences in {request.language}.
- Make each visual_prompt specific enough for an image or video generator.
- End with a question or curiosity loop.
- Keep total spoken narration near {request.duration_seconds} seconds.
""".strip()

    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=settings.cursor_api_key,
                model=settings.cursor_model,
                name="acf-script-generator",
                cloud=CloudAgentOptions(),
            ),
        )
    except CursorAgentError as err:
        logger.exception("Cursor agent failed to start: %s", err.message)
        raise RuntimeError(f"Cursor agent startup failed: {err.message}") from err

    if result.status != "finished":
        raise RuntimeError(f"Cursor agent run failed with status={result.status}")

    if not result.result:
        raise RuntimeError("Cursor agent returned an empty result")

    return _parse_script_json(result.result)


def _parse_script_json(text: str) -> dict:
    candidate = text.strip()
    fence = _JSON_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    elif not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("Cursor agent response did not contain JSON")
        candidate = candidate[start : end + 1]

    payload = json.loads(candidate)
    for key in ("title", "description", "hashtags", "scenes"):
        if key not in payload:
            raise RuntimeError(f"Cursor agent JSON missing required key: {key}")
    return payload


def _generate_mock(request: GenerateScriptRequest) -> dict:
    clean_topic = request.topic.strip().rstrip("?")
    return {
        "title": f"Did You Know? {clean_topic}",
        "description": (
            f"A short AI-generated draft about {clean_topic}. "
            "Add a CURSOR_API_KEY to enable Cursor agent script generation."
        ),
        "hashtags": ["#DidYouKnow", "#AIFacts", "#Shorts"],
        "scenes": [
            {
                "order": 1,
                "narration": f"Did you know {clean_topic.lower()} has a story most people never hear?",
                "visual_prompt": f"Vertical cinematic opener about {clean_topic}, bold curiosity-driven mood",
            },
            {
                "order": 2,
                "narration": "The surprising part is not just the fact itself, but why it happens.",
                "visual_prompt": f"Detailed educational visual explaining {clean_topic}, clean high-contrast composition",
            },
            {
                "order": 3,
                "narration": "And once you notice it, you start seeing the pattern everywhere.",
                "visual_prompt": f"Fast-paced montage of examples related to {clean_topic}, vertical social video style",
            },
            {
                "order": 4,
                "narration": "What topic should we explain next?",
                "visual_prompt": "Comment prompt end screen, modern vertical video layout",
            },
        ],
    }
