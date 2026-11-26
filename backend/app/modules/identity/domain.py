from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Mapping
from types import MappingProxyType
from uuid import UUID


class InvalidToken(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


class MissingProfile(Exception):
    pass


class HiddenResource(Exception):
    pass


class StaleProfile(Exception):
    pass


@dataclass(frozen=True)
class ExternalIdentity:
    issuer: str
    subject: str
    expires_at: datetime | None = field(default=None, compare=False, repr=False)
    email_verified: bool = field(default=False, compare=False, repr=False)
    publication_authorized: bool = field(default=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not self.issuer or len(self.issuer) > 256 or not self.subject or len(self.subject) > 128:
            raise InvalidToken()
        if any((ord(c) < 32 or ord(c) == 127) for c in self.issuer + self.subject):
            raise InvalidToken()


# Explicit Unicode whitespace set, independent of database collation. No normalization.
PROFILE_WHITESPACE = " \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
PROFILE_LIMITS = {"nickname": 80, "avatar_style": 64, "avatar_seed": 256}


def validate_profile_text(field: str, value: str | None) -> None:
    if field not in PROFILE_LIMITS:
        raise ValueError("Unknown profile field")
    if value is None:
        if field == "nickname":
            raise ValueError("Nickname required")
        return
    if (not 1 <= len(value) <= PROFILE_LIMITS[field] or not value.strip(PROFILE_WHITESPACE) or
        any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ValueError("Invalid profile text")


@dataclass(frozen=True)
class ProfileValues:
    nickname: str
    avatar_style: str | None = None
    avatar_seed: str | None = None

    def __post_init__(self) -> None:
        for field, value in (("nickname", self.nickname), ("avatar_style", self.avatar_style), ("avatar_seed", self.avatar_seed)):
            validate_profile_text(field, value)


@dataclass(frozen=True)
class ProfileChanges:
    fields: Mapping[str, str | None]

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("Empty patch")
        for field, value in self.fields.items():
            validate_profile_text(field, value)
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


@dataclass(frozen=True)
class Profile:
    user_id: UUID
    values: ProfileValues
    version: int


def require_owner(actor: UUID, resource: UUID) -> None:
    if actor != resource:
        # Same result for unknown and foreign private resources.
        raise HiddenResource()
