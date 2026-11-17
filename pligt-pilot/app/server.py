"""To små webservere i samme proces.

- børneserveren (port 8099): kun børnenes personlige links. Intet andet.
- forældreserveren (port 8100): hele appen. Nås kun gennem Home Assistants
  indbyggede panel (ingress), så HA's egen login beskytter den.
"""
import base64
import datetime as dt
import binascii
import json
import logging
import os
import re
import ssl
import struct
import threading
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import i18n
from house import find_sensors
from store import Problem
from suggestions import suggest

log = logging.getLogger('pligt')
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
MAX_BODY = 64 * 1024
MAX_PHOTO_BODY = 700 * 1024

PARENT = re.compile(r'^/p/([A-Za-z0-9_-]{8,64})(/.*)?$')
KID_PAGE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/?$')
KID_STATE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/state$')
KID_DONE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/items/([a-f0-9]{10})/done$')
KID_TRADE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/items/([a-f0-9]{10})/trade$')
KID_TRADE_END = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/trades/([a-f0-9]{10})/(accept|end)$')
KID_I18N = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/i18n$')
KID_BUY = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/rewards/([a-f0-9]{10})/buy$')
KID_UNBUY = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/claims/([a-f0-9]{10})/cancel$')
KID_WISH = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/wish$')
KID_CLAIM = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/tasks/([a-f0-9]{10})/claim$')

KID_FILE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/(sw\.js|manifest\.json|icon\.png)$')
KID_PUSH_KEY = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/push_key$')
KID_PUSH = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/push$')

ID = r'([a-f0-9]{10})'


def _icon_png(size=192):
    """Et lille ikon (gul flade med et flueben), lavet uden eksterne pakker."""
    sun, ink = (255, 194, 71), (34, 48, 74)
    pts = [(0.27, 0.53), (0.43, 0.69), (0.74, 0.33)]
    width = 0.075

    def dist(px, py, a, b):
        ax, ay, bx, by = a[0], a[1], b[0], b[1]
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5

    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            px, py = (x + 0.5) / size, (y + 0.5) / size
            hit = min(dist(px, py, pts[0], pts[1]), dist(px, py, pts[1], pts[2])) < width
            row += bytes(ink if hit else sun)
        rows.append(bytes(row))

    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))


ICON = _icon_png()


class App:
    def __init__(self, store, ha, options=None):
        self.store = store
        self.ha = ha
        self.options = options or {}
        self.vapid = None
        self.ha.translator = lambda kid, text: i18n.translate(store.lang_of(kid), text)


def _read(name):
    with open(os.path.join(WEB, name), 'rb') as f:
        return f.read()


def make_handler(app, role, allow_from=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'PligtPilot'
        sys_version = ''
        timeout = 20      # en hængende forbindelse må ikke blokere de andre

        def log_message(self, fmt, *args):
            log.debug('%s %s', role, fmt % args)

        # ---- svar ------------------------------------------------------
        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status=200):
            if getattr(self, 'via_parent', None) and isinstance(payload, dict) and 'parents' in payload:
                payload = dict(payload, parents=[])
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self._send(status, body, 'application/json; charset=utf-8')

        def _page(self, name):
            self._send(200, _read(name), 'text/html; charset=utf-8')

        def _problem(self, err):
            self._json({'error': err.message}, err.status)

        def _body(self, limit=MAX_BODY):
            length = int(self.headers.get('Content-Length') or 0)
            if length > limit:
                raise Problem('For stor forespørgsel', 413)
            if not length:
                return {}
            ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip()
            if ctype != 'application/json':
                raise Problem('Forkert type', 415)
            try:
                data = json.loads(self.rfile.read(length).decode('utf-8'))
            except ValueError:
                raise Problem('Kunne ikke læse forespørgslen')
            return data if isinstance(data, dict) else {}

        def _allowed(self):
            if not allow_from:
                return True
            return self.client_address[0] in allow_from

        # ---- indgang ---------------------------------------------------
        def do_GET(self):
            self._route('GET')

        def do_POST(self):
            self._route('POST')

        def _route(self, method):
            path, _, query = self.path.partition('?')
            self.query = urllib.parse.parse_qs(query)
            try:
                if not self._allowed():
                    return self._json({'error': 'Ikke tilladt'}, 403)
                if role == 'kid':
                    self._kid(method, path)
                else:
                    self._admin(method, path)
            except Problem as err:
                self._problem(err)
            except Exception:  # noqa: BLE001
                log.exception('Uventet fejl')
                self._json({'error': 'Noget gik galt'}, 500)

        # ---- børn ------------------------------------------------------
        def _kid(self, method, path):
            store = app.store
            m = PARENT.match(path)
            if m:
                parent = store.parent_by_token(m.group(1))
                if not parent:
                    return self._json({'error': 'Linket passer ikke'}, 404)
                if m.group(2) is None:
                    self.send_response(301)
                    self.send_header('Location', path + '/')
                    self.end_headers()
                    return
                self.via_parent = parent
                return self._admin(method, m.group(2))
            m = KID_PAGE.match(path)
            if m and method == 'GET':
                if not store.kid_by_token(m.group(1)):
                    return self._json({'error': 'Linket passer ikke'}, 404)
                if not path.endswith('/'):
                    self.send_response(301)
                    self.send_header('Location', path + '/')
                    self.end_headers()
                    return
                return self._page('kid.html')
            m = KID_FILE.match(path)
            if m and method == 'GET':
                kid = store.kid_by_token(m.group(1))
                if not kid:
                    return self._json({'error': 'Linket passer ikke'}, 404)
                name = m.group(2)
                if name == 'sw.js':
                    return self._send(200, _read('sw.js'), 'application/javascript; charset=utf-8')
                if name == 'icon.png':
                    return self._send(200, ICON, 'image/png')
                manifest = {'name': 'Pligter', 'short_name': kid['name'][:12], 'start_url': './',
                            'scope': './', 'display': 'standalone', 'lang': 'da',
                            'background_color': '#FFF6E9', 'theme_color': kid['color'],
                            'icons': [{'src': 'icon.png', 'sizes': '192x192', 'type': 'image/png',
                                       'purpose': 'any'}]}
                return self._send(200, json.dumps(manifest).encode('utf-8'),
                                  'application/manifest+json')
            m = KID_PUSH_KEY.match(path)
            if m and method == 'GET':
                if not store.kid_by_token(m.group(1)):
                    return self._json({'error': 'Linket passer ikke'}, 404)
                if not app.vapid:
                    return self._json({'error': 'Beskeder er ikke slået til'}, 404)
                return self._json({'key': app.vapid.public})
            m = KID_PUSH.match(path)
            if m and method == 'POST':
                body = self._body()
                store.add_push(m.group(1), body.get('subscription'))
                return self._json({'ok': True})
            m = KID_I18N.match(path)
            if m and method == 'GET':
                kid = store.kid_by_token(m.group(1))
                if not kid:
                    return self._json({'error': 'Linket passer ikke'}, 404)
                lang = store.lang_of(kid)
                return self._json({'lang': lang, 'locale': i18n.LOCALES[lang], 'table': i18n.table(lang)})
            m = KID_STATE.match(path)
            if m and method == 'GET':
                store.touch(m.group(1))
                return self._json(store.kid_view(m.group(1)))
            m = KID_DONE.match(path)
            if m and method == 'POST':
                body = self._body(MAX_PHOTO_BODY)
                photo = None
                if body.get('image'):
                    try:
                        photo = base64.b64decode(str(body['image']), validate=True)
                    except (binascii.Error, ValueError):
                        raise Problem('Billedet kunne ikke læses')
                kid, item = store.mark_done(m.group(1), m.group(2), photo)
                app.ha.notify(
                    'Pligt-pilot',
                    '%s er færdig med: %s (%d kr.). Åbn Pligter for at godkende.'
                    % (kid['name'], item['title'], item['price']))
                return self._json(store.kid_view(m.group(1)))
            m = KID_TRADE.match(path)
            if m and method == 'POST':
                body = self._body()
                kid, receiver, trade, item = store.offer_trade(m.group(1), m.group(2), body.get('to'),
                                                               body.get('amount', 0))
                text = '%s vil give dig: %s' % (kid['name'], item['title'])
                if trade['amount']:
                    text += ' og betaler %d kr.' % trade['amount']
                app.ha.notify_kid(receiver, 'Bytte', text)
                return self._json(store.kid_view(m.group(1)))
            m = KID_TRADE_END.match(path)
            if m and method == 'POST':
                self._body()
                if m.group(3) == 'accept':
                    sender, kid, item = store.accept_trade(m.group(1), m.group(2))
                    app.ha.notify_kid(sender, 'Bytte', '%s tog imod: %s' % (kid['name'], item['title']))
                else:
                    store.end_trade(m.group(1), m.group(2))
                return self._json(store.kid_view(m.group(1)))
            m = KID_BUY.match(path)
            if m and method == 'POST':
                self._body()
                kid, claim = store.buy_reward(m.group(1), m.group(2))
                app.ha.notify('Pligt-pilot', '%s vil bruge %d kr. på: %s. Åbn Pligter for at svare.'
                              % (kid['name'], claim['price'], claim['title']))
                return self._json(store.kid_view(m.group(1)))
            m = KID_UNBUY.match(path)
            if m and method == 'POST':
                self._body()
                store.cancel_claim(m.group(1), m.group(2))
                return self._json(store.kid_view(m.group(1)))
            m = KID_WISH.match(path)
            if m and method == 'POST':
                body = self._body()
                kid = store.make_wish(m.group(1), body.get('title'), body.get('price'))
                if kid.get('wish'):
                    app.ha.notify('Pligt-pilot', '%s ønsker sig: %s (%d kr.). Åbn Pligter for at svare.'
                                  % (kid['name'], kid['wish']['title'], kid['wish']['price']))
                return self._json(store.kid_view(m.group(1)))
            m = KID_CLAIM.match(path)
            if m and method == 'POST':
                self._body()
                store.claim(m.group(1), m.group(2))
                return self._json(store.kid_view(m.group(1)))
            if path in ('/', '/health') and method == 'GET':
                return self._send(200, 'Åbn dit personlige link.'.encode('utf-8'),
                                  'text/plain; charset=utf-8')
            self._json({'error': 'Findes ikke'}, 404)

        # ---- forældre --------------------------------------------------
        def _admin(self, method, path):
            store = app.store
            via = getattr(self, 'via_parent', None)
            if via and (path == '/api/backup' or path.startswith('/api/parents')):
                return self._json({'error': 'Ikke tilladt'}, 403)
            if method == 'GET':
                if path in ('/', '/index.html'):
                    return self._page('admin.html')
                if path == '/api/state':
                    state = store.admin_state()
                    state['public_url'] = app.options.get('public_url', '')
                    state['notify_on'] = bool(app.ha.enabled and app.ha.notify_service)
                    state['kid_https'] = bool(app.options.get('https'))
                    ip = app.ha.local_ip()
                    state['local_url'] = ('%s://%s:%d' % ('https' if app.options.get('https') else 'http',
                                                          ip, app.options.get('kid_port', 8099))) if ip else ''
                    state['push_on'] = bool(app.vapid)
                    state['via_link'] = bool(via)
                    if via:
                        state['parents'] = []
                        state['parent_name'] = via['name']
                    return self._json(state)
                if path == '/api/backup':
                    name = 'pligt-pilot-%s.json' % dt.date.today().isoformat()
                    body = store.backup()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Disposition', 'attachment; filename="%s"' % name)
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                    return
                m = re.match(r'^/photo/' + ID + r'$', path)
                if m:
                    data = store.photo(m.group(1))
                    if not data:
                        return self._json({'error': 'Findes ikke'}, 404)
                    return self._send(200, data, 'image/jpeg')
                if path == '/api/house_find':
                    names = [r['name'] for r in store.data['rules']]
                    return self._json({'found': find_sensors(app.ha.entities(), names),
                                       'on': app.ha.enabled and bool(app.ha.entities())})
                if path == '/api/fairness':
                    q = self.query
                    one = lambda k, d='': (q.get(k) or [d])[0]
                    return self._json(store.fairness(one('price'), one('repeat', 'daily'),
                                                     one('times', '1'), one('skip') or None))
                if path == '/api/i18n':
                    lang = store.lang_of()
                    return self._json({'lang': lang, 'locale': i18n.LOCALES[lang], 'table': i18n.table(lang)})
                if path == '/api/entities':
                    return self._json({'entities': app.ha.entities(), 'on': app.ha.enabled})
                if path == '/api/suggestions':
                    s = store.admin_state()
                    rows = suggest(app.ha.areas(), [k['age'] for k in s['kids']],
                                   [t['title'] for t in s['tasks']], app.ha.devices())
                    lang = store.lang_of()
                    for r in rows:
                        r['title'] = i18n.translate(lang, r['title'])
                        r['room'] = i18n.translate(lang, r.get('room', ''))
                        if store.has_task_titled(r['title']):
                            r['exists'], r['on'] = True, False
                    return self._json({'rows': rows})
                return self._json({'error': 'Findes ikke'}, 404)

            body = self._body()
            if path == '/api/kids':
                store.add_kid(body.get('name'), body.get('age'), body.get('color'), body.get('birthday'))
                return self._json(store.admin_state())
            m = re.match(r'^/api/kids/' + ID + r'$', path)
            if m:
                store.update_kid(m.group(1), body.get('name'), body.get('age'),
                                 body.get('color'), body.get('paused'), body.get('birthday'),
                                 body.get('notify'), body.get('allowance'), body.get('ntfy_on'),
                                 body.get('lang'))
                return self._json(store.admin_state())
            m = re.match(r'^/api/kids/' + ID + r'/test$', path)
            if m:
                kid = store._kid(m.group(1))
                if not app.ha.notify_kid(kid, 'Pligt-pilot', 'Det virker! Her kommer dine beskeder.'):
                    raise Problem('Slå beskeder til og gem først')
                return self._json(store.admin_state())
            m = re.match(r'^/api/kids/' + ID + r'/goal$', path)
            if m:
                store.set_goal(m.group(1), body.get('title'), body.get('amount'))
                return self._json(store.admin_state())
            m = re.match(r'^/api/items/' + ID + r'/undo$', path)
            if m:
                store.undo(m.group(1))
                return self._json(store.admin_state())
            m = re.match(r'^/api/kids/' + ID + r'/(delete|payout|newlink)$', path)
            if m:
                kid_id, action = m.groups()
                if action == 'delete':
                    store.delete_kid(kid_id)
                elif action == 'payout':
                    store.payout(kid_id)
                else:
                    store.new_token(kid_id)
                return self._json(store.admin_state())
            if path == '/api/tasks':
                store.add_task(body.get('title'), body.get('price', 0), body.get('room', ''),
                               body.get('repeat', 'daily'), body.get('open', False),
                               body.get('kids'), body.get('age_min', 0),
                               body.get('age_max', 99), body.get('times', 1),
                               body.get('photo', False), None, body.get('season', ''),
                               body.get('surprise', False))
                if body.get('open'):
                    task = store.data['tasks'][-1]
                    for kid in store.data['kids']:
                        if not kid.get('paused') and store._in_scope(task, kid):
                            app.ha.notify_kid(kid, 'Ny opgave',
                                              '%s (%d kr.). Først til mølle!' % (task['title'], task['price']))
                return self._json(store.admin_state())
            m = re.match(r'^/api/tasks/' + ID + r'$', path)
            if m:
                allowed = ('title', 'price', 'room', 'repeat', 'open', 'active', 'kids', 'age_min', 'times', 'photo', 'season',
                           'surprise')
                store.update_task(m.group(1), **{k: v for k, v in body.items() if k in allowed})
                return self._json(store.admin_state())
            m = re.match(r'^/api/tasks/' + ID + r'/delete$', path)
            if m:
                store.delete_task(m.group(1))
                return self._json(store.admin_state())
            if path == '/api/pay_all':
                store.pay_all()
                return self._json(store.admin_state())
            if path == '/api/rewards':
                store.add_reward(body.get('title'), body.get('price'))
                return self._json(store.admin_state())
            if path == '/api/rewards/examples':
                store.add_reward_examples()
                return self._json(store.admin_state())
            m = re.match(r'^/api/rewards/' + ID + r'/delete$', path)
            if m:
                store.delete_reward(m.group(1))
                return self._json(store.admin_state())
            m = re.match(r'^/api/claims/' + ID + r'/(approve|reject)$', path)
            if m:
                approve = m.group(2) == 'approve'
                claim = store.decide_claim(m.group(1), approve)
                kid = next((k for k in store.data['kids'] if k['id'] == claim['kid_id']), None)
                if kid:
                    app.ha.notify_kid(kid, 'Pligt-pilot', 'Du fik lov: %s!' % claim['title'] if approve
                                      else 'Ikke i dag: %s' % claim['title'])
                return self._json(store.admin_state())
            m = re.match(r'^/api/kids/' + ID + r'/wish/(accept|reject)$', path)
            if m:
                kid, wish = store.decide_wish(m.group(1), m.group(2) == 'accept')
                if wish:
                    app.ha.notify_kid(kid, 'Pligt-pilot', 'Dit ønske er et mål nu: %s!' % wish['title']
                                      if m.group(2) == 'accept' else 'Ønsket blev ikke til noget: %s' % wish['title'])
                return self._json(store.admin_state())
            if path == '/api/parents':
                store.add_parent(body.get('name'))
                return self._json(store.admin_state())
            m = re.match(r'^/api/parents/' + ID + r'/(delete|newlink)$', path)
            if m:
                if m.group(2) == 'delete':
                    store.delete_parent(m.group(1))
                else:
                    store.renew_parent(m.group(1))
                return self._json(store.admin_state())
            if path == '/api/starter':
                store.add_starter_pack()
                return self._json(store.admin_state())
            if path == '/api/approve_all':
                for item in store.decide_all():
                    kid = next((k for k in store.data['kids'] if k['id'] == item['kid_id']), None)
                    if kid:
                        app.ha.notify_kid(kid, 'Pligt-pilot', 'Godkendt: %s. Du fik %d kr.!'
                                          % (item['title'], item['price']))
                return self._json(store.admin_state())
            m = re.match(r'^/api/tasks/' + ID + r'/duplicate$', path)
            if m:
                store.duplicate_task(m.group(1))
                return self._json(store.admin_state())
            m = re.match(r'^/api/items/' + ID + r'/(approve|reject)$', path)
            if m:
                approve = m.group(2) == 'approve'
                item = store.decide(m.group(1), approve)
                kid = next((k for k in store.data['kids'] if k['id'] == item['kid_id']), None)
                if kid:
                    app.ha.notify_kid(kid, 'Pligt-pilot',
                                      'Godkendt: %s. Du fik %d kr.!' % (item['title'], item['price'])
                                      if approve else 'Prøv igen: %s' % item['title'])
                if approve:
                    app.ha.celebrate(store.data['settings'].get('celebrate_light'))
                return self._json(store.admin_state())
            if path == '/api/hero_bonus':
                store.pay_hero_bonus()
                return self._json(store.admin_state())
            if path == '/api/settings':
                for key in ('goal', 'hero_bonus', 'penalty', 'perfect_bonus',
                            'reminder_time', 'celebrate_light', 'boss_hp', 'boss_bonus', 'trading', 'weekly_summary', 'streak_bonus', 'lang'):
                    if key in body:
                        store.set_setting(key, body[key])
                if 'family_title' in body or 'family_amount' in body:
                    store.set_family_goal(body.get('family_title'), body.get('family_amount'))
                return self._json(store.admin_state())
            if path == '/api/boss_bonus':
                store.pay_boss_bonus()
                return self._json(store.admin_state())
            m = re.match(r'^/api/perfect/' + ID + r'$', path)
            if m:
                store.pay_perfect(m.group(1))
                return self._json(store.admin_state())
            if path == '/api/rules':
                store.add_rule(body.get('name'), body.get('entity'), body.get('title'),
                               body.get('price', 0))
                return self._json(store.admin_state())
            m = re.match(r'^/api/rules/' + ID + r'$', path)
            if m:
                store.update_rule(m.group(1), body.get('active'))
                return self._json(store.admin_state())
            m = re.match(r'^/api/rules/' + ID + r'/delete$', path)
            if m:
                store.delete_rule(m.group(1))
                return self._json(store.admin_state())
            if path == '/api/setup':
                rows = body.get('rows')
                if not isinstance(rows, list):
                    raise Problem('Ingen opgaver at oprette')
                for r in rows[:100]:
                    if not isinstance(r, dict) or store.has_task_titled(r.get('title')):
                        continue
                    store.add_task(r.get('title'), r.get('price', 0), r.get('room', ''),
                                   r.get('repeat', 'daily'), False, None,
                                   r.get('age_min', 0), 99, r.get('times', 1), False, None,
                                   r.get('season', ''))
                return self._json(store.admin_state())
            self._json({'error': 'Findes ikke'}, 404)

    return Handler


def make_tls(certfile, keyfile):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile, keyfile)
    return ctx


def serve(app, role, port, allow_from=None, host='0.0.0.0', tls=None):
    """Starter en server i en baggrundstråd. Returnerer (server, tråd).

    Med `tls` (en SSLContext) tales der https. Håndtrykket sker i den enkelte
    forbindelses egen tråd, så en hængende klient ikke blokerer de andre.
    """
    server = ThreadingHTTPServer((host, port), make_handler(app, role, allow_from))
    server.daemon_threads = True
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True,
                                        do_handshake_on_connect=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
