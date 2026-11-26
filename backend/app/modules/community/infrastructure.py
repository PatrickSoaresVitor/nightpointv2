import hashlib
from typing import Literal
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from app.platform.database import Database
from .domain import Summary, Comment, HiddenComment, StaleComment, InteractionConflict

COLUMNS = 'id,event_id,actor_id,text,version,removed,removed_by'


def comment_of(row: RowMapping) -> Comment:
    return Comment(row['id'],row['event_id'],row['actor_id'],row['text'],row['version'],row['removed'],row['removed_by'])


class PostgresCommunity:
    def __init__(self, database: Database) -> None:
        self.database = database

    def summary(self, actor: UUID, event_id: UUID) -> Summary:
        with self.database.transaction() as session:
            row = session.execute(text("SELECT count(*) FILTER(WHERE kind='like' AND active) AS likes,"
                "count(*) FILTER(WHERE kind='participation' AND active) AS participants,"
                "coalesce(bool_or(actor_id=:actor AND kind='like' AND active),false) AS liked,"
                "coalesce(bool_or(actor_id=:actor AND kind='participation' AND active),false) AS participating "
                'FROM community.reactions WHERE event_id=:event'), {'actor':actor,'event':event_id}).mappings().one()
            return Summary(row['likes'],row['participants'],row['liked'],row['participating'])

    def reaction(self, actor: UUID, event_id: UUID, kind: Literal['like','participation'], active: bool) -> None:
        with self.database.transaction() as session:
            session.execute(text('INSERT INTO community.reactions(event_id,actor_id,kind,active) VALUES(:event,:actor,:kind,:active) '
                'ON CONFLICT(event_id,actor_id,kind) DO UPDATE SET active=excluded.active,updated_at=now()'),
                {'event':event_id,'actor':actor,'kind':kind,'active':active})

    def comments(self, actor: UUID, event_id: UUID, include_removed: bool, limit: int, offset: int) -> list[Comment]:
        with self.database.transaction() as session:
            rows = session.execute(text(f'SELECT {COLUMNS} FROM community.comments WHERE event_id=:event '
                'AND (NOT removed OR (:include_removed AND removed_by=:actor)) '
                'ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset'),
                {'event':event_id,'actor':actor,'include_removed':include_removed,'limit':limit,'offset':offset}).mappings().all()
            return [comment_of(row) for row in rows]

    def comment(self, actor: UUID, event_id: UUID, identifier: UUID) -> Comment | None:
        with self.database.transaction() as session:
            row = session.execute(text(f'SELECT {COLUMNS} FROM community.comments WHERE event_id=:event AND id=:id '
                'AND (NOT removed OR removed_by=:actor)'), {'event':event_id,'id':identifier,'actor':actor}).mappings().first()
            return comment_of(row) if row is not None else None

    def create_comment(self, actor: UUID, event_id: UUID, key: UUID, content: str, allow_create: bool) -> tuple[Comment,bool]:
        fingerprint = hashlib.sha256(content.encode('utf-8')).hexdigest()
        with self.database.transaction() as session:
            session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                {'key':f'community:{event_id}:{actor}:{key}'})
            receipt = session.execute(text('SELECT fingerprint,comment_id FROM community.creation_requests '
                'WHERE event_id=:event AND actor_id=:actor AND key=:key'),
                {'event':event_id,'actor':actor,'key':key}).mappings().first()
            if receipt is not None:
                if receipt['fingerprint'] != fingerprint: raise InteractionConflict()
                row = session.execute(text(f'SELECT {COLUMNS} FROM community.comments WHERE id=:id AND event_id=:event AND actor_id=:actor'),
                    {'id':receipt['comment_id'],'event':event_id,'actor':actor}).mappings().one()
                return comment_of(row),False
            if not allow_create: raise InteractionConflict()
            identifier = uuid4()
            row = session.execute(text(f'INSERT INTO community.comments(id,event_id,actor_id,text) '
                f'VALUES(:id,:event,:actor,:text) RETURNING {COLUMNS}'),
                {'id':identifier,'event':event_id,'actor':actor,'text':content}).mappings().one()
            session.execute(text('INSERT INTO community.creation_requests(event_id,actor_id,key,fingerprint,comment_id) '
                'VALUES(:event,:actor,:key,:fingerprint,:id)'),
                {'event':event_id,'actor':actor,'key':key,'fingerprint':fingerprint,'id':identifier})
            return comment_of(row),True

    def visibility(self, actor: UUID, organizer: UUID, event_id: UUID, identifier: UUID, removed: bool, version: int) -> Comment:
        with self.database.transaction() as session:
            row = session.execute(text(f'SELECT {COLUMNS} FROM community.comments WHERE id=:id AND event_id=:event FOR UPDATE'),
                {'id':identifier,'event':event_id}).mappings().first()
            if row is None: raise HiddenComment()
            previous = comment_of(row)
            if (previous.removed and previous.removed_by != actor or
                not previous.removed and actor not in {previous.actor_id,organizer}): raise HiddenComment()
            if previous.version != version: raise StaleComment()
            if previous.removed == removed: return previous
            changed = session.execute(text(f'UPDATE community.comments SET removed=:removed,removed_by=:actor,'
                f'version=version+1,updated_at=now() WHERE id=:id AND event_id=:event RETURNING {COLUMNS}'),
                {'removed':removed,'actor':actor if removed else None,'id':identifier,'event':event_id}).mappings().one()
            return comment_of(changed)
