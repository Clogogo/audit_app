"""Tests for the one-time is_admin -> role_id migration in
database.py's _seed_roles_and_permissions(): existing users without a role
yet must land on Admin (if is_admin was set) or Accountant (everyone else),
matching their prior defacto access level."""
from database import _seed_roles_and_permissions
from models import Role, User
from utils.auth import hash_password


def test_existing_admin_user_migrates_to_the_admin_role(db_session):
    user = User(
        email="legacy-admin@example.com", hashed_password=hash_password("password123"),
        full_name="Legacy Admin", is_active=True, is_admin=True,
    )
    db_session.add(user)
    db_session.commit()

    _seed_roles_and_permissions()

    db_session.refresh(user)
    assert user.role is not None
    assert user.role.name == "Admin"
    assert "user_management" in {p.key for p in user.role.permissions}


def test_existing_non_admin_user_migrates_to_the_accountant_role(db_session):
    user = User(
        email="legacy-user@example.com", hashed_password=hash_password("password123"),
        full_name="Legacy User", is_active=True, is_admin=False,
    )
    db_session.add(user)
    db_session.commit()

    _seed_roles_and_permissions()

    db_session.refresh(user)
    assert user.role is not None
    assert user.role.name == "Accountant"
    granted = {p.key for p in user.role.permissions}
    assert "user_management" not in granted
    assert "transactions" in granted  # keeps full financial access, matching prior defacto behavior


def test_migration_is_permanently_inert_once_a_role_is_assigned(db_session):
    # A user who already has a role (however it got there) must never be
    # silently reassigned by a later run of this migration.
    user = User(
        email="already-migrated@example.com", hashed_password=hash_password("password123"),
        full_name="Already Migrated", is_active=True, is_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    _seed_roles_and_permissions()
    db_session.refresh(user)

    staff_role = db_session.query(Role).filter(Role.name == "Staff").first()
    user.role_id = staff_role.id
    db_session.commit()

    _seed_roles_and_permissions()  # re-running must not touch an already-migrated user

    db_session.refresh(user)
    assert user.role.name == "Staff"
