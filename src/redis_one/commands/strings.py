from __future__ import annotations

import time

from ..resp import Array, BulkString, RESPValue, SimpleString
from ..store import Store
from . import CommandError, Registry

INTEGER_ERROR = b"ERR value is not an integer or out of range"
OVERFLOW_ERROR = b"ERR increment or decrement would overflow"
SYNTAX_ERROR = b"ERR syntax error"
MIN_INT = -(2**63)
MAX_INT = 2**63 - 1


def _integer(value: bytes) -> int:
    negative = value.startswith(b"-")
    digits = value[1:] if negative else value
    # Redis rejects plus signs, leading zeroes, and negative zero.
    if (not digits or not digits.isdigit() or len(digits) > 19
            or (len(digits) > 1 and digits.startswith(b"0"))
            or (negative and digits == b"0")):
        raise CommandError(INTEGER_ERROR)
    result = int(value)
    if result < MIN_INT or result > MAX_INT:
        raise CommandError(INTEGER_ERROR)
    return result


def _set_options(args: tuple[bytes, ...]) -> tuple[bool, bool, int | None]:
    nx = xx = False
    ttl_value: bytes | None = None
    ttl_kind: bytes | None = None
    i = 0
    while i < len(args):
        option = args[i].lower()
        if option == b"nx" and not xx:
            nx = True
        elif option == b"xx" and not nx:
            xx = True
        elif option in (b"ex", b"px") and ttl_kind in (None, option) and i + 1 < len(args):
            # Redis accepts repeated identical expiry options; the last wins.
            ttl_kind = option
            ttl_value = args[i + 1]
            i += 1
        else:
            raise CommandError(SYNTAX_ERROR)
        i += 1
    ttl_ms: int | None = None
    if ttl_value is not None:
        duration = _integer(ttl_value)
        ttl_ms = duration * (1000 if ttl_kind == b"ex" else 1)
        # Redis stores expiration as a signed 64-bit absolute millisecond time.
        if duration <= 0 or ttl_ms > MAX_INT - int(time.time() * 1000):
            raise CommandError(b"ERR invalid expire time in 'set' command")
    return nx, xx, ttl_ms


def set_string(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    nx, xx, ttl_ms = _set_options(args[2:])
    exists = store.get(args[0]) is not None
    if (nx and exists) or (xx and not exists):
        return BulkString(None)
    store.set(args[0], args[1], ttl_ms=ttl_ms)
    return SimpleString(b"OK")


def get(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return BulkString(store.get(args[0]))


def getset(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    previous = store.get(args[0])
    store.set(args[0], args[1])
    return BulkString(previous)


def mset(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    if len(args) % 2:
        raise CommandError(b"ERR wrong number of arguments for 'mset' command")
    for i in range(0, len(args), 2):
        store.set(args[i], args[i + 1])
    return SimpleString(b"OK")


def mget(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return Array(tuple(BulkString(store.get(key)) for key in args))


def append(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    value = (store.get(args[0]) or b"") + args[1]
    store.set(args[0], value, keep_ttl=True)
    return len(value)


def strlen(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return len(store.get(args[0]) or b"")


def _adjust(store: Store, key: bytes, delta: int) -> int:
    original = store.get(key)
    value = 0 if original is None else _integer(original)
    result = value + delta
    if result < MIN_INT or result > MAX_INT:
        raise CommandError(OVERFLOW_ERROR)
    store.set(key, str(result).encode("ascii"), keep_ttl=True)
    return result


def incr(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return _adjust(store, args[0], 1)


def decr(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return _adjust(store, args[0], -1)


def incrby(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return _adjust(store, args[0], _integer(args[1]))


def decrby(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    decrement = _integer(args[1])
    if decrement == MIN_INT:
        raise CommandError(b"ERR decrement would overflow")
    return _adjust(store, args[0], -decrement)


def register(registry: Registry) -> None:
    registry.add(b"set", set_string, 2)
    registry.add(b"get", get, 1, 1)
    registry.add(b"getset", getset, 2, 2)
    registry.add(b"mset", mset, 2)
    registry.add(b"mget", mget, 1)
    registry.add(b"append", append, 2, 2)
    registry.add(b"strlen", strlen, 1, 1)
    registry.add(b"incr", incr, 1, 1)
    registry.add(b"decr", decr, 1, 1)
    registry.add(b"incrby", incrby, 2, 2)
    registry.add(b"decrby", decrby, 2, 2)
