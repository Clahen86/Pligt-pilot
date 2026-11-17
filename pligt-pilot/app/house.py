"""Huset passer på: opgaver ud fra apparater, påmindelser og fødselsdage.

`step` er ren logik, så den kan testes uden Home Assistant.
"""
import datetime as dt
import logging
import threading

from store import SURPRISE_MINUTES

log = logging.getLogger('pligt')

RUNNING = {'on', 'running', 'washing', 'drying', 'active', 'in_use', 'working', 'cycle',
           'wash', 'dry', 'run', 'heating', 'rinse', 'spin', 'busy'}
STOPPED = {'off', 'idle', 'finished', 'done', 'complete', 'completed', 'ready', 'standby',
           'stopped', 'end', 'færdig', 'slut', 'clean'}
POWER_ON = 15.0     # watt: maskinen arbejder
POWER_OFF = 5.0     # watt: maskinen er stoppet
SETTLE_POWER = dt.timedelta(minutes=3)   # maskiner holder pause midt i et program
SETTLE_TEXT = dt.timedelta(seconds=30)


def _number(value):
    try:
        return float(str(value).replace(',', '.'))
    except ValueError:
        return None


def classify(value):
    """'running', 'stopped' eller None, hvis vi ikke kan afgøre det."""
    text = str(value or '').strip().lower()
    num = _number(text)
    if num is not None:
        return 'running' if num >= POWER_ON else 'stopped' if num < POWER_OFF else None
    if text in RUNNING:
        return 'running'
    if text in STOPPED:
        return 'stopped'
    return None


def step(state, value, now):
    """Opdaterer en regels tilstand. Returnerer (ny_tilstand, færdig).

    Færdig betyder: maskinen har kørt og har nu været stoppet længe nok.
    """
    state = dict(state or {'active': False, 'low_since': None})
    kind = classify(value)
    settle = SETTLE_POWER if _number(value) is not None else SETTLE_TEXT
    if kind == 'running':
        state.update(active=True, low_since=None)
        return state, False
    if kind == 'stopped' and state['active']:
        if state['low_since'] is None:
            state['low_since'] = now
            return state, False
        if now - state['low_since'] >= settle:
            return {'active': False, 'low_since': None}, True
    return state, False


class Automation:
    def __init__(self, store, ha, clock=None):
        self.store = store
        self.ha = ha
        self.clock = clock or dt.datetime.now
        self.states = {}
        self._stop = threading.Event()

    def tick(self):
        now = self.clock()
        self.store.housekeeping()
        self._rules(now)
        self._surprise()
        self._reminders()
        self._birthdays()
        self._summary()

    def _rules(self, now):
        rules = [r for r in self.store.data['rules'] if r['active']]
        if not rules:
            return
        values = self.ha.states([r['entity'] for r in rules])
        for rule in rules:
            if rule['entity'] not in values:
                continue
            self.states[rule['id']], done = step(self.states.get(rule['id']),
                                                 values[rule['entity']], now)
            if done:
                task = self.store.fire_rule(rule['id'])
                if task:
                    self.tell_kids('Ny opgave', '%s (%d kr.). Først til mølle!'
                                   % (task['title'], task['price']), task)

    def tell_kids(self, title, message, task=None):
        for kid in self.store.data['kids']:
            if not kid.get('paused') and (task is None or self.store._in_scope(task, kid)):
                self.ha.notify_kid(kid, title, message)

    def _surprise(self):
        task = self.store.due_surprise()
        if task:
            self.tell_kids('Overraskelse!', '%s: %d kr. (dobbelt pris) de næste %d minutter. Først til mølle!'
                           % (task['title'], task['price'], SURPRISE_MINUTES), task)

    def _reminders(self):
        for kid, n in self.store.due_reminders():
            self.ha.notify_kid(kid, 'Husk dine pligter',
                               'Du har %d opgave%s i dag.' % (n, '' if n == 1 else 'r'))

    def _birthdays(self):
        for kid, age in self.store.birthday_notices():
            self.ha.notify('Fødselsdag i morgen',
                           '%s fylder %d i morgen. Så får %s nye opgaver.' % (kid['name'], age, kid['name']))

    def _summary(self):
        text = self.store.weekly_summary()
        if text:
            self.ha.notify('Ugens pligter', text)

    def run(self, every=20):
        def loop():
            while not self._stop.wait(every):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001
                    log.exception('Fejl i husets automatik')
        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread


# ---- find måleren selv ---------------------------------------------------
MACHINES = [
    {'preset': 'Vaskemaskine', 'title': 'Flyt tøj fra vaskemaskinen til tørretumbleren', 'price': 5,
     'words': ['vaskemaskine', 'washing_machine', 'washer', 'vasker'], 'not': ['opvask', 'dishwasher']},
    {'preset': 'Tørretumbler', 'title': 'Tag tøj ud af tørretumbleren og fold det', 'price': 8,
     'words': ['tørretumbler', 'toerretumbler', 'tumbler', 'dryer', 'tumble'], 'not': ['hair', 'hår']},
    {'preset': 'Opvaskemaskine', 'title': 'Tøm opvaskemaskinen', 'price': 5,
     'words': ['opvaskemaskine', 'dishwasher', 'opvasker'], 'not': []},
]
BAD = ('energy', 'kwh', 'forbrug', 'total', 'update', 'battery', 'batteri', 'rssi', 'linkquality',
       'voltage', 'spænding', 'frequency', 'cost', 'price', 'pris', 'signal', 'uptime', 'temperature',
       'temperatur', 'reset', 'child_lock', 'børnesikring', 'restart')
DOMAINS = ('sensor.', 'binary_sensor.', 'switch.', 'input_boolean.')


def score_entity(row, words, not_words):
    """Hvor godt en enhed ligner måleren for en maskine. 0 betyder: ikke egnet."""
    ent, name, dclass, unit = (list(row) + ['', '', '', ''])[:4]
    text = (ent + ' ' + name).lower()
    if not ent.startswith(DOMAINS):
        return 0
    if not any(w in text for w in words) or any(w in text for w in not_words):
        return 0
    if any(b in text for b in BAD) or unit.lower() in ('kwh', 'wh', 'v', 'hz', '°c', '%', 'dbm'):
        return 0
    if dclass in ('energy', 'voltage', 'battery', 'temperature', 'signal_strength', 'timestamp'):
        return 0
    score = 10
    if dclass == 'power' or unit.lower() in ('w', 'kw'):
        score += 8                      # effektmåling fortæller bedst, om maskinen kører
    elif unit.lower() == 'a' or dclass == 'current':
        score += 4
    if ent.startswith('binary_sensor.') and any(w in text for w in ('running', 'kører', 'drift', 'active')):
        score += 7
    if ent.startswith('sensor.') and any(w in text for w in ('status', 'state', 'program', 'operation')):
        score += 5
    if ent.startswith(('switch.', 'input_boolean.')):
        score -= 6                      # en stikkontakt er tændt, uanset om maskinen kører
    return max(score, 1)


def find_sensors(entities, existing_names=()):
    """For hver maskine: den bedste måler og et par alternativer."""
    out = []
    for m in MACHINES:
        if m['preset'] in existing_names:
            continue
        ranked = []
        for row in entities:
            sc = score_entity(row, m['words'], m['not'])
            if sc:
                ranked.append((sc, row))
        ranked.sort(key=lambda x: (-x[0], x[1][0]))
        if not ranked:
            continue
        pick = lambda r: {'entity': r[1][0], 'name': r[1][1], 'unit': r[1][3] if len(r[1]) > 3 else ''}
        out.append({'preset': m['preset'], 'title': m['title'], 'price': m['price'],
                    'best': pick(ranked[0]), 'alts': [pick(r) for r in ranked[1:4]]})
    return out
