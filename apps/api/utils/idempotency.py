"""Idempotency-key protection for money-creating writes (school loans,
loan payments, ...) — guards against a duplicate submission (double click,
or a client retrying a request whose response it never saw) creating a
second real financial record."""
from typing import Optional

from fastapi import Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import IdempotencyKey

IdempotencyKeyHeader = Header(default=None, alias="Idempotency-Key", max_length=100)


def reserve_idempotency_key(db: Session, key: Optional[str]) -> None:
    """Call once per write, before the endpoint's final db.commit() — reserves
    the key in the same transaction as the actual insert, so both land
    together or neither does. A missing key is a no-op (older clients keep
    working, just without duplicate protection). Raises 409 if the key was
    already used."""
    if not key:
        return
    db.add(IdempotencyKey(key=key))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This request was already submitted")
