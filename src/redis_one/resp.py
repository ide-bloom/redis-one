from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class SimpleString:
    value: bytes


@dataclass(frozen=True, slots=True)
class Error:
    value: bytes


@dataclass(frozen=True, slots=True)
class BulkString:
    value: bytes | None


@dataclass(frozen=True, slots=True)
class Array:
    value: tuple[RESPValue, ...] | None


RESPValue: TypeAlias = SimpleString | Error | int | BulkString | Array


class ProtocolError(ValueError):
    pass


class _Incomplete(Exception):
    pass


def _number(raw: bytes) -> int:
    digits = raw[1:] if raw.startswith(b"-") else raw
    if not digits or len(digits) > 19 or not digits.isdigit():
        raise ProtocolError("invalid integer")
    value = int(raw)
    if not -(2**63) <= value <= 2**63 - 1:
        raise ProtocolError("invalid integer")
    return value


def _inline_words(line: bytes) -> tuple[RESPValue, ...]:
    words: list[RESPValue] = []
    i = 0
    while i < len(line):
        while i < len(line) and line[i] in b" \t\r\n\v\f":
            i += 1
        if i == len(line):
            break
        word = bytearray()
        quote: int | None = None
        while i < len(line):
            char = line[i]
            if quote is None and char in b" \t\r\n\v\f":
                break
            if quote is None and char in (ord('"'), ord("'")):
                quote = char
                i += 1
                continue
            if quote is not None and char == quote:
                quote = None
                i += 1
                if i < len(line) and line[i] not in b" \t\r\n\v\f":
                    raise ProtocolError("unbalanced quotes in request")
                break
            if char == ord("\\") and quote is not None and i + 1 < len(line):
                following = line[i + 1]
                if quote == ord('"'):
                    if following == ord("x") and i + 3 < len(line):
                        try:
                            word.append(int(line[i + 2 : i + 4], 16))
                        except ValueError:
                            pass
                        else:
                            i += 4
                            continue
                    word.append({ord("n"): 10, ord("r"): 13, ord("t"): 9,
                                 ord("b"): 8, ord("a"): 7}.get(following, following))
                    i += 2
                    continue
                if following == ord("'"):
                    word.append(following)
                    i += 2
                    continue
            word.append(char)
            i += 1
        if quote is not None:
            raise ProtocolError("unbalanced quotes in request")
        words.append(BulkString(bytes(word)))
    return tuple(words)


class RESPParser:
    def __init__(self, *, allow_inline: bool = False) -> None:
        self._buffer = bytearray()
        self._allow_inline = allow_inline

    def feed(self, data: bytes) -> None:
        self._buffer.extend(data)

    def get(self) -> RESPValue | None:
        if not self._buffer:
            return None
        try:
            value, end = self._parse(0, 0)
        except _Incomplete:
            return None
        del self._buffer[:end]
        return value

    def _line(self, start: int) -> tuple[bytes, int]:
        end = self._buffer.find(b"\r\n", start)
        if end < 0:
            raise _Incomplete
        return bytes(self._buffer[start:end]), end + 2

    def _parse(self, start: int, depth: int) -> tuple[RESPValue, int]:
        if depth > 128:
            raise ProtocolError("nested arrays are too deep")
        if start >= len(self._buffer):
            raise _Incomplete
        prefix = self._buffer[start]
        if prefix not in b"+-:$*":
            if depth or not self._allow_inline:
                raise ProtocolError("invalid RESP type byte")
            line, end = self._line(start)
            return Array(_inline_words(line)), end

        line, pos = self._line(start + 1)
        if prefix == ord("+"):
            return SimpleString(line), pos
        if prefix == ord("-"):
            return Error(line), pos
        if prefix == ord(":"):
            return _number(line), pos

        length = _number(line)
        if length < -1:
            raise ProtocolError("invalid length")
        if prefix == ord("$"):
            if length == -1:
                return BulkString(None), pos
            end = pos + length
            if end + 2 > len(self._buffer):
                raise _Incomplete
            if self._buffer[end : end + 2] != b"\r\n":
                raise ProtocolError("invalid bulk string terminator")
            return BulkString(bytes(self._buffer[pos:end])), end + 2

        if length == -1:
            return Array(None), pos
        values: list[RESPValue] = []
        for _ in range(length):
            value, pos = self._parse(pos, depth + 1)
            values.append(value)
        return Array(tuple(values)), pos


def encode(value: RESPValue) -> bytes:
    if isinstance(value, SimpleString | Error):
        if b"\r" in value.value or b"\n" in value.value:
            raise ValueError("simple strings and errors cannot contain CR or LF")
        prefix = b"+" if isinstance(value, SimpleString) else b"-"
        return prefix + value.value + b"\r\n"
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise ValueError("RESP integer outside signed 64-bit range")
        return b":" + str(value).encode("ascii") + b"\r\n"
    if isinstance(value, BulkString):
        if value.value is None:
            return b"$-1\r\n"
        return b"$" + str(len(value.value)).encode("ascii") + b"\r\n" + value.value + b"\r\n"
    if isinstance(value, Array):
        if value.value is None:
            return b"*-1\r\n"
        return b"*" + str(len(value.value)).encode("ascii") + b"\r\n" + b"".join(
            encode(item) for item in value.value
        )
    raise TypeError(f"unsupported RESP value: {type(value).__name__}")
