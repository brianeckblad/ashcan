# User Model Reference

Two-user security model for deployment and runtime operations.

---

## User Roles

### 1. Admin User (`admin_user`)

**Default:** `ubuntu`

**Purpose:** Deployment, administration, and system management

**Capabilities:**
- SSH access to the server ✅
- Shell access (`/bin/bash`) ✅
- sudo privileges (for ansible) ✅
- Git operations ✅
- Python virtual environment management ✅
- Code ownership and maintenance ✅

**Usage in Deployment:**
- Ansible connects as this user
- All deployment tasks run as this user
- Managing code, dependencies, and system configuration

**Security Notes:**
- This is the traditional admin/deployment user
- Should only be accessible via SSH keys
- Standard Ubuntu AMI default user
- Full server management access (appropriate for deployment)

---

### 2. Application User (`app_user`)

**Default:** `{app_name}` (configured as `app_user` variable in vault.yml)

**Purpose:** Runtime application execution (principle of least privilege)

**Capabilities:**
- Runs the Gunicorn application process ✅
- Reads application code ✅
- Writes to logs (`/var/log/apps/{app_name}/`) ✅
- Writes to instance data (`/home/{admin_user}/{app_name}/instance/`) ✅

**Restrictions:**
- NO SSH access ❌
- NO shell access (`/usr/sbin/nologin`) ❌
- NO sudo privileges ❌
- Cannot write to arbitrary locations ❌
- Cannot execute system commands ❌

**Usage in Runtime:**
- Systemd service runs the application as this user
- Limited to application-specific directories and operations
- Completely isolated from administrative functions

**Security Benefits:**
- **Reduced blast radius:** If app is compromised, attacker has no SSH access
- **No shell access:** Attacker cannot spawn interactive shell
- **No privilege escalation:** User cannot use sudo
- **File isolation:** Can only access necessary directories
- **Principle of least privilege:** Only permissions needed for runtime

---

## Configuration

### Setting User Names

In `deployment/group_vars/vault.yml` (edit with `ansible-vault edit`):

```yaml
# ============================================================================
# USERS
# ============================================================================

admin_user: ubuntu                      # Deployment/SSH user (default for Ubuntu AMI)
                                        # Leave as 'ubuntu' unless you have specific needs

app_user: "{{ app_name }}"              # Application runtime user
                                        # Defaults to your app_name
                                        # Change only if you need a different username
                                        # Examples: app_user: "myapp_runtime"
```

### Default Setup (Recommended)

```yaml
app_name: myapp
admin_user: ubuntu          # SSH/deployment user
app_user: myapp             # Runtime user (automatically derived from app_name)
```

This configuration:
- Uses AWS EC2 standard user `ubuntu` for deployment
- Creates a dedicated application user `myapp` for runtime
- Maintains clear separation between deployment and runtime

---

## Deployment Flow

### 1. Initial Deployment

```
Local Machine
    ↓
ansible-playbook (as you, with SSH key)
    ↓
SSH Connection as ubuntu (admin_user)
    ↓
EC2 Instance
├─ Create app_user (myapp)
├─ Clone code as admin_user
├─ Install dependencies as admin_user
├─ Create systemd service
│  └─ Service configured to run as app_user
└─ Start service
   └─ Service runs as app_user (myapp)
```

### 2. Runtime

```
Supervisor
    ↓
supervisorctl start {app_name}
    ↓
Gunicorn (as app_user)
    ├─ Reads code (owned by admin_user, readable by app_user)
    ├─ Writes logs (owned by app_user)
    └─ Accesses data (owned by app_user)
       └─ Serves HTTP requests
```

### 3. Updates

```
Local Machine
    ↓
git push origin main
    ↓
ansible-playbook (update.yml)
    ↓
SSH as ubuntu (admin_user)
    ├─ git pull
    ├─ pip install requirements
    └─ supervisorctl restart {app_name}
       └─ Service restarts as app_user
```

---

## File Ownership and Permissions

### Code Directory

```bash
/opt/{app_name}/
├── Owner: ubuntu (admin_user)
├── Permission: 755 (admin_user full access, app_user read-execute)
└── Readable by: app_user ✅
    Writable by: app_user for logs only
```

### Python Virtual Environment

```bash
/opt/{app_name}/.venv/
├── Owner: ubuntu (admin_user)
├── Permission: 755 (admin_user full access, app_user read-execute)
└── Used by: app_user for Python interpreter and libraries
```

### Log Directory

```bash
/var/log/apps/{app_name}/
├── Owner: {app_name} (app_user)
├── Permission: 755
└── Writable by: app_user ✅
```

### Instance Data Directory

```bash
/opt/{app_name}/instance/
├── Owner: {app_name} (app_user)
├── Permission: 755
└── Writable by: app_user ✅
```

---

## Verification Commands

### Check User Exists

```bash
# Check if app_user exists
getent passwd {app_name}

# Should show something like:
# myapp:x:998:998:MyApp Application User (no login):/nonexistent:/usr/sbin/nologin
```

### Check Process Running as App User

```bash
# See what user is running the application
ps aux | grep gunicorn

# Should show:
# {app_name}  12345  ...  /opt/{app_name}/.venv/bin/gunicorn ...
```

### Check File Ownership

```bash
# Check code ownership
ls -ld /opt/{app_name}
# drwxr-xr-x ubuntu ubuntu ...

# Check log ownership
ls -ld /var/log/apps/{app_name}
# drwxr-xr-x {app_name} {app_name} ...
```

### Verify No SSH Access

```bash
# Try to SSH as app_user (should fail)
sudo -u {app_name} ssh localhost
# Permission denied (publickey)
# or
# no such file or directory (if no home directory)
```

### Verify No Shell

```bash
# Try to get shell as app_user (should fail)
sudo -u {app_name} /bin/bash
# This account is currently not available
```

---

## Customization

### Using Different Admin User

If you want to use a different user for SSH/deployment (e.g., `deploy`):

```yaml
# In vault.yml
admin_user: deploy          # Instead of ubuntu
app_user: "{{ app_name }}"  # Leave as is
```

**Steps:**
1. Create the `deploy` user on the EC2 instance
2. Add your SSH key to `deploy` user's authorized_keys
3. Set `admin_user: deploy` in your vault.yml
4. Run deployment playbooks

### Using Different Application User

If you want a different username for the runtime user:

```yaml
# In vault.yml
admin_user: ubuntu          # Keep as is
app_user: myapp_runtime     # Custom name instead of app_name
```

The application will then run as `myapp_runtime` instead of `myapp`.

---

## Why This Model?

### Security

1. **Principle of Least Privilege:** Application only has permissions it needs
2. **Reduced Attack Surface:** Compromised app cannot SSH to server or use sudo
3. **Clear Separation:** Deployment operations are distinct from runtime
4. **Auditability:** Easy to see who did what (admin_user for deployment, app_user for runtime)

### Operational

1. **Standard Practice:** Used by most production deployments
2. **Systemd Integration:** Works perfectly with systemd services
3. **Easy to Debug:** Clear file ownership and permissions make troubleshooting easier
4. **Flexible:** Easy to customize both usernames if needed

### Compliance

1. **CIS Benchmarks:** Aligns with security best practices
2. **Production-Ready:** Used in enterprise deployments
3. **Auditability:** Clear user separation for audit trails

---

## Migration from Old Model

If you had a different user model before, to migrate:

1. Update vault.yml:
   ```yaml
   admin_user: ubuntu        # Your deployment user
   app_user: myapp           # Your app runtime user
   ```

2. Run deployment to update users:
   ```bash
   ansible-playbook deployment/playbooks/setup.yml
   ```

3. The playbook will:
   - Update file ownership
   - Create/update app_user with proper permissions
   - Update systemd service configuration
   - Restart the application with correct user

---

## Troubleshooting

### "Permission denied" when app writes to logs

**Problem:** App cannot write to log directory

**Solution:**
```bash
# Check ownership
ls -ld /var/log/apps/{app_name}

# Should be owned by {app_name}:{app_name} with setgid (drwxrwsr-x)
# Fix with:
sudo chown -R {app_name}:{app_name} /var/log/apps/{app_name}
sudo chmod 2775 /var/log/apps/{app_name}
```

### App runs but logs not showing

**Problem:** Log directory not writable by app_user

**Solution:**
```bash
# Check permissions
stat /var/log/apps/{app_name}

# Should have write permission for owner (app_user)
# Fix with:
sudo chmod 755 /var/log/apps/{app_name}
```

### Cannot update application as admin_user

**Problem:** admin_user cannot write to code directory

**Solution:**
```bash
# Code should be owned by admin_user with shared group
ls -ld /opt/{app_name}

# Fix with:
sudo chown -R ubuntu:{app_name} /opt/{app_name}
sudo chmod 2775 /opt/{app_name}
```

---

## See Also

- [SECURITY.md](SECURITY.md) - Detailed security hardening information
- [ARCHITECTURE.md](ARCHITECTURE.md) - Overall system architecture
- [PREREQUISITES.md](../guides/PREREQUISITES.md) - Initial setup guide

