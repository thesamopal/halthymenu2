"""
Rate limiter. Используется для защиты /login, /register от brute-force.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


limiter = Limiter(key_func=get_remote_address)
