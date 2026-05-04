#!/bin/bash
# Initialize git and add the E2ER-project remote
set -e

cd "$(dirname "$0")/.."

if [ ! -d ".git" ]; then
    git init
    git add .
    git commit -m "feat: initial E2ER v3 open-source release"
fi

REMOTE_URL="git@github.com:bhanneke/E2ER-project.git"
if git remote | grep -q "^origin$"; then
    echo "Remote 'origin' already exists. Skipping."
else
    git remote add origin "$REMOTE_URL"
    echo "Added remote origin: $REMOTE_URL"
fi

echo "Done. Run: git push -u origin main"
