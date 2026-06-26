"""Shared rate limiter — defined separately from main.py so routers can
import it without a circular import (main.py imports the routers)."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
