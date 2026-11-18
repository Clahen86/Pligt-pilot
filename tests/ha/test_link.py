"""The Home Assistant side: the children's links pass through /pligter to the add-on (here its real server)."""

import os
import sys

from pytest_homeassistant_custom_component.common import MockConfigEntry

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "pligt-pilot", "app"))

from ha import HomeAssistant as AddonHA  # noqa: E402
from server import App, serve  # noqa: E402
from store import Store  # noqa: E402

DOMAIN = "pligt_pilot"


async def _setup(hass, monkeypatch):
    store = Store(None)
    app = App(store, AddonHA())
    srv, thread = serve(app, "kid", 0, host="127.0.0.1")
    srv.thread = thread
    kid = store.add_kid("Emil", 8)
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "127.0.0.1"}, unique_id=DOMAIN)
    entry.add_to_hass(hass)

    async def hello(self, *_):
        self.base = "http://127.0.0.1:%d" % srv.server_address[1]
    monkeypatch.setattr("custom_components.pligt_pilot.Link.hello", hello)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return srv, kid


async def test_kid_link_passes_through(hass, hass_client_no_auth, monkeypatch):
    srv, kid = await _setup(hass, monkeypatch)
    client = await hass_client_no_auth()
    try:
        r = await client.get("/pligter/k/%s" % kid["token"], allow_redirects=False)
        assert r.status == 301 and r.headers["Location"] == kid["token"] + "/"
        r = await client.get("/pligter/k/%s/" % kid["token"])
        assert r.status == 200 and "beforeinstallprompt" in await r.text()
        r = await client.get("/pligter/k/%s/api/state" % kid["token"])
        assert r.status == 200 and (await r.json())["kid"]["name"] == "Emil"
        r = await client.get("/pligter/k/%s/manifest.json" % kid["token"])
        assert r.status == 200 and r.headers["Content-Type"].startswith("application/manifest+json")
        r = await client.get("/pligter/k/wrongtoken123/api/state")
        assert r.status == 404
    finally:
        srv.shutdown()
        srv.server_close()
        srv.thread.join()


async def test_nothing_else_in_the_addon_can_be_reached(hass, hass_client_no_auth, monkeypatch):
    srv, _ = await _setup(hass, monkeypatch)
    client = await hass_client_no_auth()
    try:
        for path in ("/pligter/_ha/hello", "/pligter/api/state", "/pligter/k/../api/backup", "/pligter/"):
            assert (await client.get(path)).status == 404, path
    finally:
        srv.shutdown()
        srv.server_close()
        srv.thread.join()


async def test_outside_address_is_cloud_first(hass, monkeypatch):
    from custom_components.pligt_pilot import Link
    link = Link(hass, "x")
    assert link.outside() == ""
    await hass.config.async_update(external_url="https://hjem.example.com")
    assert link.outside() == "https://hjem.example.com/pligter"

