#!/bin/bash
# Fix git pull on Pi by stashing local changes, pulling, and restarting
# Run this on the Pi when SSH/access is available

set -e

echo "🔧 Fixing git pull on Pi..."
echo ""

cd ~/anima-mcp || { echo "❌ Could not find anima-mcp directory"; exit 1; }

echo "1️⃣ Checking git status..."
git status --short
echo ""

echo "2️⃣ Stashing local changes..."
git stash push -m "Local changes before sync - $(date +%Y-%m-%d_%H:%M:%S)"
echo ""

echo "3️⃣ Pulling latest changes..."
git pull origin main
echo ""

echo "4️⃣ Restarting anima services..."
sudo systemctl restart anima.service
sudo systemctl restart anima-broker.service
echo ""

echo "✅ Done! Changes stashed, pulled, and services restarted."
echo ""
echo "To see stashed changes later:"
echo "  git stash list"
echo "  git stash show -p stash@{0}"
