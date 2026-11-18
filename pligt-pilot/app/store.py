"""Data og regler for Pligt-pilot.

Alt ligger i én JSON-fil. Ingen eksterne pakker.

Begreber
- kid:    et barn med navn, alder, farve og et hemmeligt link-token
- task:   en opgave, der kan gentages (dagligt, ugentligt, én gang)
- item:   en konkret opgave til et barn i en periode (i dag, i denne uge)
- ledger: penge ind og ud (godkendte opgaver, bonus, udbetalinger)
"""
import datetime as dt
import json
import os
import re
import secrets
import threading
import uuid

import i18n
import icons
import outdoor

COLORS = ['#0B7A70', '#C73A30', '#6C4AB6', '#B05A00', '#1F6FB2', '#B03A83']
DAYS = ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn']
REPEATS = ('daily', 'weekly', 'once')
MONTHS = ['januar', 'februar', 'marts', 'april', 'maj', 'juni', 'juli', 'august',
          'september', 'oktober', 'november', 'december']
SEASONS = {'forår': (3, 4, 5), 'sommer': (6, 7, 8), 'efterår': (9, 10, 11), 'vinter': (12, 1, 2)}
BOSSES = ['Støvdragen', 'Opvaskemonsteret', 'Vasketøjstrolden', 'Rodebunke-Rasmus',
          'Snavsedjævelen', 'Krummeuhyret', 'Sokkespøgelset', 'Skraldegiganten']
# Startpakke: (titel, pris, rum, gentagelse, gange, mindstealder, højestealder, sæson)
STARTER = [
    ('Dæk bord', 3, 'Køkken', 'daily', 1, 4, 99, ''),
    ('Ryd dit legetøj op', 3, 'Børneværelse', 'daily', 1, 4, 9, ''),
    ('Fodr kæledyr', 3, '', 'daily', 1, 5, 99, ''),
    ('Sæt sko og jakke på plads', 2, 'Gang', 'daily', 1, 4, 9, ''),
    ('Tøm opvaskemaskinen', 5, 'Køkken', 'daily', 1, 8, 99, ''),
    ('Tøm skraldespanden', 5, 'Køkken', 'daily', 1, 8, 99, ''),
    ('Ryd dit værelse', 10, 'Børneværelse', 'weekly', 1, 7, 99, ''),
    ('Hjælp med aftensmaden', 5, 'Køkken', 'daily', 1, 9, 99, ''),
    ('Støvsug stuen', 10, 'Stue', 'weekly', 1, 11, 99, ''),
    ('Gør badeværelset rent', 20, 'Badeværelse', 'weekly', 1, 13, 99, ''),
    ('Tag tøj ned og fold det', 8, 'Bryggers', 'weekly', 2, 11, 99, ''),
    ('Fej løv', 25, 'Have', 'weekly', 1, 11, 99, 'efterår'),
    ('Slå græs', 40, 'Have', 'weekly', 1, 13, 99, 'sommer'),
    ('Ryd sne', 30, 'Have', 'weekly', 1, 11, 99, 'vinter'),
]
LEVELS = [(0, 'Ægget'), (3, 'Ungen'), (10, 'Pligtfuglen'), (25, 'Pligtfuglen med kasket'),
          (50, 'Pligtmesteren'), (100, 'Pligtkongen'), (200, 'Pligtlegenden')]
SURPRISE_MINUTES = 90
ENTITY = re.compile(r'^[a-z_]+\.[a-z0-9_]+$')
SERVICE = re.compile(r'^(notify\.)?[a-z0-9_]+$')
MAX_PHOTO = 450 * 1024
MACHINES = ('washer', 'dryer', 'dishwasher')
DOOR_OPEN = ('on', 'open')
QUICK = 8                   # højst så mange hurtigknapper på Oversigt, fastgjorte først
USE_DAYS = 30               # hurtigknapperne følger, hvad der er brugt de sidste 30 dage
# "Hver sin" eller "én gør det", gættet ud fra titlen (dansk, engelsk, tysk, svensk og norsk).
# Ord med * til sidst er ordstammer; resten skal stå som hele ord.
# 1) ejeord og "egen" vinder altid, 2) fælles ting giver én, 3) personlige ting giver hver sin.
EACH_MINE = ['din', 'dit', 'dine', 'egen', 'eget', 'egne', 'own', 'your', 'yours', 'dein*', 'eigen*',
             'ditt', 'dina', 'egna', 'sin', 'sit', 'sine', 'sina', 'sitt']
EACH_SHARED = ['dæk* bord*', 'dække bord*', 'ryd af bord*', 'ryd* af', 'opvask*', 'skrald*', 'kæledyr*', 'fodr*',
               'stue*', 'badeværelse*', 'toilet*', 'set the table', 'clear the table', 'dishwasher*', 'trash',
               'garbage', 'bin', 'bins', 'pet', 'pets', 'feed*', 'living room', 'bathroom', 'tisch*', 'geschirr*',
               'spülmaschine*', 'müll*', 'haustier*', 'füttern', 'wohnzimmer', 'duka*', 'diskmaskin*', 'sopor',
               'soptunn*', 'husdjur*', 'mata', 'vardagsrum*', 'badrum*', 'dekk* bord*', 'oppvask*', 'søppel*',
               'kjæledyr*', 'mate', 'stua', 'stuen']
EACH_OWN = ['madpak*', 'seng*', 'værelse*', 'beskidt* tøj', 'snavset* tøj', 'skoletask*', 'lektie*', 'sko', 'skoene',
            'jakke*', 'tallerken', 'tænder', 'nattøj', 'bed', 'beds', 'bedroom', 'room', 'homework', 'lunchbox*',
            'lunch box*', 'schoolbag*', 'school bag*', 'backpack*', 'shoes', 'jacket*', 'coat', 'teeth',
            'dirty clothes', 'bett*', 'zimmer', 'kinderzimmer', 'hausaufgabe*', 'brotdose*', 'schulranzen',
            'schultasche*', 'schuhe', 'jacke*', 'zähne', 'schmutzige wäsche', 'säng*', 'rum', 'rummet', 'läx*',
            'matlåd*', 'skolväsk*', 'skor', 'skorna', 'jack*', 'tänder', 'smutsiga kläder', 'rom', 'rommet',
            'lekse*', 'matpakk*', 'skolesekk*', 'tenner', 'skittentøy*']


def _words(words):
    parts = [r'(?<!\w)' + re.escape(w.rstrip('*')).replace(r'\*', r'\w*') + ('' if w.endswith('*') else r'(?!\w)')
             for w in words]
    return re.compile('|'.join(parts))


_EACH = [(_words(EACH_MINE), True), (_words(EACH_SHARED), False), (_words(EACH_OWN), True)]


def guess_each(title):
    """True, hvis titlen lyder som noget hvert barn laver for sig selv (egen seng, egne lektier)."""
    text = (title or '').lower()
    for rx, each in _EACH:
        if rx.search(text):
            return each
    return False


def machine_type(name):
    """Maskinetype ud fra navnet (fælles aftale med Hus-chat): washer, dryer, dishwasher eller other."""
    text = (name or '').lower()
    if 'opvask' in text or 'dish' in text:
        return 'dishwasher'
    if any(w in text for w in ('tørre', 'tumbl', 'dryer', 'trockner', 'tork')):
        return 'dryer'
    if any(w in text for w in ('vask', 'wash', 'wasch', 'tvätt')):
        return 'washer'
    return 'other'


def age_on(birth, today):
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def step_back(repeat, d):
    return d - dt.timedelta(days=7 if repeat == 'weekly' else 1)


class Problem(Exception):
    """En fejl, som kan vises for brugeren."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _id():
    return uuid.uuid4().hex[:10]


def period_key(repeat, d):
    if repeat == 'weekly':
        y, w, _ = d.isocalendar()
        return '%d-W%02d' % (y, w)
    if repeat == 'once':
        return 'once'
    return d.strftime('%Y-%m-%d')


def week_key(d):
    return period_key('weekly', d)


def _period_kind(period):
    """Dag, uge eller blok af uger. Skifter en opgave slags periode, er det ikke barnets skyld."""
    return 'B' if period.startswith('B') else 'W' if '-W' in period else 'D'


def age_factor(age):
    """Yngre børn får lidt flere point, så konkurrencen er til at være med i."""
    return max(1.0, 1.0 + (12 - int(age)) * 0.1)


class Store:
    def __init__(self, path=None, clock=None):
        self.path = path
        self.clock = clock or dt.datetime.now
        self.lock = threading.RLock()
        self.data = {
            'kids': [], 'tasks': [], 'items': [], 'ledger': [],
            'rules': [],
            'settings': {'goal': 8, 'hero_bonus': 20, 'hero_paid_week': '',
                         'penalty': 0, 'perfect_bonus': 0, 'reminder_time': '',
                         'reminder_sent': '', 'celebrate_light': '',
                         'family_goal': None, 'hero_wins': {}, 'perfect_paid': {},
                         'boss_hp': 20, 'boss_bonus': 0, 'boss_paid_week': '',
                         'trading': True, 'surprise_plan': {}, 'streak_bonus': 5,
                         'auto_task_hours': 4, 'min_tasks_age': 0, 'min_tasks_week': 5,
                         'meal_price': 0},
            'trades': [], 'rewards': [], 'claims': [], 'parents': [],
        }
        self._photos = {}
        self.listener = None        # fx: fyr pligt_pilot_task i Home Assistant
        self.photo_dir = os.path.join(os.path.dirname(path) or '.', 'photos') if path else None
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            for key, value in loaded.items():
                if key == 'settings':
                    self.data['settings'].update(value)
                else:
                    self.data[key] = value
        for t in self.data['tasks']:
            if 'auto_season' not in t:
                t['auto_season'] = self._legacy_auto(t)

    # ---- lagring -------------------------------------------------------
    def lang_of(self, kid=None):
        """Sprog for et barn (eller for forælderen): barnets eget, ellers husets."""
        house = i18n.valid(self.data['settings'].get('lang', 'da'))
        if kid is not None and kid.get('lang'):
            return i18n.valid(kid['lang'])
        return house

    def _save(self):
        if not self.path:
            return
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---- små hjælpere --------------------------------------------------
    def _now(self):
        return self.clock()

    def _emit(self, kind, task, kid=None):
        """Fortæller omverdenen om husopgaver, maddage og pligter. Fejl må aldrig stoppe noget."""
        payload = self._event_payload(kind, task, kid)
        if payload is None or not self.listener:
            return
        try:
            self.listener(payload)
        except Exception:  # noqa: BLE001
            pass

    def _event_payload(self, kind, task, kid=None):
        if not task:
            return None
        payload = {'kind': kind, 'title': task['title'], 'kid': kid['name'] if kid else '',
                   'task_id': task['id']}
        rule_id = task.get('auto_rule')
        if task.get('meal'):
            payload.update(source='meal', meal=task['meal'].get('meal', ''))
        elif task.get('duty'):
            payload['source'] = 'duty'
        elif rule_id and rule_id not in ('surprise', 'given'):
            rule = next((r for r in self.data['rules'] if r['id'] == rule_id), None)
            payload.update(source='machine', machine=machine_type(rule['name'] if rule else ''))
        else:
            return None
        return payload

    def _kid(self, kid_id):
        for k in self.data['kids']:
            if k['id'] == kid_id:
                return k
        raise Problem('Barnet findes ikke', 404)

    def _task(self, task_id):
        for t in self.data['tasks']:
            if t['id'] == task_id:
                return t
        raise Problem('Opgaven findes ikke', 404)

    def _item(self, item_id):
        for it in self.data['items']:
            if it['id'] == item_id:
                return it
        raise Problem('Opgaven findes ikke', 404)

    def kid_by_token(self, token):
        found = None
        for k in self.data['kids']:
            # gennemløb alle, så svartiden ikke afslører noget
            if secrets.compare_digest(k['token'], token or ''):
                found = k
        return found

    @staticmethod
    def _clean_text(value, what, limit=60):
        text = (value or '').strip()
        if not text:
            raise Problem('%s mangler' % what)
        return text[:limit]

    @staticmethod
    def _clean_price(value):
        try:
            price = int(round(float(str(value).replace(',', '.'))))
        except (TypeError, ValueError):
            raise Problem('Prisen skal være et tal')
        if price < 0 or price > 1000:
            raise Problem('Prisen skal være mellem 0 og 1000 kr.')
        return price

    @staticmethod
    def _clean_season(value):
        value = (value or '').strip().lower()
        if value and value not in SEASONS:
            raise Problem('Ukendt sæson')
        return value

    @staticmethod
    def _legacy_auto(task):
        """Opgaver fra før auto-sæson: automatik, medmindre forælderen selv har valgt en sæson.
        En sæson fra startpakken tæller ikke som forælderens valg."""
        season = task.get('season') or ''
        if not season:
            return True
        title = task['title'].strip().lower()
        for row in STARTER:
            if row[7] == season and title in {i18n.translate(lang, row[0]).lower() for lang in i18n.LANGS}:
                return True
        return False

    @staticmethod
    def _auto_rule(task):
        """Den automatiske regel for årstid og hyppighed ud fra titlen (uanset om den er slået til)."""
        if task.get('duty') or task.get('meal') or task.get('auto_rule'):
            return None
        return outdoor.auto_rule(task['title'], task.get('room', ''))

    def _auto(self, task):
        """Reglen, hvis den gælder: forælderens eget valg af sæson vinder."""
        return self._auto_rule(task) if task.get('auto_season', True) else None

    def _in_season(self, task, d):
        rule = self._auto(task)
        if rule:
            return d.month in rule['months']
        season = task.get('season') or ''
        return not season or d.month in SEASONS[season]

    def _period(self, task, d):
        """Opgavens periode. Græs og blade højst hver uge, hæk højst hver 3. uge."""
        if task['repeat'] == 'once':
            return 'once'
        rule = self._auto(task)
        every = rule['every'] if rule else 0
        if every >= 14:
            weeks = every // 7
            return 'B%d-%d' % (weeks, (d.toordinal() - 1) // 7 // weeks)   # dag 1 er en mandag
        if every >= 7:
            return period_key('weekly', d)
        return period_key(task['repeat'], d)

    def _weather_blocks(self, task, d):
        """Vejret holder opgaven tilbage (regn for udendørs opgaver, sne-opgaver uden sne)."""
        if task.get('duty') or task.get('meal') or task.get('auto_rule'):
            return False
        return outdoor.blocks(self.data['settings'].get('weather'), task['title'], task.get('room', ''), d)

    def set_weather(self, entity, state):
        """Husets vejr fra Home Assistant. Sne huskes i et døgn, også over en genstart."""
        with self.lock:
            now = self._now()
            state = (state or '').strip().lower()
            w = self.data['settings'].get('weather') or {}
            changed = w.get('entity') != (entity or '') or w.get('state') != state
            w.update(entity=entity or '', state=state, at=now.isoformat(timespec='seconds'))
            if entity and state in outdoor.SNOWY:
                w['snow_at'] = now.isoformat(timespec='seconds')
                changed = True
            self.data['settings']['weather'] = w
            if changed:
                self._save()

    @staticmethod
    def _clean_days(value):
        """Faste ugedage (0 = mandag). Tom liste: alle dage som før."""
        try:
            days = sorted({int(x) for x in (value or [])})
        except (TypeError, ValueError):
            raise Problem('Ukendte ugedage')
        if any(x < 0 or x > 6 for x in days):
            raise Problem('Ukendte ugedage')
        return days

    def _on_day(self, task, d):
        """Faste dage: en daglig opgave kun på de valgte dage, en ugentlig fra den første valgte dag i perioden."""
        days = task.get('days') or []
        if not days:
            return True
        if _period_kind(self._period(task, d)) == 'D':
            return d.weekday() in days
        return d.weekday() >= days[0]

    @staticmethod
    def _clean_times(value):
        try:
            times = int(value or 1)
        except (TypeError, ValueError):
            raise Problem('Antal gange skal være et tal')
        if times < 1 or times > 5:
            raise Problem('Antal gange skal være mellem 1 og 5')
        return times

    @staticmethod
    def _clean_age(value):
        try:
            age = int(value)
        except (TypeError, ValueError):
            raise Problem('Alderen skal være et tal')
        if age < 1 or age > 25:
            raise Problem('Alderen skal være mellem 1 og 25 år')
        return age

    # ---- børn ----------------------------------------------------------
    @staticmethod
    def _parse_birthday(value, today):
        try:
            birth = dt.date.fromisoformat(str(value).strip())
        except ValueError:
            raise Problem('Fødselsdatoen skal være en dato')
        age = age_on(birth, today)
        if birth > today or age < 1 or age > 25:
            raise Problem('Alderen skal være mellem 1 og 25 år')
        return birth.isoformat(), age

    @staticmethod
    def _clean_service(value):
        text = (value or '').strip()
        if text and not SERVICE.match(text):
            raise Problem('Notifikationstjenesten må kun indeholde bogstaver, tal og _')
        return text

    def add_kid(self, name, age=None, color=None, birthday=None):
        with self.lock:
            kid = {
                'id': _id(),
                'name': self._clean_text(name, 'Navn', 30),
                'color': color or COLORS[len(self.data['kids']) % len(COLORS)],
                'token': secrets.token_urlsafe(12),
                'ntfy': 'pligt-' + secrets.token_urlsafe(12),
            }
            if str(birthday or '').strip():
                kid['birthday'], kid['age'] = self._parse_birthday(birthday, self._now().date())
            else:
                kid['age'] = self._clean_age(age)
            self.data['kids'].append(kid)
            self._save()
            return kid

    def update_kid(self, kid_id, name=None, age=None, color=None, paused=None,
                   birthday=None, notify=None, allowance=None, ntfy_on=None, lang=None):
        with self.lock:
            kid = self._kid(kid_id)
            if name is not None:
                kid['name'] = self._clean_text(name, 'Navn', 30)
            if birthday is not None:
                if str(birthday).strip():
                    kid['birthday'], kid['age'] = self._parse_birthday(birthday, self._now().date())
                else:
                    kid.pop('birthday', None)
            if age is not None and 'birthday' not in kid:
                kid['age'] = self._clean_age(age)
            if color:
                kid['color'] = color
            if paused is not None:
                kid['paused'] = bool(paused)
            if notify is not None:
                kid['notify'] = self._clean_service(notify)
            if ntfy_on is not None:
                kid['ntfy_on'] = bool(ntfy_on)
            if lang is not None:
                kid['lang'] = i18n.valid(lang) if lang else ''
            if allowance is not None:
                amount = self._clean_price(allowance or 0)
                kid['allowance'] = amount
                kid['allowance_week'] = week_key(self._now())
            self._save()
            return kid

    def set_goal(self, kid_id, title, amount):
        """Sparemål. Tæller det, barnet tjener fra nu af, uanset udbetalinger."""
        with self.lock:
            kid = self._kid(kid_id)
            if not (title or '').strip() and not str(amount or '').strip():
                kid.pop('saving', None)
            else:
                price = self._clean_price(amount)
                if price < 1:
                    raise Problem('Beløbet skal være mindst 1 kr.')
                kid['saving'] = {
                    'title': self._clean_text(title, 'Navn på sparemålet', 40),
                    'amount': price,
                    'since': self._now().isoformat(timespec='seconds'),
                }
            self._save()
            return kid

    def _earned_since(self, since, kid_id=None):
        return sum(e['amount'] for e in self.data['ledger']
                   if (kid_id is None or e['kid_id'] == kid_id)
                   and e['kind'] in ('task', 'bonus', 'allowance') and e['at'] >= since)

    def _saving(self, kid):
        goal = kid.get('saving')
        if not goal:
            return None
        saved = max(0, self._earned_since(goal['since'], kid['id']))
        return {'title': goal['title'], 'amount': goal['amount'], 'saved': min(saved, goal['amount']),
                'reached': saved >= goal['amount']}

    def set_family_goal(self, title, amount):
        with self.lock:
            if not (title or '').strip() and not str(amount or '').strip():
                self.data['settings']['family_goal'] = None
            else:
                price = self._clean_price(amount)
                if price < 1:
                    raise Problem('Beløbet skal være mindst 1 kr.')
                self.data['settings']['family_goal'] = {
                    'title': self._clean_text(title, 'Navn på familiemålet', 40),
                    'amount': price, 'since': self._now().isoformat(timespec='seconds')}
            self._save()

    def _family(self):
        goal = self.data['settings'].get('family_goal')
        if not goal:
            return None
        saved = max(0, self._earned_since(goal['since']))
        return {'title': goal['title'], 'amount': goal['amount'],
                'saved': min(saved, goal['amount']), 'reached': saved >= goal['amount']}

    def add_push(self, token, sub):
        """Gemmer barnets telefon som modtager af web-push. Højst 3 enheder pr. barn."""
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            try:
                endpoint = str(sub['endpoint'])
                keys = {'p256dh': str(sub['keys']['p256dh']), 'auth': str(sub['keys']['auth'])}
            except (KeyError, TypeError):
                raise Problem('Tilmeldingen er ugyldig')
            if not endpoint.startswith('https://') or len(endpoint) > 600 or \
                    not all(re.match(r'^[A-Za-z0-9_-]{8,200}$', v) for v in keys.values()):
                raise Problem('Tilmeldingen er ugyldig')
            subs = [x for x in kid.get('push', []) if x['endpoint'] != endpoint]
            subs.append({'endpoint': endpoint, 'keys': keys})
            kid['push'] = subs[-3:]
            self._save()
            return kid

    def remove_push(self, kid_id, endpoint):
        with self.lock:
            kid = self._kid(kid_id)
            kid['push'] = [x for x in kid.get('push', []) if x['endpoint'] != endpoint]
            self._save()

    # ---- forældre med eget link ----------------------------------------
    def parent_by_token(self, token):
        found = None
        for p in self.data['parents']:
            if secrets.compare_digest(p['token'], token or ''):
                found = p
        return found

    def add_parent(self, name):
        with self.lock:
            if len(self.data['parents']) >= 6:
                raise Problem('Der kan højst være 6 forældre')
            parent = {'id': _id(), 'name': self._clean_text(name, 'Navn', 30),
                      'token': secrets.token_urlsafe(18)}
            self.data['parents'].append(parent)
            self._save()
            return parent

    def renew_parent(self, parent_id):
        with self.lock:
            parent = next((p for p in self.data['parents'] if p['id'] == parent_id), None)
            if not parent:
                raise Problem('Forælderen findes ikke')
            parent['token'] = secrets.token_urlsafe(18)
            self._save()
            return parent

    def delete_parent(self, parent_id):
        with self.lock:
            self.data['parents'] = [p for p in self.data['parents'] if p['id'] != parent_id]
            self._save()

    def new_token(self, kid_id):
        with self.lock:
            kid = self._kid(kid_id)
            kid['token'] = secrets.token_urlsafe(12)
            self._save()
            return kid

    def delete_kid(self, kid_id):
        with self.lock:
            self._kid(kid_id)
            d = self.data
            d['kids'] = [k for k in d['kids'] if k['id'] != kid_id]
            for i in d['items']:
                if i['kid_id'] == kid_id:
                    self.delete_photo(i['id'])
            d['items'] = [i for i in d['items'] if i['kid_id'] != kid_id]
            d['ledger'] = [e for e in d['ledger'] if e['kid_id'] != kid_id]
            for t in d['tasks']:
                if kid_id in (t.get('kids') or []):
                    t['kids'] = [x for x in t['kids'] if x != kid_id]
            self._save()

    # ---- opgaver -------------------------------------------------------
    def add_task(self, title, price, room='', repeat='daily', open_job=False,
                 kids=None, age_min=0, age_max=99, times=1, photo=False, auto_rule=None,
                 season='', surprise=False, icon='', auto_season=None, days=None, active=True):
        with self.lock:
            if repeat not in REPEATS:
                raise Problem('Ukendt gentagelse')
            task = {
                'id': _id(),
                'title': self._clean_text(title, 'Navn på opgaven'),
                'room': (room or '').strip()[:40],
                'price': self._clean_price(price),
                'repeat': repeat,
                'open': bool(open_job),
                'kids': list(kids or []),
                'age_min': int(age_min or 0),
                'age_max': int(age_max or 99),
                'times': self._clean_times(times),
                'photo': bool(photo),
                'season': self._clean_season(season), 'icon': icons.valid(icon),
                'surprise': bool(surprise),
                'auto_season': (not season) if auto_season is None else bool(auto_season),
                'created': self._now().isoformat(timespec='seconds'),
                'active': bool(active),             # False: kun når forælderen giver den
            }
            if days:
                task['days'] = self._clean_days(days)
            if auto_rule:
                task['auto_rule'] = auto_rule
            self.data['tasks'].append(task)
            self._save()
            return task

    def update_task(self, task_id, **fields):
        with self.lock:
            task = self._task(task_id)
            if 'title' in fields:
                task['title'] = self._clean_text(fields['title'], 'Navn på opgaven')
            if 'price' in fields:
                task['price'] = self._clean_price(fields['price'])
            if 'room' in fields:
                task['room'] = (fields['room'] or '').strip()[:40]
            if 'repeat' in fields:
                if fields['repeat'] not in REPEATS:
                    raise Problem('Ukendt gentagelse')
                task['repeat'] = fields['repeat']
            if 'open' in fields:
                task['open'] = bool(fields['open'])
            if 'active' in fields:
                task['active'] = bool(fields['active'])     # False: kun når forælderen giver den
            if 'days' in fields:
                task['days'] = self._clean_days(fields['days'])
            if 'kids' in fields:
                task['kids'] = list(fields['kids'] or [])
            if 'times' in fields:
                task['times'] = self._clean_times(fields['times'])
            if 'photo' in fields:
                task['photo'] = bool(fields['photo'])
            if 'season' in fields:
                if fields['season'] == 'auto':
                    task['auto_season'] = True
                else:
                    task['season'] = self._clean_season(fields['season'])
                    task['auto_season'] = False     # forælderens eget valg vinder
            if 'quick' in fields:
                task['quick'] = bool(fields['quick'])
            if 'each' in fields:
                task['each'] = bool(fields['each'])
                task['each_auto'] = False           # forælderens eget valg vinder over titlen
            if 'surprise' in fields:
                task['surprise'] = bool(fields['surprise'])
            if 'icon' in fields:
                task['icon'] = icons.valid(fields['icon'])
            if 'age_min' in fields:
                try:
                    task['age_min'] = max(0, min(25, int(fields['age_min'] or 0)))
                except (TypeError, ValueError):
                    raise Problem('Alder skal være et tal')
            self._save()
            return task

    def delete_task(self, task_id):
        with self.lock:
            self._task(task_id)
            self.data['tasks'] = [t for t in self.data['tasks'] if t['id'] != task_id]
            self._save()

    def add_starter_pack(self):
        """Opretter en passende startpakke. Springer opgaver over, der allerede findes."""
        made = 0
        for title, price, room, repeat, times, lo, hi, season in STARTER:
            if self.has_task_titled(title) or self.has_task_titled(i18n.translate(self.lang_of(), title)):
                continue
            lang = self.lang_of()
            self.add_task(i18n.translate(lang, title), price, i18n.translate(lang, room), repeat,
                          False, None, lo, hi, times, False, None, season, auto_season=True)
            made += 1
        return made

    def duplicate_task(self, task_id):
        with self.lock:
            src = self._task(task_id)
            copy = dict(src)
            copy.update({'id': _id(), 'title': (src['title'] + ' (kopi)')[:60],
                         'created': self._now().isoformat(timespec='seconds')})
            copy['kids'] = list(src.get('kids') or [])
            copy['days'] = list(src.get('days') or [])
            self.data['tasks'].append(copy)
            self._save()
            return copy

    def decide_all(self):
        """Godkender alt, der venter. Opgaver med billede springes over, så de ses først."""
        with self.lock:
            ids = [i['id'] for i in self.data['items'] if i['status'] == 'wait' and not i.get('photo')]
        return [self.decide(item_id, True) for item_id in ids]

    # ---- dage i træk ----------------------------------------------------
    STREAK_EVERY = 5

    def _day_streak(self, kid_id):
        """Antal dage i træk (til og med i dag, eller til og med i går), hvor barnet har meldt noget færdigt."""
        days = {i['done_at'][:10] for i in self.data['items']
                if i['kid_id'] == kid_id and i['status'] in ('wait', 'done') and i.get('done_at')}
        d = self._now().date()
        if d.isoformat() not in days:
            d -= dt.timedelta(days=1)
        n = 0
        while d.isoformat() in days:
            n += 1
            d -= dt.timedelta(days=1)
        return n

    def _streak_view(self, kid):
        n = self._day_streak(kid['id'])
        bonus = int(self.data['settings'].get('streak_bonus') or 0)
        return {'days': n, 'bonus': bonus,
                'to_go': self.STREAK_EVERY - n % self.STREAK_EVERY if bonus else 0}

    def _streak_bonus(self, kid_id):
        bonus = int(self.data['settings'].get('streak_bonus') or 0)
        kid = self._kid(kid_id)
        today = self._now().date().isoformat()
        n = self._day_streak(kid_id)
        if bonus > 0 and n >= self.STREAK_EVERY and n % self.STREAK_EVERY == 0 \
                and kid.get('streak_paid') != today:
            kid['streak_paid'] = today
            self._credit(kid_id, bonus, 'bonus', '%d dage i træk' % n)

    # ---- belønninger -----------------------------------------------------
    def add_reward(self, title, price):
        with self.lock:
            cost = self._clean_price(price)
            if cost < 1:
                raise Problem('Prisen skal være mindst 1 kr.')
            reward = {'id': _id(), 'title': self._clean_text(title, 'Navn på belønningen', 40), 'price': cost}
            self.data['rewards'].append(reward)
            self._save()
            return reward

    def add_reward_examples(self):
        for title, price in (('30 minutters ekstra skærmtid', 15), ('Vælg fredagsfilmen', 10),
                             ('Blive oppe 30 minutter længere', 20)):
            if not any(r['title'] == title for r in self.data['rewards']):
                self.add_reward(title, price)

    def delete_reward(self, reward_id):
        with self.lock:
            self.data['rewards'] = [r for r in self.data['rewards'] if r['id'] != reward_id]
            self.data['claims'] = [c for c in self.data['claims'] if c['reward_id'] != reward_id]
            self._save()

    def _reserved(self, kid_id):
        return sum(c['price'] for c in self.data['claims'] if c['kid_id'] == kid_id)

    def buy_reward(self, token, reward_id):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            reward = next((r for r in self.data['rewards'] if r['id'] == reward_id), None)
            if not reward:
                raise Problem('Belønningen findes ikke længere')
            if any(c['kid_id'] == kid['id'] and c['reward_id'] == reward_id for c in self.data['claims']):
                raise Problem('Du har allerede bedt om den')
            if self.balance(kid['id']) - self._reserved(kid['id']) < reward['price']:
                raise Problem('Du har ikke penge nok endnu')
            claim = {'id': _id(), 'kid_id': kid['id'], 'reward_id': reward_id, 'title': reward['title'],
                     'price': reward['price'], 'at': self._now().isoformat(timespec='seconds')}
            self.data['claims'].append(claim)
            self._save()
            return kid, claim

    def decide_claim(self, claim_id, approve):
        with self.lock:
            claim = next((c for c in self.data['claims'] if c['id'] == claim_id), None)
            if not claim:
                raise Problem('Anmodningen findes ikke længere')
            if approve:
                if self.balance(claim['kid_id']) < claim['price']:
                    raise Problem('Barnet har ikke penge nok længere')
                self._credit(claim['kid_id'], -claim['price'], 'reward', claim['title'])
            self.data['claims'] = [c for c in self.data['claims'] if c['id'] != claim_id]
            self._save()
            return claim

    def cancel_claim(self, token, claim_id):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            self.data['claims'] = [c for c in self.data['claims']
                                   if not (c['id'] == claim_id and c['kid_id'] == kid['id'])]
            self._save()

    # ---- ønsker ------------------------------------------------------------
    def make_wish(self, token, title, price):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            if not (title or '').strip() and not str(price or '').strip():
                kid.pop('wish', None)
            else:
                cost = self._clean_price(price)
                if cost < 1:
                    raise Problem('Skriv, hvad det koster')
                kid['wish'] = {'title': self._clean_text(title, 'Hvad ønsker du dig', 40), 'price': cost}
            self._save()
            return kid

    def decide_wish(self, kid_id, accept):
        with self.lock:
            kid = self._kid(kid_id)
            wish = kid.pop('wish', None)
            if wish and accept:
                self.set_goal(kid_id, wish['title'], wish['price'])
            self._save()
            return kid, wish

    def pay_all(self):
        with self.lock:
            total = 0
            for k in self.data['kids']:
                amount = self.balance(k['id'])
                if amount > 0:
                    self._credit(k['id'], -amount, 'payout', 'Udbetalt')
                    total += amount
            if not total:
                raise Problem('Der er ikke noget at udbetale')
            self._save()
            return total

    def touch(self, token):
        """Husker, hvornår barnet sidst åbnede siden (kun datoen)."""
        with self.lock:
            kid = self.kid_by_token(token)
            today = self._now().date().isoformat()
            if kid and kid.get('seen') != today:
                kid['seen'] = today
                self._save()

    def advice(self):
        """Få, korte råd til forælderen."""
        out = []
        today = self._now().date()
        for k in self.data['kids']:
            if k.get('paused'):
                continue
            seen = k.get('seen')
            if seen and (today - dt.date.fromisoformat(seen)).days >= 3:
                out.append('%s har ikke åbnet siden i %d dage. Send linket igen.'
                           % (k['name'], (today - dt.date.fromisoformat(seen)).days))
            elif not seen and any(i['kid_id'] == k['id'] and (i['created'] or '')[:10] < today.isoformat()
                                  for i in self.data['items']):
                out.append('%s har endnu ikke åbnet sit link. Send det igen.' % k['name'])
        since = (today - dt.timedelta(days=14)).isoformat()
        for t in self.data['tasks']:
            if not t.get('active', True):
                continue                    # kun når forælderen giver den: ikke barnets skyld
            n = sum(1 for i in self.data['items']
                    if i['task_id'] == t['id'] and i['status'] == 'missed' and (i['created'] or '')[:10] >= since)
            if n >= 3:
                out.append('"%s" er misset %d gange de sidste 14 dage. Prøv at sætte prisen op eller fjern den.'
                           % (t['title'], n))
        return out[:3]

    def backup(self):
        with self.lock:
            return json.dumps(self.data, ensure_ascii=False, indent=1).encode('utf-8')

    def has_task_titled(self, title):
        wanted = (title or '').strip().lower()
        return any(t['title'].strip().lower() == wanted for t in self.data['tasks'])

    # ---- perioder og forekomster --------------------------------------
    def _in_scope(self, task, kid):
        if task['kids'] and kid['id'] not in task['kids']:
            return False
        return task.get('age_min', 0) <= kid['age'] <= task.get('age_max', 99)

    def _new_item(self, task, kid, d, status='todo', slot=1):
        item = {
            'slot': slot,
            'of': task.get('times', 1),
            'id': _id(),
            'task_id': task['id'],
            'kid_id': kid['id'],
            'period': self._period(task, d),
            'title': task['title'],
            'room': task['room'],
            'price': task['price'],
            'status': status,
            'created': d.isoformat(timespec='seconds'),
            'done_at': None,
            'decided_at': None,
            'rejected': 0,
        }
        if task.get('given_from'):
            item['from_task'] = task['given_from']      # tæller med til hurtigknapperne
        self.data['items'].append(item)
        return item

    def _refresh(self):
        """Opretter dagens opgaver og lukker gamle. Kaldes før alt, der læser."""
        d = self._now()
        changed = False
        # alder følger fødselsdatoen
        for kid in self.data['kids']:
            if kid.get('birthday'):
                age = age_on(dt.date.fromisoformat(kid['birthday']), d.date())
                if age != kid['age']:
                    kid['age'] = age
                    changed = True
        for kid in self.data['kids']:
            if not kid.get('ntfy'):
                kid['ntfy'] = 'pligt-' + secrets.token_urlsafe(12)
                changed = True
        # lommepenge: én gang pr. uge (for ugen før). Store børn skal måske have lavet nok først.
        wk = week_key(d)
        prev = week_key(d - dt.timedelta(days=7))
        for kid in self.data['kids']:
            if kid.get('allowance', 0) > 0 and kid.get('allowance_week') != wk:
                need = self._allowance_need(kid)
                got = self._approved_in(kid['id'], prev)
                if need and got < need:
                    kid['allowance_held'] = {'week': prev, 'amount': kid['allowance'], 'need': need}
                    kid['allowance_notice'] = 'Lommepengene for uge %d er holdt tilbage: %d af %d opgaver godkendt.' \
                        % (int(prev[-2:]), got, need)
                else:
                    self._credit(kid['id'], kid['allowance'], 'allowance', 'Lommepenge')
                    kid.pop('allowance_held', None)
                kid['allowance_week'] = wk
                changed = True
            held = kid.get('allowance_held')
            if held and self._approved_in(kid['id'], held['week']) >= held['need']:
                # opgaverne blev godkendt lidt for sent: pengene kommer alligevel
                self._credit(kid['id'], held['amount'], 'allowance', 'Lommepenge')
                kid.pop('allowance_held', None)
                changed = True
        # ryd huset-opgaver, der er klaret eller har ligget for længe
        hours = int(self.data['settings'].get('auto_task_hours') or 0)
        for t in list(self.data['tasks']):
            if not t.get('auto_rule'):
                continue
            mine = [i for i in self.data['items'] if i['task_id'] == t['id']]
            finished = any(i['status'] == 'done' for i in mine) and not any(
                i['status'] in ('todo', 'wait') for i in mine)
            age = d - dt.datetime.fromisoformat(t.get('created') or d.isoformat())
            until = t.get('expires') or t.get('until')
            lapsed = until and d > dt.datetime.fromisoformat(until)
            limit = dt.timedelta(hours=hours) if hours > 0 and t['auto_rule'] not in ('surprise', 'given') \
                else dt.timedelta(days=2)
            if finished:
                self.data['tasks'].remove(t)
                changed = True
            elif not self._taken(t) and (age > limit or lapsed):
                self.data['tasks'].remove(t)
                self._emit('removed', t)
                changed = True
        # pligter og maddage ryddes op et par dage efter
        for t in list(self.data['tasks']):
            end = self._day_end(t)
            if end and d > end + dt.timedelta(days=7 if t.get('duty') else 2):
                self.data['tasks'].remove(t)
                changed = True
        live = {i['id']: i for i in self.data['items']}
        keep = [t for t in self.data['trades']
                if t['item_id'] in live and live[t['item_id']]['status'] == 'todo'
                and live[t['item_id']]['kid_id'] == t['from']
                and d - dt.datetime.fromisoformat(t['at']) < dt.timedelta(days=1)]
        if len(keep) != len(self.data['trades']):
            self.data['trades'] = keep
            changed = True
        tasks = {t['id']: t for t in self.data['tasks']}
        kids = {k['id']: k for k in self.data['kids']}
        penalty = int(self.data['settings'].get('penalty') or 0)
        for it in self.data['items']:
            if it['status'] != 'todo':
                continue
            t = tasks.get(it['task_id'])
            kid = kids.get(it['kid_id'])
            paused = bool(kid and kid.get('paused'))
            current = d.strftime('%Y-%m-%d') if it.get('given') else self._period(t, d) if t is not None else ''
            expired = (t is not None and (t['repeat'] != 'once' or it.get('given')) and it['period'] != current)
            off_season = t is not None and not self._in_season(t, d)
            if t is not None and t.get('duty') and d > self._day_end(t) and not paused and t['active']:
                # pligten blev ikke lavet inden fristen: træk beløbet (aldrig under 0)
                it['status'] = 'missed'
                changed = True
                cut = min(int(t['duty'].get('fine') or 0), max(0, self.balance(it['kid_id'])))
                if cut:
                    self._credit(it['kid_id'], -cut, 'penalty', it['title'], it['id'])
                continue
            day_over = t is not None and t.get('meal') and d > self._day_end(t)
            # en opgave, forælderen selv har givet, lever videre, selvom opgaven kun gives på bestilling
            live_task = t is not None and (t['active'] or it.get('given'))
            stale = t is None or not live_task or paused or expired or off_season or day_over
            if stale:
                it['status'] = 'missed'
                self.delete_photo(it['id'])
                changed = True
                if penalty and expired and live_task and not paused and not off_season \
                        and not t.get('open') and _period_kind(it['period']) == _period_kind(current):
                    cut = min(penalty, max(0, self.balance(it['kid_id'])))
                    if cut:
                        self._credit(it['kid_id'], -cut, 'penalty', it['title'])
        existing = {}
        for i in self.data['items']:
            if i['status'] != 'missed' and not i.get('given'):
                key = (i['task_id'], i['kid_id'], i['period'])
                existing[key] = existing.get(key, 0) + 1
        for t in self.data['tasks']:
            if not t['active'] or t['open'] or t.get('surprise') or not self._in_season(t, d):
                continue
            if t.get('meal') and t['meal']['date'] != d.date().isoformat():
                continue                    # maddagen vises kun på dagen
            if t.get('duty') and d > self._day_end(t):
                continue
            if self._weather_blocks(t, d):
                continue                    # regn eller ingen sne: kommer næste gang, vejret passer
            if not self._on_day(t, d):
                continue                    # faste dage: ikke i dag
            period = self._period(t, d)
            for kid in self.data['kids']:
                if kid.get('paused') or not self._in_scope(t, kid):
                    continue
                have = existing.get((t['id'], kid['id'], period), 0)
                for slot in range(have + 1, t.get('times', 1) + 1):
                    self._new_item(t, kid, d, slot=slot)
                    changed = True
        if changed:
            self._save()

    def housekeeping(self):
        with self.lock:
            self._refresh()

    def _taken(self, task):
        """Har et barn taget opgaven (eller er den i gang)?"""
        return any(i['task_id'] == task['id'] and i['status'] != 'missed' for i in self.data['items'])

    @staticmethod
    def _day_end(task):
        """Fristen for en pligt eller slutningen af maddagen. None for andre opgaver."""
        if task.get('duty'):
            return dt.datetime.fromisoformat(task['duty']['due'])
        if task.get('meal'):
            return dt.datetime.fromisoformat(task['meal']['date'] + 'T23:59:59')
        return None

    # ---- lommepenge med krav ---------------------------------------------
    def _allowance_need(self, kid):
        """Antal godkendte opgaver i ugen, barnet skal have for at få lommepenge (0 = intet krav)."""
        st = self.data['settings']
        age = int(st.get('min_tasks_age') or 0)
        if age <= 0 or kid['age'] < age:
            return 0
        return int(st.get('min_tasks_week') or 0)

    def _approved_in(self, kid_id, wk):
        return sum(1 for i in self.data['items']
                   if i['kid_id'] == kid_id and i['status'] == 'done' and i.get('done_at')
                   and week_key(dt.datetime.fromisoformat(i['done_at'])) == wk)

    def _allowance_view(self, kid):
        need = self._allowance_need(kid)
        if not need or not kid.get('allowance'):
            return None
        held = kid.get('allowance_held')
        return {'need': need, 'done': self._approved_in(kid['id'], week_key(self._now())),
                'amount': kid['allowance'], 'held': held['amount'] if held else 0}

    def allowance_notices(self):
        """[(barn, tekst)] for børn, hvis lommepenge lige er holdt tilbage. Hver besked kun én gang."""
        with self.lock:
            self._refresh()
            out = []
            for k in self.data['kids']:
                text = k.pop('allowance_notice', None)
                if text:
                    out.append((k, text))
            if out:
                self._save()
            return out

    def _open_jobs_for(self, kid):
        d = self._now()
        jobs = []
        if kid.get('paused'):
            return jobs
        for t in self.data['tasks']:
            if not t['active'] or not t['open'] or t.get('surprise') or not self._in_scope(t, kid) \
                    or not self._in_season(t, d) or self._weather_blocks(t, d) or not self._on_day(t, d):
                continue
            period = self._period(t, d)
            taken = sum(1 for i in self.data['items'] if i['task_id'] == t['id']
                        and i['period'] == period and i['status'] != 'missed')
            if taken < t.get('times', 1):
                jobs.append(t)
        return jobs

    # ---- billeder ------------------------------------------------------
    def _photo_file(self, item_id):
        return os.path.join(self.photo_dir, item_id + '.jpg') if self.photo_dir else None

    def save_photo(self, item_id, data):
        if len(data) > MAX_PHOTO:
            raise Problem('Billedet er for stort')
        if data[:3] != b'\xff\xd8\xff':
            raise Problem('Billedet skal være et JPEG-billede')
        if self.photo_dir:
            os.makedirs(self.photo_dir, exist_ok=True)
            with open(self._photo_file(item_id), 'wb') as f:
                f.write(data)
        else:
            self._photos[item_id] = data

    def photo(self, item_id):
        if self.photo_dir:
            try:
                with open(self._photo_file(item_id), 'rb') as f:
                    return f.read()
            except OSError:
                return None
        return self._photos.get(item_id)

    def delete_photo(self, item_id):
        self._photos.pop(item_id, None)
        if self.photo_dir:
            try:
                os.remove(self._photo_file(item_id))
            except OSError:
                pass

    # ---- serier og mærker ---------------------------------------------
    def _streak(self, kid_id, task):
        """Hvor mange perioder i træk (før den nuværende), opgaven er godkendt."""
        if task['repeat'] == 'once':
            return 0
        done = {i['period'] for i in self.data['items']
                if i['task_id'] == task['id'] and i['kid_id'] == kid_id and i['status'] == 'done'}
        d = step_back(task['repeat'], self._now())
        n = 0
        while period_key(task['repeat'], d) in done:
            n += 1
            d = step_back(task['repeat'], d)
        return n

    def _best_streak(self, kid_id):
        best = 0
        for t in self.data['tasks']:
            best = max(best, self._streak(kid_id, t))
        return best

    def _badges(self, kid):
        approved = sum(1 for e in self.data['ledger']
                       if e['kid_id'] == kid['id'] and e['kind'] == 'task')
        wins = (self.data['settings'].get('hero_wins') or {}).get(kid['id'], 0)
        out = []
        for need, title in ((1, 'Første opgave'), (10, '10 opgaver'), (25, '25 opgaver'),
                            (50, '50 opgaver'), (100, '100 opgaver')):
            if approved >= need:
                out.append({'id': 'n%d' % need, 'title': title})
        streak = self._best_streak(kid['id'])
        for need, title in ((3, '3 i træk'), (7, '7 i træk'), (30, '30 i træk')):
            if streak >= need:
                out.append({'id': 's%d' % need, 'title': title})
        if wins:
            out.append({'id': 'hero', 'title': 'Ugens helt' + (' x%d' % wins if wins > 1 else '')})
        if kid.get('saving') and self._saving(kid)['reached']:
            out.append({'id': 'goal', 'title': 'Sparemål nået'})
        return out

    # ---- penge ---------------------------------------------------------
    def balance(self, kid_id):
        return sum(e['amount'] for e in self.data['ledger'] if e['kid_id'] == kid_id)

    def _credit(self, kid_id, amount, kind, note='', item_id=None):
        self.data['ledger'].append({
            'id': _id(), 'kid_id': kid_id, 'amount': amount, 'kind': kind,
            'note': note, 'item_id': item_id,
            'at': self._now().isoformat(timespec='seconds'),
        })

    # ---- ugen ----------------------------------------------------------
    def _week_items(self, kid_id, statuses):
        wk = week_key(self._now())
        out = []
        for i in self.data['items']:
            if i['kid_id'] != kid_id or i['status'] not in statuses or not i['done_at']:
                continue
            when = dt.datetime.fromisoformat(i['done_at'])
            if week_key(when) == wk:
                out.append((when, i))
        return out

    def _bars(self, kid_id, lang='da'):
        today = self._now().weekday()
        counts = [0] * 7
        for when, _ in self._week_items(kid_id, ('wait', 'done')):
            counts[when.weekday()] += 1
        days = i18n.DAYS[i18n.valid(lang)]
        return [{'label': days[n], 'n': counts[n], 'today': n == today, 'future': n > today}
                for n in range(7)]

    def _score(self, kid):
        done = self._week_items(kid['id'], ('done',))
        return round(len(done) * age_factor(kid['age']), 2)

    def _hero_id(self):
        scores = [(self._score(k), k['id']) for k in self.data['kids']]
        if not scores:
            return None
        best = max(s for s, _ in scores)
        leaders = [kid_id for s, kid_id in scores if s == best]
        if best <= 0 or len(leaders) != 1:
            return None
        return leaders[0]

    # ---- barnets visning ----------------------------------------------
    def kid_view(self, token):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            self._refresh()
            today = self._now().strftime('%Y-%m-%d')
            items = []
            for i in self.data['items']:
                if i['kid_id'] != kid['id']:
                    continue
                if i['status'] in ('todo', 'wait'):
                    items.append(i)
                elif i['status'] == 'done' and (i['decided_at'] or '')[:10] == today:
                    items.append(i)
            order = {'todo': 0, 'wait': 1, 'done': 2}
            items.sort(key=lambda i: (order[i['status']], i['created']))
            week = self._week_items(kid['id'], ('wait', 'done'))
            return {
                'kid': {'id': kid['id'], 'name': kid['name'], 'age': kid['age'],
                        'color': kid['color']},
                'paused': bool(kid.get('paused')),
                'saving': self._saving(kid),
                'family': self._family(),
                'badges': self._badges(kid),
                'level': self._level(kid),
                'boss': self._boss_view(),
                'lang': self.lang_of(kid),
                'streak': self._streak_view(kid),
                'rewards': [{'id': r['id'], 'title': r['title'], 'price': r['price'],
                             'asked': any(c['kid_id'] == kid['id'] and c['reward_id'] == r['id']
                                          for c in self.data['claims'])}
                            for r in self.data['rewards']],
                'claims': [{'id': c['id'], 'title': c['title'], 'price': c['price']}
                           for c in self.data['claims'] if c['kid_id'] == kid['id']],
                'spendable': self.balance(kid['id']) - self._reserved(kid['id']),
                'wish': kid.get('wish'),
                'trading': bool(self.data['settings'].get('trading', True)),
                'siblings': [{'id': k['id'], 'name': k['name']} for k in self.data['kids']
                             if k['id'] != kid['id'] and not k.get('paused')],
                'trades_in': self._trade_views(kid)[0],
                'trades_out': self._trade_views(kid)[1],
                'birthday_today': self._birthday_today(kid),
                'balance': self.balance(kid['id']),
                'waiting': sum(i['price'] for i in self.data['items']
                               if i['kid_id'] == kid['id'] and i['status'] == 'wait'),
                'goal': self.data['settings']['goal'],
                'allowance_rule': self._allowance_view(kid),
                'completed': len(week),
                'bars': self._bars(kid['id'], self.lang_of(kid)),
                'week_label': 'Uge %d' % self._now().isocalendar()[1],
                'items': [{'id': i['id'], 'title': i['title'], 'room': i['room'],
                           'price': i['price'], 'status': i['status'],
                           'rejected': i['rejected'], 'slot': i.get('slot', 1),
                           'of': i.get('of', 1),
                           'need_photo': i['status'] == 'todo' and self._needs_photo(i),
                           'icon': self._icon_for(i['task_id'], i['title'], i['room']),
                           'streak': self._item_streak(kid['id'], i),
                           **self._extra_for(i)} for i in items],
                'jobs': [{'task_id': t['id'], 'title': t['title'], 'room': t['room'],
                          'icon': t.get('icon') or icons.guess(t['title'], t['room']),
                          'price': t['price'], 'expires': t.get('expires', '')}
                         for t in self._open_jobs_for(kid)],
            }

    def _extra_for(self, item):
        """Pligt (frist og træk) eller maddag (opskrift) til barnets side."""
        task = next((t for t in self.data['tasks'] if t['id'] == item['task_id']), None) or {}
        if task.get('duty'):
            return {'duty': {'due': task['duty']['due'], 'fine': task['duty'].get('fine', 0)}}
        if task.get('meal'):
            m = task['meal']
            return {'meal': {k: m.get(k) for k in ('meal', 'date', 'time', 'recipe', 'ingredients', 'url')}}
        return {}

    def _icon_for(self, task_id, title, room):
        task = next((t for t in self.data['tasks'] if t['id'] == task_id), None)
        return (task or {}).get('icon') or icons.guess(title, room)

    def _boss_view(self):
        boss = self._boss()
        if not boss:
            return None
        return {k: boss[k] for k in ('name', 'hp', 'hits', 'defeated')}

    def _needs_photo(self, item):
        task = next((t for t in self.data['tasks'] if t['id'] == item['task_id']), None)
        return bool(task and task.get('photo'))

    def _item_streak(self, kid_id, item):
        task = next((t for t in self.data['tasks'] if t['id'] == item['task_id']), None)
        return self._streak(kid_id, task) if task and item['status'] != 'missed' else 0

    def _birthday_today(self, kid):
        b = kid.get('birthday')
        if not b:
            return False
        born, today = dt.date.fromisoformat(b), self._now().date()
        return (born.month, born.day) == (today.month, today.day) and born.year != today.year

    def mark_done(self, token, item_id, photo=None):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            self._refresh()
            item = self._item(item_id)
            if item['kid_id'] != kid['id']:
                raise Problem('Det er ikke din opgave', 403)
            if item['status'] != 'todo':
                raise Problem('Opgaven er allerede meldt færdig')
            task = next((t for t in self.data['tasks'] if t['id'] == item['task_id']), None)
            if task and task.get('photo') and not photo:
                raise Problem('Tag et billede af opgaven først')
            if photo:
                self.save_photo(item['id'], photo)
                item['photo'] = True
            item['status'] = 'wait'
            item['done_at'] = self._now().isoformat(timespec='seconds')
            self._save()
            self._emit('done', task, kid)
            return kid, item

    def claim(self, token, task_id):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            self._refresh()
            task = self._task(task_id)
            if task not in self._open_jobs_for(kid):
                raise Problem('Opgaven er allerede taget')
            period = self._period(task, self._now())
            taken = sum(1 for i in self.data['items'] if i['task_id'] == task['id']
                        and i['period'] == period and i['status'] != 'missed')
            item = self._new_item(task, kid, self._now(), slot=taken + 1)
            self._save()
            self._emit('taken', task, kid)
            return kid, item

    # ---- hurtigknapper: giv en opgave for i dag ----------------------------
    @staticmethod
    def _giveable(task):
        """Også opgaver, der kun kommer, når forælderen giver dem (active False). Aldrig pligter, maddage og husets."""
        return not (task.get('duty') or task.get('meal') or task.get('auto_rule'))

    @staticmethod
    def _each(task):
        """Hvert barn sin egen? Gættes ud fra titlen, indtil forælderen selv vælger."""
        if task.get('each_auto', True):
            return guess_each(task['title'])
        return bool(task.get('each'))

    def _kids_for(self, task):
        return [k for k in self.data['kids'] if not k.get('paused') and self._in_scope(task, k)]

    def give_task(self, task_id, kid_id=None):
        """Forælderen giver en opgave for i dag: til ét barn, til hvert barn ('all'), eller som ledig opgave til alle.

        Returnerer (opgave, børn der skal have besked, item / liste af items eller None for en ledig opgave).
        """
        with self.lock:
            self._refresh()
            task = self._task(task_id)
            now = self._now()
            if not self._giveable(task):
                raise Problem('Den opgave kan ikke gives herfra')
            if not self._in_season(task, now):
                raise Problem('Opgaven hører ikke til på denne tid af året')
            if kid_id == 'all':                     # hver sin: en egen opgave til hvert barn, der må få den
                kids = self._kids_for(task)
                if not kids:
                    raise Problem('Intet barn kan tage den opgave')
                items = []
                for kid in kids:
                    item = self._new_item(task, kid, now)
                    item.update(period=now.strftime('%Y-%m-%d'), given=True, slot=1, of=1)
                    items.append(item)
                self._save()
                return task, kids, items
            if kid_id:
                kid = self._kid(kid_id)
                if kid.get('paused'):
                    raise Problem('%s er på pause' % kid['name'])
                if not self._in_scope(task, kid):
                    raise Problem('%s kan ikke få den opgave' % kid['name'])
                item = self._new_item(task, kid, now)
                item.update(period=now.strftime('%Y-%m-%d'), given=True, slot=1, of=1)
                self._save()
                return task, [kid], item
            kids = self._kids_for(task)
            if not kids:
                raise Problem('Intet barn kan tage den opgave')
            job = self.add_task(task['title'], task['price'], task['room'], 'once', True, task.get('kids'),
                                task.get('age_min', 0), task.get('age_max', 99), photo=task.get('photo', False),
                                auto_rule='given', icon=task.get('icon', ''))
            job.update(given_from=task['id'], until=now.date().isoformat() + 'T23:59:59')
            self._save()
            return job, kids, None

    def _quick(self):
        """Hurtigknapperne: fastgjorte først, så de mest brugte de sidste 30 dage, ellers rækkefølgen."""
        now = self._now()
        since = (now - dt.timedelta(days=USE_DAYS)).isoformat(timespec='seconds')
        use = {}
        for i in self.data['items']:
            if (i.get('created') or '') >= since and (i.get('given') or i.get('from_task')
                                                      or i['status'] in ('wait', 'done')):
                tid = i.get('from_task') or i['task_id']
                use[tid] = use.get(tid, 0) + 1
        ok = self._giveable_now(now)
        pinned = [t for t in ok if t.get('quick')]
        rest = sorted((t for t in ok if not t.get('quick')), key=lambda t: -use.get(t['id'], 0))
        pick = (pinned + rest)[:QUICK]
        return [{'id': t['id'], 'title': t['title'], 'price': t['price'], 'quick': bool(t.get('quick')),
                 'each': self._each(t),
                 'icon_shown': t.get('icon') or icons.guess(t['title'], t['room']),
                 'kids': [k['id'] for k in self._kids_for(t)]} for t in pick]

    def _giveable_now(self, now):
        return [t for t in self.data['tasks'] if self._giveable(t) and self._in_season(t, now)]

    def _quick_choices(self):
        """Arket "Tilføj": alle opgaver, der kan gives nu, og om de er fastgjort som hurtigknap."""
        return [{'id': t['id'], 'title': t['title'], 'price': t['price'], 'quick': bool(t.get('quick')),
                 'icon_shown': t.get('icon') or icons.guess(t['title'], t['room'])}
                for t in self._giveable_now(self._now())]

    # ---- forældrenes visning ------------------------------------------
    def admin_state(self):
        with self.lock:
            self._refresh()
            hero = self._hero_id()
            week = week_key(self._now())
            kids = []
            for k in self.data['kids']:
                done = self._week_items(k['id'], ('done',))
                kids.append({
                    'id': k['id'], 'name': k['name'], 'age': k['age'],
                    'color': k['color'], 'token': k['token'], 'lang': k.get('lang', ''),
                    'balance': self.balance(k['id']),
                    'tasks_week': len(done),
                    'bars': self._bars(k['id'], self.lang_of()),
                    'score': self._score(k),
                    'is_hero': k['id'] == hero,
                    'paused': bool(k.get('paused')),
                    'saving': self._saving(k),
                    'birthday': k.get('birthday', ''),
                    'notify': k.get('notify', ''),
                    'ntfy': k.get('ntfy', ''), 'ntfy_on': bool(k.get('ntfy_on')),
                    'push': len(k.get('push') or []),
                    'allowance': k.get('allowance', 0),
                    'allowance_rule': self._allowance_view(k),
                    'badges': self._badges(k),
                    'level': self._level(k),
                    'streak': self._best_streak(k['id']),
                })
            kid_names = {k['id']: k for k in self.data['kids']}
            pending = []
            for i in self.data['items']:
                if i['status'] == 'wait' and i['kid_id'] in kid_names:
                    kid = kid_names[i['kid_id']]
                    pending.append({'id': i['id'], 'title': i['title'], 'price': i['price'],
                                    'kid_id': kid['id'], 'name': kid['name'],
                                    'color': kid['color'], 'done_at': i['done_at'],
                                    'has_photo': bool(i.get('photo'))})
            pending.sort(key=lambda p: p['done_at'] or '')
            settings = self.data['settings']
            return {
                'kids': kids,
                'history': self._history(kid_names),
                'months': self._months(),
                'perfect': self._perfect_candidates(),
                'family': self._family(),
                'boss': self._boss(),
                'parents': [dict(p) for p in self.data['parents']],
                'lang': self.lang_of(),
                'langs': [[c, i18n.NAMES[c]] for c in i18n.LANGS],
                'locale': i18n.LOCALES[self.lang_of()],
                'advice': self.advice(),
                'rewards': [dict(r) for r in self.data['rewards']],
                'claims': [dict(c, name=next((k['name'] for k in self.data['kids'] if k['id'] == c['kid_id']), ''),
                                color=next((k['color'] for k in self.data['kids'] if k['id'] == c['kid_id']), '#888'))
                           for c in self.data['claims']],
                'wishes': [{'kid_id': k['id'], 'name': k['name'], 'color': k['color'], 'title': k['wish']['title'],
                            'price': k['wish']['price']} for k in self.data['kids'] if k.get('wish')],
                'to_pay': sum(max(0, self.balance(k['id'])) for k in self.data['kids']),
                'rules': [dict(r) for r in self.data['rules']],
                'settings': dict({k: settings.get(k) for k in
                                  ('penalty', 'perfect_bonus', 'reminder_time', 'celebrate_light',
                                   'boss_hp', 'boss_bonus', 'trading', 'streak_bonus', 'auto_task_hours',
                                   'min_tasks_age', 'min_tasks_week', 'meal_price')},
                                 weekly_summary=bool(settings.get('weekly_summary', True))),
                'pending': pending,
                'duties': self._duty_views(),
                'icons': icons.ICONS,
                'day_names': i18n.DAYS[self.lang_of()],
                'tasks': [dict(t, icon_shown=t.get('icon') or icons.guess(t['title'], t['room']),
                               each=self._each(t), each_auto=t.get('each_auto', True),
                               fair=self.fairness(t['price'], t['repeat'], t.get('times', 1), t['id']),
                               auto=outdoor.describe(self._auto_rule(t)),
                               auto_season=bool(self._auto(t)),
                               outdoor=not t.get('auto_rule') and outdoor.is_outdoor(t['title'], t['room']),
                               snow=not t.get('auto_rule') and outdoor.is_snow(t['title'], t['room']))
                          for t in self.data['tasks']],
                'quick': self._quick(),
                'quick_choices': self._quick_choices(),
                'weather': self._weather_view(),
                'total': sum(k['balance'] for k in kids),
                'goal': settings['goal'],
                'hero_bonus': settings['hero_bonus'],
                'hero_paid': settings.get('hero_paid_week') == week,
                'week_label': 'Uge %d' % self._now().isocalendar()[1],
            }

    def _weather_view(self):
        w = self.data['settings'].get('weather') or {}
        return {'entity': w['entity'], 'state': w.get('state', '')} if w.get('entity') else None

    def _duty_views(self):
        """Pligter til forældrene: hvem, frist og hvordan det går."""
        out = []
        kids = {k['id']: k for k in self.data['kids']}
        for t in self.data['tasks']:
            if not t.get('duty'):
                continue
            mine = {i['kid_id']: i['status'] for i in self.data['items'] if i['task_id'] == t['id']}
            out.append({'id': t['id'], 'title': t['title'], 'due': t['duty']['due'],
                        'fine': t['duty'].get('fine', 0),
                        'kids': [{'name': kids[k]['name'], 'color': kids[k]['color'],
                                  'status': mine.get(k, 'todo')} for k in t['kids'] if k in kids]})
        out.sort(key=lambda x: x['due'])
        return out

    def _history(self, kid_names, limit=30):
        paid_after = {}
        out = []
        for e in reversed(self.data['ledger']):
            kid = kid_names.get(e['kid_id'])
            if not kid:
                continue
            can_undo = False
            if e['kind'] == 'task' and e.get('item_id'):
                it = next((i for i in self.data['items'] if i['id'] == e['item_id']), None)
                can_undo = bool(it and it['status'] == 'done' and
                                self.balance(kid['id']) >= e['amount'])
            out.append({'id': e['id'], 'kid_id': kid['id'], 'name': kid['name'],
                        'color': kid['color'], 'amount': e['amount'], 'kind': e['kind'],
                        'note': e.get('note', ''), 'at': e['at'], 'item_id': e.get('item_id'),
                        'can_undo': can_undo})
            if len(out) >= limit:
                break
        return out

    def undo(self, item_id):
        """Fortryder en godkendelse: pengene trækkes tilbage, og opgaven venter igen."""
        with self.lock:
            item = self._item(item_id)
            if item['status'] != 'done':
                raise Problem('Opgaven er ikke godkendt')
            entry = next((e for e in self.data['ledger']
                          if e.get('item_id') == item_id and e['kind'] == 'task'), None)
            if entry and self.balance(item['kid_id']) < entry['amount']:
                raise Problem('Pengene er allerede udbetalt, så det kan ikke fortrydes')
            if entry:
                self.data['ledger'].remove(entry)
            item['status'] = 'wait'
            item['decided_at'] = None
            self._save()
            return item

    def _months(self, count=3):
        today = self._now()
        keys = []
        y, m = today.year, today.month
        for _ in range(count):
            keys.append((y, m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        out = []
        for y, m in keys:
            prefix = '%04d-%02d' % (y, m)
            per = []
            for k in self.data['kids']:
                amount = sum(e['amount'] for e in self.data['ledger']
                             if e['kid_id'] == k['id'] and e['kind'] in ('task', 'bonus', 'allowance')
                             and e['at'].startswith(prefix))
                per.append({'name': k['name'], 'color': k['color'], 'amount': amount})
            out.append({'label': MONTHS[m - 1] + (' %d' % y if y != today.year else ''),
                        'kids': per, 'total': sum(p['amount'] for p in per)})
        return out

    def _perfect_candidates(self):
        bonus = int(self.data['settings'].get('perfect_bonus') or 0)
        if bonus <= 0:
            return []
        prev = week_key(self._now() - dt.timedelta(days=7))
        paid = self.data['settings'].get('perfect_paid', {}).get(prev, [])
        out = []
        for k in self.data['kids']:
            if k['id'] in paid:
                continue
            mine = [i for i in self.data['items'] if i['kid_id'] == k['id']
                    and week_key(dt.datetime.fromisoformat(i['created'])) == prev]
            if len(mine) >= 3 and all(i['status'] == 'done' for i in mine):
                out.append({'kid_id': k['id'], 'name': k['name'], 'color': k['color'],
                            'amount': bonus, 'week': prev[-2:].lstrip('0')})
        return out

    def pay_perfect(self, kid_id):
        with self.lock:
            self._refresh()
            kid = self._kid(kid_id)
            cand = [c for c in self._perfect_candidates() if c['kid_id'] == kid_id]
            if not cand:
                raise Problem('Ingen perfekt uge at give bonus for')
            prev = week_key(self._now() - dt.timedelta(days=7))
            paid = self.data['settings'].setdefault('perfect_paid', {})
            paid.setdefault(prev, []).append(kid_id)
            # gem kun de seneste uger
            for key in sorted(paid)[:-6]:
                paid.pop(key)
            self._credit(kid_id, cand[0]['amount'], 'bonus', 'Perfekt uge')
            self._save()
            return kid, cand[0]['amount']

    # ---- rimelighedstjek -----------------------------------------------
    TYPICAL = {'daily': (2, 12), 'weekly': (5, 40), 'once': (5, 80)}

    def fairness(self, price, repeat='daily', times=1, skip_id=None):
        """Er prisen rimelig? {'level': 'ok'|'high'|'low', 'text': ...}"""
        try:
            price = int(round(float(str(price).replace(',', '.'))))
        except (TypeError, ValueError):
            return {'level': 'ok', 'text': ''}
        repeat = repeat if repeat in REPEATS else 'daily'
        times = max(1, min(5, int(times or 1)))
        lo, hi = self.TYPICAL[repeat]
        label = {'daily': 'daglige', 'weekly': 'ugentlige', 'once': 'enkeltstående'}[repeat]
        others = sorted(t['price'] for t in self.data['tasks']
                        if t['repeat'] == repeat and t['id'] != skip_id and t['price'] > 0
                        and not t.get('auto_rule') and not t.get('surprise') and not t.get('meal'))
        if price <= 0:
            return {'level': 'low', 'text': 'Opgaven er gratis. Er det meningen?'}
        if price > hi:
            return {'level': 'high', 'text': 'Højt: %s opgaver ligger ofte på %d–%d kr.' % (label, lo, hi)}
        if len(others) >= 3:
            median = others[len(others) // 2]
            if price > 2.5 * median:
                return {'level': 'high', 'text': 'Højt: dine andre %s opgaver koster typisk %d kr.' % (label, median)}
            if price < 0.4 * median:
                return {'level': 'low', 'text': 'Lavt: dine andre %s opgaver koster typisk %d kr.' % (label, median)}
        if price * times > 2 * hi:
            return {'level': 'high', 'text': 'Højt: %d gange %d kr. er meget for en %s opgave.' % (times, price, label[:-1])}
        return {'level': 'ok', 'text': 'Rimeligt.'}

    # ---- ugens boss ----------------------------------------------------
    def _boss(self):
        hp = int(self.data['settings'].get('boss_hp') or 0)
        if hp <= 0:
            return None
        now = self._now()
        week = week_key(now)
        hits = 0
        contributors = []
        for k in self.data['kids']:
            n = len(self._week_items(k['id'], ('done',)))
            hits += n
            if n:
                contributors.append(k['id'])
        year, wk, _ = now.isocalendar()
        return {'name': BOSSES[(year * 53 + wk) % len(BOSSES)], 'hp': hp, 'hits': min(hits, hp),
                'defeated': hits >= hp, 'bonus': int(self.data['settings'].get('boss_bonus') or 0),
                'paid': self.data['settings'].get('boss_paid_week') == week,
                'contributors': contributors}

    def pay_boss_bonus(self):
        with self.lock:
            self._refresh()
            boss = self._boss()
            if not boss or not boss['defeated']:
                raise Problem('Bossen er ikke besejret endnu')
            if boss['paid']:
                raise Problem('Bossbonussen er allerede givet')
            if boss['bonus'] <= 0:
                raise Problem('Der er ikke valgt en bonus')
            for kid_id in boss['contributors']:
                self._credit(kid_id, boss['bonus'], 'bonus', 'Besejrede ' + boss['name'])
            self.data['settings']['boss_paid_week'] = week_key(self._now())
            self._save()
            return boss

    # ---- overraskelsesopgaver -----------------------------------------
    def due_surprise(self, rng=None):
        """Opretter en ledig opgave til dobbelt pris, når dagens tilfældige tidspunkt er nået."""
        import random
        rng = rng or random
        with self.lock:
            self._refresh()
            now = self._now()
            templates = [t for t in self.data['tasks'] if t.get('surprise') and t['active']
                         and self._in_season(t, now) and not self._weather_blocks(t, now)]
            if not templates:
                return None
            today = now.strftime('%Y-%m-%d')
            plan = self.data['settings'].get('surprise_plan') or {}
            if plan.get('date') != today:
                at = ''
                if rng.random() < 0.5:                      # cirka hver anden dag
                    at = '%02d:%02d' % (rng.randint(15, 17), rng.randint(0, 59))
                plan = {'date': today, 'at': at, 'done': False}
                self.data['settings']['surprise_plan'] = plan
                self._save()
            if not plan['at'] or plan['done'] or now.strftime('%H:%M') < plan['at']:
                return None
            plan['done'] = True
            if any(t.get('auto_rule') == 'surprise' for t in self.data['tasks']):
                self._save()
                return None
            base = rng.choice(templates)
            task = self.add_task(base['title'], base['price'] * 2, 'Overraskelse', 'once', True,
                                 base.get('kids'), base.get('age_min', 0), base.get('age_max', 99),
                                 photo=base.get('photo', False), auto_rule='surprise')
            task['expires'] = (now + dt.timedelta(minutes=SURPRISE_MINUTES)).isoformat(timespec='seconds')
            self._save()
            return task

    # ---- bytte ---------------------------------------------------------
    def _trade_ok(self, item, sender, receiver, amount):
        task = next((t for t in self.data['tasks'] if t['id'] == item['task_id']), None)
        if not self.data['settings'].get('trading', True):
            raise Problem('Bytte er slået fra')
        if item['kid_id'] != sender['id'] or item['status'] != 'todo':
            raise Problem('Den opgave kan ikke byttes')
        if receiver['id'] == sender['id'] or receiver.get('paused'):
            raise Problem('Det barn kan ikke tage den')
        if task and not self._in_scope(task, receiver):
            raise Problem('%s er ikke gammel nok til den opgave' % receiver['name'])
        if amount < 0 or amount > item['price']:
            raise Problem('Beløbet skal være mellem 0 og %d kr.' % item['price'])
        if amount > self.balance(sender['id']):
            raise Problem('Du har ikke penge nok til at betale for et bytte')

    def offer_trade(self, token, item_id, to_kid_id, amount):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            self._refresh()
            item = self._item(item_id)
            receiver = self._kid(to_kid_id)
            try:
                amount = int(amount or 0)
            except (TypeError, ValueError):
                raise Problem('Beløbet skal være et tal')
            self._trade_ok(item, kid, receiver, amount)
            if any(t['item_id'] == item_id for t in self.data['trades']):
                raise Problem('Du har allerede tilbudt den opgave')
            trade = {'id': _id(), 'item_id': item_id, 'from': kid['id'], 'to': receiver['id'],
                     'amount': amount, 'at': self._now().isoformat(timespec='seconds')}
            self.data['trades'].append(trade)
            self._save()
            return kid, receiver, trade, item

    def _trade(self, trade_id):
        for t in self.data['trades']:
            if t['id'] == trade_id:
                return t
        raise Problem('Tilbuddet findes ikke længere', 404)

    def accept_trade(self, token, trade_id):
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            self._refresh()
            trade = self._trade(trade_id)
            if trade['to'] != kid['id']:
                raise Problem('Det tilbud er ikke til dig', 403)
            item = self._item(trade['item_id'])
            sender = self._kid(trade['from'])
            self._trade_ok(item, sender, kid, trade['amount'])
            item['status'] = 'traded'
            new = dict(item, id=_id(), kid_id=kid['id'], status='todo', done_at=None,
                       decided_at=None, rejected=0, slot=item.get('slot', 1))
            new.pop('photo', None)
            self.data['items'].append(new)
            if trade['amount']:
                self._credit(sender['id'], -trade['amount'], 'trade', 'Bytte: ' + item['title'])
                self._credit(kid['id'], trade['amount'], 'trade', 'Bytte: ' + item['title'])
            self.data['trades'].remove(trade)
            self._save()
            return sender, kid, new

    def end_trade(self, token, trade_id):
        """Afviser (modtageren) eller trækker tilbage (afsenderen)."""
        with self.lock:
            kid = self.kid_by_token(token)
            if not kid:
                raise Problem('Linket passer ikke', 404)
            trade = self._trade(trade_id)
            if kid['id'] not in (trade['from'], trade['to']):
                raise Problem('Det tilbud er ikke dit', 403)
            self.data['trades'].remove(trade)
            self._save()
            return kid, trade

    def _trade_views(self, kid):
        items = {i['id']: i for i in self.data['items']}
        kids = {k['id']: k for k in self.data['kids']}
        incoming, outgoing = [], []
        for t in self.data['trades']:
            item = items.get(t['item_id'])
            if not item or item['status'] != 'todo' or t['from'] not in kids or t['to'] not in kids:
                continue
            view = {'id': t['id'], 'title': item['title'], 'price': item['price'],
                    'amount': t['amount'], 'from': kids[t['from']]['name'], 'to': kids[t['to']]['name'],
                    'item_id': item['id']}
            if t['to'] == kid['id']:
                incoming.append(view)
            elif t['from'] == kid['id']:
                outgoing.append(view)
        return incoming, outgoing

    # ---- niveau --------------------------------------------------------
    def _level(self, kid):
        count = sum(1 for e in self.data['ledger'] if e['kid_id'] == kid['id'] and e['kind'] == 'task')
        n = max(i for i, (need, _) in enumerate(LEVELS) if count >= need)
        nxt = LEVELS[n + 1][0] if n + 1 < len(LEVELS) else None
        return {'n': n + 1, 'name': LEVELS[n][1], 'count': count, 'next': nxt,
                'left': (nxt - count) if nxt else 0}

    # ---- huset-regler --------------------------------------------------
    @staticmethod
    def _clean_door(value):
        door = (value or '').strip().lower()
        if door and not (ENTITY.match(door) and door.startswith('binary_sensor.')):
            raise Problem('Dørsensoren skal ligne binary_sensor.vaskemaskine_dor')
        return door

    def add_rule(self, name, entity, title, price, door=''):
        with self.lock:
            entity = (entity or '').strip().lower()
            if not ENTITY.match(entity):
                raise Problem('Enhedens id skal ligne sensor.vaskemaskine')
            rule = {'id': _id(), 'name': self._clean_text(name, 'Navn', 40), 'entity': entity,
                    'title': self._clean_text(title, 'Navn på opgaven'),
                    'price': self._clean_price(price), 'active': True, 'door': self._clean_door(door)}
            self.data['rules'].append(rule)
            self._save()
            return rule

    def update_rule(self, rule_id, active=None, door=None):
        with self.lock:
            rule = self._rule(rule_id)
            if active is not None:
                rule['active'] = bool(active)
            if door is not None:
                rule['door'] = self._clean_door(door)
            self._save()
            return rule

    def drop_open_job(self, rule_id=None, machine=None):
        """Fjerner en LEDIG husopgave (ingen har taget den): maskinen er tømt eller kører igen.

        Med rule_id: opgaven fra den regel. Med machine: den ældste fra en regel med samme maskinetype.
        Returnerer den fjernede opgave eller None. En taget opgave bliver altid liggende.
        """
        with self.lock:
            if machine is not None and machine not in MACHINES:
                return None
            rules = {r['id']: r for r in self.data['rules']}
            for t in self.data['tasks']:
                rid = t.get('auto_rule')
                if not rid or rid not in rules or (rule_id and rid != rule_id):
                    continue
                if machine is not None and machine_type(rules[rid]['name']) != machine:
                    continue
                if self._taken(t):
                    continue
                self.data['tasks'].remove(t)
                self._save()
                self._emit('removed', t)
                return t
            return None

    def delete_rule(self, rule_id):
        with self.lock:
            self._rule(rule_id)
            self.data['rules'] = [r for r in self.data['rules'] if r['id'] != rule_id]
            self.data['tasks'] = [t for t in self.data['tasks'] if t.get('auto_rule') != rule_id]
            self._save()

    def _rule(self, rule_id):
        for r in self.data['rules']:
            if r['id'] == rule_id:
                return r
        raise Problem('Reglen findes ikke', 404)

    def fire_rule(self, rule_id):
        """Huset melder 'færdig': opretter en ledig opgave. None, hvis den allerede ligger."""
        with self.lock:
            self._refresh()
            rule = self._rule(rule_id)
            if not rule['active']:
                return None
            if any(t.get('auto_rule') == rule_id for t in self.data['tasks']):
                return None
            task = self.add_task(rule['title'], rule['price'], 'Fra huset', 'once', True,
                                 auto_rule=rule_id)
            return task

    # ---- pligter uden betaling ------------------------------------------
    def add_duty(self, title, kids, date, time='', fine=0):
        """En pligt (pris 0) til et eller flere børn med en frist. Laves den ikke i tide, trækkes `fine`."""
        with self.lock:
            chosen = [k for k in (kids or []) if any(x['id'] == k for x in self.data['kids'])]
            if not chosen:
                raise Problem('Vælg mindst ét barn')
            try:
                day = dt.date.fromisoformat(str(date or '').strip())
            except ValueError:
                raise Problem('Fristen skal være en dato')
            time = (time or '').strip()
            if time and not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', time):
                raise Problem('Tidspunktet skal være som 17:00')
            due = dt.datetime.fromisoformat('%sT%s' % (day.isoformat(), time or '23:59'))
            if due <= self._now():
                raise Problem('Fristen er allerede gået')
            task = self.add_task(title, 0, '', 'once', kids=chosen)
            task['duty'] = {'due': due.isoformat(timespec='minutes'), 'fine': self._clean_price(fine or 0)}
            self._refresh()             # børnene får den med det samme
            self._save()
            return task

    # ---- navne udefra (Madplan, Hus-chat) ---------------------------------
    def kid_by_name(self, name):
        """Barnet med navnet. Helt ens vinder, ellers det første ord i barnets navn ("Dennis" -> "Dennis opgaver").
        Passer flere børn, gives None."""
        wanted = ' '.join(str(name or '').split()).lower()
        if not wanted:
            return None
        for test in (lambda k: ' '.join(k['name'].split()).lower() == wanted,
                     lambda k: (k['name'].split() or [''])[0].lower() == wanted):
            found = [k for k in self.data['kids'] if test(k)]
            if found:
                return found[0] if len(found) == 1 else None
        return None

    def meal_kid(self, data):
        """Barnet til en maddag: ud fra 'kid', ellers ud fra personen (person.dennis -> dennis)."""
        data = data if isinstance(data, dict) else {}
        person = str(data.get('person') or '')
        names = [str(data.get('kid') or ''),
                 person.split('.', 1)[1].replace('_', ' ') if person.startswith('person.') else person]
        for name in names:
            kid = self.kid_by_name(name)
            if kid:
                return kid
        return None

    # ---- maddage fra Madplan --------------------------------------------
    def add_meal(self, data):
        """Madplan har givet et barn en maddag. Samme barn og dato igen opdaterer opgaven. None, hvis barnet ikke findes."""
        with self.lock:
            data = data if isinstance(data, dict) else {}
            kid = self.meal_kid(data)
            if not kid:
                return None
            try:
                date = dt.date.fromisoformat(str(data.get('date') or '').strip()).isoformat()
            except ValueError:
                return None
            meal_name = str(data.get('meal') or '').strip()[:50]
            if not meal_name:
                return None
            time = str(data.get('time') or '').strip()
            url = str(data.get('url') or '').strip()
            ingredients = data.get('ingredients') if isinstance(data.get('ingredients'), list) else []
            meal = {'kid_id': kid['id'], 'date': date, 'meal': meal_name,
                    'time': time if re.match(r'^([01]\d|2[0-3]):[0-5]\d$', time) else '',
                    'recipe': str(data.get('recipe') or '').strip()[:4000],
                    'ingredients': [str(x).strip()[:120] for x in ingredients if str(x).strip()][:60],
                    'url': url[:500] if re.match(r'^https?://', url) else ''}
            title = 'Maddag: ' + meal_name
            price = self._clean_price(self.data['settings'].get('meal_price') or 0)
            task = next((t for t in self.data['tasks'] if t.get('meal') and t['meal']['kid_id'] == kid['id']
                         and t['meal']['date'] == date), None)
            if task:
                if task['meal'].get('told'):
                    meal['told'] = task['meal']['told']     # beskeden er sendt: ikke igen samme dag
                task.update(title=title[:60], price=price, meal=meal)
                for i in self.data['items']:
                    if i['task_id'] == task['id'] and i['status'] == 'todo':
                        i.update(title=task['title'], price=price)
                self._save()
            else:
                task = self.add_task(title, price, 'Køkken', 'once', kids=[kid['id']], icon='🍳')
                task['meal'] = meal
                self._save()
            return task

    # ---- automatik: påmindelser og fødselsdage ------------------------
    def due_reminders(self):
        """[(kid, antal)] for børn med åbne opgaver, når påmindelsestiden er nået."""
        with self.lock:
            self._refresh()
            st = self.data['settings']
            at = st.get('reminder_time') or ''
            now = self._now()
            if not at or st.get('reminder_sent') == now.strftime('%Y-%m-%d'):
                return []
            if now.strftime('%H:%M') < at:
                return []
            st['reminder_sent'] = now.strftime('%Y-%m-%d')
            self._save()
            out = []
            for k in self.data['kids']:
                n = sum(1 for i in self.data['items']
                        if i['kid_id'] == k['id'] and i['status'] == 'todo')
                if n and not k.get('paused'):
                    out.append((k, n))
            return out

    def weekly_summary(self):
        """Tekst til forældrene om søndagen kl. 18 (én gang pr. uge). Ellers None."""
        with self.lock:
            self._refresh()
            st = self.data['settings']
            now = self._now()
            wk = week_key(now)
            if not st.get('weekly_summary', True) or now.weekday() != 6 or now.hour < 18 \
                    or st.get('summary_week') == wk or not self.data['kids']:
                return None
            st['summary_week'] = wk
            self._save()
            lines = []
            for k in self.data['kids']:
                done = self._week_items(k['id'], ('done',))
                money = sum(i['price'] for _, i in done)
                line = '%s: %d opgave%s, %d kr.' % (k['name'], len(done), '' if len(done) == 1 else 'r', money)
                bal = self.balance(k['id'])
                if bal > 0:
                    line += ' (til udbetaling: %d kr.)' % bal
                lines.append(line)
            boss = self._boss()
            if boss:
                lines.append('%s: %s' % (boss['name'], 'besejret!' if boss['defeated']
                                         else '%d af %d slag' % (boss['hits'], boss['hp'])))
            return 'Uge %d\n' % now.isocalendar()[1] + '\n'.join(lines)

    def birthday_notices(self):
        """Børn, der fylder år i morgen (kun efter kl. 16, én gang pr. år)."""
        with self.lock:
            now = self._now()
            if now.hour < 16:
                return []
            tomorrow = now.date() + dt.timedelta(days=1)
            out = []
            for k in self.data['kids']:
                b = k.get('birthday')
                if not b or k.get('bday_notice') == now.year:
                    continue
                born = dt.date.fromisoformat(b)
                if (born.month, born.day) == (tomorrow.month, tomorrow.day):
                    k['bday_notice'] = now.year
                    out.append((k, age_on(born, tomorrow)))
            if out:
                self._save()
            return out

    def decide(self, item_id, approve):
        with self.lock:
            item = self._item(item_id)
            if item['status'] != 'wait':
                raise Problem('Opgaven venter ikke på godkendelse')
            if approve:
                item['status'] = 'done'
                item['decided_at'] = self._now().isoformat(timespec='seconds')
                self._credit(item['kid_id'], item['price'], 'task', item['title'], item['id'])
                self._streak_bonus(item['kid_id'])
            else:
                item['status'] = 'todo'
                item['done_at'] = None
                item['rejected'] += 1
            item.pop('photo', None)
            self.delete_photo(item_id)
            self._save()
            return item

    def payout(self, kid_id):
        with self.lock:
            self._kid(kid_id)
            amount = self.balance(kid_id)
            if amount <= 0:
                raise Problem('Der er ikke noget at udbetale')
            self._credit(kid_id, -amount, 'payout', 'Udbetalt')
            self._save()
            return amount

    def pay_hero_bonus(self):
        with self.lock:
            self._refresh()
            week = week_key(self._now())
            if self.data['settings'].get('hero_paid_week') == week:
                raise Problem('Ugens bonus er allerede givet')
            hero = self._hero_id()
            if not hero:
                raise Problem('Der er ingen ugens helt endnu')
            amount = int(self.data['settings']['hero_bonus'])
            self._credit(hero, amount, 'bonus', 'Ugens helt')
            wins = self.data['settings'].setdefault('hero_wins', {})
            wins[hero] = wins.get(hero, 0) + 1
            self.data['settings']['hero_paid_week'] = week
            self._save()
            return hero, amount

    def set_setting(self, key, value):
        with self.lock:
            if key == 'goal':
                value = int(value)
                if value < 1 or value > 50:
                    raise Problem('Målet skal være mellem 1 og 50')
            elif key == 'lang':
                value = i18n.valid(value)
            elif key in ('trading', 'weekly_summary'):
                value = bool(value)
            elif key == 'boss_hp':
                value = int(value or 0)
                if value < 0 or value > 500:
                    raise Problem('Bossens liv skal være mellem 0 og 500')
            elif key in ('hero_bonus', 'penalty', 'perfect_bonus', 'boss_bonus', 'streak_bonus', 'meal_price'):
                value = self._clean_price(value or 0)
            elif key in ('auto_task_hours', 'min_tasks_age', 'min_tasks_week'):
                top = {'auto_task_hours': 72, 'min_tasks_age': 25, 'min_tasks_week': 50}[key]
                try:
                    value = int(value or 0)
                except (TypeError, ValueError):
                    raise Problem('Skriv et tal')
                if value < 0 or value > top:
                    raise Problem('Tallet skal være mellem 0 og %d' % top)
            elif key == 'reminder_time':
                value = (value or '').strip()
                if value and not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', value):
                    raise Problem('Tidspunktet skal være som 17:00')
            elif key == 'outside_url':
                value = (value or '').strip().rstrip('/')
                if value and not re.match(r'^https?://[^\s/]+(/[A-Za-z0-9_./-]*)?$', value):
                    raise Problem('Forkert adresse')
            elif key == 'celebrate_light':
                value = (value or '').strip().lower()
                if value and not (ENTITY.match(value) and value.startswith('light.')):
                    raise Problem('Vælg en lampe, fx light.stue')
            else:
                raise Problem('Ukendt indstilling')
            self.data['settings'][key] = value
            self._save()
