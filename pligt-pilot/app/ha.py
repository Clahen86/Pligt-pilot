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
import urllib.parse
import urllib.request

log = logging.getLogger('pligt')
ENTITY = re.compile(r'^[a-z_]+\.[a-z0-9_]+$')
NTFY_TOPIC = re.compile(r'^[-_A-Za-z0-9]{8,64}$')


class HomeAssistant:
    def __init__(self, base_url=None, token=None, notify_service='', ntfy_server='', public_url=''):
        self.base_url = (base_url or '').rstrip('/')
        self.token = token or ''
        self.notify_service = (notify_service or '').strip()
        self.ntfy_server = (ntfy_server or 'https://ntfy.sh').rstrip('/')
        self.public_url = (public_url or '').rstrip('/')
        self.pusher = None
        self.translator = None          # (barn eller None, tekst) -> tekst
        self._ingress = None
        self._local_ip = ''
        self._local_try = 0.0
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

    def local_ip(self):
        """Home Assistants adresse på hjemmenetværket, fx 192.168.1.50 (spørger Supervisor)."""
        if self._local_ip:
            return self._local_ip
        if time.time() - self._local_try < 60:      # spørg højst én gang i minuttet
            return ''
        self._local_try = time.time()
        ip = ''
        if self.enabled and self.base_url.endswith('/core/api'):
            try:
                root = self.base_url[:-len('/core/api')]
                info = json.loads(self._get(root + '/network/info'))
                ifaces = (info.get('data') or {}).get('interfaces') or []
                ifaces.sort(key=lambda i: not i.get('primary'))
                for iface in ifaces:
                    for addr in (iface.get('ipv4') or {}).get('address') or []:
                        cand = str(addr).split('/')[0]
                        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', cand) and not cand.startswith(('169.254.', '127.')):
                            ip = cand
                            break
                    if ip:
                        break
            except Exception as err:  # noqa: BLE001
                log.warning('Kunne ikke spørge Supervisor om netværksadressen: %s', err)
        if not ip and self.enabled:
            # reserve: den interne adresse, du har skrevet i Home Assistants egne indstillinger
            try:
                cfg = json.loads(self._get(self.base_url + '/config'))
                host = urllib.parse.urlsplit(cfg.get('internal_url') or '').hostname or ''
                if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', host) or host.endswith('.local'):
                    ip = host
            except Exception as err:  # noqa: BLE001
                log.warning('Kunne ikke læse Home Assistants interne adresse: %s', err)
        if ip:
            log.info('Hjemmenetværkets adresse: %s', ip)
        else:
            log.warning('Fandt ikke hjemmenetværkets adresse. Skriv den i public_url.')
        self._local_ip = ip
        return ip

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

    def ntfy(self, topic, title, message, click=None):
        """Sender en besked via ntfy (gratis app til telefonen). Svarer med det samme."""
        if not NTFY_TOPIC.match(topic or ''):
            return False
        payload = {'topic': topic, 'title': title, 'message': message}
        if click:
            payload['click'] = click

        def work():
            try:
                req = urllib.request.Request(
                    self.ntfy_server, data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}, method='POST')
                urllib.request.urlopen(req, timeout=10).read()
            except Exception as err:  # noqa: BLE001
                log.warning('Kunne ikke sende via ntfy: %s', err)

        threading.Thread(target=work, daemon=True).start()
        return True

    def notify_kid(self, kid, title, message):
        """Besked til et barn: via ntfy og/eller barnets notifikationstjeneste i HA."""
        title, message = self._tr(kid, title), self._tr(kid, message)
        sent = False
        click = '%s/k/%s/' % (self.public_url, kid['token']) if self.public_url else None
        if self.pusher and self.pusher.send_kid(kid, title, message, click):
            sent = True
        if kid.get('ntfy_on') and kid.get('ntfy'):
            sent = self.ntfy(kid['ntfy'], title, message, click) or sent
        if kid.get('notify'):
            sent = self.notify_to(kid['notify'], title, message) or sent
        return sent

    def _tr(self, kid, text):
        return self.translator(kid, text) if self.translator else text

    def notify(self, title, message):
        """Notifikation til forælderen. Et tryk åbner appen."""
        title, message = self._tr(None, title), self._tr(None, message)
        return self.notify_to(self.notify_service, title, message, open_app=True)

    def entities(self):
        """[[entity_id, navn, enhedstype, enhed, rum], ...] for alt i Home Assistant. Gemmes i et minut."""
        if not self.enabled:
            return []
        if self._entities and time.time() - self._entities_at < 60:
            return self._entities
        try:
            raw = self._post('/template', {'template':
                "{% set ns = namespace(r=[]) %}{% for s in states %}"
                "{% set ns.r = ns.r + [[s.entity_id, s.name, s.attributes.get('device_class', '') or '', "
                "s.attributes.get('unit_of_measurement', '') or '', area_name(s.entity_id) or '']] %}"
                "{% endfor %}{{ ns.r | tojson }}"},
                timeout=15)
            rows = []
            for row in json.loads(raw):
                row = [str(x) for x in row] + [''] * (5 - len(row))
                rows.append(row[:5])
            self._entities = rows
            self._entities_at = time.time()
        except Exception as err:  # noqa: BLE001
            log.warning('Kunne ikke hente enheder fra Home Assistant: %s', err)
        return self._entities

    def devices(self):
        """Navne og id'er på husets enheder, små bogstaver."""
        out = []
        for row in self.entities():
            out += [row[0].lower(), row[1].lower()]
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
