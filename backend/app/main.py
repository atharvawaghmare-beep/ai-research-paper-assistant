import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config.settings import get_settings
from app.rate_limit import limiter
from app.routers import auth_router, chat_router, health_router, papers_router, users_router

# Schema management lives in Alembic now (see backend/alembic/), not here.
# Run `alembic upgrade head` before starting the app.

# Uvicorn configures its own loggers but leaves everything else at the default
# WARNING level, which would silently swallow app.llm's per-request latency/token
# logs — bump just this app's namespace to INFO rather than every third-party
# library's (avoids drowning the console in httpx/sqlalchemy chatter).
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("app").setLevel(logging.INFO)

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health_router, prefix=settings.api_prefix, tags=["health"])
app.include_router(auth_router, prefix=settings.api_prefix, tags=["auth"])
app.include_router(papers_router, prefix=settings.api_prefix, tags=["papers"])
app.include_router(chat_router, prefix=settings.api_prefix, tags=["chat"])
app.include_router(users_router, prefix=settings.api_prefix, tags=["users"])


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Full-stack starter API"}