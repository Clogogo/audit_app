"""
Error Handling Utilities
Centralized error handling for common API patterns
"""
from typing import TypeVar
from fastapi import HTTPException
from sqlalchemy.orm import Session

T = TypeVar("T")


def get_or_404(
    db: Session,
    model: type[T],
    entity_id: int,
    entity_name: str | None = None,
) -> T:
    """
    Retrieve entity by ID or raise 404 HTTPException.

    Args:
        db: Database session
        model: SQLAlchemy model class
        entity_id: ID of entity to retrieve
        entity_name: Optional custom name for error message

    Returns:
        The entity if found

    Raises:
        HTTPException: 404 if entity not found

    Example:
        account = get_or_404(db, BankAccount, account_id, "Bank account")
    """
    entity = db.get(model, entity_id)
    if not entity:
        name = entity_name or model.__name__
        raise HTTPException(404, f"{name} not found")
    return entity
