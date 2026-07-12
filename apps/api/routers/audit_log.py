from typing import Optional

from fastapi import APIRouter, Depends, Query
from utils.auth import require_permission
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog
from schemas import AuditLogOut
from utils import safe_json_loads

router = APIRouter(prefix="/audit-log", tags=["audit-log"], dependencies=[Depends(require_permission("audit_log"))])


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
        out.old_values = safe_json_loads(log.old_values)
        out.new_values = safe_json_loads(log.new_values)
        result.append(out)
    return result
