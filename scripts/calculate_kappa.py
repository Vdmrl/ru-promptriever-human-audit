"""Calculate the pre-declared metrics for the frozen human-audit sample.

The script accepts one combined Argilla export or two per-annotator JSONL
files. It uses only the frozen private manifest for expected document roles;
annotations remain independent and are never adjudicated.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

BINARY_QUESTIONS = ("query_acceptable", "passage_acceptable")
ROLE_QUESTIONS = tuple(f"document_{i}_role" for i in range(1, 5))
ALL_QUESTIONS = BINARY_QUESTIONS + ROLE_QUESTIONS


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    manifest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            manifest[row["item_id"]] = row
    if not manifest:
        raise ValueError(f"Manifest is empty: {path}")
    for item_id, row in manifest.items():
        roles = row.get("module_b", {}).get("passage_roles", [])
        if len(roles) != 4 or roles.count("positive") != 1 or roles.count("negative") != 3:
            raise ValueError(f"Invalid frozen role metadata for {item_id}: {roles}")
    return manifest


def read_rows(path: Path, forced_username: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            username = forced_username or row.get("username")
            if not username:
                raise ValueError(f"No username in {path} for {row.get('record_id')}")
            row["username"] = str(username)
            rows.append(row)
    return rows


def load_annotations(
    combined: Path | None,
    vladimir: Path | None,
    daria: Path | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    if combined:
        rows.extend(read_rows(combined))
    if vladimir:
        rows.extend(read_rows(vladimir, "vladimir"))
    if daria:
        rows.extend(read_rows(daria, "daria"))
    if not rows:
        raise ValueError("Provide --input or --vladimir and --daria")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        username = row["username"]
        record_id = str(row["record_id"])
        if record_id in result.setdefault(username, {}):
            raise ValueError(f"Duplicate annotation for {username}/{record_id}")
        result[username][record_id] = row
    return result


def completed(rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        record_id: row
        for record_id, row in rows.items()
        if row.get("completed") and all(q in row.get("responses", {}) for q in ALL_QUESTIONS)
    }


def expected_roles(row: dict[str, Any]) -> list[str]:
    return [
        "query_and_instruction" if role == "positive" else "query_only"
        for role in row["module_b"]["passage_roles"]
    ]


def proportion(values: Iterable[bool]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def nominal_kappa(left: list[Any], right: list[Any]) -> float | None:
    if not left or len(left) != len(right):
        return None
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    left_counts, right_counts = Counter(left), Counter(right)
    expected = sum(
        left_counts[label] * right_counts[label]
        for label in set(left_counts) | set(right_counts)
    ) / (len(left) * len(left))
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def agreement(left: list[Any], right: list[Any]) -> dict[str, Any]:
    return {
        "n": len(left),
        "exact_agreement": proportion(a == b for a, b in zip(left, right)),
        "cohen_kappa": nominal_kappa(left, right),
    }


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def ci(values: Iterable[float | None]) -> list[float | None]:
    usable = [float(value) for value in values if value is not None]
    return [percentile(usable, 0.025), percentile(usable, 0.975)]


def record_metrics(
    rows: dict[str, dict[str, Any]], manifest: dict[str, dict[str, Any]], ids: list[str]
) -> dict[str, Any]:
    query = []
    passage = []
    positive = []
    negatives = []
    strict = []
    role_values = []
    by_role: dict[str, dict[str, list[bool]]] = {
        "positive": {"topical_relevance": [], "full_compliance": []},
        "instruction_negative": {"topical_relevance": [], "full_compliance": []},
    }
    by_negative_type: dict[str, dict[str, list[bool]]] = {}
    for item_id in ids:
        response = rows[item_id]["responses"]
        query.append(response["query_acceptable"] == "yes")
        passage.append(response["passage_acceptable"] == "yes")
        expected = expected_roles(manifest[item_id])
        actual = [response[question] for question in ROLE_QUESTIONS]
        role_values.extend(actual)
        positive_index = expected.index("query_and_instruction")
        positive.append(actual[positive_index] == "query_and_instruction")
        negatives.extend(
            actual[index] == "query_only"
            for index, role in enumerate(expected)
            if role == "query_only"
        )
        strict.append(all(actual[index] == expected[index] for index in range(4)))
        private_roles = manifest[item_id]["module_b"]["passage_roles"]
        negative_types = manifest[item_id]["module_b"].get("negative_types", [])
        negative_type_index = 0
        for index, private_role in enumerate(private_roles):
            topical = actual[index] != "not_relevant"
            compliant = actual[index] == "query_and_instruction"
            role_name = "positive" if private_role == "positive" else "instruction_negative"
            by_role[role_name]["topical_relevance"].append(topical)
            by_role[role_name]["full_compliance"].append(compliant)
            if private_role == "negative":
                negative_type = str(
                    negative_types[negative_type_index]
                    if negative_type_index < len(negative_types)
                    else "unknown"
                )
                negative_type_index += 1
                type_metrics = by_negative_type.setdefault(
                    negative_type, {"valid": [], "topical_relevance": [], "full_compliance": []}
                )
                type_metrics["valid"].append(actual[index] == "query_only")
                type_metrics["topical_relevance"].append(topical)
                type_metrics["full_compliance"].append(compliant)

    role_diagnostics = {
        role: {
            metric: {"count": len(values), "rate": proportion(values)}
            for metric, values in metrics.items()
        }
        for role, metrics in by_role.items()
    }
    negative_type_diagnostics = {
        negative_type: {
            metric: {"count": len(values), "rate": proportion(values)}
            for metric, values in metrics.items()
        }
        for negative_type, metrics in sorted(by_negative_type.items())
    }
    return {
        "records": len(ids),
        "query_acceptability": {
            "yes": sum(query), "denominator": len(query), "rate": proportion(query)
        },
        "positive_passage_acceptability": {
            "yes": sum(passage), "denominator": len(passage), "rate": proportion(passage)
        },
        "positive_validity": {
            "correct": sum(positive), "denominator": len(positive), "rate": proportion(positive)
        },
        "negative_validity": {
            "correct": sum(negatives), "denominator": len(negatives), "rate": proportion(negatives)
        },
        "strict_record_validity": {
            "correct": sum(strict), "denominator": len(strict), "rate": proportion(strict)
        },
        "role_distribution": dict(Counter(role_values)),
        "by_private_role": role_diagnostics,
        "by_negative_type": negative_type_diagnostics,
    }


def bootstrap_record_metrics(
    rows: dict[str, dict[str, Any]],
    manifest: dict[str, dict[str, Any]],
    ids: list[str],
    repetitions: int,
    seed: int,
) -> dict[str, list[float | None]]:
    rng = random.Random(seed)
    names = (
        "query_acceptability",
        "positive_passage_acceptability",
        "positive_validity",
        "negative_validity",
        "strict_record_validity",
    )
    samples = {name: [] for name in names}
    for _ in range(repetitions):
        draw = [rng.choice(ids) for _ in ids]
        metrics = record_metrics(rows, manifest, draw)
        for name in names:
            samples[name].append(metrics[name]["rate"])
    return {name: ci(values) for name, values in samples.items()}


def agreement_for_ids(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]], ids: list[str]
) -> dict[str, Any]:
    binary = {}
    for question in BINARY_QUESTIONS:
        binary[question] = agreement(
            [left[item]["responses"][question] for item in ids],
            [right[item]["responses"][question] for item in ids],
        )
    left_roles = [left[item]["responses"][q] for item in ids for q in ROLE_QUESTIONS]
    right_roles = [right[item]["responses"][q] for item in ids for q in ROLE_QUESTIONS]
    return {"binary": binary, "document_roles": agreement(left_roles, right_roles)}


def bootstrap_agreement(
    left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]],
    ids: list[str],
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    keys = (*BINARY_QUESTIONS, "document_roles")
    samples = {key: {metric: [] for metric in ("exact_agreement", "cohen_kappa")} for key in keys}
    for _ in range(repetitions):
        draw = [rng.choice(ids) for _ in ids]
        metrics = agreement_for_ids(left, right, draw)
        for question in BINARY_QUESTIONS:
            for metric in samples[question]:
                samples[question][metric].append(metrics["binary"][question][metric])
        for metric in samples["document_roles"]:
            samples["document_roles"][metric].append(metrics["document_roles"][metric])
    return {
        key: {metric: ci(values) for metric, values in values_by_metric.items()}
        for key, values_by_metric in samples.items()
    }


def calculate(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(args.manifest)
    annotations = load_annotations(args.input, args.vladimir, args.daria)
    names = args.annotators or sorted(annotations)
    if len(names) != 2:
        raise ValueError(f"Expected exactly two annotators, found {names}")

    complete = {name: completed(annotations.get(name, {})) for name in names}
    result: dict[str, Any] = {
        "sample": {"records": len(manifest), "annotators": names},
        "annotators": {},
    }
    for offset, name in enumerate(names):
        ids = sorted(set(manifest) & set(complete[name]))
        result["annotators"][name] = {
            "completed_records": len(ids),
            "missing_records": sorted(set(manifest) - set(ids)),
            "pooled": record_metrics(complete[name], manifest, ids),
            "pooled_bootstrap_95ci": (
                bootstrap_record_metrics(complete[name], manifest, ids, args.bootstrap, args.seed + offset)
                if ids else {}
            ),
            "by_split": {},
        }
        for split in ("train", "synthetic_test"):
            split_ids = [item_id for item_id in ids if manifest[item_id].get("source_split") == split]
            result["annotators"][name]["by_split"][split] = (
                record_metrics(complete[name], manifest, split_ids) if split_ids else {"records": 0}
            )

    common = sorted(set(complete[names[0]]) & set(complete[names[1]]) & set(manifest))
    result["inter_annotator_agreement"] = {
        "common_records": len(common),
        "pooled": agreement_for_ids(complete[names[0]], complete[names[1]], common) if common else {},
        "pooled_bootstrap_95ci": (
            bootstrap_agreement(complete[names[0]], complete[names[1]], common, args.bootstrap, args.seed + 100)
            if common else {}
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Combined export containing both usernames")
    parser.add_argument("--vladimir", type=Path, help="Vladimir's export JSONL")
    parser.add_argument("--daria", type=Path, help="Daria's export JSONL")
    parser.add_argument("--manifest", type=Path, default=Path("data/private_manifest.jsonl"))
    parser.add_argument("--annotators", nargs=2, metavar="USERNAME")
    parser.add_argument("--bootstrap", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260710)
    parser.add_argument("--output", type=Path, default=Path("data/exports/audit_metrics.json"))
    args = parser.parse_args()
    if args.bootstrap < 100:
        raise ValueError("Use at least 100 bootstrap repetitions; the default is 10000.")
    result = calculate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["sample"], ensure_ascii=False))
    for username, values in result["annotators"].items():
        print(username, json.dumps(values["pooled"], ensure_ascii=False))
    print("IAA", json.dumps(result["inter_annotator_agreement"], ensure_ascii=False))
    print(f"Saved metrics to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
