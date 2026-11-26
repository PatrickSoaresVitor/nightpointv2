from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import uuid4
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from app.bootstrap import create_app
from app.modules.garage.domain import VehicleInput
from app.modules.garage.infrastructure import PostgresGarage
from app.modules.garage.presentation import VehicleBody
from app.modules.identity.domain import ExternalIdentity
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.platform.database import Database
from app.platform.test_guard import require_disposable
from tests.identity_fakes import FakeVerifier
from tests.test_database import engines as engines
from tests.test_events import event_store as event_store
from tests.test_identity_http import headers


@pytest.mark.parametrize('values', [
    {'brand': ' '}, {'model': 'x\x00'}, {'color': '\n'}, {'year': True},
    {'year': 1899}, {'year': 2101}, {'category': 'invalid'},
    {'primary': True, 'archived': True}, {'owner_id': str(uuid4())},
])
def test_invalid_vehicle_input(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError): VehicleBody.model_validate({'brand': 'Synthetic', 'model': 'Demo', **values})


def test_vehicle_fingerprint_includes_all_mutable_fields() -> None:
    first = VehicleInput('Synthetic', 'Demo')
    assert first.fingerprint() == VehicleInput('Synthetic', 'Demo').fingerprint()
    assert first.fingerprint() != VehicleInput('Synthetic', 'Demo', primary=True).fingerprint()
    assert first.fingerprint() != VehicleInput('Synthetic', 'Demo', archived=True).fingerprint()


@pytest.fixture
def garage_store(event_store: tuple[Engine, Database, PostgresIdentityRepository]) -> Iterator[tuple[Engine, Database, PostgresIdentityRepository]]:
    migrator, _, _ = event_store
    try: yield event_store
    finally:
        with migrator.begin() as conn:
            require_disposable(conn)
            for table in ('vehicle_revisions', 'creation_requests', 'vehicles'):
                conn.execute(text(f'DELETE FROM garage.{table}'))


@pytest.mark.integration
def test_private_garage_replay_archive_restore_versions_and_history(garage_store: tuple[Engine, Database, PostgresIdentityRepository]) -> None:
    migrator, runtime, identities = garage_store
    with TestClient(create_app(identity_test=(FakeVerifier(), identities))) as transport:
        client = cast(httpx.Client, transport)
        base = '/api/v1/me/vehicles'
        create_headers = {**headers(), 'Idempotency-Key': str(uuid4())}
        values = {'brand': 'Synthetic', 'model': 'Demo', 'year': 2020, 'primary': True}
        created = client.post(base, headers=create_headers, json=values)
        assert created.status_code == 201
        path = created.headers['location']
        assert created.headers['etag'] == '"1"'
        assert client.post(base, headers=create_headers, json=values).json() == created.json()
        assert client.post(base, headers=create_headers, json={**values, 'model': 'Changed'}).status_code == 409
        assert client.get(base, headers=headers('actor-b')).json()['items'] == []
        assert client.get(path, headers=headers('actor-b')).status_code == 404
        assert client.get(path + '/history', headers=headers('actor-b')).status_code == 404
        assert client.put(path, headers={**headers('actor-b'), 'If-Match': '"1"'}, json=values).status_code == 404
        assert client.put(path, headers=headers(), json=values).status_code == 428
        archived = client.put(path, headers={**headers(), 'If-Match': '"1"'}, json={**values, 'primary': False, 'archived': True})
        assert archived.status_code == 200 and archived.json()['version'] == 2
        assert client.get(base, headers=headers()).json()['items'] == []
        assert len(client.get(base + '?archived=true', headers=headers()).json()['items']) == 1
        assert client.put(path, headers={**headers(), 'If-Match': '"1"'}, json=values).status_code == 412
        restored = client.put(path, headers={**headers(), 'If-Match': '"2"'}, json=values)
        assert restored.status_code == 200 and restored.json()['version'] == 3
        replay = client.post(base, headers=create_headers, json=values)
        assert replay.status_code == 200 and replay.json() == restored.json()
        revisions = client.get(path + '/history?limit=2', headers=headers()).json()
        assert [row['version'] for row in revisions['items']] == [3, 2] and revisions['next_offset'] == 2
        assert client.get(base + '?limit=51', headers=headers()).status_code == 422
        assert client.get(base).status_code == 401
        with migrator.connect() as conn:
            assert conn.scalar(text('SELECT count(*) FROM garage.vehicles')) == 1
    assert runtime.ready()


@pytest.mark.integration
def test_principal_concurrency_is_serialized_and_history_records_displacement(garage_store: tuple[Engine, Database, PostgresIdentityRepository]) -> None:
    migrator, runtime, identities = garage_store
    actor = identities.resolve(ExternalIdentity('synthetic-issuer', 'actor-a'))
    assert actor is not None
    repository = PostgresGarage(runtime)
    def create(index: int) -> str:
        vehicle, created = repository.create(actor, uuid4(), VehicleInput('Synthetic', f'Demo{index}', primary=True))
        assert created
        return str(vehicle.id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        identifiers = list(executor.map(create, range(2)))
    with migrator.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM garage.vehicles WHERE is_primary AND NOT archived')) == 1
        assert conn.scalar(text('SELECT count(*) FROM garage.vehicles')) == 2
        assert conn.scalar(text("SELECT count(*) FROM garage.vehicle_revisions WHERE kind='primary_replaced'")) == 1
    assert len(set(identifiers)) == 2


@pytest.mark.integration
def test_garage_runtime_cannot_delete_change_owner_or_rewrite_history(garage_store: tuple[Engine, Database, PostgresIdentityRepository]) -> None:
    _, runtime, identities = garage_store
    actor = identities.resolve(ExternalIdentity('synthetic-issuer', 'actor-a'))
    assert actor is not None
    PostgresGarage(runtime).create(actor, uuid4(), VehicleInput('Synthetic', 'Demo'))
    for statement in ('DELETE FROM garage.vehicles', 'UPDATE garage.vehicles SET owner_id=owner_id',
                      "UPDATE garage.vehicle_revisions SET kind='updated'", 'DELETE FROM garage.creation_requests',
                      'CREATE TABLE garage.unauthorized(id integer)'):
        with pytest.raises(DBAPIError) as error:
            with runtime.transaction() as session: session.execute(text(statement))
        assert getattr(error.value.orig, 'sqlstate', None) == '42501'
