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


def test_a_user_registered_after_the_first_run_is_never_auto_assigned_a_role(db_session):
    # Regression: the legacy cutover must only ever apply on the very first
    # run (when the Role table itself didn't exist yet) — a user who shows
    # up on any LATER run (e.g. a brand new registration) must keep
    # role_id = NULL forever, until an admin explicitly assigns one. Silently
    # upgrading a fresh signup to Accountant on the next server restart would
    # hand out real financial-data access with no one having decided that.
    _seed_roles_and_permissions()  # first run: seeds Admin/Accountant/Staff, no users yet

    new_user = User(
        email="freshly-registered@example.com", hashed_password=hash_password("password123"),
        full_name="Fresh Signup", is_active=True, is_admin=False,
    )
    db_session.add(new_user)
    db_session.commit()

    _seed_roles_and_permissions()  # a later run — must NOT touch this user's role

    db_session.refresh(new_user)
    assert new_user.role is None
