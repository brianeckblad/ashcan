# Chapter 5: Operations

Day-to-day operation: restarts, logs, backups, scaling, SSL, and troubleshooting.

---

## Quick reference

```bash
# SSH to server
ssh ubuntu@$server_host

# Application status
sudo supervisorctl status $app_name

# Tail live log
sudo tail -f /var/log/apps/$app_name/app.log

# Restart application
sudo supervisorctl restart $app_name

# Deploy code update
cd deployment && ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass

# Sync a vault change to Secrets Manager
cd deployment && ansible-playbook playbooks/setup-secrets-manager.yml --vault-password-file ~/.vault_pass
```

Load shell variables once per session for `$server_host`, `$app_name`, `$s3_bucket_name`, `$aws_region`:

```bash
cd deployment && source scripts/load-vars.sh
```

---

## AWS CLI Profiles

All deployment playbooks use the `{app_name}-deploy` named profile automatically (via `environment.AWS_PROFILE`).
For manual `aws` CLI commands, include the profile flag:

```bash
aws s3 ls --profile {app_name}-deploy
aws secretsmanager list-secrets --profile {app_name}-deploy
```

Or export it for a full session:

```bash
export AWS_PROFILE={app_name}-deploy
```

---

## Daily health check

```bash
# HTTPS is responding
curl -I https://$server_name
# Expected: HTTP/2 200

# SSH to the server
ssh ubuntu@$server_host

# Application is running and healthy
sudo supervisorctl status $app_name
# Expected: {app_name}   RUNNING   pid XXXXX, uptime X:XX:XX

# No recent errors
sudo grep -c ERROR /var/log/apps/$app_name/app.log
# Expected: low count; investigate spikes

# Disk space not critical
df -h /opt/$app_name /var/log/apps/$app_name
# Expected: Use% < 80%

exit
```

---

## Log management

### Application logs

```bash
ssh ubuntu@$server_host

# Log directory
ls /var/log/apps/$app_name/
# app.log, service.log, cleanup.log, error.log, nginx_access.log, nginx_error.log

# Watch live
sudo tail -f /var/log/apps/$app_name/app.log

# Last 100 lines
sudo tail -n 100 /var/log/apps/$app_name/app.log

# Search for errors
sudo grep ERROR /var/log/apps/$app_name/app.log | tail -50

# Top requesting IPs today
sudo awk '{print $1}' /var/log/apps/$app_name/nginx_access.log | sort | uniq -c | sort -rn | head -10

# Response codes distribution
sudo awk '{print $9}' /var/log/apps/$app_name/nginx_access.log | sort | uniq -c
```

### Log rotation

Logrotate configuration is installed by `setup.yml` under `/etc/logrotate.d/$app_name`.
Rotation frequency and retention are controlled by `log_max_size` and `log_retention_days` in vault.yml.

```bash
# Check current config
sudo cat /etc/logrotate.d/$app_name

# Force a rotation manually
sudo logrotate -f /etc/logrotate.d/$app_name

# Verify rotated files exist
ls -lh /var/log/apps/$app_name/*.gz
```

---

## Restarts

```bash
ssh ubuntu@$server_host

# Graceful restart (zero connection drop for in-flight requests)
sudo supervisorctl restart $app_name

# Full stop/start
sudo supervisorctl stop $app_name
sudo supervisorctl start $app_name

# Reload nginx (config change, no downtime)
sudo nginx -t && sudo systemctl reload nginx
```

---

## CloudWatch alarms

CloudWatch alarms are configured via `setup-monitoring.yml`. To add or adjust alarms after deployment,
use the AWS Console (CloudWatch → Alarms → Create alarm) or the AWS CLI:

```bash
aws cloudwatch describe-alarms \
    --query 'MetricAlarms[?starts_with(AlarmName, `'$app_name'`)].{Name:AlarmName,State:StateValue}' \
    --output table

aws cloudwatch describe-alarms --state-value ALARM
```

The three alarms to watch: `HighErrorRate`, `HighCPU`, `DiskSpaceCritical`.

---

## Verify backups

This app's primary persistence is S3 (images + CSV exports) and AWS Secrets Manager (config).
The in-app snapshot feature creates per-user ZIPs under `{S3_FOLDER}/{username}/snapshots/`.

```bash
# List all objects in the app bucket
aws s3 ls s3://$s3_bucket_name/ --recursive --human-readable --summarize

# List snapshots for a user
aws s3 ls s3://$s3_bucket_name/production/admin/snapshots/
```

On-server instance data (`items.csv`, `user_preferences.json`) is synced to S3 on startup and
in a background thread — no separate backup cron is needed.

---

## Disk space management

```bash
ssh ubuntu@$server_host

# Disk usage at a glance
df -h

# Largest directories under the app
sudo du -h --max-depth=2 /opt/$app_name/ | sort -h | tail -20

# Log directory size
sudo du -sh /var/log/apps/$app_name/

# Clean old rotated logs (beyond logrotate retention)
sudo find /var/log/apps/$app_name/ -name "*.gz" -mtime +30 -delete

# Supervisor log
sudo du -sh /var/log/supervisor/

exit
```

If disk > 90%: clean rotated logs, check `/opt/$app_name/instance/exports/` for large CSV exports.

---

## Secrets rotation

See [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) for full procedures.

Quick reference:

| Credential | Rotation method |
|-----------|----------------|
| eBay token | `secret-rotate.yml` + `secret-promote.yml` |
| Admin passwords, Flask key | Edit vault → `setup-secrets-manager.yml` → restart |
| Deploy IAM access keys | Re-run `create-deploy-user.yml` (auto-rotates) |
| `git_token` | Edit vault only (not synced to Secrets Manager) |

---

## SSL certificate

Let's Encrypt certificates expire after 90 days. Certbot auto-renews at 60 days remaining
via a systemd timer installed by `setup.yml`.

```bash
ssh ubuntu@$server_host

# Check certificate status and expiry
sudo certbot certificates

# Verify auto-renewal timer is active
sudo systemctl list-timers | grep certbot
# Expected: certbot-renew.timer with a recent LAST trigger

# Dry run (test without renewing)
sudo certbot renew --dry-run

# Force manual renewal if needed
sudo certbot renew --force-renewal
sudo systemctl reload nginx

exit
```

If renewal fails with `Address already in use`:

```bash
sudo systemctl stop nginx
sudo certbot renew --force-renewal
sudo systemctl start nginx
```

If DNS validation fails: confirm `server_name` in vault.yml has an A record pointing to `$server_host`.
Run `ansible-playbook playbooks/setup-ssl.yml --vault-password-file ~/.vault_pass` once DNS resolves.

---

## Deployment procedures

### Standard code update

```bash
# 1. Commit and push changes
git add . && git commit -m "fix: description" && git push origin main

# 2. Deploy
cd deployment
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass

# 3. Verify
curl -I https://$server_name
ssh ubuntu@$server_host
sudo supervisorctl status $app_name
sudo tail -20 /var/log/apps/$app_name/app.log
exit
```

### Hotfix

```bash
git add . && git commit -m "fix: critical bug" && git push origin main
cd deployment && ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

### Rollback to a previous commit

```bash
ssh ubuntu@$server_host

cd /opt/$app_name
git log --oneline -5        # identify the commit to return to
git reset --hard <hash>

source /opt/$app_name/.venv/bin/activate
pip install -r requirements.txt

sudo supervisorctl restart $app_name
sudo supervisorctl status $app_name
sudo tail -20 /var/log/apps/$app_name/app.log
exit
```

After rolling back, investigate the root cause before re-deploying.

---

## AWS operations reference

### Secrets Manager

```bash
# View current secret
aws secretsmanager get-secret-value \
    --secret-id ${app_name}/production \
    --region $aws_region \
    --query SecretString \
    --output text | python3 -m json.tool

# Check versions
aws secretsmanager describe-secret \
    --secret-id ${app_name}/production \
    --region $aws_region
```

### S3

```bash
# List all objects
aws s3 ls s3://$s3_bucket_name/ --recursive

# Download a specific file
aws s3 cp s3://$s3_bucket_name/production/admin/items.csv ./items-backup.csv

# Sync a local dir to S3
aws s3 sync ./local-dir/ s3://$s3_bucket_name/prefix/
```

### CloudWatch logs

```bash
# List log groups for this app
aws logs describe-log-groups \
    --query 'logGroups[?contains(logGroupName, `'$app_name'`)].logGroupName' \
    --output table

# Search recent errors
aws logs filter-log-events \
    --log-group-name /aws/ec2/$app_name \
    --start-time $(date -d '1 hour ago' +%s)000 \
    --filter-pattern "ERROR"

# Tail in real-time
aws logs tail /aws/ec2/$app_name --follow
```

### Monthly AWS cost check

```bash
aws ce get-cost-and-usage \
    --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
    --granularity MONTHLY \
    --metrics UnblendedCost \
    --group-by Type=SERVICE \
    --output table
```

---

## Security operations

### Blocked IPs

The app automatically blocks IPs after repeated attack-pattern hits (5 hits in 60 s → 1-hour block).

```bash
# Check via admin API (must be logged in as admin)
curl http://localhost:8000/api/admin/security/blocked-ips

# Check logs
ssh ubuntu@$server_host
sudo grep "IP BLOCKED" /var/log/apps/$app_name/app.log | tail -20
exit

# Unblock via admin API
curl -X POST http://localhost:8000/api/admin/security/unblock-ip \
    -H "Content-Type: application/json" \
    -d '{"ip": "1.2.3.4"}'
```

### Review attack attempts

```bash
ssh ubuntu@$server_host
sudo grep "ATTACK DETECTED" /var/log/apps/$app_name/app.log | tail -20
sudo grep "RATE LIMIT" /var/log/apps/$app_name/app.log | tail -20
exit
```

---

## Incident response

### Application not responding

```bash
# Check server health
aws ec2 describe-instance-status --instance-ids i-XXXXX

# Check process
ssh ubuntu@$server_host
sudo supervisorctl status $app_name
sudo tail -50 /var/log/apps/$app_name/app.log

# Restart
sudo supervisorctl restart $app_name
exit
```

### Application won't start after update

```bash
ssh ubuntu@$server_host

# Full startup trace
cd /opt/$app_name
source /opt/$app_name/.venv/bin/activate
gunicorn --bind 127.0.0.1:$gunicorn_port "app:create_app('production')" 2>&1 | head -60

exit
```

| Error in log | Cause |
|-------------|-------|
| `ModuleNotFoundError` | New dependency not in `requirements.txt` |
| `SyntaxError` | Python error in changed file |
| `KeyError` / secret missing | New secret added to code but not yet synced to Secrets Manager |
| `Address already in use` | Old process still holding port — see restart procedure |

If port is stuck:
```bash
sudo supervisorctl stop $app_name
sudo pkill -f "gunicorn.*$app_name" || true
sudo supervisorctl start $app_name
```

### Disk full

```bash
ssh ubuntu@$server_host
df -h
sudo du -h --max-depth=2 /opt/$app_name/ | sort -h | tail -10
sudo du -sh /var/log/apps/$app_name/
sudo find /var/log/apps/$app_name/ -name "*.gz" -delete
exit
```

### High CPU

```bash
ssh ubuntu@$server_host
ps aux | grep gunicorn       # one process expected (1 worker + 4 threads)
top -b -n 1 | head -20
sudo supervisorctl restart $app_name
exit
```

---

## Decommission

When you are done with the application, see [Chapter 11: Decommission](DECOMMISSION.md) for safe teardown.

---

## Next step

Continue to [Chapter 6: Monitoring](MONITORING.md).

## See also

- [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md) — deploy code changes
- [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — rotate credentials
