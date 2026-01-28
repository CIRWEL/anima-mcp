#!/bin/bash
# One-Step Deploy: Mac -> Pi (Lumen)

REMOTE_USER="unitares-anima"
REMOTE_HOST="lumen.local"
REMOTE_DIR="~/anima-mcp"

# 1. Commit/Push Local
echo ">> Committing local changes..."
git add .
git commit -m "Deployment $(date +%Y%m%d_%H%M%S)"
echo ">> Pushing to origin..."
git push

# 2. Pull on Remote
echo ">> Triggering pull on Lumen..."
ssh $REMOTE_USER@$REMOTE_HOST "cd $REMOTE_DIR && git pull && sudo systemctl restart anima-mcp"

echo ">> Deployment Complete!"
