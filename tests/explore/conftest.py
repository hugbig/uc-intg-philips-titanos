import pytest
from titan_explore.console import Console

from tests.fake_tv import FakeTitanTV


@pytest.fixture
def fake_tv() -> FakeTitanTV:
    """The exploration tool is tested against the original fake TV, which exercises each hypothesis."""
    return FakeTitanTV()


class ScriptedIO:
    """Scripted console: predefined answers, recorded output."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.output: list[str] = []

    def input(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"Unexpected question: {prompt}")
        answer = self.answers.pop(0)
        return answer() if callable(answer) else answer  # a function simulates a user action

    def print(self, *args) -> None:
        self.output.append(" ".join(str(a) for a in args))


@pytest.fixture
def scripted():
    def _make(*answers):
        io = ScriptedIO(answers)
        return io, Console(input_fn=io.input, output_fn=io.print)

    return _make


@pytest.fixture
def js_factory(fake_tv, tmp_path):
    """Builds a SafeJointSpace wired to the fake server."""
    from titan_explore.record import Journal
    from titan_explore.safe_js import SafeJointSpace

    from intg_philips_titanos.client import PhilipsJointSpaceClient

    clients = []

    def _make(interval=0.0, slow_threshold=1.0):
        client = PhilipsJointSpaceClient("192.168.1.42", secured_transport=False, transport=fake_tv.transport())
        clients.append(client)
        journal = Journal(tmp_path / "journal.jsonl")
        return SafeJointSpace(client, journal, interval=interval, slow_threshold=slow_threshold)

    return _make


@pytest.fixture
def make_session(tmp_path, fake_tv, scripted):
    """Session wired to the fake server; returns (io, session)."""
    from titan_explore.session import Session

    fake_tv.offline_hang = 0.05

    def _make(*answers, host="192.168.1.42", mac="AA:BB:CC:DD:EE:FF", out=None, paired=True):
        io, console = scripted(*answers)
        session = Session(out or tmp_path, console, host=host, mac=mac, interval=0.0)
        session.context["transport"] = fake_tv.transport()
        if paired and "jointspace" not in session.credentials:
            session.credentials["jointspace"] = {"username": "test", "password": "test", "protocol": "http"}
        return io, session

    return _make
