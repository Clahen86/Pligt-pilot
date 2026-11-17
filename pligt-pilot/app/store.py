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

COLORS = ['#0B7A70', '#C73A30', '#6C4AB6', '#B05A00', '#1F6FB2', '#B03A83']
DAYS = ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn']
REPEATS = ('daily', 'weekly', 'once')
MONTHS = ['januar', 'februar', 'marts', 'april', 'maj', 'juni', 'juli', 'august',
          'september', 'oktober', 'november', 'december']
ENTITY = re.compile(r'^[a-z_]+\.[a-z0-9_]+$')
SERVICE = re.compile(r'^(notify\.)?[a-z0-9_]+$')
MAX_PHOTO = 450 * 1024


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
                         'family_goal': None, 'hero_wins': {}, 'perfect_paid': {}},
        }
        self._photos = {}
        self.photo_dir = os.path.join(os.path.dirname(path) or '.', 'photos') if path else None
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            for key, value in loaded.items():
                if key == 'settings':
                    self.data['settings'].update(value)
                else:
                    self.data[key] = value

    # ---- lagring -------------------------------------------------------
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
                   birthday=None, notify=None, allowance=None, ntfy_on=None):
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
                 kids=None, age_min=0, age_max=99, times=1, photo=False, auto_rule=None):
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
                'created': self._now().isoformat(timespec='seconds'),
                'active': True,
            }
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
                task['active'] = bool(fields['active'])
            if 'kids' in fields:
                task['kids'] = list(fields['kids'] or [])
            if 'times' in fields:
                task['times'] = self._clean_times(fields['times'])
            if 'photo' in fields:
                task['photo'] = bool(fields['photo'])
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
            'period': period_key(task['repeat'], d),
            'title': task['title'],
            'room': task['room'],
            'price': task['price'],
            'status': status,
            'created': d.isoformat(timespec='seconds'),
            'done_at': None,
            'decided_at': None,
            'rejected': 0,
        }
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
        # lommepenge: én gang pr. uge
        wk = week_key(d)
        for kid in self.data['kids']:
            if kid.get('allowance', 0) > 0 and kid.get('allowance_week') != wk:
                self._credit(kid['id'], kid['allowance'], 'allowance', 'Lommepenge')
                kid['allowance_week'] = wk
                changed = True
        # ryd huset-opgaver, der er klaret eller har ligget for længe
        for t in list(self.data['tasks']):
            if not t.get('auto_rule'):
                continue
            mine = [i for i in self.data['items'] if i['task_id'] == t['id']]
            finished = any(i['status'] == 'done' for i in mine) and not any(
                i['status'] in ('todo', 'wait') for i in mine)
            age = d - dt.datetime.fromisoformat(t.get('created') or d.isoformat())
            if finished or (not mine and age > dt.timedelta(days=2)):
                self.data['tasks'].remove(t)
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
            expired = (t is not None and t['repeat'] != 'once' and
                       it['period'] != period_key(t['repeat'], d))
            stale = t is None or not t['active'] or paused or expired
            if stale:
                it['status'] = 'missed'
                self.delete_photo(it['id'])
                changed = True
                if penalty and expired and t['active'] and not paused and not t.get('open'):
                    cut = min(penalty, max(0, self.balance(it['kid_id'])))
                    if cut:
                        self._credit(it['kid_id'], -cut, 'penalty', it['title'])
        existing = {}
        for i in self.data['items']:
            if i['status'] != 'missed':
                key = (i['task_id'], i['kid_id'], i['period'])
                existing[key] = existing.get(key, 0) + 1
        for t in self.data['tasks']:
            if not t['active'] or t['open']:
                continue
            period = period_key(t['repeat'], d)
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

    def _open_jobs_for(self, kid):
        d = self._now()
        jobs = []
        if kid.get('paused'):
            return jobs
        for t in self.data['tasks']:
            if not t['active'] or not t['open'] or not self._in_scope(t, kid):
                continue
            period = period_key(t['repeat'], d)
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

    def _bars(self, kid_id):
        today = self._now().weekday()
        counts = [0] * 7
        for when, _ in self._week_items(kid_id, ('wait', 'done')):
            counts[when.weekday()] += 1
        return [{'label': DAYS[n], 'n': counts[n], 'today': n == today, 'future': n > today}
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
                'birthday_today': self._birthday_today(kid),
                'balance': self.balance(kid['id']),
                'waiting': sum(i['price'] for i in self.data['items']
                               if i['kid_id'] == kid['id'] and i['status'] == 'wait'),
                'goal': self.data['settings']['goal'],
                'completed': len(week),
                'bars': self._bars(kid['id']),
                'week_label': 'Uge %d' % self._now().isocalendar()[1],
                'items': [{'id': i['id'], 'title': i['title'], 'room': i['room'],
                           'price': i['price'], 'status': i['status'],
                           'rejected': i['rejected'], 'slot': i.get('slot', 1),
                           'of': i.get('of', 1),
                           'need_photo': i['status'] == 'todo' and self._needs_photo(i),
                           'streak': self._item_streak(kid['id'], i)} for i in items],
                'jobs': [{'task_id': t['id'], 'title': t['title'], 'room': t['room'],
                          'price': t['price']} for t in self._open_jobs_for(kid)],
            }

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
            period = period_key(task['repeat'], self._now())
            taken = sum(1 for i in self.data['items'] if i['task_id'] == task['id']
                        and i['period'] == period and i['status'] != 'missed')
            item = self._new_item(task, kid, self._now(), slot=taken + 1)
            self._save()
            return kid, item

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
                    'color': k['color'], 'token': k['token'],
                    'balance': self.balance(k['id']),
                    'tasks_week': len(done),
                    'bars': self._bars(k['id']),
                    'score': self._score(k),
                    'is_hero': k['id'] == hero,
                    'paused': bool(k.get('paused')),
                    'saving': self._saving(k),
                    'birthday': k.get('birthday', ''),
                    'notify': k.get('notify', ''),
                    'ntfy': k.get('ntfy', ''), 'ntfy_on': bool(k.get('ntfy_on')),
                    'push': len(k.get('push') or []),
                    'allowance': k.get('allowance', 0),
                    'badges': self._badges(k),
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
                'rules': [dict(r) for r in self.data['rules']],
                'settings': {k: settings.get(k) for k in
                             ('penalty', 'perfect_bonus', 'reminder_time', 'celebrate_light')},
                'pending': pending,
                'tasks': [dict(t) for t in self.data['tasks']],
                'total': sum(k['balance'] for k in kids),
                'goal': settings['goal'],
                'hero_bonus': settings['hero_bonus'],
                'hero_paid': settings.get('hero_paid_week') == week,
                'week_label': 'Uge %d' % self._now().isocalendar()[1],
            }

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

    # ---- huset-regler --------------------------------------------------
    def add_rule(self, name, entity, title, price):
        with self.lock:
            entity = (entity or '').strip().lower()
            if not ENTITY.match(entity):
                raise Problem('Enhedens id skal ligne sensor.vaskemaskine')
            rule = {'id': _id(), 'name': self._clean_text(name, 'Navn', 40), 'entity': entity,
                    'title': self._clean_text(title, 'Navn på opgaven'),
                    'price': self._clean_price(price), 'active': True}
            self.data['rules'].append(rule)
            self._save()
            return rule

    def update_rule(self, rule_id, active=None):
        with self.lock:
            rule = self._rule(rule_id)
            if active is not None:
                rule['active'] = bool(active)
            self._save()
            return rule

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
            elif key in ('hero_bonus', 'penalty', 'perfect_bonus'):
                value = self._clean_price(value or 0)
            elif key == 'reminder_time':
                value = (value or '').strip()
                if value and not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', value):
                    raise Problem('Tidspunktet skal være som 17:00')
            elif key == 'celebrate_light':
                value = (value or '').strip().lower()
                if value and not (ENTITY.match(value) and value.startswith('light.')):
                    raise Problem('Vælg en lampe, fx light.stue')
            else:
                raise Problem('Ukendt indstilling')
            self.data['settings'][key] = value
            self._save()
