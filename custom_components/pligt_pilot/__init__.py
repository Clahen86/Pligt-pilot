"""Pligt-pilot away from home: Home Assistant passes the children's and parents' links on to the add-on.

The links then work wherever Home Assistant can be reached - through Nabu Casa or Home Assistant's own outside
address - without a port of their own. No login: the token in the link is the key, just as at home.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import os
import re

import aiohttp
from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.network import NoURLAvailableError, get_url

_LOGGER = logging.getLogger(__name__)
DOMAIN = "pligt_pilot"
PREFIX = "/pligter"
PORT = 8099
PATH = re.compile(r"^(k|p)/[A-Za-z0-9_-]{8,64}(/[A-Za-z0-9_.-]+)*/?$")  # only the links - nothing else in the add-on
TO_ADDON = ("Content-Type", "Accept", "Accept-Language")
TO_BROWSER = ("Content-Type", "Cache-Control", "Location", "Content-Disposition")
MAX_BODY = 1024 * 1024
BRIDGED = ("hus_chat_machine", "madplan_cook")  # events from Hus-chat and Madplan that the add-on acts on


async def find_addon(hass: HomeAssistant) -> str | None:
    """The add-on's name on the Supervisor's network: its slug with - for _ (e.g. 1fb5ace7-pligt-pilot)."""
    sup, token = os.environ.get("SUPERVISOR"), os.environ.get("SUPERVISOR_TOKEN")
    if not sup or not token:
        return None
    try:
        async with async_get_clientsession(hass).get(f"http://{sup}/addons", headers={"Authorization": f"Bearer {token}"},
                                                      timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None
    for addon in (data.get("data") or {}).get("addons") or []:
        slug = addon.get("slug") or ""
        if slug == "pligt_pilot" or slug.endswith("_pligt_pilot"):
            return slug.replace("_", "-")
    return None


class Link:
    """The way to the add-on, and the outside address it should put in the links."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        self.hass, self.host, self.base = hass, host, None

    def outside(self) -> str:
        try:
            return get_url(self.hass, allow_internal=False, prefer_cloud=True).rstrip("/") + PREFIX
        except NoURLAvailableError:
            return ""  # no Nabu Casa and no outside address: the links stay as they are

    async def hello(self, *_: object) -> None:
        """Find the add-on (https when it has a certificate) and tell it the outside address."""
        session = async_get_clientsession(self.hass, verify_ssl=False)
        for scheme in ("https", "http"):
            base = f"{scheme}://{self.host}:{PORT}"
            try:
                async with session.get(f"{base}/_ha/hello", headers={"X-Pligt-Outside": self.outside()},
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        self.base = base
                        return
            except (aiohttp.ClientError, asyncio.TimeoutError):
                continue
        self.base = None

    async def send_event(self, event_type: str, data: dict) -> None:
        """Pass an event from Home Assistant's bus on to the add-on. Quietly does nothing when it can't."""
        if not self.base:
            await self.hello()
        if not self.base:
            return
        try:
            async with async_get_clientsession(self.hass, verify_ssl=False).post(
                    f"{self.base}/_ha/event", json={"event": event_type, "data": data},
                    headers={"X-Pligt-Outside": self.outside()}, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    _LOGGER.debug("Pligt-pilot answered %s to %s", r.status, event_type)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.base = None  # found again next time
        except Exception:  # noqa: BLE001 - never break the event bus
            _LOGGER.debug("Could not pass %s on to Pligt-pilot", event_type, exc_info=True)


class PligtView(HomeAssistantView):
    """/pligter/k/<token>/... and /pligter/p/<token>/... - passed on to the add-on as they are."""

    url = PREFIX + "/{path:.*}"
    name = "pligt_pilot:links"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def _pass(self, request: web.Request, path: str) -> web.Response:
        link: Link | None = self.hass.data.get(DOMAIN)
        if link is None or not PATH.match(path) or ".." in path:
            return web.Response(status=404, text="Not found")
        if not link.base:
            await link.hello()
        if not link.base:
            return web.Response(status=503, text="Pligt-pilot is not running")
        body = None
        if request.method == "POST":
            if (request.content_length or 0) > MAX_BODY:
                return web.Response(status=413, text="Too big")
            body = await request.read()
        headers = {k: request.headers[k] for k in TO_ADDON if k in request.headers}
        headers["X-Pligt-Outside"] = link.outside()
        url = f"{link.base}/{path}" + (f"?{request.query_string}" if request.query_string else "")
        try:
            async with async_get_clientsession(self.hass, verify_ssl=False).request(
                    request.method, url, data=body, headers=headers, allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.read()
                out = {k: r.headers[k] for k in TO_BROWSER if k in r.headers}
                status = r.status
        except (aiohttp.ClientError, asyncio.TimeoutError):
            link.base = None  # restarted or moved: found again on the next request
            return web.Response(status=502, text="Pligt-pilot did not answer")
        if out.get("Location", "").startswith("/"):
            out["Location"] = PREFIX + out["Location"]
        out["X-Robots-Tag"] = "noindex"
        return web.Response(status=status, body=data, headers=out)

    async def get(self, request: web.Request, path: str) -> web.Response:
        return await self._pass(request, path)

    async def post(self, request: web.Request, path: str) -> web.Response:
        return await self._pass(request, path)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    link = hass.data[DOMAIN] = Link(hass, entry.data["host"])
    if not hass.data.get(f"{DOMAIN}_view"):  # a view can't be removed again: registered once
        hass.http.register_view(PligtView(hass))
        hass.data[f"{DOMAIN}_view"] = True
    entry.async_create_background_task(hass, link.hello(), "pligt_pilot hello")
    entry.async_on_unload(async_track_time_interval(hass, link.hello, timedelta(minutes=30)))

    @callback
    def _bridge(event: Event) -> None:
        hass.async_create_background_task(link.send_event(event.event_type, dict(event.data)),
                                          f"pligt_pilot {event.event_type}")

    for event_type in BRIDGED:
        entry.async_on_unload(hass.bus.async_listen(event_type, _bridge))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.pop(DOMAIN, None)  # the view stays, but answers 404 until set up again
    return True
