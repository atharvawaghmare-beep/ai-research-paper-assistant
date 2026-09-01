from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserCreateInternal


def list_users(db: Session) -> list[User]:
    statement = select(User).order_by(User.created_at.desc())
    return list(db.scalars(statement))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    return db.scalar(statement)


def create_user(db: Session, payload: UserCreate) -> User:
    existing_user = get_user_by_email(db, payload.email)
    if existing_user is not None:
        raise ValueError("User with this email already exists")

    user = User(email=payload.email, password_hash=hash_password(payload.password), full_name=payload.full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_user_with_password(db: Session, payload: UserCreateInternal) -> User:
    existing_user = get_user_by_email(db, payload.email)
    if existing_user is not None:
        raise ValueError("User with this email already exists")

    user = User(email=payload.email, password_hash=payload.password_hash, full_name=payload.full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user