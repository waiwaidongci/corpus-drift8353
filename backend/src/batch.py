"""Offline batch proofreading for reference/candidate corpus snapshots.

The runner intentionally reuses :func:`src.services.comparison.compare_snapshots`
so frozen quantile/category bins, PSI/JS, KS and BH stay identical to the
interactive product.  Only the orchestration around it is new:

* a JSON manifest lists one comparison per item;
* every item is isolated, so one bad snapshot/config cannot stop the batch;
* successful results are cached by a content hash of *all* inputs and the
  comparison algorithm version, therefore a later run only recomputes items
  whose snapshot data or comparison rules actually changed;
* result files are written atomically and carry a completion marker; a
  truncated or stale file is never reported as a successful reuse;
* rerunning the same manifest resumes from the completed items.

Canonical manifest shape (item-level aliases are accepted, see README):

.. code-block:: json

    {
      "items": [
        {
          "id": "november-full",
          "name": "十一月采集分布复校",
          "reference": "snapshots/reference.json",
          "candidate": "snapshots/candidate.json",
          "config": {
            "features": ["duration", "noise", "token_rate", "language", "device"],
            "bins": 6,
            "smoothing": 0.5,
            "fdr_alpha": 0.05,
            "slice_language": null,
            "slice_device": null
          }
        }
      ]
    }

Paths are resolved relative to the manifest file.  A snapshot may also be an
inline JSON array (``[{"reference": ..., "features": {...}}, ...]``) or an
object with an ``utterances`` array.  ``config`` may be an inline object or a
path to a JSON file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# Support `python backend/src/batch.py` as well as `python -m src.batch`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.constants.features import FEATURES, MISSING, NEW, NUMERIC
from src.services.comparison import compare_snapshots
from src.services.fingerprint import fingerprint

# Bump either version when the orchestration/result contract or the statistical
# implementation changes.  Both are part of the reuse key, so old results are
# recomputed instead of being silently treated as current.
RESULT_RECORD_VERSION = 1
BATCH_ALGORITHM_VERSION = "batch-compare-v1"

CONFIG_KEYS = (
    "features",
    "bins",
    "smoothing",
    "fdr_alpha",
    "slice_language",
    "slice_device",
)

DEFAULT_CONFIG = {
    "features": list(FEATURES),
    "bins": 6,
    "smoothing": 0.5,
    "fdr_alpha": 0.05,
    "slice_language": None,
    "slice_device": None,
}

ID_KEYS = ("id", "key", "slug")
NAME_KEYS = ("name", "title", "label")
REFERENCE_KEYS = (
    "reference",
    "reference_path",
    "reference_snapshot",
    "reference_file",
    "ref",
)
CANDIDATE_KEYS = (
    "candidate",
    "candidate_path",
    "candidate_snapshot",
    "candidate_file",
    "cand",
)
CONFIG_KEYS_IN_ITEM = (
    "config",
    "config_path",
    "config_file",
    "comparison_config",
    "comparison",
)

_MISSING = object()


class BatchError(Exception):
    """Base class for failures that should be reported to the operator."""


class ManifestError(BatchError):
    """The manifest itself is unusable; no item can be processed."""


class ItemError(BatchError):
    """One manifest item is invalid or could not be computed."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_constant(value: str) -> Any:
    # json.loads accepts NaN/Infinity by default; the import contract and the
    # fingerprint both require finite values, so reject them at the boundary.
    raise ValueError(f"不允许非有限数值: {value}")


def _load_json(path: Path, label: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ItemError(f"无法读取{label} {path}: {exc}") from exc
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ItemError(f"{label} {path} 不是合法 JSON: {exc}") from exc


def _atomic_write_json(path: Path, value: Any) -> None:
    """Write a complete JSON document atomically, never exposing a prefix."""

    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        # Best-effort directory fsync so the rename itself is durable.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _first(mapping: dict[str, Any], keys: Iterable[str], default: Any = _MISSING) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    if default is _MISSING:
        return _MISSING
    return default


def _resolve_path(value: str, base: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _item_key(item_id: str) -> str:
    """Return a filesystem-safe, deterministic key for an item id."""

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", item_id).strip("-.")[:80]
    if not slug:
        slug = "item"
    return f"{slug}-{_sha256(item_id.encode('utf-8'))[:10]}"


# ---------------------------------------------------------------------------
# Snapshot / config loading
# ---------------------------------------------------------------------------


@dataclass
class SnapshotSource:
    rows: list[dict[str, Any]]
    label: str
    sha256: str


def _snapshot_rows(raw: Any, label: str) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        for key in ("utterances", "items", "rows", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise ItemError(f"{label} 必须是片段数组")
    if not raw:
        raise ItemError(f"{label} 为空快照")

    rows: list[dict[str, Any]] = []
    seen_references: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ItemError(f"{label} 第{index + 1}项必须是对象")
        reference = entry.get("reference")
        if (
            not isinstance(reference, str)
            or not reference.strip()
            or len(reference) > 80
        ):
            raise ItemError(
                f"{label} 第{index + 1}项 reference 必须是1-80字符的非空字符串"
            )
        if reference in seen_references:
            raise ItemError(f"{label} reference 重复: {reference}")
        seen_references.add(reference)

        features = entry.get("features")
        if not isinstance(features, dict) or set(features) != set(FEATURES):
            raise ItemError(
                f"{label} 第{index + 1}项必须包含且仅包含五个特征: "
                + ", ".join(FEATURES)
            )
        normalized: dict[str, Any] = {}
        for key, value in features.items():
            if value is None:
                normalized[key] = None
                continue
            if key in NUMERIC:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ItemError(
                        f"{label} 第{index + 1}项 {key} 必须是有限数字或 null"
                    )
                numeric = float(value)
                if not math.isfinite(numeric):
                    raise ItemError(f"{label} 第{index + 1}项 {key} 不是有限数值")
                # Normalise int/float representation so 3 and 3.0 hash alike.
                normalized[key] = numeric
            else:
                if not isinstance(value, str) or not 1 <= len(value) <= 40:
                    raise ItemError(
                        f"{label} 第{index + 1}项 {key} 必须是1-40字符的字符串或 null"
                    )
                if value in (MISSING, NEW):
                    raise ItemError(
                        f"{label} 第{index + 1}项 {key} 不得使用保留桶名 {value}"
                    )
                normalized[key] = value

        row_id = entry.get("id")
        if row_id is None:
            row_id = reference
        if isinstance(row_id, bool) or not isinstance(row_id, (str, int)):
            row_id = str(row_id)
        rows.append(
            {"id": row_id, "reference": reference, "features": normalized}
        )
    return rows


def _snapshot_from_value(
    value: Any,
    *,
    base: Path,
    aliases: dict[str, Any],
    label: str,
    expected_kind: str,
) -> SnapshotSource:
    if isinstance(value, str) and value in aliases:
        # Alias targets can be a path, an inline array or a snapshot object.
        # Empty the alias map to avoid an accidental cycle.
        return _snapshot_from_value(
            aliases[value],
            base=base,
            aliases={},
            label=label,
            expected_kind=expected_kind,
        )
    if isinstance(value, str):
        path = _resolve_path(value, base)
        raw_bytes = _read_bytes(path, label)
        return SnapshotSource(
            rows=_snapshot_rows(_loads_bytes(raw_bytes, path, label), str(path)),
            label=str(path),
            sha256=_sha256(raw_bytes),
        )
    if isinstance(value, (list, tuple)):
        raw = list(value)
    elif isinstance(value, dict):
        kind = value.get("kind")
        if kind is not None and kind != expected_kind:
            raise ItemError(f"{label} 快照用途为 {kind}，此处要求 {expected_kind}")
        if "utterances" in value or "items" in value or "rows" in value or "data" in value:
            raw = value
        elif "path" in value or "file" in value or "filename" in value:
            path_value = _first(value, ("path", "file", "filename"))
            if not isinstance(path_value, str):
                raise ItemError(f"{label} 的路径必须是字符串")
            path = _resolve_path(path_value, base)
            raw_bytes = _read_bytes(path, label)
            return SnapshotSource(
                rows=_snapshot_rows(_loads_bytes(raw_bytes, path, label), str(path)),
                label=str(path),
                sha256=_sha256(raw_bytes),
            )
        else:
            raise ItemError(f"{label} 对象必须包含 utterances 或 path")
    else:
        raise ItemError(f"{label} 必须是路径、片段数组或快照对象")

    return SnapshotSource(
        rows=_snapshot_rows(raw, label),
        label=f"inline:{label}",
        sha256=_sha256(_canonical_bytes(raw)),
    )


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ItemError(f"无法读取{label} {path}: {exc}") from exc


def _loads_bytes(raw: bytes, path: Path, label: str) -> Any:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ItemError(f"{label} {path} 不是 UTF-8 文本: {exc}") from exc
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ItemError(f"{label} {path} 不是合法 JSON: {exc}") from exc


def _config_from_value(
    value: Any,
    *,
    base: Path,
    aliases: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if value is _MISSING or value is None:
        return {}
    if isinstance(value, dict):
        # Allow a config file/object wrapped as {"config": {...}}.
        if "config" in value and isinstance(value["config"], dict):
            return dict(value["config"])
        return dict(value)
    if isinstance(value, str):
        if value in aliases:
            return _config_from_value(
                aliases[value], base=base, aliases={}, label=label
            )
        path = _resolve_path(value, base)
        raw = _load_json(path, f"{label}配置")
        return _config_from_value(raw, base=base, aliases={}, label=str(path))
    raise ItemError(f"{label} 配置必须是对象或 JSON 文件路径")


def _normalise_config(raw: dict[str, Any], label: str) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    for key in CONFIG_KEYS:
        if key in raw:
            merged[key] = raw[key]

    features = merged["features"]
    if not isinstance(features, (list, tuple)) or not features:
        raise ItemError(f"{label} features 必须是非空特征数组")
    if any(not isinstance(feature, str) for feature in features):
        raise ItemError(f"{label} features 只能包含字符串")
    if len(set(features)) != len(features):
        raise ItemError(f"{label} features 不得重复")
    if not set(features) <= set(FEATURES):
        unknown = sorted(set(features) - set(FEATURES))
        raise ItemError(f"{label} 包含未知特征: {', '.join(unknown)}")

    bins = merged["bins"]
    if isinstance(bins, bool) or not isinstance(bins, int):
        raise ItemError(f"{label} bins 必须是整数")
    if not 2 <= bins <= 10:
        raise ItemError(f"{label} bins 必须在2到10之间")

    smoothing = merged["smoothing"]
    if isinstance(smoothing, bool) or not isinstance(smoothing, (int, float)):
        raise ItemError(f"{label} smoothing 必须是数字")
    if not math.isfinite(float(smoothing)) or not 0 < float(smoothing) <= 10:
        raise ItemError(f"{label} smoothing 必须是(0,10]内的有限数")

    fdr_alpha = merged["fdr_alpha"]
    if isinstance(fdr_alpha, bool) or not isinstance(fdr_alpha, (int, float)):
        raise ItemError(f"{label} fdr_alpha 必须是数字")
    if not math.isfinite(float(fdr_alpha)) or not 0 < float(fdr_alpha) <= 0.2:
        raise ItemError(f"{label} fdr_alpha 必须在(0,.2]内")

    for key in ("slice_language", "slice_device"):
        value = merged[key]
        if value is None or value == "":
            merged[key] = None
            continue
        if not isinstance(value, str) or len(value) > 40:
            raise ItemError(f"{label} {key} 必须是null或不超过40字符的字符串")
        merged[key] = value

    return {
        "features": list(features),
        "bins": int(bins),
        "smoothing": float(smoothing),
        "fdr_alpha": float(fdr_alpha),
        "slice_language": merged["slice_language"],
        "slice_device": merged["slice_device"],
    }


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


@dataclass
class ItemSpec:
    index: int
    id: str
    name: str
    reference_value: Any
    candidate_value: Any
    config_value: Any
    config_source: str
    error: str | None = None


@dataclass
class Manifest:
    path: Path
    base: Path
    items: list[ItemSpec]
    snapshot_aliases: dict[str, Any] = field(default_factory=dict)
    config_aliases: dict[str, Any] = field(default_factory=dict)
    default_config_value: Any = _MISSING


def _description(raw: Any, index: int) -> tuple[str, str]:
    if not isinstance(raw, dict):
        return f"item-{index + 1:04d}", f"item-{index + 1:04d}"
    item_id = _first(raw, ID_KEYS)
    if item_id is _MISSING or item_id is None:
        item_id = f"item-{index + 1:04d}"
    if not isinstance(item_id, str) or not item_id.strip():
        item_id = str(item_id).strip() or f"item-{index + 1:04d}"
    item_name = _first(raw, NAME_KEYS)
    if item_name is _MISSING or item_name is None or item_name == "":
        item_name = item_id
    if not isinstance(item_name, str):
        item_name = str(item_name)
    return item_id, item_name


def load_manifest(path: Path) -> Manifest:
    try:
        raw = _load_json(path, "清单")
    except ItemError as exc:
        raise ManifestError(str(exc)) from exc
    base = path.parent

    if isinstance(raw, list):
        raw_items = raw
        defaults: dict[str, Any] = {}
        snapshot_aliases: dict[str, Any] = {}
        config_aliases: dict[str, Any] = {}
    elif isinstance(raw, dict):
        raw_items = _first(raw, ("items", "comparisons", "cases", "entrypoints"))
        if raw_items is _MISSING:
            raise ManifestError("清单对象必须包含 items 数组")
        if not isinstance(raw_items, list):
            raise ManifestError("清单的 items 必须是数组")
        defaults = raw.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ManifestError("清单 defaults 必须是对象")
        snapshot_aliases = raw.get("snapshots") or {}
        if not isinstance(snapshot_aliases, dict):
            raise ManifestError("清单 snapshots 必须是对象")
        config_aliases = (
            raw.get("configs")
            or raw.get("comparison_configs")
            or {}
        )
        if not isinstance(config_aliases, dict):
            raise ManifestError("清单 configs 必须是对象")
    else:
        raise ManifestError("清单必须是 items 数组或包含 items 的对象")

    default_reference = _first(
        defaults, REFERENCE_KEYS, default=_MISSING
    )
    default_candidate = _first(defaults, CANDIDATE_KEYS, default=_MISSING)
    default_config = _first(defaults, CONFIG_KEYS_IN_ITEM, default=_MISSING)
    if default_config is _MISSING and any(key in defaults for key in CONFIG_KEYS):
        default_config = {key: defaults[key] for key in CONFIG_KEYS if key in defaults}

    specs: list[ItemSpec] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        item_id, item_name = _description(raw_item, index)
        if item_id in seen_ids:
            raise ManifestError(f"清单 item id 重复: {item_id}")
        seen_ids.add(item_id)

        if not isinstance(raw_item, dict):
            # A malformed entry fails on its own; the rest of the manifest runs.
            specs.append(
                ItemSpec(
                    index=index,
                    id=item_id,
                    name=item_name,
                    reference_value=_MISSING,
                    candidate_value=_MISSING,
                    config_value=_MISSING,
                    config_source="inline",
                    error=f"清单第{index + 1}项必须是对象",
                )
            )
            continue

        reference_value = _first(raw_item, REFERENCE_KEYS, default=_MISSING)
        candidate_value = _first(raw_item, CANDIDATE_KEYS, default=_MISSING)
        if reference_value is _MISSING:
            reference_value = default_reference
        if candidate_value is _MISSING:
            candidate_value = default_candidate

        config_value = _first(raw_item, CONFIG_KEYS_IN_ITEM, default=_MISSING)
        if config_value is _MISSING:
            direct = {key: raw_item[key] for key in CONFIG_KEYS if key in raw_item}
            config_value = direct if direct else _MISSING
        if config_value is _MISSING:
            config_value = default_config

        config_source = "inline"
        if isinstance(config_value, str):
            config_source = config_value

        specs.append(
            ItemSpec(
                index=index,
                id=item_id,
                name=item_name,
                reference_value=reference_value,
                candidate_value=candidate_value,
                config_value=config_value,
                config_source=config_source,
            )
        )

    return Manifest(
        path=path,
        base=base,
        items=specs,
        snapshot_aliases=snapshot_aliases,
        config_aliases=config_aliases,
        default_config_value=default_config,
    )


# ---------------------------------------------------------------------------
# Result record validation
# ---------------------------------------------------------------------------


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _validate_success_record(
    record: Any,
    *,
    expected_input_hash: str,
    expected_comparison_fingerprint: str,
    expected_config: dict[str, Any],
) -> tuple[bool, str]:
    """Return whether a stored record is a complete, current success.

    This is deliberately strict: anything that does not prove the whole result
    was written is treated as a cache miss, never as a successful reuse.
    """

    if not isinstance(record, dict):
        return False, "记录不是对象"
    if record.get("status") != "succeeded":
        return False, "记录状态不是 succeeded"
    if record.get("complete") is not True:
        return False, "记录缺少 complete=true 完成标记"
    if record.get("record_version") != RESULT_RECORD_VERSION:
        return False, "记录版本不匹配"
    if record.get("algorithm_version") != BATCH_ALGORITHM_VERSION:
        return False, "算法版本不匹配"
    if record.get("input_hash") != expected_input_hash:
        return False, "输入哈希不匹配"
    if record.get("comparison_fingerprint") != expected_comparison_fingerprint:
        return False, "比较指纹不匹配"
    if record.get("config") != expected_config:
        return False, "比较配置不匹配"

    result = record.get("result")
    if not isinstance(result, dict):
        return False, "结果缺失"
    if result.get("fingerprint") != expected_comparison_fingerprint:
        return False, "结果内指纹不匹配"
    if not isinstance(result.get("reference_n"), int) or not isinstance(
        result.get("candidate_n"), int
    ):
        return False, "结果缺少样本量"
    if not isinstance(result.get("test_family"), dict):
        return False, "结果缺少检验族"
    findings = result.get("findings")
    if not isinstance(findings, list):
        return False, "结果缺少 findings"
    if len(findings) != len(expected_config["features"]):
        return False, "findings 数量与配置不符"
    by_feature: dict[str, dict[str, Any]] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            return False, "findings 项不是对象"
        feature = finding.get("feature")
        if feature not in expected_config["features"] or feature in by_feature:
            return False, "findings 特征与配置不符"
        if finding.get("status") not in ("quiet", "review"):
            return False, "findings 状态不合法"
        metrics = finding.get("metrics")
        if not isinstance(metrics, dict):
            return False, "findings 指标缺失"
        if not _is_finite_number(metrics.get("psi")):
            return False, "PSI 非法"
        if not _is_finite_number(metrics.get("js")):
            return False, "JS 非法"
        for key in ("reference_counts", "candidate_counts"):
            counts = metrics.get(key)
            if not isinstance(counts, list) or any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in counts
            ):
                return False, f"{key} 非法"
        if not isinstance(metrics.get("binning"), dict):
            return False, "冻结分箱缺失"
        by_feature[feature] = finding
    numeric_count = sum(1 for feature in expected_config["features"] if feature in NUMERIC)
    if result["test_family"].get("m") != numeric_count:
        return False, "检验族数量不匹配"
    return True, ""


def _read_record(path: Path) -> tuple[Any, str]:
    if not path.exists():
        return None, "不存在"
    try:
        text = path.read_text(encoding="utf-8-sig")
        return json.loads(text, parse_constant=_reject_constant), ""
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, f"无法读取或解析: {exc}"


def _input_hash(comparison_fingerprint: str) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "algorithm_version": BATCH_ALGORITHM_VERSION,
                "record_version": RESULT_RECORD_VERSION,
                "comparison_fingerprint": comparison_fingerprint,
            }
        )
    )


def _success_record(
    *,
    item: dict[str, Any],
    source: dict[str, Any],
    config: dict[str, Any],
    input_hash: str,
    comparison_fingerprint: str,
    result: dict[str, Any],
    computed_at: str,
    include_item: bool,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "record_version": RESULT_RECORD_VERSION,
        "algorithm_version": BATCH_ALGORITHM_VERSION,
        "status": "succeeded",
        "complete": True,
        "input_hash": input_hash,
        "comparison_fingerprint": comparison_fingerprint,
        "config": config,
        "source": source,
        "computed_at": computed_at,
        "result": result,
    }
    if include_item:
        record["item"] = item
    return record


def _failure_record(
    *,
    item: dict[str, Any],
    error: str,
    input_hash: str | None,
    comparison_fingerprint: str | None,
    config: dict[str, Any] | None,
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "record_version": RESULT_RECORD_VERSION,
        "algorithm_version": BATCH_ALGORITHM_VERSION,
        "status": "failed",
        "complete": True,
        "item": item,
        "input_hash": input_hash,
        "comparison_fingerprint": comparison_fingerprint,
        "config": config,
        "source": source,
        "error": error,
        "computed_at": _utc_now(),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class _ItemResult:
    id: str
    name: str
    index: int
    status: str
    input_hash: str | None = None
    comparison_fingerprint: str | None = None
    result_path: str | None = None
    cache_path: str | None = None
    error: str | None = None
    reason: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


def _summarise(entries: list[_ItemResult], *, interrupted: bool = False) -> dict[str, Any]:
    reused = sum(1 for entry in entries if entry.status == "reused")
    recomputed = sum(1 for entry in entries if entry.status == "recomputed")
    failed = sum(1 for entry in entries if entry.status == "failed")
    not_run = sum(1 for entry in entries if entry.status == "interrupted")
    return {
        "record_version": RESULT_RECORD_VERSION,
        "algorithm_version": BATCH_ALGORITHM_VERSION,
        "status": (
            "interrupted"
            if interrupted
            else ("partial_failure" if failed else "ok")
        ),
        "total": len(entries),
        "reused": reused,
        "recomputed": recomputed,
        "failed": failed,
        "not_run": not_run,
        "successful": reused + recomputed,
        "items": [
            {
                "index": entry.index,
                "id": entry.id,
                "name": entry.name,
                "status": entry.status,
                "reason": entry.reason,
                "input_hash": entry.input_hash,
                "comparison_fingerprint": entry.comparison_fingerprint,
                "result_path": entry.result_path,
                "cache_path": entry.cache_path,
                "error": entry.error,
                "source": entry.source,
                "duration_ms": entry.duration_ms,
            }
            for entry in entries
        ],
    }


def _process_item(
    spec: ItemSpec,
    *,
    manifest: Manifest,
    snapshot_aliases: dict[str, Any],
    config_aliases: dict[str, Any],
    items_dir: Path,
    cache_dir: Path,
    force: bool,
) -> _ItemResult:
    started = time.monotonic()
    item_meta = {"id": spec.id, "name": spec.name, "index": spec.index}
    source_meta: dict[str, Any] = {
        "config": spec.config_source,
        "reference": None,
        "candidate": None,
    }
    item_path = items_dir / f"{_item_key(spec.id)}.json"
    input_hash: str | None = None
    comparison_fingerprint: str | None = None
    config: dict[str, Any] | None = None

    def finish(status: str, *, error: str | None = None, reason: str | None = None) -> _ItemResult:
        cache_file = (
            cache_dir / f"{input_hash}.json" if input_hash else None
        )
        return _ItemResult(
            id=spec.id,
            name=spec.name,
            index=spec.index,
            status=status,
            input_hash=input_hash,
            comparison_fingerprint=comparison_fingerprint,
            result_path=str(item_path) if item_path.exists() else None,
            cache_path=(
                str(cache_file)
                if status in ("reused", "recomputed")
                and cache_file is not None
                and cache_file.exists()
                else None
            ),
            error=error,
            reason=reason,
            source=source_meta,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def fail(error: Exception | str) -> _ItemResult:
        message = str(error)[:2000]
        try:
            _atomic_write_json(
                item_path,
                _failure_record(
                    item=item_meta,
                    error=message,
                    input_hash=input_hash,
                    comparison_fingerprint=comparison_fingerprint,
                    config=config,
                    source=source_meta,
                ),
            )
        except Exception as write_error:  # noqa: BLE001 - report, don't mask
            message = f"{message}; 失败记录写入失败: {write_error}"[:2000]
        return finish("failed", error=message)

    try:
        if spec.error:
            raise ItemError(spec.error)
        if spec.reference_value is _MISSING:
            raise ItemError("缺少 reference 快照")
        if spec.candidate_value is _MISSING:
            raise ItemError("缺少 candidate 快照")

        reference = _snapshot_from_value(
            spec.reference_value,
            base=manifest.base,
            aliases=snapshot_aliases,
            label=f"{spec.id} reference",
            expected_kind="reference",
        )
        candidate = _snapshot_from_value(
            spec.candidate_value,
            base=manifest.base,
            aliases=snapshot_aliases,
            label=f"{spec.id} candidate",
            expected_kind="candidate",
        )
        source_meta["reference"] = {
            "label": reference.label,
            "sha256": reference.sha256,
        }
        source_meta["candidate"] = {
            "label": candidate.label,
            "sha256": candidate.sha256,
        }

        default_config = _config_from_value(
            manifest.default_config_value,
            base=manifest.base,
            aliases=config_aliases,
            label=f"{spec.id} defaults",
        )
        item_config = _config_from_value(
            spec.config_value,
            base=manifest.base,
            aliases=config_aliases,
            label=spec.id,
        )
        # Per-item rules override manifest defaults key by key.
        raw_config = {**default_config, **item_config}
        config = _normalise_config(raw_config, spec.id)
        comparison_fingerprint = fingerprint(reference.rows, candidate.rows, config)
        input_hash = _input_hash(comparison_fingerprint)
        cache_path = cache_dir / f"{input_hash}.json"

        if not force:
            # A complete per-item record is the primary resume checkpoint.
            record, _ = _read_record(item_path)
            valid, _ = _validate_success_record(
                record,
                expected_input_hash=input_hash,
                expected_comparison_fingerprint=comparison_fingerprint,
                expected_config=config,
            )
            if valid:
                return finish("reused", reason="item_checkpoint")

            # Content-addressed cache also recovers a missing/half-written
            # per-item record and lets renamed items reuse their computation.
            cached, _ = _read_record(cache_path)
            valid, _ = _validate_success_record(
                cached,
                expected_input_hash=input_hash,
                expected_comparison_fingerprint=comparison_fingerprint,
                expected_config=config,
            )
            if valid:
                record = _success_record(
                    item=item_meta,
                    source=source_meta,
                    config=config,
                    input_hash=input_hash,
                    comparison_fingerprint=comparison_fingerprint,
                    result=cached["result"],
                    computed_at=cached.get("computed_at", _utc_now()),
                    include_item=True,
                )
                _atomic_write_json(item_path, record)
                return finish("reused", reason="result_cache")

        result = compare_snapshots(reference.rows, candidate.rows, config)
        valid, reason = _validate_success_record(
            {
                "status": "succeeded",
                "complete": True,
                "record_version": RESULT_RECORD_VERSION,
                "algorithm_version": BATCH_ALGORITHM_VERSION,
                "input_hash": input_hash,
                "comparison_fingerprint": comparison_fingerprint,
                "config": config,
                "result": result,
            },
            expected_input_hash=input_hash,
            expected_comparison_fingerprint=comparison_fingerprint,
            expected_config=config,
        )
        if not valid:
            raise ItemError(f"计算结果不完整: {reason}")

        computed_at = _utc_now()
        cache_record = _success_record(
            item=item_meta,
            source=source_meta,
            config=config,
            input_hash=input_hash,
            comparison_fingerprint=comparison_fingerprint,
            result=result,
            computed_at=computed_at,
            include_item=False,
        )
        # Cache first, then the per-item checkpoint.  A crash in between is
        # recoverable because the next run finds the complete cache record.
        _atomic_write_json(cache_path, cache_record)
        item_record = _success_record(
            item=item_meta,
            source=source_meta,
            config=config,
            input_hash=input_hash,
            comparison_fingerprint=comparison_fingerprint,
            result=result,
            computed_at=computed_at,
            include_item=True,
        )
        _atomic_write_json(item_path, item_record)
        return finish("recomputed", reason="computed")
    except ItemError as exc:
        return fail(exc)
    except Exception as exc:  # noqa: BLE001 - item isolation is the point
        return fail(exc)


def run_batch(
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    force: bool = False,
    progress: Callable[[int, int, _ItemResult], None] | None = None,
) -> dict[str, Any]:
    """Run a manifest and return the summary dictionary.

    ``progress`` is called after each item with ``(position, total, result)``.
    The function never raises for individual item failures; it raises
    :class:`ManifestError` only when the manifest itself cannot be used.
    """

    manifest_file = Path(manifest_path).expanduser().resolve()
    if not manifest_file.exists():
        raise ManifestError(f"清单不存在: {manifest_file}")
    if not manifest_file.is_file():
        raise ManifestError(f"清单不是文件: {manifest_file}")

    manifest = load_manifest(manifest_file)
    output_path = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else manifest.base / "batch-results"
    )
    output_path.mkdir(parents=True, exist_ok=True)
    items_dir = output_path / "items"
    cache_dir = output_path / "cache"
    items_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    snapshot_aliases = manifest.snapshot_aliases
    config_aliases = manifest.config_aliases

    entries: list[_ItemResult] = []
    interrupted = False
    total = len(manifest.items)
    for position, spec in enumerate(manifest.items, start=1):
        try:
            entry = _process_item(
                spec,
                manifest=manifest,
                snapshot_aliases=snapshot_aliases,
                config_aliases=config_aliases,
                items_dir=items_dir,
                cache_dir=cache_dir,
                force=force,
            )
        except KeyboardInterrupt:
            interrupted = True
            for remaining_spec in manifest.items[position - 1 :]:
                entries.append(
                    _ItemResult(
                        id=remaining_spec.id,
                        name=remaining_spec.name,
                        index=remaining_spec.index,
                        status="interrupted",
                        error="运行被中断，未处理",
                    )
                )
            break
        entries.append(entry)
        if progress is not None:
            try:
                progress(position, total, entry)
            except Exception:
                pass

    summary = _summarise(entries, interrupted=interrupted)
    summary["manifest"] = str(manifest_file)
    summary["output_dir"] = str(output_path)
    summary["generated_at"] = _utc_now()
    summary_path = output_path / "summary.json"
    _atomic_write_json(summary_path, summary)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="batch-compare",
        description=(
            "离线批量复核参考/候选快照；逐项隔离失败，按输入哈希复用，"
            "原子写结果并输出复用/重算/失败汇总。"
        ),
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        help="清单 JSON 路径（也可用 --manifest）",
    )
    parser.add_argument("-m", "--manifest", dest="manifest_opt", help="清单 JSON 路径")
    parser.add_argument(
        "-o",
        "--output-dir",
        "--output",
        dest="output_dir",
        help="结果目录（默认与清单同目录的 batch-results/）",
    )
    parser.add_argument(
        "--summary",
        dest="summary_path",
        help="汇总 JSON 的额外副本路径（主汇总始终写入输出目录）",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="忽略已成功缓存，全部重算",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="不向 stderr 打印逐项进度",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    manifest = args.manifest_opt or args.manifest
    if not manifest:
        parser.error("必须提供清单路径（位置参数或 --manifest）")
    if args.manifest_opt and args.manifest:
        parser.error("清单路径只能提供一次")
    if args.summary_path and not args.manifest_opt and not args.manifest:
        parser.error("--summary 需要清单路径")

    def on_progress(position: int, total: int, entry: _ItemResult) -> None:
        if args.quiet:
            return
        suffix = f" ({entry.reason})" if entry.reason else ""
        print(
            f"[{position}/{total}] {entry.id}: {entry.status}{suffix}"
            + (f" — {entry.error}" if entry.error else ""),
            file=sys.stderr,
        )

    try:
        summary = run_batch(
            manifest,
            args.output_dir,
            force=args.force,
            progress=on_progress,
        )
    except ManifestError as exc:
        print(f"清单错误: {exc}", file=sys.stderr)
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except BatchError as exc:
        print(f"批处理错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - surface as a fatal batch error
        print(f"批处理失败: {exc}", file=sys.stderr)
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    if args.summary_path:
        try:
            _atomic_write_json(Path(args.summary_path).expanduser().resolve(), summary)
        except Exception as exc:  # noqa: BLE001 - summary already persisted
            print(f"额外汇总写入失败: {exc}", file=sys.stderr)

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if not args.quiet:
        print(
            "批量校对: total={total} reused={reused} recomputed={recomputed} "
            "failed={failed} status={status}".format(**summary),
            file=sys.stderr,
        )
    if summary["status"] == "interrupted":
        return 130
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
