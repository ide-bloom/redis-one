import asyncio
import signal
import sys
import unittest

from redis_one.config import Config
from redis_one.resp import Array, BulkString, Error, RESPParser, RESPValue, SimpleString, encode
from redis_one.server import RedisOneServer


class TCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = RedisOneServer(Config(port=0))
        await self.server.start()
        self.reader, self.writer = await asyncio.open_connection(*self.server.address)
        self.parser = RESPParser()

    async def asyncTearDown(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()
        await self.server.close()

    async def reply(self) -> RESPValue:
        while (value := self.parser.get()) is None:
            data = await asyncio.wait_for(self.reader.read(4096), 2)
            self.assertTrue(data, "connection closed before reply")
            self.parser.feed(data)
        return value

    async def test_fragmented_and_pipelined_commands(self) -> None:
        self.writer.write(b"*2\r\n$4\r\nEC")
        await self.writer.drain()
        await asyncio.sleep(0)
        self.writer.write(b"HO\r\n$3\r\na\x00b\r\nPING\r\n*2\r\n$4\r\nPING\r\n$2\r\nhi\r\n")
        await self.writer.drain()
        self.assertEqual(await self.reply(), BulkString(b"a\x00b"))
        self.assertEqual(await self.reply(), SimpleString(b"PONG"))
        self.assertEqual(await self.reply(), BulkString(b"hi"))

    async def test_shared_store_and_pipelined_writes(self) -> None:
        requests = [
            (b"SET", b"counter", b"10"),
            (b"INCRBY", b"counter", b"2"),
            (b"MGET", b"counter", b"missing"),
        ]
        for command in requests:
            self.writer.write(encode(Array(tuple(BulkString(arg) for arg in command))))
        await self.writer.drain()
        self.assertEqual(await self.reply(), SimpleString(b"OK"))
        self.assertEqual(await self.reply(), 12)
        self.assertEqual(await self.reply(), Array((BulkString(b"12"), BulkString(None))))

        reader, writer = await asyncio.open_connection(*self.server.address)
        try:
            writer.write(b"GET counter\r\n")
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(8), 2), b"$2\r\n12\r\n")
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_command_errors_and_quit(self) -> None:
        self.writer.write(b"ECHO\r\nWHAT\r\nCOMMAND\r\nCOMMAND COUNT\r\nQUIT\r\nPING\r\n")
        await self.writer.drain()
        self.assertEqual(await self.reply(), Error(b"ERR wrong number of arguments for 'echo' command"))
        self.assertEqual(await self.reply(), Error(b"ERR unknown command 'what'"))
        self.assertEqual(await self.reply(), Array(()))
        self.assertEqual(await self.reply(), 0)
        self.assertEqual(await self.reply(), SimpleString(b"OK"))
        self.assertEqual(await self.reader.read(), b"")

    async def test_protocol_error_closes_only_that_client(self) -> None:
        self.writer.write(b"*1\r\n$-2\r\n")
        await self.writer.drain()
        self.assertEqual(await self.reply(), Error(b"ERR Protocol error: invalid length"))
        self.assertEqual(await self.reader.read(), b"")
        reader, writer = await asyncio.open_connection(*self.server.address)
        writer.write(b"PING\r\n")
        await writer.drain()
        self.assertEqual(await reader.readline(), b"+PONG\r\n")
        writer.close()
        await writer.wait_closed()

    async def test_wrong_wire_type_and_abrupt_disconnect(self) -> None:
        self.writer.write(encode(SimpleString(b"PING")))
        await self.writer.drain()
        self.assertEqual(await self.reply(), Error(b"ERR Protocol error: expected an array of bulk strings"))
        reader, writer = await asyncio.open_connection(*self.server.address)
        writer.write(b"*1\r\n$4\r\nPI")
        await writer.drain()
        writer.transport.abort()
        del reader
        await asyncio.sleep(0)

    async def test_server_close_disconnects_idle_clients(self) -> None:
        await asyncio.wait_for(self.server.close(), 2)
        self.assertEqual(await asyncio.wait_for(self.reader.read(), 2), b"")

    async def test_serve_forever_returns_after_close(self) -> None:
        serving = asyncio.create_task(self.server.serve_forever())
        await asyncio.sleep(0)
        await asyncio.wait_for(self.server.close(), 2)
        await asyncio.wait_for(serving, 2)


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(hasattr(signal, "SIGINT"), "SIGINT unavailable")
    async def test_sigint_stops_server_cleanly(self) -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "redis_one.server", "--port", "0",
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stderr is not None
        writer = None
        try:
            line = await asyncio.wait_for(process.stderr.readline(), 5)
            port = int(line.decode().strip().rsplit(":", 1)[1])
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            process.send_signal(signal.SIGINT)
            self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            if process.returncode is None:
                process.kill()
                await process.wait()
