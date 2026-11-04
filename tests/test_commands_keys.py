import pytest

from conftest import Clock, Engine
from redis_one.resp import Array, BulkString, Error, SimpleString


def test_keyspace_counts_rename_and_flush(engine: Engine) -> None:
    engine.run(b"MSET", b"a", b"A", b"b", b"B")
    assert engine.run(b"EXISTS", b"a", b"a", b"missing") == 2
    assert engine.run(b"TYPE", b"a") == SimpleString(b"string")
    assert engine.run(b"TYPE", b"missing") == SimpleString(b"none")
    assert engine.run(b"RENAME", b"a", b"a") == SimpleString(b"OK")
    assert engine.run(b"RENAME", b"a", b"b") == SimpleString(b"OK")
    assert engine.run(b"GET", b"b") == BulkString(b"A")
    assert engine.run(b"RENAME", b"missing", b"b") == Error(b"ERR no such key")
    assert engine.run(b"DBSIZE") == 1
    assert engine.run(b"DEL", b"b", b"b", b"missing") == 1
    assert engine.run(b"FLUSHALL") == SimpleString(b"OK")
    assert engine.run(b"DBSIZE") == 0


def test_rename_preserves_ttl_and_overwrites_destination(engine: Engine, clock: Clock) -> None:
    engine.run(b"SET", b"source", b"v", b"EX", b"2")
    engine.run(b"SET", b"dest", b"old")
    engine.run(b"RENAME", b"source", b"dest")
    clock.now += 2
    assert engine.run(b"GET", b"dest") == BulkString(None)
    assert engine.run(b"DBSIZE") == 0


def test_expired_keys_are_absent_from_keyspace_commands(engine: Engine, clock: Clock) -> None:
    engine.run(b"SET", b"a", b"v", b"PX", b"1000")
    engine.run(b"SET", b"b", b"v", b"PX", b"1000")
    clock.now += 1
    assert engine.run(b"EXISTS", b"a") == 0
    assert engine.run(b"DEL", b"b") == 0
    assert engine.run(b"TYPE", b"a") == SimpleString(b"none")
    assert engine.run(b"DBSIZE") == 0
    assert engine.run(b"KEYS", b"*") == Array(())
    assert engine.run(b"SET", b"a", b"new", b"NX") == SimpleString(b"OK")


@pytest.mark.parametrize("pattern, expected", [
    (b"*", {b"cat", b"car", b"cab", b"dog", b"c*t", b"\xff"}),
    (b"ca?", {b"cat", b"car", b"cab"}),
    (b"ca[br]", {b"car", b"cab"}),
    (b"ca[b-t]", {b"cat", b"car", b"cab"}),
    (b"ca[^bt]", {b"car"}),
    (b"c\\*t", {b"c*t"}),
    (b"?", {b"\xff"}),
    (b"none*", set()),
])
def test_keys_glob_patterns(engine: Engine, pattern: bytes, expected: set[bytes]) -> None:
    for key in (b"cat", b"car", b"cab", b"dog", b"c*t", b"\xff"):
        engine.run(b"SET", key, b"v")
    result = engine.run(b"KEYS", pattern)
    assert isinstance(result, Array) and result.value is not None
    assert {item.value for item in result.value if isinstance(item, BulkString)} == expected


@pytest.mark.parametrize("command_args, name", [
    ((b"GET",), b"get"), ((b"GET", b"a", b"b"), b"get"),
    ((b"SET", b"a"), b"set"), ((b"MSET", b"a"), b"mset"),
    ((b"DEL",), b"del"), ((b"DBSIZE", b"extra"), b"dbsize"),
    ((b"PING", b"a", b"b"), b"ping"), ((b"QUIT", b"a"), b"quit"),
])
def test_wrong_arity_is_redis_style(engine: Engine, command_args: tuple[bytes, ...], name: bytes) -> None:
    assert engine.run(*command_args) == Error(b"ERR wrong number of arguments for '" + name + b"' command")
