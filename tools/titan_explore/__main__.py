"""Entry point: python -m titan_explore --host <IP> [--mac <MAC>]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from titan_explore.console import Console
from titan_explore.session import Session
from titan_explore.steps import STEPS


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guided exploration of a Philips Titan OS TV")
    parser.add_argument("--host", default="", help="TV IP address")
    parser.add_argument("--mac", default="", help="MAC address of the network interface the TV uses")
    parser.add_argument("--out", default="exploration", help="folder for the report, the journal and the credentials")
    parser.add_argument("--interval", type=float, default=2.0, help="minimum seconds between two JointSpace requests")
    parser.add_argument("--step", type=int, help="run a single step")
    parser.add_argument("--from-step", type=int, help="resume from this step")
    parser.add_argument("--list", action="store_true", help="list the steps")
    return parser.parse_args()


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def install_sigint_handler() -> None:
    """Ctrl+C immediately interrupts the question in progress.

    asyncio.run only installs its own handler (which merely cancels the task, without
    interrupting input()) if the default handler is in place.
    """
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)


def main() -> None:
    args = _parse_args()
    # Technical details go to the journal; only library errors are displayed.
    logging.basicConfig(level=logging.ERROR)
    if args.list:
        for step in STEPS:
            print(f"{step.number:>2}. {step.title}" + ("  (risky)" if step.risky else ""))
        return
    install_sigint_handler()
    session = Session(Path(args.out), Console(), host=args.host, mac=args.mac, interval=args.interval)
    try:
        asyncio.run(session.run(STEPS, only=args.step, start_from=args.from_step))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
