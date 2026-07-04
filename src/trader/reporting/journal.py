"""JSON and Markdown journaling."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from trader.config import mask_sensitive_mapping
from trader.reporting.reports import markdown_summary


class Journal:
    """Write safe reports under `reports/`."""

    def __init__(self, reports_dir: str | Path = "reports") -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def write_cycle(self, name: str, payload: Mapping[str, Any]) -> tuple[Path, Path]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_payload = mask_sensitive_mapping(_to_plain(dict(payload)))
        safe_payload.setdefault("timestamp", timestamp)
        if not safe_payload.get("commit_sha"):
            safe_payload["commit_sha"] = _current_commit_sha()

        json_path = self.reports_dir / f"{name}_{timestamp}.json"
        md_path = self.reports_dir / f"{name}_{timestamp}.md"
        latest_json = self.reports_dir / f"latest_{name}.json"
        latest_md = self.reports_dir / f"latest_{name}.md"

        json_path.write_text(json.dumps(safe_payload, indent=2, sort_keys=True) + "\n")
        md_path.write_text(markdown_summary(safe_payload))
        shutil.copyfile(json_path, latest_json)
        shutil.copyfile(md_path, latest_md)
        return json_path, md_path


def _to_plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {key: _to_plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def _current_commit_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit_sha = result.stdout.strip()
    return commit_sha or None
