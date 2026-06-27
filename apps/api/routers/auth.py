"""
Authentication API
User registration, login, and profile management
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from database import get_db
from models import PasswordResetToken, User
from schemas import (
    UserRegister, UserLogin, Token, UserOut,
    ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest,
)
from utils.auth import (
    hash_password,
    verify_password,
    authenticate_user,
    create_access_token,
    get_current_user,
)
from utils.email import send_password_reset_email, send_welcome_email, send_password_changed_email
from utils.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

RESET_TOKEN_EXPIRE_MINUTES = 30


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/register", response_model=UserOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user account. Requires invite_code to match the
    REGISTRATION_INVITE_CODE env var — registration is not open to the
    public internet.

    Args:
        data: User registration data (email, password, invite_code, optional full_name)
        db: Database session

    Returns:
        Created user information

    Raises:
        HTTPException: 403 if invite code is missing/incorrect or registration is disabled
        HTTPException: 400 if email already registered
    """
    invite_code = os.getenv("REGISTRATION_INVITE_CODE")
    if not invite_code or data.invite_code != invite_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing invite code",
        )

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    hashed_pw = hash_password(data.password)
    new_user = User(
        email=data.email,
        hashed_password=hashed_pw,
        full_name=data.full_name,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    try:
        send_welcome_email(new_user.email, new_user.full_name)
    except Exception:
        # Registration already succeeded — a failed welcome email shouldn't
        # fail the request or block the account from being usable.
        logger.exception("Failed to send welcome email")

    return new_user


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Login with email and password to get access token.

    Args:
        credentials: User login credentials (email, password)
        db: Database session

    Returns:
        JWT access token

    Raises:
        HTTPException: 401 if credentials are invalid
    """
    user = authenticate_user(db, credentials.email, credentials.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    # Create access token (sub must be string per JWT spec)
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def forgot_password(request: Request, data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Request a password-reset email. Always returns the same generic message
    whether or not the email is registered, so this endpoint can't be used
    to enumerate which emails have accounts — the token is only generated
    and emailed if a matching user actually exists.
    """
    # If email sending is unconfigured, there's no point creating a token
    # that can never be delivered — short-circuit before touching the DB,
    # still returning the same generic response either way.
    if not os.getenv("MAILEROO_API_KEY") or not os.getenv("MAILEROO_FROM_EMAIL"):
        logger.error("MAILEROO_API_KEY/MAILEROO_FROM_EMAIL are not set — /auth/forgot-password cannot send reset emails")
        return {"message": "If that email is registered, a password reset link has been sent."}

    user = db.query(User).filter(User.email == data.email).first()
    if user:
        raw_token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        )
        db.add(reset_token)
        db.commit()

        # `or` (not getenv's default arg) so an empty-string env var — set but
        # blank, not unset — still falls back instead of producing a
        # link with no domain at all.
        frontend_url = (os.getenv("FRONTEND_URL") or "http://localhost:4200").rstrip("/")
        reset_link = f"{frontend_url}/reset-password?token={raw_token}"
        try:
            send_password_reset_email(user.email, reset_link)
        except Exception:
            # Don't leak send failures to the caller — that would let
            # someone distinguish "email exists" from "email send failed".
            logger.exception("Failed to send password reset email")

    return {"message": "If that email is registered, a password reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def reset_password(request: Request, data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Complete a password reset using the token emailed by /auth/forgot-password.

    Raises:
        HTTPException: 400 if the token is invalid, expired, or already used
        HTTPException: 422 if the new password is too short
    """
    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters",
        )

    token_hash = _hash_token(data.token)
    # Atomically flip used False -> True in a single UPDATE, gated on the
    # same WHERE that defines validity, so two concurrent requests with the
    # same token can't both pass: the database serializes the row write,
    # and whichever loses the race matches zero rows here.
    result = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used == False,  # noqa: E712
            PasswordResetToken.expires_at >= datetime.utcnow(),
        )
        .values(used=True)
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )

    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    user = db.get(User, reset_token.user_id)
    if not user:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user.hashed_password = hash_password(data.new_password)
    db.commit()

    try:
        send_password_changed_email(user.email)
    except Exception:
        logger.exception("Failed to send password-changed confirmation email")

    return {"message": "Password updated. You can now log in with your new password."}


@router.post("/change-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change the logged-in user's own password — requires the current
    password, no recovery code needed since the user is already
    authenticated.

    Raises:
        HTTPException: 401 if current_password is incorrect
        HTTPException: 422 if the new password is too short
    """
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters",
        )

    current_user.hashed_password = hash_password(data.new_password)
    db.commit()

    try:
        send_password_changed_email(current_user.email)
    except Exception:
        logger.exception("Failed to send password-changed confirmation email")

    return {"message": "Password updated."}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Get current authenticated user's information.

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        Current user information
    """
    return current_user
