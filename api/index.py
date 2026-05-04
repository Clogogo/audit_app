"""
Vercel serverless function entry point for FastAPI app.
Routes all /api/* requests to the FastAPI application.
"""

import sys
import os
from pathlib import Path

# Ensure apps/api is in the path for imports
api_path = Path(__file__).parent.parent / "apps" / "api"
if str(api_path) not in sys.path:
    sys.path.insert(0, str(api_path))

# Change to api directory so relative imports work
os.chdir(str(api_path))

# Import the FastAPI app (this triggers database initialization and migrations)
from main import app

# Export for Vercel
__all__ = ["app"]
