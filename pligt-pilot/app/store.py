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
import secrets
import threading
import uuid

COLORS = ['#0B7A70', '#C73A30', '#6C4AB6', '#B05A00', '#1F6FB2', '#B03A83']
DAYS = ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn']
REPEATS = ('daily', 'weekly', 'once')


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
            'settings': {'goal': 8, 'hero_bonus': 20, 'hero_paid_week': ''},
        }
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
    def add_kid(self, name, age, color=None):
        with self.lock:
            kid = {
                'id': _id(),
                'name': self._clean_text(name, 'Navn', 30),
                'age': self._clean_age(age),
                'color': color or COLORS[len(self.data['kids']) % len(COLORS)],
                'token': secrets.token_urlsafe(12),
            }
            self.data['kids'].append(kid)
            self._save()
            return kid

    def update_kid(self, kid_id, name=None, age=None, color=None, paused=None):
        with self.lock:
            kid = self._kid(kid_id)
            if name is not None:
                kid['name'] = self._clean_text(name, 'Navn', 30)
            if age is not None:
                kid['age'] = self._clean_age(age)
            if color:
                kid['color'] = color
            if paused is not None:
                kid['paused'] = bool(paused)
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

    def _saving(self, kid):
        goal = kid.get('saving')
        if not goal:
            return None
        saved = sum(e['amount'] for e in self.data['ledger']
                    if e['kid_id'] == kid['id'] and e['kind'] in ('task', 'bonus')
                    and e['at'] >= goal['since'])
        saved = max(0, saved)
        return {'title': goal['title'], 'amount': goal['amount'], 'saved': min(saved, goal['amount']),
                'reached': saved >= goal['amount']}

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
            d['items'] = [i for i in d['items'] if i['kid_id'] != kid_id]
            d['ledger'] = [e for e in d['ledger'] if e['kid_id'] != kid_id]
            for t in d['tasks']:
                if kid_id in (t.get('kids') or []):
                    t['kids'] = [x for x in t['kids'] if x != kid_id]
            self._save()

    # ---- opgaver -------------------------------------------------------
    def add_task(self, title, price, room='', repeat='daily', open_job=False,
                 kids=None, age_min=0, age_max=99, times=1):
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
                'active': True,
            }
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
        tasks = {t['id']: t for t in self.data['tasks']}
        changed = False
        for it in self.data['items']:
            if it['status'] != 'todo':
                continue
            t = tasks.get(it['task_id'])
            paused = any(k['id'] == it['kid_id'] and k.get('paused') for k in self.data['kids'])
            stale = (t is None or not t['active'] or paused or
                     (t['repeat'] != 'once' and it['period'] != period_key(t['repeat'], d)))
            if stale:
                it['status'] = 'missed'
                changed = True
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
                           'of': i.get('of', 1)} for i in items],
                'jobs': [{'task_id': t['id'], 'title': t['title'], 'room': t['room'],
                          'price': t['price']} for t in self._open_jobs_for(kid)],
            }

    def mark_done(self, token, item_id):
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
                })
            kid_names = {k['id']: k for k in self.data['kids']}
            pending = []
            for i in self.data['items']:
                if i['status'] == 'wait' and i['kid_id'] in kid_names:
                    kid = kid_names[i['kid_id']]
                    pending.append({'id': i['id'], 'title': i['title'], 'price': i['price'],
                                    'kid_id': kid['id'], 'name': kid['name'],
                                    'color': kid['color'], 'done_at': i['done_at']})
            pending.sort(key=lambda p: p['done_at'] or '')
            settings = self.data['settings']
            return {
                'kids': kids,
                'history': self._history(kid_names),
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
            self.data['settings']['hero_paid_week'] = week
            self._save()
            return hero, amount

    def set_setting(self, key, value):
        with self.lock:
            if key == 'goal':
                value = int(value)
                if value < 1 or value > 50:
                    raise Problem('Målet skal være mellem 1 og 50')
            elif key == 'hero_bonus':
                value = self._clean_price(value)
            else:
                raise Problem('Ukendt indstilling')
            self.data['settings'][key] = value
            self._save()
