"""Lille forbindelse til Home Assistant (valgfri).

Bruges til to ting:
- sende en notifikation til forælderen, når et barn melder en opgave færdig
- hente husets rum, så opgaveforslag passer til hjemmet

Alt er "best effort": fejler HA, virker appen stadig.
"""
import json
import logging
import threading
import urllib.request

log = logging.getLogger('pligt')


class HomeAssistant:
    def __init__(self, base_url=None, token=None, notify_service=''):
        self.base_url = (base_url or '').rstrip('/')
        self.token = token or ''
        self.notify_service = (notify_service or '').strip()

    @property
    def enabled(self):
        return bool(self.base_url and self.token)

    def _post(self, path, payload, timeout=8):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.token,
                     'Content-Type': 'application/json'},
            method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8')

    def notify(self, title, message):
        """Sender en notifikation i baggrunden. Svarer med det samme."""
        if not (self.enabled and self.notify_service):
            return False
        service = self.notify_service
        if service.startswith('notify.'):
            service = service[len('notify.'):]

        def work():
            try:
                self._post('/services/notify/' + service,
                           {'title': title, 'message': message})
            except Exception as err:  # noqa: BLE001 - må aldrig vælte appen
                log.warning('Kunne ikke sende notifikation: %s', err)

        threading.Thread(target=work, daemon=True).start()
        return True

    def areas(self):
        """Husets rum, fx ['Køkken', 'Stue']. Tom liste, hvis HA ikke svarer."""
        if not self.enabled:
            return []
        try:
            raw = self._post('/template', {
                'template': "{{ areas() | map('area_name') | list | tojson }}"})
            names = json.loads(raw)
            return [str(n) for n in names if n]
        except Exception as err:  # noqa: BLE001
            log.warning('Kunne ikke hente rum fra Home Assistant: %s', err)
            return []
