import argparse
from dataclasses import dataclass
from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 6399


def parse_args(args: Sequence[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Run the Redis One RESP2 server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6399)
    options = parser.parse_args(args)
    if not 0 <= options.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    return Config(host=options.host, port=options.port)
