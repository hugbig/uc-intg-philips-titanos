import json

import pytest
from titan_explore.session import TvUnreachable, TvWedged


@pytest.fixture(autouse=True)
def short_hang(fake_tv):
    fake_tv.offline_hang = 0.05


async def test_interval_between_calls(js_factory, fake_tv):
    js = js_factory(interval=0.2)
    for _ in range(3):
        await js.get("powerstate")
    times = [t for t, _, _ in fake_tv.requests]
    assert all(b - a >= 0.19 for a, b in zip(times, times[1:], strict=False))


async def test_every_call_is_journaled(js_factory, tmp_path):
    js = js_factory()
    await js.get("powerstate")
    await js.post("audio/volume", {"current": 5, "muted": False})
    lines = [json.loads(line) for line in (tmp_path / "journal.jsonl").read_text().splitlines()]
    calls = [line for line in lines if line["kind"] == "js"]
    assert [c["method"] for c in calls] == ["GET", "POST"]
    assert all("duration" in c and "status" in c for c in calls)


async def test_http_errors_are_answers_not_exceptions(js_factory):
    js = js_factory()
    response = await js.get("applications")
    assert response.status == 404
    assert response.data is None


async def test_unreachable_from_start_raises_unreachable(js_factory, fake_tv):
    fake_tv.online = False
    js = js_factory()
    with pytest.raises(TvUnreachable):
        await js.get("powerstate")


async def test_reachable_never_raises(js_factory, fake_tv):
    js = js_factory()
    assert await js.reachable() is True
    fake_tv.online = False
    assert await js.reachable() is False


async def test_lost_after_answering_is_wedged(js_factory, fake_tv):
    js = js_factory()
    await js.get("powerstate")
    fake_tv.online = False
    with pytest.raises(TvWedged):
        await js.get("powerstate")


async def test_wedge_detected_after_fast_requests(js_factory, fake_tv):
    fake_tv.wedge_after = 2
    fake_tv.wedge_interval = 1.0
    js = js_factory(interval=0.0)
    await js.get("powerstate")
    await js.get("powerstate")
    with pytest.raises(TvWedged):
        for _ in range(3):
            await js.get("powerstate")


async def test_three_404_on_known_paths_is_wedged(js_factory, fake_tv):
    js = js_factory()
    await js.get("powerstate")
    fake_tv.answer_404_everywhere = True
    await js.get("powerstate")
    await js.get("powerstate")
    with pytest.raises(TvWedged):
        await js.get("powerstate")


async def test_fast_context_restores_interval(js_factory):
    js = js_factory(interval=2.0)
    with js.fast(0.12):
        assert js.interval == 0.12
    assert js.interval == 2.0


async def test_ambilight_power_is_ignored_by_fake(js_factory, fake_tv):
    js = js_factory()
    await js.post("ambilight/power", {"power": "Off"})
    assert fake_tv.ambilight_led_on is True
    await js.post("menuitems/settings/update", {"values": [{"value": {"Nodeid": 200, "data": {"activenode_id": 210}}}]})
    assert fake_tv.ambilight_led_on is False
    current = await js.post("menuitems/settings/current", {"nodes": [{"nodeid": 200}]})
    assert current.data["values"][0]["value"]["data"]["activenode_id"] == 210


async def test_fake_list_node_uses_selected_item(js_factory, fake_tv):
    """Like the real TV: a list node (video variant 220) is read and written through selected_item."""
    js = js_factory()
    await js.post("menuitems/settings/update", {"values": [{"value": {"Nodeid": 220, "data": {"selected_item": 224}}}]})
    current = await js.post("menuitems/settings/current", {"nodes": [{"nodeid": 220}]})
    assert current.data["values"][0]["value"]["data"] == {"selected_item": 224}


async def test_notifychange_waits_for_change(js_factory, fake_tv):
    import asyncio

    js = js_factory(slow_threshold=5.0)

    async def change_later():
        await asyncio.sleep(0.2)
        fake_tv.trigger_change(volume=20)

    asyncio.create_task(change_later())
    response = await js.post("notifychange", {"notification": {"powerstate": {}}}, timeout=3.0)
    assert response.data["audio/volume"]["current"] == 20


async def test_duration_excludes_interval_wait(js_factory):
    js = js_factory(interval=0.3)
    await js.get("powerstate")
    second = await js.get("powerstate")
    assert second.duration < 0.15  # the interval wait is not counted


def test_no_unused_host_property(js_factory):
    assert not hasattr(js_factory(), "host")
