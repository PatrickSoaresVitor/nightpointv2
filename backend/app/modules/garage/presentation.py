from collections.abc import Callable
from typing import Annotated, Self, TypeVar, Literal, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.identity.api import ActorProvider, VerifiedActor
from app.presentation.contracts import Problem
from .application import GarageService
from .domain import VehicleInput, Vehicle, HiddenVehicle, StaleVehicle, VehicleConflict

T = TypeVar('T')


class VehicleBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    brand: str = Field(min_length=1, max_length=80, strict=True)
    model: str = Field(min_length=1, max_length=120, strict=True)
    year: int | None = Field(default=None, ge=1900, le=2100, strict=True)
    color: str | None = Field(default=None, min_length=1, max_length=60, strict=True)
    category: Literal['car', 'motorcycle', 'truck', 'other'] = 'car'
    primary: bool = Field(default=False, strict=True)
    archived: bool = Field(default=False, strict=True)

    def value(self) -> VehicleInput:
        return VehicleInput(self.brand, self.model, self.year, self.color, self.category, self.primary, self.archived)

    @model_validator(mode='after')
    def valid(self) -> Self:
        self.value()
        return self


class VehicleOutput(VehicleBody):
    id: UUID
    version: int

    @classmethod
    def of(cls, value: Vehicle) -> 'VehicleOutput':
        return cls(id=value.id, version=value.version, brand=value.values.brand, model=value.values.model,
                   year=value.values.year, color=value.values.color, category=value.values.category,
                   primary=value.values.primary, archived=value.values.archived)


class VehiclePage(BaseModel):
    items: list[VehicleOutput]
    next_offset: int | None


class RevisionOutput(BaseModel):
    version: int
    kind: str
    values: VehicleBody


class RevisionPage(BaseModel):
    items: list[RevisionOutput]
    next_offset: int | None


def garage_router(service: GarageService | None, actor: Callable[..., VerifiedActor]) -> APIRouter:
    correlation = {'X-Correlation-ID': {'schema': {'type': 'string', 'pattern': '^[0-9a-f]{32}$'}},
                   'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}}}
    failure: dict[str, Any] = {'description': 'Sanitized Problem Details', 'headers': correlation,
        'content': {'application/problem+json': {'schema': Problem.model_json_schema()}}}
    failures: dict[int | str, dict[str, Any]] = {code: failure for code in (400,401,403,404,408,409,412,413,422,428,429,500,503)}
    router = APIRouter(prefix='/api/v1/me/vehicles', tags=['garage'], responses=failures)

    def success(revision: bool = False, location: bool = False) -> dict[str, Any]:
        headers: dict[str, Any] = dict(correlation)
        if revision: headers['ETag'] = {'schema': {'type': 'string', 'pattern': '^"[1-9][0-9]*"$'}}
        if location: headers['Location'] = {'schema': {'type': 'string'}}
        return {'description': 'Authorized response', 'headers': headers}

    def current() -> GarageService:
        if service is None: raise HTTPException(503)
        return service

    def perform(operation: Callable[[], T]) -> T:
        try: return operation()
        except HiddenVehicle: raise HTTPException(404) from None
        except StaleVehicle: raise HTTPException(412) from None
        except VehicleConflict: raise HTTPException(409) from None

    def provider(acting: VerifiedActor) -> ActorProvider:
        return lambda: acting

    @router.post('', response_model=VehicleOutput, status_code=201, operation_id='createPrivateVehicle',
                 responses={200: {**success(True, True), 'model': VehicleOutput}, 201: success(True, True)})
    def create(body: VehicleBody, acting: Annotated[VerifiedActor, Depends(actor)], response: Response,
               idempotency_key: Annotated[UUID, Header()]) -> VehicleOutput:
        vehicle, created = perform(lambda: current().create(provider(acting), idempotency_key, body.value()))
        response.status_code = 201 if created else 200
        response.headers['ETag'] = f'"{vehicle.version}"'
        response.headers['Location'] = '/api/v1/me/vehicles/' + str(vehicle.id)
        return VehicleOutput.of(vehicle)

    @router.get('', response_model=VehiclePage, operation_id='listPrivateVehicles', responses={200: success()})
    def owned(acting: Annotated[VerifiedActor, Depends(actor)], archived: bool = False,
              limit: int = Query(default=25, ge=1, le=50), offset: int = Query(default=0, ge=0, le=5000)) -> VehiclePage:
        rows = current().owned(provider(acting), archived, limit, offset)
        return VehiclePage(items=[VehicleOutput.of(row) for row in rows[:limit]],
                           next_offset=offset + limit if len(rows) > limit else None)

    @router.get('/{identifier}', response_model=VehicleOutput, operation_id='readPrivateVehicle', responses={200: success(True)})
    def detail(identifier: UUID, acting: Annotated[VerifiedActor, Depends(actor)], response: Response) -> VehicleOutput:
        vehicle = perform(lambda: current().detail(provider(acting), identifier))
        response.headers['ETag'] = f'"{vehicle.version}"'
        return VehicleOutput.of(vehicle)

    @router.put('/{identifier}', response_model=VehicleOutput, operation_id='updatePrivateVehicle', responses={200: success(True)})
    def update(identifier: UUID, body: VehicleBody, acting: Annotated[VerifiedActor, Depends(actor)], response: Response,
               if_match: Annotated[str, Header(pattern='^"[1-9][0-9]{0,9}"$')]) -> VehicleOutput:
        vehicle = perform(lambda: current().update(provider(acting), identifier, body.value(), int(if_match.strip('"'))))
        response.headers['ETag'] = f'"{vehicle.version}"'
        return VehicleOutput.of(vehicle)

    @router.get('/{identifier}/history', response_model=RevisionPage, operation_id='privateVehicleHistory', responses={200: success()})
    def history(identifier: UUID, acting: Annotated[VerifiedActor, Depends(actor)],
                limit: int = Query(default=25, ge=1, le=50), offset: int = Query(default=0, ge=0, le=5000)) -> RevisionPage:
        rows = perform(lambda: current().history(provider(acting), identifier, limit, offset))
        return RevisionPage(items=[RevisionOutput(version=row.version, kind=row.kind,
            values=VehicleBody(brand=row.values.brand, model=row.values.model, year=row.values.year,
                color=row.values.color, category=row.values.category, primary=row.values.primary, archived=row.values.archived))
            for row in rows[:limit]], next_offset=offset + limit if len(rows) > limit else None)

    return router
