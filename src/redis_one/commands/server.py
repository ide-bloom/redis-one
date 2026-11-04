from ..resp import Array, BulkString, Error, RESPValue, SimpleString
from ..store import Store
from . import Registry


def ping(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return BulkString(args[0]) if args else SimpleString(b"PONG")


def echo(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return BulkString(args[0])


def quit_client(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return SimpleString(b"OK")


def command(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    if not args:
        return Array(())
    if len(args) == 1 and args[0].lower() == b"count":
        return 0
    return Error(b"ERR unknown subcommand or wrong number of arguments for 'command'")


def register(registry: Registry) -> None:
    registry.add(b"ping", ping, 0, 1)
    registry.add(b"echo", echo, 1, 1)
    registry.add(b"quit", quit_client, 0, 0, closes_connection=True)
    registry.add(b"command", command, 0)
