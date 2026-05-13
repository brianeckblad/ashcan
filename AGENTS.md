# Agent Operational Guidelines

**Instructions for AI agents working on this project**

> **Auto-loaded rules:** The critical rules from this file are also in
> [`.github/copilot-instructions.md`](.github/copilot-instructions.md),
> which GitHub Copilot reads automatically at the start of every session.

---

## Project Context

- **Stack:** Python 3.8+ / Flask 3.0+ web application
- **Storage:** CSV files (inventory), AWS S3 (images), JSON (settings/preferences) — no database
- **Deployment:** Ansible playbooks to AWS EC2 (Ubuntu 22.04), Gunicorn + Nginx + Systemd
- **Shell:** zsh on macOS (development)
- **Secrets:** AWS Secrets Manager in production; `.env` file for local dev (generated from vault)
- **Deployment config:** `deployment/group_vars/vault.yml` (Ansible-vault encrypted, contains all variables)
- **Vault access:** `ansible-vault view group_vars/vault.yml --vault-password-file ~/.vault_pass`
- **S3 bucket name:** Comes from `s3_bucket_name` in vault (not derived from `app_name`)
- **No tests:** The project has no test suite. There is no CI/CD pipeline.

---

## Architecture

### Entry points

| Entry | Purpose |
|-------|---------|
| `runapp.py` | Web server (Flask app via `create_app()` factory) |
| `main.py` | CLI tool for batch CSV processing, S3 image management |

### Application structure

```
app/
├── __init__.py          # App factory (create_app), logging, S3 sync on startup
├── config.py            # Config classes (Dev/Prod), secrets from AWS Secrets Manager
├── security.py          # IP blocklist, rate limiting, attack detection middleware
├── models/              # Dataclasses (Comic, User, Snapshot, TrashItem, Analytics)
│   └── user.py          # UserManager: auth, credentials, preferences (JSON file)
├── routes/
│   ├── auth.py          # login_required, csrf_required, sync_not_locked decorators
│   ├── main.py          # Page routes (landing, browse, add, add-from-image, trash, download, price-lookup, account, ebay-listings, analytics)
│   └── api/             # 11 API modules (67 routes), registered on api_bp at /api
├── services/            # Business logic layer
│   ├── comic_service.py # Comic CRUD orchestration (user-specific CSV + SKU)
│   ├── csv_service.py   # CSV read/write with file locking
│   ├── s3_service.py    # S3 uploads, thumbnails (WebP), sync, restore
│   ├── ebay_service.py  # eBay API integration (search, listings, taxonomy)
│   ├── snapshot_service.py  # Manual backup/restore to S3
│   ├── trash_service.py     # Soft-delete with 30-day retention
│   ├── health_check_service.py  # CSV ↔ S3 image consistency checks
│   ├── cloudwatch_service.py    # CloudWatch metrics
│   ├── sns_service.py           # SNS notifications
│   ├── user_secrets_service.py  # Per-user eBay credentials in Secrets Manager
│   └── analytics_service.py     # Click heatmap analytics
├── scripts/             # App-level utility scripts (image checks, CSV validation, labels)
├── utils/               # Helpers, validators, logging, monitoring decorators
│   ├── user_context.py  # Multi-user file path resolution (CSV, SKU, S3, trash, exports)
│   ├── logging_utils.py # Service/cleanup/app logger helpers
│   ├── mass_deletion_protection.py  # Safety circuit breakers
│   ├── whatnot_validators.py        # CSV field validation rules
│   ├── ebay_validators.py          # eBay CSV export field definitions
│   ├── ebay_helpers.py             # eBay description parsing helpers
│   ├── defaults_helpers.py         # User preferences and app defaults
│   ├── helpers.py                  # Filename generation, CSRF tokens, directory size
│   ├── monitoring.py               # CloudWatch @monitor_endpoint decorator
│   ├── sync_state.py              # Thread-safe singleton for S3 sync progress
│   ├── csv_sanitizer.py           # CSV injection prevention (cell sanitization)
│   └── upload_security.py         # Image upload validation helpers
├── templates/           # Jinja2 HTML templates (10 pages)
└── static/              # CSS, JS, images, error pages
```

### Key patterns

- **App factory:** `create_app(config_name)` in `app/__init__.py` — handles config, logging, security, S3 sync, blueprint registration.
- **Blueprints:** Three blueprints — `auth_bp`, `main_bp`, `api_bp` (mounted at `/api`). API routes split into 11 domain modules in `app/routes/api/`.
- **Service singletons:** Most services are module-level instances (`s3_service`, `comic_service`, `ebay_service`). Import and use directly; do not re-instantiate.
- **Multi-user isolation:** Each user gets their own subdirectory (`instance/data/{username}/`) containing `items.csv`, `sku.txt`, snapshots, trash, exports, and images. Use `app/utils/user_context.py` helpers.
- **Secret precedence:** AWS Secrets Manager → environment variable → default value (see `get_secret()` in `config.py`).
- **Logging:** Three dedicated loggers — `app.logger` (app.log), `service` (service.log), `cleanup` (cleanup.log). Use helpers from `app/utils/logging_utils.py`.
- **Authentication:** Session-based via `login_required` decorator in `app/routes/auth.py`. Sessions invalidated on app restart. Additional decorators: `csrf_required`, `sync_not_locked`, `disk_space_required`.
- **User management:** `UserManager` in `app/models/user.py` — credentials and preferences stored in `instance/user_preferences.json`, synced to S3.
- **Startup sync:** On boot, the app factory syncs SKU (highest-wins), CSV inventory, and user preferences between local files and S3. Images/exports sync in a background thread, followed by a health check.
- **Version injection:** `inject_version()` context processor reads `instance/app_version` (set by deploy), falls back to `git rev-list --count HEAD`.

### Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Generate .env from vault (requires ansible-vault):
cd deployment && python scripts/local_dev_setup_env.py && cd ..
# Or create .env manually (see README.md)
python runapp.py   # http://localhost:8000
```

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

## Session Memory — Cross-Conversation Continuity

### Why this exists

AI coding agents (Copilot, Claude, Cursor, etc.) have **no memory between
chat sessions**. Every new conversation starts blank — the agent has no idea
what was decided yesterday, which approach was already tried and abandoned, or
what branch the work was on.

To bridge that gap without bloating git history, this repo uses a single local
session-notes file the agent reads at session start and appends to on request.

### The file

| Path | `.copilot/SESSION_NOTES.md` |
|------|------------------------------|
| Tracked? | **No** — gitignored. Local to each developer's checkout. |
| Purpose | Cross-session working memory for AI agents. Not a project log. |
| Lifecycle | The developer controls it via trigger phrases (below). |
| Archive | On `archive memory`, contents move to `.copilot/SESSION_NOTES.archive.md` (also gitignored). |

The file itself contains the full convention and entry template. Read it.

### Agent rules

**At session start:**

1. Use the `read_file` tool to read `.copilot/SESSION_NOTES.md` if it exists.
2. If it has entries, summarize the most recent 1–2 to the user in 2–3 lines
   before starting new work, so they can confirm the context.
3. If the file is empty or missing, proceed normally — do not create it
   unsolicited.

**During the session, proactively offer to checkpoint when:**

- A non-trivial architectural / library / approach decision was just made.
- An approach was tried and abandoned (record *why* so the next session
  doesn't redo it).
- The user is about to switch branches or tasks.
- A long debugging session just resolved.

A proactive offer is one short sentence: *"Want me to checkpoint this before
we move on?"* — never write to the file without permission **except** when
the user uses an explicit trigger phrase below.

### Trigger phrases (developer → agent)

Short forms are the primary triggers and only count as commands when they are
the entire user message (so `ck` inside a sentence is just text). The longer
natural-language forms also work and can appear in any reasonable wording.

| Phrase                                                     | Action |
|------------------------------------------------------------|--------|
| `ck`, ` you`, `save context`, `remember this`              | Append a new dated entry using the file's entry template. Set the date to current local time, set `<branch>` to `git branch --show-current`, summarize the active goal, decisions, files touched, open questions, and a one-line "next step". |
| `ctx`, `show context`, `recall`, `what were we doing`      | Read the file and summarize recent entries (1–3 most recent depending on density). Confirm understanding before proceeding with new work. |
| `wipe`, `clear memory`, `start fresh`, `forget everything` | Truncate the **Sessions** section of the file. Keep the header (table, template, headings). Reply in chat with one line stating how many entries were cleared. |
| `arc`, `archive memory`                                    | Append all current session entries to `.copilot/SESSION_NOTES.archive.md` (creating it if needed), then clear as above. |

### Entry template

```markdown
## YYYY-MM-DD HH:MM — <branch> — <topic>

**Goal:** one line.

**Decisions:**
- bullet
- bullet

**Files touched:**
- path/to/file — one-line reason

**Open questions / TODOs:**
- bullet (or "none")

**Next step:** one sentence the next session can act on.
```

Density rule: another instance of you, three days from now, with no memory,
must be able to resume from a single entry. Optimize for *resumability*, not
narrative.

### Anti-patterns

- ❌ Writing to the file without an explicit trigger phrase or proactive
  permission. The user's working memory is theirs to control.
- ❌ Treating session notes as project documentation. Real decisions that
  matter to the project belong in `deployment/docs/` or commit messages.
- ❌ Logging secrets, tokens, or full file contents into entries. The file
  is gitignored but still lives on disk — apply the same hygiene as logs.
- ❌ Reading the file in the middle of a session "just in case" — read it
  once at session start.

---

## IDE Diagnostic False Positives — Known Noise

JetBrains (and some other IDEs) report hundreds of `WARNING(300)` and `ERROR(400)` entries
in this project that are **not real problems**. Before acting on any IDE diagnostic, confirm
whether it falls into one of the known false-positive categories below. Only consult the
authoritative validators.

### Authoritative validators (what actually matters)

| Language / context | Authoritative check | IDE diagnostics? |
|--------------------|---------------------|-----------------|
| Python | `python3 -m py_compile <file>` + `black --check` + `isort --check` | Mostly trustworthy, but see Flask note below |
| JavaScript inside `.html` templates | `node --check <extracted-js-file>` | **High noise — see below. Do not chase.** |
| Jinja2 / HTML structure | Manual review | Mostly trustworthy |

### Category 1 — JS template literals in HTML files (highest volume)

JetBrains' HTML parser does not understand JavaScript template literals (`` `...${expr}...` ``).
It reports every variable used *only* inside a `${}` expression as **"Unused constant"** /
**"Local variable is redundant"**, and reports the `${}` expressions themselves as
**"Expression expected"** / **"Closing '}' expected"** / **"Newline or semicolon expected"**.

These warnings are **always false positives** in `.html` template files. The real test is
`node --check` — if that passes, the JS is syntactically correct.

**Never delete or rename a variable just because the IDE flags it as unused inside an HTML
template. Check whether it is used inside a template literal first.**

Examples of false positives (all pre-existing in `index.html`, `comics_list.html`, etc.):
- `WARNING(300): Unused constant title` when `title` is used as `${title}` in a template literal
- `ERROR(400): Expression expected` on a line like `` ${condition ? `<div>…</div>` : ''} ``
- `WARNING(300): Local variable data is redundant` when `data` is used inside a `.then()` or template literal

### Category 2 — Flask route return type warnings

Every Flask route that returns `(jsonify({...}), 400)` gets:

```
WARNING(300): Expected type 'Response', got 'tuple[Response, int]' instead
```

This is a **JetBrains false positive**. `(jsonify(...), status_code)` IS the correct Flask
pattern. JetBrains does not model Flask's response coercion correctly. These warnings appear
in every one of the 11 API route files and are harmless. **Do not add `make_response()` wrappers
just to silence them** — it adds boilerplate and visual noise with no benefit.

### Category 3 — SVG self-closing tags

```
WARNING(300): Empty tag doesn't work in some browsers
```

Raised on every `<path/>`, `<circle/>`, `<rect/>`, `<line/>`, `<polyline/>` etc. in inline SVG.
Self-closing SVG elements **are** valid HTML5. These are standard SVG icons used throughout
the app. Ignore entirely.

### Category 4 — `throw` of exception caught locally

```
WARNING(300): 'throw' of exception caught locally
```

JetBrains warns when a `throw` is inside a `try` whose own `catch` will catch it. This pattern
is intentional in several places (e.g., re-throwing after logging, or surfacing errors through
a promise chain). Evaluate each instance in context — most are deliberate, not bugs.

### Category 5 — Missing associated label

```
WARNING(300): Missing associated label
```

Reported for hidden inputs (`type="hidden"`), `datetime-local` pickers inside modals, and
`<textarea>` elements used as internal editor state. These do not need visible labels.
Only add `<label>` where the element is a user-visible form field without one.

### Category 6 — Unused parameters in onclick-wired functions

```
WARNING(300): Unused parameter sku
```

Functions called from HTML `onclick="fn(sku)"` receive parameters that may not be referenced
in the function body (the function reads state from a global or `sessionStorage` instead).
The IDE can't see the caller is HTML, so it flags the parameter as unused. These are not bugs.

### Pre-commit validation — the correct process

1. **Python files:** `python3 -m py_compile app/path/to/file.py` — zero output = clean
2. **JS inside HTML:** Extract the `<script>` block to `/tmp/check.js`, run `node --check /tmp/check.js`
   - For large templates with multiple script blocks, validate each relevant block (or a merged extract) so parser noise does not hide real syntax errors.
3. **After confirming clean syntax**, run `black` and `isort` on Python files
4. **IDE warnings** are informational only in HTML files — do not block a change on them

---

## Shell Command Safety - CRITICAL

### Problem
Commands containing `{{ }}` (Jinja2), nested quotes, or heredocs cause the terminal to hang
waiting for input (`dquote>`, `heredoc>`, `quote>`). The agent cannot type interactively,
so the session freezes and the user must Ctrl-C to recover.

### Rule: Never Output Jinja2 Braces Through the Terminal

The zsh shell interprets `{{ }}` as glob patterns. Any command that outputs Jinja2 content
through the shell will hang or produce empty output.

```bash
# BAD - shell interprets {{ }} braces
cat file_with_jinja.yml
grep "pattern" file_with_jinja.yml
echo "{{ app_name }}"

# GOOD - use read_file / grep_search tools instead (they bypass the shell)

# GOOD - if terminal is required, use Python
python3 -c "print(open('file.yml').read()[:500])"
```

### Rule: Never Use Unquoted Heredocs with Dynamic Content

```bash
# BAD - heredoc interprets variables and braces, causes heredoc> hang
cat > file.yml << EOF
name: "{{ app_name }}"
EOF

# GOOD - single-quote the delimiter to prevent interpretation
cat > file.yml << 'EOF'
name: "{{ app_name }}"
EOF

# BEST - use Python or the insert_edit_into_file tool
```

### Rule: Prefer Non-Terminal Tools

| Task | Use This | Not This |
|------|----------|----------|
| Read a file | `read_file` tool | `cat` / `head` / `tail` in terminal |
| Search in file | `grep_search` tool | `grep` in terminal |
| Write / edit a file | `insert_edit_into_file` or `replace_string_in_file` tool | `cat > file << EOF` in terminal |
| Verify edits applied | `read_file` tool | `cat file` in terminal |

**When you must use the terminal** (running commands, playbooks, aws cli):
- Pipe through `| cat` to avoid pagers
- Use `2>&1` to capture stderr
- Run long commands with `isBackground: true`

### Rule: If Terminal Hangs (dquote>, heredoc>, quote>)

If the terminal produces no output or you suspect it is stuck:

1. **Do NOT keep waiting** - the session will not recover on its own
2. **Run a new terminal command** - the tool starts a fresh session
3. **Switch to a non-terminal tool** (read_file, grep_search, insert_edit_into_file)
4. **Re-validate** using the appropriate tool after recovering

---

## Git Branching Workflow

### Default: do NOT create feature branches

Commit changes directly to whatever branch the user is currently on
(typically `main`). The user owns branching strategy. The agent should
**only** create a feature branch when the user explicitly asks for one with
unambiguous wording such as:

- *"create a branch for this"*
- *"new feature branch for X"*
- *"work on this in a branch"*
- *"branch this"*

Words like *"try"*, *"experiment"*, *"see if"*, or any planning-style language
do **not** authorize a new branch. When in doubt, work on the current branch.

### When the agent thinks a branch is warranted

If the change is large, risky, multi-step, or exploratory enough that the
agent honestly believes a branch is the right call (large refactor, schema
migration, parallel approach exploration), **ask the user first** — do not
create the branch preemptively. One short question:

> *"This is a sizeable change — want me to do it on a feature branch, or stay on `main`?"*

### Never auto-merge or auto-push

- Never merge a branch into `main` without an explicit instruction.
- Never push to `origin` without an explicit instruction.
- Never delete a branch (local or remote) without an explicit instruction.

### Why this rule exists

Past sessions defaulted to creating a feature branch for every non-trivial
change. That added rebase / merge / push / delete steps the user did not
ask for, fragmented commit history, and made the workflow heavier than the
user wanted. The user prefers small, direct commits on the current branch
unless they explicitly request branching.

---

## Git Commit Workflow - CRITICAL

### Problem Solved
The project experienced recurring `dquote>` console errors when making git commits. This has been analyzed and resolved.

### Rule 0: Split multi-file UI work by feature

When a UI change spans multiple files with distinct behaviors, prefer separate commits per feature area (for example: add-flow, bulk-flow, shared-style).

- Keeps review and rollback low-risk
- Prevents unrelated template/CSS churn from being bundled together
- Makes future audits of behavior changes much faster


### Rule 1: Keep Git Commit Messages Simple (Primary Method)

**ALWAYS use simple commit messages without internal quotes:**

```bash
# GOOD - Simple messages work perfectly
git commit -m "docs: add deployment guide"
git commit -m "fix: correct CloudWatch permissions"
git commit -m "feat: add validation script"
git commit -m "docs: update MAINTENANCE_CHECKLIST for quarterly reviews"

# BAD - These cause dquote> errors
git commit -m "docs: add 'comprehensive' guide"
git commit -m "fix: update 'CloudWatch' 'permissions'"
git commit -m "docs: update 'guide' with 'new' features"
```

**Why?**
- No quote escaping needed
- Shell interprets message correctly
- Console shows clean output
- Commits go through immediately

### Rule 2: For Complex Messages, Use File Method (Backup Method)

**If you need multi-line or complex messages, use commit message file:**

```bash
# Create message file with complex content
cat > /tmp/commit_msg.txt << 'EOF'
docs: comprehensive documentation update

Added new guides:
- UPDATING_APPLICATION.md: Deploy code changes
- SECURITY_HARDENING.md: Secure your server
- GIT_CONFIGURATION.md: Git workflow and configuration

All links verified with 100% accuracy.
EOF

# Commit using file (avoids ALL quote issues)
git commit -F /tmp/commit_msg.txt

# Clean up
rm /tmp/commit_msg.txt
```

**Why this method?**
- No shell interpretation of file contents
- No quotes to escape
- Multi-line messages work perfectly
- Special characters handled correctly
- Always works, never fails

### Rule 3: NEVER Nest Quotes in -m Parameter

```bash
# NEVER DO THIS
git commit -m "docs: update 'guide' to 'version 2'"
git commit -m "docs: add 'comprehensive' setup with 'best' practices"
git commit -m "fix: handle 'special' 'characters' correctly"

# DO THIS INSTEAD
git commit -m "docs: update guide to version 2"
git commit -m "docs: add comprehensive setup with best practices"
git commit -m "fix: handle special characters correctly"

# OR use file method if you really need quotes
```

### Rule 4: If dquote> or heredoc> Appears

If you see `dquote>`, `heredoc>`, or `quote>` in console output:

1. **Stop immediately** - do not send more text
2. **Run a new terminal command** - the tool starts a fresh session
3. **Use the file method** for the failed operation
4. **See also:** [Shell Command Safety](#shell-command-safety---critical) for prevention rules

```bash
# Recovery: Use file method for git
cat > /tmp/msg.txt << 'EOF'
Your message here without worrying about quotes
EOF
git commit -F /tmp/msg.txt && rm /tmp/msg.txt
```

---

## Workflow Checklist

Before committing, verify:

- [ ] Using simple message format (no internal quotes)
  - OR using file method for complex messages
- [ ] Message is descriptive (tells what changed, not how)
- [ ] No 'quotes' inside the -m "message" parameter
- [ ] Related files staged with git add
- [ ] Running from project root directory

---

## Example Good Commits

```bash
# Fix
git commit -m "fix: correct CloudWatch IAM policy name"

# Docs
git commit -m "docs: add comprehensive deployment guide"

# Feature
git commit -m "feat: add automated validation script"

# Refactor
git commit -m "refactor: simplify git commit handling"

# Multiple changes (keep simple)
git commit -m "docs: add guides and maintenance system"
```

---

## Example Bad Commits (Will Cause dquote>)

```bash
# Don't use these
git commit -m "docs: add 'guide' with 'features'"
git commit -m "fix: correct 'CloudWatch' 'permissions'"
git commit -m "feat: implement 'validation' and 'testing'"

# These will show dquote> error and fail
```

---

## Git Command Best Practices

### For All Git Operations:

1. **Use simple, descriptive messages**
   - First line: One-line summary (50 chars max)
   - Then blank line
   - Then details if needed

2. **Prefer file method for complex messages**
   ```bash
   cat > /tmp/msg.txt << 'EOF'
   Summary line here

   Details:
   - Item 1
   - Item 2
   EOF
   git commit -F /tmp/msg.txt && rm /tmp/msg.txt
   ```

3. **Always verify before committing**
   ```bash
   git status  # See what's staged
   git diff --staged  # See exact changes
   ```

4. **Push immediately after committing**
   ```bash
   git push origin main
   ```

---

## Reference Documents

- **deployment/scripts/git-commit-safe.sh** - Helper script for safe git commits

---

## UI Design System - CRITICAL

### Problem
Every template (`base.html`, `landing.html`, `comics_list.html`, `account.html`, etc.)
re-declares its own `.btn`, `.btn-primary`, `.modal`, `.modal-content`, `.action-section`,
and color values — often with slight inconsistencies. This creates visual drift and makes
palette changes require editing every file.

### Rule: Use CSS Custom Properties from `app/static/css/tokens.css`

All colors, spacing, radii, and shadows are defined once in `app/static/css/tokens.css`.
Templates and inline styles must reference these variables — never hard-code hex values.

```css
/* app/static/css/tokens.css — single source of truth */
:root {
  /* Backgrounds */
  --color-bg:             #1B1A1B;   /* global app background */
  --color-surface:        #242223;   /* top/bottom bars and core surfaces */
  --color-elevated:       #2D2B2C;   /* cards, modals */
  --color-inset:          #171616;   /* input fields, code blocks */

  /* Borders */
  --color-border:         #5A5758;
  --color-border-hover:   #7A7778;
  --color-border-focus:   #5C9EB8;   /* secondary accent for focus */

  /* Text */
  --color-text:           #E8E8E6;   /* primary text */
  --color-text-muted:     #C5C2BE;   /* secondary text */
  --color-text-dim:       #ADADAD;   /* placeholders, disabled, captions */

  /* Primary Accent — bright yellow highlight */
  --color-accent:         #E2E800;
  --color-accent-hover:   #D1D700;
  --color-accent-subtle:  rgba(226, 232, 0, 0.16);
  --color-accent-text:    #141414;   /* text ON accent-colored backgrounds */

  /* Secondary Accent — steel blue */
  --color-accent-2:       #5C9EB8;
  --color-accent-2-hover: #6DB1CB;
  --color-accent-2-subtle: rgba(92, 158, 184, 0.16);

  /* Semantic */
  --color-danger:         #C45C5C;
  --color-danger-subtle:  rgba(196, 92, 92, 0.14);
  --color-success:        #5C8A5C;
  --color-success-subtle: rgba(92, 138, 92, 0.14);
  --color-info:           #5C9EB8;
  --color-info-subtle:    rgba(92, 158, 184, 0.14);
  --color-warning:        #B8A05C;
  --color-warning-subtle: rgba(184, 160, 92, 0.14);

  /* Platform Brand Colors */
  --color-ebay:           #00BFFF;   /* eBay brand blue */
  --color-ebay-subtle:    rgba(0, 191, 255, 0.14);
  --color-whatnot:        #FF00FF;   /* WhatNot brand magenta */
  --color-whatnot-subtle: rgba(255, 0, 255, 0.14);

  /* Status feedback surfaces */
  --color-status-surface: #312E2F;

  /* Typography */
  --font-family:          'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-size-xs:         11px;
  --font-size-sm:         13px;
  --font-size-base:       14px;
  --font-size-md:         16px;
  --font-size-lg:         20px;
  --font-size-xl:         28px;
  --font-size-2xl:        48px;

  /* Spacing */
  --space-xs:  4px;
  --space-sm:  8px;
  --space-md:  16px;
  --space-lg:  24px;
  --space-xl:  48px;

  /* Radii */
  --radius-sm:  6px;    /* buttons, inputs, tags */
  --radius-md:  10px;   /* cards, small containers */
  --radius-lg:  14px;   /* modals, sections, large containers */

  /* Shadows (neutral — no colored glows) */
  --shadow-sm:  0 1px 2px   rgba(0, 0, 0, 0.36);
  --shadow-md:  0 4px 12px  rgba(0, 0, 0, 0.5);
  --shadow-lg:  0 8px 24px  rgba(0, 0, 0, 0.6);
}
```

### Rule: Use Shared Component Classes from `app/static/css/components.css`

Common UI components are defined once in `app/static/css/components.css`. Templates must
use these classes — never re-declare `.btn`, `.btn-primary`, `.modal`, etc. in `<style>` blocks.

**Shared components** (defined in `components.css`, used everywhere):

| Component | Class(es) | Notes |
|-----------|-----------|-------|
| Buttons | `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-sm` | Consistent padding, radius, hover |
| Modals | `.modal`, `.modal-content`, `.modal-header`, `.modal-body`, `.close-btn` | Escape-to-close in `base.html` JS |
| Cards | `.card`, `.stat-card` | Surface background, border, radius |
| Forms | `.form-group`, `.form-label`, `.form-input`, `.form-select` | Focus ring uses `--color-border-focus` |
| Section labels | `.section-label` | Uppercase, letter-spaced, with optional icon |
| Page header | `.page-header`, `.page-header h1`, `.page-header p` | Consistent across all pages |
| Action section | `.action-section` | Grouped actions with border and hover |
| Notifications | `.notification`, `.notification.success/error/info` | Positioned top-center |
| Footer bar | `.footer-bar` | Fixed bottom bar with actions |

**Page-specific styles** remain in each template's `{% block extra_css %}` block, but only
for layout and features unique to that page (grid columns, table tweaks, page-specific modals).

### Rule: Never Hard-Code Colors

```css
/* BAD — color will drift across templates */
.my-element { color: #FFE500; background: #1A1A1A; }

/* GOOD — uses design tokens */
.my-element { color: var(--color-accent); background: var(--color-surface); }
```

### Rule: Never Use Inline Style for Hover/Focus Effects

```html
<!-- BAD — cannot be overridden, causes sticky hover on mobile -->
<button onmouseover="this.style.background='#F5DB00'" onmouseout="this.style.background='#FFE500'">

<!-- GOOD — use a CSS class -->
<button class="btn btn-primary">
```

### Rule: No Colored Glow Shadows

```css
/* BAD — dated 2018 glow effect */
box-shadow: 0 4px 16px rgba(255, 229, 0, 0.3);

/* GOOD — neutral shadow */
box-shadow: var(--shadow-md);
```

### Rule: Consistent Border Radius

| Element | Radius |
|---------|--------|
| Buttons, inputs, tags | `var(--radius-sm)` (6px) |
| Cards, comic cards, small containers | `var(--radius-md)` (10px) |
| Modals, sections, large containers | `var(--radius-lg)` (14px) |

### Color Palette Reference

| Name | Hex | Role |
|------|-----|------|
| Primary text | `#E8E8E6` | `--color-text` |
| Secondary text | `#C5C2BE` | `--color-text-muted` |
| App background | `#1B1A1B` | `--color-bg` |
| Surface (bars, areas) | `#242223` | `--color-surface` |
| Elevated (cards, modals) | `#2D2B2C` | `--color-elevated` |
| Inset (inputs) | `#171616` | `--color-inset` |
| Primary accent | `#E2E800` | `--color-accent` — bright yellow highlight |
| Secondary accent | `#5C9EB8` | `--color-accent-2` — steel blue |
| Danger | `#C45C5C` | `--color-danger` — destructive actions |
| Success | `#5C8A5C` | `--color-success` |
| Warning | `#B8A05C` | `--color-warning` |
| eBay brand | `#00BFFF` | `--color-ebay` |
| WhatNot brand | `#FF00FF` | `--color-whatnot` |

### Template Checklist

Before editing any template:

- [ ] `tokens.css` and `components.css` are linked in `base.html` `<head>`
- [ ] No new `.btn` / `.btn-primary` / `.modal` declarations in `{% block extra_css %}`
- [ ] All colors reference `var(--color-*)` tokens
- [ ] No `onmouseover` / `onmouseout` inline event handlers for styling
- [ ] No `rgba(255, 229, 0, ...)` colored glow shadows
- [ ] Border-radius uses `var(--radius-sm/md/lg)`
- [ ] Page-specific styles only contain layout unique to that page

---

## eBay Integration Patterns

### XML Payload Sanitization

eBay's Trading API returns `Code: 5 — XML Parse error` when a title or field contains a
bare `&` (e.g. "Street Fighter & Friends"). `EbayService` automatically sanitizes all
`AddFixedPriceItem` and `ReviseFixedPriceItem` payloads before sending:

- `_escape_bare_ampersands(value)` — replaces bare `&` with `&amp;` using a regex that
  skips already-valid entities (`&amp;`, `&gt;`, named entities).
- `_sanitize_trading_payload_strings(payload)` — recursively walks dicts and lists to
  apply the escaper to every string value.

Do not manually escape `&` in titles or descriptions — the sanitizer handles it.

### Scheduled ↔ Live Toggle

Comics can be moved between live and scheduled eBay listings without going through the
full list/delist flow:

- **Single-comic page (`index.html`):** eBay footer dropdown shows "⚡ Move to Live" when
  the listing is `Scheduled`, or "📅 Move to Scheduled" when it is `Active`. Both call
  `/api/comic/<sku>/ebay/relist` with the appropriate `mode` and optional `schedule_time`.
- **Bulk actions (`comics_list.html`):** "Bulk Move to Live" and "Bulk Move to Scheduled"
  action cards in the eBay Bulk Actions modal. "Move to Scheduled" shows a day-picker
  (1–17 days) before confirming.

The `/api/comic/<sku>/ebay/relist` endpoint (in `app/routes/api/ebay.py`) reads `mode`
and `schedule_time` from the JSON body via `resolve_ebay_context()`. It internally ends
the existing listing before relisting, so no separate end call is needed.

### Bulk eBay Action Flow

The three-modal flow for bulk eBay operations:

1. **`bulkEbayModal`** — choose action (List, Update, End, Unlink, Move to Live, Move to Scheduled)
2. **`bulkEbaySelectionModal`** — pick "All Listed Items" or select specific items
3. **`bulkConfirmModal`** — confirm; shows day-picker for `update` (push schedule) and
   `go-scheduled` (set future date) actions

State is tracked in `bulkCurrentAction` and `bulkCurrentPlatform` globals. The executor
`executeBulkAction()` processes items sequentially with a 100 ms delay between calls.

---

## Secure Coding Standards - CRITICAL

### Why this section exists

Insecure code has slipped into this project before — image uploads that trusted the
client-supplied filename, paths built by string concatenation, missing Pillow validation,
and routes that forgot `@login_required`. These rules are the standing fix. Apply them on
every change. If existing code violates a rule, fix the existing code; do not copy it.

This section is the canonical source. The condensed version in
[`.github/copilot-instructions.md`](.github/copilot-instructions.md) is auto-loaded for
every Copilot session and points back here.

### Threat model summary

- **Multi-user app**: every user has their own subtree under `instance/data/{username}/`.
  A bug that lets user A read or write user B's files is a critical defect.
- **No database**: storage is CSV + JSON + S3 objects. Path-traversal and key-collision
  bugs map directly to data-loss / data-leak bugs.
- **Public S3 bucket for images**: anything written there is world-readable. Never put
  secrets, raw uploads, or PII there.
- **AWS-deployed Flask**: SSRF to `169.254.169.254` would leak instance role credentials.

### Rule 1 — File uploads

| Do | Do not |
|----|--------|
| Wrap every client filename with `werkzeug.utils.secure_filename()` before joining it to a path or S3 key | Pass `request.files['x'].filename` directly into `os.path.join`, `open`, or an S3 key |
| Validate image content with `PIL.Image.open(stream).verify()` (or full re-decode) at the upload site | Trust the file extension or `Content-Type` header |
| Enforce a server-side size cap (Flask `MAX_CONTENT_LENGTH` and/or explicit length check) | Allow unbounded uploads — they enable DoS and decompression bombs |
| Use an allow-list of extensions and MIME types (`.jpg`, `.jpeg`, `.png`, `.webp`) | Use a deny-list — attackers will find an extension you forgot |
| Generate the stored filename (UUID, SKU-based, hash) | Reuse the user-supplied filename in storage |
| Catch `PIL.UnidentifiedImageError` and `PIL.Image.DecompressionBombError` and reject the request | Let Pillow exceptions bubble up as a 500 |

```python
# GOOD - canonical upload validation
from werkzeug.utils import secure_filename
from PIL import Image, UnidentifiedImageError

ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp'}
MAX_BYTES = 15 * 1024 * 1024

def validate_uploaded_image(file_storage):
    name = secure_filename(file_storage.filename or '')
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext not in ALLOWED_EXT:
        abort(400, 'Unsupported image type')

    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_BYTES:
        abort(413, 'Image too large')

    try:
        img = Image.open(file_storage.stream)
        img.verify()  # Pillow integrity check
    except (UnidentifiedImageError, Image.DecompressionBombError, Exception):
        abort(400, 'Invalid image')
    file_storage.stream.seek(0)
    return ext
```

### Rule 2 — Path handling

- Never build filesystem paths by string concatenation with user input. Use `pathlib.Path`
  or `os.path.join` + `secure_filename`, then **resolve and confine**:
  ```python
  base = Path(user_dir).resolve()
  candidate = (base / secure_filename(name)).resolve()
  if base not in candidate.parents and base != candidate:
      abort(400, 'Invalid path')
  ```
- Reject `..`, absolute paths, null bytes (`\x00`), and symlink components from user input.
- Multi-user file/CSV/S3 access **must** go through helpers in `app/utils/user_context.py`
  (`get_user_csv_path`, `get_user_image_dir`, etc.). Routes and services must not hand-craft
  `instance/data/{username}/...` strings.
- Never accept a `username` (or any path component) from a request body, query string, or
  header for authorization decisions. Use `session['username']` only.

### Rule 3 — Subprocess, shell, SQL, templates, deserialization

| Never | Use instead |
|-------|-------------|
| `subprocess.run(cmd, shell=True)` with user input | `subprocess.run([prog, arg1, arg2], shell=False)` |
| f-string SQL / CSV / HTML / JSON with user input | Parameterized APIs (`csv.writer`, `json.dumps`, Jinja autoescape, DB params) |
| `{{ value \| safe }}` on user content | Default Jinja autoescape; sanitize HTML server-side if rich text is required |
| `eval`, `exec`, `pickle.loads` | `ast.literal_eval` for literals, JSON for data |
| `yaml.load(s)` | `yaml.safe_load(s)` |
| Concatenating XML for eBay | `EbayService._sanitize_trading_payload_strings()` (see eBay section) |

### Rule 4 — Authentication & authorization

- Every route that reads or mutates user data **must** carry `@login_required`.
- Every state-changing route (POST / PUT / PATCH / DELETE) **must** also carry
  `@csrf_required`.
- Scope every file, CSV, JSON, and S3 access to `session['username']` via `user_context`.
  Authorization is never derived from request parameters.
- Sync-locked routes use `@sync_not_locked`; disk-sensitive routes use
  `@disk_space_required`. Don't bypass these to "make a test work".
- Sessions invalidate on app restart — do not add a "remember me" path that survives
  restart without re-authentication.

### Rule 5 — Secrets, logging, error responses

- Read secrets only via `get_secret()` in `app/config.py` (precedence: AWS Secrets Manager
  → environment variable → default). Never hard-code keys, tokens, passwords, or AWS
  credentials.
- Never commit `.env`, decrypted vault contents, or `~/.vault_pass`. Vault stays encrypted
  in `deployment/group_vars/vault.yml`.
- Per-user eBay credentials live in Secrets Manager via
  `app/services/user_secrets_service.py`. Do not write them to CSV, JSON, logs, or
  responses.
- Use `safe_error_message(exc)` from `app/utils/logging_utils.py` when forming the
  client-facing error string. In production it returns a generic message; full detail
  goes to the logger only.
- Never log: passwords, full session cookies, eBay user tokens, AWS credentials, full
  request bodies for auth endpoints, or full S3 pre-signed URLs.

### Rule 6 — External requests, SSRF, timeouts

- Every `requests.*` / `urllib` call **must** set an explicit `timeout=` (connect + read).
  Default to `timeout=(5, 30)` unless there's a reason for more.
- Never fetch a URL supplied by the client without an allow-list of hosts and schemes.
  Block `file://`, `gopher://`, `http://169.254.169.254`, and RFC-1918 / loopback CIDRs.
- Disable redirects (`allow_redirects=False`) when fetching from an allow-listed host
  unless redirects are explicitly required.

### Rule 7 — Input validation & rate limiting

- Validate every API input at the entry point: required fields, types, length caps,
  numeric ranges, enum membership. Reject unknown fields rather than silently ignoring
  them.
- Cap string lengths server-side (titles, descriptions, SKUs). Don't rely on the browser.
- Respect `app/security.py` rate limiting. New public endpoints must be explicitly added
  to the rate-limit config; never bypass it.
- Login, password reset, eBay token exchange, and bulk-action endpoints need stricter
  rate limits than the default.

### Rule 8 — CSV / JSON / S3 specifics

- All CSV writes go through `app/services/csv_service.py` (file-locking + sanitization).
  Do not open the CSV directly with `open(..., 'w')` from a route or another service.
- CSV cell values that begin with `=`, `+`, `-`, `@`, tab, or CR must be prefixed with a
  single quote (`csv_sanitizer.py`) to prevent CSV-injection in spreadsheet apps.
- S3 object keys must be derived from `user_context` helpers + a generated filename.
  Never put raw user filenames in keys.
- `instance/user_preferences.json` is loaded with `json.load` — do not load arbitrary
  user-supplied JSON without size caps and schema validation.

### Pre-commit security checklist

Before finalizing any code change, walk this list:

- [ ] No `request.files[...].filename` reaches a path or S3 key without `secure_filename`
- [ ] All image uploads run through `Image.open(...).verify()` **and** a size cap
- [ ] No new `shell=True`, `eval`, `exec`, `pickle.loads`, `yaml.load`, or `|safe` on user data
- [ ] Every new state-changing route has `@login_required` and `@csrf_required`
- [ ] User-controlled filesystem paths are `secure_filename`-d, resolved, and confined under the expected base
- [ ] No secrets, tokens, full cookies, or full request bodies appear in log calls
- [ ] All outbound `requests` calls have an explicit `timeout`
- [ ] CSV writes go through `csv_service`; CSV cells are sanitized
- [ ] All colors / paths / filenames use existing helpers (`tokens.css`, `user_context`) rather than re-implementations
- [ ] Multi-user file access uses `app/utils/user_context.py`, never hand-crafted `instance/data/{username}/...` strings
- [ ] Error responses use `safe_error_message()`; full detail is in logs only

---

## General Coding Standards

These rules cover recurring bugs and lint warnings found during the April 2026 hardening
pass. Apply them on every change — they are not security-specific but prevent the same
class of defect repeatedly.

### Python — Never Use `str(e)` in JSON Responses

`str(e)` leaks internal paths, class names, and stack details to the client. Use
`safe_error_message(exc)` from `app/utils/logging_utils.py` for every `jsonify` error
response. Full detail goes to the logger only.

```python
# BAD — leaks internal error detail to the client
except Exception as e:
    return jsonify({'error': str(e)}), 500

# GOOD — sanitized client message, full detail in logs
from app.utils.logging_utils import safe_error_message
except Exception as e:
    logger.exception("operation failed")
    return jsonify({'error': safe_error_message(e)}), 500
```

This is the enforcement companion to Rule 5 in the Secure Coding Standards section.

### Python — All Imports at Module Level

Never place `import` or `from … import` statements inside functions, route handlers, or
`except` blocks. Imports inside handlers create "unresolved reference" warnings, confuse
static analysis, and hide circular-dependency problems.

```python
# BAD — import inside a route handler / except block
@main_bp.route('/download')
def download_csv():
    try:
        ...
    except Exception:
        from app.utils.user_context import get_current_username  # ← wrong
        ...

# GOOD — import once at the top of the file
from app.utils.user_context import get_current_username, get_user_csv_file

@main_bp.route('/download')
def download_csv():
    ...
```

**Exceptions — when a deferred import is required:**

1. **Circular imports** — module A imports module B which imports module A. Document with:
   ```python
   from app.services.s3_service import s3_service  # Deferred: avoids circular import
   ```
2. **Initialization-order / app-context** — service singletons are constructed at module
   load time (before the Flask app context exists). Helpers that call `current_app` or
   `session` must be deferred until a request is in flight.
   ```python
   from app.utils.user_context import get_user_csv_file  # Deferred: requires app context
   ```

In both cases, add the comment so reviewers know the deferral is intentional, not an
oversight, and do **not** silently re-import a symbol that is already at module level.

### Python — Initialize Variables Before `try` Blocks

Any variable referenced in an `except` or `finally` block must be initialized before the
`try` — not inside it. Assigning inside `try` leaves the variable unbound if an exception
fires before that line.

```python
# BAD — data_type referenced in except, but only set inside try
try:
    data_type = request.args.get('type', 'summary')
    ...
except Exception as e:
    logger.error("failed to load %s", data_type)   # ← may be unbound

# GOOD — initialize before try
data_type = 'summary'
try:
    data_type = request.args.get('type', data_type)
    ...
except Exception as e:
    logger.error("failed to load %s", data_type)   # always defined
```

### Python — Use Pythonic Style and Documentation

Follow PEP 8 for code style and PEP 257 for docstrings.

- Use `snake_case` for functions/variables and `PascalCase` for classes.
- Add clear docstrings for public modules, classes, and functions.
- Keep style compatible with `black` output (line wrapping and spacing).

```python
# GOOD
class UserExportService:
    """Builds CSV exports for the current user."""

    def build_export_rows(self) -> list[dict]:
        ...
```

### Python — Prefer Named Functions Over Non-Trivial `lambda`

Use named `def` functions for non-trivial logic. This improves stack traces, typing,
reuse, and debugging. Tiny sort keys are acceptable as inline `lambda`.

```python
# BAD
records.sort(key=lambda r: normalize_title(r.get('title', '').strip()))

# GOOD
def _sort_key(record: dict) -> str:
    return normalize_title(record.get('title', '').strip())

records.sort(key=_sort_key)
```

### Python — Type Hints on Public and Boundary APIs

Use type hints where they provide real value, especially on route handlers, service public
methods, and helper utilities shared across modules.

- Prefer explicit return types on public methods.
- Use `typing` aliases for repeated complex structures.
- Keep runtime behavior unchanged; hints should clarify intent, not add noise.

### Python — Formatting and Import Order

- Run `black` on edited Python files.
- Run `isort` for stable import grouping/order.
- Do not manually micro-format around these tools.

### Python — Naming, Readability, and DRY

- Prefer meaningful names (`listing_status`, `analytics_dir`) over cryptic abbreviations.
- Keep functions focused and short; extract repeated logic to shared helpers.
- Avoid copy-paste branches when a small helper or registry can express the pattern once.

### Python — Exception Specificity and Boundaries

Catch specific exceptions first. Use broad `except Exception` only at clear boundaries
(route handlers, task boundaries, service top-level operations), where errors are logged
and sanitized for clients.

### Python — No Import-Time Side Effects

Module import should define symbols, not execute network/file/session-dependent work.

- No API calls, filesystem mutations, or session access at module import time.
- Defer runtime-dependent initialization to request handlers, service methods, or app startup hooks.

### JavaScript — Modal / Pending-State Lifecycle

Confirm flows that mutate pending state must follow a strict single-owner pattern.

**Rule:** The confirm function owns the full lifecycle — snapshot, execute, and clean up.
Executors never read or reset `pending*` / `bulk*` state directly.

```javascript
// BAD — cleanup scattered across confirm, cancel, and multiple executors
async function confirmDelete() {
    await executeDelete();
    pendingAction = null;   // ← duplicated in execute too
}
async function executeDelete() {
    ...
    pendingAction = null;   // ← wrong place
}

// GOOD — single owner, try/finally guarantees cleanup even on error
async function confirmDelete() {
    // 1. Snapshot state before any async work
    const sku = pendingAction.sku;
    const type = pendingAction.type;

    try {
        await executeDelete(sku);   // executor takes values as args
    } finally {
        pendingAction = { type: null, sku: null };   // always runs
    }
}

// Cancel path clears immediately (no try/finally needed — no async work)
function cancelDelete() {
    pendingAction = { type: null, sku: null };
    closeModal();
}

// Executor accepts values as parameters — never reads/resets global state
async function executeDelete(sku) {
    const resp = await fetch(`/api/comic/${sku}`, { method: 'DELETE', ... });
    ...
}
```

### JavaScript — Declare Related State Variables Together

All variables that form a single logical state group must be declared in one contiguous
block at the top of their scope. Do not scatter declarations or redeclare a variable in
a nested scope.

```javascript
// BAD — bulkGoScheduledDays declared again later, shadowing the first
let bulkCurrentAction = null;
let bulkCurrentPlatform = null;
...
// 200 lines later:
let bulkGoScheduledDays = 0;   // ← duplicate declaration

// GOOD — all bulk state in one place
let bulkCurrentAction    = null;
let bulkCurrentPlatform  = null;
let bulkSelectedItems    = [];
let bulkScheduleDays     = 0;
let bulkGoScheduledDays  = 0;
window.bulkActionComics  = null;
```

### JavaScript — Use Registry Arrays for Grouped DOM Operations

When multiple modals (or other elements) must be hidden / reset together, define a
constant array of their IDs and iterate — do not duplicate `hide` / `pop` calls.

```javascript
// BAD — duplicated teardown in every branch
modal1.style.display = 'none'; popModalFromStack('modal1');
modal2.style.display = 'none'; popModalFromStack('modal2');
// ... repeated in 4 other functions

// GOOD — single registry, one helper
const BULK_MODAL_IDS = ['bulkConfirmModal', 'bulkEbaySelectionModal', 'bulkEbayModal'];

function closeAllBulkModals() {
    BULK_MODAL_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
        popModalFromStack(id);
    });
}
```

### General Coding Checklist

Add these to your pre-commit review alongside the security checklist:

- [ ] No `str(e)` in `jsonify` error responses — use `safe_error_message(e)`
- [ ] All imports are at module level, not inside functions or except blocks
- [ ] Variables referenced in `except`/`finally` are initialized before the `try`
- [ ] PEP 8 + PEP 257 followed for modified Python modules
- [ ] Public functions/methods include useful type hints where practical
- [ ] Non-trivial `lambda` logic moved to named functions
- [ ] Edited Python files are formatted with `black` and imports sorted with `isort`
- [ ] Names are descriptive and repeated logic is extracted into helpers (DRY)
- [ ] Broad exception handlers are only used at boundaries with logging + sanitization
- [ ] No import-time side effects (network/file/session-dependent work)
- [ ] JS confirm functions snapshot state, execute in `try`, reset in `finally`
- [ ] JS executor functions accept values as arguments — no reads of `pending*` state
- [ ] Related JS state variables declared together in one block, no re-declarations
- [ ] Groups of modal/element operations use a registry constant + shared helper

---

## Documentation Standards

All documentation in `deployment/docs/` follows a consistent style modeled after
professional vendor guides (Cisco, HashiCorp, AWS). Apply these rules when creating
or editing any `.md` file in the project.

When code changes alter a user-facing workflow (new required steps, new preflight behavior,
new post-save actions), include a short matching note in docs (`README.md` or the relevant
guide in `deployment/docs/`) in the same change set.

### File Structure

**Guides** (procedural, step-by-step):

```markdown
# Chapter N: Title

One-line description of what this chapter covers.

---

## Section Name

Content...

---

## Next step

Continue to [Chapter N+1: Title](NEXT_FILE.md).

## See also

- [Chapter X: Title](FILE.md) — brief reason
- [Reference: Title](../reference/FILE.md) — brief reason
```

**Reference docs** (descriptive, not procedural):

```markdown
# Title Reference

One-line description.

---

## Section Name

Content...
```

### Rules

| Rule | Do | Do Not |
|------|----|--------|
| Title format (guides) | `# Chapter 6: Monitoring` | `# CloudWatch Monitoring Guide` |
| Title format (reference) | `# Architecture Reference` | `# Architecture Reference Guide v5.0` |
| Subtitle | One plain sentence | Bold text, version numbers, dates, status badges |
| Ending (guides) | Single `## Next step` link, optional `## See also` (2–3 links max) | Multiple "next step" sections, decision tables, "pick one" blocks |
| Prerequisite reference | `> Prerequisite: Complete [Chapter 1](PREREQUISITES.md).` | 15-line checklist re-verifying the previous chapter |
| Cross-references | `See [Chapter 5: Operations](OPERATIONS.md).` | `→ **[OPERATIONS.md](OPERATIONS.md)** — Full guide!` |
| Tone | Direct, declarative prose | Emojis in headings, exclamation marks, "Think of it as…" analogies |
| Metadata | None — use Git history | `**Version:** 5.0`, `**Date:** Feb 2026`, `**Status:** Production-Ready` |
| Variable placeholders | Use `{app_name}` inline without explanation | Multi-line note explaining what `{app_name}` means (stated once in Ch. 1) |
| Emoji | Allowed in verification output (`✓`) and warnings (`⚠️`) | Not in headings, not in bullet lists as decoration (`🚀`, `📋`, `🎉`) |

### Chapter Numbers

Guides are numbered 1–11 and live in `deployment/docs/guides/`. Reference docs live in
`deployment/docs/reference/`. The table of contents is `deployment/docs/README.md`.
When adding a new guide, assign the next number and update the README.

| Chapter | File |
|---------|------|
| 1 | guides/PREREQUISITES.md |
| 2 | guides/QUICKSTART.md |
| 3 | guides/MANUAL_DEPLOYMENT.md |
| 4 | guides/UPDATING_APPLICATION.md |
| 5 | guides/OPERATIONS.md |
| 6 | guides/MONITORING.md |
| 7 | guides/SECRET_MANAGEMENT.md |
| 8 | guides/SECURITY_HARDENING.md |
| 9 | guides/MULTI_USER.md |
| 10 | guides/GIT_CONFIGURATION.md |
| 11 | guides/DECOMMISSION.md |

### Writing Checklist

Before finalizing any documentation change:

- [ ] Title matches the `# Chapter N: Title` pattern (guides) or `# Title` (reference)
- [ ] No version, date, or status metadata in the header
- [ ] No repeated prerequisite checks from the previous chapter
- [ ] File ends with a single `## Next step` (guides) or nothing (reference)
- [ ] No emojis in section headings
- [ ] Cross-references use chapter numbers: "See Chapter 5" not "See OPERATIONS.md"
- [ ] `docs/README.md` table of contents is updated if a file was added or renamed

---

## Summary

| Aspect | Guideline |
|--------|-----------|
| Primary Method | Simple commit messages (no internal quotes) |
| Backup Method | File method for complex messages |
| Never Do | Nest quotes in -m parameter |
| If dquote> Appears | Use file method instead |
| Pattern | git commit -m "type: description" |
| Example | git commit -m "docs: add deployment guide" |

---

**Key Point:** Following Rule 1 (simple messages) and Rule 2 (file method for complex) will PREVENT all dquote> errors from happening again.

---

**Last Updated:** April 24, 2026 (expanded General Coding Standards: Pythonic style, typing, formatting, DRY/readability)
