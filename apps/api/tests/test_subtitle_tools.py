from pathlib import Path

from app.services.subtitle_tools import (
    align_subtitle_cues,
    build_subtitle_export,
    render_subtitles,
)
from app.services.text_chunking import SubtitleCue


def test_align_subtitles_uses_overlap_and_keeps_single_line_without_secondary() -> None:
    primary = [SubtitleCue(0, 2000, "Hello"), SubtitleCue(2500, 4000, "World")]
    secondary = [SubtitleCue(100, 1900, "你好"), SubtitleCue(2500, 3900, "世界")]

    result = align_subtitle_cues(primary, secondary)

    assert [cue.text for cue in result] == ["Hello · 你好", "World · 世界"]
    assert [cue.text for cue in align_subtitle_cues(primary, [])] == ["Hello", "World"]


def test_render_subtitles_supports_structured_formats_and_timestamp_display() -> None:
    cues = [SubtitleCue(1000, 2500, "第一行\nsecond line")]

    assert "WEBVTT" in render_subtitles(cues, "vtt")
    assert "00:00:01,000 --> 00:00:02,500" in render_subtitles(cues, "srt")
    assert "[00:00:01.000]" in render_subtitles(cues, "txt", show_timestamps=True)
    assert '"start_ms": 1000' in render_subtitles(cues, "json")
    assert "Dialogue:" in render_subtitles(cues, "ass")


def test_bilingual_preview_text_does_not_insert_manual_line_breaks() -> None:
    cues = align_subtitle_cues(
        [SubtitleCue(0, 1000, "Hello")],
        [SubtitleCue(0, 1000, "你好")],
    )

    assert "\n" not in cues[0].text


def test_build_subtitle_export_reads_recorded_tracks_and_creates_bilingual_file(
    tmp_path: Path,
) -> None:
    base = "workspace/downloads/record/video"
    media_dir = tmp_path / base
    media_dir.mkdir(parents=True)
    (media_dir / "video.en.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello\n",
        encoding="utf-8",
    )
    (media_dir / "video.zh.vtt").write_text(
        "WEBVTT\n\n00:00:00.100 --> 00:00:01.900\n你好\n",
        encoding="utf-8",
    )

    export = build_subtitle_export(
        {
            "base": base,
            "subtitles": [
                {"lang": "en", "file": "video.en.vtt"},
                {"lang": "zh", "file": "video.zh.vtt"},
            ],
        },
        primary_lang="en",
        secondary_lang="zh",
        output_format="srt",
        media_root=str(tmp_path),
    )

    assert export.media_entry["bilingual"] is True
    assert export.filename.endswith("-and-zh-bilingual.srt")
    assert "Hello · 你好" in export.content
    assert "Hello\n你好" not in export.content
