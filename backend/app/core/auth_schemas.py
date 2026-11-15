"""Request/response shapes shared by staff and user authentication."""

from typing import Literal

from pydantic import BaseModel, Field

PASSWORD = Field(min_length=10, max_length=200)


class LoginOut(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    two_factor_required: bool = False
    challenge_token: str | None = None
    # "app": a code from the authenticator app; "email": a code Core just emailed.
    two_factor_method: Literal["app", "email"] | None = None


class TwoFactorVerifyIn(BaseModel):
    challenge_token: str
    # the app's 6-digit code, the emailed code, or a backup code (xxxx-xxxx, go-live G-4)
    code: str = Field(min_length=6, max_length=12)


class ChallengeIn(BaseModel):
    challenge_token: str


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorEnableIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class RecoveryCodesOut(BaseModel):
    """Shown once: each works once in place of the app's code (go-live G-4)."""

    recovery_codes: list[str]


class RecoveryCodesIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=6)  # the app's current code


class TwoFactorDisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=6)
