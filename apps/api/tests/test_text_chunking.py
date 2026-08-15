"""Chunking and subtitle parsing for local semantic search.

Pure-function checks (no DB / network / model) so they run in the default CI
slice. These guard the two properties that decide retrieval quality: chunks
must stay inside the size budget, and subtitle chunks must keep an accurate
time range so a hit can seek the player to the evidence.
"""

import pytest

from app.services.text_chunking import (
    SubtitleCue,
    build_meta_text,
    chunk_cues,
    chunk_text,
    normalise_subtitle_text,
    normalise_whitespace,
    parse_subtitle,
    parse_timestamp_ms,
    sha256_text,
)

# --- normalise_whitespace --------------------------------------------------


def test_normalise_whitespace_collapses_runs_and_drops_blank_lines():
    assert normalise_whitespace("a   b\t\tc") == "a b c"
    assert normalise_whitespace("line1\n\n\n  line2  ") == "line1\nline2"
    assert normalise_whitespace("\r\nwin\r\nlines\r\n") == "win\nlines"


def test_normalise_whitespace_handles_nbsp():
    assert normalise_whitespace("\u00a0排球\u00a0世界\u00a0") == "排球 世界"


def test_normalise_subtitle_text_flattens_entities_and_youtube_marker():
    source = "What's happening? &gt;&gt; In\n<c>the middle</c>"
    assert normalise_subtitle_text(source) == "What's happening? In the middle"


# --- build_meta_text -------------------------------------------------------


def test_build_meta_text_puts_title_first():
    text = build_meta_text(
        title="女排世联赛决赛集锦",
        description="中国队对阵巴西队的完整回放。",
        tags=["排球", "世联赛"],
    )
    assert text.startswith("女排世联赛决赛集锦")
    assert "标签：排球、世联赛" in text


def test_build_meta_text_tolerates_missing_fields():
    assert build_meta_text(title="只有标题", description=None, tags=None) == "只有标题"
    assert build_meta_text(title=None, description=None, tags=[]) == ""
    # 空白标签不应产出一个孤零零的 "标签：" 行。
    assert build_meta_text(title="T", description=None, tags=["", "  "]) == "T"


# --- chunk_text ------------------------------------------------------------


def test_chunk_text_respects_max_chars():
    body = "。".join(f"第{i}句内容" for i in range(60)) + "。"
    chunks = chunk_text(body, max_chars=100, overlap_chars=0)
    assert chunks, "long text must produce chunks"
    assert all(len(chunk.text) <= 100 for chunk in chunks)


def test_chunk_text_splits_on_sentence_boundaries():
    chunks = chunk_text("第一句。第二句。第三句。", max_chars=8, overlap_chars=0)
    # 每块都应以句号收尾，而不是把句子拦腰截断。
    assert [chunk.text for chunk in chunks] == ["第一句。", "第二句。", "第三句。"]


def test_chunk_text_hard_splits_text_without_punctuation():
    # 无标点长串（例如连写的标签）必须被硬切，否则会超出模型上下文。
    chunks = chunk_text("A" * 250, max_chars=100, overlap_chars=0)
    assert [len(chunk.text) for chunk in chunks] == [100, 100, 50]


def test_chunk_text_overlap_shares_tail():
    chunks = chunk_text("第一句。第二句。第三句。第四句。", max_chars=10, overlap_chars=4)
    assert len(chunks) >= 2
    # 相邻块之间有共享文本，避免答案正好落在切口上而两块都召不回。
    assert any(chunks[0].text[-2:] in chunks[1].text for _ in [0])


def test_chunk_text_indexes_are_sequential():
    chunks = chunk_text("句子。" * 40, max_chars=30, overlap_chars=0)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_text_respects_max_chunks():
    chunks = chunk_text("句子。" * 200, max_chars=30, overlap_chars=0, max_chunks=3)
    assert len(chunks) == 3


def test_chunk_text_empty_input_returns_no_chunks():
    assert chunk_text("", max_chars=100) == []
    assert chunk_text("   \n  ", max_chars=100) == []


def test_chunk_text_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("x", max_chars=10, overlap_chars=10)


def test_text_chunk_hash_is_stable():
    chunk = chunk_text("稳定文本。", max_chars=100)[0]
    assert chunk.text_hash == sha256_text("稳定文本。")


# --- parse_timestamp_ms ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00:01.000", 1_000),
        ("00:01:02.500", 62_500),
        ("01:00:00.000", 3_600_000),
        ("00:00:01,250", 1_250),  # SRT 用逗号
        ("02:03.400", 123_400),  # 省略小时位
        ("00:00:00.05", 50),  # 毫秒不足三位
    ],
)
def test_parse_timestamp_ms(raw, expected):
    assert parse_timestamp_ms(raw) == expected


# --- parse_subtitle --------------------------------------------------------


WEBVTT = """WEBVTT

NOTE this is a comment

00:00:01.000 --> 00:00:03.000
<v Speaker>中国队<c> 发球</c>得分

00:00:03.000 --> 00:00:06.500
巴西队请求暂停
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
中国队发球得分

2
00:00:03,000 --> 00:00:06,500
巴西队请求暂停
"""


def test_parse_subtitle_webvtt_strips_inline_tags():
    cues = parse_subtitle(WEBVTT)
    assert len(cues) == 2
    assert cues[0] == SubtitleCue(start_ms=1_000, end_ms=3_000, text="中国队 发球得分")
    assert cues[1].start_ms == 3_000
    assert cues[1].end_ms == 6_500


def test_parse_subtitle_srt_ignores_index_lines():
    cues = parse_subtitle(SRT)
    assert [cue.text for cue in cues] == ["中国队发球得分", "巴西队请求暂停"]
    assert cues[0].start_ms == 1_000


def test_parse_subtitle_merges_identical_rolling_cues():
    rolling = """WEBVTT

00:00:01.000 --> 00:00:02.000
同一句话

00:00:02.000 --> 00:00:04.000
同一句话
"""
    cues = parse_subtitle(rolling)
    assert len(cues) == 1
    # 合并后时间区间必须覆盖两条 cue，否则跳转会落在句子中间。
    assert cues[0].start_ms == 1_000
    assert cues[0].end_ms == 4_000


def test_parse_subtitle_collapses_youtube_style_growing_cues():
    growing = """WEBVTT

00:00:01.000 --> 00:00:02.000
这是一段比较长的解说

00:00:02.000 --> 00:00:04.000
这是一段比较长的解说词继续
"""
    cues = parse_subtitle(growing)
    assert len(cues) == 1
    assert cues[0].text == "这是一段比较长的解说词继续"
    assert cues[0].start_ms == 1_000


def test_parse_subtitle_empty_content():
    assert parse_subtitle("") == []
    assert parse_subtitle("WEBVTT\n\n") == []


# --- chunk_cues ------------------------------------------------------------


def _cues(count: int, *, text: str = "解说词") -> list[SubtitleCue]:
    return [
        SubtitleCue(start_ms=i * 1_000, end_ms=(i + 1) * 1_000, text=f"{text}{i}")
        for i in range(count)
    ]


def test_chunk_cues_keeps_time_range():
    chunks = chunk_cues(_cues(10), max_chars=40, overlap_chars=0)
    assert chunks
    assert chunks[0].start_ms == 0
    assert chunks[-1].end_ms == 10_000
    for chunk in chunks:
        assert chunk.start_ms is not None and chunk.end_ms is not None
        assert chunk.start_ms < chunk.end_ms


def test_chunk_cues_respects_max_chars():
    chunks = chunk_cues(_cues(50), max_chars=60, overlap_chars=0)
    assert all(len(chunk.text) <= 60 for chunk in chunks)


def test_chunk_cues_does_not_emit_trailing_overlap_duplicate():
    # 带重叠时，收尾不能把上一块的尾部再单独写出一块。
    chunks = chunk_cues(_cues(9), max_chars=40, overlap_chars=15)
    texts = [chunk.text for chunk in chunks]
    assert len(texts) == len(set(texts)), f"duplicate chunk emitted: {texts}"


def test_chunk_cues_indexes_are_sequential():
    chunks = chunk_cues(_cues(20), max_chars=40, overlap_chars=0)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_cues_empty_input():
    assert chunk_cues([], max_chars=100) == []


def test_chunk_cues_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_cues(_cues(2), max_chars=10, overlap_chars=10)
