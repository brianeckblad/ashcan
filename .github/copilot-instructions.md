# Copilot Instructions: Dockyard

**These instructions are automatically loaded for every Copilot session in this project.**

---

## Session Memory - READ FIRST EVERY SESSION

AI agents have **no memory between conversations**. To bridge that, this repo
keeps a local session-notes file the agent reads at the start of every session
and appends to on request.

**File:** `.copilot/SESSION_NOTES.md` (gitignored, local working memory only)

### At the start of every session

1. Use the `read_file` tool to read `.copilot/SESSION_NOTES.md` if it exists.
2. If it has session entries, briefly summarize the most recent 1–2 entries to
   the user before starting new work, so they can confirm the context is right.
3. If it does not exist or is empty, proceed normally.

### Trigger phrases the user can say

Short forms are the primary triggers. Longer natural-language forms still work.

| User says | Agent does |
|-----------|------------|
| `ck` / `checkpoint` / `save context` / `remember this` | Append a new dated entry to the **Sessions** section using the template in the file. |
| `ctx` / `show context` / `recall` / `what were we doing` | Read the file and summarize recent entries. |
| `wipe` / `clear memory` / `start fresh` / `forget everything` | Truncate the file's **Sessions** section (keep the header), confirm what was cleared. |
| `arc` / `archive memory` | Move all session entries to `.copilot/SESSION_NOTES.archive.md`, then clear. |

A short trigger (`ck`, `ctx`, `wipe`, `arc`) is a command only when it is the
entire user message. Inside a longer sentence, treat it as normal text.

### Proactively offer to checkpoint when

- A non-trivial decision was just made (architecture, library choice, abandoned approach).
- The user is about to switch tasks or branches.
- A long debugging session just resolved.

---

## IDE Diagnostic False Positives — Known Noise

Before acting on any IDE diagnostic, identify its category.

### Authoritative validators

| Context | Real validator | IDE diagnostics |
|---------|---------------|-----------------|
| Python | `python3 -m py_compile file.py` | Mostly trustworthy, except Flask note below |
| JS inside `.html` | `node --check extracted-js.js` | **High noise — do not chase** |

### False positive categories (do NOT fix these)

| Category | IDE message | Why it's false |
|----------|-------------|----------------|
| **JS template literals** | `Unused constant x` / `Expression expected` / `Closing '}' expected` | Variables used inside `${x}` are invisible to the HTML parser |
| **Flask route returns** | `Expected type 'Response', got 'tuple[Response, int]'` | `(jsonify(...), 400)` IS correct Flask — JetBrains can't infer the union type |
| **SVG self-closing tags** | `Empty tag doesn't work in some browsers` | `<path/>`, `<circle/>`, `<rect/>` are valid HTML5/SVG |
| **onclick-wired params** | `Unused parameter x` | Functions called by HTML `onclick` — IDE can't see the caller |
| **Missing label** | `Missing associated label` | Hidden inputs and internal state fields don't need visible labels |
| **throw in try/catch** | `'throw' of exception caught locally` | Intentional re-throw pattern for error propagation |

**Key rule:** `node --check` passing clean means JS is correct. IDE template errors in `.html`
files are noise from the HTML parser misreading JS — ignore them.

---

## Shell Command Safety - CRITICAL

### Never Output Jinja2 Braces Through the Terminal

The zsh shell interprets `{{ }}` as glob patterns. Commands that output Jinja2 content will hang or produce empty output.

```bash
# BAD - causes empty output or hangs
cat file_with_jinja.yml
grep "pattern" file_with_jinja.yml

# GOOD - use the read_file / grep_search tools instead (they bypass the shell)
# GOOD - if terminal is required, use Python:
python3 -c "print(open('file.yml').read()[:500])"
```

### Never Use Unquoted Heredocs with Dynamic Content

```bash
# BAD - shell interprets {{ }} and $vars, causes heredoc> hang
cat > file.yml << EOF
name: "{{ app_name }}"
EOF

# GOOD - single-quote the delimiter
cat > file.yml << 'EOF'
name: "{{ app_name }}"
EOF

# BEST - use Python or the insert_edit_into_file tool to write files
```

### Prefer Non-Terminal Tools

| Task | Use This | Not This |
|------|----------|----------|
| Read a file | `read_file` tool | `cat` / `head` / `tail` in terminal |
| Search in file | `grep_search` tool | `grep` in terminal |
| Write / edit a file | `insert_edit_into_file` or `replace_string_in_file` tool | `cat > file << EOF` in terminal |
| Verify edits applied | `read_file` tool | `cat file` in terminal |

### If Terminal Hangs (no output, or dquote> / heredoc> / quote>)

1. **Do NOT keep waiting** - it will not recover
2. **Run a new terminal command** - the tool starts a fresh session
3. **Switch to a non-terminal tool** to accomplish the task

### Ansible Playbooks

- Run with `isBackground: true` and retrieve output with `get_terminal_output` for long-running playbooks
- Pipe short playbook runs through `2>&1` to capture all output

---

## Git Branching Rules

**Default: do not create feature branches.** Commit directly to whatever branch
the user is currently on (typically `main`). The user controls branching
strategy — only create a branch when the user explicitly asks for one.

If you genuinely believe a branch is warranted (large refactor, risky
multi-step change), **ask before creating it** — do not create one preemptively.

---

## Git Commit Rules

```bash
# ALWAYS - simple messages, no internal quotes
git commit -m "docs: add deployment guide"
git commit -m "fix: correct IAM role permissions"

# NEVER - nested quotes cause dquote> hangs
git commit -m "docs: add 'comprehensive' guide"

# FOR COMPLEX MESSAGES - use file method
cat > /tmp/msg.txt << 'EOF'
feat: multi-line commit message

- Detail one
- Detail two
EOF
git commit -F /tmp/msg.txt && rm /tmp/msg.txt
```

---

## General Python Coding Standards

These supplement the language-specific rules in the Flask Security Rules section below.

- **Never `str(e)` in JSON responses** — use `safe_error_message(e)` from `app/utils/logging_utils.py`. Full detail goes to the logger only.
- **All imports at module level** — never inside functions, route handlers, or `except` blocks. Two allowed exceptions (both require a comment): `# Deferred: avoids circular import` and `# Deferred: requires Flask app context`.
- **Initialize before `try`** — any variable referenced in `except`/`finally` must be assigned before the `try` block, not inside it.
- **Use Pythonic style** — follow PEP 8 and PEP 257. `snake_case` names, clear docstrings.
- **Prefer named callables over inline `lambda`** — use `def` for any non-trivial logic.
- **Use type hints where applicable** — annotate public functions/methods and complex return types.
- **Format with `black` and sort imports with `isort`** — keep import order stable.
- **Catch specific exceptions first** — avoid broad `except Exception` unless you log and re-raise.
- **No side effects at import time** — module import should define symbols only.

---

## Project Context

- **App name:** Dockyard — a comic book inventory and listing management tool
- **Stack:** Python / Flask with Ansible deployment to AWS EC2
- **Storage:** CSV files (inventory), AWS S3 (images + exports), JSON (user preferences) — no database
- **Shell:** zsh on macOS
- **Entry points:** `runapp.py` (web server), `main.py` (CLI batch/S3 utility)
- **Deployment config:** `deployment/` directory with Ansible playbooks, group_vars, vault
- **Ansible variables:** All configuration in encrypted `deployment/group_vars/vault.yml`
- **Vault secrets:** Access with `ansible-vault view group_vars/vault.yml --vault-password-file ~/.vault_pass`
- **Secrets in production:** AWS Secrets Manager at `dockyard/production` via `get_secret()` in `app/config.py`
- **S3 bucket name:** Comes from `S3_BUCKET_NAME` in vault (not derived from `app_name`)
- **Local dev:** Generate `.env` from vault via `deployment/scripts/local_dev_setup_env.py`, or fill in manually
- **No test suite:** The project has no automated tests and no CI/CD pipeline

---

## Interaction Style

Think like a comic collector and seller:
- Users manage inventory to sell on eBay and WhatNot
- Prioritize friction-free listing flows over decorative UI changes
- Keep bulk operations fast and reliable — sellers move high volume
- Keep the dark yellow-accent design palette consistent; color communicates action state, not decoration
- Emphasize data the seller needs: SKU, title, condition, price, listing status

---

## Coding Workflow

- Start from clear requirements; if scope is ambiguous, propose small options before implementing.
- Prefer small, focused edits that preserve existing behavior unless a change is requested.
- Keep naming and structure consistent with the current codebase.
- There is no smoke test — validate Python changes with `python3 -m py_compile` and JS changes with `node --check`.
- Highlight risks, assumptions, and missing data explicitly instead of silently guessing.
- Optimize for maintainability: straightforward code paths, minimal side effects, clear data ownership.

---

## Architecture Overview

```
Browser
  │
  ▼
Nginx  (SSL termination, static files, rate limiting, offline error pages)
  │     deployment/templates/nginx.conf.j2 — rate zones, error_page → app/static/
  ▼
Gunicorn WSGI  (gunicorn.conf.py — workers=2×CPU+1, bind=127.0.0.1:8000)
  │
  ▼
Flask app factory  create_app()  in  app/__init__.py
  │   On startup: load .env (dev) or pull from AWS Secrets Manager (prod)
  │   Sync user_preferences.json ↔ S3 (mtime wins)
  │   Sync per-user items.csv and sku.txt ↔ S3 (newest/highest wins)
  │   Cleanup expired trash items
  │   Background thread: sync images + exports ↔ S3, then run health check
  │
  ├── app/security.py          before_request — IP blocklist, attack detection,
  │                            global rate limit, periodic in-memory cleanup
  │
  ├── auth_bp     /login  /logout
  ├── main_bp     /  /browse  /add  /add-from-image  /trash  /download
  │               /price-lookup  /account  /ebay-listings  /analytics
  └── api_bp      /api/**  (67 routes across 11 modules)
        ├── admin.py          Admin settings and security (8 routes)
        ├── analytics.py      Analytics tracking (1 route)
        ├── comics.py         Comic CRUD operations (11 routes)
        ├── ebay.py           eBay listing operations (10 routes)
        ├── ebay_listings.py  eBay account listings management (3 routes)
        ├── ebay_search.py    eBay price lookup and search (4 routes)
        ├── ebay_taxonomy.py  eBay category/taxonomy operations (4 routes)
        ├── account.py        User account management (13 routes)
        ├── snapshots.py      Snapshot operations (4 routes)
        ├── system.py         System stats and utilities (6 routes)
        └── trash.py          Trash management (3 routes)
```

---

## Key File Roles (never mix these)

| File | Role |
|------|------|
| `app/__init__.py` | App factory, startup S3 sync, blueprint registration, eBay cache init, version injection |
| `app/config.py` | All config via `get_secret()` — never read `os.environ` directly in routes |
| `app/security.py` | IP blocklist, attack detection, global rate limit, cleanup sweep |
| `app/routes/auth.py` | `auth_bp`, `login_required`, `csrf_required`, `admin_required`, `sync_not_locked`, `disk_space_required` |
| `app/routes/api/` | Thin route handlers — validate input, call services, return JSON |
| `app/services/comic_service.py` | Comic CRUD orchestration (user-specific CSV + SKU) |
| `app/services/csv_service.py` | CSV read/write with file locking; all CSV writes go here |
| `app/services/s3_service.py` | S3 uploads, thumbnail generation (WebP), sync, restore |
| `app/services/ebay_service.py` | eBay API integration (search, list, end, relist, taxonomy) |
| `app/services/snapshot_service.py` | Manual backup/restore to S3 |
| `app/services/trash_service.py` | Soft-delete with 30-day retention |
| `app/services/health_check_service.py` | CSV ↔ S3 image consistency checks, orphan cleanup |
| `app/models/user.py` | `UserManager`: credentials, preferences, admin flag — stored in `instance/user_preferences.json` |
| `app/utils/user_context.py` | Per-request path resolution: `get_user_csv_file()`, `get_user_image_dir()`, `get_user_sku_file()`, etc. |
| `app/utils/logging_utils.py` | `safe_error_message(exc)` — **always use this in error responses, never `str(e)`** |
| `app/utils/csv_sanitizer.py` | CSV injection prevention (prefix `=`, `+`, `-`, `@` cells) |
| `app/utils/upload_security.py` | Image upload validation helpers |
| `app/utils/helpers.py` | `generate_csrf_token()`, filename generation, directory size |
| `app/utils/sync_state.py` | Thread-safe singleton for S3 sync progress / cross-worker lock |

---

## Multi-User Architecture

- `app/models/user.py` (`UserManager`) owns all user CRUD: `create_user`, `delete_user`, `update_password`, `credentials_valid`, `list_users`, `is_admin`.
- User preferences and credentials stored in `instance/user_preferences.json`, synced to S3.
- Per-user data lives at `instance/data/{username}/`:
  `items.csv`, `sku.txt`, `snapshots/`, `trash/`, `exports/`, and per-user images on S3.
- **All route handlers that need per-user paths** must use helpers from `app/utils/user_context.py`
  (`get_user_csv_file`, `get_user_sku_file`, `get_user_image_dir`, `get_user_trash_dir`, etc.)
  — never hand-craft `instance/data/{username}/...` strings manually.
- Username rules: 3–32 chars, alphanumeric + underscore + hyphen, validated by `validate_username()` in `app/routes/auth.py`.
- Authorization is always derived from `session['username']` — never from request parameters.

### Startup sync order

1. Sync `user_preferences.json` ↔ S3 (mtime wins; safety check if local has more users)
2. Load `UserManager` from the synced preferences to discover registered users
3. For each user: sync `sku.txt` (highest value wins), sync `items.csv` (newest mtime wins)
4. Background thread: sync images + exports ↔ S3, then run `HealthCheckService`

---

## Security Architecture

### Layer stack (outermost to innermost)

1. **Nginx** — SSL/TLS (TLS 1.2+), request body limit, static file serving, rate zones, offline error pages
2. **`app/security.py` `_security_gate`** — IP blocklist (persistent JSON), regex attack-pattern detection, auto-block after 5+ hits/60 s, global app-layer rate limit
3. **`app/routes/auth.py` decorators** — `login_required` (session check + restart invalidation), `csrf_required` (POST/PUT/DELETE), `admin_required`, `sync_not_locked`, `disk_space_required`
4. **Input validation** — every field validated in route handlers before touching storage
5. **Service layer** — `csv_service.py` file locking; `csv_sanitizer.py` on writes; `upload_security.py` on image uploads

### Authorization decorators (`app/routes/auth.py`)

| Decorator | Effect |
|-----------|--------|
| `login_required` | Returns 401/redirect if session absent; invalidates pre-restart sessions |
| `csrf_required` | Returns 403 if X-CSRF-Token header or `_csrf_token` form field does not match session token on POST/PUT/DELETE |
| `admin_required` | Returns 403 if session user is not admin |
| `sync_not_locked` | Returns 503 if S3 sync is currently running |
| `disk_space_required` | Returns 507 if disk is below threshold |

Stack decorators after the route decorator:

```python
@api_bp.post("/comic/<sku>")
@login_required
@csrf_required
def update_comic(sku):
    ...
```

### CSRF pattern

`app/utils/helpers.py` `generate_csrf_token()` is registered as a Jinja2 global.
`base.html` injects it as a `<meta name="csrf-token">` and in a JS variable.
All state-changing JS calls add `X-CSRF-Token` from that variable.
`@csrf_required` compares the session token against `request.headers.get('X-CSRF-Token')` or `request.form.get('_csrf_token')`.

### TOTP / session-security pattern

- TOTP enrollment must require the current password before enabling 2FA. A stolen active session alone must not be enough to enroll an attacker-controlled authenticator.
- TOTP setup secrets are short-lived setup state. Clear pending setup state after success or expiry; do not log TOTP secrets, QR payloads, or one-time codes.
- TOTP login is a two-step flow: password success creates `totp_pending`; only a valid TOTP code creates `logged_in=True`.
- Pending TOTP sessions must expire quickly (5 minutes), validate that the user still has TOTP enabled, and be rate-limited separately from password attempts.
- Session timestamps (`session_created`, `last_activity`, TOTP timestamps) must be coerced/validated before arithmetic so malformed or legacy sessions fail closed.
- Production cookies must always be `Secure`, `HttpOnly`, and `SameSite=Lax`; do not add environment overrides that disable secure cookies in production.

---

## Persistence Expectations

- `instance/data/{username}/items.csv` is the canonical per-user inventory record.
- All CSV writes go through `csv_service.py` — never `open(csv_path, 'w')` directly from a route.
- `instance/user_preferences.json` holds all user credentials and preferences; synced to S3 on every write.
- Images stored on S3 under `{S3_FOLDER}/{username}/images/`; thumbnails generated as WebP.
- `instance/data/` and log directories are gitignored — never commit them.

### Snapshot service

Snapshots are per-user ZIPs uploaded to S3 at `{S3_FOLDER}/{username}/snapshots/`.
Routes: `POST /api/snapshots` (create), `GET /api/snapshots` (list),
`POST /api/snapshots/<id>/restore`, `DELETE /api/snapshots/<id>`.

### Trash service

Deleted comics go to `instance/data/{username}/trash/recent/` for 30-day soft-delete.
`TrashService.cleanup_expired()` runs on startup for each registered user.

---

## Adding a New Feature — Checklist

1. **Route**: add to the appropriate `app/routes/api/*.py` module.
   - Decorate with `@login_required` (and `@csrf_required` for state-changing methods).
   - If admin-only, also add `@admin_required`.
   - Use `user_context` helpers for all per-user paths — never build them manually.
   - Return errors via `safe_error_message(exc)`, never `str(e)`.
2. **Register**: add an import in `app/routes/api/__init__.py` if creating a new module.
3. **Service**: if new business logic, put it in `app/services/` not in the route handler.
4. **Validation**: validate all input fields (type, length, range, allow-list) before storage.
5. **Security checklist**: run through the pre-commit security checklist in `AGENTS.md`.
6. **Instructions**: update this file if the architecture or a decision pattern changes.

---

## Production Deployment

### Gunicorn (`deployment/templates/supervisor.conf.j2`)

- Bind only to `127.0.0.1:{gunicorn_port}`; Nginx is the public edge.
- Shared-server default: `gunicorn_workers=1`, `gunicorn_threads=4`, `gunicorn_timeout=120`.
- Recycle workers with `--max-requests 1000` and `--max-requests-jitter 100`.
- Logs to `LOG_DIR/app.log` and `LOG_DIR/error.log` (set by Systemd service)
- `--forwarded-allow-ips 127.0.0.1` — only trust X-Forwarded-For from Nginx.

### Nginx (`deployment/templates/nginx.conf.j2`)

- HTTP → HTTPS redirect; TLS 1.2/1.3 via Let's Encrypt
- Static assets served directly with cache headers
- `client_max_body_size` aligned with Flask `MAX_CONTENT_LENGTH` (96 MB for multi-image uploads)
- API `proxy_read_timeout` / `proxy_send_timeout` should be just above `gunicorn_timeout`, not several minutes longer, so failures surface predictably.
- CSP currently keeps `'unsafe-inline'` only because legacy templates still have inline CSS/JS. Do not add new inline scripts/styles; move new behavior into static assets or a nonce-based CSP migration.

### Version (`inject_version()` context processor in `app/__init__.py`)

Lookup order: `instance/app_version` file → `git rev-list --count HEAD` (+850 offset) → `"unavailable"`.
Injected into every template as `{{ app_version }}` and `{{ app_version_display }}`.

### Deployment commands

```bash
cd deployment
source scripts/load-vars.sh
ansible-playbook playbooks/provision-infrastructure.yml --vault-password-file ~/.vault_pass
ansible-playbook playbooks/setup-server.yml --vault-password-file ~/.vault_pass
ansible-playbook playbooks/setup.yml --vault-password-file ~/.vault_pass
# Update existing deployment:
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

---

## Flask Security Rules

Dockyard stores user credentials and personal inventory data. Apply every rule
below when generating, refactoring, or reviewing Flask code.

### 1. File uploads

- Wrap every client filename with `werkzeug.utils.secure_filename()` before joining or using as an S3 key.
- Validate image content with `PIL.Image.open(stream).verify()` at the upload site.
- Enforce size caps: per-file 10 MB cap; `MAX_CONTENT_LENGTH = 96 MB` for multi-image batches.
- Allow-list extensions: `.jpg`, `.jpeg`, `.png`, `.webp` only.
- Generate stored filenames (UUID, SKU-based) — never reuse the user-supplied filename.
- Catch `PIL.UnidentifiedImageError` and `PIL.Image.DecompressionBombError` and return 400.

### 2. Path handling

- Never build filesystem paths by string concatenation with user input.
- Use `app/utils/user_context.py` helpers for all per-user paths.
- Never accept a `username` from request body, query string, or header for authorization. Use `session['username']` only.
- Reject `..`, absolute paths, null bytes from user input; `_assert_safe_username()` guards all path construction.

### 3. Authentication & secrets

- Never hardcode credentials, API keys, or secrets in source code.
- All secrets via `get_secret()` in `app/config.py` (Secrets Manager → env var → default).
- Per-user eBay credentials live in AWS Secrets Manager via `app/services/user_secrets_service.py`.
- `SECRET_KEY` must be unique per deployment (auto-randomized in dev; required from Secrets Manager in prod).
- Session cookies: `HTTPONLY=True`, `SECURE=True` in production, `SAMESITE=Lax`, 24-hour lifetime.

### 4. Input validation & output encoding

- Validate all incoming fields: type, explicit length max, range, allow-list of values.
- Jinja2 auto-escaping is always on — never use `{{ value|safe }}` on user-controlled data.
- CSV cell values go through `csv_sanitizer.py` before write to prevent spreadsheet injection.

### 5. Security response headers

| Header | Required value |
|--------|---------------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` (production only) |

Legacy CSP exception: existing templates still require `'unsafe-inline'`. Treat that as technical debt, not permission for new inline JavaScript or page-specific style expansion.

### 6. Rate limiting & brute-force protection

- Login: rate-limited per IP in `security.py`; auto-block after repeated attack patterns.
- Nginx rate zones for global and login endpoints.
- Auto-block: 5+ attack-pattern hits in 60 s → 1-hour IP block persisted to JSON.

### 7. Error handling

- Always use `safe_error_message(exc)` from `app/utils/logging_utils.py` in JSON error responses.
- Never log eBay tokens, full session cookies, or AWS credentials.

### 8. Dependency & supply-chain security

- Review `requirements.txt` with `pip-audit` before each deployment.
- HIGH or CRITICAL CVE = deployment blocker.
- Do not add a new dependency without justification; prefer stdlib or already-present packages.

---

## UI Design System

All colors, spacing, radii, and shadows are defined once in `app/static/css/tokens.css`.
Shared component classes (`.btn`, `.modal`, `.card`, etc.) are in `app/static/css/components.css`.

### Key tokens

```css
:root {
  --color-bg:             #1B1A1B;
  --color-surface:        #242223;
  --color-elevated:       #2D2B2C;
  --color-inset:          #171616;
  --color-border:         #5A5758;
  --color-text:           #E8E8E6;
  --color-text-muted:     #C5C2BE;
  --color-accent:         #E2E800;   /* primary: bright yellow */
  --color-accent-hover:   #D1D700;
  --color-accent-text:    #141414;   /* text ON accent backgrounds */
  --color-accent-2:       #5C9EB8;   /* secondary: steel blue */
  --color-danger:         #C45C5C;
  --color-success:        #5C8A5C;
  --color-ebay:           #00BFFF;
  --color-whatnot:        #FF00FF;
  --radius-sm:  6px;
  --radius-md:  10px;
  --radius-lg:  14px;
  --shadow-md:  0 4px 12px rgba(0, 0, 0, 0.5);
}
```

### Rules

- **Never hard-code hex colors** — always use `var(--color-*)` tokens.
- This includes quick one-offs like `#fff`; use `var(--color-text)` / `var(--color-accent-text)` or the shared component class.
- **Never re-declare `.btn`, `.modal`, `.card`** in `{% block extra_css %}` — use `components.css` classes.
- Prefer shared component classes over inline `style` attributes. Inline style is tolerated only for small layout values already common in legacy templates; do not use it for colors, hover/focus states, or component variants.
- **No inline `onmouseover`/`onmouseout`** for styling — use CSS classes.
- **No colored glow shadows** — use `var(--shadow-sm/md/lg)` (neutral, dark).
- Border radius: buttons/inputs → `var(--radius-sm)`, cards → `var(--radius-md)`, modals/sections → `var(--radius-lg)`.

---

## eBay Integration Patterns

### XML Payload Sanitization

eBay's Trading API returns `Code: 5 — XML Parse error` when a title contains a
bare `&`. `EbayService` automatically sanitizes all AddFixedPriceItem and
ReviseFixedPriceItem payloads:

- `_escape_bare_ampersands(value)` — replaces bare `&` with `&amp;` (skips valid entities).
- `_sanitize_trading_payload_strings(payload)` — recursively walks dicts/lists.

Do not manually escape `&` in titles or descriptions — the sanitizer handles it.

### Scheduled ↔ Live Toggle

- **Single-comic page:** eBay footer dropdown shows "⚡ Move to Live" or "📅 Move to Scheduled".
  Both call `POST /api/comic/<sku>/ebay/relist` with `mode` and optional `schedule_time`.
- **Bulk actions (`comics_list.html`):** "Bulk Move to Live" and "Bulk Move to Scheduled".

`/api/comic/<sku>/ebay/relist` ends the existing listing before relisting — no separate end call needed.

### Bulk eBay Action Flow (three-modal pattern)

1. `bulkEbayModal` — choose action (List, Update, End, Unlink, Move to Live, Move to Scheduled)
2. `bulkEbaySelectionModal` — pick "All Listed Items" or select specific items
3. `bulkConfirmModal` — confirm; shows day-picker for `update` (push schedule) and `go-scheduled`

State tracked in `bulkCurrentAction` and `bulkCurrentPlatform` globals. `executeBulkAction()` processes items sequentially with 100 ms delay.

---

## Source Note

Additional workflow principles adapted from:
`https://github.com/github/awesome-copilot/blob/main/instructions/codexer.instructions.md`.
