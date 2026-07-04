"""
User Management — listing and activation/role control for registered
accounts, gated behind the user_management permission. Every change is
written to the AuditLog.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Permission, Role, User
from schemas import UserAdminUpdate, UserOut
from utils.audit import AuditLogger
from utils.auth import require_permission

# A single shared dependency instance — reused for both the router-level
# gate and update_user's per-endpoint `current_user` parameter, so FastAPI's
# per-request dependency cache actually applies (require_permission(...)
# returns a new closure on every call, so using two separate calls here
# would run the permission check, and its get_current_user/DB lookup, twice).
require_user_management = require_permission("user_management")

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_user_management)])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at).all()


def _has_user_management(role: Optional[Role]) -> bool:
    return role is not None and any(p.key == "user_management" for p in role.permissions)


def _other_user_management_holder_exists(db: Session, exclude_user_id: int) -> bool:
    """True if some other ACTIVE user currently holds a role granting
    user_management — an inactive holder can't actually reach anything, so
    doesn't count toward keeping the system manageable. One joined query,
    not one query per role."""
    return (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .join(Role.permissions)
        .filter(
            Permission.key == "user_management",
            User.id != exclude_user_id,
            User.is_active == True,
        )
        .first()
        is not None
    )


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserAdminUpdate,
    current_user: User = Depends(require_user_management),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # exclude_unset alone still lets a caller send an explicit `null` for a
    # field ({"is_active": null}), which would try to write None into a
    # NOT NULL column (a 500) — drop any None values too, since there's no
    # meaningful "set this flag to null" operation on this endpoint.
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        return user

    new_role = None
    if "role_id" in updates:
        new_role = db.get(Role, updates["role_id"])
        if not new_role:
            raise HTTPException(404, "Role not found")

    is_self = user_id == current_user.id
    deactivating_self = is_self and updates.get("is_active") is False
    losing_user_management = (
        new_role is not None and _has_user_management(user.role) and not _has_user_management(new_role)
    )
    # Deactivating someone (not just changing their role) can strand the
    # system too if they currently hold user_management and no one else does.
    deactivating_a_holder = updates.get("is_active") is False and _has_user_management(user.role)

    if deactivating_self or (is_self and losing_user_management):
        raise HTTPException(400, "You cannot deactivate or demote your own account")

    strands_user_management = (
        (losing_user_management or deactivating_a_holder)
        and not _other_user_management_holder_exists(db, user_id)
    )
    if strands_user_management:
        raise HTTPException(400, "Cannot remove the last remaining user with User Management access")

    old_values = {"is_active": user.is_active, "role_id": user.role_id, "full_name": user.full_name}
    for key, value in updates.items():
        setattr(user, key, value)
    new_values = {"is_active": user.is_active, "role_id": user.role_id, "full_name": user.full_name}

    AuditLogger.log_action(db, "user", user.id, "admin_update", old_values=old_values, new_values=new_values)
    db.commit()
    db.refresh(user)
    return user
