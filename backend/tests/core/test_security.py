import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)


def test_password_roundtrip():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)


def test_wrong_password_fails():
    assert not verify_password("wrong", hash_password("right"))


def test_garbage_hash_fails_instead_of_crashing():
    assert not verify_password("x", "not-a-hash")


def test_token_roundtrip_carries_claims():
    sub, tenant = uuid.uuid4(), uuid.uuid4()
    claims = decode_access_token(create_access_token(sub, "user", tenant), expected_typ="user")
    assert (claims.sub, claims.typ, claims.tenant_id) == (sub, "user", tenant)


def test_token_with_wrong_typ_rejected():
    token = create_access_token(uuid.uuid4(), "user", uuid.uuid4())
    with pytest.raises(InvalidToken):
        decode_access_token(token, expected_typ="staff")


def test_expired_token_rejected():
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    token = create_access_token(uuid.uuid4(), "staff", None, now=long_ago)
    with pytest.raises(InvalidToken):
        decode_access_token(token, expected_typ="staff")


def test_tampered_token_rejected():
    token = create_access_token(uuid.uuid4(), "staff", None)
    with pytest.raises(InvalidToken):
        decode_access_token(token[:-2] + "xx", expected_typ="staff")


def test_refresh_token_is_stored_only_as_hash():
    plain, hashed = new_refresh_token()
    assert plain != hashed
    assert hash_token(plain) == hashed
    assert len(plain) >= 40
