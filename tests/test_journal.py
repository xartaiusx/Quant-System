from __future__ import annotations

import json
from pathlib import Path

from trader.reporting import journal as journal_module
from trader.reporting.journal import Journal


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_journal_populates_missing_commit_sha(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_module, "_current_commit_sha", lambda: "abc123")

    json_path, _ = Journal(tmp_path).write_cycle("sample", {"ok": True})

    assert read_json(json_path)["commit_sha"] == "abc123"
    assert read_json(tmp_path / "latest_sample.json")["commit_sha"] == "abc123"


def test_journal_populates_null_commit_sha(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_module, "_current_commit_sha", lambda: "abc123")

    json_path, _ = Journal(tmp_path).write_cycle("sample", {"ok": True, "commit_sha": None})

    assert read_json(json_path)["commit_sha"] == "abc123"


def test_journal_preserves_existing_commit_sha(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(journal_module, "_current_commit_sha", lambda: "abc123")

    json_path, _ = Journal(tmp_path).write_cycle("sample", {"ok": True, "commit_sha": "keepme"})

    assert read_json(json_path)["commit_sha"] == "keepme"
