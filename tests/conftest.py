from collections.abc import Callable

import pytest

from redis_one.commands import create_registry
from redis_one.resp import RESPValue
from redis_one.store import Store


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Engine:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.store = Store(clock)
        self.registry = create_registry()

    def run(self, *request: bytes) -> RESPValue:
        return self.registry.execute(self.store, request)[0]


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(clock: Clock) -> Engine:
    return Engine(clock)
