from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..resp import Error, RESPValue
from ..store import Store

Handler = Callable[[Store, tuple[bytes, ...]], RESPValue]


class CommandError(Exception):
    def __init__(self, message: bytes) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True, slots=True)
class Command:
    handler: Handler
    minimum: int
    maximum: int | None = None
    closes_connection: bool = False


class Registry:
    def __init__(self) -> None:
        self._commands: dict[bytes, Command] = {}

    def add(self, name: bytes, handler: Handler, minimum: int,
            maximum: int | None = None, *, closes_connection: bool = False) -> None:
        self._commands[name] = Command(handler, minimum, maximum, closes_connection)

    def execute(self, store: Store, request: tuple[bytes, ...]) -> tuple[RESPValue, bool]:
        name = request[0].lower()
        command = self._commands.get(name)
        if command is None:
            # RESP error lines cannot contain unescaped CR or LF.
            safe_name = name.replace(b"\r", b"?").replace(b"\n", b"?")
            return Error(b"ERR unknown command '" + safe_name + b"'"), False
        args = request[1:]
        if len(args) < command.minimum or (command.maximum is not None and len(args) > command.maximum):
            return Error(b"ERR wrong number of arguments for '" + name + b"' command"), False
        try:
            return command.handler(store, args), command.closes_connection
        except CommandError as exc:
            return Error(exc.message), False


def create_registry() -> Registry:
    from . import keys, server, strings

    registry = Registry()
    server.register(registry)
    strings.register(registry)
    keys.register(registry)
    return registry
