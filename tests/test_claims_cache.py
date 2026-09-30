import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from club.config import settings
from club.errors import DomainError
from club.security import VERIFIED, claims


def short_token(seconds):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": "1", "ver": 1, "iat": now, "exp": now + timedelta(seconds=seconds), "aud": "club-v2"},
        settings().jwt_secret,
        algorithm="HS256",
    )


def test_cached_claims_still_expire(env):
    value = short_token(1)
    assert claims(value)["sub"] == "1"
    assert value in VERIFIED
    time.sleep(1.1)
    with pytest.raises(DomainError) as expired:
        claims(value)
    assert expired.value.status == 401


def test_forged_token_is_never_cached(env):
    forged = jwt.encode({"sub": "1", "ver": 1, "exp": time.time() + 60, "aud": "club-v2"}, "x" * 40)
    with pytest.raises(DomainError):
        claims(forged)
    assert forged not in VERIFIED
