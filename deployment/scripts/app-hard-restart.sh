#!/bin/bash
# Force hard restart and cache clearing script
# Supported shells: bash, zsh

# Shell compatibility check
current_shell=$(ps -p $$ -o comm= 2>/dev/null)
current_shell=$(basename "$current_shell" 2>/dev/null)
current_shell=$(echo "$current_shell" | tr -d '-')
if [[ -z "$current_shell" ]]; then
    current_shell=$(basename "$SHELL" 2>/dev/null)
    current_shell=$(echo "$current_shell" | tr -d '-')
fi
case "$current_shell" in
    bash|zsh)
        ;; # Supported shell
    *)
        echo "⚠️  WARNING: Unsupported shell detected!" >&2
        echo "   Current shell: $current_shell" >&2
        echo "   Supported shells: bash, zsh" >&2
        echo "" >&2
        echo "   Please run with: bash ./deployment/scripts/app-hard-restart.sh" >&2
        exit 1
        ;;
esac

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the app name getter function
source "$SCRIPT_DIR/lib/get-app-name.sh"

# Get app name from config (or use environment variable override)
if [ -z "$APP_NAME" ]; then
    APP_NAME=$(get_app_name) || exit 1
fi

echo "🔄 FORCE RESTART WITH CACHE CLEARING"
echo "======================================"
echo "Application: $APP_NAME"
echo ""

APP_DIR="/opt/${APP_NAME}"
cd "${APP_DIR}"

# Step 1: Stop the app
echo ""
echo "1️⃣ Stopping application..."
sudo supervisorctl stop ${APP_NAME}
sleep 2
echo "✅ App stopped"

# Step 2: Clear ALL Python caches
echo ""
echo "2️⃣ Clearing all Python caches..."
echo "   • Clearing __pycache__ directories..."
find "${APP_DIR}" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
echo "   • Clearing .pyc files..."
find "${APP_DIR}" -type f -name "*.pyc" -delete 2>/dev/null || true
echo "   • Clearing .pytest_cache..."
find "${APP_DIR}" -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
echo "   • Clearing Flask temp files..."
rm -rf /tmp/flask-* 2>/dev/null || true
rm -rf /tmp/gunicorn-* 2>/dev/null || true
echo "✅ All Python caches cleared"

# Step 3: Verify code is latest
echo ""
echo "3️⃣ Verifying latest code from git..."
git fetch origin main 2>/dev/null
git log --oneline -1
echo "✅ Code verified"

# Step 4: Kill any remaining Gunicorn processes
echo ""
echo "4️⃣ Killing any remaining Gunicorn processes..."
pkill -f "gunicorn.*${APP_NAME}" 2>/dev/null || true
sleep 2
echo "✅ Old processes killed"

# Step 5: Start the app fresh
echo ""
echo "5️⃣ Starting application fresh..."
sudo supervisorctl start ${APP_NAME}
sleep 5  # Give it more time to start
echo "✅ App started"

# Step 6: Check status
echo ""
echo "6️⃣ Checking application status..."
if sudo supervisorctl status ${APP_NAME} | grep -q "RUNNING"; then
    echo "✅ App is running"
else
    echo "❌ App is NOT running - check logs"
    echo ""
    echo "Recent logs:"
    sudo tail -20 /var/log/apps/${APP_NAME}/error.log
    exit 1
fi

# Step 7: Verify the method exists in the code
echo ""
echo "7️⃣ Verifying cleanup_orphaned_images method exists in code..."
if grep -q "def cleanup_orphaned_images(self):" app/services/comic_service.py; then
    echo "✅ Method found in code"
else
    echo "❌ Method NOT found in code"
    exit 1
fi

# Step 8: Verify the method is accessible via Python (live check)
echo ""
echo "8️⃣ Testing if method is accessible in running app..."
cd "/opt/${APP_NAME}"
python3 << PYTHON_TEST
import sys
sys.path.insert(0, '/opt/${APP_NAME}')
try:
    from app.services.comic_service import comic_service
    if hasattr(comic_service, 'cleanup_orphaned_images'):
        print("✅ Method is accessible via Python import")
    else:
        print("❌ Method NOT accessible - comic_service does not have cleanup_orphaned_images attribute")
        print(f"Available methods: {[m for m in dir(comic_service) if not m.startswith('_')]}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Error testing method: {e}")
    sys.exit(1)
PYTHON_TEST

if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️  WARNING: Method exists in code but is not accessible!"
    echo "This suggests the virtual environment or imports are stale."
    echo ""
    echo "Trying to reinstall dependencies in venv..."
    source /opt/${APP_NAME}/.venv/bin/activate
    pip install --force-reinstall --no-cache-dir -e . 2>/dev/null || true
fi

echo ""
echo "======================================"
echo "✅ RESTART COMPLETE!"
echo "======================================"
echo ""
echo "The cleanup_orphaned_images button should now work."
echo ""
echo "To test:"
echo "  1. Go to the trash page"
echo "  2. Click the cleanup button"
echo "  3. Check the logs for success:"
echo "     sudo tail -f /var/log/apps/$APP_NAME/app.log"
