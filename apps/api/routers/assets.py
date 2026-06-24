"""
School Assets — fixed asset register with straight-line / reducing-balance depreciation.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Asset

router = APIRouter(prefix="/assets", tags=["assets"])

ASSET_CATEGORIES = [
    "Land & Buildings",
    "Motor Vehicles",
    "Furniture & Fittings",
    "Plant & Equipment",
    "Computer Equipment",
    "Library Books & Educational Materials",
    "Intangible Assets",
    "Other",
]


# ── Depreciation helpers (also imported by financial_statements + tax) ─────────

def _annual_sl(asset: Asset) -> float:
    """Annual straight-line depreciation charge."""
    depreciable = max(asset.purchase_cost - asset.residual_value, 0.0)
    return depreciable / max(asset.useful_life_years, 0.1)


def calc_accumulated(asset: Asset, as_at: date) -> float:
    """Accumulated depreciation from purchase_date through as_at."""
    if as_at <= asset.purchase_date:
        return 0.0
    years = (as_at - asset.purchase_date).days / 365.25
    max_dep = max(asset.purchase_cost - asset.residual_value, 0.0)

    if asset.depreciation_method == "reducing_balance":
        rate = 1.0 / max(asset.useful_life_years, 0.1)
        nbv = asset.purchase_cost
        whole = int(years)
        for _ in range(whole):
            nbv = max(nbv - nbv * rate, asset.residual_value)
        frac = years - whole
        nbv = max(nbv - nbv * rate * frac, asset.residual_value)
        return round(asset.purchase_cost - nbv, 2)
    else:
        return round(min(_annual_sl(asset) * years, max_dep), 2)


def calc_period_dep(asset: Asset, start: date, end: date) -> float:
    """Depreciation charge for the period [start, end]."""
    if end <= asset.purchase_date:
        return 0.0
    effective_start = max(start, asset.purchase_date)
    days = (end - effective_start).days
    if days <= 0:
        return 0.0
    acc_start = calc_accumulated(asset, effective_start)
    acc_end = calc_accumulated(asset, end)
    return round(max(acc_end - acc_start, 0.0), 2)


def calc_nbv(asset: Asset, as_at: date) -> float:
    return round(asset.purchase_cost - calc_accumulated(asset, as_at), 2)


def _asset_out(asset: Asset, as_at: date) -> dict:
    acc = calc_accumulated(asset, as_at)
    return {
        "id": asset.id,
        "name": asset.name,
        "category": asset.category,
        "purchase_date": str(asset.purchase_date),
        "purchase_cost": asset.purchase_cost,
        "useful_life_years": asset.useful_life_years,
        "depreciation_method": asset.depreciation_method,
        "residual_value": asset.residual_value,
        "accumulated_depreciation": round(acc, 2),
        "net_book_value": round(asset.purchase_cost - acc, 2),
        "annual_depreciation": round(_annual_sl(asset), 2) if asset.depreciation_method == "straight_line" else None,
        "notes": asset.notes,
        "created_at": str(asset.created_at),
        "updated_at": str(asset.updated_at),
    }


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    name: str
    category: str
    purchase_date: date
    purchase_cost: float = Field(gt=0)
    useful_life_years: float = Field(default=5.0, gt=0)
    depreciation_method: str = Field(default="straight_line")
    residual_value: float = Field(default=0.0, ge=0)
    notes: Optional[str] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_cost: Optional[float] = None
    useful_life_years: Optional[float] = None
    depreciation_method: Optional[str] = None
    residual_value: Optional[float] = None
    notes: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/categories")
def list_categories():
    return ASSET_CATEGORIES


@router.get("/summary")
def get_assets_summary(
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: Session = Depends(get_db),
):
    """Assets grouped by category: NBV at end_date + depreciation charge for the period."""
    sd = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date)
    assets = db.query(Asset).all()

    by_cat: dict[str, dict] = {}
    total_cost = total_acc = total_nbv = total_per_dep = 0.0

    for a in assets:
        acc = calc_accumulated(a, ed)
        nbv = round(a.purchase_cost - acc, 2)
        p_dep = calc_period_dep(a, sd, ed)
        cat = a.category

        if cat not in by_cat:
            by_cat[cat] = {"category": cat, "cost": 0.0,
                           "accumulated_depreciation": 0.0,
                           "net_book_value": 0.0,
                           "period_depreciation": 0.0,
                           "count": 0}
        by_cat[cat]["cost"] = round(by_cat[cat]["cost"] + a.purchase_cost, 2)
        by_cat[cat]["accumulated_depreciation"] = round(by_cat[cat]["accumulated_depreciation"] + acc, 2)
        by_cat[cat]["net_book_value"] = round(by_cat[cat]["net_book_value"] + nbv, 2)
        by_cat[cat]["period_depreciation"] = round(by_cat[cat]["period_depreciation"] + p_dep, 2)
        by_cat[cat]["count"] += 1

        total_cost = round(total_cost + a.purchase_cost, 2)
        total_acc = round(total_acc + acc, 2)
        total_nbv = round(total_nbv + nbv, 2)
        total_per_dep = round(total_per_dep + p_dep, 2)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "asset_count": len(assets),
        "categories": sorted(by_cat.values(), key=lambda x: x["category"]),
        "total_cost": total_cost,
        "total_accumulated_depreciation": total_acc,
        "total_net_book_value": total_nbv,
        "total_period_depreciation": total_per_dep,
    }


@router.get("/")
def list_assets(
    as_at: Optional[str] = Query(None, description="Date for NBV YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    assets = db.query(Asset).order_by(Asset.category, Asset.name).all()
    ad = date.fromisoformat(as_at) if as_at else date.today()
    return [_asset_out(a, ad) for a in assets]


@router.post("/", status_code=201)
def create_asset(body: AssetCreate, db: Session = Depends(get_db)):
    asset = Asset(**body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _asset_out(asset, date.today())


@router.put("/{asset_id}")
def update_asset(asset_id: int, body: AssetUpdate, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    asset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(asset)
    return _asset_out(asset, date.today())


@router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    db.delete(asset)
    db.commit()
