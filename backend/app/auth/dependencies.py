from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.config.database import get_db
from app.config.settings import get_settings
from app.models.user import User
from app.services.auth_service import is_token_revoked
from app.services.user_service import get_user_by_id

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_prefix}/auth/login")


def get_current_token(token: str = Depends(oauth2_scheme)) -> str:
    return token


def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        jti = payload.get("jti")
        if not isinstance(subject, str) or not isinstance(jti, str):
            raise credentials_exception
        if is_token_revoked(db, jti):
            raise credentials_exception
        user_id = int(subject)
    except (InvalidTokenError, ValueError, TypeError):
        raise credentials_exception from None

    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_token_payload(token: str = Depends(oauth2_scheme)) -> dict[str, object]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        if not isinstance(payload, dict):
            raise credentials_exception
        return payload
    except InvalidTokenError:
        raise credentials_exception from None