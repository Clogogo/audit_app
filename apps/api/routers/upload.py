import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models import UploadedFile, Transaction, AuditLog
from schemas import (
    TransactionCreate, TransactionOut,
    UploadedFileOut, AIResult,
    BatchUploadResult, BatchItem,
    BatchConfirmRequest,
)
import ai_worker
from ai_worker import GeminiRateLimitError, AIProviderError

router = APIRouter(prefix="/upload", tags=["upload"])

BASE_DIR = Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "application/pdf",
}


def _save_file(contents: bytes, filename: str) -> Path:
    ext = Path(filename).suffix or ".bin"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(contents)
    return stored_path


# ── Single receipt upload ─────────────────────────────────────────────────────

@router.post("", response_model=UploadedFileOut)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    contents = await file.read()
    stored_path = _save_file(contents, file.filename or "file")
    try:
        ocr_text, ai_result = ai_worker.process_file(str(stored_path), file.content_type or "")
    except GeminiRateLimitError as e:
        raise HTTPException(429, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(503, detail=str(e))

    record = UploadedFile(
        original_name=file.filename or stored_path.name,
        stored_path=str(stored_path),
        mime_type=file.content_type or "",
        ocr_text=ocr_text,
        ai_result=json.dumps(ai_result) if ai_result else None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    out = UploadedFileOut.model_validate(record)
    if record.ai_result:
        try:
            out.ai_result = AIResult(**json.loads(record.ai_result))
        except Exception:
            pass
    return out


@router.post("/{upload_id}/confirm", response_model=TransactionOut, status_code=201)
def confirm_upload(upload_id: int, data: TransactionCreate, db: Session = Depends(get_db)):
    upload = db.get(UploadedFile, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found")
    data.file_id = upload_id
    tx = Transaction(**data.model_dump())
    db.add(tx)
    db.flush()
    db.add(AuditLog(entity_type="transaction", entity_id=tx.id, action="create",
                    new_values=json.dumps(data.model_dump(mode="json"))))
    db.commit()
    db.refresh(tx)
    return tx


# ── Batch upload ──────────────────────────────────────────────────────────────

@router.post("/batch", response_model=BatchUploadResult)
async def upload_batch(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    contents = await file.read()
    stored_path = _save_file(contents, file.filename or "file")
    try:
        ocr_text, items = ai_worker.process_file_batch(str(stored_path), file.content_type or "")
    except GeminiRateLimitError as e:
        raise HTTPException(429, detail=str(e))
    except AIProviderError as e:
        raise HTTPException(503, detail=str(e))

    record = UploadedFile(
        original_name=file.filename or stored_path.name,
        stored_path=str(stored_path),
        mime_type=file.content_type or "",
        ocr_text=ocr_text,
        ai_result=json.dumps(items),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    batch_items = []
    for item in items:
        try:
            batch_items.append(BatchItem(**item))
        except Exception:
            continue

    return BatchUploadResult(
        file_id=record.id,
        original_name=record.original_name,
        mime_type=record.mime_type,
        item_count=len(batch_items),
        items=batch_items,
    )


@router.post("/batch/{file_id}/confirm", response_model=list[TransactionOut], status_code=201)
def confirm_batch(file_id: int, req: BatchConfirmRequest, db: Session = Depends(get_db)):
    upload = db.get(UploadedFile, file_id)
    if not upload:
        raise HTTPException(404, "Upload not found")

    saved = []
    for item in req.items:
        item.file_id = file_id
        tx = Transaction(**item.model_dump())
        db.add(tx)
        db.flush()
        db.add(AuditLog(entity_type="transaction", entity_id=tx.id, action="create",
                        new_values=json.dumps(item.model_dump(mode="json"))))
        saved.append(tx)

    db.commit()
    for tx in saved:
        db.refresh(tx)
    return saved


# ── File preview ──────────────────────────────────────────────────────────────

@router.get("/{file_id}/preview")
def preview_file(file_id: int, db: Session = Depends(get_db)):
    record = db.get(UploadedFile, file_id)
    if not record:
        raise HTTPException(404, "File not found")
    path = Path(record.stored_path)
    if not path.exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(path=str(path), media_type=record.mime_type,
                        filename=record.original_name)
