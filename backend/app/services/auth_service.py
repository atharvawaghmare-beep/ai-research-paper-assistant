from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import create_access_token, hash_password, verify_password
from app.models.token_blacklist import RevokedToken
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserCreateInternal
from app.services.user_service import create_user_with_password, get_user_by_email


def authenticate_user(db: Session, payload: LoginRequest) -> User | None:
    user = get_user_by_email(db, payload.email)
    if user is None:
        return None
    if not verify_password(payload.password, user.password_hash):
        return None
    return user


def build_auth_response(user: User, token: str) -> AuthResponse:
    return AuthResponse(token=TokenResponse(access_token=token), user=user)


def register_user(db: Session, payload: RegisterRequest) -> AuthResponse:
    user = create_user_with_password(
        db,
        UserCreateInternal(
            email=payload.email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
        ),
    )
    token = create_access_token(subject=str(user.id))
    return build_auth_response(user, token)


def login_user(db: Session, payload: LoginRequest) -> AuthResponse:
    user = authenticate_user(db, payload)
    if user is None:
        raise ValueError("Invalid email or password")
    token = create_access_token(subject=str(user.id))
    return build_auth_response(user, token)


def revoke_token(db: Session, jti: str, expires_at: datetime) -> None:
    statement = select(RevokedToken).where(RevokedToken.jti == jti)
    existing = db.scalar(statement)
    if existing is not None:
        return

    revoked_token = RevokedToken(jti=jti, expires_at=expires_at)
    db.add(revoked_token)
    db.commit()


def is_token_revoked(db: Session, jti: str) -> bool:
    statement = select(RevokedToken).where(RevokedToken.jti == jti)
    return db.scalar(statement) is not None


def extract_token_expiry(payload: dict[str, object]) -> datetime:
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(exp, tz=timezone.utc)