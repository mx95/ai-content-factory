import json

from openai import OpenAI

from app.config import settings
from app.schemas import GenerateScriptRequest


def generate_script_payload(request: GenerateScriptRequest) -> dict:
    if settings.openai_api_key:
        return _generate_with_openai(request)
    return _generate_mock(request)


def _generate_with_openai(request: GenerateScriptRequest) -> dict:
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = f"""
Create a short vertical video script as strict JSON.

Topic: {request.topic}
Niche: {request.niche}
Language: {request.language}
Target duration: {request.duration_seconds} seconds

Return this shape:
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
- Use short spoken sentences.
- Make each visual_prompt specific enough for an image or video generator.
- End with a question or curiosity loop.
"""
    response = client.responses.create(
        model=settings.openai_model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    return json.loads(response.output_text)


def _generate_mock(request: GenerateScriptRequest) -> dict:
    clean_topic = request.topic.strip().rstrip("?")
    return {
        "title": f"Did You Know? {clean_topic}",
        "description": (
            f"A short AI-generated draft about {clean_topic}. "
            "Add an OpenAI API key to enable production-quality scripts."
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
