from __future__ import annotations

from ..resp import Array, BulkString, RESPValue, SimpleString
from ..store import Store
from . import CommandError, Registry

# Tokens are (kind, literal/class, negated). Matching is byte-oriented.
Token = tuple[str, int | frozenset[int] | None, bool]


def _pattern(pattern: bytes) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == ord("*"):
            if not tokens or tokens[-1][0] != "star":
                tokens.append(("star", None, False))
        elif char == ord("?"):
            tokens.append(("any", None, False))
        elif char == ord("["):
            i += 1
            negate = i < len(pattern) and pattern[i] == ord("^")
            i += int(negate)
            members: set[int] = set()
            while i < len(pattern) and pattern[i] != ord("]"):
                if pattern[i] == ord("\\") and i + 1 < len(pattern):
                    i += 1
                    members.add(pattern[i])
                elif i + 2 < len(pattern) and pattern[i + 1] == ord("-"):
                    start, end = sorted((pattern[i], pattern[i + 2]))
                    members.update(range(start, end + 1))
                    i += 2
                else:
                    members.add(pattern[i])
                i += 1
            tokens.append(("class", frozenset(members), negate))
        else:
            if char == ord("\\") and i + 1 < len(pattern):
                i += 1
                char = pattern[i]
            tokens.append(("literal", char, False))
        i += 1
    return tokens


def _glob_match(tokens: list[Token], value: bytes) -> bool:
    def advance_stars(states: set[int]) -> set[int]:
        result = set(states)
        for index in sorted(states):
            while index < len(tokens) and tokens[index][0] == "star":
                index += 1
                result.add(index)
        return result

    states = advance_stars({0})
    for byte in value:
        next_states: set[int] = set()
        for index in states:
            if index == len(tokens):
                continue
            kind, data, negate = tokens[index]
            if kind == "star":
                next_states.add(index)
            elif kind == "any" or (kind == "literal" and data == byte):
                next_states.add(index + 1)
            elif kind == "class" and isinstance(data, frozenset) and ((byte in data) != negate):
                next_states.add(index + 1)
        states = advance_stars(next_states)
        if not states:
            return False
    return len(tokens) in states


def delete(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return sum(store.delete(key) for key in args)


def exists(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return sum(store.get(key) is not None for key in args)


def keys(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    tokens = _pattern(args[0])
    return Array(tuple(BulkString(key) for key in store.keys() if _glob_match(tokens, key)))


def key_type(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return SimpleString(b"string" if store.get(args[0]) is not None else b"none")


def rename(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    if not store.rename(args[0], args[1]):
        raise CommandError(b"ERR no such key")
    return SimpleString(b"OK")


def dbsize(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    return sum(1 for _ in store.keys())


def flushall(store: Store, args: tuple[bytes, ...]) -> RESPValue:
    store.clear()
    return SimpleString(b"OK")


def register(registry: Registry) -> None:
    registry.add(b"del", delete, 1)
    registry.add(b"exists", exists, 1)
    registry.add(b"keys", keys, 1, 1)
    registry.add(b"type", key_type, 1, 1)
    registry.add(b"rename", rename, 2, 2)
    registry.add(b"dbsize", dbsize, 0, 0)
    registry.add(b"flushall", flushall, 0, 0)
