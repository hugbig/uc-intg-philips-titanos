"""Raw journal (JSON Lines) and Markdown report of the session."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["works", "lies", "ignored", "unknown", "not tested", "to configure", "info"]

HYPOTHESES = {
    "H1": "powerstate says \"On\" in standby",
    "H2": "the JointSpace server freezes under load",
    "H3": "a Titan OS MQTT broker exists (port 8883)",
    "H4": "ambilight/power and AmbilightOnOff are ignored; the style (node 200) drives the LEDs",
    "H5": "no source API; HDMI at the bottom of the Sources menu",
    "H6": "wake-up: POST powerstate On / Wake-on-LAN",
    "H7": "JointSpace applications/sources refused (403/405)",
}


# Findings that decide the integration's next steps (parent spec §8.1).
DECISIONS = [
    ("powerstate in quick standby", "State detection: is JointSpace enough, or do we need MQTT / reachability?"),
    ("Titan OS MQTT broker (port 8883)", "Is an MQTT channel available for state and keys?"),
    ("MQTT topics announced by the TV", "Which MQTT topics does this firmware offer?"),
    ("Safe interval", "Maximum JointSpace request rate (polling, HDMI macro)"),
    ("Network wake (API reachable)", "Power-on by Wake-on-LAN and the delay to expect"),
    ("Power-on via POST powerstate On", "Power-on through the API from quick standby"),
    ("Distinguish HDMI inputs", "Can the HDMI macro verify its result?"),
    ("Steps to configure", "HDMI steps to enter in the configuration"),
    ("Macro pace", "Does the macro hold at 0.12 s between keys?"),
    ("Turn-off like the app", "Ambilight command to implement (power + style 210, like the app)"),
    ("Style 210 (Off) alone", "Is the style alone enough to turn Ambilight off?"),
    ("AmbilightOnOff key", "Is the current AMBILIGHT_TOGGLE command useful?"),
    ("Picture mode node", "Can the picture mode be driven through the API?"),
    ("Picture mode remembered per input", "Should the picture mode be driven from activities?"),
    ("Volume keys → amplifier (ARC/CEC)", "Volume of the media_player entity"),
    ("notifychange", "Listen for changes instead of polling?"),
    ("CEC: automatic TV power-on", "Should activities power the TV on themselves?"),
    ("Philips app", "What can the official app do (so an API exists)?"),
]


@dataclass
class Finding:
    step: int
    item: str
    status: Status
    value: str = ""
    note: str = ""
    hypothesis: str = ""


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def log(self, kind: str, **data: Any) -> None:
        entry = {"ts": datetime.now().isoformat(timespec="milliseconds"), "kind": kind, **data}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


class Report:
    def __init__(self, path: Path, state_path: Path) -> None:
        self.path = path
        self.state_path = state_path
        self.findings: list[Finding] = []
        self.titles: dict[int, str] = {}
        self.notices: list[str] = []

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def findings_for(self, step: int) -> list[Finding]:
        return [f for f in self.findings if f.step == step]

    def clear_step(self, step: int) -> None:
        self.findings = [f for f in self.findings if f.step != step]

    def save_state(self) -> None:
        self.notices = list(dict.fromkeys(self.notices))
        state = {"findings": [asdict(f) for f in self.findings], "titles": self.titles, "notices": self.notices}
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_state(self) -> None:
        if not self.state_path.exists():
            return
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.findings = [Finding(**f) for f in state.get("findings", [])]
        self.titles = {int(k): v for k, v in state.get("titles", {}).items()}
        self.notices = list(state.get("notices", []))

    def write(self) -> None:
        lines = [
            "# TV exploration report",
            "",
            f"Generated on {datetime.now():%Y-%m-%d %H:%M}.",
            "",
        ]
        for notice in dict.fromkeys(self.notices):
            lines += [f"> ⚠️ {notice}", ""]
        lines += ["## Hypothesis summary", "", "| Hypothesis | Finding | Result |", "|---|---|---|"]
        for key, label in HYPOTHESES.items():
            related = [f for f in self.findings if f.hypothesis == key]
            result = "; ".join(f"{f.item} : **{f.status}**" for f in related) or "not verified"
            lines.append(f"| {key} | {label} | {result} |")
        lines += ["", "## Takeaways for the integration", "", "| Question | Finding | Result |", "|---|---|---|"]
        for item, question in DECISIONS:
            related = [f for f in self.findings if f.item.startswith(item)]
            result = "; ".join(
                f"**{f.status}**" + (f" — {f.value}" if f.value else "") + (f" ({f.note})" if f.note else "")
                for f in related
            )
            lines.append(f"| {question} | {item} | {result or 'not verified'} |")
        lines += ["", "## Details by step", ""]
        for step in sorted({f.step for f in self.findings} | set(self.titles)):
            lines += [f"### Step {step} — {self.titles.get(step, '')}".rstrip(" —"), ""]
            for f in self.findings_for(step):
                details = " — ".join(part for part in (f.value, f.note) if part)
                lines.append(f"- **{f.status}** · {f.item}" + (f" — {details}" if details else ""))
            lines.append("")
        self.path.write_text("\n".join(lines), encoding="utf-8")
