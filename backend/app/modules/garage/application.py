from uuid import UUID
from app.modules.identity.api import ActorProvider
from .domain import Vehicle, VehicleInput, VehicleRevision, HiddenVehicle
from .ports import VehicleRepository


class GarageService:
    def __init__(self, repository: VehicleRepository) -> None:
        self.repository = repository

    def create(self, actor: ActorProvider, key: UUID, values: VehicleInput) -> tuple[Vehicle, bool]:
        return self.repository.create(actor().user_id, key, values)

    def detail(self, actor: ActorProvider, identifier: UUID) -> Vehicle:
        vehicle = self.repository.detail(actor().user_id, identifier)
        if vehicle is None: raise HiddenVehicle()
        return vehicle

    def update(self, actor: ActorProvider, identifier: UUID, values: VehicleInput, version: int) -> Vehicle:
        return self.repository.update(actor().user_id, identifier, values, version)

    def owned(self, actor: ActorProvider, archived: bool, limit: int, offset: int) -> list[Vehicle]:
        self._bounds(limit, offset)
        return self.repository.owned(actor().user_id, archived, limit + 1, offset)

    def history(self, actor: ActorProvider, identifier: UUID, limit: int, offset: int) -> list[VehicleRevision]:
        self._bounds(limit, offset)
        return self.repository.history(actor().user_id, identifier, limit + 1, offset)

    @staticmethod
    def _bounds(limit: int, offset: int) -> None:
        if not 1 <= limit <= 50 or not 0 <= offset <= 5000: raise ValueError('Invalid bounds')
