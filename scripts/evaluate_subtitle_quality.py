"""Evaluate an operator-provided subtitle reference set without model calls.

Input JSON:
[{"id": "sample-1", "reference": "...", "hypothesis": "...",
  "translation_reference": "...", "translation_hypothesis": "..."}]

The report labels missing references and never treats a mock/synthetic sample
as a production quality claim. BLEU is a lightweight diagnostic here; use a
reviewed COMET/metric implementation for release decisions.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def tokens(value: str) -> list[str]:
    return TOKEN_RE.findall(value.casefold())


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, ref_token in enumerate(reference, start=1):
        current = [row]
        for column, hyp_token in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_token != hyp_token),
                )
            )
        previous = current
    return previous[-1]


def sentence_bleu(reference: list[str], hypothesis: list[str]) -> float | None:
    if not reference or not hypothesis:
        return None
    precisions: list[float] = []
    for n in range(1, 5):
        ref_grams = Counter(tuple(reference[index : index + n]) for index in range(len(reference) - n + 1))
        hyp_grams = Counter(tuple(hypothesis[index : index + n]) for index in range(len(hypothesis) - n + 1))
        total = sum(hyp_grams.values())
        matched = sum(min(count, ref_grams[gram]) for gram, count in hyp_grams.items())
        precisions.append(matched / total if total else 0.0)
    if any(value == 0 for value in precisions):
        return 0.0
    brevity = 1.0 if len(hypothesis) >= len(reference) else math.exp(1 - len(reference) / len(hypothesis))
    return brevity * math.exp(sum(math.log(value) for value in precisions) / 4)


def evaluate(items: list[dict[str, Any]]) -> dict[str, Any]:
    wer_distance = 0
    wer_reference_tokens = 0
    bleu_values: list[float] = []
    missing_reference = 0
    missing_translation_reference = 0
    for item in items:
        reference = tokens(str(item.get("reference") or ""))
        hypothesis = tokens(str(item.get("hypothesis") or ""))
        if not reference:
            missing_reference += 1
        else:
            wer_distance += edit_distance(reference, hypothesis)
            wer_reference_tokens += len(reference)
        translation_reference = tokens(str(item.get("translation_reference") or ""))
        translation_hypothesis = tokens(str(item.get("translation_hypothesis") or ""))
        if not translation_reference:
            missing_translation_reference += 1
        else:
            score = sentence_bleu(translation_reference, translation_hypothesis)
            if score is not None:
                bleu_values.append(score)
    return {
        "dataset_kind": "operator_provided_reference_required",
        "sample_count": len(items),
        "transcription_token_error_rate": (
            wer_distance / wer_reference_tokens if wer_reference_tokens else None
        ),
        "translation_sentence_bleu_diagnostic": (
            sum(bleu_values) / len(bleu_values) if bleu_values else None
        ),
        "missing_reference_count": missing_reference,
        "missing_translation_reference_count": missing_translation_reference,
        "quality_claim_allowed": bool(items)
        and missing_reference == 0
        and missing_translation_reference == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise SystemExit("input must be a JSON array of sample objects")
    report = evaluate(payload)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
