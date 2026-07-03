"""Terms — named custom date ranges (e.g. school terms) reusable as a filter across pages."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_permission
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Term

router = APIRouter(prefix="/terms", tags=["terms"], dependencies=[Depends(require_permission("staff"))])


class TermIn(BaseModel):
    name: str
    start_date: date
    end_date: date


class TermOut(BaseModel):
    id: int
    name: str
    start_date: date
    end_date: date
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[TermOut])
def list_terms(db: Session = Depends(get_db)):
    return db.query(Term).order_by(Term.start_date.desc()).all()


@router.post("/", response_model=TermOut, status_code=201)
def create_term(body: TermIn, db: Session = Depends(get_db)):
    if body.end_date < body.start_date:
        raise HTTPException(422, "End date must be on or after the start date")
    term = Term(**body.model_dump())
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


@router.put("/{term_id}", response_model=TermOut)
def update_term(term_id: int, body: TermIn, db: Session = Depends(get_db)):
    term = db.get(Term, term_id)
    if not term:
        raise HTTPException(404, "Term not found")
    if body.end_date < body.start_date:
        raise HTTPException(422, "End date must be on or after the start date")
    for k, v in body.model_dump().items():
        setattr(term, k, v)
    db.commit()
    db.refresh(term)
    return term


@router.delete("/{term_id}", status_code=204)
def delete_term(term_id: int, db: Session = Depends(get_db)):
    term = db.get(Term, term_id)
    if not term:
        raise HTTPException(404, "Term not found")
    db.delete(term)
    db.commit()
