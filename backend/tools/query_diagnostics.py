"""Read-only SQL experiments on an already attested synthetic connection."""
from datetime import datetime
import re
import time
from app.platform.config import load_settings
from typing import Any
from sqlalchemy import text
from app.modules.events.api import SearchSpec
from app.modules.events.infrastructure import nearby_statement
from app.platform.database import Database


def prepared_plan_comparison(database: Database, search: SearchSpec) -> list[dict[str, Any]]:
    statement, parameters=nearby_statement(search,26)
    order: list[str]=[]
    def bind(match: re.Match[str]) -> str:
        name=match.group(1)
        if name not in order:order.append(name)
        return "$"+str(order.index(name)+1)
    sql=re.sub(r"(?<!:):([a-z_]+)",bind,statement)
    types={"lon":"double precision","lat":"double precision","radius":"double precision",
           "from_ts":"timestamptz","until_ts":"timestamptz","snapshot":"timestamptz","limit":"integer"}
    def literal(value: object) -> str:
        if isinstance(value,datetime):return "'"+value.isoformat()+"'::timestamptz"
        if isinstance(value,(int,float)) and not isinstance(value,bool):return str(value)
        raise ValueError("Only fixed synthetic numeric/time parameters allowed")
    arguments=",".join(literal(parameters[key]) for key in order)
    results: list[dict[str,Any]]=[]
    with database.transaction() as session:
        session.execute(text("PREPARE np_performance_probe("+",".join(types[k] for k in order)+") AS "+sql))
        try:
            for mode,jit in (("force_custom_plan","on"),("force_generic_plan","on"),
                             ("force_generic_plan","off"),("force_custom_plan","off")):
                # Settings are transaction-local; never alter host/DB defaults or other connections.
                session.execute(text("SET LOCAL plan_cache_mode="+mode))
                session.execute(text("SET LOCAL jit="+jit))
                for repeat in range(2):
                    result=session.execute(text("EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) EXECUTE np_performance_probe("+arguments+")")).scalar_one()
                    results.append({"plan_cache_mode":mode,"jit":jit,"repeat":repeat,"plan":result})
        finally:session.execute(text("DEALLOCATE np_performance_probe"))
    return results


def fresh_connection_comparison(search: SearchSpec) -> list[dict[str,Any]]:
    sql,parameters=nearby_statement(search,26)
    results: list[dict[str,Any]]=[]
    reference: list[object] | None=None
    for iteration in range(3):
        database=Database(load_settings())
        try:
            for repeat in range(3):
                with database.transaction() as session:
                    started=time.monotonic()
                    rows=session.execute(text(sql),parameters).mappings().all()
                    elapsed=(time.monotonic()-started)*1000
                ids=[row["id"] for row in rows]
                if reference is None:reference=ids
                assert ids==reference
                results.append({"connection_generation":iteration,"repeat":repeat,"rows":len(rows),
                                "sql_ms":elapsed,"same_order":True,"database":database.diagnostics()})
        finally:database.close()
    return results
