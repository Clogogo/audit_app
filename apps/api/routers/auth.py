"""
Authentication API
User registration, login, and profile management
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import UserRegister, UserLogin, Token, UserOut, ForgotPasswordRequest, ChangePasswordRequest
from utils.auth import (
    hash_password,
    verify_password,
    authenticate_user,
    create_access_token,
    get_current_user,
)
from utils.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
    Reset a forgotten password by email — gated by recovery_code, which must
    match the PASSWORD_RECOVERY_CODE env var. There's no email service to
    send a reset link through, so this code (set by the admin in the
    deployment's environment, not in source control) stands in for one;
    without it, anyone who knew an account's email could take it over.

    Args:
        data: Account email, the new password to set, and the recovery code
        db: Database session

    Raises:
        HTTPException: 403 if PASSWORD_RECOVERY_CODE is unset or recovery_code doesn't match
        HTTPException: 404 if no account exists for that email
        HTTPException: 422 if the new password is too short
    """
    recovery_code = os.getenv("PASSWORD_RECOVERY_CODE")
    if not recovery_code or data.recovery_code != recovery_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing recovery code",
        )

    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters",
        )

    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with that email",
        )

    user.hashed_password = hash_password(data.new_password)
    db.commit()
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
