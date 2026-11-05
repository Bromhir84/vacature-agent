from __future__ import annotations

import html as html_lib
import re

from bs4 import BeautifulSoup

NAV_BOILERPLATE_RE = re.compile(
    r"(?i)\b("
    r"jouw interesse|veelgestelde vragen|arbeidsvoorwaarden|diversiteit\s*&\s*inclusie|"
    r"statushouders|participatiebanen|log in als medewerker|ga naar mijn persoonlijke|"
    r"vergelijkbare vacatures|cookie|privacyverklaring|alle rechten voorbehouden|"
    r"vacaturemailing|bewaar vacature|solliciteer direct"
    r")\b"
)

ROLE_HINT_RE = re.compile(
    r"(?i)\b("
    r"je (gaat|werkt|bouwt|ontwikkelt|bent|zoekt|draagt|helpt|speelt|realiseert)|"
    r"wij zoeken|voor deze (rol|opdracht|functie)|dit ga je doen|als .{0,40} (ben|speel|werk)|"
    r"opdracht|inhuur|detach|interim|zzp|freelance|platform|engineer|developer|consultant"
    r")\b"
)


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = value
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    out: list[str] = []
    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip(" •\t-")
        if len(cleaned) >= 40:
            out.append(cleaned)
    return out


def extract_listing_quote(
    *,
    title: str | None = None,
    description: str | None = None,
    raw_snippet: str | None = None,
    max_len: int = 280,
) -> str | None:
    """Pick a short, role-describing quote instead of nav/chrome first-text."""
    blobs = [strip_html(description), strip_html(raw_snippet)]
    text = " ".join(b for b in blobs if b).strip()
    if not text:
        return None

    # Drop obvious chrome prefixes (NS whole-page grabs start with the mega-menu).
    if NAV_BOILERPLATE_RE.search(text[:220]):
        # Try to jump to the first role-like sentence in the full text.
        sentences = _split_sentences(text)
    else:
        sentences = _split_sentences(text)

    title_l = (title or "").lower()
    scored: list[tuple[float, str]] = []
    for sentence in sentences:
        if NAV_BOILERPLATE_RE.search(sentence):
            continue
        if len(sentence) < 50:
            continue
        score = 0.0
        if ROLE_HINT_RE.search(sentence):
            score += 3.0
        if title_l and any(tok in sentence.lower() for tok in title_l.split() if len(tok) > 3):
            score += 1.5
        if 80 <= len(sentence) <= 320:
            score += 1.0
        if sentence.lower().startswith(("vacatures ", "jouw interesse", "contact ")):
            score -= 5.0
        scored.append((score, sentence))

    if not scored:
        # Last resort: trim cleaned text but skip leading chrome if possible.
        cleaned = text
        m = ROLE_HINT_RE.search(cleaned)
        if m and m.start() > 40:
            cleaned = cleaned[m.start() :]
        cleaned = cleaned[:max_len].rsplit(" ", 1)[0].strip()
        return cleaned or None

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    best = scored[0][1]
    if len(best) > max_len:
        best = best[:max_len].rsplit(" ", 1)[0].strip() + "…"
    return best


def summarize_with_fallback(
    *,
    title: str | None,
    description: str | None,
    raw_snippet: str | None,
    llm_summary: str | None = None,
) -> str | None:
    summary = strip_html(llm_summary)
    if summary and len(summary) >= 40 and not NAV_BOILERPLATE_RE.search(summary[:120]):
        return summary[:400]
    return extract_listing_quote(title=title, description=description, raw_snippet=raw_snippet)
