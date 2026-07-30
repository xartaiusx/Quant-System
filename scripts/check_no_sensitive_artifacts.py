"""Reject tracked credentials, broker evidence, reports, and market-data artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path

_BLOCKED_SUFFIXES = (
    ".csv",
    ".csv.gz",
    ".clixml",
    ".db",
    ".json.gz",
    ".jsonl",
    ".ndjson",
    ".ndjson.gz",
    ".parquet",
    ".sqlite",
    ".sqlite3",
)


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        print("git ls-files failed")
        return 1
    tracked = [Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]
    offenders: list[str] = []
    for path in tracked:
        normalized = path.as_posix().lower()
        blocked = (
            normalized.startswith("quant creds/")
            or normalized.startswith("data/historical/")
            or normalized.startswith("research/evidence/")
            or (normalized.startswith("state/") and normalized != "state/.gitkeep")
            or (
                normalized.startswith("reports/")
                and normalized != "reports/.gitkeep"
            )
            or (
                path.name.lower().startswith(".env")
                and path.name != ".env.example"
            )
            or any(normalized.endswith(suffix) for suffix in _BLOCKED_SUFFIXES)
        )
        if blocked:
            offenders.append(path.as_posix())
    if offenders:
        print("Tracked sensitive/generated artifacts:\n" + "\n".join(sorted(offenders)))
        return 1
    print("No tracked credentials, broker reports, evidence, or market-data artifacts found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
