from types import SimpleNamespace

import pytest

from app.providers.transcription import faster_whisper
from app.providers.transcription.faster_whisper import (
    FasterWhisperTranscriber,
    TranscriptionUnavailable,
)


def test_transcriber_requires_optional_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def missing_model(*args, **kwargs):
        raise TranscriptionUnavailable("missing")

    monkeypatch.setattr(faster_whisper, "_load_model", missing_model)
    transcriber = FasterWhisperTranscriber(
        model="small",
        device="cpu",
        compute_type="int8",
        model_dir=str(tmp_path),
    )
    with pytest.raises(TranscriptionUnavailable):
        transcriber.transcribe("missing.mp4")


def test_provider_maps_word_timed_segments(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FakeModel:
        def transcribe(self, *args, **kwargs):
            assert kwargs["word_timestamps"] is True
            return iter(
                [
                    SimpleNamespace(
                        start=0.0,
                        end=1.0,
                        text="hello world",
                        words=[
                            SimpleNamespace(start=0.0, end=0.4, word="hello"),
                            SimpleNamespace(start=0.5, end=0.9, word="world"),
                        ],
                    )
                ]
            ), SimpleNamespace(language="en", language_probability=0.99, duration=1.0)

    monkeypatch.setattr(faster_whisper, "_load_model", lambda *args, **kwargs: FakeModel())
    result = FasterWhisperTranscriber(
        model="small",
        device="cpu",
        compute_type="int8",
        model_dir=str(tmp_path),
    ).transcribe("test.mp4")

    assert result.language == "en"
    assert [word.text for word in result.segments[0].words] == ["hello", "world"]
