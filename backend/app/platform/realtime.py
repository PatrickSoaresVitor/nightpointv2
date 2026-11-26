"""Bounded single-process invalidation delivery; REST is authoritative."""
from dataclasses import dataclass, field
from queue import Queue, Empty, Full
from threading import Lock
from uuid import UUID


class ConnectionLimit(Exception): pass


@dataclass(frozen=True)
class Change:
    version: int
    kind: str = "changed"


@dataclass(eq=False)
class Subscription:
    event_id: UUID
    actor_id: UUID
    version: int
    messages: Queue[Change] = field(default_factory=lambda:Queue[Change](maxsize=8))
    closed: bool = False


class EventBus:
    def __init__(self,total: int=32,per_actor: int=2) -> None:
        self.total,self.per_actor=total,per_actor
        self._subscriptions: list[Subscription]=[]
        self._lock=Lock()
        self._closed=False

    @property
    def active(self) -> int:
        with self._lock:return len(self._subscriptions)

    def subscribe(self,event_id: UUID,actor_id: UUID,version: int) -> Subscription:
        with self._lock:
            if self._closed or len(self._subscriptions)>=self.total or sum(s.actor_id==actor_id for s in self._subscriptions)>=self.per_actor:
                raise ConnectionLimit()
            subscription=Subscription(event_id,actor_id,version)
            self._subscriptions.append(subscription)
            return subscription

    def unsubscribe(self,subscription: Subscription) -> None:
        with self._lock:
            subscription.closed=True
            if subscription in self._subscriptions:self._subscriptions.remove(subscription)

    def publish(self,identifier: UUID,version: int) -> None:
        with self._lock:
            for subscription in self._subscriptions:
                if subscription.closed or subscription.event_id!=identifier or version<=subscription.version:continue
                subscription.version=version
                try:subscription.messages.put_nowait(Change(version))
                except Full:
                    while True:
                        try:subscription.messages.get_nowait()
                        except Empty:break
                    subscription.messages.put_nowait(Change(version,"resync"))

    def invalidate(self,identifier: UUID) -> None:
        # A child resource changed; event version and data ownership stay intact.
        with self._lock:
            for subscription in self._subscriptions:
                if subscription.closed or subscription.event_id != identifier: continue
                try: subscription.messages.put_nowait(Change(subscription.version,'resync'))
                except Full:
                    while True:
                        try: subscription.messages.get_nowait()
                        except Empty: break
                    subscription.messages.put_nowait(Change(subscription.version,'resync'))

    def close(self) -> None:
        with self._lock:
            self._closed=True
            for subscription in self._subscriptions:subscription.closed=True
            self._subscriptions.clear()
