# Chapter 10: Git Configuration

Repository setup for deployment workflows.

---

## Quick Start (Recommended)

Just run the script - it automatically sets up git with your email based on your app name:

```bash
cd deployment
./scripts/configure-git.sh
```

**That's it!** Your email is now set to `{app_name}@brianeckblad.dev`

### Example:

```bash
$ cd deployment
$ ./scripts/configure-git.sh

Git Configuration Setup
==================================================

📝 Configuration:
   Name: Brian Eckblad
   Email: dockyard@brianeckblad.dev
   Scope: Local (this repo)

Setting git config for this repository...

✅ Local git config set (.git/config)

Your commits will now use:
   Author: Brian Eckblad <dockyard@brianeckblad.dev>

================================================== 
✅ Git configuration complete!
==================================================
```

---

## Usage Options

### Option 1: Auto-Detect from Config (Default)

Automatically reads `app_name` from your deployment configuration:

```bash
cd deployment
./scripts/configure-git.sh
```

**Sets up for:** This repository only (local config)  
**Email:** Extracted from `group_vars/vault.yml`

---

### Option 2: Manually Specify App Name

Useful if outside the deployment directory:

```bash
# Set for dockyard project
./scripts/configure-git.sh dockyard

# Or with full path
/path/to/dockyard/deployment/scripts/configure-git.sh myapp
```

**Sets up for:** This repository only (local config)  
**Email:** `rivit@brianeckblad.dev`

---

### Option 3: Global Configuration

Set git email globally for all repositories:

```bash
# Set globally for this app
./scripts/configure-git.sh --global dockyard

# Or from anywhere
/path/to/dockyard/deployment/scripts/configure-git.sh -g myapp
```

**Sets up for:** All repositories on this machine  
**Email:** `myapp@brianeckblad.dev`

⚠️ **Note:** Global config is useful when you always use the same email, but local config (per-repo) is recommended when working on multiple projects.

---

## How It Works

The script is designed to be **reusable across all your projects**:

```
Your Identity (hardcoded in script):
├── Name: Brian Eckblad (fixed)
└── Email domain: brianeckblad.dev (fixed)

Per-project:
├── Reads app_name from deployment config OR accepts as argument
└── Constructs email: {app_name}@brianeckblad.dev

Configuration scope:
├── Local (default): .git/config (this repo only)
└── Global (--global): ~/.gitconfig (all repos)
```

---

## Examples

### Example 1: rivit Project

```bash
cd ~/Development/dockyard/deployment
./scripts/configure-git.sh

# Sets: dockyard@brianeckblad.dev (local)
```

### Example 2: Comic Tracker Project

```bash
cd ~/Development/comic-tracker/deployment
./scripts/configure-git.sh

# Sets: comic-tracker@brianeckblad.dev (local)
```

### Example 3: Manually Specify for Global Use

```bash
./scripts/configure-git.sh --global invoicing

# Sets globally: invoicing@brianeckblad.dev (all repos)
```

---

## Verify It's Working

```bash
# Check what email git will use
git config user.email
# Shows: dockyard@brianeckblad.dev

# Check where it's configured
git config --show-origin user.email
# Shows: file:.git/config (local) or file:~/.gitconfig (global)

# Test with a commit
git add .
git commit -m "test: verify git config"
git log -1 --format=fuller
# Should show: Author: Brian Eckblad <dockyard@brianeckblad.dev>
```

---

## Change Email Later

```bash
# Change for this repo
git config user.email "newemail@domain.com"

# Change globally
git config --global user.email "newemail@domain.com"
```

---

## Script Personalization

If you ever need to change your name or email domain, edit the script:

```bash
nano deployment/scripts/configure-git.sh
```

Look for these lines at the top:

```bash
# Configuration - personalize this section for your identity
GIT_USER_NAME="Brian Eckblad"
EMAIL_DOMAIN="brianeckblad.dev"
```

Update these values and the script will use your new identity for all projects.

---

## Integration with Deployment

The script works perfectly with your deployment workflow:

```bash
# 1. Create deployment config
./scripts/local-dev-setup.sh

# 2. Configure git automatically  
./scripts/configure-git.sh

# 3. Your commits now use dockyard@brianeckblad.dev
git add .
git commit -m "Initial setup"
```

---

## Troubleshooting

**"Not in a git repository"**
```bash
# Must run inside a git repo for local config
# Either: run from repo root, or use --global flag
./scripts/configure-git.sh --global myapp
```

**"Could not determine app name"**
```bash
# Manually specify the app name
./scripts/configure-git.sh myapp
```

**Want to verify the script works?**
```bash
cd /path/to/any/repo
/path/to/dockyard/deployment/scripts/configure-git.sh myapp
```

---

## Next step

Continue to [Chapter 13: Decommission](DECOMMISSION.md).

## See also

- [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md) — deploy code changes via Git
- [Chapter 2: Quick Start](QUICKSTART.md) — automated deployment workflow
