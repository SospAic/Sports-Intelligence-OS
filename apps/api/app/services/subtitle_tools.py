"""Safe subtitle parsing, alignment, preview and export helpers.

The platform adapter is responsible for obtaining *real* source tracks. This
module deliberately does not invent speech: it turns archived VTT/SRT tracks
into user-selected output formats and aligns a second track by cue overlap.
That separation makes a missing platform caption an explicit state instead of
silently presenting an estimate as a transcript.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.services.text_chunking import SubtitleCue, normalise_subtitle_text, parse_subtitle

SubtitleFormat = Literal["vtt", "srt", "txt", "json", "ass"]

MEDIA_ROOT = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")
MAX_SUBTITLE_BYTES = 8 * 1024 * 1024
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class SubtitleTrackData:
    requested_lang: str
    actual_lang: str
    file: str
    cues: list[SubtitleCue]


@dataclass(frozen=True, slots=True)
class SubtitleExport:
    filename: str
    content: str
    media_entry: dict[str, Any]
    primary_lang: str
    secondary_lang: str
    source_files: list[str]
    cues: list[SubtitleCue]
    show_timestamps: bool


def _safe_component(value: str, fallback: str = "subtitle") -> str:
    cleaned = _SAFE_COMPONENT.sub("-", value.strip()).strip(".-_")
    return cleaned[:80] or fallback


def _candidate_languages(value: str) -> set[str]:
    cleaned = value.strip()
    if not cleaned:
        return set()
    candidates = {cleaned.casefold()}
    # TikTok public tracks are persisted as ``und-auto`` so that manual and
    # automatic tracks remain distinguishable while the selector can still
    # address the public language as ``und``.
    if cleaned.casefold().endswith("-auto"):
        candidates.add(cleaned[:-5].casefold())
    if "." in cleaned:
        candidates.add(cleaned.split(".", 1)[0].casefold())
    if "-" in cleaned:
        candidates.add(cleaned.split("-", 1)[0].casefold())
    return candidates


def _recorded_path(base: str, filename: str, media_root: str) -> Path:
    root = Path(media_root).resolve()
    candidate = (root / base / filename).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("字幕文件路径越界")
    return candidate


def _read_subtitle_file(base: str, filename: str, media_root: str) -> str:
    path = _recorded_path(base, filename, media_root)
    if not path.is_file():
        raise FileNotFoundError(filename)
    if path.stat().st_size > MAX_SUBTITLE_BYTES:
        raise ValueError("字幕文件超过 8 MB 安全上限")
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("字幕文件编码无法识别")


def _media_tracks(media: dict[str, Any]) -> list[dict[str, str]]:
    tracks: list[dict[str, str]] = []
    for raw in media.get("subtitles") or []:
        if not isinstance(raw, dict):
            continue
        lang = str(raw.get("lang") or raw.get("language") or "").strip()
        filename = str(raw.get("file") or "").strip()
        if lang and filename:
            tracks.append({"lang": lang, "file": filename})
    return tracks


def _find_track(media: dict[str, Any], requested_lang: str) -> dict[str, str]:
    requested = requested_lang.strip()
    if not requested:
        raise ValueError("必须选择第一语言")
    requested_candidates = _candidate_languages(requested)
    tracks = _media_tracks(media)
    exact = [track for track in tracks if track["lang"].casefold() == requested.casefold()]
    matches = [
        track
        for track in tracks
        if _candidate_languages(track["lang"]) & requested_candidates
    ]
    selected = (exact or matches)
    if not selected:
        raise ValueError(f"未找到已归档的字幕轨道：{requested}")
    return selected[0]


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            result.append(cleaned)
    return result


def align_subtitle_cues(
    primary: list[SubtitleCue], secondary: list[SubtitleCue]
) -> list[SubtitleCue]:
    """Attach overlapping secondary cues to each primary cue.

    A small nearest-cue fallback handles tracks whose providers differ by a
    few hundred milliseconds. It is bounded to 1.2 seconds so unrelated
    sentences are never joined merely because they are nearby.
    """

    if not secondary:
        return list(primary)
    result: list[SubtitleCue] = []
    for cue in primary:
        overlapping = [
            other
            for other in secondary
            if other.end_ms > cue.start_ms and other.start_ms < cue.end_ms
        ]
        if not overlapping:
            nearest = min(
                secondary,
                key=lambda other: min(
                    abs(other.start_ms - cue.end_ms), abs(other.end_ms - cue.start_ms)
                ),
            )
            distance = min(abs(nearest.start_ms - cue.end_ms), abs(nearest.end_ms - cue.start_ms))
            if distance <= 1200:
                overlapping = [nearest]
        secondary_text = " · ".join(_unique_texts([other.text for other in overlapping]))
        text = cue.text if not secondary_text else f"{cue.text} · {secondary_text}"
        result.append(SubtitleCue(start_ms=cue.start_ms, end_ms=cue.end_ms, text=text))
    return result


def _stamp(ms: int, separator: str = ".") -> str:
    total = max(0, int(ms))
    hours, remainder = divmod(total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _display_text(cue: SubtitleCue, show_timestamps: bool) -> str:
    text = normalise_subtitle_text(cue.text)
    if not show_timestamps:
        return text
    return f"[{_stamp(cue.start_ms)}] {text}"


def render_subtitles(
    cues: list[SubtitleCue],
    output_format: SubtitleFormat,
    *,
    show_timestamps: bool = False,
) -> str:
    """Render a composed cue list while preserving structural timings."""

    if output_format == "txt":
        rendered = "\n\n".join(_display_text(cue, show_timestamps) for cue in cues)
        return rendered + ("\n" if cues else "")
    if output_format == "json":
        payload = [
            {
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "start": _stamp(cue.start_ms),
                "end": _stamp(cue.end_ms),
                "text": _display_text(cue, show_timestamps),
            }
            for cue in cues
        ]
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output_format == "vtt":
        blocks = [
            (
                f"{_stamp(cue.start_ms)} --> {_stamp(cue.end_ms)}\n"
                f"{_display_text(cue, show_timestamps)}"
            )
            for cue in cues
        ]
        return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")
    if output_format == "ass":
        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding"
            ),
            (
                "Style: Default,Arial,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
                "0,0,1,2,0,2,40,40,40,1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for cue in cues:
            text = (
                _display_text(cue, show_timestamps)
                .replace("\n", r"\N")
                .replace("{", "\\{")
                .replace("}", "\\}")
            )
            lines.append(
                f"Dialogue: 0,{_stamp(cue.start_ms)[:-1]},"
                f"{_stamp(cue.end_ms)[:-1]},Default,,0,0,0,,{text}"
            )
        return "\n".join(lines) + "\n"

    blocks = [
        (
            f"{index}\n{_stamp(cue.start_ms, ',')} --> "
            f"{_stamp(cue.end_ms, ',')}\n{_display_text(cue, show_timestamps)}"
        )
        for index, cue in enumerate(cues, 1)
    ]
    return "\n\n".join(blocks) + ("\n\n" if blocks else "")


def build_subtitle_export(
    media: dict[str, Any],
    *,
    primary_lang: str,
    secondary_lang: str = "",
    output_format: SubtitleFormat = "srt",
    show_timestamps: bool = False,
    media_root: str = MEDIA_ROOT,
) -> SubtitleExport:
    """Load recorded tracks and return a validated, rendered export."""

    base = str(media.get("base") or "").strip()
    if not base:
        raise ValueError("该记录没有可用的媒体目录")
    primary_track = _find_track(media, primary_lang)
    primary = SubtitleTrackData(
        requested_lang=primary_lang,
        actual_lang=primary_track["lang"],
        file=primary_track["file"],
        cues=parse_subtitle(_read_subtitle_file(base, primary_track["file"], media_root)),
    )
    if not primary.cues:
        raise ValueError(f"字幕轨道为空：{primary.actual_lang}")
    secondary: SubtitleTrackData | None = None
    if secondary_lang.strip():
        if secondary_lang.casefold() == primary.actual_lang.casefold():
            raise ValueError("第二语言不能与第一语言相同")
        secondary_track = _find_track(media, secondary_lang)
        secondary = SubtitleTrackData(
            requested_lang=secondary_lang,
            actual_lang=secondary_track["lang"],
            file=secondary_track["file"],
            cues=parse_subtitle(_read_subtitle_file(base, secondary_track["file"], media_root)),
        )
    cues = align_subtitle_cues(primary.cues, secondary.cues if secondary else [])
    stem = Path(primary.file).stem
    if secondary:
        stem = f"{stem}-and-{_safe_component(secondary.actual_lang)}-bilingual"
    filename = f"{_safe_component(stem)}.{output_format}"
    content = render_subtitles(cues, output_format, show_timestamps=show_timestamps)
    source_files = [primary.file] + ([secondary.file] if secondary else [])
    entry: dict[str, Any] = {
        "lang": (
            f"{primary.actual_lang}+{secondary.actual_lang}"
            if secondary
            else primary.actual_lang
        ),
        "file": filename,
        "format": output_format,
        "bilingual": bool(secondary),
        "show_timestamps": bool(show_timestamps),
        "source_files": source_files,
    }
    return SubtitleExport(
        filename=filename,
        content=content,
        media_entry=entry,
        primary_lang=primary.actual_lang,
        secondary_lang=secondary.actual_lang if secondary else "",
        source_files=source_files,
        cues=cues,
        show_timestamps=bool(show_timestamps),
    )


def write_subtitle_export(
    export: SubtitleExport,
    media: dict[str, Any],
    *,
    media_root: str = MEDIA_ROOT,
) -> Path:
    base = str(media.get("base") or "").strip()
    path = _recorded_path(base, export.filename, media_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export.content, encoding="utf-8")
    return path


def subtitle_preview(
    export: SubtitleExport,
    *,
    show_timestamps: bool | None = None,
    max_cues: int = 80,
) -> dict[str, Any]:
    cues = export.cues[:max_cues]
    timestamps = export.show_timestamps if show_timestamps is None else show_timestamps
    return {
        "primary_lang": export.primary_lang,
        "secondary_lang": export.secondary_lang,
        "format": Path(export.filename).suffix.lstrip("."),
        "show_timestamps": bool(timestamps),
        "cue_count": len(export.cues),
        "cues": [
            {
                "start_ms": cue.start_ms,
                "end_ms": cue.end_ms,
                "text": _display_text(cue, timestamps),
            }
            for cue in cues
        ],
        "rendered_text": render_subtitles(cues, "txt", show_timestamps=timestamps)[:24_000],
        "source_files": export.source_files,
        "generated_file": export.filename,
    }
