"""Run the API.

Bound to 127.0.0.1 and not configurable to anything else without saying so on
the command line. This process spawns Claude Code runs on the user's own
subscription and has no authentication of any kind, so a default that listened
on every interface would hand the machine's whole tool environment to anyone on
the network.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from planify import composition
from planify.adapters.driving.http.api import create_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="planify-api",
        description="Serve the planner over HTTP for the local web app.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=composition.DEFAULT_PATH,
        help="path to settings.py (default: config/settings.py)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="restart on code changes. Development only — a reload kills live runs.",
    )
    args = parser.parse_args(argv)

    if args.host != DEFAULT_HOST:
        print(
            f"! serving on {args.host}: this API has no authentication and drives "
            "your Claude Code subscription. Only do this on a trusted network."
        )

    if args.reload:
        # The reloader needs an import string rather than an instance, so the
        # config path travels through the environment instead of a closure.
        os.environ["TECH_PLANNER_CONFIG"] = str(args.config)
        uvicorn.run(
            "planify.adapters.driving.http.main:app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
        )
        return 0

    uvicorn.run(create_app(args.config), host=args.host, port=args.port)
    return 0


def app_from_env() -> FastAPI:
    """Factory for `--reload`, which re-imports this module in a child process."""
    return create_app(Path(os.environ.get("TECH_PLANNER_CONFIG", composition.DEFAULT_PATH)))


if __name__ == "__main__":
    raise SystemExit(main())
