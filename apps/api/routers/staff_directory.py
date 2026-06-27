"""Staff directory — employee profiles used by payroll and loan tracking."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import get_current_user
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Staff

router = APIRouter(prefix="/staff-directory", tags=["staff-directory"], dependencies=[Depends(get_current_user)])


class StaffIn(BaseModel):
    full_name: str
    role: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    monthly_gross: float = 0.0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: bool = True
    notes: Optional[str] = None


class StaffOut(BaseModel):
    id: int
    full_name: str
    role: Optional[str]
    bank_name: Optional[str]
    account_number: Optional[str]
    monthly_gross: float
    start_date: Optional[date]
    end_date: Optional[date]
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[StaffOut])
def list_staff(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(Staff).order_by(Staff.full_name)
    if active_only:
        q = q.filter(Staff.is_active == True)
    return q.all()


@router.post("/", response_model=StaffOut, status_code=201)
def create_staff(body: StaffIn, db: Session = Depends(get_db)):
    member = Staff(**body.model_dump())
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: int, body: StaffIn, db: Session = Depends(get_db)):
    member = db.get(Staff, staff_id)
    if not member:
        raise HTTPException(404, "Staff member not found")
    for k, v in body.model_dump().items():
        setattr(member, k, v)
    member.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{staff_id}", status_code=204)
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    member = db.get(Staff, staff_id)
    if not member:
        raise HTTPException(404, "Staff member not found")
    db.delete(member)
    db.commit()
