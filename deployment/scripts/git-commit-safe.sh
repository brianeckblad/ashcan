# Git Commit Helper Script
# Use this to safely commit with complex messages

#!/bin/bash

# Safe commit function that handles quotes and special characters properly
git_commit_safe() {
    local message="$1"

    # Use printf with %q for proper quoting
    git commit -m "$message"
}

# Example usage:
# git_commit_safe "feat: add new feature"
# git_commit_safe "docs: fix something with 'quotes' and special chars"

# Alternative: Use commit message file to avoid quote issues entirely
git_commit_file() {
    local message_file="$1"
    git commit -F "$message_file"
}

# Usage: Create a file called COMMIT_MSG.txt with your message,
# then run: git_commit_file COMMIT_MSG.txt

