"""Export Argilla responses to analysis-friendly JSONL and CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

import argilla as rg

BINARY_QUESTION_NAMES = ["query_acceptable", "passage_acceptable"]
MAX_DOCUMENTS = 5
QUESTION_NAMES = BINARY_QUESTION_NAMES + [
    f"document_{index}_role" for index in range(1, MAX_DOCUMENTS + 1)
]


def scalar(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def response_parts(response: Any) -> tuple[str, str, Any]:
    user_id = str(getattr(response, "user_id", "") or "")
    status = str(getattr(response, "status", "") or "")
    value = scalar(getattr(response, "value", response))
    return user_id, status, value


def response_rows(record: Any) -> list[dict[str, Any]]:
    fields = getattr(record, "fields", {}) or {}
    document_count = sum(
        bool(str(fields.get(f"document_{index}", "") or "").strip())
        for index in range(1, MAX_DOCUMENTS + 1)
    )
    responses = getattr(record, "responses", {}) or {}
    grouped: dict[str, list[Any]] = {}
    if isinstance(responses, dict):
        for question, values in responses.items():
            if values is None:
                continue
            if not isinstance(values, (list, tuple)):
                values = [values]
            grouped[str(question)] = list(values)
    else:
        for response in responses:
            question = str(getattr(response, "question_name", "") or getattr(response, "question", ""))
            grouped.setdefault(question, []).append(response)

    by_user: dict[str, dict[str, Any]] = {}
    for question, values in grouped.items():
        for response in values:
            user_id, status, value = response_parts(response)
            key = user_id or "unknown-user"
            row = by_user.setdefault(
                key,
                {
                    "record_id": str(getattr(record, "id", "") or ""),
                    "user_id": user_id,
                    "responses": {},
                    "statuses": {},
                    "document_count": document_count,
                },
            )
            row["responses"][question] = value
            row["statuses"][question] = status
    return list(by_user.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="/workspace/data/exports")
    args = parser.parse_args()

    client = rg.Argilla(
        api_url=os.getenv("ARGILLA_API_URL", "http://localhost:6900"),
        api_key=os.getenv("ARGILLA_API_KEY", "argilla.apikey"),
    )
    dataset = client.datasets(
        name=os.getenv("ARGILLA_DATASET", "ru-promptriever-human-audit"),
        workspace=os.getenv("ARGILLA_WORKSPACE", "default"),
    )
    if dataset is None:
        raise RuntimeError("Dataset was not found. Run setup_argilla.py first.")

    users = {}
    for user in client.users:
        users[str(getattr(user, "id", ""))] = str(getattr(user, "username", ""))

    rows: list[dict[str, Any]] = []
    for record in dataset.records(with_responses=True):
        for row in response_rows(record):
            row["username"] = users.get(row["user_id"], row["user_id"])
            required_questions = [
                *BINARY_QUESTION_NAMES,
                *[
                    f"document_{index}_role"
                    for index in range(1, row["document_count"] + 1)
                ],
            ]
            row["completed"] = all(question in row["responses"] for question in required_questions)
            rows.append(row)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = Path("/workspace/data/sample_metadata.json")
    dataset_hash = ""
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        dataset_hash = metadata.get("dataset_hash", "")
    for row in rows:
        row["dataset_hash"] = dataset_hash

    json_path = output_dir / "annotations.jsonl"
    with json_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    csv_path = output_dir / "annotations.csv"
    columns = [
        "record_id",
        "username",
        "user_id",
        "completed",
        "document_count",
        "dataset_hash",
        *QUESTION_NAMES,
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            flat = {
                "record_id": row["record_id"],
                "username": row["username"],
                "user_id": row["user_id"],
                "completed": row["completed"],
                "document_count": row["document_count"],
                "dataset_hash": row["dataset_hash"],
                **row["responses"],
            }
            writer.writerow(flat)

    print(f"Exported {len(rows)} annotator-record rows to {json_path} and {csv_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
