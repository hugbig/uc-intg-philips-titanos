from titan_explore.steps.s12_philips_app import CAPABILITIES, step_philips_app


async def test_philips_app_answers_recorded(make_session, fake_tv):
    answers = ["y"] + ["yes", "no", "not found"] + ["yes"] * (len(CAPABILITIES) - 3)
    _, session = make_session(*answers)
    await step_philips_app(session)
    findings = {f.item: f.status for f in session.report.findings_for(12)}
    first, second, third = CAPABILITIES[:3]
    assert findings[f"Philips app: {first}"] == "works"
    assert findings[f"Philips app: {second}"] == "ignored"
    assert findings[f"Philips app: {third}"] == "unknown"
    assert fake_tv.requests == []  # no request to the TV: questions only


async def test_philips_app_skipped_when_not_installed(make_session):
    _, session = make_session("n")
    await step_philips_app(session)
    assert [f.status for f in session.report.findings_for(12)] == ["not tested"]


def test_stability_is_last_and_risky():
    from titan_explore.steps import STEPS

    assert [step.number for step in STEPS] == list(range(1, 14))
    assert STEPS[-1].risky and "Stability" in STEPS[-1].title
    assert STEPS[11].title == "Comparison with the Philips app"
