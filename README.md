# Redis One

[![Tests](https://github.com/ide-bloom/redis-one/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/ide-bloom/redis-one/actions/workflows/tests.yml)

Redis One is an in-memory key-value server built from scratch with Python's
standard library and asyncio. It speaks RESP2, so Redis-compatible clients can
use the commands implemented so far without a custom protocol adapter. This is
an educational, incremental project, not a production Redis replacement.

## Quick start

Requires Python 3.11 or newer.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
redis-one                          # listens on 127.0.0.1:6399
redis-cli -p 6399 SET visits 1     # OK
redis-cli -p 6399 INCR visits      # (integer) 2
redis-cli -p 6399 GET visits       # "2"
```

Use `redis-one --host HOST --port PORT` to change the address. Press Ctrl-C to
stop the server. Run the tests with `python -m pytest`.

## Supported commands

| Family | Commands |
| --- | --- |
| Connection | `PING`, `ECHO`, `QUIT`, minimal `COMMAND` and `COMMAND COUNT` |
| Strings | `SET` (`NX`, `XX`, `EX`, `PX`), `GET`, `GETSET`, `MSET`, `MGET`, `APPEND`, `STRLEN`, `INCR`, `DECR`, `INCRBY`, `DECRBY` |
| Keyspace | `DEL`, `EXISTS`, `KEYS`, `TYPE`, `RENAME`, `DBSIZE`, `FLUSHALL` |

`KEYS` supports Redis-style byte glob patterns, including `*`, `?`, bracket
classes, and escapes. Command names are case-insensitive and keys and values
are binary-safe. `COMMAND` returns empty metadata; client features relying on
introspection are not yet supported.

## How it works and current limits

A buffer-based RESP2 parser handles partial reads, pipelined requests, and
inline commands. A registry checks arity before handing each command to a
family-specific handler. All clients share one in-memory store; command handlers
run without awaiting, so each command completes before the event loop switches
clients. The parser reparses an incomplete value when more bytes arrive, trading
simplicity for extra work on heavily fragmented large frames.

`SET EX/PX` uses monotonic deadlines and passive expiry: expired entries are
removed when accessed or encountered during a keyspace scan. There is no active
expiry task or dedicated TTL commands yet. All data is **lost on shutdown**;
persistence, additional data structures, and transactions are future
milestones. There are no input-size or connection limits yet, so run this only
on a trusted network. Malformed protocol input receives an error and the
connection is closed because the stream cannot be safely resynchronized.

## License

[MIT](LICENSE)
