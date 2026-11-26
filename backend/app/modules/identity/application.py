from uuid import UUID

from .domain import ExternalIdentity, MissingProfile, Profile, ProfileValues, ProfileChanges, require_owner
from .ports import IdentityRepository
from .api import VerifiedActor


class IdentityService:
    def __init__(self, repository: IdentityRepository) -> None:
        self.repository = repository

    def actor(self, identity: ExternalIdentity) -> VerifiedActor | None:
        identifier = self.repository.resolve(identity)
        return VerifiedActor(identifier) if identifier is not None else None

    def profile(self, actor: UUID, resource: UUID) -> Profile:
        require_owner(actor, resource)
        profile = self.repository.read(actor)
        if profile is None:
            raise MissingProfile()
        return profile

    def provision(self, identity: ExternalIdentity, values: ProfileValues) -> tuple[Profile, bool]:
        return self.repository.enroll(identity, values)

    def update(self, actor: UUID, resource: UUID, values: ProfileChanges, version: int) -> Profile:
        require_owner(actor, resource)
        return self.repository.update(actor, values, version)
