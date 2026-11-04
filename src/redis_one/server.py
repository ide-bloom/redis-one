from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from .commands import create_registry
from .config import Config, parse_args
from .resp import Array, BulkString, Error, ProtocolError, RESPParser, RESPValue, encode
from .store import Store

logger = logging.getLogger(__name__)


def _arguments(value: RESPValue) -> tuple[bytes, ...]:
    if not isinstance(value, Array) or value.value is None:
        raise ProtocolError("expected an array of bulk strings")
    result: list[bytes] = []
    for item in value.value:
        if not isinstance(item, BulkString) or item.value is None:
            raise ProtocolError("expected a bulk string")
        result.append(item.value)
    return tuple(result)


class RedisOneServer:
    def __init__(self, config: Config = Config()) -> None:
        self.config = config
        self.store = Store()
        self.registry = create_registry()
        self._server: asyncio.Server | None = None
        self._stopped = asyncio.Event()
        self._clients: set[asyncio.StreamWriter] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.config.host, self.config.port)
        self._stopped.clear()

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("server is not running")
        address = self._server.sockets[0].getsockname()
        return str(address[0]), int(address[1])

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("server is not running")
        # asyncio.Server.serve_forever() waits for active connections when
        # cancelled on Python 3.12, before our cleanup can close those clients.
        await self._stopped.wait()

    async def close(self) -> None:
        server = self._server
        if server is not None:
            server.close()
            self._server = None
        # Python 3.12+ waits for connections too, so close clients first.
        for writer in tuple(self._clients):
            writer.close()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if server is not None:
            await server.wait_closed()
        self._stopped.set()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        self._clients.add(writer)
        parser = RESPParser(allow_inline=True)
        try:
            while data := await reader.read(65536):
                parser.feed(data)
                while (value := parser.get()) is not None:
                    command = _arguments(value)
                    if not command:
                        continue  # Redis ignores empty requests.
                    reply, close = self.registry.execute(self.store, command)
                    writer.write(encode(reply))
                    if close:
                        await writer.drain()
                        return
                await writer.drain()
        except ProtocolError as exc:
            # A framing error leaves the stream ambiguous, so reply once and close.
            writer.write(encode(Error(b"ERR Protocol error: " + str(exc).encode("ascii"))))
            try:
                await writer.drain()
            except (ConnectionError, OSError):
                pass
        except (ConnectionError, OSError):
            pass  # A client can disappear between a read and a write.
        finally:
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task is not None:
                self._tasks.discard(task)


async def _run(config: Config) -> None:
    server = RedisOneServer(config)
    await server.start()
    logger.info("Listening on %s:%d", *server.address)
    try:
        await server.serve_forever()
    finally:
        await server.close()


def main(args: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(_run(parse_args(args)))
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
