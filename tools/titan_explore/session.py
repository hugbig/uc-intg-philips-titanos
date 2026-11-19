"""Session orchestration: independent steps, resume, skip, restore."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from titan_explore.console import Console
from titan_explore.record import Finding, Journal, Report

WEDGE_INSTRUCTIONS = (
    "The TV server is no longer responding properly. Unplug the TV from the mains for 30 seconds, "
    "plug it back in, wait for it to restart, then rerun the script with --from-step at the next step."
)


async def _protected(awaitable: Awaitable[None]) -> None:
    """Runs the restore to completion, even if a cancellation (Ctrl+C under asyncio.run)
    is delivered to the current task in the meantime."""
    inner = asyncio.ensure_future(awaitable)
    while True:
        try:
            await asyncio.shield(inner)
            return
        except asyncio.CancelledError:
            if inner.done():
                return


class TvUnreachable(Exception):
    """The TV does not respond (deep standby, network): the step is marked "unknown"."""


class TvWedged(Exception):
    """The TV was responding and no longer responds properly: the whole session stops."""


@dataclass
class Step:
    number: int
    title: str
    run: Callable[[Session], Awaitable[None]]
    risky: bool = False


@dataclass
class RestoreStack:
    """Undo actions for modified settings, unwound in reverse order."""

    _items: list[tuple[str, Callable[[], Awaitable[None]]]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def push(self, description: str, undo: Callable[[], Awaitable[None]]) -> None:
        self._items.append((description, undo))

    async def unwind(self) -> list[str]:
        restored = []
        while self._items:
            description, undo = self._items.pop()
            try:
                await undo()
                restored.append(description)
            except Exception as err:  # a failed restore must not block the following ones
                self.errors.append(f"{description} : {type(err).__name__}: {err}")
        return restored


class Session:
    def __init__(self, out_dir: Path, console: Console, host: str = "", mac: str = "", interval: float = 2.0) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.console = console
        self.host = host
        self.mac = mac
        self.interval = interval
        self.journal = Journal(self.out_dir / "journal.jsonl")
        self.report = Report(self.out_dir / "report.md", self.out_dir / "state.json")
        self.report.load_state()
        self.restore = RestoreStack()
        self.credentials: dict[str, Any] = self._load_credentials()
        self.context: dict[str, Any] = {}  # objects shared between steps (JointSpace and MQTT clients…)

    # ------------------------------------------------------------------ credentials
    @property
    def _credentials_path(self) -> Path:
        return self.out_dir / "credentials.json"

    def _load_credentials(self) -> dict[str, Any]:
        if self._credentials_path.exists():
            return json.loads(self._credentials_path.read_text(encoding="utf-8"))
        return {}

    def save_credentials(self) -> None:
        path = self._credentials_path
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self.credentials, handle, indent=2)
        os.chmod(path, 0o600)

    # ------------------------------------------------------------------ execution
    def _persist(self) -> None:
        self.report.save_state()
        self.report.write()

    async def _restore(self) -> None:
        restored = await self.restore.unwind()
        if restored:
            self.console.say("Settings restored to their initial state: " + ", ".join(restored))
        for error in self.restore.errors:
            self.report.notices.append(f"Restore failed: {error} — set it back by hand.")
        self.restore.errors.clear()

    async def run(self, steps: list[Step], only: int | None = None, start_from: int | None = None) -> None:
        for step in steps:
            if only is not None and step.number != only:
                continue
            if start_from is not None and step.number < start_from:
                continue
            self.report.titles[step.number] = step.title
            choice = self.console.ask_choice(f"\nStep {step.number} — {step.title}", ["run", "skip"])
            if choice == "skip":
                if not self.report.findings_for(step.number):  # keep the results of a previous session
                    self.report.add(Finding(step.number, step.title, "not tested", note="step skipped"))
                self._persist()
                continue
            self.report.clear_step(step.number)
            self.journal.log("step", number=step.number, title=step.title)
            try:
                await step.run(self)
            except TvUnreachable as err:
                self.report.add(Finding(step.number, step.title, "unknown", note=f"TV unreachable: {err}"))
            except TvWedged as err:
                self.journal.log("wedged", step=step.number, error=str(err))
                self.report.add(Finding(step.number, step.title, "unknown", note=f"TV frozen: {err}"))
                self.report.notices.append(WEDGE_INSTRUCTIONS)
                await self._restore()
                self._persist()
                self.console.say(f"\n⚠️  {WEDGE_INSTRUCTIONS}")
                return
            except (KeyboardInterrupt, asyncio.CancelledError):
                self.console.say("\nInterrupted: restoring settings and writing the partial report…")
                self.report.notices.append(f"Session interrupted during step {step.number}.")
                await _protected(self._restore())
                self._persist()
                return
            except Exception as err:  # unexpected error: restore the TV and carry on
                self.journal.log("error", step=step.number, error=f"{type(err).__name__}: {err}")
                self.report.add(
                    Finding(step.number, step.title, "unknown", note=f"unexpected error: {type(err).__name__}: {err}")
                )
            await self._restore()
            self._persist()
        self.console.say(f"\nReport written to {self.report.path}")
