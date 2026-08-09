"""Text preparation for local embedding: chunking plus subtitle parsing.

这一层刻意与 embedding 后端解耦——它只负责把 ``content_items`` 里的文本
（标题/描述/标签，以及未来的字幕、语音转写）切成适合嵌入的片段，不发起任何
网络请求，因此可以被纯单元测试完整覆盖。

CJK 注意事项
------------
中文没有空格分词，按 token 数估算长度不可靠，所以这里统一按**字符数**切分，
并优先在句末标点（。！？；等，含全角）处断句。ASCII 与 CJK 标点都要处理，
否则中英混排的体育解说文本会被拦腰截断。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: 句子边界：中英文终止标点 + 换行。保留标点本身（用 lookbehind 切分）。
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；!?;\n])")

#: WebVTT / SRT 时间轴行，同时兼容 ``.`` 与 ``,`` 作为毫秒分隔符，
#: 以及省略小时位的 ``MM:SS.mmm`` 写法。
_CUE_TIMING = re.compile(
    r"^\s*(?P<start>(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(?P<end>(?:\d{1,3}:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)

#: WebVTT 内联标签：``<c>``、``<v Speaker>``、``</c>``、逐字时间戳 ``<00:00:01.234>``。
_INLINE_TAG = re.compile(r"<[^>]*>")

#: SRT 序号行。
_CUE_INDEX = re.compile(r"^\s*\d+\s*$")

_WHITESPACE = re.compile(r"[ \t\u00a0]+")


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """One timed caption line."""

    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class TextChunk:
    """An embeddable fragment, optionally anchored to a time range."""

    text: str
    index: int
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def text_hash(self) -> str:
        return sha256_text(self.text)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalise_whitespace(value: str) -> str:
    """Collapse runs of spaces/tabs but keep paragraph breaks meaningful."""

    collapsed = _WHITESPACE.sub(" ", value.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [line.strip() for line in collapsed.split("\n")]
    return "\n".join(line for line in lines if line)


def build_meta_text(
    *,
    title: str | None,
    description: str | None,
    tags: Sequence[str] | None = None,
) -> str:
    """Compose the always-available text for a content item.

    标题放最前面：它信息密度最高，即使描述被截断，第一块也一定包含标题。
    """

    parts: list[str] = []
    if title:
        parts.append(title.strip())
    if description:
        parts.append(description.strip())
    if tags:
        cleaned = [tag.strip() for tag in tags if tag and tag.strip()]
        if cleaned:
            parts.append("标签：" + "、".join(cleaned))
    return normalise_whitespace("\n".join(part for part in parts if part))


def chunk_text(
    value: str,
    *,
    max_chars: int,
    overlap_chars: int = 0,
    max_chunks: int | None = None,
) -> list[TextChunk]:
    """Split ``value`` into overlapping, sentence-aligned chunks.

    切分策略：先按句子边界聚合到接近 ``max_chars``；单句本身超长时（比如没有
    标点的长串标签）再做硬切。``overlap_chars`` 让相邻块共享尾部文本，避免答案
    正好落在切口上而两块都召不回。
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be >= 0 and smaller than max_chars")

    text = normalise_whitespace(value)
    if not text:
        return []

    pieces = [piece for piece in _SENTENCE_BOUNDARY.split(text) if piece.strip()]
    if not pieces:
        return []

    raw_chunks: list[str] = []
    buffer = ""
    for piece in pieces:
        candidate = piece.strip()
        while len(candidate) > max_chars:
            # 无标点的超长片段：硬切，保证不会产出超过模型上下文的块。
            if buffer:
                raw_chunks.append(buffer.strip())
                buffer = ""
            raw_chunks.append(candidate[:max_chars])
            advance = max_chars - overlap_chars
            candidate = candidate[advance:]
        if not candidate:
            continue
        if not buffer:
            buffer = candidate
        elif len(buffer) + 1 + len(candidate) <= max_chars:
            buffer = f"{buffer} {candidate}"
        else:
            raw_chunks.append(buffer.strip())
            tail = buffer[-overlap_chars:] if overlap_chars else ""
            buffer = f"{tail} {candidate}".strip() if tail else candidate
    if buffer.strip():
        raw_chunks.append(buffer.strip())

    if max_chunks is not None:
        raw_chunks = raw_chunks[:max_chunks]
    return [TextChunk(text=chunk, index=index) for index, chunk in enumerate(raw_chunks)]


def parse_timestamp_ms(value: str) -> int:
    """Parse ``HH:MM:SS.mmm`` / ``MM:SS,mmm`` into milliseconds."""

    cleaned = value.strip().replace(",", ".")
    head, _, millis = cleaned.partition(".")
    segments = [int(part) for part in head.split(":")]
    while len(segments) < 3:
        segments.insert(0, 0)
    hours, minutes, seconds = segments[-3], segments[-2], segments[-1]
    total = ((hours * 60 + minutes) * 60 + seconds) * 1000
    if millis:
        total += int(millis.ljust(3, "0")[:3])
    return total


def parse_subtitle(content: str) -> list[SubtitleCue]:
    """Parse WebVTT or SRT text into cues.

    两种格式的差别只在毫秒分隔符和是否有序号行，统一用一个状态机处理即可。
    YouTube 自动字幕会把上一行滚动重复到下一条 cue，这里顺带去重，否则嵌入
    出来的块里全是重复句子，严重稀释语义。
    """

    cues: list[SubtitleCue] = []
    current: tuple[int, int] | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None:
            text = normalise_whitespace(" ".join(buffer))
            if text:
                cues.append(SubtitleCue(start_ms=current[0], end_ms=current[1], text=text))
        current = None
        buffer = []

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.upper().startswith("WEBVTT") or line.startswith(("NOTE", "STYLE", "REGION")):
            flush()
            continue
        match = _CUE_TIMING.match(line)
        if match:
            flush()
            current = (
                parse_timestamp_ms(match.group("start")),
                parse_timestamp_ms(match.group("end")),
            )
            continue
        if current is None:
            # 序号行或 cue 标识行，忽略。
            if _CUE_INDEX.match(line):
                continue
            continue
        stripped = _INLINE_TAG.sub("", line).strip()
        if stripped:
            buffer.append(stripped)
    flush()

    return _drop_rolling_duplicates(cues)


def _drop_rolling_duplicates(cues: Sequence[SubtitleCue]) -> list[SubtitleCue]:
    """Remove the rolling repetition typical of auto-generated captions."""

    result: list[SubtitleCue] = []
    for cue in cues:
        if result and cue.text == result[-1].text:
            previous = result[-1]
            result[-1] = SubtitleCue(
                start_ms=previous.start_ms,
                end_ms=max(previous.end_ms, cue.end_ms),
                text=previous.text,
            )
            continue
        if result and cue.text.startswith(result[-1].text) and len(result[-1].text) > 8:
            # 滚动字幕：后一条把前一条整句包含在开头，保留更完整的那条。
            previous = result[-1]
            result[-1] = SubtitleCue(
                start_ms=previous.start_ms,
                end_ms=cue.end_ms,
                text=cue.text,
            )
            continue
        result.append(cue)
    return result


def chunk_cues(
    cues: Iterable[SubtitleCue],
    *,
    max_chars: int,
    overlap_chars: int = 0,
    max_chunks: int | None = None,
) -> list[TextChunk]:
    """Group cues into chunks that keep their time range.

    时间区间是本地方案相对纯 LLM 摘要的核心优势：命中后可以直接把播放器
    seek 到 ``start_ms``，用户看到的是证据本身而不是模型的转述。
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be >= 0 and smaller than max_chars")

    chunks: list[TextChunk] = []
    buffer: list[SubtitleCue] = []
    length = 0
    #: buffer 里是否含有尚未被写出过的 cue。重叠模式下 flush 会把尾部 cue 留在
    #: buffer 里作为下一块的前缀，如果之后没有新 cue 进来，收尾时不能再写一遍。
    has_unemitted = False

    def flush() -> None:
        nonlocal buffer, length, has_unemitted
        if not buffer or not has_unemitted:
            return
        text = normalise_whitespace(" ".join(cue.text for cue in buffer))
        if text:
            chunks.append(
                TextChunk(
                    text=text,
                    index=len(chunks),
                    start_ms=buffer[0].start_ms,
                    end_ms=buffer[-1].end_ms,
                )
            )
        has_unemitted = False
        if not overlap_chars:
            buffer = []
            length = 0
            return
        tail: list[SubtitleCue] = []
        tail_length = 0
        for cue in reversed(buffer):
            if tail_length >= overlap_chars:
                break
            tail.insert(0, cue)
            tail_length += len(cue.text) + 1
        buffer = tail
        length = tail_length

    for cue in cues:
        cue_length = len(cue.text) + 1
        if buffer and length + cue_length > max_chars:
            flush()
            if max_chunks is not None and len(chunks) >= max_chunks:
                return chunks
        buffer.append(cue)
        length += cue_length
        has_unemitted = True
    flush()

    if max_chunks is not None:
        return chunks[:max_chunks]
    return chunks
