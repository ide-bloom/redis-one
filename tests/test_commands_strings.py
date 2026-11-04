import pytest

from redis_one.resp import Array, BulkString, Error, SimpleString
from conftest import Clock, Engine

OK = SimpleString(b"OK")
NIL = BulkString(None)
INTEGER_ERROR = Error(b"ERR value is not an integer or out of range")
OVERFLOW = Error(b"ERR increment or decrement would overflow")
SYNTAX = Error(b"ERR syntax error")


def test_set_get_and_getset_are_binary_safe(engine: Engine) -> None:
    assert engine.run(b"get", b"absent") == NIL
    assert engine.run(b"SeT", b"\x00key", b"\xff\x00value") == OK
    assert engine.run(b"GET", b"\x00key") == BulkString(b"\xff\x00value")
    assert engine.run(b"GETSET", b"\x00key", b"") == BulkString(b"\xff\x00value")
    assert engine.run(b"get", b"\x00key") == BulkString(b"")
    assert engine.run(b"getset", b"new", b"x") == NIL


def test_mset_mget_and_failed_mset_are_atomic(engine: Engine) -> None:
    assert engine.run(b"MSET", b"a", b"one", b"b", b"two", b"a", b"last") == OK
    assert engine.run(b"MGET", b"a", b"missing", b"b") == Array((BulkString(b"last"), NIL, BulkString(b"two")))
    assert engine.run(b"MSET", b"a", b"changed", b"orphan") == Error(
        b"ERR wrong number of arguments for 'mset' command"
    )
    assert engine.run(b"GET", b"a") == BulkString(b"last")


def test_append_and_strlen_count_bytes(engine: Engine) -> None:
    assert engine.run(b"STRLEN", b"a") == 0
    assert engine.run(b"APPEND", b"a", b"\xc3\xa9") == 2
    assert engine.run(b"APPEND", b"a", b"\x00!") == 4
    assert engine.run(b"STRLEN", b"a") == 4
    assert engine.run(b"GET", b"a") == BulkString(b"\xc3\xa9\x00!")


def test_integer_operations_and_boundaries(engine: Engine) -> None:
    assert engine.run(b"INCR", b"n") == 1
    assert engine.run(b"INCRBY", b"n", b"-3") == -2
    assert engine.run(b"DECRBY", b"n", b"-2") == 0
    assert engine.run(b"DECR", b"n") == -1
    assert engine.run(b"GET", b"n") == BulkString(b"-1")
    engine.run(b"SET", b"n", b"9223372036854775807")
    assert engine.run(b"INCR", b"n") == OVERFLOW
    assert engine.run(b"GET", b"n") == BulkString(b"9223372036854775807")
    engine.run(b"SET", b"n", b"-9223372036854775808")
    assert engine.run(b"DECR", b"n") == OVERFLOW
    assert engine.run(b"DECRBY", b"n", b"-9223372036854775808") == Error(b"ERR decrement would overflow")
    assert engine.run(b"GET", b"n") == BulkString(b"-9223372036854775808")


@pytest.mark.parametrize("value", [b"", b" 1", b"1 ", b"+1", b"01", b"-0", b"--1", b"1.0", b"\xff", b"9223372036854775808"])
def test_invalid_integers_do_not_change_data(engine: Engine, value: bytes) -> None:
    engine.run(b"SET", b"n", value)
    assert engine.run(b"INCR", b"n") == INTEGER_ERROR
    assert engine.run(b"GET", b"n") == BulkString(value)
    assert engine.run(b"INCRBY", b"other", value) == INTEGER_ERROR
    assert engine.run(b"GET", b"other") == NIL


def test_set_conditions_and_options(engine: Engine, clock: Clock) -> None:
    assert engine.run(b"SET", b"a", b"one", b"NX") == OK
    assert engine.run(b"SET", b"a", b"two", b"NX") == NIL
    assert engine.run(b"SET", b"missing", b"x", b"XX") == NIL
    assert engine.run(b"SET", b"a", b"two", b"XX", b"PX", b"2000") == OK
    clock.now += 1
    assert engine.run(b"GET", b"a") == BulkString(b"two")
    clock.now += 1
    assert engine.run(b"GET", b"a") == NIL
    assert engine.run(b"SET", b"a", b"x", b"EX", b"invalid", b"EX", b"3") == OK
    clock.now += 2
    assert engine.run(b"GET", b"a") == BulkString(b"x")
    clock.now += 1
    assert engine.run(b"GET", b"a") == NIL


@pytest.mark.parametrize("options, reply", [
    ((b"NX", b"XX"), SYNTAX),
    ((b"EX",), SYNTAX),
    ((b"WHAT",), SYNTAX),
    ((b"EX", b"1", b"PX", b"5"), SYNTAX),
    ((b"EX", b"0"), Error(b"ERR invalid expire time in 'set' command")),
    ((b"PX", b"-1"), Error(b"ERR invalid expire time in 'set' command")),
    ((b"EX", b"not-a-number"), INTEGER_ERROR),
    ((b"EX", b"9223372036854775807"), Error(b"ERR invalid expire time in 'set' command")),
])
def test_invalid_set_options_do_not_mutate(engine: Engine, options: tuple[bytes, ...], reply: Error) -> None:
    engine.run(b"SET", b"a", b"before")
    assert engine.run(b"SET", b"a", b"after", *options) == reply
    assert engine.run(b"GET", b"a") == BulkString(b"before")


def test_write_ttl_rules(engine: Engine, clock: Clock) -> None:
    for command, args in [
        (b"APPEND", (b"1",)), (b"INCR", ()), (b"DECR", ()),
        (b"INCRBY", (b"1",)), (b"DECRBY", (b"1",)),
    ]:
        engine.run(b"SET", b"k", b"1", b"PX", b"1000")
        engine.run(command, b"k", *args)
        clock.now += 1
        assert engine.run(b"GET", b"k") == NIL
    for command, args in [(b"SET", (b"new",)), (b"GETSET", (b"new",)), (b"MSET", (b"new",))]:
        engine.run(b"SET", b"k", b"1", b"PX", b"1000")
        engine.run(command, b"k", *args)
        clock.now += 1
        assert engine.run(b"GET", b"k") == BulkString(b"new")
