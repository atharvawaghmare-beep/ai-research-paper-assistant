from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.user import UserCreate, UserRead
from app.services.user_service import create_user, get_user_by_id, list_users


router = APIRouter(prefix="/users")


@router.get("/", response_model=list[UserRead])
def read_users(db: Session = Depends(get_db)) -> list[UserRead]:
    return list_users(db)


@router.get("/{user_id}", response_model=UserRead)
def read_user(user_id: int, db: Session = Depends(get_db)) -> UserRead:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def add_user(payload: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    try:
        return create_user(db, payload)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error