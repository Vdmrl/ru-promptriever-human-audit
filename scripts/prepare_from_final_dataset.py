"""Build the audit sample directly from the frozen final Parquet dataset.

The final dataset is the authoritative source for Module B. Module A is
therefore framed as acceptability of the shipped final query and positive
passage; the dataset does not preserve whether each only_query was the
original or the Stage-1 rewrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any


COLUMNS = [
    "query_id",
    "only_query",
    "only_instruction",
    "has_instruction",
    "positive_passages",
    "new_negatives",
    "is_repeated",
]


def read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=COLUMNS)
    return table.to_pylist()


def eligible(row: dict[str, Any]) -> bool:
    return bool(
        row.get("has_instruction")
        and not row.get("is_repeated")
        and row.get("only_query")
        and row.get("only_instruction")
        and row.get("positive_passages")
        and len(row.get("new_negatives") or []) == 3
    )


def reservoir_sample(paths: list[Path], target: int, rng: random.Random) -> list[dict[str, Any]]:
    reservoir: list[dict[str, Any]] = []
    seen = 0
    for path in paths:
        for row in read_parquet_rows(path):
            if not eligible(row):
                continue
            seen += 1
            if len(reservoir) < max(target * 20, 1000):
                reservoir.append(row)
                continue
            index = rng.randrange(seen)
            if index < len(reservoir):
                reservoir[index] = row
    if len(reservoir) < target:
        raise RuntimeError(f"{paths}: found only {len(reservoir)} eligible rows, need {target}")
    return rng.sample(reservoir, target)


def passage(value: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(value.get("title", "") or ""),
        "text": str(value.get("text", "") or ""),
    }


def shuffled_passages(row: dict[str, Any], seed: int) -> tuple[list[dict[str, str]], list[str]]:
    passages = [passage(row["positive_passages"][0])]
    passages.extend(passage(value) for value in row["new_negatives"])
    roles = ["positive", "negative", "negative", "negative"]
    digest = hashlib.sha256(f"{seed}:{row['query_id']}".encode()).digest()
    order = list(range(4))
    for index in range(3, 0, -1):
        swap = digest[index] % (index + 1)
        order[index], order[swap] = order[swap], order[index]
    return [passages[index] for index in order], [roles[index] for index in order]


def make_item(row: dict[str, Any], split: str, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    passages, roles = shuffled_passages(row, seed)
    public = {
        "item_id": f"final_{split}_{row['query_id']}",
        "module_a": {
            "audit_query": str(row["only_query"]),
            "audit_passage": passage(row["positive_passages"][0])["text"],
            "audit_passage_title": passage(row["positive_passages"][0])["title"],
        },
        "module_b": {
            "query": str(row["only_query"]),
            "instruction": str(row["only_instruction"]),
            "passages": passages,
        },
    }
    private = {
        "item_id": public["item_id"],
        "source_split": split,
        "source_query_id": str(row["query_id"]),
        "module_a": {
            "source": "final_dataset_only_query_and_positive_passage",
            "query_rewrite_status": "not_preserved_in_final_schema",
        },
        "module_b": {
            "passage_roles": roles,
            "negative_types": [
                str(value.get("explanation", "unknown"))
                for value in row["new_negatives"]
            ],
        },
    }
    return public, private


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-dir",
        default="data_preprocessing/data/output_final_dataset/data",
    )
    parser.add_argument("--out-dir", default="human_annotation/argilla/data")
    parser.add_argument("--seed", type=int, default=20260710)
    parser.add_argument("--train-n", type=int, default=60)
    parser.add_argument("--test-n", type=int, default=40)
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    train_paths = sorted(dataset_dir.glob("train-*.parquet"))
    test_paths = sorted(dataset_dir.glob("test-*.parquet"))
    if not train_paths or not test_paths:
        raise FileNotFoundError(f"Expected train-*.parquet and test-*.parquet in {dataset_dir}")

    train_rng = random.Random(args.seed)
    test_rng = random.Random(args.seed + 1)
    selected = [
        *[(row, "train") for row in reservoir_sample(train_paths, args.train_n, train_rng)],
        *[(row, "synthetic_test") for row in reservoir_sample(test_paths, args.test_n, test_rng)],
    ]
    random.Random(args.seed).shuffle(selected)

    public_items: list[dict[str, Any]] = []
    private_items: list[dict[str, Any]] = []
    for row, split in selected:
        public, private = make_item(row, split, args.seed)
        public_items.append(public)
        private_items.append(private)

    if len(public_items) != 100:
        raise RuntimeError(f"Expected 100 records, found {len(public_items)}")

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

    source_metadata = [
        {
            "path": str(path),
            "size": path.stat().st_size,
        }
        for path in [*train_paths, *test_paths]
    ]
    metadata = {
        "schema_version": 3,
        "seed": args.seed,
        "quality_requested": {"train": args.train_n, "synthetic_test": args.test_n},
        "quality_selected": {"train": args.train_n, "synthetic_test": args.test_n},
        "dataset_hash": dataset_hash,
        "source": "data_preprocessing/data/output_final_dataset/data",
        "source_files": source_metadata,
        "module_a_note": "Final dataset does not preserve original-vs-rewritten only_query status.",
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

