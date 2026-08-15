from app.services.subtitle_timeline import (
    clean_transcript_text,
    render_word_timed_vtt,
    timeline_from_segments,
)


def test_timeline_keeps_provider_word_timestamps_without_interpolation() -> None:
    segments, _ = timeline_from_segments(
        [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "Hello world",
                "words": [
                    {"start": 0.0, "end": 0.7, "word": "Hello"},
                    {"start": 0.8, "end": 1.4, "word": "world"},
                ],
            }
        ]
    )

    assert len(segments) == 1
    assert [(word.text, word.start_ms, word.end_ms) for word in segments[0].words] == [
        ("Hello", 0, 700),
        ("world", 800, 1400),
    ]
    assert "<00:00:00.000>Hello" in render_word_timed_vtt(segments)


def test_invalid_or_overlapping_words_are_not_presented_as_exact() -> None:
    segments, _ = timeline_from_segments(
        [
            {
                "start": 1.0,
                "end": 2.0,
                "text": "one two",
                "words": [
                    {"start": 1.0, "end": 1.5, "word": "one"},
                    {"start": 1.4, "end": 1.9, "word": "two"},
                ],
            }
        ]
    )

    assert len(segments) == 1
    assert [word.text for word in segments[0].words] == ["one"]


def test_text_is_flattened_and_platform_marker_removed() -> None:
    assert clean_transcript_text("Hello\nworld &gt;&gt; again") == "Hello world again"
