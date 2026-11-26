import json
from typing import cast
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.engine import RowMapping
from app.platform.database import Database
from .domain import Vehicle, VehicleInput, VehicleRevision, HiddenVehicle, StaleVehicle, VehicleConflict

FIELDS = 'id,owner_id,brand,model,year,color,category,is_primary,archived,version'


def vehicle_of(row: RowMapping) -> Vehicle:
    return Vehicle(row['id'], row['owner_id'], VehicleInput(row['brand'], row['model'], row['year'],
                   row['color'], row['category'], row['is_primary'], row['archived']), row['version'])


class PostgresGarage:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _lock(session: Session, actor: UUID) -> None:
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,0))"), {'owner': 'garage:' + str(actor)})

    @staticmethod
    def _record(session: Session, vehicle: Vehicle, kind: str) -> None:
        session.execute(text('INSERT INTO garage.vehicle_revisions(vehicle_id,version,kind,snapshot) '
                             'VALUES(:id,:version,:kind,CAST(:snapshot AS jsonb))'),
                        {'id': vehicle.id, 'version': vehicle.version, 'kind': kind,
                         'snapshot': json.dumps(vehicle.values.canonical())})

    def _prepare(self, session: Session, actor: UUID, values: VehicleInput, previous: Vehicle | None) -> None:
        if not values.archived and (previous is None or previous.values.archived):
            count = session.scalar(text('SELECT count(*) FROM garage.vehicles WHERE owner_id=:actor AND NOT archived'), {'actor': actor})
            if cast(int, count) >= 50: raise VehicleConflict()
        if values.primary:
            rows = session.execute(text(f'UPDATE garage.vehicles SET is_primary=false,version=version+1,updated_at=now() '
                                        f'WHERE owner_id=:actor AND is_primary AND id<>:id RETURNING {FIELDS}'),
                                   {'actor': actor, 'id': previous.id if previous else uuid4()}).mappings().all()
            for row in rows: self._record(session, vehicle_of(row), 'primary_replaced')

    def create(self, actor: UUID, key: UUID, values: VehicleInput) -> tuple[Vehicle, bool]:
        if values.archived: raise VehicleConflict()
        with self.database.transaction() as session:
            self._lock(session, actor)
            receipt = session.execute(text('SELECT fingerprint,vehicle_id FROM garage.creation_requests '
                                           'WHERE owner_id=:actor AND key=:key'), {'actor': actor, 'key': key}).mappings().first()
            if receipt is not None:
                if receipt['fingerprint'] != values.fingerprint(): raise VehicleConflict()
                row = session.execute(text(f'SELECT {FIELDS} FROM garage.vehicles WHERE id=:id AND owner_id=:actor'),
                                      {'id': receipt['vehicle_id'], 'actor': actor}).mappings().one()
                return vehicle_of(row), False
            self._prepare(session, actor, values, None)
            identifier = uuid4()
            parameters = {**values.canonical(), 'id': identifier, 'actor': actor}
            row = session.execute(text(f'INSERT INTO garage.vehicles(id,owner_id,brand,model,year,color,category,is_primary) '
                                      f'VALUES(:id,:actor,:brand,:model,:year,:color,:category,:primary) RETURNING {FIELDS}'), parameters).mappings().one()
            session.execute(text('INSERT INTO garage.creation_requests(owner_id,key,fingerprint,vehicle_id) '
                                 'VALUES(:actor,:key,:fingerprint,:id)'),
                            {'actor': actor, 'key': key, 'fingerprint': values.fingerprint(), 'id': identifier})
            vehicle = vehicle_of(row)
            self._record(session, vehicle, 'created')
            return vehicle, True

    def detail(self, actor: UUID, identifier: UUID) -> Vehicle | None:
        with self.database.transaction() as session:
            row = session.execute(text(f'SELECT {FIELDS} FROM garage.vehicles WHERE id=:id AND owner_id=:actor'),
                                  {'id': identifier, 'actor': actor}).mappings().first()
            return vehicle_of(row) if row else None

    def update(self, actor: UUID, identifier: UUID, values: VehicleInput, version: int) -> Vehicle:
        with self.database.transaction() as session:
            self._lock(session, actor)
            row = session.execute(text(f'SELECT {FIELDS} FROM garage.vehicles WHERE id=:id AND owner_id=:actor FOR UPDATE'),
                                  {'id': identifier, 'actor': actor}).mappings().first()
            if row is None: raise HiddenVehicle()
            previous = vehicle_of(row)
            if previous.version != version: raise StaleVehicle()
            self._prepare(session, actor, values, previous)
            changed = session.execute(text(f'UPDATE garage.vehicles SET brand=:brand,model=:model,year=:year,color=:color,'
                                          f'category=:category,is_primary=:primary,archived=:archived,version=version+1,updated_at=now() '
                                          f'WHERE id=:id AND owner_id=:actor RETURNING {FIELDS}'),
                                      {**values.canonical(), 'id': identifier, 'actor': actor}).mappings().one()
            vehicle = vehicle_of(changed)
            self._record(session, vehicle, 'archived' if values.archived else 'updated')
            return vehicle

    def owned(self, actor: UUID, archived: bool, limit: int, offset: int) -> list[Vehicle]:
        with self.database.transaction() as session:
            rows = session.execute(text(f'SELECT {FIELDS} FROM garage.vehicles WHERE owner_id=:actor AND archived=:archived '
                                        'ORDER BY is_primary DESC,created_at DESC,id DESC LIMIT :limit OFFSET :offset'),
                                   {'actor': actor, 'archived': archived, 'limit': limit, 'offset': offset}).mappings().all()
            return [vehicle_of(row) for row in rows]

    def history(self, actor: UUID, identifier: UUID, limit: int, offset: int) -> list[VehicleRevision]:
        with self.database.transaction() as session:
            exists = session.scalar(text('SELECT id FROM garage.vehicles WHERE id=:id AND owner_id=:actor'), {'id': identifier, 'actor': actor})
            if exists is None: raise HiddenVehicle()
            rows = session.execute(text('SELECT version,kind,snapshot FROM garage.vehicle_revisions WHERE vehicle_id=:id '
                                        'ORDER BY version DESC LIMIT :limit OFFSET :offset'),
                                   {'id': identifier, 'limit': limit, 'offset': offset}).mappings().all()
            return [VehicleRevision(row['version'], row['kind'], VehicleInput(**row['snapshot'])) for row in rows]
