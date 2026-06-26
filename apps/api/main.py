from dotenv import load_dotenv
load_dotenv()  # loads apps/api/.env → sets OPENROUTER_API_KEY in os.environ

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from sqlalchemy import text
from database import engine, Base, initialize_database
import models  # noqa: ensure all models are registered before create_all
from utils.rate_limit import limiter

from routers import transactions, upload, bank_statements, bank_accounts, reconciliation, reports, audit_log, llm_bank_statements, duplicates, auth
from routers import tax, financial_statements, assets, staff_loans, staff_directory, payroll, terms, school_loans

if __name__ != "__pytest_main__":
    # Ensure local SQLite DB is initialized when running the app normally.
    try:
        initialize_database()
    except Exception:
        # Keep startup resilient; initialization can also be run via init_db.py
        pass

app = FastAPI(
    title="FinanceAudit API",
    description="Personal finance management with AI receipt parsing and bank statement reconciliation",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


import os as _os

_origins = ["http://localhost:4200", "http://localhost:3000"]
# FRONTEND_URL is set in Render env vars to your stable Vercel production URL.
_frontend_url = _os.getenv("FRONTEND_URL", "")
if _frontend_url:
    _origins.append(_frontend_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Vercel generates a new random preview URL on every deploy
    # (e.g. audit-aaduzxlng-clogogos-projects.vercel.app) and a separate
    # stable per-branch alias (e.g. audit-app-git-staging-clogogos-projects.vercel.app)
    # — match either shape so CORS doesn't break on new deploys or branches.
    allow_origin_regex=r"^https://audit(-app-git-[a-z0-9-]+|-[a-z0-9]+)?-clogogos-projects\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(upload.router)
app.include_router(bank_statements.router)
app.include_router(llm_bank_statements.router)
app.include_router(bank_accounts.router)
app.include_router(reconciliation.router)
app.include_router(duplicates.router)
app.include_router(reports.router)
app.include_router(audit_log.router)
app.include_router(tax.router)
app.include_router(financial_statements.router)
app.include_router(assets.router)
app.include_router(staff_loans.router)
app.include_router(staff_directory.router)
app.include_router(payroll.router)
app.include_router(terms.router)
app.include_router(school_loans.router)


@app.get("/health")
def health():
    import ai_worker
    import os
    
    ai_status = ai_worker.get_provider_status()
    
    # Check if OCR is available
    ocr_available = False
    try:
        import pytesseract
        import pdf2image
        pytesseract.get_tesseract_version()
        ocr_available = True
    except:
        pass
    
    return {
        "status": "ok",
        "ai": ai_status,
        "ocr": {
            "available": ocr_available,
            "note": "Install tesseract for scanned PDF support: brew install tesseract" if not ocr_available else "OCR ready"
        },
        "supported_formats": {
            "receipts": ["JPG", "PNG", "WebP", "GIF", "PDF"],
            "statements": ["CSV", "Excel (.xlsx/.xls)", "PDF"],
            "max_file_size": "50MB"
        }
    }
