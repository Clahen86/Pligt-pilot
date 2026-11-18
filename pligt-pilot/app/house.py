"""Huset passer på: opgaver ud fra apparater, påmindelser og fødselsdage.

`step` er ren logik, så den kan testes uden Home Assistant.
"""
import datetime as dt
import logging
import threading

import outdoor
from store import DOOR_OPEN, SURPRISE_MINUTES

log = logging.getLogger('pligt')

RUNNING = {'on', 'running', 'washing', 'drying', 'active', 'in_use', 'working', 'cycle',
           'wash', 'dry', 'run', 'heating', 'rinse', 'spin', 'busy'}
STOPPED = {'off', 'idle', 'finished', 'done', 'complete', 'completed', 'ready', 'standby',
           'stopped', 'end', 'færdig', 'slut', 'clean'}
POWER_ON = 15.0     # watt: maskinen arbejder
POWER_OFF = 5.0     # watt: maskinen er stoppet
SETTLE_POWER = dt.timedelta(minutes=3)   # maskiner holder pause midt i et program
SETTLE_TEXT = dt.timedelta(seconds=30)
WEATHER_EVERY = dt.timedelta(minutes=5)
DOORS_EVERY = dt.timedelta(minutes=10)


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
        self.doors = {}         # sidste kendte tilstand for hver regels dørsensor
        self.weather_at = None
        self.doors_at = None
        self._stop = threading.Event()

    def tick(self):
        now = self.clock()
        self._weather(now)
        self.store.housekeeping()
        self._doors(now)
        self._rules(now)
        self._allowance()
        self._surprise()
        self._reminders()
        self._birthdays()
        self._summary()

    def _doors(self, now):
        """A machine rule without a door sensor gets one by itself, when exactly one fits the machine. Once: one the
        parent has removed again is not put back."""
        if self.doors_at and now - self.doors_at < DOORS_EVERY:
            return
        self.doors_at = now
        rules = [r for r in self.store.data['rules'] if not r.get('door') and not r.get('door_tried')]
        if not rules or not hasattr(self.ha, 'entities'):
            return
        ents = self.ha.entities()
        if not ents:
            return
        from store import machine_type
        for rule in rules:
            door = find_door(ents, machine_type(rule['name']))
            if door:
                self.store.auto_door(rule['id'], door)

    def _rules(self, now):
        rules = [r for r in self.store.data['rules'] if r['active']]
        if not rules:
            return
        values = self.ha.states([r['entity'] for r in rules] + [r['door'] for r in rules if r.get('door')])
        for rule in rules:
            self._door(rule, values.get(rule.get('door')) if rule.get('door') else None)
            if rule['entity'] not in values:
                continue
            if classify(values[rule['entity']]) == 'running':
                self.store.drop_open_job(rule_id=rule['id'])      # maskinen er startet igen
            self.states[rule['id']], done = step(self.states.get(rule['id']),
                                                 values[rule['entity']], now)
            if done:
                task = self.store.fire_rule(rule['id'])
                if task:
                    self.tell_kids('Ny opgave', '%s (%d kr.). Først til mølle!'
                                   % (task['title'], task['price']), task)

    def _weather(self, now):
        """Læser husets vejr hvert 5. minut. Svarer HA ikke, bruges det gemte (og det bliver for gammelt af sig selv)."""
        if self.weather_at and now - self.weather_at < WEATHER_EVERY:
            return
        self.weather_at = now
        if not hasattr(self.ha, 'weather'):
            return
        pairs = self.ha.weather()
        if pairs is None:
            return
        found = outdoor.pick_weather(pairs)
        self.store.set_weather(*(found or ('', '')))

    def _door(self, rule, value):
        """Lågen er åbnet (fra lukket til åben): maskinen bliver tømt, så den ledige opgave fjernes.

        'unavailable', 'unknown' og manglende værdier ignoreres, så en defekt sensor aldrig fjerner noget.
        """
        value = str(value).strip().lower() if value is not None else ''
        if value not in DOOR_OPEN + ('off', 'closed'):
            self.doors[rule['id']] = None       # glem den: næste 'on' tæller først efter et rigtigt 'off'
            return
        before = self.doors.get(rule['id'])
        self.doors[rule['id']] = value
        if value in DOOR_OPEN and before in ('off', 'closed'):
            self.store.drop_open_job(rule_id=rule['id'])

    def _allowance(self):
        for kid, text in self.store.allowance_notices():
            self.ha.notify_kid(kid, 'Lommepenge', text)

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
     'words': ['vaskemaskine', 'vask', 'washing', 'washer', 'laundry', 'waschmaschine', 'tvättmaskin', 'vaskemaskin'],
     'not': ['opvask', 'dishwasher', 'dryer', 'tørre', 'tumble', 'trockner', 'torktumlare', 'spül', 'diskmaskin', 'oppvask']},
    {'preset': 'Tørretumbler', 'title': 'Tag tøj ud af tørretumbleren og fold det', 'price': 8,
     'words': ['tørretumbler', 'toerretumbler', 'tørre', 'tumbler', 'dryer', 'tumble', 'trockner', 'torktumlare', 'tørketrommel'],
     'not': ['hair', 'hår', 'opvask', 'dishwasher']},
    {'preset': 'Opvaskemaskine', 'title': 'Tøm opvaskemaskinen', 'price': 5,
     'words': ['opvask', 'dishwasher', 'spülmaschine', 'diskmaskin', 'oppvask'], 'not': []},
]
BAD = ('energy', 'kwh', 'forbrug', 'total', 'update', 'battery', 'batteri', 'rssi', 'linkquality',
       'voltage', 'spænding', 'frequency', 'cost', 'price', 'pris', 'signal', 'uptime', 'temperature',
       'temperatur', 'reset', 'child_lock', 'børnesikring', 'restart')
DOMAINS = ('sensor.', 'binary_sensor.', 'switch.', 'input_boolean.')


def score_entity(row, words, not_words):
    """Hvor godt en enhed ligner måleren for en maskine. 0 betyder: ikke egnet."""
    ent, name, dclass, unit, area = (list(row) + ['', '', '', '', ''])[:5]
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


DOOR_CLASSES = ('door', 'opening', 'window', 'garage_door')
DOOR_WORDS = ('dør', 'door', 'låge', 'lage', 'luge', 'contact', 'kontakt')
NOT_DOOR = ('batteri', 'battery', 'problem', 'tamper', 'sabotage')


def find_door(entities, machine):
    """The door sensor (binary_sensor) on a machine type (washer, dryer, dishwasher) - only when exactly one fits.
    None when there is none or several: then the parent picks from the list."""
    from store import machine_type
    hits = []
    for row in entities:
        eid, name, dclass = row[0], row[1], row[2]
        if not eid.startswith('binary_sensor.'):
            continue
        text = (eid + ' ' + name).lower()
        if any(w in text for w in NOT_DOOR):
            continue
        if dclass not in DOOR_CLASSES and not any(w in text for w in DOOR_WORDS):
            continue
        kind = machine_type(name)
        if kind == 'other':
            kind = machine_type(eid)
        if kind == machine:
            hits.append(eid)
    return hits[0] if len(hits) == 1 else None


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
        pick = lambda r: {'entity': r[1][0], 'name': r[1][1], 'unit': r[1][3] if len(r[1]) > 3 else '',
                          'area': r[1][4] if len(r[1]) > 4 else ''}
        out.append({'preset': m['preset'], 'title': m['title'], 'price': m['price'],
                    'best': pick(ranked[0]), 'alts': [pick(r) for r in ranked[1:4]]})
    return out


def power_sensors(entities, limit=60):
    """Alle effektmålere i huset (watt), så man selv kan pege på dem, hvis navnene ikke passer."""
    out = []
    for row in entities:
        ent, name, dclass, unit, area = (list(row) + ['', '', '', '', ''])[:5]
        if ent.startswith('sensor.') and (dclass == 'power' or unit.lower() in ('w', 'kw')):
            out.append({'entity': ent, 'name': name, 'unit': unit, 'area': area})
    out.sort(key=lambda x: (x['area'] == '', x['area'].lower(), x['name'].lower()))
    return out[:limit]
