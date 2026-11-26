import hashlib
import json
from contextlib import contextmanager
from collections.abc import Generator
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from app.platform.database import Database
from app.platform.telemetry import METRICS, measure
from .domain import Event, EventInput, IdempotencyConflict, HiddenEvent, StaleEvent, EventStateConflict
from .api import SearchSpec, EventSummary

EVENT_COLUMNS = "id,organizer_id,title,category_code,starts_at,timezone,location_label,ST_X(location::geometry) AS longitude,ST_Y(location::geometry) AS latitude,description,version,state,visibility"
NEARBY_SQL = """SELECT id,title,category_code,starts_at,location_label,version,distance_mm FROM (
 SELECT id,title,category_code,starts_at,location_label,version,
 round(ST_Distance(location,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography)*1000)::bigint AS distance_mm
 FROM events.events WHERE state='published' AND visibility='listed'
 AND starts_at>=:from_ts AND starts_at<:until_ts AND created_at<=:snapshot AND updated_at<=:snapshot
 AND ST_DWithin(location,ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography,:radius)
 {category}
) ranked {after} ORDER BY distance_mm,id LIMIT :limit"""


def event_of(row: RowMapping) -> Event:
    return Event(row["id"],row["organizer_id"],EventInput(row["title"],row["category_code"],
        row["starts_at"].astimezone(ZoneInfo(row["timezone"])),row["timezone"],row["location_label"],row["longitude"],row["latitude"],row["description"],row["visibility"]),row["version"],row["state"])



class PostgresEvents:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def guard(self, actor: UUID, identifier: UUID) -> Generator[Event]:
        # Same authorization as detail; the shared lock holds the policy stable
        # while a child module commits its own data through its own repository.
        with self.database.transaction() as session:
            row = session.execute(text(f'SELECT {EVENT_COLUMNS} FROM events.events WHERE id=:id AND '
                "((state='published' AND visibility='listed') OR (organizer_id=:actor AND visibility IN ('listed','owner_only'))) FOR SHARE"),
                {'id': identifier, 'actor': actor}).mappings().first()
            if row is None: raise HiddenEvent()
            yield event_of(row)

    def create(self, actor: UUID, key: UUID, values: EventInput) -> tuple[Event,bool]:
        fingerprint = hashlib.sha256(json.dumps(values.canonical(),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        with self.database.transaction() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:lock,0))"),{"lock":f"{actor}:events.create.v1:{key}"})
            previous = session.execute(text("SELECT fingerprint,event_id FROM events.creation_requests WHERE actor_id=:actor AND operation='events.create.v1' AND key=:key"),{"actor":actor,"key":key}).mappings().first()
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    raise IdempotencyConflict()
                return event_of(session.execute(text(f"SELECT {EVENT_COLUMNS} FROM events.events WHERE id=:id"),{"id":previous["event_id"]}).mappings().one()),False
            identifier = uuid4()
            parameters = {**values.canonical(),"visibility":values.visibility,"id":identifier,"actor":actor,"starts_at":values.starts_at}
            row = session.execute(text("INSERT INTO events.events(id,organizer_id,title,category_code,starts_at,timezone,location_label,location,description,visibility) "
                "VALUES(:id,:actor,:title,:category_code,:starts_at,:timezone,:location_label,ST_SetSRID(ST_MakePoint(:longitude,:latitude),4326)::geography,:description,:visibility) "
                f"RETURNING {EVENT_COLUMNS}"),parameters).mappings().one()
            session.execute(text("INSERT INTO events.creation_requests(actor_id,operation,key,fingerprint,event_id) VALUES(:actor,'events.create.v1',:key,:fingerprint,:id)"),
                {"actor":actor,"key":key,"fingerprint":fingerprint,"id":identifier})
            event = event_of(row)
        return event,True

    def detail(self, identifier: UUID, actor: UUID | None = None) -> Event | None:
        with self.database.transaction() as session:
            row = session.execute(text(f"SELECT {EVENT_COLUMNS} FROM events.events WHERE id=:id AND "
                "((state='published' AND visibility='listed') OR "
                "(organizer_id=:actor AND visibility IN ('listed','owner_only')))"),{"id":identifier,"actor":actor}).mappings().first()
            return event_of(row) if row is not None else None

    def owned(self, actor: UUID, limit: int, offset: int) -> list[Event]:
        with self.database.transaction() as session:
            rows = session.execute(text(f"SELECT {EVENT_COLUMNS} FROM events.events WHERE organizer_id=:actor "
                "AND visibility IN ('listed','owner_only') "
                "ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"),
                {"actor":actor,"limit":limit,"offset":offset}).mappings().all()
            return [event_of(row) for row in rows]

    def update(self, actor: UUID, identifier: UUID, values: EventInput | None, version: int) -> Event:
        with self.database.transaction() as session:
            previous = session.execute(text("SELECT version,state FROM events.events "
                "WHERE id=:id AND organizer_id=:actor FOR UPDATE"),{"id":identifier,"actor":actor}).mappings().first()
            if previous is None:raise HiddenEvent()
            if previous["version"] != version:raise StaleEvent()
            if previous["state"] != "published":raise EventStateConflict()
            parameters: dict[str,object] = {"id":identifier,"actor":actor}
            if values is None:
                assignments = "state='cancelled'"
            else:
                parameters.update({**values.canonical(),"visibility":values.visibility,"starts_at":values.starts_at})
                assignments = ("title=:title,category_code=:category_code,starts_at=:starts_at,timezone=:timezone,"
                    "location_label=:location_label,location=ST_SetSRID(ST_MakePoint(:longitude,:latitude),4326)::geography,"
                    "description=:description,visibility=:visibility")
            row = session.execute(text(f"UPDATE events.events SET {assignments},version=version+1,updated_at=now() "
                f"WHERE id=:id AND organizer_id=:actor RETURNING {EVENT_COLUMNS}"),parameters).mappings().one()
            return event_of(row)

    def nearby(self, search: SearchSpec, limit: int) -> list[EventSummary]:
        sql,parameters = nearby_statement(search,limit)
        with self.database.transaction() as session:
            with measure("events.sql"):
                result = session.execute(text(sql),parameters)
            with measure("events.fetch"):
                rows = result.mappings().all()
            METRICS.gauge("events.rows", len(rows))
            with measure("events.project"):
                return [EventSummary(row["id"],row["title"],row["category_code"],row["starts_at"],row["location_label"],row["distance_mm"],row["version"]) for row in rows]


def nearby_statement(search: SearchSpec, limit: int) -> tuple[str,dict[str,object]]:
    sql = NEARBY_SQL.format(category="AND category_code=:category" if search.category_code is not None else "",
        after="WHERE (distance_mm,id) > (:after_mm,:after_id)" if search.after_mm is not None else "")
    return sql,{"lon":search.longitude,"lat":search.latitude,"radius":search.radius_m,"from_ts":search.from_ts,
        "until_ts":search.until_ts,"category":search.category_code,"snapshot":search.snapshot,
        "after_mm":search.after_mm,"after_id":search.after_id,"limit":limit}
