from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from hashlib import sha256


class RuleParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSection:
    key: str
    parent_key: str | None
    title: str
    slug: str
    description: str | None
    sort_order: int


@dataclass
class ParsedRule:
    section_key: str
    key: str
    title: str
    rule_type: str
    instruction: str
    why: str | None = None
    how: str | None = None
    good_example: str | None = None
    bad_example: str | None = None
    qa_check: str | None = None
    rewrite_instruction: str | None = None
    priority: int = 50
    severity: str = "warning"
    is_mandatory: bool = False
    enabled: bool = True
    sports: list[str] = field(default_factory=list)
    story_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_reference: str | None = None
    source_status: str = "full"
    sort_order: int = 0

    @property
    def section_id(self) -> str:
        return self.section_key


@dataclass(frozen=True)
class ParsedRuleDocument:
    version: str
    source_text: str
    source_hash: str
    sections: list[ParsedSection]
    rules: list[ParsedRule]


_KERNEL = re.compile(r"^KERNEL\s+(\d+)\s+[—-]\s+(.+)$", re.IGNORECASE)
_PART = re.compile(r"^PART\s+(\d+)\s+[—-]\s+(.+)$", re.IGNORECASE)
_SUBSECTION = re.compile(r"^(\d+\.\d+[A-Z]?)\s+(.+)$")
_CALIBRATION = re.compile(r"^CALIBRATION\s+(\d+)\s+[—-]\s+(.+)$", re.IGNORECASE)
_TEST = re.compile(r"^TEST\s+(\d+)\s+[—-]\s+(.+)$", re.IGNORECASE)
_VERSION = re.compile(r"\bVersion\s+(\d+\.\d+[A-Z]?)\b", re.IGNORECASE)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return slug[:200] or "section"


def _rule_type(title: str, instruction: str, kind: str) -> str:
    text = f"{title} {instruction}".casefold()
    if kind in {"test", "calibration"} or " qa" in text or "checklist" in text:
        return "qa"
    if "ssml" in text:
        return "ssml"
    if any(token in text for token in ("tts", "voice", "prosody", "acoustic", "eleven")):
        return "tts"
    if "material search" in text or "footage search" in text:
        return "material_search"
    if "search keyword" in text:
        return "search_keyword"
    if "title" in text or "packaging" in text:
        return "title"
    if any(token in text for token in ("length", "character target", "size control")):
        return "length"
    if any(token in text for token in ("rewrite", "repair", "revision")):
        return "rewrite"
    if any(token in text for token in ("language", "lexicon", "metaphor", "american")):
        return "language"
    if any(token in text for token in ("research", "source", "evidence", "claim")):
        return "research"
    if any(token in text for token in ("truth", "fact", "canon", "verify")):
        return "fact_check"
    if any(token in text for token in ("qualif", "activation gate", "sufficiency gate")):
        return "qualification"
    if any(token in text for token in ("output", "deliverable", "format")):
        return "output"
    if any(token in text for token in ("structure", "pipeline", "sequence", "turn")):
        return "structure"
    if any(token in text for token in ("narrative", "hook", "reveal", "story", "climax")):
        return "narrative"
    return "principle"


def _label(text: str, *labels: str) -> str | None:
    alternatives = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:^|\n)(?:{alternatives})\s*:\s*(.+?)(?=\n[A-Z][A-Z /-]{{2,}}\s*:|\Z)",
        text,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else None


def _build_rule(
    *,
    section_key: str,
    key: str,
    title: str,
    instruction: str,
    kind: str,
    start_line: int,
    end_line: int,
    sort_order: int,
) -> ParsedRule:
    normalized = instruction.strip()
    rule_type = _rule_type(title, normalized, kind)
    upper = normalized.upper()
    mandatory = kind == "kernel" or any(
        marker in upper for marker in (" MUST ", " NEVER ", " REQUIRED", "LOCKED")
    )
    output_types: list[str] = []
    if rule_type == "tts":
        output_types.append("tts")
    elif rule_type == "ssml":
        output_types.append("ssml")
    elif rule_type == "title":
        output_types.append("title")
    elif rule_type == "search_keyword":
        output_types.append("search_keyword")
    elif rule_type == "material_search":
        output_types.append("material_search")
    qa_check = (
        normalized if kind in {"test", "calibration"} else _label(normalized, "QA", "QA CHECK")
    )
    return ParsedRule(
        section_key=section_key,
        key=key,
        title=title.strip()[:500],
        rule_type=rule_type,
        instruction=normalized,
        why=_label(normalized, "WHY"),
        how=_label(normalized, "HOW"),
        good_example=_label(normalized, "GOOD", "GOOD EXAMPLE"),
        bad_example=_label(normalized, "BAD", "BAD EXAMPLE", "FAIL"),
        qa_check=qa_check,
        rewrite_instruction=_label(normalized, "REWRITE", "REWRITE INSTRUCTION"),
        priority=100 if kind == "kernel" else 80 if mandatory else 50,
        severity="critical" if kind == "kernel" else "error" if mandatory else "warning",
        is_mandatory=mandatory,
        output_types=output_types,
        tags=["v7.9", kind, rule_type],
        source_reference=f"lines:{start_line}-{end_line}",
        sort_order=sort_order,
    )


def parse_v79_bytes(content: bytes) -> ParsedRuleDocument:
    if not content:
        raise RuleParseError("规则文件为空")
    if len(content) > 2_000_000:
        raise RuleParseError("规则文件超过 2 MB 安全上限")
    try:
        # Plain UTF-8 preserves a possible BOM as U+FEFF so exporting and re-encoding
        # reproduces the exact original bytes used for source_hash.
        source_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuleParseError("规则文件必须使用 UTF-8 编码") from exc
    if "ELITE SPORTS FACELESS NARRATION ENGINE" not in source_text:
        raise RuleParseError("文件不是可识别的 Elite Sports 规则文档")
    version_match = _VERSION.search(source_text[:2000])
    if version_match is None:
        raise RuleParseError("未找到规则版本标识")

    lines = source_text.splitlines()
    headings: list[tuple[int, str, str, str]] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if match := _KERNEL.match(line):
            headings.append((index, "kernel", match.group(1), match.group(2)))
        elif match := _PART.match(line):
            headings.append((index, "part", match.group(1), match.group(2)))
        elif match := _SUBSECTION.match(line):
            headings.append((index, "subsection", match.group(1), match.group(2)))
        elif match := _CALIBRATION.match(line):
            headings.append((index, "calibration", match.group(1), match.group(2)))
        elif match := _TEST.match(line):
            headings.append((index, "test", match.group(1), match.group(2)))
    if not headings:
        raise RuleParseError("规则文件中没有可解析章节")

    sections: list[ParsedSection] = [
        ParsedSection("preamble", None, "Document Preamble", "document-preamble", None, 0),
        ParsedSection("kernels", None, "Foundation Kernels", "foundation-kernels", None, 10),
    ]
    rules: list[ParsedRule] = []
    first_heading = headings[0][0]
    preamble = "\n".join(lines[:first_heading]).strip()
    if preamble:
        rules.append(
            _build_rule(
                section_key="preamble",
                key="document-preamble",
                title="Runtime identity and primary contract",
                instruction=preamble,
                kind="preamble",
                start_line=1,
                end_line=first_heading,
                sort_order=0,
            )
        )

    known_sections = {"preamble", "kernels"}
    current_part_key: str | None = None
    rule_order = 0
    for position, (line_index, kind, number, title) in enumerate(headings):
        end_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body_lines = lines[line_index + 1 : end_index]
        body = "\n".join(body_lines).strip()
        rule_order += 1
        if kind == "part":
            current_part_key = f"part-{int(number):02d}"
            if current_part_key not in known_sections:
                sections.append(
                    ParsedSection(
                        current_part_key,
                        None,
                        f"Part {number} — {title}",
                        f"part-{int(number):02d}-{slugify(title)}",
                        None,
                        100 + int(number),
                    )
                )
                known_sections.add(current_part_key)
            # A part heading can own prose before its first numbered subsection.
            if body:
                rules.append(
                    _build_rule(
                        section_key=current_part_key,
                        key=f"{current_part_key}-overview",
                        title=title,
                        instruction=body,
                        kind="part",
                        start_line=line_index + 1,
                        end_line=end_index,
                        sort_order=rule_order,
                    )
                )
            continue
        if kind == "subsection":
            part_number = number.split(".", maxsplit=1)[0]
            parent_key = f"part-{int(part_number):02d}"
            if parent_key not in known_sections:
                sections.append(
                    ParsedSection(
                        parent_key,
                        None,
                        f"Part {part_number}",
                        f"part-{int(part_number):02d}",
                        None,
                        100 + int(part_number),
                    )
                )
                known_sections.add(parent_key)
            section_key = f"section-{number.casefold().replace('.', '-')}"
            if section_key not in known_sections:
                sections.append(
                    ParsedSection(
                        section_key,
                        parent_key,
                        f"{number} {title}",
                        f"section-{number.casefold().replace('.', '-')}-{slugify(title)}",
                        None,
                        rule_order,
                    )
                )
                known_sections.add(section_key)
            rules.append(
                _build_rule(
                    section_key=section_key,
                    key=f"part-{number.casefold().replace('.', '-')}",
                    title=title,
                    instruction=body or title,
                    kind=kind,
                    start_line=line_index + 1,
                    end_line=end_index,
                    sort_order=rule_order,
                )
            )
            current_part_key = parent_key
            continue
        if kind == "kernel":
            section_key = "kernels"
            key = f"kernel-{int(number):02d}"
        else:
            section_key = current_part_key or "preamble"
            key = f"{kind}-{int(number):03d}"
        heading_detail = title
        instruction = body
        if kind in {"test", "calibration"}:
            # These entries frequently carry their complete test statement on the heading line.
            instruction = f"{heading_detail}\n{body}".strip()
            heading_detail = heading_detail.split("|", maxsplit=1)[0].strip()
        rules.append(
            _build_rule(
                section_key=section_key,
                key=key,
                title=heading_detail,
                instruction=instruction or title,
                kind=kind,
                start_line=line_index + 1,
                end_line=end_index,
                sort_order=rule_order,
            )
        )

    return ParsedRuleDocument(
        version=version_match.group(1),
        source_text=source_text,
        source_hash=sha256(content).hexdigest(),
        sections=sections,
        rules=rules,
    )
