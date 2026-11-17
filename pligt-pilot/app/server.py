"""To små webservere i samme proces.

- børneserveren (port 8099): kun børnenes personlige links. Intet andet.
- forældreserveren (port 8100): hele appen. Nås kun gennem Home Assistants
  indbyggede panel (ingress), så HA's egen login beskytter den.
"""
import json
import logging
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from store import Problem
from suggestions import suggest

log = logging.getLogger('pligt')
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
MAX_BODY = 64 * 1024

KID_PAGE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/?$')
KID_STATE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/state$')
KID_DONE = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/items/([a-f0-9]{10})/done$')
KID_CLAIM = re.compile(r'^/k/([A-Za-z0-9_-]{8,64})/api/tasks/([a-f0-9]{10})/claim$')

ID = r'([a-f0-9]{10})'


class App:
    def __init__(self, store, ha, options=None):
        self.store = store
        self.ha = ha
        self.options = options or {}


def _read(name):
    with open(os.path.join(WEB, name), 'rb') as f:
        return f.read()


def make_handler(app, role, allow_from=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'PligtPilot'
        sys_version = ''

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
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self._send(status, body, 'application/json; charset=utf-8')

        def _page(self, name):
            self._send(200, _read(name), 'text/html; charset=utf-8')

        def _problem(self, err):
            self._json({'error': err.message}, err.status)

        def _body(self):
            length = int(self.headers.get('Content-Length') or 0)
            if length > MAX_BODY:
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
            path = self.path.split('?', 1)[0]
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
            m = KID_STATE.match(path)
            if m and method == 'GET':
                return self._json(store.kid_view(m.group(1)))
            m = KID_DONE.match(path)
            if m and method == 'POST':
                self._body()
                kid, item = store.mark_done(m.group(1), m.group(2))
                app.ha.notify(
                    'Pligt-pilot',
                    '%s er færdig med: %s (%d kr.). Åbn Pligter for at godkende.'
                    % (kid['name'], item['title'], item['price']))
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
            if method == 'GET':
                if path in ('/', '/index.html'):
                    return self._page('admin.html')
                if path == '/api/state':
                    state = store.admin_state()
                    state['public_url'] = app.options.get('public_url', '')
                    state['notify_on'] = bool(app.ha.enabled and app.ha.notify_service)
                    return self._json(state)
                if path == '/api/suggestions':
                    s = store.admin_state()
                    rows = suggest(app.ha.areas(), [k['age'] for k in s['kids']],
                                   [t['title'] for t in s['tasks']], app.ha.devices())
                    return self._json({'rows': rows})
                return self._json({'error': 'Findes ikke'}, 404)

            body = self._body()
            if path == '/api/kids':
                store.add_kid(body.get('name'), body.get('age'), body.get('color'))
                return self._json(store.admin_state())
            m = re.match(r'^/api/kids/' + ID + r'$', path)
            if m:
                store.update_kid(m.group(1), body.get('name'), body.get('age'),
                                 body.get('color'), body.get('paused'))
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
                               body.get('age_max', 99), body.get('times', 1))
                return self._json(store.admin_state())
            m = re.match(r'^/api/tasks/' + ID + r'$', path)
            if m:
                allowed = ('title', 'price', 'room', 'repeat', 'open', 'active', 'kids', 'age_min', 'times')
                store.update_task(m.group(1), **{k: v for k, v in body.items() if k in allowed})
                return self._json(store.admin_state())
            m = re.match(r'^/api/tasks/' + ID + r'/delete$', path)
            if m:
                store.delete_task(m.group(1))
                return self._json(store.admin_state())
            m = re.match(r'^/api/items/' + ID + r'/(approve|reject)$', path)
            if m:
                store.decide(m.group(1), m.group(2) == 'approve')
                return self._json(store.admin_state())
            if path == '/api/hero_bonus':
                store.pay_hero_bonus()
                return self._json(store.admin_state())
            if path == '/api/settings':
                for key in ('goal', 'hero_bonus'):
                    if key in body:
                        store.set_setting(key, body[key])
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
                                   r.get('age_min', 0), 99, r.get('times', 1))
                return self._json(store.admin_state())
            self._json({'error': 'Findes ikke'}, 404)

    return Handler


def serve(app, role, port, allow_from=None, host='0.0.0.0'):
    """Starter en server i en baggrundstråd. Returnerer (server, tråd)."""
    server = ThreadingHTTPServer((host, port), make_handler(app, role, allow_from))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
