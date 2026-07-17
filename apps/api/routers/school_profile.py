"""
School Profile — singleton identity record (name, tagline, contacts, logo).

GET is open to any authenticated user because the app header and PDF report
covers render from it; updates are gated behind the user_management
permission since the school identity is admin-level configuration. The logo
is stored in the database as base64 — the production filesystem is
ephemeral, so a file in uploads/ would disappear on every redeploy.
"""
import base64
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, SchoolProfile
from schemas import SchoolProfileIn, SchoolProfileOut
from utils.auth import get_current_user, require_permission

router = APIRouter(
    prefix="/school-profile",
    tags=["school-profile"],
    dependencies=[Depends(get_current_user)],
)

MAX_LOGO_BYTES = 500 * 1024

# Magic-byte signatures — validates real image content, not just the
# client-supplied Content-Type header.
_IMAGE_SIGNATURES: dict[str, bytes] = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
}

_PROFILE_ID = 1  # singleton row


def _to_out(profile: SchoolProfile | None) -> SchoolProfileOut:
    if profile is None:
        return SchoolProfileOut(name="")
    logo = None
    if profile.logo_data and profile.logo_mime:
        logo = f"data:{profile.logo_mime};base64,{profile.logo_data}"
    return SchoolProfileOut(
        name=profile.name,
        tagline=profile.tagline,
        phone=profile.phone,
        website=profile.website,
        address=profile.address,
        country=profile.country or "Nigeria",
        logo=logo,
        updated_at=profile.updated_at,
    )


@router.get("", response_model=SchoolProfileOut)
def get_school_profile(db: Session = Depends(get_db)):
    """Current profile, or blank defaults if it has never been saved."""
    return _to_out(db.get(SchoolProfile, _PROFILE_ID))


@router.put(
    "",
    response_model=SchoolProfileOut,
    dependencies=[Depends(require_permission("user_management"))],
)
def update_school_profile(data: SchoolProfileIn, db: Session = Depends(get_db)):
    """Create or update the singleton profile (text fields only)."""
    profile = db.get(SchoolProfile, _PROFILE_ID)
    fields = data.model_dump()

    if profile is None:
        action, old_values = "create", None
        profile = SchoolProfile(id=_PROFILE_ID, **fields)
        db.add(profile)
    else:
        action = "update"
        old_values = json.dumps({k: getattr(profile, k) for k in fields})
        for key, value in fields.items():
            setattr(profile, key, value)

    db.add(AuditLog(
        entity_type="school_profile", entity_id=_PROFILE_ID, action=action,
        old_values=old_values, new_values=json.dumps(fields),
    ))
    db.commit()
    db.refresh(profile)
    return _to_out(profile)


@router.post(
    "/logo",
    response_model=SchoolProfileOut,
    dependencies=[Depends(require_permission("user_management"))],
)
async def upload_school_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload/replace the school logo (JPG or PNG, max 500KB)."""
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(400, detail="Empty file uploaded")
    if len(contents) > MAX_LOGO_BYTES:
        raise HTTPException(413, detail="Logo too large. Maximum size: 500KB")

    mime = next(
        (m for m, sig in _IMAGE_SIGNATURES.items() if contents.startswith(sig)),
        None,
    )
    if mime is None:
        raise HTTPException(
            400, detail="Unsupported image format. Please upload a JPG or PNG file."
        )

    profile = db.get(SchoolProfile, _PROFILE_ID)
    if profile is None:
        # Logo uploaded before the profile form was ever saved — create the
        # singleton with a blank name so the row exists to hold the logo.
        profile = SchoolProfile(id=_PROFILE_ID, name="")
        db.add(profile)

    profile.logo_data = base64.b64encode(contents).decode("ascii")
    profile.logo_mime = mime

    db.add(AuditLog(
        entity_type="school_profile", entity_id=_PROFILE_ID, action="logo_update",
        new_values=json.dumps({"logo_mime": mime, "logo_bytes": len(contents)}),
    ))
    db.commit()
    db.refresh(profile)
    return _to_out(profile)


def get_branding(db: Session) -> tuple[str | None, bytes | None]:
    """(school_name, logo_bytes) for report covers and headers — both None
    when the profile has never been saved. Used by the PDF/Excel exporters."""
    profile = db.get(SchoolProfile, _PROFILE_ID)
    if profile is None:
        return None, None
    name = (profile.name or "").strip() or None
    logo = base64.b64decode(profile.logo_data) if profile.logo_data else None
    return name, logo
