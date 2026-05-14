# Chapter 6: Monitoring

CloudWatch dashboards, alarms, and alerting.

---

## Overview

After deployment, your application automatically sends logs to CloudWatch. Now you can create:
- **Alarms** - Automated alerts for problems
- **Dashboards** - Visual monitoring of metrics

---

## Prerequisites

The `{app_name}-deploy` IAM user created by `create-deploy-user.yml` already has `CloudWatchFullAccess`,
which covers creating alarms, dashboards, and querying metrics. No additional policy is needed.

If you are running `setup-monitoring.yml` for the first time, confirm the named profile is active:

```bash
aws sts get-caller-identity --profile {app_name}-deploy
```

---

## Quick Setup (10 minutes)

### Step 1: Create Error Rate Alarm

Alerts you if application is returning 5xx errors (crashes, bugs, etc.)

**Via AWS Console:**

1. Go to [CloudWatch Console](https://console.aws.amazon.com/cloudwatch/)
2. Left sidebar → **Alarms** → **All Alarms**
3. Click **Create alarm**

**Configuration:**

4. **Select metric:**
   - Namespace: `AWS/Logs`
   - Search: `{app_name}` 
   - Metric name: `5xxErrorRate` or filter by "ERROR" in logs

5. **Define threshold:**
   - Statistic: Sum
   - Period: 5 minutes
   - Condition: Greater than or equal
   - Threshold: `5`  (5 errors in 5 minutes)

6. **Configure action:**
   - Click **In alarm** action
   - Select: **SNS notification**
   - Topic: Create new → `{app_name}-alerts`
   - Email: Your email address
   - Click **Create topic**

7. **Name alarm:**
   - `{app_name}-HighErrorRate`
   - Description: "Alert when application returns 5 or more errors in 5 minutes"

8. Click **Create alarm**

9. **Confirm subscription:**
   - Check your email
   - Click confirmation link
   - You'll now get alerts!

### Step 2: Create CPU Alarm

Alerts if server is overloaded (traffic spike or bug causing CPU spike).

1. Go to [CloudWatch Alarms](https://console.aws.amazon.com/cloudwatch/home#alarmsV2:alarmFilter=ALL)
2. Click **Create alarm**

**Configuration:**

3. **Select metric:**
   - Browse metrics
   - EC2 → Per-Instance Metrics
   - Search for your instance (check instance name in AWS Console)
   - Metric: `CPUUtilization`

4. **Define threshold:**
   - Statistic: Average
   - Period: 5 minutes
   - Condition: Greater than
   - Threshold: `80`  (alert if CPU > 80%)

5. **Configure action:**
   - SNS notification
   - Topic: `{app_name}-alerts` (use existing)

6. **Name alarm:**
   - `{app_name}-HighCPU`

7. Click **Create alarm**

### Step 3: Create Storage Alarm

Alerts if disk space is running out (logs filling up, S3 sync issue, etc.).

1. Click **Create alarm**

**Configuration:**

2. **Select metric:**
   - Browse metrics
   - EC2 → Per-Instance Metrics
   - Your instance
   - Metric: `DiskSpaceUtilization` or `RootVolumeSize`

3. **Define threshold:**
   - Statistic: Average
   - Period: 1 hour
   - Condition: Greater than
   - Threshold: `80`  (alert if disk > 80% full)

4. **Configure action:**
   - SNS notification
   - Topic: `{app_name}-alerts`

5. **Name alarm:**
   - `{app_name}-DiskSpaceCritical`

6. Click **Create alarm**

---

## Understanding Metrics Available

**From Application Logs:**
- Error count (5xx errors, exceptions)
- Request rate (requests per minute)
- Response time (slow requests)
- Failed login attempts

**From EC2:**
- CPU usage
- Memory usage
- Disk usage
- Network traffic

**From S3:**
- Put request rate (uploads)
- Get request rate (downloads)
- 4xx errors (permission denied)
- 5xx errors (service errors)

---

## Dashboard Setup (Optional but Recommended)

**Create a visual dashboard to see app health at a glance**

### Create Dashboard

1. Go to [CloudWatch Console](https://console.aws.amazon.com/cloudwatch/)
2. Left sidebar → **Dashboards**
3. Click **Create dashboard**
4. Name: `{app_name}-Health`
5. Click **Create dashboard**

### Add Widgets

**Widget 1: Error Rate**

1. Click **Add widget** → **Line**
2. Metrics:
   - Namespace: `AWS/Logs`
   - Search: `{app_name}` 
   - Select: `5xxErrorRate`
3. Label: "Error Rate"
4. Add widget

**Widget 2: Request Count**

1. Click **Add widget** → **Number**
2. Metrics:
   - Namespace: `CWAgent` or `Custom`
   - Select: Request count metric
3. Label: "Requests/min"
4. Add widget

**Widget 3: CPU Usage**

1. Click **Add widget** → **Line**
2. Metrics:
   - Browse metrics
   - EC2 → Per-Instance Metrics
   - Your instance
   - Select: `CPUUtilization`
3. Label: "CPU %"
4. Add widget

**Widget 4: Active Alarms**

1. Click **Add widget** → **Number**
2. Metrics:
   - Namespace: `AWS/CloudWatch`
   - Metric: `AlarmCount`
3. Label: "Active Alarms"
4. Add widget

5. Click **Save dashboard**

---

## Alarm Best Practices

### What to Monitor

**Critical (create alarms):**
- ✅ High error rate (> 5 errors/5 min)
- ✅ High CPU (> 80%)
- ✅ Disk full (> 80%)
- ✅ Multiple failed logins (potential attack)

**Warning (optional):**
- 📊 Response time too high (> 5 seconds)
- 📊 Request rate unusual (50% increase/decrease)
- 📊 Memory usage trending up

**Nice-to-have:**
- 📈 Successful login count (trending)
- 📈 Cache hit rate
- 📈 Database query time

### Threshold Guidelines

**Error Rate:**
- Development: Alert on > 10 errors/5min
- Production: Alert on > 5 errors/5min
- Critical: > 20 errors/5min = page on-call

**CPU Usage:**
- Normal: 20-40%
- Alert: > 80%
- Critical: > 95%

**Memory Usage:**
- Normal: 40-60%
- Alert: > 85%
- Critical: > 95%

**Disk Usage:**
- Warning: > 70%
- Alert: > 85%
- Critical: > 95%

---

## Responding to Alarms

### High Error Rate

```bash
# SSH to server
ssh ubuntu@$server_host

# Check recent errors
sudo grep ERROR /var/log/apps/{app_name}/app.log | tail -100

# Check error log
sudo tail -100 /var/log/apps/{app_name}/error.log

# Restart app if needed
sudo supervisorctl restart {app_name}

# Monitor in real-time
sudo tail -f /var/log/apps/{app_name}/app.log
```

### High CPU

```bash
# Check what's using CPU
top

# Find the process
ps aux | grep {app_name}

# Check if many requests coming in
sudo netstat -tulpn | grep ESTABLISHED | wc -l

# If runaway process, restart
sudo supervisorctl restart {app_name}
```

### Disk Full

```bash
# Check disk usage
df -h

# Find large files/folders
du -sh /*

# Check old logs
ls -lh /var/log/apps/{app_name}/

# Clean old logs
sudo journalctl --vacuum=30d
sudo find /var/log/apps/{app_name}/ -mtime +30 -delete
```

### Multiple Failed Logins (Attack)

```bash
# Check failed logins
sudo grep "Failed password" /var/log/auth.log | tail -20

# Get IPs of attackers
sudo grep "Failed password" /var/log/auth.log | awk '{print $(NF-3)}' | sort | uniq -c | sort -rn

# Block IP (if you know it's malicious)
sudo ufw deny from ATTACKER_IP

# Check if SSH port is exposed (should be yes, that's normal)
# But consider moving to non-standard port or using fail2ban
```

---

## Advanced: Custom Metrics

Create your own metrics from application logs.

**Example: Track login attempts**

```bash
# In your application code, log logins:
logger -t {app_name} "LOGIN_SUCCESS user=john"
logger -t {app_name} "LOGIN_FAILED user=attacker"

# In CloudWatch, create alarm:
# Metric: Count occurrences of "LOGIN_FAILED"
# If count > 5 in 5 minutes → Alert (brute force attempt)
```

---

## Troubleshooting

### Not Getting Alarm Emails?

```bash
# Check SNS topic subscription
aws sns list-subscriptions --region us-east-2

# Check subscription status
aws sns get-subscription-attributes \
  --subscription-arn arn:aws:sns:... \
  --region us-east-2

# Confirm subscription from email
# (Check spam folder!)
```

### Alarm Never Triggers?

1. Check metric is being sent:
   - Go to CloudWatch → Metrics → Browse metrics
   - Search for your metric name
   - Does it have data points?

2. Check threshold:
   - Is it too high?
   - Example: if you alert on > 100 errors but average is 2, alarm never triggers

3. Check period:
   - 5 minutes is common for logs
   - 1 minute is common for infrastructure

### Wrong Instance Selected?

```bash
# Get instance ID
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values={app_name}-server" \
  --query 'Reservations[0].Instances[0].InstanceId'

# Use this ID in alarm metric selection
```

---


## Next step

Continue to [Chapter 7: Secret Management](SECRET_MANAGEMENT.md).

## See also

- [Chapter 5: Operations](OPERATIONS.md) — daily monitoring tasks
- [Chapter 8: Security Hardening](SECURITY_HARDENING.md) — server lockdown

