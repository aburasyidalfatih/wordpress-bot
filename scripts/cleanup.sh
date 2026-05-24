#!/bin/bash
# Cleanup script for bot

cd "$(dirname "$0")/.."

echo "Cleaning up..."

# Clean old logs
find logs/ -name "*.log" -size +50M -exec truncate -s 0 {} \; 2>/dev/null

# Clean __pycache__
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# Clean .pyc files
find . -name "*.pyc" -delete 2>/dev/null

# Clean old generated images (if exists)
find generated_images/ -type f -mtime +7 -delete 2>/dev/null

echo "✅ Cleanup complete"
