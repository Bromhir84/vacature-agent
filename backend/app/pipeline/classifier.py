from __future__ import annotations

from typing import Any

from app.llm import chat_completion, parse_json_content
from app.schemas import ListingDraft


CLASSIFIER_SYSTEM = """You classify Dutch job vacancies for external staffing relevance.
Decide whether the vacancy is intended for detachering, inhuur, inlener, externe inhuur, interim, or zzp/freelance.
Reject permanent hire roles (vast dienstverband), stages, and unrelated uses of words like "externe auditor".

Respond with ONLY JSON:
{
  "is_external_staffing": boolean,
  "category": "detachering" | "inhuur" | "interim_zzp" | "unclear" | "not_external",
  "confidence": number between 0 and 1,
  "evidence": [short quotes from the text],
  "reason": "one sentence",
  "summary": "1-2 sentence neutral description of what the role/assignment is about (Dutch preferred). No nav chrome, no apply CTAs."
}
"""


def classify_listing(draft: ListingDraft, *, model: str | None = None) -> dict[str, Any]:
    user = (
        f"Title: {draft.title}\n"
        f"Employment type: {draft.employment_type or ''}\n"
        f"Location: {draft.location or ''}\n"
        f"URL: {draft.url}\n"
        f"Tags: {', '.join(draft.tags or [])}\n"
        f"Description:\n{(draft.description or draft.raw_snippet or '')[:6000]}"
    )
    response = chat_completion(
        [
            {"role": "system", "content": CLASSIFIER_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=800,
        json_mode=True,
        model=model,
    )
    content = response.choices[0].message.content
    data = parse_json_content(content)
    # Normalize fields
    conf = data.get("confidence")
    try:
        confidence = float(conf) if conf is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    summary = str(data.get("summary") or "").strip()
    return {
        "is_external_staffing": bool(data.get("is_external_staffing")),
        "category": str(data.get("category") or "unclear"),
        "confidence": confidence,
        "evidence": data.get("evidence") if isinstance(data.get("evidence"), list) else [],
        "reason": str(data.get("reason") or ""),
        "summary": summary[:400] if summary else "",
    }
