"""A strict, JSON-safe subtitle timeline used by ASR and translation workers.

The timeline keeps cue timing and word timing separate.  Word timestamps are
only emitted when the provider actually returned them; this module never
interpolates a segment into invented per-word timings.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from app.services.text_chunking import SubtitleCue

_INLINE_TIMESTAMP = re.compile(r"<((?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3})>")


def clean_transcript_text(value: str) -> str:
    """Flatten a provider's text into one display flow without fake content."""

    cleaned = html.unescape(str(value or ""))
    cleaned = re.sub(r"<[^>]*>", "", cleaned)
    cleaned = re.sub(r"[\r\n]+", " ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    cleaned = re.sub(r"(?:^|\s)>>(?=\s|$)", " ", cleaned)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


@dataclass(frozen=True, slots=True)
class TimedWord:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class TimedSegment:
    text: str
    start_ms: int
    end_ms: int
    words: tuple[TimedWord, ...] = ()


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _milliseconds(value: Any, *, default: int = 0) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return max(0, int(round(number * 1000)))


def timeline_from_segments(
    segments: Iterable[Any], *, language: str | None = None
) -> tuple[list[TimedSegment], str | None]:
    """Convert faster-whisper-shaped segments into a validated timeline."""

    del language  # kept in the signature for provider-facing call symmetry
    result: list[TimedSegment] = []
    for raw_segment in segments:
        text = clean_transcript_text(str(_value(raw_segment, "text", "")))
        start_ms = _milliseconds(_value(raw_segment, "start", 0))
        end_ms = _milliseconds(_value(raw_segment, "end", 0))
        if not text or end_ms <= start_ms:
            continue

        raw_words = _value(raw_segment, "words", None) or ()
        words: list[TimedWord] = []
        for raw_word in raw_words:
            word_text = clean_transcript_text(str(_value(raw_word, "word", "")))
            word_start = max(start_ms, _milliseconds(_value(raw_word, "start", 0)))
            word_end = min(end_ms, _milliseconds(_value(raw_word, "end", 0)))
            if word_text and word_end > word_start:
                words.append(TimedWord(word_text, word_start, word_end))

        # Provider output can contain a word outside the segment or out of
        # order. Keep only monotonic words rather than presenting a misleading
        # karaoke highlight.
        monotonic: list[TimedWord] = []
        previous_end = start_ms
        for word in words:
            if word.start_ms < previous_end:
                continue
            monotonic.append(word)
            previous_end = word.end_ms
        result.append(
            TimedSegment(text, start_ms, end_ms, tuple(monotonic))
        )
    result.sort(key=lambda segment: (segment.start_ms, segment.end_ms))
    return result, None


def has_word_timestamps(raw_text: str) -> bool:
    """Return true only for an actual inline timestamp marker."""

    return bool(_INLINE_TIMESTAMP.search(html.unescape(raw_text)))


def _stamp(ms: int, separator: str = ".") -> str:
    total = max(0, int(ms))
    hours, remainder = divmod(total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _escape_vtt_text(value: str) -> str:
    return html.escape(clean_transcript_text(value), quote=False)


def render_word_timed_vtt(segments: Iterable[TimedSegment]) -> str:
    """Render a browser-readable VTT with exact provider word markers.

    Inline timestamp markers are intentionally kept in the VTT text. Native
    browser VTT renderers may display the raw cue text, while the application's
    custom parser consumes these markers for precise karaoke highlighting.
    """

    blocks: list[str] = []
    for segment in segments:
        if segment.words:
            text = "".join(
                f"<{_stamp(word.start_ms)}>{_escape_vtt_text(word.text)} "
                for word in segment.words
            ).rstrip()
        else:
            text = _escape_vtt_text(segment.text)
        if text:
            blocks.append(
                f"{_stamp(segment.start_ms)} --> {_stamp(segment.end_ms)}\n{text}"
            )
    return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def render_cue_vtt(cues: Iterable[SubtitleCue]) -> str:
    """Render a translated cue-level track with no invented word timing."""

    blocks = [
        f"{_stamp(cue.start_ms)} --> {_stamp(cue.end_ms)}\n{_escape_vtt_text(cue.text)}"
        for cue in cues
        if clean_transcript_text(cue.text)
    ]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def timeline_json(segments: Iterable[TimedSegment], *, language: str | None) -> str:
    payload = {
        "version": 1,
        "language": language,
        "word_timestamps": any(segment.words for segment in segments),
        "segments": [asdict(segment) for segment in segments],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
