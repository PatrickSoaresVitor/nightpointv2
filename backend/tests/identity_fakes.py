"""Synthetic fixtures only: not packaged in app or selected by an environment flag."""
from uuid import UUID, uuid4

from app.modules.identity.domain import ExternalIdentity, InvalidToken, MissingProfile, Profile, ProfileValues, ProfileChanges, ProviderUnavailable, StaleProfile


class FakeVerifier:
    def verify(self, token: str) -> ExternalIdentity:
        if token == "provider-unavailable":
            raise ProviderUnavailable("synthetic-secret-in-exception")
        if token not in {"actor-a", "actor-b"}:
            raise InvalidToken("synthetic-secret-in-exception")
        return ExternalIdentity("synthetic-issuer", token, email_verified=True, publication_authorized=True)


class MemoryRepository:
    def __init__(self) -> None:
        self.identities: dict[ExternalIdentity, UUID] = {}
        self.profiles: dict[UUID, Profile] = {}

    def resolve(self, identity: ExternalIdentity) -> UUID | None:
        return self.identities.get(identity)

    def read(self, user_id: UUID) -> Profile | None:
        return self.profiles.get(user_id)

    def enroll(self, identity: ExternalIdentity, values: ProfileValues) -> tuple[Profile, bool]:
        user_id = self.identities.setdefault(identity, uuid4())
        created = user_id not in self.profiles
        if created:
            self.profiles[user_id] = Profile(user_id, values, 1)
        return self.profiles[user_id], created

    def update(self, user_id: UUID, values: ProfileChanges, expected_version: int) -> Profile:
        old = self.profiles.get(user_id)
        if old is None:
            raise MissingProfile()
        if old.version != expected_version:
            raise StaleProfile()
        fields = {"nickname": old.values.nickname, "avatar_style": old.values.avatar_style, "avatar_seed": old.values.avatar_seed, **values.fields}
        nickname = fields["nickname"]
        assert nickname is not None
        self.profiles[user_id] = Profile(user_id, ProfileValues(nickname, fields["avatar_style"], fields["avatar_seed"]), old.version + 1)
        return self.profiles[user_id]
