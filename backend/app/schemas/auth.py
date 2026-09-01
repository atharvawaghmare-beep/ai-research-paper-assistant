from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.user import UserRead


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    token: TokenResponse
    user: UserRead


class LogoutResponse(BaseModel):
    message: str


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserRead