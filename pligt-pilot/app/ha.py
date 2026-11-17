"""Lille forbindelse til Home Assistant (valgfri).

Bruges til to ting:
- sende en notifikation til forælderen, når et barn melder en opgave færdig
- hente husets rum, så opgaveforslag passer til hjemmet

Alt er "best effort": fejler HA, virker appen stadig.
"""
import json
import logging
import re
import threading
import time
import urllib.request

log = logging.getLogger('pligt')
ENTITY = re.compile(r'^[a-z_]+\.[a-z0-9_]+$')


class HomeAssistant:
    def __init__(self, base_url=None, token=None, notify_service=''):
        self.base_url = (base_url or '').rstrip('/')
        self.token = token or ''
        self.notify_service = (notify_service or '').strip()
        self._ingress = None
        self._entities = []
        self._entities_at = 0.0

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

    def _get(self, url, timeout=8):
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8')

    def ingress_path(self):
        """Stien til appen i Home Assistant, så en notifikation kan åbne den."""
        if self._ingress is not None:
            return self._ingress
        path = ''
        if self.enabled and self.base_url.endswith('/core/api'):
            try:
                root = self.base_url[:-len('/core/api')]
                info = json.loads(self._get(root + '/addons/self/info'))
                slug = (info.get('data') or {}).get('slug')
                if slug and re.match(r'^[a-z0-9_]+$', slug):
                    path = '/hassio/ingress/' + slug
            except Exception as err:  # noqa: BLE001
                log.warning('Kunne ikke finde appens adresse: %s', err)
        self._ingress = path
        return path

    def notify_to(self, service, title, message, open_app=False):
        """Sender en notifikation i baggrunden. Svarer med det samme."""
        service = (service or '').strip()
        if not (self.enabled and service):
            return False
        if service.startswith('notify.'):
            service = service[len('notify.'):]

        def work():
            payload = {'title': title, 'message': message}
            if open_app:
                path = self.ingress_path()
                if path:
                    payload['data'] = {'url': path, 'clickAction': path}
            try:
                self._post('/services/notify/' + service, payload)
            except Exception as err:  # noqa: BLE001 - må aldrig vælte appen
                log.warning('Kunne ikke sende notifikation: %s', err)

        threading.Thread(target=work, daemon=True).start()
        return True

    def notify(self, title, message):
        """Notifikation til forælderen. Et tryk åbner appen."""
        return self.notify_to(self.notify_service, title, message, open_app=True)

    def entities(self):
        """[[entity_id, navn], ...] for alt i Home Assistant. Gemmes i et minut."""
        if not self.enabled:
            return []
        if self._entities and time.time() - self._entities_at < 60:
            return self._entities
        try:
            raw = self._post('/template', {'template':
                "{% set ns = namespace(r=[]) %}{% for s in states %}"
                "{% set ns.r = ns.r + [[s.entity_id, s.name]] %}{% endfor %}{{ ns.r | tojson }}"},
                timeout=15)
            self._entities = [[str(a), str(b)] for a, b in json.loads(raw)]
            self._entities_at = time.time()
        except Exception as err:  # noqa: BLE001
            log.warning('Kunne ikke hente enheder fra Home Assistant: %s', err)
        return self._entities

    def devices(self):
        """Navne og id'er på husets enheder, små bogstaver."""
        out = []
        for ent, name in self.entities():
            out += [ent.lower(), name.lower()]
        return out

    def states(self, entity_ids):
        """{entity_id: tilstand} for de angivne enheder."""
        ids = [e for e in entity_ids if ENTITY.match(e)]
        if not (self.enabled and ids):
            return {}
        try:
            expr = ', '.join("states('%s')" % e for e in ids)
            raw = self._post('/template', {'template': '{{ [%s] | tojson }}' % expr})
            return dict(zip(ids, [str(v) for v in json.loads(raw)]))
        except Exception as err:  # noqa: BLE001
            log.warning('Kunne ikke læse enheder fra Home Assistant: %s', err)
            return {}

    def celebrate(self, entity):
        """Får en lampe til at blinke grønt."""
        if not (self.enabled and entity and entity.startswith('light.') and ENTITY.match(entity)):
            return False

        def work():
            try:
                self._post('/services/light/turn_on', {
                    'entity_id': entity, 'flash': 'long', 'rgb_color': [0, 200, 80]})
            except Exception as err:  # noqa: BLE001
                log.warning('Kunne ikke styre lampen: %s', err)

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
