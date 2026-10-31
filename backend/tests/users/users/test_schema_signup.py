"""The sign-up request body rejects keys it does not declare."""

import pytest
from pydantic import ValidationError

import modules.users.users.schema as users_schema

_BODY = {"name": "New", "username": "newuser", "email": "new@example.com", "password": "SecurePass1!"}


def test_signup_rejects_unknown_key():
    users_schema.UsersSignup(**_BODY)

    with pytest.raises(ValidationError) as exc:
        users_schema.UsersSignup(**_BODY, access_type=2)

    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_signup_password_is_optional():
    body = {key: value for key, value in _BODY.items() if key != "password"}

    assert users_schema.UsersSignup(**body).password is None


def test_signup_password_still_has_a_minimum_length():
    with pytest.raises(ValidationError):
        users_schema.UsersSignup(**{**_BODY, "password": "short"})
