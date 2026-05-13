#!/usr/bin/env python3
"""Backup and migrate inventory CSV files to the latest schema.

This utility is safe to run on every deployment update. It can:
- discover default CSV files (`instance/items.csv` and `instance/data/*/items.csv`)
- create timestamped backups before any migration
- create missing CSV files with the latest headers
- run CSVService schema migrations to add/remove required columns
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path so app imports resolve when script is run directly.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.csv_service import CSVService


def _read_headers(csv_path: Path) -> list[str]:
    """Return CSV headers from the first row, or an empty list if unavailable."""
    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            return next(reader, [])
    except Exception:
        return []


def discover_default_csv_paths(project_root: Path) -> list[Path]:
    """Discover default inventory CSV paths for single-user and multi-user layouts."""
    paths: list[Path] = [project_root / "instance" / "items.csv"]

    users_dir = project_root / "instance" / "data"
    if users_dir.exists():
        for user_dir in sorted(path for path in users_dir.iterdir() if path.is_dir()):
            paths.append(user_dir / "items.csv")

    # Preserve order while removing duplicates.
    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for csv_path in paths:
        resolved = csv_path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(csv_path)
    return unique_paths


def create_backup(csv_path: Path, timestamp: str) -> Path:
    """Create a timestamped backup of an existing CSV and return backup path."""
    backup_path = csv_path.with_name(f"{csv_path.name}.{timestamp}.bak")
    shutil.copy2(csv_path, backup_path)
    return backup_path


def migrate_csv(csv_path: Path, backup_first: bool, dry_run: bool) -> tuple[str, list[str]]:
    """Migrate one CSV file and return status plus informational details."""
    details: list[str] = []
    service = CSVService(csv_path)

    if not csv_path.exists():
        if dry_run:
            return "would-create", details
        service.initialize()
        return "created", details

    before_headers = _read_headers(csv_path)

    if backup_first and not dry_run:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = create_backup(csv_path, timestamp)
        details.append(f"backup={backup_path}")

    if dry_run:
        final_headers, needs_migration = service._build_fieldname_order(before_headers)
        missing = sorted(set(final_headers) - set(before_headers))
        removed = sorted(set(before_headers) - set(final_headers))
        if missing:
            details.append("missing=" + ", ".join(missing))
        if removed:
            details.append("removed=" + ", ".join(removed))
        return ("would-migrate" if needs_migration else "ok"), details

    service.initialize()
    after_headers = _read_headers(csv_path)

    if before_headers != after_headers:
        added = sorted(set(after_headers) - set(before_headers))
        removed = sorted(set(before_headers) - set(after_headers))
        if added:
            details.append("added=" + ", ".join(added))
        if removed:
            details.append("removed=" + ", ".join(removed))
        return "migrated", details

    return "ok", details


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Backup and migrate inventory CSV schema")
    parser.add_argument(
        "--csv-path",
        action="append",
        default=[],
        help="Specific CSV path to migrate (can be used multiple times)",
    )
    parser.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not auto-discover default CSV paths under instance/",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip pre-migration backup creation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files",
    )
    return parser.parse_args()


def main() -> int:
    """Run migrations for requested CSV files."""
    args = parse_args()

    requested_paths = [
        Path(path) if Path(path).is_absolute() else (PROJECT_ROOT / path)
        for path in args.csv_path
    ]

    csv_paths: list[Path] = []
    if not args.no_discover:
        csv_paths.extend(discover_default_csv_paths(PROJECT_ROOT))
    csv_paths.extend(requested_paths)

    # Preserve order while removing duplicates.
    deduped_paths: list[Path] = []
    seen: set[Path] = set()
    for csv_path in csv_paths:
        resolved = csv_path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped_paths.append(csv_path)

    if not deduped_paths:
        print("No CSV paths provided or discovered.")
        return 1

    backup_first = not args.no_backup
    failures: list[tuple[Path, str]] = []

    print(f"CSV schema migration root: {PROJECT_ROOT}")
    for csv_path in deduped_paths:
        try:
            status, details = migrate_csv(csv_path, backup_first=backup_first, dry_run=args.dry_run)
            detail_text = f" ({'; '.join(details)})" if details else ""
            print(f"[{status}] {csv_path}{detail_text}")
        except Exception as exc:
            failures.append((csv_path, str(exc)))
            print(f"[error] {csv_path}: {exc}")

    if failures:
        print("\nMigration finished with errors:")
        for csv_path, message in failures:
            print(f" - {csv_path}: {message}")
        return 1

    print("\nMigration completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

