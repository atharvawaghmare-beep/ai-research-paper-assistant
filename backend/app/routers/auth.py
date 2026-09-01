from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_token, get_current_user, get_token_payload
from app.auth.security import decode_access_token
from app.config.database import get_db
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, LogoutResponse, RegisterRequest
from app.schemas.user import UserRead
from app.services.auth_service import login_user, register_user, revoke_token


router = APIRouter(prefix="/auth")


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    try:
        return register_user(db, payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    try:
        return login_user(db, payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


@router.get("/me", response_model=UserRead)
def current_user(current_user: User = Depends(get_current_user)) -> UserRead:
    return current_user


@router.post("/logout", response_model=LogoutResponse)
def logout(
    db: Session = Depends(get_db),
    token: str = Depends(get_current_token),
) -> LogoutResponse:
    try:
        payload = decode_access_token(token)
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not isinstance(jti, str) or not isinstance(exp, (int, float)):
            raise ValueError
        revoke_token(db, jti, datetime.fromtimestamp(exp, tz=timezone.utc))
    except (InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials") from None

    return LogoutResponse(message="Logged out successfully")