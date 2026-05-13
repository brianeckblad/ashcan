# Application Security Reference

Attack detection, rate limiting, and security middleware.

---

## Overview

Multi-layer security architecture:

1. **Application Security** - IP blocking, attack detection (`app/security.py`)
2. **Nginx** - Rate limiting, path filtering, security headers

**For operational tasks (blocking/unblocking IPs, monitoring):** See [OPERATIONS.md](../guides/OPERATIONS.md)

---

## Security Layers

### Layer 1: Application Security Middleware

**Location:** `app/security.py`

#### Features

**1. IP Blocklist**
- Automatic blocking of malicious IPs
- Configurable block duration (default: 24 hours)
- Persistent storage (survives restarts)
- Manual unblock capability

**2. Attack Pattern Detection**
Automatically blocks requests matching:
- Config file access attempts (`.env`, `.git`, `.aws`, etc.)
- Admin panel probes (`/admin`, `/phpmyadmin`, etc.)
- SQL injection patterns
- Command injection attempts
- Path traversal attempts (`../`)
- Common exploit patterns

**3. Rate Limiting**
- 100 requests per minute per IP
- Automatic temporary blocking (1 hour) on violation
- Tracks all IPs with request timestamps
- Automatic cleanup of old data

**4. Security Headers**
Automatically adds to all responses:
- `X-Frame-Options: SAMEORIGIN` (prevent clickjacking)
- `X-Content-Type-Options: nosniff` (prevent MIME sniffing)
- `X-XSS-Protection: 1; mode=block` (XSS protection)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy` (CSP)
- `Strict-Transport-Security` (HSTS - production only)

**5. Real IP Detection**
Gets actual client IP from:
- `X-Forwarded-For` (reverse proxy)
- `X-Real-IP` (fallback)
- `request.remote_addr` (final fallback)

---

### Layer 2: Nginx

**Location:** Nginx configuration on server

**Provides:**
- HTTPS enforcement (HTTP → HTTPS redirect)
- Security headers (HSTS, X-Frame-Options, etc.)
- Rate limiting at the edge

---

## Attack Pattern Detection

### Patterns Detected

```python
# Config/environment files
/.env
/.git
/.aws
/config.php
/wp-config
/.htaccess
/web.config

# Admin panels
/admin
/phpmyadmin
/mysql
/dbadmin
/wp-admin
/administrator

# Vulnerability scanners
/security.txt
/.DS_Store
/xmlrpc.php
/wp-login.php

# SQL injection
union.*select
concat\(.*\)
0x[0-9a-f]+
--\s
/\*.*\*/

# Command injection
;.*cat\s
\|.*ls\s
&&.*whoami

# Path traversal
\.\./
\.\.\\

# Common exploits
eval\s*\(
exec\s*\(
system\s*\(
passthru
shell_exec
```

---

## Automatic IP Blocking

### When IPs Are Blocked

**1. Attack Attempt (24-hour block):**
```
GET /.env HTTP/1.1
GET /phpmyadmin HTTP/1.1
GET /../etc/passwd HTTP/1.1
POST /admin?id=1' OR '1'='1 HTTP/1.1
```

**2. Rate Limit Exceeded (1-hour block):**
```
> 100 requests in 60 seconds from single IP
```

### Block Storage

**File:** `instance/blocked_ips.json`

```json
{
  "192.168.1.100": 1707436800.0,
  "10.0.0.50": 1707433200.0
}
```

- Persisted to disk
- Survives application restarts
- Automatic expiration cleanup

---

## Monitoring Security Events

### Log Locations

**Application Logs:**
```bash
# Security events logged to main application log
tail -f /var/log/apps/{app_name}/app.log | grep "🚫\|🚨\|⚠️"
```

**Log Examples:**
```
[2026-02-08 10:15:32] 🚨 ATTACK DETECTED from 192.168.1.100: GET /.env (matched pattern: \.env)
[2026-02-08 10:15:32] 🚫 IP BLOCKED: 192.168.1.100 for 24 hours (expires: 2026-02-09 10:15:32)
[2026-02-08 10:20:45] ⚠️  RATE LIMIT EXCEEDED: 10.0.0.50 - 150 req/min
[2026-02-08 10:20:45] 🚫 IP BLOCKED: 10.0.0.50 for 1 hours (expires: 2026-02-08 11:20:45)
[2026-02-08 10:25:10] 🚫 Blocked IP attempted access: 192.168.1.100 - /
```

---

## Admin Security Dashboard

### API Endpoints (Admin Only)

**1. List Blocked IPs**
```
GET /api/admin/security/blocked-ips
```

Response:
```json
{
  "success": true,
  "blocked_ips": [
    {
      "ip": "192.168.1.100",
      "expires": "2026-02-09T10:15:32",
      "expires_in_hours": 23.5
    }
  ],
  "count": 1
}
```

**2. Unblock IP**
```
POST /api/admin/security/unblock-ip
Content-Type: application/json

{
  "ip": "192.168.1.100"
}
```

**3. Check Rate Limit**
```
GET /api/admin/security/rate-limit/192.168.1.100
```

Response:
```json
{
  "success": true,
  "ip": "192.168.1.100",
  "requests_last_minute": 45,
  "is_rate_limited": false,
  "limit": 100
}
```

**4. Security Statistics**
```
GET /api/admin/security/stats
```

Response:
```json
{
  "success": true,
  "stats": {
    "blocked_ips_count": 5,
    "total_requests_tracked": 150,
    "attack_patterns_count": 30
  }
}
```

---

## Configuration

### Rate Limits

**Application Level:**
- 100 requests per minute per IP
- Configurable in `app/security.py`:

```python
# security_middleware() function
if rate_limiter.is_rate_limited(client_ip, max_requests=100, window_seconds=60):
    # Block IP
```


### Block Durations

**Attack Attempts:** 24 hours
```python
ip_blocklist.block_ip(client_ip, duration_hours=24)
```

**Rate Limit Violations:** 1 hour
```python
ip_blocklist.block_ip(client_ip, duration_hours=1)
```

**Modify in:** `app/security.py` in `security_middleware()` function

---

## Manual IP Management

### Via Python Console

```python
from app.security import ip_blocklist

# Block an IP
ip_blocklist.block_ip('192.168.1.100', duration_hours=24)

# Unblock an IP
ip_blocklist.unblock_ip('192.168.1.100')

# List all blocked IPs
blocked = ip_blocklist.get_blocked_ips()
for ip, exp in blocked.items():
    print(f"{ip} expires at {exp}")

# Cleanup expired blocks
ip_blocklist.cleanup_expired()
```

### Via Admin API

See [Admin Security Dashboard](#admin-security-dashboard) section above.

---


## Best Practices

### 1. Monitor Blocked IPs
```bash
# Daily check
curl http://localhost:8000/api/admin/security/blocked-ips
```

### 2. Review Attack Logs
```bash
# Weekly review
grep "ATTACK DETECTED" /var/log/apps/<app_name>/app.log | tail -100
```

### 3. Adjust Rate Limits
If legitimate users are being blocked:
- Increase limit: `max_requests=150`
- Increase window: `window_seconds=120`

### 4. Whitelist Trusted IPs (if needed)
Edit `app/security.py`:

```python
TRUSTED_IPS = {'192.168.1.1', '10.0.0.1'}

def security_middleware():
    client_ip = get_real_ip(request)
    
    # Skip security checks for trusted IPs
    if client_ip in TRUSTED_IPS:
        return
    
    # ...rest of security checks
```

### 5. Custom Attack Patterns
Add to `ATTACK_PATTERNS` in `app/security.py`:

```python
ATTACK_PATTERNS = [
    # Existing patterns...
    r'/your-custom-pattern',
    r'specific-exploit',
]
```

---

## Troubleshooting

### Legitimate User Blocked

**Symptom:** User reports "Access denied" (403)

**Fix:**
```bash
# 1. Check if IP is blocked
curl http://localhost:8000/api/admin/security/rate-limit/USER_IP

# 2. Unblock if legitimate
curl -X POST http://localhost:8000/api/admin/security/unblock-ip \
  -H "Content-Type: application/json" \
  -d '{"ip": "USER_IP"}'
```

### Rate Limit Too Aggressive

**Symptom:** Many legitimate users being rate limited

**Fix:** Edit `app/security.py`:
```python
# Increase limit
if rate_limiter.is_rate_limited(client_ip, max_requests=200, window_seconds=60):
```

### False Positive Attack Detection

**Symptom:** Legitimate URL blocked as attack

**Fix:** Edit `ATTACK_PATTERNS` in `app/security.py` to exclude pattern

---

## Performance Impact

**Minimal overhead:**
- IP lookup: ~0.1ms
- Rate limit check: ~0.2ms
- Attack pattern check: ~0.5ms
- **Total: ~0.8ms per request**

**Memory usage:**
- Blocklist: ~1KB per 10 IPs
- Rate limiter: ~100 bytes per tracked IP
- **Total: ~10MB for 10,000 active IPs**

---

## Security Checklist

### Initial Setup
- [x] Security middleware initialized
- [x] Attack patterns configured
- [x] Rate limits set
- [x] Security headers enabled
- [x] IP blocklist persistent storage configured

### Ongoing
- [ ] Review blocked IPs weekly
- [ ] Check attack logs daily
- [ ] Monitor rate limit effectiveness
- [ ] Update attack patterns as needed
- [ ] Test security with penetration testing

---

## Related Documentation

- **Nginx Configuration:** `deployment/templates/nginx.conf.j2`
- **Security Admin API:** `app/routes/api/admin.py`
- **Security Hardening:** [Chapter 8: Security Hardening](../guides/SECURITY_HARDENING.md)
