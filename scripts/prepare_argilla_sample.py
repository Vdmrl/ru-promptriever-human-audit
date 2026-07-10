"""Prepare the frozen, blinded 64-record sample for Argilla.

This script deliberately emits two artifacts:
- public_items.jsonl: safe to give to annotators;
- private_manifest.jsonl: keep locally for metric calculation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable


def input_paths(value: str) -> list[Path]:
    path = Path(value)
    if path.is_dir():
        return sorted(path.glob("*.jsonl"))
    return [path]


def records(values: Iterable[str]) -> Iterable[dict[str, Any]]:
    for value in values:
        for path in input_paths(value):
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError(f"{path}:{line_number} is not a JSON object")
                    yield item


def text_doc(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"title": "", "text": ""}
    return {
        "title": str(value.get("title", "") or ""),
        "text": str(value.get("text", value.get("passage", "")) or ""),
    }


def first_nonempty(*values: Any) -> dict[str, str]:
    for value in values:
        doc = text_doc(value)
        if doc["text"].strip():
            return doc
    return {"title": "", "text": ""}


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def extract_candidate(record: dict[str, Any], split: str) -> dict[str, Any] | None:
    data = record.get("instruction_data") or {}
    mining = record.get("mining_data") or {}

    query_id = first_text(record.get("query_id"), record.get("id"))
    query = first_text(
        data.get("rewritten_query"),
        record.get("rewritten_query"),
        record.get("only_query"),
        record.get("query"),
    )
    instruction = first_text(
        data.get("instruction"),
        record.get("instruction"),
        record.get("only_instruction"),
    )
    stage1_positive = first_nonempty(
        {"title": data.get("rewritten_pos_title"), "text": data.get("rewritten_pos_doc")},
        record.get("rewritten_original_positive"),
        record.get("rewritten_pos_doc"),
    )
    stage1_negative = first_nonempty(
        {"title": data.get("rewritten_neg_title"), "text": data.get("rewritten_neg_doc")},
        record.get("rewritten_original_negative"),
        record.get("rewritten_neg_doc"),
    )

    final_positive = first_nonempty(
        record.get("final_positive"),
        stage1_positive,
    )

    negatives: list[dict[str, str]] = []
    negative_types: list[str] = []
    for value in record.get("valid_synthetic_negatives") or []:
        doc = text_doc(value)
        if doc["text"].strip():
            negatives.append(doc)
            negative_types.append(str(value.get("error_type", "unknown")))
    if len(negatives) < 3:
        negatives = []
        negative_types = []
        for value in mining.get("documents", []) or []:
            if isinstance(value, dict) and value.get("matches_both", False):
                continue
            doc = text_doc(value)
            if doc["text"].strip():
                negatives.append(doc)
                negative_types.append(str(value.get("error_type", "unknown")))
    negatives = negatives[:3]
    negative_types = negative_types[:3]

    if not query_id or not query or not instruction:
        return None
    if not stage1_positive["text"].strip() or not stage1_negative["text"].strip():
        return None
    if not final_positive["text"].strip() or len(negatives) != 3:
        return None

    return {
        "item_id": f"quality_{split}_{query_id}",
        "query_id": query_id,
        "split": split,
        "query": query,
        "instruction": instruction,
        "stage1_positive": stage1_positive,
        "stage1_negative": stage1_negative,
        "final_positive": final_positive,
        "negatives": negatives,
        "negative_types": negative_types,
    }


def shuffled_passages(candidate: dict[str, Any], seed: int) -> tuple[list[dict[str, str]], list[str]]:
    passages = [candidate["final_positive"], *candidate["negatives"]]
    roles = ["positive", "negative", "negative", "negative"]
    digest = hashlib.sha256(f"{seed}:{candidate['item_id']}".encode()).digest()
    order = list(range(4))
    for index in range(3, 0, -1):
        swap = digest[index] % (index + 1)
        order[index], order[swap] = order[swap], order[index]
    return [passages[index] for index in order], [roles[index] for index in order]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-input", action="append", default=[])
    parser.add_argument("--test-input", action="append", default=[])
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--out-dir", default="human_annotation/argilla/data")
    parser.add_argument("--seed", type=int, default=20260710)
    parser.add_argument("--train-n", type=int, default=40)
    parser.add_argument("--test-n", type=int, default=24)
    parser.add_argument("--expected-total", type=int, default=64, help="Production value is 64; smaller values are only for smoke tests.")
    args = parser.parse_args()

    candidates: dict[str, list[dict[str, Any]]] = {"train": [], "test": []}
    seen: set[str] = set()

    for value in args.train_input:
        for record in records([value]):
            candidate = extract_candidate(record, "train")
            if candidate and candidate["item_id"] not in seen:
                candidates["train"].append(candidate)
                seen.add(candidate["item_id"])
    for value in args.test_input:
        for record in records([value]):
            candidate = extract_candidate(record, "synthetic_test")
            if candidate and candidate["item_id"] not in seen:
                candidates["test"].append(candidate)
                seen.add(candidate["item_id"])
    for value in args.input:
        for record in records([value]):
            split = str(record.get("split", "")).lower()
            bucket = "test" if split in {"test", "synthetic_test"} else "train"
            candidate = extract_candidate(record, "synthetic_test" if bucket == "test" else "train")
            if candidate and candidate["item_id"] not in seen:
                candidates[bucket].append(candidate)
                seen.add(candidate["item_id"])

    rng = random.Random(args.seed)
    for values in candidates.values():
        rng.shuffle(values)

    train = candidates["train"][: args.train_n]
    test = candidates["test"][: args.test_n]
    if len(train) != args.train_n or len(test) != args.test_n:
        raise SystemExit(
            f"Frozen sample is incomplete: train={len(train)}/{args.train_n}, "
            f"synthetic_test={len(test)}/{args.test_n}. "
            "Check that every record has both Stage-1 passages and exactly three final negatives."
        )

    selected = train + test
    rng.shuffle(selected)
    if args.expected_total % 2 != 0:
        raise SystemExit("expected-total must be even so Stage-1 passage roles can be balanced.")
    if len(selected) != args.expected_total or args.train_n + args.test_n != args.expected_total:
        raise SystemExit(f"This audit package requires exactly {args.expected_total} records.")

    public_items: list[dict[str, Any]] = []
    private_items: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        stage1_role = "positive" if index < args.expected_total // 2 else "negative"
        stage1_passage = (
            candidate["stage1_positive"]
            if stage1_role == "positive"
            else candidate["stage1_negative"]
        )
        passages, passage_roles = shuffled_passages(candidate, args.seed)
        public_items.append(
            {
                "item_id": candidate["item_id"],
                "module_a": {
                    "rewritten_query": candidate["query"],
                    "rewritten_passage": stage1_passage["text"],
                    "rewritten_passage_title": stage1_passage["title"],
                },
                "module_b": {
                    "query": candidate["query"],
                    "instruction": candidate["instruction"],
                    "passages": passages,
                },
            }
        )
        private_items.append(
            {
                "item_id": candidate["item_id"],
                "source_split": candidate["split"],
                "query_id": candidate["query_id"],
                "module_a": {"passage_role": stage1_role},
                "module_b": {
                    "passage_roles": passage_roles,
                    "negative_types": candidate["negative_types"],
                },
            }
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    public_path = out_dir / "public_items.jsonl"
    private_path = out_dir / "private_manifest.jsonl"
    with public_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in public_items:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    dataset_hash = hashlib.sha256(public_path.read_bytes()).hexdigest()
    with private_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in private_items:
            item["dataset_hash"] = dataset_hash
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    metadata = {
        "schema_version": 2,
        "seed": args.seed,
        "quality_requested": {"train": args.train_n, "synthetic_test": args.test_n},
        "quality_selected": {"train": len(train), "synthetic_test": len(test)},
        "stage1_passage_roles": {
            "positive": args.expected_total // 2,
            "negative": args.expected_total // 2,
        },
        "dataset_hash": dataset_hash,
        "warning": "Keep private_manifest.jsonl out of the annotator package.",
    }
    (out_dir / "sample_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
