"""Synthetic benchmark support: bounded resource sampling and exact timing summaries."""
from collections import Counter
from collections.abc import Callable
import math
from pathlib import Path
from threading import Event, Thread
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine


def timings(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    def at(percent: float) -> float:
        return ordered[max(0, math.ceil(len(ordered)*percent)-1)] if ordered else 0.
    return {"count":len(values),"p50_ms":at(.5),"p95_ms":at(.95),"p99_ms":at(.99),
            "mean_ms":sum(values)/len(values) if values else 0.,"max_ms":ordered[-1] if ordered else 0.}


def resource_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("cpu.stat","cpu.max","memory.current","memory.max","memory.events","io.stat",
                 "cpu.pressure","memory.pressure","io.pressure"):
        file=Path("/sys/fs/cgroup")/name
        try:
            result[name]=file.read_text(encoding="utf-8")[:4096]
        except OSError:
            result[name]="unavailable"
    for name in ("cpu","memory","io"):
        try:result["host_pressure_"+name]=Path("/proc/pressure",name).read_text(encoding="utf-8")[:1024]
        except OSError:result["host_pressure_"+name]="unavailable"
    try:
        memory=Path("/proc/meminfo").read_text(encoding="utf-8")
        result["host_memory_kib"]={line.split(":")[0]:int(line.split()[1]) for line in memory.splitlines()
                                  if line.startswith(("MemTotal:","MemAvailable:","SwapTotal:","SwapFree:"))}
    except (OSError,ValueError):result["host_memory_kib"]={}
    return result


class Sampler:
    def __init__(self, migrator: Engine, pools: Callable[[],dict[str, Any]]) -> None:
        self.engine=migrator
        self.pools=pools
        self.stop=Event()
        self.samples: list[dict[str,Any]]=[]
        self.errors=0
        self.thread=Thread(target=self.run,daemon=True)

    def run(self) -> None:
        started=time.monotonic()
        while not self.stop.is_set():
            item: dict[str,Any]={"elapsed_seconds":time.monotonic()-started,"resources":resource_snapshot(),"pools":self.pools()}
            if len(self.samples)%5==0:
                try:
                    # Attested migrator connection, read-only aggregate. No PID/user/query/addresses.
                    with self.engine.connect() as conn:
                        rows=conn.execute(text("SELECT COALESCE(state,'unavailable'),COALESCE(wait_event_type,'none'),count(*) "
                            "FROM pg_stat_activity WHERE datname=current_database() GROUP BY 1,2")).all()
                        item["postgres_activity"]=[{"state":r[0],"wait_type":r[1],"count":r[2]} for r in rows]
                        row=conn.execute(text("SELECT numbackends,xact_commit,xact_rollback,blks_read,blks_hit,temp_bytes,deadlocks "
                                              "FROM pg_stat_database WHERE datname=current_database()")).mappings().one()
                        item["postgres_database"]=dict(row)
                except Exception:
                    self.errors+=1
            self.samples.append(item)
            if self.stop.wait(1):break

    def close(self) -> None:
        self.stop.set()
        self.thread.join(8)
        if self.thread.is_alive():raise RuntimeError("Resource sampler did not stop")

    def summary(self) -> dict[str,Any]:
        return {"samples":self.samples,"errors":self.errors,"interval_seconds":1,
                "postgres_interval_seconds":5,"postgres_other_role_details":"may be unavailable by grants"}


def counts_consistent(counts: Counter[str], statuses: dict[int,int]) -> bool:
    return (counts["started"]==counts["completed"]+counts["timeouts"]+counts["http_errors"]+counts["aborted"]
            and counts["completed"]==sum(statuses.values())
            and counts["pending"]==0)
