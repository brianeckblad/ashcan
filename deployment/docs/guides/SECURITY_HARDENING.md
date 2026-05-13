# Chapter 8: Security Hardening
Verify, tune, and maintain the security controls for this application on a shared server.

---

## Overview

Hardening for this application covers app-level controls only: file permissions, SSL, nginx headers, and rate limiting. OS-level hardening (SSH config, sysctl, fail2ban) is the responsibility of the server admin and is applied separately outside of these playbooks.

---

## App-Level Hardening

These settings are applied automatically by `setup.yml` and re-applied on every `update.yml` run.

### File Permissions

| Path | Owner | Group | Mode | Purpose |
|------|-------|-------|------|---------|
| `/opt/{app_name}/` | `{app_runtime_user}` | `{app_name}` | `2775` (setgid) | App directory |
| `/opt/{app_name}/instance/` | `{app_runtime_user}` | `{app_name}` | `2775` (setgid) | Data directory |
| `/var/log/apps/{app_name}/` | `{app_runtime_user}` | `{app_name}` | `2775` (setgid) | Log directory |
| `instance/user_preferences.json` | `{app_runtime_user}` | `{app_name}` | `0640` | User credentials |
| `instance/*.csv`, `instance/sku.txt` | `{app_runtime_user}` | `{app_name}` | `0664` | Data files |
| `app/static/` | `{app_runtime_user}` | `{app_name}` | `2775` (recurse) | Static assets |
| `app/scripts/` | `{app_runtime_user}` | `{app_name}` | `2775` (recurse) | Utility scripts |
| Log files (`*.log`) | `{app_runtime_user}` | `{app_name}` | `0664` | Not executable |

The `{app_name}` group contains both `{server_admin_user}` (deploy) and `{app_runtime_user}` (runtime). Setgid on directories ensures new files inherit the group automatically.

To re-apply permissions without redeploying code:

```bash
cd deployment
ansible-playbook playbooks/harden-permissions.yml --vault-password-file ~/.vault_pass
```

### SSL/HTTPS

| Setting | Value |
|---------|-------|
| Certificate provider | Let's Encrypt (certbot) |
| Auto-renewal | Daily cron + systemd timer |
| TLS version | 1.2+ (Let's Encrypt defaults) |
| HSTS | 1 year, includeSubDomains |
| HTTP redirect | 301 to HTTPS |
| OCSP stapling | Enabled |

### Nginx Security Headers (per-vhost)

| Header | Value |
|--------|-------|
| `X-Frame-Options` | `SAMEORIGIN` |
| `X-Content-Type-Options` | `nosniff` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |
| `Content-Security-Policy` | Restrictive policy allowing self, S3, eBay images |
| `server_tokens` | `off` (hides Nginx version) |

### Nginx Rate Limits (per-vhost)

| Zone | Default rate | Purpose |
|------|-------------|---------|
| `login_limit` | 20 req/min | Login endpoint |
| `api_limit` | 200 req/min | API endpoints |
| `general_limit` | 300 req/min | General pages |

To update headers or rate limits, edit `deployment/templates/nginx.conf.j2` and redeploy:

```bash
cd deployment
ansible-playbook playbooks/update.yml --vault-password-file ~/.vault_pass
```

---

## Verifying App-Level Hardening

### Check file permissions

```bash
ssh ubuntu@YOUR_SERVER

# App directory ownership and setgid
ls -la /opt/{app_name}/
# Expected: drwxrwsr-x  owner:group = {app_runtime_user}:{app_name}
# The 's' in group-execute confirms setgid is set.

# Log directory
ls -la /var/log/apps/{app_name}/

# Both users are in the shared group
getent group {app_name}
# Expected: {app_name}:x:NNN:{server_admin_user},{app_runtime_user}
```

### Check SSL certificate

```bash
ssh ubuntu@YOUR_SERVER

# Certificate exists
sudo certbot certificates

# Expiry date
sudo openssl x509 -in /etc/letsencrypt/live/{server_name}/fullchain.pem -noout -dates

# Renewal timer running
sudo systemctl status certbot.timer

# Dry-run renewal
sudo certbot renew --dry-run
```

### Check nginx security headers

```bash
# From your local machine
curl -sI https://{server_name} | grep -iE "x-frame|x-content|x-xss|strict-transport|referrer|permissions|content-security"
```

### Check application is running as unprivileged user

```bash
ssh ubuntu@YOUR_SERVER

# Process should be owned by {app_runtime_user}, not root
ps aux | grep gunicorn
# Expected: {app_runtime_user}    ...  gunicorn...
```

---

## SSL Operations

### Force SSL certificate renewal

```bash
ssh ubuntu@YOUR_SERVER

# Check current expiry
sudo certbot certificates

# Force renewal
sudo certbot renew --force-renewal

# Reload nginx (graceful, no downtime)
sudo systemctl reload nginx
```

### Obtain SSL certificate if it failed during setup

```bash
cd deployment
ansible-playbook playbooks/setup-ssl.yml --vault-password-file ~/.vault_pass
```

---

## Unblock an IP Banned by Fail2Ban (Nginx Rate Limit)

```bash
ssh ubuntu@YOUR_SERVER

# Find banned IPs
sudo fail2ban-client status nginx-limit-req

# Unban a specific IP
sudo fail2ban-client set nginx-limit-req unbanip X.X.X.X
```

---

## Security Maintenance Schedule

### Weekly

- Review nginx error logs: `sudo tail -50 /var/log/nginx/error.log`
- Verify SSL certificate not expiring soon: `sudo certbot certificates`
- Check disk space (logs growing): `df -h`

### Monthly

- Review user accounts: `getent group {app_name}`
- Verify application is running as `{app_runtime_user}`, not root: `ps aux | grep gunicorn`
- Review nginx security headers: `curl -sI https://{server_name}`

### Quarterly

- SSL Labs test: `https://www.ssllabs.com/ssltest/analyze.html?d={server_name}`
- Security headers test: `https://securityheaders.com/?q=https://{server_name}`

---

## Next step

Continue to [Chapter 9: Multi-User Support](MULTI_USER.md).

## See also

- [Chapter 6: Monitoring](MONITORING.md) — CloudWatch dashboards and alarms
