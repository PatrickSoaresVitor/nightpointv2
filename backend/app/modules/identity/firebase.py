"""Official verifier only; initialization/credentials are external to this adapter."""
import os
from datetime import datetime, timezone
import re
from dataclasses import dataclass
from typing import Literal, Any, cast
from uuid import uuid4
from google.auth.credentials import Credentials

from firebase_admin import initialize_app, delete_app, auth, exceptions

from .domain import ExternalIdentity, InvalidToken, ProviderUnavailable


class UnconfiguredVerifier:
    def verify(self, token: str) -> ExternalIdentity:
        raise ProviderUnavailable()


@dataclass(frozen=True)
class FirebaseConfiguration:
    project: str
    environment: Literal["test", "local"]
    provenance: Literal["explicit-isolated-composition"]
    timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if (not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project) or
            self.environment not in {"test", "local"} or self.provenance != "explicit-isolated-composition" or
            not 0 < self.timeout_seconds <= 5):
            raise ValueError("Invalid explicit Firebase configuration")


class FirebaseVerifier:
    def __init__(self, configuration: FirebaseConfiguration, credential: Credentials) -> None:
        # Own a new named App; never reuse an externally initialized/cached Auth client.
        if os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
            raise ValueError("Non-emulator process required")
        self.configuration = configuration
        self.project = configuration.project
        self._app = initialize_app(credential, {"projectId": self.project,
            "httpTimeout": configuration.timeout_seconds}, name="nightpoint-" + uuid4().hex)

    def ready(self) -> bool:
        # Configuration readiness only; real provider connectivity needs its authorized test.
        return not os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") and self._app.project_id == self.project

    def close(self) -> None:
        delete_app(self._app)

    def verify(self, token: str) -> ExternalIdentity:
        if not self.ready():
            raise ProviderUnavailable()
        try:
            # Verify cryptography/claims first, then reject unapproved namespaces before status lookup.
            claims = auth.verify_id_token(token, app=self._app, check_revoked=False, clock_skew_seconds=0)
            issuer = "https://securetoken.google.com/" + self.project
            subject = claims.get("sub")
            firebase_claim = claims.get("firebase", {})
            if (claims.get("iss") != issuer or claims.get("aud") != self.project or not isinstance(subject, str) or
                not isinstance(firebase_claim, dict) or cast(dict[str, Any], firebase_claim).get("tenant") is not None):
                raise InvalidToken()
            # Real age/elegibility policy is not authorized yet: publication stays
            # closed even for a cryptographically verified email. No client claim
            # or arbitrary custom role is promoted into publication authority.
            identity = ExternalIdentity(issuer, subject, datetime.fromtimestamp(claims["exp"], timezone.utc),
                                        email_verified=claims.get("email_verified") is True)
            # Keep revocation/disabled-account validation in the official SDK too.
            auth.verify_id_token(token, app=self._app, check_revoked=True, clock_skew_seconds=0)
            return identity
        except auth.CertificateFetchError:
            raise ProviderUnavailable() from None
        except (auth.InvalidIdTokenError, auth.RevokedIdTokenError, auth.UserDisabledError,
                auth.UserNotFoundError, ValueError):
            raise InvalidToken() from None
        except (exceptions.FirebaseError, OSError):
            raise ProviderUnavailable() from None
