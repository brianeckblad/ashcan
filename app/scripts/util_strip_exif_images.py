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


# Ansible vault key → uppercase env-style key used by app/config.py
_VAULT_KEY_MAP = {
    "s3_bucket_name":            "S3_BUCKET_NAME",
    "s3_folder":                 "S3_FOLDER",
    "aws_region":                "AWS_REGION",
    "secret_name":               "SECRET_NAME",
    # Direct AWS keys (rarely in vault — IAM role is preferred in production)
    "aws_access_key_id":         "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key":     "AWS_SECRET_ACCESS_KEY",
    # Deploy-user keys (auto-populated by create-deploy-user.yml)
    "deploy_aws_access_key_id":     "AWS_ACCESS_KEY_ID",
    "deploy_aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
}


def _load_secrets_from_vault(vault_password_file: str) -> dict:
    """Decrypt deployment/group_vars/vault.yml and extract S3 credentials.

    Uses ``ansible-vault view`` to decrypt + ``yaml.safe_load()`` to parse —
    the same approach as ``deployment/scripts/local_dev_setup_env.py``.
    Falls back to a simple line parser if PyYAML is not installed.

    Only extracts the keys listed in ``_VAULT_KEY_MAP`` — no sensitive
    values are logged.

    Args:
        vault_password_file: Path to the vault password file (e.g. ``~/.vault_pass``).

    Returns:
        Dict of uppercase config-style keys (e.g. ``S3_BUCKET_NAME``), or an
        empty dict if decryption fails.
    """
    import subprocess

    vault_path = PROJECT_ROOT / "deployment" / "group_vars" / "vault.yml"
    password_file = Path(vault_password_file).expanduser()

    if not vault_path.exists():
        print(f"  [vault] vault file not found: {vault_path}")
        return {}
    if not password_file.exists():
        print(f"  [vault] password file not found: {password_file}")
        return {}

    print(f"  [vault] decrypting {vault_path.relative_to(PROJECT_ROOT)} ...")
    try:
        result = subprocess.run(
            ["ansible-vault", "view", str(vault_path),
             "--vault-password-file", str(password_file)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        print("  [vault] ansible-vault not found — is ansible installed?")
        return {}
    except subprocess.TimeoutExpired:
        print("  [vault] ansible-vault timed out")
        return {}

    if result.returncode != 0:
        print(f"  [vault] decryption failed: {result.stderr.strip()}")
        return {}

    # Parse YAML content — use PyYAML when available (same as local_dev_setup_env.py)
    vault_data: dict = {}
    try:
        import yaml
        parsed = yaml.safe_load(result.stdout)
        if isinstance(parsed, dict):
            vault_data = parsed
    except ImportError:
        # PyYAML not installed — fall back to a simple line parser.
        # Handles:  key: value  and  key: "value"  (but not complex YAML).
        import re
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("---"):
                continue
            match = re.match(r'^([a-z_][a-z0-9_]*):\s*["\']?([^"\'#\n]+?)["\']?\s*(?:#.*)?$', line)
            if match:
                vault_data[match.group(1)] = match.group(2).strip()
    except Exception as exc:
        print(f"  [vault] YAML parse error: {exc}")
        return {}

    # Map ansible lowercase keys → uppercase app config keys.
    # First resolve simple intra-vault Jinja2 references like {{ app_name }}
    # (Ansible allows one variable to reference another in the same file).
    import re as _re

    def _resolve(value: str, lookup: dict) -> str:
        """Replace {{ var }} references with values from the same vault dict."""
        def _subst(m):
            ref = m.group(1).strip()
            return str(lookup.get(ref, m.group(0)))  # leave unresolved refs as-is
        return _re.sub(r'\{\{\s*(\w+)\s*\}\}', _subst, str(value))

    creds: dict = {}
    for ansible_key, config_key in _VAULT_KEY_MAP.items():
        value = vault_data.get(ansible_key)
        if value is not None and str(value).strip():
            resolved = _resolve(str(value).strip(), vault_data)
            creds[config_key] = resolved

    found = list(creds.keys())
    print(f"  [vault] OK — extracted keys: {found}")
    return creds


def _load_all_credentials(vault_password_file: str | None = None) -> dict:
    """Return a merged credential dict using the same priority as app/config.py.

    Priority (highest → lowest):
      1. AWS Secrets Manager  — production EC2 via IAM role
      2. Ansible vault        — when --vault-password-file is passed
      3. .env file            — local dev generated from vault
      4. Environment vars     — CI / manual override

    Secrets Manager wins over everything else so the script behaves
    identically to the running app on the server.
    """
    # Tier 1 — AWS Secrets Manager (production)
    sm_creds = _load_secrets_from_aws()

    # Tier 2 — Ansible vault (explicit --vault-password-file flag)
    vault_creds: dict = {}
    if vault_password_file:
        vault_creds = _load_secrets_from_vault(vault_password_file)

    # Tier 3 — .env file (local dev)
    env_file_creds = _load_env_file(PROJECT_ROOT / ".env")

    # Tier 4 — live environment variables (lowest priority)
    # Merge: env vars → .env → vault → Secrets Manager (SM wins)
    creds = dict(os.environ)
    creds.update(env_file_creds)
    creds.update(vault_creds)
    creds.update(sm_creds)

    # Report which tier resolved the bucket name
    bucket_key = "S3_BUCKET_NAME" if "S3_BUCKET_NAME" in creds else "S3_BUCKET"
    if bucket_key in sm_creds:
        source = "Secrets Manager"
    elif bucket_key in vault_creds:
        source = "Ansible vault"
    elif bucket_key in env_file_creds:
        source = ".env file"
    elif bucket_key in os.environ:
        source = "environment variable"
    else:
        source = "NOT FOUND"
    print(f"  [credentials] {bucket_key} resolved from: {source}")

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
# S3-direct helpers  (used when no local images exist, e.g. on dev machine)
# ---------------------------------------------------------------------------
def _list_s3_users_and_images(s3_client, bucket: str, s3_folder: str,
                               username_filter: str | None) -> list:
    """Scan S3 and return a list of (username, s3_key) pairs for full-size images.

    Looks in:
      • users/{username}/images/{file}  — multi-user layout
      • {s3_folder}/images/{file}       — legacy single-user layout (username="default")

    Thumbnails (_thumb) are excluded.
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    results = []  # [(username, s3_key), ...]

    def _collect(prefix, username):
        if username_filter and username != username_filter:
            return
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                filename = key.split("/")[-1]
                if filename and "_thumb" not in filename:
                    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                    if ext in IMAGE_EXTENSIONS:
                        results.append((username, key))

    # Multi-user: scan users/*/images/
    try:
        top = s3_client.list_objects_v2(Bucket=bucket, Prefix="users/", Delimiter="/")
        for cp in top.get("CommonPrefixes", []):
            # cp["Prefix"] = "users/{username}/"
            parts = cp["Prefix"].rstrip("/").split("/")
            if len(parts) == 2:
                uname = parts[1]
                _collect(f"users/{uname}/images/", uname)
    except Exception as exc:
        print(f"  [S3 scan] warning listing users/ prefix: {exc}")

    # Legacy single-user: {s3_folder}/images/
    _collect(f"{s3_folder}/images/", "default")

    return results


def _process_from_s3(s3_client, bucket: str, s3_folder: str,
                     username_filter: str | None, dry_run: bool) -> dict:
    """Download every full-size image from S3, strip EXIF, re-upload clean.

    Works entirely in temp files — no permanent local storage required.
    Returns summary dict: {'total', 'processed', 'errors'}.
    """
    import tempfile

    print("Scanning S3 for images...")
    all_images = _list_s3_users_and_images(s3_client, bucket, s3_folder, username_filter)

    summary = {"total": len(all_images), "processed": 0, "errors": 0}

    if not all_images:
        print("  No images found in S3.")
        return summary

    # Group by username for readable output
    by_user: dict = {}
    for username, s3_key in all_images:
        by_user.setdefault(username, []).append(s3_key)

    print(f"  Found {len(all_images)} image(s) across {len(by_user)} user(s)")
    print()

    for username, keys in sorted(by_user.items()):
        print(f"{'─' * 70}")
        print(f"User: {username}  ({len(keys)} images)")
        print(f"{'─' * 70}")

        for i, s3_key in enumerate(sorted(keys), 1):
            filename = s3_key.split("/")[-1]
            print(f"  [{i}/{len(keys)}] {filename}")

            if dry_run:
                print(f"    Would download, strip EXIF, re-upload → {s3_key}")
                summary["processed"] += 1
                continue

            # Use a temp directory so the download and clean file are on the
            # same filesystem (enables efficient rename / avoids cross-device copy)
            with tempfile.TemporaryDirectory(prefix="exif_strip_") as tmpdir:
                tmp_dir = Path(tmpdir)
                download_path = tmp_dir / filename
                clean_path = tmp_dir / f"{Path(filename).stem}_clean.jpg"

                try:
                    # 1. Download from S3
                    s3_client.download_file(bucket, s3_key, str(download_path))
                except Exception as exc:
                    print(f"    ✗ Download failed: {exc}")
                    summary["errors"] += 1
                    continue

                # 2. Strip EXIF by re-encoding through PIL
                if not strip_exif_to_file(download_path, clean_path):
                    summary["errors"] += 1
                    continue

                # 3. Re-upload the clean version, replacing the original key
                if not _upload_file(s3_client, bucket, clean_path, s3_key):
                    summary["errors"] += 1
                    continue

                print(f"    ✓ Stripped + re-uploaded")
                summary["processed"] += 1
            # TemporaryDirectory cleanup happens automatically on context exit

        print()

    return summary
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
    parser.add_argument(
        "--vault-password-file",
        metavar="FILE",
        help="Decrypt deployment/group_vars/vault.yml with this password file "
             "(e.g. ~/.vault_pass) to read S3 credentials",
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
    creds = _load_all_credentials(vault_password_file=args.vault_password_file)
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
        print(f"AWS auth   : explicit key (from vault/env)")
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_key,
            aws_secret_access_key=aws_secret,
            region_name=aws_region,
        )
    else:
        # Fall back to the default credential chain:
        #   ~/.aws/credentials  (configured by configure-local-aws.yml)
        #   EC2 IAM role        (on the server)
        print(f"AWS auth   : default credential chain (~/.aws or IAM role)")
        s3_client = boto3.client("s3", region_name=aws_region)

    # Quick connectivity check before doing any real work
    try:
        s3_client.head_bucket(Bucket=bucket)
        print(f"S3 access  : OK")
    except Exception as exc:
        err = str(exc)
        print(f"S3 access  : FAILED — {err}")
        if "NoCredentialsError" in err or "Unable to locate credentials" in err:
            print()
            print("  No AWS credentials found. Options:")
            print("  1. Run configure-local-aws.yml to set up ~/.aws profile:")
            print("       cd deployment && ansible-playbook playbooks/configure-local-aws.yml \\")
            print("           --vault-password-file ~/.vault_pass")
            print("  2. Export credentials manually:")
            print("       export AWS_ACCESS_KEY_ID=...")
            print("       export AWS_SECRET_ACCESS_KEY=...")
        return 1

    print(f"S3 bucket  : {bucket}")
    print(f"S3 folder  : {s3_folder}")
    print(f"AWS region : {aws_region}")
    print()

    # Discover local users / images
    all_users = _discover_users(DATA_DIR, INSTANCE_DIR)
    if args.user:
        all_users = [(u, d) for u, d in all_users if u == args.user]

    user_image_counts = [(u, d, _find_full_size_images(d)) for u, d in all_users]
    total_local = sum(len(imgs) for _, _, imgs in user_image_counts)

    # ------------------------------------------------------------------
    # Choose execution mode
    # ------------------------------------------------------------------
    if total_local > 0:
        # LOCAL MODE — images exist on this machine; process in-place
        print(f"Mode: LOCAL  ({total_local} image(s) found in instance/data/)")
        print()

        if not args.dry_run:
            print("This will:")
            print(f"  • Re-encode {total_local} full-size image(s) as clean JPEG (EXIF removed)")
            print(f"  • Overwrite each local file with the clean version")
            print(f"  • Upload each clean file to S3, replacing the original")
            print()
            response = input("Continue? [y/N]: ")
            if response.lower() != "y":
                print("Cancelled.")
                return 0
            print()

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

    else:
        # S3-DIRECT MODE — no local images; download → strip EXIF → re-upload
        # This is the normal path when running from a dev machine.
        if args.user:
            print(f"Mode: S3-DIRECT  (no local images found; will process user '{args.user}' from S3)")
        else:
            print("Mode: S3-DIRECT  (no local images found; will download, strip, and re-upload from S3)")
        print()

        if not args.dry_run:
            target = f"user '{args.user}'" if args.user else "all users"
            print("This will:")
            print(f"  • Download every full-size image ({target}) from S3 to a temp file")
            print(f"  • Re-encode as clean JPEG (EXIF removed)")
            print(f"  • Re-upload the clean version to S3, replacing the original")
            print(f"  • Delete the temp file immediately after each image")
            print()
            response = input("Continue? [y/N]: ")
            if response.lower() != "y":
                print("Cancelled.")
                return 0
            print()

        summary = _process_from_s3(
            s3_client, bucket, s3_folder,
            username_filter=args.user,
            dry_run=args.dry_run,
        )
        grand_total = summary["total"]
        grand_processed = summary["processed"]
        grand_errors = summary["errors"]

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

