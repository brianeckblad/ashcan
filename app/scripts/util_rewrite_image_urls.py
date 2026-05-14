#!/usr/bin/env python3
"""Rewrite S3 image URLs in inventory CSV files.

Replaces any S3 bucket hostname with the correct one in all Image URL columns
(Image URL 1 … Image URL 8).  Safe to run on every deployment — rows whose
URLs already reference the correct bucket are left untouched.

The ``--new-bucket`` argument is required.  ``--old-bucket`` is optional: when
omitted the script replaces *any* ``*.s3.amazonaws.com`` hostname that does not
match ``--new-bucket``, making it useful when the old bucket name is unknown.

Usage
-----
# Preview without writing (auto-detect old bucket):
python util_rewrite_image_urls.py --new-bucket ashcan-adequate-app --dry-run

# Apply in-place, targeting a specific old bucket:
python util_rewrite_image_urls.py --old-bucket dockyard-adequate-app \
                                   --new-bucket ashcan-adequate-app
"""

from __future__ import annotations

import argparse
import csv
import io
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Project-root resolution — works whether script is called from anywhere.
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Image URL column names as defined in whatnot_validators.py
IMAGE_URL_COLUMNS = [f"Image URL {i}" for i in range(1, 9)]


def discover_csv_paths(project_root: Path) -> list[Path]:
    """Return all per-user items.csv paths under instance/data/, plus root."""
    paths: list[Path] = [project_root / "instance" / "items.csv"]
    users_dir = project_root / "instance" / "data"
    if users_dir.exists():
        for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
            paths.append(user_dir / "items.csv")
    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(p)
    return unique


import re as _re

# Matches any s3 bucket hostname: {bucket}.s3.amazonaws.com or
# {bucket}.s3.{region}.amazonaws.com
_S3_HOST_RE = _re.compile(r'https?://([^/]+\.s3(?:\.[^/]+)?\.amazonaws\.com)')


def _rewrite_url(url: str, old_host: str, new_host: str) -> str:
    """Return *url* with *old_host* replaced by *new_host* (no-op if not present)."""
    return url.replace(old_host, new_host)


def rewrite_csv(
    csv_path: Path,
    old_bucket: str | None,
    new_bucket: str,
    backup: bool,
    dry_run: bool,
) -> tuple[str, int]:
    """Rewrite image URLs in one CSV file.

    When *old_bucket* is ``None`` the script replaces any s3.amazonaws.com
    hostname that does not already match *new_bucket*.

    Returns (status, changed_rows) where status is one of:
        'skipped'      – file does not exist
        'ok'           – file exists, no changes needed
        'would-update' – dry-run: rows would be changed
        'updated'      – file was rewritten
    """
    if not csv_path.exists():
        return "skipped", 0

    new_host = f"{new_bucket}.s3.amazonaws.com"
    old_host: str | None = f"{old_bucket}.s3.amazonaws.com" if old_bucket else None

    # Read all rows into memory (inventory CSVs are small)
    with open(csv_path, "r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames: list[str] = reader.fieldnames or []
        rows = list(reader)

    # Determine which image-URL columns are present in this file
    active_cols = [c for c in IMAGE_URL_COLUMNS if c in fieldnames]

    changed_rows = 0
    for row in rows:
        row_changed = False
        for col in active_cols:
            cell = row.get(col) or ""
            if not cell or new_host in cell:
                continue  # already correct or empty
            if old_host:
                # Targeted replacement
                if old_host in cell:
                    row[col] = _rewrite_url(cell, old_host, new_host)
                    row_changed = True
            else:
                # Auto-detect: replace any non-matching s3 bucket in this URL
                m = _S3_HOST_RE.search(cell)
                if m and m.group(1) != new_host:
                    row[col] = cell.replace(m.group(1), new_host)
                    row_changed = True
        if row_changed:
            changed_rows += 1

    if changed_rows == 0:
        return "ok", 0

    if dry_run:
        return "would-update", changed_rows

    # Back up before writing
    if backup:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = csv_path.with_name(f"{csv_path.name}.{ts}.bak")
        shutil.copy2(csv_path, backup_path)

    # Write updated CSV, preserving original column order
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        fh.write(buf.getvalue())

    return "updated", changed_rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rewrite S3 bucket name in CSV image URLs")
    p.add_argument(
        "--old-bucket",
        default=None,
        help="Old S3 bucket name (default: auto-detect from CSV URLs)",
    )
    p.add_argument(
        "--new-bucket",
        required=True,
        help="Correct S3 bucket name (e.g. ashcan-adequate-app)",
    )
    p.add_argument(
        "--csv-path",
        action="append",
        default=[],
        help="Specific CSV path to rewrite (can repeat; default: auto-discover)",
    )
    p.add_argument(
        "--no-discover",
        action="store_true",
        help="Do not auto-discover CSVs under instance/",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip pre-rewrite backup creation",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    csv_paths: list[Path] = []
    if not args.no_discover:
        csv_paths.extend(discover_csv_paths(PROJECT_ROOT))
    for path_str in args.csv_path:
        p = Path(path_str)
        csv_paths.append(p if p.is_absolute() else PROJECT_ROOT / p)

    # Deduplicate
    seen: set[Path] = set()
    deduped: list[Path] = []
    for p in csv_paths:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            deduped.append(p)

    if not deduped:
        print("No CSV paths provided or discovered.")
        return 1

    old_label = f"{args.old_bucket!r}" if args.old_bucket else "(auto-detect)"
    print(f"Rewriting image URLs: {old_label} → {args.new_bucket!r}")
    if args.dry_run:
        print("(dry-run — no files will be written)")

    total_changed = 0
    failures: list[tuple[Path, str]] = []

    for csv_path in deduped:
        try:
            status, changed = rewrite_csv(
                csv_path,
                old_bucket=args.old_bucket,
                new_bucket=args.new_bucket,
                backup=not args.no_backup,
                dry_run=args.dry_run,
            )
            suffix = f" ({changed} row(s) changed)" if changed else ""
            print(f"[{status}] {csv_path}{suffix}")
            total_changed += changed
        except Exception as exc:
            failures.append((csv_path, str(exc)))
            print(f"[error] {csv_path}: {exc}")

    if failures:
        print("\nFinished with errors:")
        for p, msg in failures:
            print(f"  - {p}: {msg}")
        return 1

    print(f"\nDone. {total_changed} row(s) updated across {len(deduped)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

