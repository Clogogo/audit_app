import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog
from schemas import AuditLogOut

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


@router.get("", response_model=list[AuditLogOut])
def get_audit_log(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditLog.entity_id == entity_id)
    logs = q.order_by(AuditLog.timestamp.desc()).limit(limit).all()

    result = []
    for log in logs:
        out = AuditLogOut.model_validate(log)
        if log.old_values:
            try:
                out.old_values = json.loads(log.old_values)
            except Exception:
                out.old_values = log.old_values
        if log.new_values:
            try:
                out.new_values = json.loads(log.new_values)
            except Exception:
                out.new_values = log.new_values
        result.append(out)
    return result
