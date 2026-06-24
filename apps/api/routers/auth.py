"""
Authentication API
User registration, login, and profile management
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import UserRegister, UserLogin, Token, UserOut, ForgotPasswordRequest
from utils.auth import (
    hash_password,
    authenticate_user,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user account.

    Args:
        data: User registration data (email, password, optional full_name)
        db: Database session

    Returns:
        Created user information

    Raises:
        HTTPException: 400 if email already registered
    """
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
def login(credentials: UserLogin, db: Session = Depends(get_db)):
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
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Reset a forgotten password directly by email — no current password or
    verification token required. Intended for small/trusted deployments
    where there's no email service to send a reset link through.

    Args:
        data: Account email and the new password to set
        db: Database session

    Raises:
        HTTPException: 404 if no account exists for that email
        HTTPException: 422 if the new password is too short
    """
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
