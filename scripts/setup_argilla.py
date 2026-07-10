"""Create the blinded Argilla dataset and the two annotator accounts."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import argilla as rg

DATA_DIR = Path(os.getenv("ARGILLA_DATA_DIR", "/workspace/data"))
PUBLIC_PATH = DATA_DIR / "public_items.jsonl"
API_URL = os.getenv("ARGILLA_API_URL", "http://localhost:6900")
API_KEY = os.getenv("ARGILLA_API_KEY", "argilla.apikey")
WORKSPACE = os.getenv("ARGILLA_WORKSPACE", "default")
DATASET_NAME = os.getenv("ARGILLA_DATASET", "ru-promptriever-human-audit")

FORBIDDEN_PUBLIC_KEYS = {
    "gold",
    "expected",
    "source_split",
    "split",
    "role",
    "passage_roles",
    "error_type",
    "negative_type",
    "matches_both",
    "generator",
    "private_manifest",
}


def wait_for_server() -> rg.Argilla:
    last_error: Exception | None = None
    for _ in range(60):
        try:
            client = rg.Argilla(api_url=API_URL, api_key=API_KEY)
            _ = client.me
            return client
        except Exception as exc:
            last_error = exc
            time.sleep(5)
    raise RuntimeError(f"Argilla did not become ready at {API_URL}: {last_error}")


def find_forbidden(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_PUBLIC_KEYS:
                return str(key)
            found = find_forbidden(nested)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = find_forbidden(nested)
            if found:
                return found
    return None


def load_items() -> tuple[list[dict[str, Any]], str]:
    if not PUBLIC_PATH.exists():
        raise FileNotFoundError(
            f"{PUBLIC_PATH} is missing. Vladimir must prepare public_items.jsonl before sharing the folder."
        )

    items: list[dict[str, Any]] = []
    for line_number, line in enumerate(PUBLIC_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or not item.get("item_id"):
            raise ValueError(f"Invalid item at line {line_number}: item_id is required")
        if find_forbidden(item):
            raise ValueError(f"Private key leaked into public item at line {line_number}")
        module_a = item.get("module_a") or {}
        module_b = item.get("module_b") or {}
        if not (module_a.get("audit_query") or module_a.get("rewritten_query")) or not (module_a.get("audit_passage") or module_a.get("rewritten_passage")):
            raise ValueError(f"{item['item_id']}: Module A fields are incomplete")
        if not module_b.get("query") or not module_b.get("instruction"):
            raise ValueError(f"{item['item_id']}: Module B query/instruction is incomplete")
        if len(module_b.get("passages") or []) != 4:
            raise ValueError(f"{item['item_id']}: exactly four Module B passages are required")
        items.append(item)

    if len(items) != 64:
        raise ValueError(f"Expected exactly 64 quality records, found {len(items)}")
    return items, hashlib.sha256(PUBLIC_PATH.read_bytes()).hexdigest()


def text_with_title(passage: dict[str, Any]) -> str:
    title = str(passage.get("title", "") or "").strip()
    text = str(passage.get("text", "") or "").strip()
    if title:
        return f"Заголовок: {title}\n\n{text}"
    return text


def argilla_settings(client: rg.Argilla) -> rg.Settings:
    binary_labels = {"yes": "Да", "no": "Нет"}
    role_labels = {
        "not_relevant": "1. Не отвечает на query",
        "query_only": "2. Отвечает на query, но нарушает instruction",
        "query_and_instruction": "3. Отвечает на query и удовлетворяет instruction",
    }
    fields = [
        rg.TextField(name="query", title="Query", required=True, client=client),
        rg.TextField(name="rewritten_passage", title="Положительный passage", required=True, client=client),
        rg.TextField(name="instruction", title="Instruction", required=True, client=client),
    ]
    fields.extend(
        rg.TextField(name=f"document_{index}", title=f"Документ {index}", required=True, client=client)
        for index in range(1, 5)
    )
    questions = [
        rg.LabelQuestion(
            name="query_acceptable",
            title="Query написан на понятном и приемлемом русском языке?",
            labels=binary_labels,
            required=True,
            client=client,
        ),
        rg.LabelQuestion(
            name="passage_acceptable",
            title="Положительный passage написан на понятном, связном русском языке?",
            labels=binary_labels,
            required=True,
            client=client,
        ),
    ]
    questions.extend(
        rg.LabelQuestion(
            name=f"document_{index}_role",
            title=f"Роль документа {index}",
            labels=role_labels,
            required=True,
            client=client,
        )
        for index in range(1, 5)
    )
    guidelines = """
Это слепой аудит синтетических данных ru-Promptriever.

Для каждого record:
1. Оцени query из итоговой записи: понятен ли он и пригоден ли как поисковый query.
2. Оцени положительный passage из итоговой записи: понятен ли он, написан ли связно и на русском языке.
3. Для каждого из четырёх документов выбери ровно одну роль:
   1 — документ не отвечает на query;
   2 — документ отвечает на query, но нарушает instruction;
   3 — документ отвечает на query и удовлетворяет instruction.

Порядок документов случайный. Не пытайся определить, какой документ был сгенерирован как positive или negative.
Не оценивай исходный машинный перевод и не проверяй сохранение смысла относительно исходного текста.
Не используй шкалу 1–5, вариант «неясно» или свободные комментарии.
Если ситуация спорная, выбери наиболее обоснованный вариант. Расхождения будут использованы для расчёта IAA.
"""
    return rg.Settings(
        guidelines=guidelines,
        fields=fields,
        questions=questions,
        distribution=rg.TaskDistribution(min_submitted=2),
    )


def ensure_user(client: rg.Argilla, username: str, password: str, workspace: Any) -> None:
    user = client.users(username)
    if user is None:
        user = rg.User(
            username=username,
            first_name=username.title(),
            role="annotator",
            password=password,
            client=client,
        )
        user.create()
        user = client.users(username)
    user.add_to_workspace(workspace)


def main() -> int:
    items, dataset_hash = load_items()
    client = wait_for_server()
    workspace = client.workspaces(WORKSPACE)

    ensure_user(
        client,
        "daria",
        os.getenv("ARGILLA_DARIA_PASSWORD", "password"),
        workspace,
    )
    ensure_user(
        client,
        "vladimir",
        os.getenv("ARGILLA_VLADIMIR_PASSWORD", "password"),
        workspace,
    )

    dataset = client.datasets(name=DATASET_NAME, workspace=WORKSPACE)
    if dataset is None:
        dataset = rg.Dataset(
            name=DATASET_NAME,
            workspace=WORKSPACE,
            settings=argilla_settings(client),
            client=client,
        )
        dataset.create()
        records = []
        for item in items:
            module_a = item["module_a"]
            module_b = item["module_b"]
            fields = {
                "query": module_a.get("audit_query", module_a.get("rewritten_query", "")),
                "rewritten_passage": text_with_title(
                    {
                        "title": module_a.get("audit_passage_title", module_a.get("rewritten_passage_title", "")),
                        "text": module_a.get("audit_passage", module_a.get("rewritten_passage", "")),
                    }
                ),
                "instruction": module_b["instruction"],
            }
            for index, passage in enumerate(module_b["passages"], 1):
                fields[f"document_{index}"] = text_with_title(passage)
            records.append({"id": item["item_id"], **fields})
        dataset.records.log(records)
        print(f"Created dataset {DATASET_NAME} with {len(records)} records.")
    else:
        existing = dataset.records.to_list()
        if len(existing) != len(items):
            raise RuntimeError(
                f"Dataset {DATASET_NAME} already exists with {len(existing)} records, expected {len(items)}. "
                "Do not replace a frozen dataset after annotation has started."
            )
        print(f"Dataset {DATASET_NAME} already exists; records were not duplicated.")

    (DATA_DIR / "argilla_dataset.json").write_text(
        json.dumps(
            {
                "dataset": DATASET_NAME,
                "workspace": WORKSPACE,
                "public_items": len(items),
                "public_dataset_hash": dataset_hash,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Open http://localhost:6900 and sign in as daria or vladimir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
