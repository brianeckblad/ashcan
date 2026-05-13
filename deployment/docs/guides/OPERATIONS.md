# Chapter 5: Operations

Backups, restarts, scaling, log management, and troubleshooting.

---

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Weekly Maintenance](#weekly-maintenance)
3. [Monthly Tasks](#monthly-tasks)
4. [Updating Application](#updating-application)
5. [Secret Rotation](#secret-rotation)
6. [Deployment Procedures](#deployment-procedures)
7. [Monitoring](#monitoring)
8. [Backup & Recovery](#backup--recovery)
9. [SSL Certificate Renewal](#ssl-certificate-renewal)
10. [Server Decommissioning](#server-decommissioning)
11. [Incident Response](#incident-response)
12. [Cost Management](#cost-management)

---

## Quick Links to Detailed Guides

- [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md)
- [Chapter 8: Security Hardening](SECURITY_HARDENING.md)

---

## AWS CLI Profiles

**Managing Multiple AWS Accounts/Regions**

If you manage multiple AWS accounts (dev/staging/production) or regions, use AWS CLI profiles:

```bash
# Set profile for session
export AWS_PROFILE=myapp-production

# Or use with each command
aws s3 ls --profile myapp-production
aws ec2 describe-instances --profile myapp-production
```

**All AWS commands in this guide can use `--profile NAME` flag.**

**Complete guide:** → Configure AWS CLI with profiles for multiple regions and accounts

---

## Daily Operations

### Daily Operations Checklist

**Morning Check (8:00 AM):**
- [ ] Check application health endpoint
- [ ] Review overnight error logs
- [ ] Verify backup completion
- [ ] Check CloudWatch alarms
- [ ] Review blocked IPs (if any)

**Midday Check (12:00 PM):**
- [ ] Monitor current traffic levels
- [ ] Check response times
- [ ] Review error rate

**Evening Check (6:00 PM):**
- [ ] Review day's metrics summary
- [ ] Check disk space usage
- [ ] Verify all services running

### Check Application Health

```bash
# Quick health check
curl https://yourdomain.com/health

# Expected: HTTP 200
# Response: {"status": "healthy", "version": "1.0.0"}

# Or via script
cd deployment
./scripts/app-deploy.sh status
```

**What to check:**
- ✅ HTTP 200 status code
- ✅ Response time < 500ms
- ✅ JSON response with "healthy" status

**If unhealthy:**
1. Check application logs: `./scripts/app-deploy.sh logs`
2. Check service status: `ssh ubuntu@server "sudo supervisorctl status {app_name}"`
3. Check recent deployments: Review git log
4. Restart if needed: SSH to server and run `sudo supervisorctl restart {app_name}`

### Review Error Logs

```bash
# Via SSH
ssh ubuntu@YOUR_SERVER_IP
sudo tail -f /var/log/apps/{app_name}/error.log

# Via deployment script
cd deployment
./scripts/app-deploy.sh logs --errors

# Check for specific patterns
sudo grep -i "error\|exception\|critical" /var/log/apps/{app_name}/app.log | tail -50

# Count errors by hour
sudo awk '/ERROR/ {print $1, $2}' /var/log/apps/{app_name}/app.log | cut -d: -f1 | uniq -c
```

**Look for:**
- ERROR or CRITICAL level messages
- Repeated warnings (same error multiple times)
- Authentication failures (potential security issue)
- Database connection errors
- S3 upload failures
- Memory errors or warnings

**Action if errors found:**
1. Identify error pattern
2. Check if it's affecting users (monitor metrics)
3. Review recent code changes
4. Create incident ticket if needed
5. Deploy fix or rollback if critical

### Verify Backups

```bash
# Check latest backup timestamp
aws s3 ls s3://your-bucket-name/backups/ --recursive | tail -5

# Verify today's backup exists
aws s3 ls s3://your-bucket-name/backups/$(date +%Y%m%d)/ --human-readable

# Check backup size (should be consistent)
aws s3 ls s3://your-bucket-name/backups/$(date +%Y%m%d)/ --recursive --summarize --human-readable

# Expected output shows files and total size
```

**What to check:**
- ✅ Backup file created today
- ✅ Size is reasonable (compare with yesterday)
- ✅ No backup failures in logs

**If backup missing:**
1. Check cron job: `sudo crontab -l -u ubuntu`
2. Check backup script: `/opt/{app_name}/scripts/backup.sh`
3. Check S3 permissions
4. Run manual backup: `./scripts/backup-now.sh`

### Check CloudWatch Alarms

```bash
# List active alarms
aws cloudwatch describe-alarms --state-value ALARM

# Get alarm history
aws cloudwatch describe-alarm-history --alarm-name HighErrorRate --max-records 10

# Check specific alarm
aws cloudwatch describe-alarms --alarm-names HighErrorRate HighCPU DiskSpaceCritical
```

**Via AWS Console:**
1. Go to: AWS Console → CloudWatch → Alarms
2. Check for any alarms in "In alarm" state
3. Click alarm for details and history

**If alarms are firing:**
- **HighErrorRate** → Check error logs, recent deployments
- **HighCPU** → Check for traffic spike, runaway process
- **HighMemory** → Check for memory leak, restart application
- **DiskSpaceCritical** → Clean up old logs, snapshots

### Monitor Dashboard

#### Via AWS Console

1. Go to: AWS Console → CloudWatch → Dashboards
2. Select: `app-item-listing-tool`
3. Review panels:
   - Request rate
   - Error rate
   - Response time
   - CPU/Memory usage
   - Cache hit rate

#### Via CLI

```bash
# Get dashboard definition
aws cloudwatch get-dashboard --dashboard-name {app_name}

# Export metrics for last hour
for metric in CPUUtilization MemoryUtilization; do
  echo "=== $metric ==="
  aws cloudwatch get-metric-statistics \
    --namespace CWAgent \
    --metric-name $metric \
    --dimensions Name=InstanceId,Value=$instance_id \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Average
done
```

**What to look for:**
- Error rate < 1%
- Response time < 500ms (p95)
- No unusual traffic spikes
- Cache hit rate > 80%
- CPU < 70% average
- Memory stable (no growth trend)

### Check Traffic Patterns

```bash
# Request count per hour (Nginx logs)
sudo awk '{print $4}' /var/log/apps/{app_name}/nginx_access.log | cut -d: -f2 | sort | uniq -c

# Top requesting IPs
sudo awk '{print $1}' /var/log/apps/{app_name}/nginx_access.log | sort | uniq -c | sort -rn | head -10

# Top requested URLs
sudo awk '{print $7}' /var/log/apps/{app_name}/nginx_access.log | sort | uniq -c | sort -rn | head -10

# Response codes distribution
sudo awk '{print $9}' /var/log/apps/{app_name}/nginx_access.log | sort | uniq -c
```

**Normal patterns:**
- Gradual traffic increase during business hours
- Mix of URLs (not one URL dominating)
- Mostly 200 responses
- Some 304 (cache) responses

**Abnormal patterns (investigate):**
- Sudden traffic spike from single IP (potential attack)
- High rate of 404 errors (broken links or scanning)
- Many 500 errors (application issue)
- One URL getting hammered (potential issue or bot)

### Review Blocked IPs

```bash
# Via application API (if available)
curl http://localhost:8000/api/admin/security/blocked-ips

# Or check file directly
ssh ubuntu@server "cat /opt/{app_name}/instance/blocked_ips.json"

# Count blocked IPs
ssh ubuntu@server "cat /opt/{app_name}/instance/blocked_ips.json" | jq '. | length'

# Check recent blocks in logs
sudo grep "IP BLOCKED" /var/log/apps/{app_name}/app.log | tail -20
```

**Action if many blocked IPs:**
- Review patterns (same subnet? same attack signature?)
- Check if legitimate users affected (unblock if needed)
- Document attack pattern

### System Resource Check

```bash
# Connect to server
ssh ubuntu@YOUR_SERVER_IP

# Disk usage
df -h

# Memory usage
free -h

# CPU load
uptime

# Top processes
top -b -n 1 | head -20

# Application process status
ps aux | grep gunicorn

# Check for zombie processes
ps aux | grep defunct
```

**Normal values:**
- Disk usage < 80%
- Memory usage < 80%
- Load average < number of CPUs
- Gunicorn workers running (4 workers typical)

**If resources high:**
- Disk > 85%: Clean up logs, old backups
- Memory > 85%: Check for leaks, restart app
- CPU > 80%: Check for runaway process, traffic spike
- Many zombies: Restart supervisor

---

## Weekly Maintenance


### Verify Backups

```bash
# List recent backups
aws s3 ls s3://your-bucket-name/backups/ --recursive | tail -20

# Check backup size
aws s3 ls s3://your-bucket-name/backups/$(date +%Y%m%d)/ --recursive --human-readable --summarize
```

**Expected:**
- Daily backups present
- Reasonable file sizes
- No errors in backup logs

### Check Disk Space

```bash
ssh ubuntu@YOUR_SERVER_IP

# Check disk usage
df -h

# Check largest directories
sudo du -h --max-depth=1 /opt/{app_name}/ | sort -h

# Check log sizes
sudo du -sh /var/log/apps/{app_name}/
```

**Actions:**
- If > 80% full: Clean old logs
- If > 90% full: Urgent cleanup or resize disk

### Review CloudWatch Alarms

```bash
# List alarm states
aws cloudwatch describe-alarms \
  --query 'MetricAlarms[?starts_with(AlarmName, `app-item-listing-tool`)].{Name:AlarmName,State:StateValue}' \
  --output table
```

**Actions:**
- Investigate any alarms in ALARM state
- Review alarm history for patterns
- Update thresholds if needed

---

## Monthly Tasks

### Update Application Dependencies

```bash
# Review and update requirements.txt
git pull
cd deployment
./scripts/app-deploy.sh update
```

**Process:**
1. Review dependency updates
2. Test in staging/local first
3. Deploy to production
4. Monitor for issues

### Review AWS Costs

```bash
# Get current month costs
aws ce get-cost-and-usage \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=SERVICE

# Or via console
# AWS Console → Billing → Cost Explorer
```

**Actions:**
- Compare to previous months
- Identify unusual spikes
- Optimize if over budget

### Security Group Review

```bash
# List security group rules
aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=app-item-listing-tool-sg" \
  --query 'SecurityGroups[0].IpPermissions' \
  --output table
```

**Review:**
- All rules still needed?
- Any overly permissive rules?
- Document any changes

### SSL Certificate Check

```bash
# Check certificate expiry
echo | openssl s_client -servername yourdomain.com -connect yourdomain.com:443 2>/dev/null | openssl x509 -noout -dates

# Check certificate details
echo | openssl s_client -servername yourdomain.com -connect yourdomain.com:443 2>/dev/null | openssl x509 -noout -subject -issuer -dates
```

**Actions:**
- If < 30 days: Renew certificate (see SSL Certificate Rotation below)
- Update calendar reminders

### SSL/TLS Certificate Rotation

**Frequency:** Automatic (Let's Encrypt renews at 60 days remaining)  
**Manual Check:** Monthly

#### Check Certificate Status

```bash
# Connect to server
ssh ubuntu@YOUR_SERVER_IP

# Check certbot status
sudo certbot certificates

# View renewal configuration
sudo cat /etc/letsencrypt/renewal/yourdomain.com.conf
```

**Expected Output:**
```
Certificate Name: yourdomain.com
  Domains: yourdomain.com www.yourdomain.com
  Expiry Date: 2026-05-10 12:34:56+00:00 (VALID: 60 days)
  Certificate Path: /etc/letsencrypt/live/yourdomain.com/fullchain.pem
  Private Key Path: /etc/letsencrypt/live/yourdomain.com/privkey.pem
```

#### Manual Certificate Renewal

If automatic renewal fails or you need to renew early:

```bash
# Connect to server
ssh ubuntu@YOUR_SERVER_IP

# Stop nginx (required for standalone renewal)
sudo systemctl stop nginx

# Renew certificate
sudo certbot renew --force-renewal

# Or for specific domain
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Restart nginx
sudo systemctl start nginx

# Verify certificate
curl -vI https://yourdomain.com 2>&1 | grep -i "expire date"
```

#### Troubleshooting Certificate Renewal

**Issue: Renewal fails with "Address already in use"**
```bash
# Check what's using port 80
sudo netstat -tulpn | grep :80

# Stop nginx temporarily
sudo systemctl stop nginx

# Retry renewal
sudo certbot renew

# Restart nginx
sudo systemctl start nginx
```

**Issue: DNS validation fails**
```bash
# Verify DNS is pointing to your server
dig yourdomain.com +short

# Check if it matches your server IP
curl ifconfig.me

# If different, update DNS records and wait for propagation (up to 48 hours)
```

**Issue: Certificate expired**
```bash
# Emergency renewal
sudo certbot certonly --standalone -d yourdomain.com --force-renewal

# Update nginx immediately
sudo systemctl reload nginx

# Verify
curl https://yourdomain.com
```

#### Test Auto-Renewal

```bash
# Dry run (test renewal without actually renewing)
sudo certbot renew --dry-run
```

**Expected:** "The dry run was successful"

#### Configure Auto-Renewal (if not already set up)

```bash
# Check certbot timer
sudo systemctl status certbot.timer

# Enable if not running
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# View renewal schedule
sudo systemctl list-timers | grep certbot
```

#### Post-Renewal Actions

Certbot automatically reloads nginx after renewal. Verify:

```bash
# Check nginx reload hook
sudo cat /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
```

Should contain:
```bash
#!/bin/bash
systemctl reload nginx
```

If missing, create it:
```bash
sudo nano /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
# Add: systemctl reload nginx
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh
```

#### Certificate Monitoring

Set up monitoring alert:

```bash
# Add to CloudWatch or monitoring system
# Alert if cert expires in < 14 days

# Manual check (add to cron)
echo "0 6 * * * /usr/bin/certbot certificates | grep 'VALID: [0-9] days' && echo 'Certificate expiring soon!' | mail -s 'SSL Alert' admin@example.com" | sudo crontab -
```

### Update System Packages

```bash
ssh ubuntu@YOUR_SERVER_IP

# Update packages
sudo apt-get update
sudo apt-get upgrade -y

# Restart if kernel updated
sudo reboot
```

**Timing:** During low-traffic hours

---

## Secret Rotation

### Quarterly Rotation Schedule

**Rotate every 90 days:**
- eBay production token
- Admin passwords
- Application secret keys
- GitHub tokens

### Zero-Downtime Rotation Process

#### Step 1: Prepare New Secret

```bash
# Edit encrypted vault
cd deployment
ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass
```

Add new secret with `_new` suffix:
```yaml
# Example: Rotating eBay token
ebay_production_token: "v^1.1#i^1#...old-token..."
vault_ebay_production_token_new: "v^1.1#i^1#...NEW-TOKEN-HERE..."  # Add this
```

Save and commit (encrypted vault is safe):
```bash
git add group_vars/vault.yml
git commit -m "Prepare eBay token rotation"
git push
```

#### Step 2: Create AWSPENDING Version

```bash
# Create new version in AWS (doesn't affect production yet)
ansible-playbook playbooks/secret-rotate.yml -e secret_key=ebay_production_token
```

**What happens:**
- Extracts `_new` value from vault
- Creates AWSPENDING version in Secrets Manager
- Production still uses AWSCURRENT (old token)

#### Step 3: Test New Secret

```bash
# Application can fetch AWSPENDING for testing
# Test your eBay integration
curl https://yourdomain.com/api/ebay/test

# Or manual test
ssh ubuntu@YOUR_SERVER_IP
# Test eBay API calls with new token
```

#### Step 4: Promote to Production

If tests successful:
```bash
ansible-playbook playbooks/secret-promote.yml -e secret_key=ebay_production_token
```

**What happens:**
- AWSPENDING becomes AWSCURRENT
- Old version becomes AWSPREVIOUS
- Production now uses new token
- **Zero downtime** - instant switchover

#### Step 5: Clean Up Vault

```bash
ansible-vault edit group_vars/vault.yml --vault-password-file ~/.vault_pass
```

Update vault:
```yaml
# Remove _new suffix, update main value
ebay_production_token: "v^1.1#i^1#...NEW-TOKEN-HERE..."  # Updated
# Remove: vault_ebay_production_token_new line
```

Commit:
```bash
git add group_vars/vault.yml
git commit -m "Complete eBay token rotation"
git push
```

### Rotation Verification

```bash
# Verify new secret is active
aws secretsmanager describe-secret --secret-id app-item-listing-tool/production

# Check application logs
./scripts/app-deploy.sh logs | grep -i "secret\|token"

# Test functionality
curl https://yourdomain.com/api/ebay/categories
```

### Rollback Procedure

If new secret doesn't work:

```bash
# Get previous version ID from rotation info
cat deployment/.secret-rotation-info

# Rollback in AWS
aws secretsmanager update-secret-version-stage \
  --secret-id app-item-listing-tool/production \
  --version-stage AWSCURRENT \
  --move-to-version-id <old-version-id>

# Restart application
./scripts/app-deploy.sh restart
```

---

## Deployment Procedures

### Standard Deployment (Code Updates)

```bash
# 1. Make changes locally
git add .
git commit -m "Description of changes"

# 2. Push to GitHub
git push origin main

# 3. Deploy to production
cd deployment
./scripts/app-deploy.sh update

# 4. Monitor logs
./scripts/app-deploy.sh logs

# 5. Verify
curl https://yourdomain.com/health
```

**Duration:** 2-3 minutes  
**Downtime:** None (graceful reload)

### Hotfix Deployment

```bash
# 1. Create hotfix branch
git checkout -b hotfix/critical-bug
# Make fix
git commit -m "Fix critical bug"

# 2. Deploy directly
cd deployment
./scripts/app-deploy.sh update

# 3. Merge back to main
git checkout main
git merge hotfix/critical-bug
git push
```

### Rollback to Previous Version

```bash
# 1. Find commit hash to rollback to
git log --oneline -10

# 2. Rollback
cd deployment
./scripts/app-deploy.sh rollback <commit-hash>

# 3. Verify
curl https://yourdomain.com/health
```

### Database Migrations

```bash
# 1. Connect to server
ssh ubuntu@YOUR_SERVER_IP

# 2. Backup database
cd /opt/{app_name}
python -c "from app import backup; backup.create_backup()"

# 3. Run migrations
flask db upgrade

# 4. Verify
flask db current

# 5. Restart application
sudo supervisorctl restart {app_name}
```

---

## Monitoring

### CloudWatch Metrics to Watch

**Application Metrics:**
- Request count
- Error rate
- Response time
- 4xx/5xx errors

**Infrastructure Metrics:**
- EC2 CPU utilization
- Memory usage
- Disk space
- Network I/O


---

## Log Management

### Application Logs (On Server)

#### Location and Structure

```bash
# Log directory (configurable via app_name)
/var/log/apps/<app_name>/

# Example structure:
/var/log/apps/{app_name}/
├── app.log              # Application logs (Python/Flask)
├── error.log            # Error logs (critical issues)
├── access.log           # Gunicorn access logs
├── nginx_access.log     # Nginx access logs
└── nginx_error.log      # Nginx error logs
```

#### View Application Logs

```bash
# Real-time tail
sudo tail -f /var/log/apps/{app_name}/app.log

# Last 100 lines
sudo tail -n 100 /var/log/apps/{app_name}/app.log

# Error logs only
sudo tail -f /var/log/apps/{app_name}/error.log

# Search for specific error
sudo grep "ERROR" /var/log/apps/{app_name}/app.log | tail -20

# Search by timestamp
sudo grep "2026-02-09 14:" /var/log/apps/{app_name}/app.log
```

#### View Access Logs

```bash
# Nginx access logs
sudo tail -f /var/log/apps/{app_name}/nginx_access.log

# Gunicorn access logs
sudo tail -f /var/log/apps/{app_name}/access.log

# Count requests per hour
sudo awk '{print $4}' /var/log/apps/{app_name}/nginx_access.log | cut -d: -f1-2 | sort | uniq -c

# Top requesting IPs
sudo awk '{print $1}' /var/log/apps/{app_name}/nginx_access.log | sort | uniq -c | sort -rn | head -20

# 404 errors
sudo grep " 404 " /var/log/apps/{app_name}/nginx_access.log | tail -20

# 500 errors
sudo grep " 500 " /var/log/apps/{app_name}/nginx_access.log | tail -20
```

#### Log Analysis Commands

```bash
# Errors in last hour
sudo find /var/log/apps/{app_name} -name "*.log" -mmin -60 -exec grep -H "ERROR" {} \;

# Count errors by type
sudo grep ERROR /var/log/apps/{app_name}/app.log | awk '{print $5}' | sort | uniq -c | sort -rn

# Find slow requests (> 5 seconds)
sudo awk '$NF > 5 {print $0}' /var/log/apps/{app_name}/access.log

# Memory errors
sudo grep -i "memory\|out of memory\|oom" /var/log/apps/{app_name}/*.log

# Database errors
sudo grep -i "database\|sql\|connection" /var/log/apps/{app_name}/error.log | tail -20
```

#### Log Rotation

```bash
# Check logrotate configuration
sudo cat /etc/logrotate.d/{app_name}

# Manual rotation (if needed)
sudo logrotate -f /etc/logrotate.d/{app_name}

# Verify rotation is working
ls -lh /var/log/apps/{app_name}/*.gz

# View rotated logs
sudo zcat /var/log/apps/{app_name}/app.log.1.gz | tail -100
```

**Logrotate Config:**
```
/var/log/apps/{app_name}/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 ubuntu ubuntu
    sharedscripts
    postrotate
        systemctl reload {app_name} > /dev/null
    endscript
}
```

### AWS CloudWatch Logs

#### View Logs via AWS Console

1. Go to: AWS Console → CloudWatch → Log groups
2. Find: `/aws/ec2/<app_name>` or `/aws/lambda/<function_name>`
3. Click on log streams to view

#### View Logs via AWS CLI

```bash
# List log groups
aws logs describe-log-groups --query 'logGroups[*].logGroupName' --output table

# List log streams in a group
aws logs describe-log-streams \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --order-by LastEventTime \
  --descending \
  --max-items 10

# View recent logs (last hour)
aws logs filter-log-events \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --start-time $(date -d '1 hour ago' +%s)000 \
  --limit 100

# Search for errors
aws logs filter-log-events \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --filter-pattern "ERROR" \
  --start-time $(date -d '24 hours ago' +%s)000

# Tail logs in real-time
aws logs tail /aws/ec2/app-item-listing-tool --follow

# Search by specific string
aws logs filter-log-events \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --filter-pattern "database connection" \
  --start-time $(date -d '7 days ago' +%s)000
```

#### Export CloudWatch Logs

```bash
# Export to S3 for long-term storage
aws logs create-export-task \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --from $(date -d '30 days ago' +%s)000 \
  --to $(date +%s)000 \
  --destination my-logs-bucket \
  --destination-prefix cloudwatch-exports/

# Check export task status
aws logs describe-export-tasks --task-id <task-id>
```

#### CloudWatch Insights Queries

```bash
# Run insights query via CLI
aws logs start-query \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --start-time $(date -d '1 hour ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20'
```

**Common Insights Queries (run in AWS Console):**

```
# Top 20 errors
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() by @message
| sort count desc
| limit 20

# Request latency percentiles
fields @timestamp, responseTime
| stats avg(responseTime), percentile(responseTime, 50), percentile(responseTime, 95), percentile(responseTime, 99)

# Error rate over time
fields @timestamp, @message
| filter @message like /ERROR/
| stats count() as errors by bin(5m)

# Failed authentication attempts
fields @timestamp, ip, username
| filter @message like /authentication failed/
| stats count() by ip
| sort count desc
```

### CloudTrail Logs (AWS API Activity)

#### View CloudTrail Events

```bash
# Recent events
aws cloudtrail lookup-events --max-results 50

# Events by specific user
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=Username,AttributeValue=admin

# Events for specific resource
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=i-xxxxxxxxxxxxx

# Events in last 7 days
aws cloudtrail lookup-events \
  --start-time $(date -d '7 days ago' --iso-8601) \
  --max-results 100
```

#### Monitor Security Events

```bash
# Failed console logins
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=ConsoleLogin \
  | jq '.Events[] | select(.CloudTrailEvent | contains("Failure"))'

# IAM changes
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateUser

# Security group changes
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AuthorizeSecurityGroupIngress
```

### VPC Flow Logs

#### Enable Flow Logs (if not already enabled)

```bash
# Create flow log to CloudWatch
aws ec2 create-flow-logs \
  --resource-type VPC \
  --resource-ids vpc-xxxxxxxxxxxxx \
  --traffic-type ALL \
  --log-destination-type cloud-watch-logs \
  --log-group-name /aws/vpc/flowlogs
```

#### Analyze Traffic

```bash
# View flow logs
aws logs filter-log-events \
  --log-group-name /aws/vpc/flowlogs \
  --start-time $(date -d '1 hour ago' +%s)000

# Find connections to specific IP
aws logs filter-log-events \
  --log-group-name /aws/vpc/flowlogs \
  --filter-pattern "192.168.1.100"

# Find rejected connections
aws logs filter-log-events \
  --log-group-name /aws/vpc/flowlogs \
  --filter-pattern "REJECT"
```

---

## AWS Operations Reference

### EC2 Instance Management

#### Connect to Instance

```bash
# Via SSM Session Manager (no SSH key needed)
ssh ubuntu@YOUR_SERVER_IP

# Via SSH (if port 22 is open)
ssh -i ~/.ssh/app-key.pem ubuntu@<instance-ip>
```

#### Check Instance Status

```bash
# Instance status
aws ec2 describe-instance-status --instance-ids i-xxxxxxxxxxxxx

# Instance details
aws ec2 describe-instances --instance-ids i-xxxxxxxxxxxxx

# System logs
aws ec2 get-console-output --instance-id i-xxxxxxxxxxxxx --latest
```

#### Start/Stop/Reboot Instance

```bash
# Stop instance
aws ec2 stop-instances --instance-ids i-xxxxxxxxxxxxx

# Start instance
aws ec2 start-instances --instance-ids i-xxxxxxxxxxxxx

# Reboot instance
aws ec2 reboot-instances --instance-ids i-xxxxxxxxxxxxx

# Wait for instance to be ready
aws ec2 wait instance-running --instance-ids i-xxxxxxxxxxxxx
aws ec2 wait instance-status-ok --instance-ids i-xxxxxxxxxxxxx
```

#### Monitor Instance Metrics

```bash
# CPU utilization (last hour)
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-xxxxxxxxxxxxx \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average

# Network in/out
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name NetworkIn \
  --dimensions Name=InstanceId,Value=i-xxxxxxxxxxxxx \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

### S3 Operations

#### List and Inspect Bucket

```bash
# List buckets
aws s3 ls

# List objects in bucket
aws s3 ls s3://your-bucket-name/ --recursive

# Get bucket size
aws s3 ls s3://your-bucket-name/ --recursive --summarize --human-readable

# Count objects
aws s3 ls s3://your-bucket-name/ --recursive | wc -l
```

#### Download/Upload Files

```bash
# Download file
aws s3 cp s3://your-bucket-name/path/to/file.jpg ./local-file.jpg

# Upload file
aws s3 cp ./local-file.jpg s3://your-bucket-name/path/to/file.jpg

# Sync directory
aws s3 sync ./local-dir/ s3://your-bucket-name/remote-dir/

# Sync with delete
aws s3 sync ./local-dir/ s3://your-bucket-name/remote-dir/ --delete
```

#### Check Bucket Metrics

```bash
# Number of objects
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name NumberOfObjects \
  --dimensions Name=BucketName,Value=your-bucket-name Name=StorageType,Value=AllStorageTypes \
  --start-time $(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Average

# Bucket size
aws cloudwatch get-metric-statistics \
  --namespace AWS/S3 \
  --metric-name BucketSizeBytes \
  --dimensions Name=BucketName,Value=your-bucket-name Name=StorageType,Value=StandardStorage \
  --start-time $(date -u -d '1 day ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Average
```


### Secrets Manager Operations

#### View Secrets

```bash
# List secrets
aws secretsmanager list-secrets

# Get secret value
aws secretsmanager get-secret-value --secret-id app-item-listing-tool/production

# Get specific key from secret
aws secretsmanager get-secret-value \
  --secret-id app-item-listing-tool/production \
  --query 'SecretString' \
  --output text | jq -r '.EBAY_PRODUCTION_APP_ID'
```

#### Update Secret

```bash
# Update entire secret
aws secretsmanager put-secret-value \
  --secret-id app-item-listing-tool/production \
  --secret-string file://secrets.json

# Check secret versions
aws secretsmanager describe-secret --secret-id app-item-listing-tool/production
```


### Setting Up Alerts

```bash
# Create alerts for your email
./scripts/cloudwatch-alarms-setup.sh your-email@example.com
```

**Alarms created:**
- High error rate (>5% for 10 minutes)
- High request rate (>10,000/minute)
- EC2 CPU high (>80% for 15 minutes)
- Disk space critical (>85%)

### Log Analysis

```bash
# Error patterns in last hour
aws logs filter-log-events \
  --log-group-name /aws/ec2/app-item-listing-tool \
  --start-time $(date -d '1 hour ago' +%s)000 \
  --filter-pattern "ERROR"

# Count errors by type
sudo grep ERROR /var/log/apps/{app_name}/error.log | \
  awk '{print $5}' | sort | uniq -c | sort -rn
```

### Performance Monitoring

```bash
# Check response times
curl -w "@curl-format.txt" -o /dev/null -s https://yourdomain.com

# curl-format.txt:
time_namelookup:  %{time_namelookup}\n
time_connect:     %{time_connect}\n
time_starttransfer: %{time_starttransfer}\n
time_total:       %{time_total}\n
```

---

## Backup & Recovery

### Automated Backup Schedule

- **Instance snapshots:** Daily at 2:00 AM UTC
- **S3 sync:** Every 15 minutes (cron job)
- **Database exports:** Daily at 3:00 AM UTC
- **Retention:** 7 daily, 4 weekly, 12 monthly

### Manual Backup

```bash
# Full backup
ssh ubuntu@YOUR_SERVER_IP
sudo /opt/app-scripts/backup-all.sh

# Verify backup in S3
aws s3 ls s3://your-bucket-name/backups/$(date +%Y%m%d)/
```

### Restore from Backup

```bash
# 1. List available backups
aws s3 ls s3://your-bucket-name/backups/ --recursive | grep $(date +%Y%m)

# 2. Download backup
aws s3 sync \
  s3://your-bucket-name/backups/20260208/ \
  /tmp/restore/

# 3. Stop application
ssh ubuntu@YOUR_SERVER_IP
sudo supervisorctl stop {app_name}

# 4. Restore files
sudo cp -r /tmp/restore/* /opt/{app_name}/instance/

# 5. Restart application
sudo supervisorctl start {app_name}

# 6. Verify
curl https://yourdomain.com/health
```

### Disaster Recovery

**Recovery Time Objective (RTO):** 1-2 hours  
**Recovery Point Objective (RPO):** 15 minutes

**DR Steps:**
1. Launch new EC2 from latest snapshot
2. Restore application files from S3
3. Update DNS to new instance
4. Verify functionality

**Test DR:** Quarterly

---

## Incident Response

### Severity Levels

**P0 - Critical**
- Application completely down
- Data loss
- Security breach
- **Response time:** Immediate

**P1 - High**
- Partial outage
- Significant performance degradation
- **Response time:** 1 hour

**P2 - Medium**
- Minor functionality issues
- Non-critical bugs
- **Response time:** 4 hours

**P3 - Low**
- Cosmetic issues
- Feature requests
- **Response time:** Next business day

### Incident Response Checklist

#### Immediate Actions

- [ ] Assess severity
- [ ] Check monitoring dashboard
- [ ] Review recent changes
- [ ] Check CloudWatch logs
- [ ] Check application security blocked IPs

#### Investigation

- [ ] Identify root cause
- [ ] Document timeline
- [ ] Collect logs
- [ ] Take screenshots

#### Resolution

- [ ] Implement fix or rollback
- [ ] Verify resolution
- [ ] Monitor for recurrence
- [ ] Update documentation

#### Post-Mortem

- [ ] Write incident report
- [ ] Identify prevention measures
- [ ] Update runbooks
- [ ] Schedule review meeting

### Common Incidents

**Application Not Responding:**
```bash
# Check EC2 status
aws ec2 describe-instance-status --instance-ids i-xxxxxxxxxxxxx

# Restart application
./scripts/app-deploy.sh restart

# If no response, reboot instance
aws ec2 reboot-instances --instance-ids i-xxxxxxxxxxxxx
```

**High Error Rate:**
```bash
# Check logs
./scripts/app-deploy.sh logs | grep ERROR

# Review recent deployments
git log --oneline -5

# Rollback if needed
./scripts/app-deploy.sh rollback <commit-hash>
```

**DDoS Attack:**
```bash
# Check application-level rate limiting blocks
curl http://localhost:{app_port}/api/admin/security/blocked-ips

# Rate limits will automatically protect; manually block persistent attackers
curl -X POST http://localhost:{app_port}/api/admin/security/block-ip \
  -H "Content-Type: application/json" \
  -d '{"ip": "1.2.3.4", "duration_hours": 24}'
```

---

## Cost Management

### Monthly Cost Review

```bash
# Current month costs by service
aws ce get-cost-and-usage \
  --time-period Start=$(date +%Y-%m-01),End=$(date +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=SERVICE
```

### Cost Optimization Tips

**EC2:**
- Use reserved instances (50% savings)
- Use a smaller instance type if sufficient
- Stop instances during non-business hours (if acceptable)


**S3:**
- Use lifecycle policies
- Enable S3 Intelligent-Tiering
- Clean up old backups


### Budget Alerts

```bash
# Set budget alert at $30/month
aws budgets create-budget \
  --account-id <account-id> \
  --budget file://budget.json

# budget.json:
{
  "BudgetName": "app-item-listing-tool-budget",
  "BudgetLimit": {
    "Amount": "30",
    "Unit": "USD"
  },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
```

---

## Security Operations

### Monitor Blocked IPs

```bash
# Check blocked IPs via admin API
curl http://localhost:8000/api/admin/security/blocked-ips

# Or check logs
sudo grep "IP BLOCKED" /var/log/apps/{app_name}/app.log | tail -20
```

### Unblock an IP (if legitimate user)

```bash
# Via API
curl -X POST http://localhost:8000/api/admin/security/unblock-ip \
  -H "Content-Type: application/json" \
  -d '{"ip": "192.168.1.100"}'

# Or edit blocklist file directly
sudo nano /opt/{app_name}/instance/blocked_ips.json
# Remove the IP, save, restart app
./scripts/app-deploy.sh restart
```

### Check Rate Limiting

```bash
# Check specific IP
curl http://localhost:8000/api/admin/security/rate-limit/192.168.1.100

# Review rate-limited IPs in logs
sudo grep "RATE LIMIT EXCEEDED" /var/log/apps/{app_name}/app.log | tail -20
```

### Review Security Events

```bash
# All security events
sudo grep -E "🚨|🚫|⚠️" /var/log/apps/{app_name}/app.log | tail -50

# Attack attempts
sudo grep "ATTACK DETECTED" /var/log/apps/{app_name}/app.log | tail -20

# By IP
sudo grep "192.168.1.100" /var/log/apps/{app_name}/app.log | grep -E "BLOCKED|ATTACK"
```

**Note:** Application security (IP blocking, attack detection) runs automatically. See `app/security.py` for implementation details.

---

## Runbook Quick Reference

### Restart Application

```bash
./scripts/app-deploy.sh restart
```


### Scale Up Instance

```bash
# Stop instance
aws ec2 stop-instances --instance-ids i-xxxxxxxxxxxxx

# Change instance type
aws ec2 modify-instance-attribute \
  --instance-id i-xxxxxxxxxxxxx \
  --instance-type "{\"Value\": \"t3.small\"}"

# Start instance
aws ec2 start-instances --instance-ids i-xxxxxxxxxxxxx
```

### Emergency Contact

- **On-Call Engineer:** [Phone/Email]
- **AWS Support:** [Support Plan Details]
- **Escalation Path:** [Management Contact]

---

## Updating Application

**For deploying code changes, see:** → [UPDATING_APPLICATION.md](UPDATING_APPLICATION.md)

Quick reference:

```bash
cd deployment

# Deploy latest code from Git
ansible-playbook -i inventories playbooks/update.yml
```

---

## SSL Certificate Renewal

**Let's Encrypt certificates expire after 90 days**

### Check Certificate Expiry

```bash
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# Check when certificate expires
sudo certbot certificates

# Expected output shows expiration date

# If less than 30 days away, renew
exit
```

### Automatic Renewal (Recommended)

Deployed by default, runs automatically:

```bash
# Verify it's configured
sudo systemctl list-timers | grep certbot

# Should show certbot-renew timer (runs daily)

# Manual test (don't use on production frequently)
sudo certbot renew --dry-run
```

### Manual Renewal

```bash
ssh -i ~/.ssh/{app_name}-key.pem ubuntu@YOUR_SERVER_IP

# Renew certificate
sudo certbot renew

# If that fails
sudo certbot renew --force-renewal

# Restart Nginx to load new cert
sudo systemctl restart nginx

# Verify
curl https://your-domain.com
# Should show no certificate warnings

exit
```

---

## Server Decommissioning

**Safely remove server and clean up resources**

### Before Decommissioning

```
Checklist:
  [ ] Backup all data
  [ ] Export database
  [ ] Save logs (archive old logs)
  [ ] Document configuration
  [ ] Notify users
  [ ] Plan maintenance window
  [ ] Test recovery on new server
```

### Backup Everything

```bash
# Download application files
scp -r -i ~/.ssh/${app_name}-key.pem \
  ubuntu@YOUR_SERVER_IP:/opt/${app_name} \
  ./backup-${app_name}-$(date +%Y%m%d)/

# Backup logs
scp -r -i ~/.ssh/${app_name}-key.pem \
  ubuntu@YOUR_SERVER_IP:/var/log/apps/${app_name} \
  ./backup-logs-$(date +%Y%m%d)/

# Backup instance data (CSV, preferences, uploads)
scp -r -i ~/.ssh/${app_name}-key.pem \
  ubuntu@YOUR_SERVER_IP:/opt/${app_name}/instance \
  ./backup-config-$(date +%Y%m%d)/
```

### Delete AWS Resources

Once backups are confirmed, follow the teardown guide:

→ [Chapter 13: Decommission](DECOMMISSION.md) — full teardown with dependency order

---

## Next step

Continue to [Chapter 6: Monitoring](MONITORING.md).

## See also

- [Chapter 4: Updating Your Application](UPDATING_APPLICATION.md) — deploy code changes
- [Chapter 7: Secret Management](SECRET_MANAGEMENT.md) — rotate credentials
