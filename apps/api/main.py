from dotenv import load_dotenv
load_dotenv()  # loads apps/api/.env → sets GEMINI_API_KEY in os.environ

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import text
from database import engine, Base
import models  # noqa: ensure all models are registered before create_all

from routers import transactions, upload, bank_statements, bank_accounts, reconciliation, reports, audit_log

# Create all tables on startup
Base.metadata.create_all(bind=engine)

# Run lightweight migrations for new columns
with engine.connect() as _conn:
    for _col_sql in [
        "ALTER TABLE transactions ADD COLUMN bank VARCHAR(200)",
        "ALTER TABLE bank_transactions ADD COLUMN suggested_category VARCHAR(100)",
        "ALTER TABLE bank_transactions ADD COLUMN suggested_type VARCHAR(20)",
        "ALTER TABLE bank_transactions ADD COLUMN vendor VARCHAR(200)",
    ]:
        try:
            _conn.execute(text(_col_sql))
            _conn.commit()
        except Exception:
            pass  # column already exists

    # Normalize legacy USD entries to NGN (this app is NGN-primary)
    try:
        _conn.execute(text("UPDATE transactions SET currency = 'NGN' WHERE currency = 'USD' OR currency IS NULL"))
        _conn.commit()
    except Exception:
        pass

app = FastAPI(
    title="FinanceAudit API",
    description="Personal finance management with AI receipt parsing and bank statement reconciliation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(upload.router)
app.include_router(bank_statements.router)
app.include_router(bank_accounts.router)
app.include_router(reconciliation.router)
app.include_router(reports.router)
app.include_router(audit_log.router)


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
