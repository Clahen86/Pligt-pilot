"""Huset passer på: opgaver ud fra apparater, påmindelser og fødselsdage.

`step` er ren logik, så den kan testes uden Home Assistant.
"""
import datetime as dt
import logging
import threading

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
        self._reminders()
        self._birthdays()

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
            if kid.get('notify') and not kid.get('paused') and (
                    task is None or self.store._in_scope(task, kid)):
                self.ha.notify_to(kid['notify'], title, message)

    def _reminders(self):
        for kid, n in self.store.due_reminders():
            if kid.get('notify'):
                self.ha.notify_to(kid['notify'], 'Husk dine pligter',
                                  'Du har %d opgave%s i dag.' % (n, '' if n == 1 else 'r'))

    def _birthdays(self):
        for kid, age in self.store.birthday_notices():
            self.ha.notify('Fødselsdag i morgen',
                           '%s fylder %d i morgen. Så får %s nye opgaver.' % (kid['name'], age, kid['name']))

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
