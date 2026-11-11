"""Tests for the offline batch proofreading runner.

Run from ``backend/``:

    python3 -m unittest discover -s tests -v

No database or Redis is required; snapshots and manifests are plain files.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.batch import ManifestError, run_batch  # noqa: E402


def _rows(count: int, prefix: str, *, shift: float = 0.0) -> list[dict]:
    rows = []
    for index in range(count):
        # Deterministic, non-constant numerics so the reference bins freeze.
        x = index / max(count - 1, 1)
        rows.append(
            {
                "reference": f"{prefix}-{index + 1:04d}",
                "features": {
                    "duration": round(1.0 + 3.0 * x + shift, 6),
                    "noise": round(5.0 + 2.0 * x + shift, 6),
                    "token_rate": round(3.0 + x + shift, 6),
                    "language": "zh" if index % 2 == 0 else "en",
                    "device": "studio" if index % 3 == 0 else "mobile",
                },
            }
        )
    return rows


class BatchRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "snaps").mkdir()
        (self.base / "configs").mkdir()
        self._write_json(self.base / "snaps/ref-a.json", _rows(30, "RA"))
        self._write_json(self.base / "snaps/cand-a.json", _rows(30, "CA", shift=1.0))
        self._write_json(self.base / "snaps/ref-b.json", _rows(30, "RB"))
        self._write_json(self.base / "snaps/cand-b.json", _rows(30, "CB", shift=1.0))
        self._write_json(
            self.base / "configs/full.json",
            {
                "features": [
                    "duration",
                    "noise",
                    "token_rate",
                    "language",
                    "device",
                ],
                "bins": 6,
                "smoothing": 0.5,
                "fdr_alpha": 0.05,
            },
        )
        self._write_json(
            self.base / "manifest.json",
            {
                "items": [
                    {
                        "id": "a",
                        "name": "A",
                        "reference": "snaps/ref-a.json",
                        "candidate": "snaps/cand-a.json",
                        "config": "configs/full.json",
                    },
                    {
                        "id": "b",
                        "name": "B",
                        "reference": "snaps/ref-b.json",
                        "candidate": "snaps/cand-b.json",
                        "config": "configs/full.json",
                    },
                ]
            },
        )
        self.out = self.base / "out"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _run(self, *, force: bool = False) -> dict:
        return run_batch(self.base / "manifest.json", self.out, force=force)

    @staticmethod
    def _counts(summary: dict) -> dict:
        return {
            key: summary[key]
            for key in ("total", "reused", "recomputed", "failed", "status")
        }

    def _item_record(self, item_id: str) -> Path:
        matches = list((self.out / "items").glob(f"{item_id}-*.json"))
        self.assertEqual(len(matches), 1, f"item record for {item_id}: {matches}")
        return matches[0]

    def test_first_run_computes_then_rerun_reuses(self) -> None:
        first = self._run()
        self.assertEqual(
            self._counts(first),
            {
                "total": 2,
                "reused": 0,
                "recomputed": 2,
                "failed": 0,
                "status": "ok",
            },
        )
        self.assertTrue((self.out / "summary.json").exists())
        second = self._run()
        self.assertEqual(
            self._counts(second),
            {
                "total": 2,
                "reused": 2,
                "recomputed": 0,
                "failed": 0,
                "status": "ok",
            },
        )

    def test_only_changed_source_is_recomputed(self) -> None:
        self._run()
        changed = _rows(30, "CA", shift=1.0)
        changed[5]["features"]["duration"] += 7.0
        self._write_json(self.base / "snaps/cand-a.json", changed)
        summary = self._run()
        self.assertEqual(self._counts(summary)["recomputed"], 1)
        self.assertEqual(self._counts(summary)["reused"], 1)
        by_id = {item["id"]: item for item in summary["items"]}
        self.assertEqual(by_id["a"]["status"], "recomputed")
        self.assertEqual(by_id["b"]["status"], "reused")

    def test_only_changed_config_is_recomputed(self) -> None:
        self._run()
        config = json.loads((self.base / "configs/full.json").read_text())
        config["bins"] = 5
        self._write_json(self.base / "configs/a.json", config)
        manifest = json.loads((self.base / "manifest.json").read_text())
        manifest["items"][0]["config"] = "configs/a.json"
        self._write_json(self.base / "manifest.json", manifest)
        summary = self._run()
        by_id = {item["id"]: item for item in summary["items"]}
        self.assertEqual(by_id["a"]["status"], "recomputed")
        self.assertEqual(by_id["b"]["status"], "reused")

    def test_failure_is_isolated_and_fixed_item_runs(self) -> None:
        manifest = json.loads((self.base / "manifest.json").read_text())
        manifest["items"][1]["reference"] = "snaps/does-not-exist.json"
        self._write_json(self.base / "manifest.json", manifest)
        failed = self._run()
        self.assertEqual(self._counts(failed)["failed"], 1)
        self.assertEqual(self._counts(failed)["recomputed"], 1)
        by_id = {item["id"]: item for item in failed["items"]}
        self.assertEqual(by_id["a"]["status"], "recomputed")
        self.assertEqual(by_id["b"]["status"], "failed")
        self.assertIn("无法读取", by_id["b"]["error"])
        failed_record = json.loads(self._item_record("b").read_text())
        self.assertEqual(failed_record["status"], "failed")

        manifest["items"][1]["reference"] = "snaps/ref-b.json"
        self._write_json(self.base / "manifest.json", manifest)
        fixed = self._run()
        self.assertEqual(self._counts(fixed)["failed"], 0)
        by_id = {item["id"]: item for item in fixed["items"]}
        self.assertEqual(by_id["b"]["status"], "recomputed")
        self.assertEqual(by_id["a"]["status"], "reused")

    def test_half_written_checkpoint_is_not_a_reuse(self) -> None:
        self._run()
        record_path = self._item_record("a")
        record = json.loads(record_path.read_text())
        cache_path = self.out / "cache" / f"{record['input_hash']}.json"
        self.assertTrue(cache_path.exists())
        cache_path.unlink()
        record_path.write_text(record_path.read_text()[:80], encoding="utf-8")
        summary = self._run()
        by_id = {item["id"]: item for item in summary["items"]}
        self.assertEqual(by_id["a"]["status"], "recomputed")
        self.assertEqual(by_id["b"]["status"], "reused")

    def test_complete_cache_recovers_a_half_written_item_record(self) -> None:
        self._run()
        record_path = self._item_record("a")
        record_path.write_text('{"status":"succeeded"}', encoding="utf-8")
        summary = self._run()
        by_id = {item["id"]: item for item in summary["items"]}
        self.assertEqual(by_id["a"]["status"], "reused")
        self.assertEqual(by_id["a"]["reason"], "result_cache")
        self.assertEqual(by_id["b"]["status"], "reused")

    def test_reordering_rows_does_not_invalidate_inputs(self) -> None:
        self._run()
        rows = json.loads((self.base / "snaps/ref-a.json").read_text())
        self._write_json(self.base / "snaps/ref-a.json", list(reversed(rows)))
        summary = self._run()
        self.assertEqual(self._counts(summary)["reused"], 2)
        self.assertEqual(self._counts(summary)["recomputed"], 0)

    def test_force_recomputes_everything(self) -> None:
        self._run()
        summary = self._run(force=True)
        self.assertEqual(self._counts(summary)["recomputed"], 2)
        self.assertEqual(self._counts(summary)["reused"], 0)

    def test_missing_manifest_is_fatal(self) -> None:
        with self.assertRaises(ManifestError):
            run_batch(self.base / "missing.json", self.out)


if __name__ == "__main__":
    unittest.main()
