"""
Inventory — items the school buys and sells (books, uniforms, textbooks),
the purchase/sale requests that move stock, and the append-only movement
ledger those requests (and manual adjustments) write to.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import InventoryItem, StockMovement, StockRequest
from utils.auth import require_permission
from utils.errors import get_or_404

router = APIRouter(prefix="/inventory", tags=["inventory"], dependencies=[Depends(require_permission("inventory"))])

VALID_REQUEST_TYPES = {"purchase", "sale"}
VALID_ADJUSTMENT_TYPES = {"adjustment_in", "adjustment_out"}

INVENTORY_CATEGORIES = [
    "Textbook",
    "Uniform",
    "Book",
    "Stationery",
    "Other",
]


# ── schemas ──────────────────────────────────────────────────────────────────

class InventoryItemIn(BaseModel):
    name: str
    sku: Optional[str] = None
    category: str
    unit: str = "piece"
    unit_cost: float = 0.0
    unit_price: float = 0.0
    reorder_level: int = 0
    is_active: bool = True
    notes: Optional[str] = None


class InventoryItemOut(BaseModel):
    id: int
    name: str
    sku: Optional[str]
    category: str
    unit: str
    unit_cost: float
    unit_price: float
    quantity_on_hand: int
    reorder_level: int
    is_low_stock: bool
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class StockRequestIn(BaseModel):
    item_id: int
    request_type: str          # purchase | sale
    quantity: int
    unit_amount: float
    counterparty: Optional[str] = None
    request_date: date
    notes: Optional[str] = None


class StockRequestOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    item_sku: Optional[str]
    request_type: str
    quantity: int
    unit_amount: float
    counterparty: Optional[str]
    status: str
    request_date: date
    fulfilled_date: Optional[date]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


class StockMovementOut(BaseModel):
    id: int
    item_id: Optional[int]
    item_name: Optional[str]
    movement_type: str
    quantity: int
    unit_amount: Optional[float]
    date: date
    request_id: Optional[int]
    transaction_id: Optional[int]
    notes: Optional[str]
    created_at: datetime


class StockAdjustmentIn(BaseModel):
    item_id: int
    movement_type: str         # adjustment_in | adjustment_out
    quantity: int
    date: date
    notes: Optional[str] = None


# ── serialization ────────────────────────────────────────────────────────────

def _item_to_out(item: InventoryItem) -> InventoryItemOut:
    return InventoryItemOut(
        id=item.id, name=item.name, sku=item.sku, category=item.category,
        unit=item.unit, unit_cost=item.unit_cost, unit_price=item.unit_price,
        quantity_on_hand=item.quantity_on_hand, reorder_level=item.reorder_level,
        is_low_stock=item.quantity_on_hand <= item.reorder_level,
        is_active=item.is_active, notes=item.notes,
        created_at=item.created_at, updated_at=item.updated_at,
    )


def _request_to_out(req: StockRequest) -> StockRequestOut:
    return StockRequestOut(
        id=req.id, item_id=req.item_id, item_name=req.item.name, item_sku=req.item.sku,
        request_type=req.request_type, quantity=req.quantity, unit_amount=req.unit_amount,
        counterparty=req.counterparty, status=req.status, request_date=req.request_date,
        fulfilled_date=req.fulfilled_date, notes=req.notes,
        created_at=req.created_at, updated_at=req.updated_at,
    )


def _movement_to_out(m: StockMovement) -> StockMovementOut:
    return StockMovementOut(
        id=m.id, item_id=m.item_id, item_name=m.item.name if m.item else None,
        movement_type=m.movement_type, quantity=m.quantity, unit_amount=m.unit_amount,
        date=m.date, request_id=m.request_id, transaction_id=m.transaction_id,
        notes=m.notes, created_at=m.created_at,
    )


# ── item CRUD ────────────────────────────────────────────────────────────────

@router.get("/items/categories", response_model=list[str])
def list_item_categories():
    """Suggested categories for the item form's dropdown — category itself
    stays free text (same as Transaction.category), so this is advisory
    only, not a server-side allowlist. Matches assets.py's /categories."""
    return INVENTORY_CATEGORIES


@router.get("/items", response_model=list[InventoryItemOut])
def list_items(active_only: bool = False, low_stock_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(InventoryItem).order_by(InventoryItem.name)
    if active_only:
        q = q.filter(InventoryItem.is_active == True)
    if low_stock_only:
        q = q.filter(InventoryItem.quantity_on_hand <= InventoryItem.reorder_level)
    return [_item_to_out(i) for i in q.all()]


@router.post("/items", response_model=InventoryItemOut, status_code=201)
def create_item(body: InventoryItemIn, db: Session = Depends(get_db)):
    item = InventoryItem(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_out(item)


@router.put("/items/{item_id}", response_model=InventoryItemOut)
def update_item(item_id: int, body: InventoryItemIn, db: Session = Depends(get_db)):
    item = get_or_404(db, InventoryItem, item_id, "Inventory item")
    for k, v in body.model_dump().items():
        setattr(item, k, v)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _item_to_out(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = get_or_404(db, InventoryItem, item_id, "Inventory item")
    db.delete(item)
    db.commit()


# ── stock requests (purchase = restock, sale = issue/sell) ─────────────────────

@router.get("/requests", response_model=list[StockRequestOut])
def list_requests(
    request_type: Optional[str] = None,
    status: Optional[str] = None,
    item_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(StockRequest).order_by(StockRequest.request_date.desc(), StockRequest.created_at.desc())
    if request_type:
        q = q.filter(StockRequest.request_type == request_type)
    if status:
        q = q.filter(StockRequest.status == status)
    if item_id:
        q = q.filter(StockRequest.item_id == item_id)
    return [_request_to_out(r) for r in q.all()]


@router.post("/requests", response_model=StockRequestOut, status_code=201)
def create_request(body: StockRequestIn, db: Session = Depends(get_db)):
    if body.request_type not in VALID_REQUEST_TYPES:
        raise HTTPException(400, "request_type must be 'purchase' or 'sale'")
    if body.quantity <= 0:
        raise HTTPException(400, "quantity must be positive")
    get_or_404(db, InventoryItem, body.item_id, "Inventory item")

    req = StockRequest(**body.model_dump(), status="pending")
    db.add(req)
    db.commit()
    db.refresh(req)
    return _request_to_out(req)


@router.put("/requests/{request_id}", response_model=StockRequestOut)
def update_request(request_id: int, body: StockRequestIn, db: Session = Depends(get_db)):
    req = get_or_404(db, StockRequest, request_id, "Stock request")
    if req.status != "pending":
        raise HTTPException(400, "Only pending requests can be edited")
    if body.request_type not in VALID_REQUEST_TYPES:
        raise HTTPException(400, "request_type must be 'purchase' or 'sale'")
    if body.quantity <= 0:
        raise HTTPException(400, "quantity must be positive")
    get_or_404(db, InventoryItem, body.item_id, "Inventory item")

    for k, v in body.model_dump().items():
        setattr(req, k, v)
    req.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return _request_to_out(req)


@router.delete("/requests/{request_id}", status_code=204)
def delete_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, StockRequest, request_id, "Stock request")
    if req.status != "pending":
        raise HTTPException(400, "Only pending requests can be deleted")
    db.delete(req)
    db.commit()


@router.post("/requests/{request_id}/fulfill", response_model=StockRequestOut)
def fulfill_request(request_id: int, db: Session = Depends(get_db)):
    """The core workflow action: turns a pending request into an actual
    stock movement and updates the item's running balance. A purchase adds
    to stock; a sale subtracts, and is rejected if it would go negative."""
    req = get_or_404(db, StockRequest, request_id, "Stock request")
    if req.status != "pending":
        raise HTTPException(400, "Only pending requests can be fulfilled")
    item = req.item

    if req.request_type == "purchase":
        item.quantity_on_hand += req.quantity
        movement_type = "purchase_in"
    else:
        if item.quantity_on_hand - req.quantity < 0:
            raise HTTPException(400, "Insufficient stock to fulfill this sale")
        item.quantity_on_hand -= req.quantity
        movement_type = "sale_out"

    today = date.today()
    movement = StockMovement(
        item_id=item.id, movement_type=movement_type, quantity=req.quantity,
        unit_amount=req.unit_amount, date=today, request_id=req.id,
    )
    db.add(movement)
    req.status = "fulfilled"
    req.fulfilled_date = today
    req.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return _request_to_out(req)


@router.post("/requests/{request_id}/cancel", response_model=StockRequestOut)
def cancel_request(request_id: int, db: Session = Depends(get_db)):
    req = get_or_404(db, StockRequest, request_id, "Stock request")
    if req.status != "pending":
        raise HTTPException(400, "Only pending requests can be cancelled")
    req.status = "cancelled"
    req.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return _request_to_out(req)


# ── stock movement ledger (read-only, plus manual adjustments) ─────────────────

@router.get("/movements", response_model=list[StockMovementOut])
def list_movements(
    item_id: Optional[int] = None,
    movement_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    q = db.query(StockMovement).order_by(StockMovement.date.desc(), StockMovement.created_at.desc())
    if item_id:
        q = q.filter(StockMovement.item_id == item_id)
    if movement_type:
        q = q.filter(StockMovement.movement_type == movement_type)
    if start_date:
        q = q.filter(StockMovement.date >= start_date)
    if end_date:
        q = q.filter(StockMovement.date <= end_date)
    return [_movement_to_out(m) for m in q.all()]


@router.post("/movements/adjust", response_model=StockMovementOut, status_code=201)
def adjust_stock(body: StockAdjustmentIn, db: Session = Depends(get_db)):
    """Manual correction (physical count fix, damage, loss) — bypasses the
    request workflow entirely since it isn't a purchase or a sale."""
    if body.movement_type not in VALID_ADJUSTMENT_TYPES:
        raise HTTPException(400, "movement_type must be 'adjustment_in' or 'adjustment_out'")
    if body.quantity <= 0:
        raise HTTPException(400, "quantity must be positive")
    item = get_or_404(db, InventoryItem, body.item_id, "Inventory item")

    if body.movement_type == "adjustment_out" and item.quantity_on_hand - body.quantity < 0:
        raise HTTPException(400, "Adjustment would take quantity_on_hand negative")

    if body.movement_type == "adjustment_in":
        item.quantity_on_hand += body.quantity
    else:
        item.quantity_on_hand -= body.quantity

    movement = StockMovement(
        item_id=item.id, movement_type=body.movement_type, quantity=body.quantity,
        date=body.date, notes=body.notes,
    )
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return _movement_to_out(movement)
