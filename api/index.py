"""
Vercel serverless function entry point for FastAPI app.
Routes all /api/* requests to the FastAPI application.
"""

import sys
from pathlib import Path

# Add apps/api to path so imports work
api_path = Path(__file__).parent.parent / "apps" / "api"
sys.path.insert(0, str(api_path))

# Import the FastAPI app
from main import app

# Export for Vercel
__all__ = ["app"]
