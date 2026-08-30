"""Pydantic models for the protonmail-mcp configuration."""

import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

# Deliberately loose: enough to catch obvious typos without rejecting valid
# addresses. Bridge is the real authority on what logs in.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Endpoint(BaseModel):
    """One IMAP or SMTP endpoint. A ``None`` port means "use the port
    discovered from Bridge's config, or the Bridge default"."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int | None = Field(default=None, ge=1, le=65535)


class AccountConfig(BaseModel):
    """One ProtonMail account, authenticated with its Bridge password."""

    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    email: str
    username: str | None = None
    password: SecretStr
    imap: Endpoint = Field(default_factory=Endpoint)
    smtp: Endpoint = Field(default_factory=Endpoint)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if not _EMAIL_RE.match(value):
            raise ValueError("does not look like an email address")
        return value

    @property
    def effective_username(self) -> str:
        """The IMAP/SMTP login name — Bridge uses the email address unless
        the user configured a distinct bridge username."""
        return self.username or self.email


class Config(BaseModel):
    """Root configuration."""

    model_config = ConfigDict(extra="forbid")

    accounts: list[AccountConfig] = Field(default_factory=list)

    @field_validator("accounts")
    @classmethod
    def _unique_names(cls, value: list[AccountConfig]) -> list[AccountConfig]:
        names = [account.name for account in value]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(f"duplicate account name(s): {', '.join(sorted(duplicates))}")
        return value

    def get_account(self, name: str) -> AccountConfig:
        for account in self.accounts:
            if account.name == name:
                return account
        available = ", ".join(a.name for a in self.accounts) or "(none configured)"
        raise KeyError(f'Account "{name}" not found. Available: {available}')
