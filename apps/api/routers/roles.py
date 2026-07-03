"""
Roles & Permissions — admin-only (user_management permission) management of
the RBAC system: create/edit/delete roles and toggle which of the app's
fixed permission keys each role grants. Permissions themselves are a fixed,
app-defined set (see database.py's _PERMISSION_SEEDS) — not admin-creatable,
only assignable to roles.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Permission, Role, User
from schemas import PermissionOut, RoleIn, RoleOut
from utils.audit import AuditLogger
from utils.auth import require_permission

router = APIRouter(prefix="/roles", tags=["roles"], dependencies=[Depends(require_permission("user_management"))])


@router.get("", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db)):
    return db.query(Role).order_by(Role.name).all()


@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(db: Session = Depends(get_db)):
    return db.query(Permission).order_by(Permission.key).all()


def _resolve_permissions(db: Session, keys: list[str]) -> list[Permission]:
    permissions = db.query(Permission).filter(Permission.key.in_(keys)).all()
    unknown = set(keys) - {p.key for p in permissions}
    if unknown:
        raise HTTPException(400, f"Unknown permission key(s): {', '.join(sorted(unknown))}")
    return permissions


def _would_strand_user_management(db: Session, role: Role, new_permission_keys: list[str]) -> bool:
    """True if removing user_management from this role would leave no role
    with both user_management AND at least one assigned user — i.e. nobody
    left who could reach Role/User Management to fix it."""
    had_it = any(p.key == "user_management" for p in role.permissions)
    keeps_it = "user_management" in new_permission_keys
    if not had_it or keeps_it:
        return False

    other_holder_ids = [
        r.id for r in db.query(Role).all()
        if r.id != role.id and any(p.key == "user_management" for p in r.permissions)
    ]
    if not other_holder_ids:
        return True
    remaining = db.query(func.count(User.id)).filter(User.role_id.in_(other_holder_ids)).scalar()
    return remaining == 0


@router.post("", response_model=RoleOut, status_code=201)
def create_role(body: RoleIn, db: Session = Depends(get_db)):
    if db.query(Role).filter(Role.name == body.name).first():
        raise HTTPException(400, f"A role named '{body.name}' already exists")

    role = Role(name=body.name, description=body.description)
    role.permissions = _resolve_permissions(db, body.permission_keys)
    db.add(role)
    db.flush()
    AuditLogger.log_action(
        db, "role", role.id, "create",
        new_values={"name": role.name, "permissions": sorted(body.permission_keys)},
    )
    db.commit()
    db.refresh(role)
    return role


@router.put("/{role_id}", response_model=RoleOut)
def update_role(role_id: int, body: RoleIn, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")

    name_taken = db.query(Role).filter(Role.name == body.name, Role.id != role_id).first()
    if name_taken:
        raise HTTPException(400, f"A role named '{body.name}' already exists")

    if _would_strand_user_management(db, role, body.permission_keys):
        raise HTTPException(400, "This change would leave no role with User Management access")

    old_values = {"name": role.name, "permissions": sorted(p.key for p in role.permissions)}
    role.name = body.name
    role.description = body.description
    role.permissions = _resolve_permissions(db, body.permission_keys)
    new_values = {"name": role.name, "permissions": sorted(body.permission_keys)}

    AuditLogger.log_action(db, "role", role.id, "update", old_values=old_values, new_values=new_values)
    db.commit()
    db.refresh(role)
    return role


@router.delete("/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role.is_system:
        raise HTTPException(400, "This role is required by the system and cannot be deleted")

    assigned_count = db.query(func.count(User.id)).filter(User.role_id == role_id).scalar()
    if assigned_count:
        raise HTTPException(400, f"Cannot delete a role assigned to {assigned_count} user(s) — reassign them first")

    AuditLogger.log_action(db, "role", role.id, "delete", old_values={"name": role.name})
    db.delete(role)
    db.commit()
