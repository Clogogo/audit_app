"""
User Management — admin-only listing and activation/role control for
registered accounts. Every change is written to the AuditLog.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import UserAdminUpdate, UserOut
from utils.audit import AuditLogger
from utils.auth import get_current_admin_user

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_admin_user)])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at).all()


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserAdminUpdate,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # exclude_unset alone still lets a caller send an explicit `null` for a
    # boolean field ({"is_active": null}), which would try to write None into
    # a NOT NULL column (a 500) — drop any None values too, since there's no
    # meaningful "set this flag to null" operation on this endpoint.
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return user

    is_self = user_id == current_user.id
    demoting_self = is_self and updates.get("is_admin") is False
    deactivating_self = is_self and updates.get("is_active") is False
    if demoting_self or deactivating_self:
        raise HTTPException(400, "You cannot deactivate or demote your own account")

    if updates.get("is_admin") is False:
        other_admins = (
            db.query(func.count(User.id))
            .filter(User.is_admin == True, User.id != user_id)
            .scalar()
        )
        if not other_admins:
            raise HTTPException(400, "Cannot remove the last remaining admin")

    old_values = {"is_active": user.is_active, "is_admin": user.is_admin}
    for key, value in updates.items():
        setattr(user, key, value)
    new_values = {"is_active": user.is_active, "is_admin": user.is_admin}

    AuditLogger.log_action(db, "user", user.id, "admin_update", old_values=old_values, new_values=new_values)
    db.commit()
    db.refresh(user)
    return user
