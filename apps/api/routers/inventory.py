"""
Inventory — items the school buys and sells (books, uniforms, textbooks),
the purchase/sale requests that move stock, and the append-only movement
ledger those requests (and manual adjustments) write to.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

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
    unit_cost: Optional[float]     # cost basis at time of sale — only set on sale_out
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


class SalesSummaryOut(BaseModel):
    total_sales_count: int
    total_revenue: float
    total_cost: float
    total_profit: float
    profit_margin_pct: float
    # Sales fulfilled before cost-snapshotting existed (or where the item
    # had no unit_cost set at the time) — counted in total_revenue but
    # excluded from cost/profit so an unknown cost is never treated as zero.
    sales_missing_cost_count: int


class ItemReportOut(BaseModel):
    item_id: int
    item_name: str
    sku: Optional[str]
    category: str
    quantity_on_hand: int
    total_purchased_quantity: int
    total_purchase_cost: float
    total_sold_quantity: int
    total_sale_revenue: float
    costed_revenue: float          # subset of total_sale_revenue with a known cost — the
                                    # correct denominator for a blended margin across items,
                                    # since total_profit only ever reflects costed sales too
    total_profit: float
    profit_margin_pct: float
    sales_missing_cost_count: int


# ── serialization ────────────────────────────────────────────────────────────

def _normalize_item_data(data: dict) -> dict:
    """An empty-string SKU is not exempt from the column's UNIQUE
    constraint the way NULL is — a second item left without a SKU would
    otherwise collide with the first and crash with an unhandled
    IntegrityError. Blank SKU always means "no SKU", so treat it as NULL."""
    if data.get("sku") == "":
        data["sku"] = None
    return data


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
        unit_cost=m.unit_cost, date=m.date, request_id=m.request_id, transaction_id=m.transaction_id,
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
    data = _normalize_item_data(body.model_dump())
    item = InventoryItem(**data)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, f"SKU \"{data['sku']}\" is already in use by another item")
    db.refresh(item)
    return _item_to_out(item)


@router.put("/items/{item_id}", response_model=InventoryItemOut)
def update_item(item_id: int, body: InventoryItemIn, db: Session = Depends(get_db)):
    item = get_or_404(db, InventoryItem, item_id, "Inventory item")
    data = _normalize_item_data(body.model_dump())
    for k, v in data.items():
        setattr(item, k, v)
    item.updated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, f"SKU \"{data['sku']}\" is already in use by another item")
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
    q = (
        db.query(StockRequest)
        .options(selectinload(StockRequest.item))
        .order_by(StockRequest.request_date.desc(), StockRequest.created_at.desc())
    )
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

    movement_unit_cost = None
    if req.request_type == "purchase":
        item.quantity_on_hand += req.quantity
        movement_type = "purchase_in"
    else:
        if item.quantity_on_hand - req.quantity < 0:
            raise HTTPException(400, "Insufficient stock to fulfill this sale")
        item.quantity_on_hand -= req.quantity
        movement_type = "sale_out"
        # Snapshot the item's cost now, at the moment stock actually leaves
        # — profit for this sale stays correct even if unit_cost is edited
        # on the item later. A cost of exactly 0 is treated the same as
        # "never entered" (unit_cost defaults to 0.0, not None, so there's
        # no schema-level way to tell a genuine free item apart from one
        # nobody priced) — a real $0 acquisition cost isn't a realistic
        # scenario for resold stock, so this avoids reporting 100% margin
        # sales-summary results for items whose cost was simply left blank.
        movement_unit_cost = item.unit_cost if item.unit_cost > 0 else None

    today = date.today()
    movement = StockMovement(
        item_id=item.id, movement_type=movement_type, quantity=req.quantity,
        unit_amount=req.unit_amount, unit_cost=movement_unit_cost, date=today, request_id=req.id,
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
    q = (
        db.query(StockMovement)
        .options(selectinload(StockMovement.item))
        .order_by(StockMovement.date.desc(), StockMovement.created_at.desc())
    )
    if item_id:
        q = q.filter(StockMovement.item_id == item_id)
    if movement_type:
        q = q.filter(StockMovement.movement_type == movement_type)
    if start_date:
        q = q.filter(StockMovement.date >= start_date)
    if end_date:
        q = q.filter(StockMovement.date <= end_date)
    return [_movement_to_out(m) for m in q.all()]


@router.get("/sales-summary", response_model=SalesSummaryOut)
def get_sales_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Total revenue and profit across every fulfilled sale (sale_out
    movements). Cost is only known for sales fulfilled after unit_cost
    snapshotting existed, so cost/profit are computed only over the subset
    where it's set — an unknown cost is never silently treated as zero.
    All aggregates computed in a single query via conditional SUM/COUNT
    rather than one query per figure."""
    has_cost = StockMovement.unit_cost.isnot(None)
    revenue_expr = StockMovement.quantity * StockMovement.unit_amount

    q = db.query(
        func.count(StockMovement.id).label("total_sales_count"),
        func.coalesce(func.sum(revenue_expr), 0.0).label("total_revenue"),
        func.count(case((has_cost, 1))).label("costed_sales_count"),
        func.coalesce(func.sum(case((has_cost, revenue_expr), else_=0.0)), 0.0).label("costed_revenue"),
        func.coalesce(
            func.sum(case((has_cost, StockMovement.quantity * StockMovement.unit_cost), else_=0.0)), 0.0
        ).label("total_cost"),
    ).filter(StockMovement.movement_type == "sale_out")
    if start_date:
        q = q.filter(StockMovement.date >= start_date)
    if end_date:
        q = q.filter(StockMovement.date <= end_date)

    row = q.one()
    total_profit = round(row.costed_revenue - row.total_cost, 2)
    profit_margin_pct = round(total_profit / row.costed_revenue * 100, 2) if row.costed_revenue > 0 else 0.0

    return SalesSummaryOut(
        total_sales_count=row.total_sales_count,
        total_revenue=round(row.total_revenue, 2),
        total_cost=round(row.total_cost, 2),
        total_profit=total_profit,
        profit_margin_pct=profit_margin_pct,
        sales_missing_cost_count=row.total_sales_count - row.costed_sales_count,
    )


@router.get("/reports/items", response_model=list[ItemReportOut])
def get_items_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Per-item purchase/sale totals and profit — "what was bought and
    what was sold", broken out by item instead of one grand total.
    Queried from InventoryItem outer-joined to StockMovement (unlike
    list_movements/get_sales_summary, which query StockMovement directly
    with a WHERE filter) so an item with no movements yet — or none
    within the given date range — still appears with all-zero figures
    rather than being omitted. Date filters are applied inside the JOIN
    condition rather than a post-join WHERE, which is what preserves that
    "item still appears" guarantee for a LEFT JOIN."""
    join_conditions = [StockMovement.item_id == InventoryItem.id]
    if start_date:
        join_conditions.append(StockMovement.date >= start_date)
    if end_date:
        join_conditions.append(StockMovement.date <= end_date)

    is_purchase = StockMovement.movement_type == "purchase_in"
    is_sale = StockMovement.movement_type == "sale_out"
    is_costed_sale = and_(is_sale, StockMovement.unit_cost.isnot(None))
    line_total = StockMovement.quantity * StockMovement.unit_amount
    cost_total = StockMovement.quantity * StockMovement.unit_cost

    rows = (
        db.query(
            InventoryItem.id.label("item_id"),
            InventoryItem.name.label("item_name"),
            InventoryItem.sku.label("sku"),
            InventoryItem.category.label("category"),
            InventoryItem.quantity_on_hand.label("quantity_on_hand"),
            func.coalesce(func.sum(case((is_purchase, StockMovement.quantity), else_=0)), 0)
                .label("total_purchased_quantity"),
            func.coalesce(func.sum(case((is_purchase, line_total), else_=0.0)), 0.0)
                .label("total_purchase_cost"),
            func.count(case((is_sale, 1))).label("total_sales_count"),
            func.coalesce(func.sum(case((is_sale, StockMovement.quantity), else_=0)), 0)
                .label("total_sold_quantity"),
            func.coalesce(func.sum(case((is_sale, line_total), else_=0.0)), 0.0)
                .label("total_sale_revenue"),
            func.count(case((is_costed_sale, 1))).label("costed_sales_count"),
            func.coalesce(func.sum(case((is_costed_sale, line_total), else_=0.0)), 0.0)
                .label("costed_revenue"),
            func.coalesce(func.sum(case((is_costed_sale, cost_total), else_=0.0)), 0.0)
                .label("total_cost"),
        )
        .outerjoin(StockMovement, and_(*join_conditions))
        .group_by(InventoryItem.id)
        .order_by(InventoryItem.name)
        .all()
    )

    results = []
    for row in rows:
        total_profit = round(row.costed_revenue - row.total_cost, 2)
        profit_margin_pct = round(total_profit / row.costed_revenue * 100, 2) if row.costed_revenue > 0 else 0.0
        results.append(ItemReportOut(
            item_id=row.item_id, item_name=row.item_name, sku=row.sku, category=row.category,
            quantity_on_hand=row.quantity_on_hand,
            total_purchased_quantity=row.total_purchased_quantity,
            total_purchase_cost=round(row.total_purchase_cost, 2),
            total_sold_quantity=row.total_sold_quantity,
            total_sale_revenue=round(row.total_sale_revenue, 2),
            costed_revenue=round(row.costed_revenue, 2),
            total_profit=total_profit,
            profit_margin_pct=profit_margin_pct,
            sales_missing_cost_count=row.total_sales_count - row.costed_sales_count,
        ))
    return results


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
