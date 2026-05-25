#!/usr/bin/env python3
"""
Strip EXIF from All Images

Retroactively removes EXIF metadata (GPS coordinates, camera make/model,
timestamps, lens info, etc.) from every full-size image stored locally
and on S3.

The script:
  1. Discovers all registered users by scanning instance/data/
  2. For each user, finds every full-size image (skips _thumb files)
  3. Re-encodes each image through PIL as a clean JPEG — PIL does not
     propagate EXIF when saving to a new file, so the output is clean
  4. Overwrites the local file with the clean version
  5. Uploads the clean version to S3, replacing the original

No database or Flask app context is required — credentials are loaded
directly from the project .env file (or from the environment).

Usage:
    cd /path/to/ashcan
    python app/scripts/util_strip_exif_images.py [--dry-run] [--user USERNAME]

Options:
    --dry-run         Show what would be done without modifying any files
    --user USERNAME   Process only this user (default: all users)

Examples:
    # Preview what would change (safe — no files touched)
    python app/scripts/util_strip_exif_images.py --dry-run

    # Strip EXIF for a single user
    python app/scripts/util_strip_exif_images.py --user brian

    # Strip EXIF for all users
    python app/scripts/util_strip_exif_images.py
"""

import argparse
import os
import sys
from pathlib import Path

# Resolve project root: app/scripts/util_strip_exif_images.py → ../../..
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402 — PIL must come after sys.path adjustment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INSTANCE_DIR = PROJECT_ROOT / "instance"
DATA_DIR = INSTANCE_DIR / "data"

# Extensions to process (full-size images only; thumbnails are already clean)
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"})

# JPEG quality for the re-encoded output — matches the rest of the app
JPEG_QUALITY = 100


# ---------------------------------------------------------------------------
# Credential loading — mirrors app/config.py priority order:
#   1. AWS Secrets Manager  (production: IAM role on EC2, no keys needed)
#   2. .env file            (local dev: generated from vault)
#   3. Environment vars     (CI / manual override)
# ---------------------------------------------------------------------------
def _load_secrets_from_aws() -> dict:
    """Fetch the app secrets from AWS Secrets Manager.

    Determines the secret name by checking (in order):
      1. ``SECRET_NAME`` environment variable (set by supervisor in the app process
         but NOT inherited when running scripts directly from the shell)
      2. The supervisor conf file  ``/etc/supervisor/conf.d/*.conf``  —
         parses the ``environment=`` line so shell sessions pick up the same
         value the app process uses without requiring a manual ``export``
      3. Hardcoded default ``ashcan/production``

    On EC2 the IAM role grants Secrets Manager access automatically — no AWS
    keys required.  Prints status so the operator can see exactly what was
    tried.  Returns an empty dict on failure so callers fall through to
    .env / environment variables.
    """
    import base64
    import json as _json
    import re

    try:
        import boto3
    except ImportError:
        print("  [secrets-manager] boto3 not installed — skipping")
        return {}

    # --- Determine SECRET_NAME ---
    secret_name = os.environ.get("SECRET_NAME")
    source = "environment variable"

    if not secret_name:
        # Try to read SECRET_NAME from the supervisor conf that the app uses.
        # The conf file is at /etc/supervisor/conf.d/{app_name}.conf and
        # contains a line like:
        #   environment=PATH="...",SECRET_NAME="ashcan/production",AWS_REGION="..."
        supervisor_conf_dir = Path("/etc/supervisor/conf.d")
        if supervisor_conf_dir.exists():
            for conf_file in supervisor_conf_dir.glob("*.conf"):
                try:
                    text = conf_file.read_text()
                    match = re.search(r'SECRET_NAME="([^"]+)"', text)
                    if match:
                        secret_name = match.group(1)
                        source = f"supervisor conf ({conf_file.name})"
                        # Also extract AWS_REGION while we're here
                        region_match = re.search(r'AWS_REGION="([^"]+)"', text)
                        if region_match and not os.environ.get("AWS_REGION"):
                            os.environ["AWS_REGION"] = region_match.group(1)
                        break
                except OSError:
                    continue

    if not secret_name:
        secret_name = "ashcan/production"
        source = "hardcoded default"

    region = os.environ.get("AWS_REGION", "us-east-2")
    print(f"  [secrets-manager] secret '{secret_name}' (from {source}), region {region}")

    try:
        client = boto3.session.Session().client(
            service_name="secretsmanager", region_name=region
        )
        response = client.get_secret_value(SecretId=secret_name)

        if "SecretString" in response:
            data = _json.loads(response["SecretString"])
        else:
            data = _json.loads(base64.b64decode(response["SecretBinary"]))

        # Show which relevant keys were found (never print values)
        found = [k for k in ("S3_BUCKET_NAME", "S3_BUCKET", "S3_FOLDER", "AWS_REGION") if k in data]
        print(f"  [secrets-manager] OK — found keys: {found}")
        return data

    except Exception as exc:
        print(f"  [secrets-manager] FAILED: {exc}")
        print(f"  [secrets-manager] Falling through to .env / environment variables")
        return {}


def _load_env_file(env_path: Path) -> dict:
    """Parse key=value pairs from a .env file.

    Ignores blank lines and comments. Strips surrounding quotes from values.
    """
    env: dict = {}
    if not env_path.exists():
        return env
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _load_all_credentials() -> dict:
    """Return a merged credential dict using the same priority as app/config.py.

    Secrets Manager values win over .env values, which win over env vars.
    Prints a summary of which tier each critical key came from.
    """
    # Tier 1 — AWS Secrets Manager (production)
    sm_creds = _load_secrets_from_aws()

    # Tier 2 — .env file (local dev)
    env_file_creds = _load_env_file(PROJECT_ROOT / ".env")

    # Tier 3 — live environment variables (lowest priority)
    # Build merged dict: SM wins over .env wins over env vars
    creds = dict(os.environ)           # start with env vars
    creds.update(env_file_creds)       # .env overrides env vars
    creds.update(sm_creds)             # Secrets Manager wins over both

    # Report which tier resolved the bucket name
    bucket_key = "S3_BUCKET_NAME" if "S3_BUCKET_NAME" in creds else "S3_BUCKET"
    if bucket_key in sm_creds:
        print(f"  [credentials] {bucket_key} resolved from Secrets Manager")
    elif bucket_key in env_file_creds:
        print(f"  [credentials] {bucket_key} resolved from .env file")
    elif bucket_key in os.environ:
        print(f"  [credentials] {bucket_key} resolved from environment variable")
    else:
        print(f"  [credentials] {bucket_key} NOT found in any source")

    return creds


# ---------------------------------------------------------------------------
# EXIF stripping
# ---------------------------------------------------------------------------
def strip_exif_to_file(source: Path, dest: Path) -> bool:
    """Re-encode *source* as a clean JPEG at *dest* with all EXIF stripped.

    PIL does not copy metadata (EXIF, XMP, IPTC) when saving to a new file
    unless the caller explicitly passes ``exif=`` data. A plain ``img.save()``
    therefore produces a metadata-free file.

    Handles mode conversion (RGBA → RGB with white background, CMYK → RGB,
    palette → RGB) so the output is always a valid JPEG.

    Returns True on success, False if an error occurs (caller reads the
    return value and should not attempt to use *dest* on failure).
    """
    try:
        with Image.open(source) as img:
            if img.mode in ("RGBA", "LA", "P"):
                # Flatten alpha onto a white background — JPEG has no alpha channel
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                if img.mode in ("RGBA", "LA"):
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Save without any exif= kwarg — PIL omits all metadata by default
            img.save(dest, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return True

    except Exception as exc:
        print(f"    ✗ Failed to re-encode {source.name}: {exc}")
        return False


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------
def _s3_key_for_image(username: str, filename: str, s3_folder: str) -> str:
    """Return the S3 object key for a given user's image filename.

    Mirrors the key structure used by s3_service / user_context:
      - Named users   → users/{username}/images/{filename}
      - Default user  → {s3_folder}/images/{filename}  (legacy single-user)
    """
    if username == "default":
        return f"{s3_folder}/images/{filename}"
    return f"users/{username}/images/{filename}"


def _upload_file(s3_client, bucket: str, local_path: Path, s3_key: str) -> bool:
    """Upload *local_path* to S3 at *s3_key*, overwriting any existing object."""
    try:
        s3_client.upload_file(str(local_path), bucket, s3_key)
        return True
    except Exception as exc:
        print(f"    ✗ S3 upload failed ({s3_key}): {exc}")
        return False


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------
def _find_full_size_images(images_dir: Path) -> list:
    """Return a sorted list of full-size image Paths, excluding thumbnails."""
    if not images_dir.exists():
        return []
    return sorted(
        p
        for p in images_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in IMAGE_EXTENSIONS
        and "_thumb" not in p.name
    )


def _discover_users(data_dir: Path, instance_dir: Path) -> list:
    """Return a list of (username, images_dir) pairs.

    Scans instance/data/{username}/images/ for multi-user setups and also
    checks the legacy instance/images/ path for any pre-migration images.
    """
    users = []

    if data_dir.exists():
        for user_dir in sorted(data_dir.iterdir()):
            if user_dir.is_dir():
                users.append((user_dir.name, user_dir / "images"))

    # Legacy single-user path
    legacy_dir = instance_dir / "images"
    if legacy_dir.exists() and _find_full_size_images(legacy_dir):
        users.append(("default", legacy_dir))

    return users


# ---------------------------------------------------------------------------
# Per-user processing
# ---------------------------------------------------------------------------
def _process_user(
    username: str,
    images_dir: Path,
    s3_client,
    bucket: str,
    s3_folder: str,
    dry_run: bool,
) -> dict:
    """Strip EXIF from every full-size image for one user.

    Returns a summary dict: {'total', 'processed', 'errors'}.
    """
    images = _find_full_size_images(images_dir)
    summary = {"total": len(images), "processed": 0, "errors": 0}

    if not images:
        print("  No images found — skipping.")
        return summary

    for i, img_path in enumerate(images, 1):
        s3_key = _s3_key_for_image(username, img_path.name, s3_folder)
        print(f"  [{i}/{len(images)}] {img_path.name}")

        if dry_run:
            print(f"    Would strip EXIF → overwrite local + upload to {s3_key}")
            summary["processed"] += 1
            continue

        # Write clean version to a sibling temp file.  Using a fixed suffix
        # (not tempfile.mktemp) keeps it on the same filesystem for an atomic
        # rename at the end.
        tmp_path = img_path.with_suffix("._clean_tmp.jpg")
        try:
            if not strip_exif_to_file(img_path, tmp_path):
                summary["errors"] += 1
                continue

            if not _upload_file(s3_client, bucket, tmp_path, s3_key):
                summary["errors"] += 1
                continue

            # Atomic replace: tmp → original (same filesystem, no window where
            # the local file is absent)
            tmp_path.replace(img_path)
            print(f"    ✓ Stripped + uploaded")
            summary["processed"] += 1

        except Exception as exc:
            print(f"    ✗ Unexpected error: {exc}")
            summary["errors"] += 1

        finally:
            # Belt-and-braces cleanup in case replace() raised above
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Strip EXIF metadata from all images locally and in S3"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying any files",
    )
    parser.add_argument(
        "--user",
        metavar="USERNAME",
        help="Process only this user (default: all users)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Strip EXIF from Images")
    print("=" * 70)
    if args.dry_run:
        print("Mode: DRY RUN — no files will be changed")
    print()

    # Load credentials using the same priority as app/config.py:
    #   1. AWS Secrets Manager (production EC2 with IAM role — no keys needed)
    #   2. .env file (local dev)
    #   3. Environment variables (CI / manual override)
    print("Loading credentials...")
    creds = _load_all_credentials()
    aws_key = creds.get("AWS_ACCESS_KEY_ID")
    aws_secret = creds.get("AWS_SECRET_ACCESS_KEY")
    aws_region = creds.get("AWS_REGION", "us-east-2")
    bucket = creds.get("S3_BUCKET_NAME") or creds.get("S3_BUCKET")
    s3_folder = creds.get("S3_FOLDER", "production")

    if not bucket:
        print()
        print("ERROR: S3 bucket name not found in any credential source.")
        print("       Checked (in order):")
        print("         1. AWS Secrets Manager  (key: S3_BUCKET_NAME or S3_BUCKET)")
        print("         2. .env file at project root")
        print("         3. Environment variables S3_BUCKET_NAME / S3_BUCKET")
        print()
        print("       On the server, ensure SECRET_NAME env var points to the")
        print("       correct Secrets Manager secret (check supervisor.conf).")
        print("       Locally, run: python deployment/scripts/local_dev_setup_env.py")
        return 1

    # Build S3 client
    try:
        import boto3  # noqa: PLC0415 — optional dependency, checked at runtime
    except ImportError:
        print("ERROR: boto3 is not installed. Run: pip install boto3")
        return 1

    if aws_key and aws_secret:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret,
            region_name=aws_region,
        )
    else:
        # Fall back to the default credential chain (IAM role, ~/.aws/credentials)
        s3_client = boto3.client("s3", region_name=aws_region)

    print(f"S3 bucket : {bucket}")
    print(f"S3 folder : {s3_folder}")
    print()

    # Discover users
    all_users = _discover_users(DATA_DIR, INSTANCE_DIR)
    if args.user:
        all_users = [(u, d) for u, d in all_users if u == args.user]
        if not all_users:
            print(f"ERROR: No image directory found for user '{args.user}'")
            return 1

    if not all_users:
        print("No users with image directories found. Nothing to do.")
        return 0

    # Count total work upfront so the confirmation prompt is informative
    user_image_counts = [(u, d, _find_full_size_images(d)) for u, d in all_users]
    total_images = sum(len(imgs) for _, _, imgs in user_image_counts)

    print(f"Users found : {len(all_users)}")
    print(f"Images found: {total_images}")
    print()

    if total_images == 0:
        print("No images to process. Nothing to do.")
        return 0

    if not args.dry_run:
        print("This will:")
        print(f"  • Re-encode {total_images} full-size image(s) as clean JPEG (EXIF removed)")
        print(f"  • Overwrite each local file with the clean version")
        print(f"  • Upload each clean file to S3, replacing the original")
        print()
        response = input("Continue? [y/N]: ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0
        print()

    # Process each user
    grand_total = grand_processed = grand_errors = 0
    for username, images_dir, _ in user_image_counts:
        print(f"{'─' * 70}")
        print(f"User: {username}  ({images_dir})")
        print(f"{'─' * 70}")
        summary = _process_user(
            username, images_dir, s3_client, bucket, s3_folder, args.dry_run
        )
        grand_total += summary["total"]
        grand_processed += summary["processed"]
        grand_errors += summary["errors"]
        print()

    # Final summary
    print("=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"  Total images : {grand_total}")
    print(f"  Processed    : {grand_processed}")
    print(f"  Errors       : {grand_errors}")
    if args.dry_run:
        print()
        print("  (Dry run — no files were changed)")
    print("=" * 70)

    return 0 if grand_errors == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n\nUnexpected fatal error: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

