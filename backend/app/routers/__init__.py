from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.routers.papers import router as papers_router
from app.routers.users import router as users_router

__all__ = ["auth_router", "chat_router", "health_router", "papers_router", "users_router"]