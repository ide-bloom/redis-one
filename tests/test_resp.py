import pytest

from redis_one.resp import Array, BulkString, Error, ProtocolError, RESPParser, SimpleString, RESPValue, encode


@pytest.mark.parametrize(
    ("value", "wire"),
    [
        (SimpleString(b"OK"), b"+OK\r\n"),
        (Error(b"ERR failure"), b"-ERR failure\r\n"),
        (0, b":0\r\n"),
        (-9223372036854775808, b":-9223372036854775808\r\n"),
        (BulkString(b"a\x00\r\nb"), b"$5\r\na\x00\r\nb\r\n"),
        (BulkString(b""), b"$0\r\n\r\n"),
        (BulkString(None), b"$-1\r\n"),
        (Array(None), b"*-1\r\n"),
        (Array(()), b"*0\r\n"),
        (Array((BulkString(b"hi"), Array((1, Error(b"oops"))))),
         b"*2\r\n$2\r\nhi\r\n*2\r\n:1\r\n-oops\r\n"),
    ],
)
def test_round_trip_and_every_split(value: RESPValue, wire: bytes) -> None:
    assert encode(value) == wire
    for split in range(len(wire) + 1):
        parser = RESPParser()
        parser.feed(wire[:split])
        if split < len(wire):
            assert parser.get() is None
        parser.feed(wire[split:])
        assert parser.get() == value
        assert parser.get() is None


def test_one_byte_at_a_time_and_pipeline() -> None:
    values = [Array((BulkString(b"PING"),)), BulkString(b"hi"), 42, Array(None)]
    wire = b"".join(map(encode, values))
    parser = RESPParser()
    received = []
    for byte in wire:
        parser.feed(bytes([byte]))
        while (value := parser.get()) is not None:
            received.append(value)
    assert received == values

    parser.feed(wire)
    assert [parser.get() for _ in values] == values
    assert parser.get() is None


def test_inline_commands_and_quoting() -> None:
    parser = RESPParser(allow_inline=True)
    parser.feed(b'PING\r\nECHO "hello \\x77orld"\r\nECHO \'it\\\'s\'\r\n')
    assert parser.get() == Array((BulkString(b"PING"),))
    assert parser.get() == Array((BulkString(b"ECHO"), BulkString(b"hello world")))
    assert parser.get() == Array((BulkString(b"ECHO"), BulkString(b"it's")))


@pytest.mark.parametrize("wire", [
    b"?bad\r\n", b":1x\r\n", b":9223372036854775808\r\n", b"$-2\r\n",
    b"*-2\r\n", b"$1\r\nx!!", b"*1\r\n?bad\r\n", b"$+1\r\na\r\n",
])
def test_bad_frames_raise_protocol_error(wire: bytes) -> None:
    parser = RESPParser()
    parser.feed(wire)
    with pytest.raises(ProtocolError):
        parser.get()


def test_bad_inline_quotes() -> None:
    parser = RESPParser(allow_inline=True)
    parser.feed(b'ECHO "unclosed\r\n')
    with pytest.raises(ProtocolError, match="unbalanced quotes"):
        parser.get()


def test_rejects_simple_string_with_line_break() -> None:
    with pytest.raises(ValueError):
        encode(SimpleString(b"hello\r\nworld"))
