# Chapter 4: Updating Your Application

Deploy code changes to your running server.

---

## Overview

When you update your application code (fix bugs, add features, etc.), you need to:
1. Test changes locally
2. Commit to Git
3. Deploy to server
4. Verify it works
5. (Optional) Roll back if something breaks

---

## Before You Deploy

### 1. Test Locally

Always test changes before deploying to production:

```bash
# Navigate to project root
cd /path/to/{app_name}

# Activate virtual environment
source .venv/bin/activate
# or on Windows:
# .venv\Scripts\activate

# Install any new dependencies
pip install -r requirements.txt

# Run tests (if you have them)
pytest
# or
python -m unittest discover

# Test manually
python runapp.py
# Visit http://localhost:8000
```

**What to test:**
- ✅ Application starts without errors
- ✅ Pages load correctly
- ✅ No error messages in logs
- ✅ Performance is acceptable

### 2. Commit to Git

```bash
# Check what changed
git status

# Stage changes
git add .

# Commit with descriptive message
git commit -m "fix: resolve login bug and improve error handling"

# Push to repository
git push origin main
```

**Good commit messages:**
- ✅ "fix: resolve timeout issue on dashboard"
- ✅ "feat: add CSV export functionality"
- ✅ "perf: optimize database queries"
- ❌ "update" or "fix stuff"

---

## Deploy to Server

### Option A: Automated Deployment (Recommended)

**Fastest way - runs the update playbook**

```bash
cd deployment

# Update application from Git
ansible-playbook -i inventories/hosts.yml playbooks/update.yml
```

**What it does:**
- ✅ Pulls latest code from Git
- ✅ Installs new dependencies (if any)
- ✅ Runs CSV schema migration if needed
- ✅ Restarts application service
- ✅ Verifies it started successfully

**Duration:** 1-2 minutes

**If update fails:**
```bash
# See error details
ansible-playbook -i inventories/hosts.yml playbooks/update.yml -vv
```

### Option B: Manual Deployment via SSH

**For learning or if playbook fails**

```bash
# SSH to server
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# Navigate to app directory
cd /opt/{app_name}

# Pull latest code
git pull origin main

# Activate virtual environment
source /opt/{app_name}/.venv/bin/activate

# Install/update dependencies
pip install -r requirements.txt

# Run database migrations (if applicable)
# python -m alembic upgrade head
# or
# python manage.py migrate

# Restart application
sudo supervisorctl restart {app_name}

# Check if it started
sudo supervisorctl status {app_name}

# View recent logs
sudo tail -20 /var/log/apps/{app_name}/app.log

# Exit server
exit
```

---

## Verify Deployment

### Quick Health Check

```bash
# Test the application
curl http://YOUR_SERVER_IP
# Should return HTML/JSON, not error

# Or test specific endpoint
curl http://YOUR_SERVER_IP/health
# Should return HTTP 200

# Via browser
# Visit http://YOUR_SERVER_IP in your browser
```

### Check Logs

```bash
# SSH to server
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# View recent application logs
sudo tail -50 /var/log/apps/{app_name}/app.log

# Follow logs in real-time (useful while testing)
sudo tail -f /var/log/apps/{app_name}/app.log

# Check for errors
sudo grep ERROR /var/log/apps/{app_name}/app.log

# Exit
exit
```

### Check Service Status

```bash
# SSH to server
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# Check if service is running
sudo supervisorctl status {app_name}
# Should show: RUNNING

# Check if Nginx is running
sudo systemctl status nginx
# Should show: active (running)

# Exit
exit
```

---

## Troubleshooting Failed Deployments

### Application Won't Start After Update

**Symptom:** Service shows "failed" status

**Diagnosis:**
```bash
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# Check the error
sudo tail -100 /var/log/apps/{app_name}/app.log

# Check error log
sudo tail -50 /var/log/apps/{app_name}/error.log

# Check if dependencies installed
source /opt/{app_name}/.venv/bin/activate
pip list | grep -i dependency-name

# Try starting manually to see full error
cd /opt/{app_name}
source /opt/{app_name}/.venv/bin/activate
gunicorn --bind 127.0.0.1:8000 "app:create_app('production')" 2>&1 | head -50

exit
```

**Common causes:**
- ❌ Missing dependency (run `pip install -r requirements.txt` again)
- ❌ Syntax error in code (check git log, undo if needed)
- ❌ Missing environment variable (check vault.yml / Secrets Manager)
- ❌ Port already in use (check what's using the gunicorn port)


### High Error Rate After Deploy

**Symptom:** Lots of 500 errors appearing in logs

**Response:**
1. **Check what changed:**
   ```bash
   git log --oneline -5
   # Shows last 5 commits
   
   git show HEAD
   # Shows exactly what changed in latest commit
   ```

2. **Check error logs:**
   ```bash
   ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP
   sudo grep ERROR /var/log/apps/{app_name}/app.log | tail -20
   exit
   ```

3. **If you know the issue:** Fix and redeploy
4. **If unsure:** Rollback (see below)

---

## Rolling Back a Bad Deployment

**If something breaks, revert to previous version**

### Option A: Quick Rollback (Recommended)

```bash
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# Go to app directory
cd /opt/{app_name}

# Go back to previous commit
git reset --hard HEAD~1

# Restart application
sudo supervisorctl restart {app_name}

# Verify it started
sudo supervisorctl status {app_name}

exit
```

### Option B: Rollback via Playbook

```bash
cd deployment

# The update playbook should handle rollback
# But if not, use:
ansible-playbook -i inventories/hosts.yml playbooks/update.yml -e version=PREVIOUS_VERSION
```

### Option C: Manual Rollback to Specific Version

```bash
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

cd /opt/{app_name}

# Check available versions
git log --oneline | head -20

# Go back to specific version (e.g., 5 commits ago)
git checkout COMMIT_HASH

# Or go back N commits
git reset --hard HEAD~5

# Restart
sudo supervisorctl restart {app_name}

# Verify
sudo supervisorctl status {app_name}

exit
```

**Important:** After rollback, investigate what went wrong and fix before deploying again.

---

## Zero-Downtime Deployments

**Keep app running while deploying**

### How It Works

Standard deployment restarts the app (brief downtime). To avoid this:

1. **Blue-Green Deployment** (ideal but complex)
   - Run two instances (blue and green)
   - Deploy to inactive instance
   - Switch traffic when ready
   - Requires load balancer (beyond scope here)

2. **Thread-based concurrency** (what this app uses)
   - 1 gunicorn worker + 4 threads handles concurrent requests in one process
   - Updating requires a full worker restart (brief — a few seconds at most)
   - In-flight requests finish before the worker is replaced

3. **Application-Level** (simplest)
   - Supervisor catches the exit and restarts immediately
   - Gunicorn's graceful shutdown finishes pending requests before stopping
   - Downtime is typically under one second

**Our setup uses #2 and #3 by default.**

### Verify Zero-Downtime

During deployment:
```bash
# In one terminal, watch requests
while true; do curl -w "%{http_code}\n" -o /dev/null -s http://YOUR_SERVER_IP/health && sleep 1; done

# In another terminal, deploy
ansible-playbook -i inventories/hosts.yml playbooks/update.yml

# Keep watching - should see no 500/503 errors
```

**What you should see:**
- ✅ Continuous 200 responses (no failures)
- ✅ Maybe slight latency spike
- ✅ No error codes

**If you see errors:**
- Something went wrong with deployment
- Rollback immediately
- Investigate before redeploying

---

## Deployment Checklist

**Before deploying to production:**

```
Pre-deployment:
  [ ] Code committed to Git
  [ ] Tested locally (app starts, pages load, no errors in logs)
  [ ] No sensitive data in code
  [ ] Dependencies updated in requirements.txt if new packages added

Deployment:
  [ ] Backup current state (git commit hash written down)
  [ ] Run update playbook
  [ ] Check service is running
  [ ] Verify health endpoint
  [ ] Test key features
  [ ] Check error logs

Post-deployment:
  [ ] Monitor for errors over next 5 minutes
  [ ] Check CloudWatch alarms
  [ ] Notify users if needed
  [ ] Document what changed
```

---

## Automating Deployments

**For continuous integration (CI/CD)**

### Option 1: Manual But Scripted

Create a deployment script:

```bash
#!/bin/bash
# deploy.sh

set -e  # Exit on error

echo "Deploying {app_name}..."

# Verify everything
git status | grep "working tree clean" || exit 1

# Deploy
cd deployment
ansible-playbook -i inventories/hosts.yml playbooks/update.yml

# Verify
curl -f http://YOUR_SERVER_IP/health || exit 1

echo "✅ Deployment successful!"
```

Run it: `./deploy.sh`

### Option 2: GitHub Actions (Advanced)

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Production

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Run tests
        run: |
          python -m pip install -r requirements.txt
          pytest
      
      - name: Deploy to AWS
        run: |
          cd deployment
          ansible-playbook -i inventories/hosts.yml playbooks/update.yml
```

Then every push to `main` auto-deploys!

---

## Deployment Frequency

**How often should you deploy?**

| Scenario | Frequency | Strategy |
|----------|-----------|----------|
| Bug fixes | ASAP | Deploy immediately |
| Features | Daily/Weekly | Deploy during low-traffic |
| Hotfixes | ASAP | Deploy, test, monitor closely |
| Minor updates | Weekly | Batch with other changes |
| Major changes | Monthly | Plan, test thoroughly |

**Best practices:**
- ✅ Deploy frequently (less risk per deploy)
- ✅ Deploy in business hours (support on-call if needed)
- ✅ Deploy before high-traffic periods
- ✅ Have rollback plan ready
- ✅ Monitor closely after deploy
- ❌ Don't deploy Friday night
- ❌ Don't deploy major changes without testing

---


## Next step

Continue to [Chapter 5: Operations](OPERATIONS.md).

## See also

- [Chapter 6: Monitoring](MONITORING.md) — dashboards and alarms
- [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — rotate credentials after deploy

