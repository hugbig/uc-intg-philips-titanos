from titan_explore.steps.s01_prep import step_prep
from titan_explore.steps.s02_pairing import step_pairing_jointspace


async def test_prep_asks_missing_host(make_session):
    io, session = make_session(
        "ethernet", "y", "y", "y", "y", "y", "not-an-ip", "192.168.1.50", "", host="", mac="", paired=False
    )
    await step_prep(session)
    assert session.host == "192.168.1.50"
    assert any(f.item == "TV IP address" and f.value == "192.168.1.50" for f in session.report.findings_for(1))


async def test_prep_records_checklist_gaps(make_session):
    _, session = make_session("ethernet", "n", "y", "y", "y", "y")
    await step_prep(session)
    notes = [f for f in session.report.findings_for(1) if f.status == "unknown"]
    assert notes and "Fixed IP" in notes[0].item


async def test_prep_wake_setting_follows_connection(make_session):
    # Wi-Fi: WoWLAN disabled = problem; Wake-on-LAN (Ethernet) disabled = irrelevant
    _, session = make_session("wifi", "y", "y", "n", "n", "y")
    await step_prep(session)
    findings = {f.item: f for f in session.report.findings_for(1)}
    assert session.context["connection"] == "wifi"
    assert findings["TV network connection"].value == "wifi"
    assert findings["WoWLAN \"Switch on with Wi-Fi\" enabled"].status == "unknown"
    assert findings["Wake-on-LAN (Ethernet) enabled"].status == "info"


async def test_pairing_saves_credentials(make_session, tmp_path):
    _, session = make_session("1234", paired=False)
    await step_pairing_jointspace(session)
    creds = session.credentials["jointspace"]
    assert creds["username"] and creds["password"]
    path = tmp_path / "credentials.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"


async def test_wrong_pin_can_be_retried(make_session):
    _, session = make_session("9999", "1234", paired=False)
    await step_pairing_jointspace(session)
    assert session.credentials["jointspace"]["username"]


async def test_rerun_reuses_credentials_and_results(make_session, tmp_path, fake_tv):
    _, first = make_session("1234", paired=False)
    await step_pairing_jointspace(first)
    first.report.save_state()

    io, second = make_session(paired=False)  # no scripted answer: no PIN must be asked
    await step_pairing_jointspace(second)
    assert second.credentials["jointspace"] == first.credentials["jointspace"]
    assert any("reused" in f.item for f in second.report.findings_for(2))


async def test_system_info_reported(make_session):
    _, session = make_session("1234", paired=False)
    await step_pairing_jointspace(session)
    values = " ".join(f.value for f in session.report.findings_for(2))
    assert "Fake Titan TV" in values
    assert "6.1" in values


async def test_h7_applications_and_sources_checked(make_session):
    _, session = make_session("1234", paired=False)
    await step_pairing_jointspace(session)
    h7 = [f for f in session.report.findings_for(2) if f.hypothesis == "H7"]
    assert h7 and "applications" in h7[0].value and "sources" in h7[0].value


def test_mac_validation_is_shared():
    from titan_explore.steps import s01_prep

    from intg_philips_titanos import setup_flow

    assert s01_prep.MAC_RE is setup_flow.MAC_RE
