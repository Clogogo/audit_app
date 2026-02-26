"""
Audit Logging Utilities
Centralized audit trail logging for entity changes
"""
import json
from sqlalchemy.orm import Session
from models import AuditLog


class AuditLogger:
    """Centralized audit logging utility."""

    @staticmethod
    def log_action(
        db: Session,
        entity_type: str,
        entity_id: int,
        action: str,
        old_values: dict | None = None,
        new_values: dict | None = None,
    ):
        """
        Log an entity change to the audit trail.

        Args:
            db: Database session
            entity_type: Type of entity (e.g., "transaction", "bank_account")
            entity_id: ID of the entity
            action: Action performed (e.g., "create", "update", "delete")
            old_values: Dictionary of old values (for updates/deletes)
            new_values: Dictionary of new values (for creates/updates)

        Example:
            AuditLogger.log_action(
                db, "transaction", tx_id, "update",
                old_values={"amount": 100.0},
                new_values={"amount": 150.0}
            )
        """
        db.add(
            AuditLog(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                old_values=json.dumps(old_values) if old_values else None,
                new_values=json.dumps(new_values) if new_values else None,
            )
        )

    @staticmethod
    def log_create(db: Session, entity_type: str, entity_id: int, data: dict):
        """
        Log entity creation.

        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: ID of created entity
            data: Dictionary of entity data

        Example:
            AuditLogger.log_create(db, "transaction", tx.id, {"amount": 100.0})
        """
        AuditLogger.log_action(db, entity_type, entity_id, "create", new_values=data)

    @staticmethod
    def log_update(
        db: Session,
        entity_type: str,
        entity_id: int,
        old_data: dict,
        new_data: dict,
    ):
        """
        Log entity update.

        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: ID of updated entity
            old_data: Dictionary of old values
            new_data: Dictionary of new values

        Example:
            AuditLogger.log_update(
                db, "transaction", tx.id,
                {"amount": 100.0}, {"amount": 150.0}
            )
        """
        AuditLogger.log_action(
            db, entity_type, entity_id, "update", old_values=old_data, new_values=new_data
        )

    @staticmethod
    def log_delete(db: Session, entity_type: str, entity_id: int, old_data: dict):
        """
        Log entity deletion.

        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: ID of deleted entity
            old_data: Dictionary of entity data before deletion

        Example:
            AuditLogger.log_delete(db, "transaction", tx.id, {"amount": 100.0})
        """
        AuditLogger.log_action(db, entity_type, entity_id, "delete", old_values=old_data)
