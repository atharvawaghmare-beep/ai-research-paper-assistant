"""Shared rate limiter for LLM-calling endpoints (chat, summary, concept
explanation) — these are the expensive, slow requests worth protecting from
abuse or accidental hammering. Keyed by client IP rather than user, since it's
a simple, standard defense against a single source firing requests too fast;
per-user quotas would need the JWT parsed inside the key function itself,
which isn't worth the extra complexity at this project's scale.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
