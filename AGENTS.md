# Agent Operational Guidelines

**Instructions for AI agents working on this project**

> **Source of truth:** This file is synced from
> [`.github/copilot-instructions.md`](.github/copilot-instructions.md),
> which GitHub Copilot reads automatically at the start of every session.
> Run `synca` after updating Copilot instructions so this file stays aligned.

---

<!--
  ╔══════════════════════════════════════════════════════════════════╗
  ║  PART 1 — GENERAL WORKFLOW                                       ║
  ║  Reusable rules that apply to any project.                       ║
  ║  Copy this section verbatim to bootstrap a new repo.             ║
  ╚══════════════════════════════════════════════════════════════════╝
-->

## Session Memory - READ FIRST EVERY SESSION

AI agents have no memory between conversations, and connections time out. To
bridge that, this repo keeps a `SESSION.md` file at the repo root that every
agent reads at the start of every session and updates automatically as work
progresses. The file persists until the user explicitly clears it, so a
reconnect or new session picks up exactly where the last one left off.

**File:** `SESSION.md` (repo root, gitignored — local working memory only)

### At the start of every session

1. Use the `read_file` tool to read `SESSION.md`.
2. If it has a **Current Work** block, summarize it in 2–3 lines so the user
   can confirm the context before starting new work.
3. If the file is empty or missing, proceed normally — do not create it yet.

### Automatic session maintenance (no trigger needed)

The agent must keep `SESSION.md` current **without being asked**:

- **After completing any significant unit of work** — feature added, bug fixed,
  decision made, file edited — append or update the **Current Work** block.
- **Before any risky or multi-step operation** — write the current state first
  so a timeout mid-operation leaves a recoverable record.
- **On reconnect** — read the file, confirm context with the user, then continue.

The goal: if the connection drops at any moment, the next session can read
`SESSION.md` and resume without the user re-explaining anything.

### Trigger phrases the user can say

Short forms are the primary triggers. Longer natural-language forms still work.

| User says | Agent does |
|-----------|------------|
| `ck` / `checkpoint` / `save context` / `remember this` | Append a full dated checkpoint entry to `SESSION.md` using the entry template below. |
| `ctx` / `show context` / `recall` / `what were we doing` | Read `SESSION.md` and summarize recent entries. |
| `wipe` / `clear memory` / `start fresh` / `forget everything` | Truncate `SESSION.md` (keep the header template), confirm what was cleared. |
| `arc` / `archive memory` | Move all session entries to `SESSION.archive.md`, then clear. |
| `gitp` / `git push` / `commit and push` | Stage all changes (`git add -A`), commit with a generated message, push to `origin/main`, then print the server update command (see below). |
| `ucp` / `update copilot instructions` / `update instructions` | Review what was just built or decided in this session and append or update the relevant rules, patterns, and architecture notes in `.github/copilot-instructions.md`. Confirm what was added/changed. |
| `synca` / `sync agents` / `sync instructions` | Copy all rules, trigger phrases, and architecture notes from `.github/copilot-instructions.md` into `AGENTS.md` so both files are identical in content. Confirm what was updated. |
| `evala` / `evaluate agents` / `evaluate instructions` | Evaluate AI instruction files for clean general vs app-specific separation. Move reusable practices to Part 1, app-only facts to Part 2, then run `synca`. |

A short trigger (`ck`, `ctx`, `wipe`, `arc`, `gitp`, `ucp`, `synca`, `evala`) is a command only when it is the
entire user message. Inside a longer sentence, treat it as normal text.

### SESSION.md structure

```markdown
# Session Notes
<!-- Gitignored. Read by all agents at session start. Updated automatically. -->
<!-- Clear with: wipe | Clear and archive with: arc -->

## Current Work
**Goal:** one line describing what is being worked on right now.
**Branch:** (git branch name)
**Status:** in-progress | blocked | done

**Recent progress:**
- bullet — what was just completed
- bullet — next up

**Key decisions:**
- bullet (or "none yet")

**Files in play:**
- path/to/file — why

**Open questions / blockers:**
- bullet (or "none")

---

## Checkpoints

<!-- Full dated entries appended here by `ck` / auto-checkpoint -->
```

### `gitp` — Stage, Commit, Push, and Print Update Command

When the user says `gitp` (or any natural-language equivalent):

1. Run `git add -A` to stage all changes.
2. Inspect `git diff --staged --stat` to summarize what changed.
3. Write a conventional-commit message (no internal quotes) describing the changes.
4. Commit using the simple `-m` form (or the `/tmp/msg.txt` file method for multi-line messages).
5. Push to `origin/main`.
6. Print the server update command so the user can copy-paste it (update this for your project):

```bash
cd deployment && ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

### `synca` — Sync AGENTS.md with Copilot Instructions

When the user says `synca` (or any natural-language equivalent):

1. Read `.github/copilot-instructions.md` (the source of truth).
2. Read `AGENTS.md` to identify sections that are out of date or missing.
3. Update `AGENTS.md` to match — trigger table, architecture notes, rules, and any new patterns added via `ucp`.
4. Keep the `AGENTS.md` header (`# Agent Operational Guidelines`) and its opening note pointing back to this file.
5. Confirm in chat what sections were updated.

### `evala` — Evaluate Agent Instructions for General/App Separation

When the user says `evala` (or any natural-language equivalent):

1. Read `.github/copilot-instructions.md`, `AGENTS.md`, and any other local agent instruction files.
2. Identify rules that are in the wrong layer:
   - General engineering, security, design, workflow, or deployment-hardening practices sitting in app-specific sections.
   - App names, file paths, cloud resources, exact commands, architecture diagrams, product/domain language, or app-only helper names sitting in reusable general sections.
3. Move generalizable practices into **Part 1 — General Workflow**.
4. Move project-only facts into **Part 2 — App-specific**.
5. Remove duplicates, stale rules, and contradictions while preserving useful project facts.
6. Run `synca` afterward so `AGENTS.md` matches `.github/copilot-instructions.md`.
7. Confirm what moved from app-specific → general, what moved from general → app-specific, and what was removed.

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

- **Never `str(e)` in JSON responses** — use a safe error helper that sanitizes the client message and logs full detail server-side only.
- **All imports at module level** — never inside functions, route handlers, or `except` blocks. Two allowed exceptions (both require a comment): `# Deferred: avoids circular import` and `# Deferred: requires app context`.
- **Initialize before `try`** — any variable referenced in `except`/`finally` must be assigned before the `try` block, not inside it.
- **Use Pythonic style** — follow PEP 8 and PEP 257. `snake_case` names, clear docstrings. Pragmatic exception: do not force line-length wrapping when the wrapped version is less readable; readability wins over strict character counts.
- **Prefer named callables over inline `lambda`** — use `def` for any non-trivial logic.
- **Use type hints where applicable** — annotate public functions/methods and complex return types.
- **Format with `black` and sort imports with `isort`** — keep import order stable, but do not contort code solely to satisfy line length; extract a helper or named value when that improves readability.
- **Catch specific exceptions first** — avoid broad `except Exception` unless you log and re-raise.
- **No side effects at import time** — module import should define symbols only.
- **No global mutable state** — avoid module-level mutable variables as implicit shared state; pass state explicitly or use a proper singleton.
- **Use context managers** — use `with` for all resource management (files, locks, connections, DB sessions). Never manual cleanup.
- **Fail fast, raise early** — validate inputs at boundaries and raise specific, descriptive exceptions immediately; don't let bad data propagate silently.
- **Functions do one thing** — keep functions focused and short (≤50 lines is the guideline); extract helpers rather than growing a single function.
- **Meaningful names** — avoid generic names like `data`, `temp`, `result`, `stuff`, `info`; name things by what they represent in the domain.
- **Prefer built-ins and stdlib** — reach for `collections.Counter`, `collections.defaultdict`, `itertools.chain`, `functools` before writing equivalent loops.
- **Prefer comprehensions** — use list/dict/set comprehensions over equivalent `for` loops that build a collection, when the result is readable.
- **Pin dependencies** — lock exact versions in `requirements.txt`; use `pip-audit` to check for CVEs before each deployment.
- **Virtual environments** — always develop inside a `venv`; never install project dependencies into the system Python.

---

## General JavaScript Coding Standards

### Modal / Pending-State Lifecycle

Confirm flows that mutate pending state must follow a strict single-owner pattern.
The **confirm function** owns the full lifecycle: snapshot → execute → clean up.
Executors never read or reset `pending*` / `bulk*` state directly.

```javascript
// GOOD — single owner, try/finally guarantees cleanup even on error
async function confirmDelete() {
    const sku = pendingAction.sku;   // 1. Snapshot state before any async work
    try {
        await executeDelete(sku);    // executor takes values as args
    } finally {
        pendingAction = { type: null, sku: null };  // always runs
    }
}

// Cancel path clears immediately — no async, no try/finally needed
function cancelDelete() {
    pendingAction = { type: null, sku: null };
    closeModal();
}

// Executor accepts values as parameters — never reads/resets global state
async function executeDelete(sku) { ... }
```

### Declare Related State Variables Together

All variables that form a single logical state group must be declared in one
contiguous block at the top of their scope. Do not scatter or redeclare.

```javascript
// GOOD — all related state in one block
let currentAction   = null;
let selectedItems   = [];
let scheduleDays    = 0;
```

### Use Registry Arrays for Grouped DOM Operations

When multiple modals (or other elements) must be hidden/reset together, define a
constant array of their IDs and iterate — do not duplicate calls across functions.

```javascript
const MODAL_IDS = ['confirmModal', 'selectionModal', 'actionModal'];

function closeAllModals() {
    MODAL_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
}
```

---

## General Coding Workflow

- Start from clear requirements; if scope is ambiguous, propose small options before implementing.
- Prefer small, focused edits that preserve existing behavior unless a change is requested.
- Keep naming and structure consistent with the current codebase.
- There is no smoke test — validate Python changes with `python3 -m py_compile` and JS changes with `node --check`.
- Highlight risks, assumptions, and missing data explicitly instead of silently guessing.
- Optimize for maintainability: straightforward code paths, minimal side effects, clear data ownership.

---

## Senior Engineering Standards — Junior-Readable Code

Write code the next developer can safely modify, even if they are new to the
project. Senior-quality code is simple, explicit, tested, and boring in the best
way.

- **Clarity beats cleverness** — prefer obvious control flow over compressed tricks.
- **Name by domain meaning** — use names that explain what a value represents, not its type (`listing_status`, not `data`).
- **Explain why, not what** — comments should capture decisions, constraints, tradeoffs, and non-obvious edge cases.
- **Keep public APIs predictable** — functions should validate inputs, return consistent shapes, and document side effects.
- **Make errors actionable** — include enough context for logs/debugging without leaking secrets or internals to users.
- **Minimize hidden coupling** — avoid magic globals, implicit file paths, import-time state, and order-dependent behavior.
- **Prefer boring dependencies** — choose stdlib or already-present libraries unless a new dependency clearly pays for itself.
- **Leave the code easier to review** — small diffs, focused functions, no unrelated formatting churn.
- **Teach through structure** — when code has a pattern, extract a helper or registry so junior devs can follow one example.

### Definition of done for code changes

- Requirements are satisfied with the smallest maintainable change.
- Edge cases and failure paths are handled intentionally.
- Relevant validators/tests were run, or the reason they cannot run is stated.
- Security checklist is satisfied: input validation, authorization, secrets/logging, dependency risk.
- New or changed behavior is discoverable through names, docstrings, UI copy, or docs.

---

## General Secure Coding Baseline — All Apps

Apply these rules to every app, CLI, worker, script, and service — not just web
apps.

- **Threat-model before coding** — identify inputs, trust boundaries, secrets, filesystem/network access, and destructive actions.
- **Validate at boundaries** — parse and validate external input before it reaches business logic.
- **Authorize server-side** — never trust a client-provided user, role, path, tenant, or account identifier for authorization.
- **Keep secrets out of code** — use environment variables or a secrets manager; never commit `.env`, tokens, private keys, or decrypted vault data.
- **Sanitize logs** — never log credentials, tokens, cookies, passwords, MFA codes, private URLs, or full auth request bodies.
- **Avoid dangerous primitives** — no `eval`, `exec`, unsafe deserialization, shell interpolation, or raw SQL/XML/HTML string concatenation with user input.
- **Use safe subprocess calls** — pass argument lists with `shell=False`; never concatenate user input into commands.
- **Use timeouts for I/O** — network calls, subprocesses, locks, and long operations need explicit timeouts where supported.
- **Fail closed** — malformed state, missing authorization, expired sessions, and invalid config should deny access, not guess permissively.
- **Prefer least privilege** — credentials, IAM roles, file permissions, and API tokens should have only the access required.
- **Audit dependencies** — pin versions and check for known CVEs before deployment.
- **Handle destructive actions carefully** — require explicit confirmation, scope operations narrowly, and log enough metadata to audit without exposing secrets.

---

## Web App Security — General Rules

Apply these rules to any Flask / Python web application. They are language and
framework patterns, not project-specific policy.

### Error responses — never leak internals

Never return a raw exception message to the client. Use a sanitized error helper
that returns a generic message to the caller and logs the full detail server-side:

```python
# BAD
return jsonify({'error': str(e)}), 500

# GOOD
logger.exception("operation failed")
return jsonify({'error': safe_error_message(e)}), 500
```

### Logging — never log sensitive material

Never log: auth tokens, API keys, session cookies, third-party OAuth tokens,
passwords, MFA codes, QR payloads, AWS/cloud credentials, or full request bodies
for authentication endpoints.

### Authentication fundamentals

- Never hardcode credentials, API keys, or secrets in source code or committed config files.
- Read all secrets from environment variables or a secrets manager — never from git-tracked files.
- `SECRET_KEY` / session secret must be unique per deployment; auto-randomize in dev, require from secrets store in prod.
- Session cookies in production: `HttpOnly=True`, `Secure=True`, `SameSite=Lax`, explicit lifetime.
- Authorization is always derived from the server-side session — never from a request parameter, body field, or header claiming identity.

### TOTP / 2FA — implementation rules

- TOTP enrollment **must require the current password**. A stolen active session alone must not enroll an attacker-controlled authenticator.
- TOTP setup secrets are short-lived. Clear pending setup state after success or expiry; never log TOTP secrets, QR payloads, or one-time codes.
- Implement a two-step login flow: password success → `totp_pending`; valid TOTP code → `logged_in=True`.
- Pending TOTP sessions must expire quickly (≤5 minutes), validate that the user still has TOTP enabled, and be rate-limited separately from password attempts.
- Session timestamps (created, last-activity, TOTP pending) must be coerced/validated before arithmetic so malformed or legacy sessions fail closed.

### Input validation

- Validate every incoming field: required, type, explicit length cap, numeric range, allow-list of values.
- Cap string lengths server-side — never rely on browser/client-side validation.
- Reject unknown or unexpected fields rather than silently ignoring them.
- Output encoding: template auto-escaping must always be on; never use `| safe` on user-controlled data.

### File uploads

- Sanitize every client-supplied filename with `werkzeug.utils.secure_filename()` before using it in a path or storage key.
- Validate file content server-side (e.g., `PIL.Image.open(stream).verify()` for images) — do not trust file extension or `Content-Type` header.
- Allow-list extensions and MIME types; deny-lists are incomplete.
- Generate the stored filename (UUID, hash, or app-defined key) — never reuse the user-supplied filename in storage.
- Enforce server-side size caps; catch decompression-bomb errors and return 400.

### Path safety

- Never build filesystem paths by string concatenation with user input — use `pathlib.Path` or `os.path.join` + `secure_filename`, then resolve and confine:
  ```python
  base = Path(allowed_dir).resolve()
  target = (base / secure_filename(user_input)).resolve()
  if not target.is_relative_to(base):
      abort(400)
  ```
- Reject `..`, absolute paths, and null bytes from any user-supplied path component.

### Security response headers

Emit these on every response in production. If a reverse proxy (Nginx) also sets
them, set them in only one place — duplicate headers confuse browsers:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` (HTTPS only) |

### Rate limiting & brute-force protection

- Rate-limit login, registration, password-reset, and MFA verification endpoints separately from general API endpoints — they need tighter limits.
- Auto-block IPs that hit repeated attack patterns; persist the block list so it survives app restarts.
- Apply rate limiting at the reverse proxy layer (Nginx) and optionally also at the app layer for defense-in-depth.

### Dependency & supply-chain security

- Audit dependencies with `pip-audit` (Python) or `npm audit` (Node) before each deployment.
- HIGH or CRITICAL CVE = deployment blocker; do not ship until resolved or explicitly accepted.
- Do not add a new dependency without justification; prefer stdlib or already-present packages.

---

## Nginx / Reverse Proxy Hardening

Apply these rules whenever deploying a web app behind Nginx (or any reverse proxy).

### Never duplicate security headers

The reverse proxy is the single source of truth for `X-Frame-Options`,
`X-Content-Type-Options`, `Referrer-Policy`, `Content-Security-Policy`, and
`Strict-Transport-Security`. If the app also emits them, browsers receive duplicate
values and CSP/HSTS behavior becomes unpredictable. Pick one layer; emit from the other
layer only in development.

### server_tokens off — every server block

```nginx
# BAD — only on the HTTPS block; HTTP block still leaks nginx/1.24.0 (Ubuntu)
server { listen 80; ... }  # no server_tokens here
server { listen 443 ssl; server_tokens off; ... }

# GOOD — every block that can respond to a request
server { listen 80; server_tokens off; return 301 https://$host$request_uri; }
server { listen 443 ssl; server_tokens off; ... }
```

### Remove the default site

```bash
rm /etc/nginx/sites-enabled/default
```

The default Ubuntu Nginx site answers unmatched `Host` headers and leaks version info.
Remove it during setup — it is safe to remove on any dedicated app host.

### HTTP → HTTPS redirect

Every HTTP request must redirect to HTTPS. The redirect server block needs
`server_tokens off` (see above) and nothing else:

```nginx
server {
    listen 80;
    server_name example.com;
    server_tokens off;
    return 301 https://$host$request_uri;
}
```

### Rate zones

Define Nginx rate zones for at minimum two tiers:

```nginx
# In http { } block
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=api:10m   rate=60r/m;
```

Apply the tighter `login` zone to `/login`, `/register`, `/reset-password`, and any
MFA verification endpoint. Apply `api` to the general app location.

### Proxy timeout alignment

Set `proxy_read_timeout` and `proxy_send_timeout` to just above the app/Gunicorn
timeout — not several minutes longer. If Gunicorn times out at 120 s, set proxy
timeouts to 125–130 s so failures surface predictably to the client.

### client_max_body_size

Align `client_max_body_size` with the app's `MAX_CONTENT_LENGTH`. If they differ,
Nginx will silently drop oversized bodies before Flask can return a helpful error.

---

<!--
  ╔══════════════════════════════════════════════════════════════════╗
  ║  PART 2 — ASHCAN APP (project-specific)                          ║
  ║  Rules, architecture, and patterns specific to this codebase.    ║
  ║  Do not copy to other projects without review.                   ║
  ╚══════════════════════════════════════════════════════════════════╝
-->

## Project Context

- **App name:** Ashcan — a comic book inventory and listing management tool
- **Stack:** Python / Flask with Ansible deployment to AWS EC2
- **Storage:** CSV files (inventory), AWS S3 (images + exports), JSON (user preferences) — no database
- **Shell:** zsh on macOS
- **Entry points:** `runapp.py` (web server), `main.py` (CLI batch/S3 utility)
- **Deployment config:** `deployment/` directory with Ansible playbooks, group_vars, vault
- **Ansible variables:** All configuration in encrypted `deployment/group_vars/vault.yml`
- **Vault secrets:** Access with `ansible-vault view group_vars/vault.yml --vault-password-file ~/.vault_pass`
- **Secrets in production:** AWS Secrets Manager at `ashcan/production` via `get_secret()` in `app/config.py`
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

General Nginx hardening rules (server_tokens, headers, rate zones, default site removal) are in Part 1.
The entries below are Ashcan-specific deployment details.

### Gunicorn (`deployment/templates/supervisor.conf.j2`)

- Bind only to `127.0.0.1:{gunicorn_port}`; Nginx is the public edge.
- Shared-server default: `gunicorn_workers=1`, `gunicorn_threads=4`, `gunicorn_timeout=120`.
- Recycle workers with `--max-requests 1000` and `--max-requests-jitter 100`.
- Logs to `LOG_DIR/app.log` and `LOG_DIR/error.log` (set by Systemd service).
- `--forwarded-allow-ips 127.0.0.1` — only trust X-Forwarded-For from Nginx.

### Nginx (`deployment/templates/nginx.conf.j2`)

- `client_max_body_size` = 96 MB (aligned with Flask `MAX_CONTENT_LENGTH` for multi-image uploads).
- API `proxy_read_timeout` / `proxy_send_timeout` = 125 s (just above `gunicorn_timeout=120`).
- In production, Nginx owns all security headers — Flask's `app/security.py` skips header injection in production to avoid duplicates.

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

## Flask Security Rules — Ashcan-Specific

The general rules (error responses, logging, auth, headers, rate limiting) are in
Part 1. The entries below are the Ashcan-specific implementations of those rules.

### File uploads (Ashcan limits)

- Per-file cap: **10 MB**; `MAX_CONTENT_LENGTH` = **96 MB** for multi-image batches.
- Allowed extensions: `.jpg`, `.jpeg`, `.png`, `.webp` only.
- Catch `PIL.UnidentifiedImageError` and `PIL.Image.DecompressionBombError` → return 400.
- Use `app/utils/upload_security.py` helpers at every upload site.

### Path handling (Ashcan)

- Use `app/utils/user_context.py` helpers for all per-user paths — never hand-craft `instance/data/{username}/...` strings.
- `_assert_safe_username()` in `user_context.py` guards all path construction; it rejects `..`, absolute paths, and null bytes.
- Never accept a `username` from request body, query string, or header for authorization — use `session['username']` only.

### Secrets (Ashcan)

- All secrets via `get_secret()` in `app/config.py` (Secrets Manager → env var → default).
- Per-user third-party credentials live in AWS Secrets Manager via `app/services/user_secrets_service.py` — never write them to CSV, JSON, logs, or responses.

### Error responses (Ashcan helper)

- Use `safe_error_message(exc)` from `app/utils/logging_utils.py` in every `jsonify` error response.

### Input encoding (Ashcan)

- Jinja2 auto-escaping is always on — never use `{{ value|safe }}` on user-controlled data.
- CSV cell values must go through `app/utils/csv_sanitizer.py` before write (prefixes `=`, `+`, `-`, `@` cells to prevent spreadsheet injection).

### CSP technical debt

Existing Ashcan templates still require `'unsafe-inline'` in `style-src`. This is
tech debt — do not add new inline scripts or styles. Move new behavior into static
assets or a nonce-based CSP migration.

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
