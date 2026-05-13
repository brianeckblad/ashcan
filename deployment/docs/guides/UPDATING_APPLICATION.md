# Chapter 4: Updating Your Application

Deploy code changes to your running server.

---

## Overview

The update cycle is:

1. Make and test changes locally
2. Commit and push to git
3. Run `update.yml` to pull and restart on the server
4. Verify the deployment is healthy

---

## Step 1 — Test locally

Before deploying, confirm the application starts cleanly on your machine:

```bash
cd /path/to/{app_name}
source .venv/bin/activate
pip install -r requirements.txt   # pick up any new packages
python runapp.py
# Visit http://localhost:8000 and exercise the changed flows
```

Check that:
- The application starts without errors
- Changed pages and API routes respond correctly
- No ERROR or CRITICAL lines appear in the terminal output

---

## Step 2 — Commit and push

```bash
git status          # confirm only expected files changed
git add .
git commit -m "fix: describe what changed"
git push origin main
```

Write commit messages that explain *what* changed, not *how*:

- `fix: resolve image upload timeout on slow connections`
- `feat: add CSV export to eBay format`
- `chore: update Pillow to 10.3.0`

---

## Step 3 — Deploy to server

```bash
cd deployment
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

The playbook:
- Pulls the latest commit from git
- Installs any new packages from `requirements.txt`
- Restarts the application under Supervisor

**Duration:** 1–2 minutes.

If the run fails partway through, fix the cause and re-run — Ansible skips completed
steps and retries only the remaining work.

For verbose error output:
```bash
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass -vv
```

---

## Step 4 — Verify

```bash
# HTTPS still responding
curl -I https://$server_name
# Expected: HTTP/2 200

# SSH to the server for a deeper check
ssh ubuntu@$server_host

sudo supervisorctl status $app_name
# Expected: RUNNING

sudo tail -20 /var/log/apps/$app_name/app.log
# Expected: startup lines, no ERROR

exit
```

---

## Manual update via SSH

If the playbook is unavailable or you need to debug on the server directly:

```bash
ssh ubuntu@$server_host

cd /opt/$app_name
git pull origin main

source /opt/$app_name/.venv/bin/activate
pip install -r requirements.txt

sudo supervisorctl restart $app_name
sudo supervisorctl status $app_name

sudo tail -20 /var/log/apps/$app_name/app.log
exit
```

---

## Troubleshooting a failed update

### Application won't start after update

```bash
ssh ubuntu@$server_host

# Read the startup error
sudo tail -100 /var/log/apps/$app_name/app.log

# Try starting gunicorn manually to see the full traceback
cd /opt/$app_name
source /opt/$app_name/.venv/bin/activate
gunicorn --bind 127.0.0.1:$gunicorn_port "app:create_app('production')" 2>&1 | head -60

exit
```

Common causes:

| Symptom in log | Cause |
|---------------|-------|
| `ModuleNotFoundError` | New dependency not in `requirements.txt`, or `pip install` failed |
| `SyntaxError` | Python syntax error in changed file |
| `KeyError` / secret missing | New secret added to code but not yet synced to Secrets Manager |
| `Address already in use` | Previous process did not stop cleanly — see below |

If the old process is still holding the port:
```bash
sudo supervisorctl stop $app_name
sudo pkill -f "gunicorn.*$app_name" || true
sudo supervisorctl start $app_name
```

### Rolling back to the previous commit

If the change breaks the application and you need to restore the previous version immediately:

```bash
ssh ubuntu@$server_host

cd /opt/$app_name
git log --oneline -5        # identify the commit to return to
git reset --hard HEAD~1     # go back one commit (or use a specific hash)

sudo supervisorctl restart $app_name
sudo supervisorctl status $app_name
exit
```

After rolling back, investigate the root cause before re-deploying.

---

## Deployment checklist

```
Before deploying:
  [ ] Changes committed and pushed to git
  [ ] Application starts cleanly in local environment
  [ ] New packages added to requirements.txt if used
  [ ] New secrets added to vault.yml and synced via setup-secrets-manager.yml

After deploying:
  [ ] supervisorctl status shows RUNNING
  [ ] curl -I https://$server_name returns HTTP/2 200
  [ ] No ERROR lines in app.log
  [ ] Manual smoke-test of the changed feature
```

---

## Next step

Continue to [Chapter 5: Operations](OPERATIONS.md).

## See also

- [Chapter 6: Monitoring](MONITORING.md) — dashboards and alarms
- [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — sync new secrets after vault changes
