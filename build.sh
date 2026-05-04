#!/bin/bash
set -e

echo "Building frontend..."
npx nx build web

echo "Python dependencies already available in /api directory"
echo "Build completed successfully"
