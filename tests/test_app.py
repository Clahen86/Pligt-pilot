import datetime as dt
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pligt-pilot', 'app'))

from ha import HomeAssistant  # noqa: E402
from server import App, serve  # noqa: E402
from store import Problem, Store  # noqa: E402


class Clock:
    def __init__(self, when):
        self.when = when

    def __call__(self):
        return self.when

    def advance(self, **kw):
        self.when += dt.timedelta(**kw)


def monday():
    return dt.datetime(2026, 11, 16, 8, 0, 0)  # en mandag, uge 47


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 8)
        self.maja = self.store.add_kid('Maja', 12)

    def kid_items(self, kid):
        return self.store.kid_view(kid['token'])['items']

    def test_daily_task_goes_to_every_child_in_scope(self):
        self.store.add_task('Dæk bord', 3)
        self.assertEqual([i['title'] for i in self.kid_items(self.emil)], ['Dæk bord'])
        self.assertEqual([i['title'] for i in self.kid_items(self.maja)], ['Dæk bord'])

    def test_age_limit_hides_task_from_young_child(self):
        self.store.add_task('Støvsug stuen', 15, age_min=11)
        self.assertEqual(self.kid_items(self.emil), [])
        self.assertEqual(len(self.kid_items(self.maja)), 1)

    def test_only_chosen_children_get_the_task(self):
        self.store.add_task('Pas kaninen', 5, kids=[self.emil['id']])
        self.assertEqual(len(self.kid_items(self.emil)), 1)
        self.assertEqual(self.kid_items(self.maja), [])

    def test_full_flow_done_approve_balance(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        state = self.store.admin_state()
        self.assertEqual([p['name'] for p in state['pending']], ['Emil'])
        view = self.store.kid_view(self.emil['token'])
        self.assertEqual(view['waiting'], 3)
        self.assertEqual(view['balance'], 0)
        self.store.decide(item['id'], True)
        view = self.store.kid_view(self.emil['token'])
        self.assertEqual(view['balance'], 3)
        self.assertEqual(view['items'][0]['status'], 'done')
        self.assertEqual(self.store.admin_state()['pending'], [])

    def test_reject_puts_task_back_for_another_try(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], False)
        again = self.kid_items(self.emil)[0]
        self.assertEqual(again['status'], 'todo')
        self.assertEqual(again['rejected'], 1)
        self.assertEqual(self.store.balance(self.emil['id']), 0)

    def test_cannot_approve_twice(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        with self.assertRaises(Problem):
            self.store.decide(item['id'], True)
        self.assertEqual(self.store.balance(self.emil['id']), 3)

    def test_child_cannot_finish_siblings_task(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.maja)[0]
        with self.assertRaises(Problem) as ctx:
            self.store.mark_done(self.emil['token'], item['id'])
        self.assertEqual(ctx.exception.status, 403)

    def test_wrong_token_is_rejected(self):
        with self.assertRaises(Problem) as ctx:
            self.store.kid_view('forkert-link-123')
        self.assertEqual(ctx.exception.status, 404)

    def test_daily_task_comes_back_next_day_and_old_one_expires(self):
        self.store.add_task('Dæk bord', 3)
        self.assertEqual(len(self.kid_items(self.emil)), 1)
        self.clock.advance(days=1)
        items = self.kid_items(self.emil)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['status'], 'todo')
        todo = [i for i in self.store.data['items'] if i['kid_id'] == self.emil['id']]
        self.assertEqual(sorted(i['status'] for i in todo), ['missed', 'todo'])

    def test_waiting_task_survives_the_night(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.clock.advance(days=1)
        self.assertEqual(len(self.store.admin_state()['pending']), 1)

    def test_weekly_task_lasts_the_week(self):
        self.store.add_task('Støvsug', 15, repeat='weekly')
        self.clock.advance(days=3)
        self.assertEqual(len(self.kid_items(self.emil)), 1)
        self.assertEqual(len([i for i in self.store.data['items']
                              if i['kid_id'] == self.emil['id']]), 1)
        self.clock.advance(days=5)
        self.assertEqual(len([i for i in self.store.data['items']
                              if i['kid_id'] == self.emil['id'] and i['status'] == 'todo']), 1)

    def test_once_task_does_not_repeat(self):
        self.store.add_task('Pak kasser ud', 20, repeat='once')
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        self.clock.advance(days=10)
        self.assertEqual(
            [i for i in self.kid_items(self.emil) if i['status'] == 'todo'], [])

    def test_open_job_goes_to_first_child_who_takes_it(self):
        task = self.store.add_task('Hæng vasketøj op', 8, open_job=True)
        view = self.store.kid_view(self.emil['token'])
        self.assertEqual([j['title'] for j in view['jobs']], ['Hæng vasketøj op'])
        self.assertEqual(view['items'], [])
        self.store.claim(self.emil['token'], task['id'])
        self.assertEqual(len(self.kid_items(self.emil)), 1)
        self.assertEqual(self.store.kid_view(self.maja['token'])['jobs'], [])
        with self.assertRaises(Problem):
            self.store.claim(self.maja['token'], task['id'])

    def test_payout_resets_balance(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        self.assertEqual(self.store.payout(self.emil['id']), 3)
        self.assertEqual(self.store.balance(self.emil['id']), 0)
        with self.assertRaises(Problem):
            self.store.payout(self.emil['id'])

    def test_week_hero_uses_age_points_and_bonus_once_a_week(self):
        self.store.add_task('Opgave A', 5)
        self.store.add_task('Opgave B', 5)
        self.assertFalse(any(k['is_hero'] for k in self.store.admin_state()['kids']))

        def finish(kid, n):
            items = [i for i in self.kid_items(kid) if i['status'] == 'todo'][:n]
            for it in items:
                self.store.mark_done(kid['token'], it['id'])
                self.store.decide(it['id'], True)

        finish(self.emil, 1)  # 1 * 1,4 = 1,4 point
        finish(self.maja, 2)  # 2 * 1,0 = 2,0 point
        hero = [k for k in self.store.admin_state()['kids'] if k['is_hero']]
        self.assertEqual([k['name'] for k in hero], ['Maja'])
        before = self.store.balance(self.maja['id'])
        self.store.pay_hero_bonus()
        self.assertEqual(self.store.balance(self.maja['id']), before + 20)
        with self.assertRaises(Problem):
            self.store.pay_hero_bonus()
        self.assertTrue(self.store.admin_state()['hero_paid'])

    def test_bars_count_the_week(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        bars = self.store.kid_view(self.emil['token'])['bars']
        self.assertEqual([b['n'] for b in bars], [1, 0, 0, 0, 0, 0, 0])
        self.assertTrue(bars[0]['today'])
        self.assertTrue(bars[6]['future'])

    def test_deactivated_task_disappears_and_returns(self):
        task = self.store.add_task('Dæk bord', 3)
        self.assertEqual(len(self.kid_items(self.emil)), 1)
        self.store.update_task(task['id'], active=False)
        self.assertEqual(self.kid_items(self.emil), [])
        self.store.update_task(task['id'], active=True)
        self.assertEqual(len(self.kid_items(self.emil)), 1)

    def test_bad_input_is_refused(self):
        with self.assertRaises(Problem):
            self.store.add_task('', 5)
        with self.assertRaises(Problem):
            self.store.add_task('Test', 'abc')
        with self.assertRaises(Problem):
            self.store.add_task('Test', 5000)
        with self.assertRaises(Problem):
            self.store.add_kid('', 8)
        with self.assertRaises(Problem):
            self.store.add_kid('Ole', 99)

    def test_paused_child_gets_no_tasks_until_back(self):
        self.store.add_task('Dæk bord', 3)
        self.store.add_task('Støvsug', 10, open_job=True)
        self.assertEqual(len(self.kid_items(self.emil)), 1)
        self.store.update_kid(self.emil['id'], paused=True)
        view = self.store.kid_view(self.emil['token'])
        self.assertTrue(view['paused'])
        self.assertEqual(view['items'], [])
        self.assertEqual(view['jobs'], [])
        self.assertEqual(len(self.kid_items(self.maja)), 1)
        self.store.update_kid(self.emil['id'], paused=False)
        self.assertEqual(len(self.kid_items(self.emil)), 1)

    def test_undo_takes_money_back_unless_paid_out(self):
        self.store.add_task('Dæk bord', 3)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        hist = self.store.admin_state()['history']
        self.assertTrue(hist[0]['can_undo'])
        self.store.undo(item['id'])
        self.assertEqual(self.store.balance(self.emil['id']), 0)
        self.assertEqual(self.store.admin_state()['pending'][0]['id'], item['id'])
        self.store.decide(item['id'], True)
        self.store.payout(self.emil['id'])
        self.assertFalse(self.store.admin_state()['history'][0]['can_undo'])
        with self.assertRaises(Problem):
            self.store.undo(item['id'])

    def test_task_can_be_done_several_times_a_day(self):
        self.store.add_task('Børst tænder', 2, times=2)
        items = self.kid_items(self.emil)
        self.assertEqual([(i['slot'], i['of']) for i in items], [(1, 2), (2, 2)])
        self.store.mark_done(self.emil['token'], items[0]['id'])
        self.assertEqual(len(self.kid_items(self.emil)), 2)
        self.store.update_task(self.store.data['tasks'][0]['id'], times=3)
        self.assertEqual(len(self.kid_items(self.emil)), 3)
        with self.assertRaises(Problem):
            self.store.update_task(self.store.data['tasks'][0]['id'], times=9)

    def test_open_job_with_two_slots_can_be_taken_twice(self):
        task = self.store.add_task('Vask bil', 20, open_job=True, times=2)
        self.store.claim(self.emil['token'], task['id'])
        self.assertEqual(len(self.store.kid_view(self.maja['token'])['jobs']), 1)
        self.store.claim(self.maja['token'], task['id'])
        self.assertEqual(self.store.kid_view(self.maja['token'])['jobs'], [])
        with self.assertRaises(Problem):
            self.store.claim(self.emil['token'], task['id'])

    def test_saving_goal_counts_earnings_after_it_is_set(self):
        self.store.add_task('Dæk bord', 3)
        first = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], first['id'])
        self.store.decide(first['id'], True)
        self.clock.advance(minutes=1)
        self.store.set_goal(self.emil['id'], 'Cykel', 10)
        self.assertEqual(self.store.kid_view(self.emil['token'])['saving']['saved'], 0)
        self.clock.advance(days=1)
        item = [i for i in self.kid_items(self.emil) if i['status'] == 'todo'][0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        self.store.payout(self.emil['id'])
        saving = self.store.kid_view(self.emil['token'])['saving']
        self.assertEqual((saving['saved'], saving['amount'], saving['reached']), (3, 10, False))
        self.store.set_goal(self.emil['id'], '', '')
        self.assertIsNone(self.store.kid_view(self.emil['token'])['saving'])
        with self.assertRaises(Problem):
            self.store.set_goal(self.emil['id'], 'Cykel', 0)

    def test_data_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'pligt.json')
            first = Store(path, self.clock)
            kid = first.add_kid('Emil', 8)
            first.add_task('Dæk bord', 3)
            again = Store(path, self.clock)
            self.assertEqual(again.data['kids'][0]['token'], kid['token'])
            self.assertEqual(len(again.kid_view(kid['token'])['items']), 1)

    def test_deleting_a_child_removes_the_data(self):
        self.store.add_task('Dæk bord', 3)
        self.store.delete_kid(self.emil['id'])
        self.assertEqual([k['name'] for k in self.store.data['kids']], ['Maja'])
        self.assertTrue(all(i['kid_id'] != self.emil['id'] for i in self.store.data['items']))
        with self.assertRaises(Problem):
            self.store.kid_view(self.emil['token'])


class FakeHA(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
        FakeHA.calls.append((self.path, self.headers.get('Authorization'), body))
        if self.path == '/template' and 'entity_id' in body:
            out = json.dumps(['sensor.vaskemaskine_effekt', 'Tørretumbler', 'light.stue']).encode()
        elif self.path == '/template':
            out = json.dumps(['Køkken', 'Bryggers', 'Have']).encode()
        else:
            out = b'[]'
        self.send_response(200)
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeHA.calls = []
        cls.fake = HTTPServer(('127.0.0.1', 0), FakeHA)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.clock = Clock(monday())
        cls.store = Store(None, cls.clock)
        ha = HomeAssistant('http://127.0.0.1:%d' % cls.fake.server_address[1], 'hemmelig',
                           'notify.mobile_app_far')
        cls.app = App(cls.store, ha, {'public_url': 'http://hjem.local:8099'})
        cls.kid_srv, _ = serve(cls.app, 'kid', 0, host='127.0.0.1')
        cls.adm_srv, _ = serve(cls.app, 'admin', 0, host='127.0.0.1')
        cls.kid = 'http://127.0.0.1:%d' % cls.kid_srv.server_address[1]
        cls.adm = 'http://127.0.0.1:%d' % cls.adm_srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        for s in (cls.kid_srv, cls.adm_srv, cls.fake):
            s.shutdown()

    def call(self, base, path, body=None, method=None, ctype='application/json'):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = ctype
        req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if resp.headers.get_content_type() ==
                                     'application/json' else raw.decode())
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                return err.code, json.loads(raw)
            except ValueError:
                return err.code, raw.decode()

    def test_everything_through_http(self):
        status, state = self.call(self.adm, '/api/kids', {'name': 'Emil', 'age': 8})
        self.assertEqual(status, 200)
        token = state['kids'][0]['token']
        status, state = self.call(self.adm, '/api/tasks', {'title': 'Dæk bord', 'price': 3})
        self.assertEqual(status, 200)

        status, view = self.call(self.kid, '/k/%s/api/state' % token)
        self.assertEqual(status, 200)
        item_id = view['items'][0]['id']
        status, view = self.call(self.kid, '/k/%s/api/items/%s/done' % (token, item_id), {})
        self.assertEqual(status, 200)
        self.assertEqual(view['items'][0]['status'], 'wait')

        # forælderen fik besked via Home Assistant
        import time
        for _ in range(40):
            if any('/services/notify/mobile_app_far' in c[0] for c in FakeHA.calls):
                break
            time.sleep(0.05)
        notify = [c for c in FakeHA.calls if c[0] == '/services/notify/mobile_app_far']
        self.assertEqual(len(notify), 1)
        self.assertEqual(notify[0][1], 'Bearer hemmelig')
        self.assertIn('Emil er færdig med: Dæk bord', json.loads(notify[0][2])['message'])

        status, state = self.call(self.adm, '/api/state')
        self.assertEqual(state['public_url'], 'http://hjem.local:8099')
        self.assertTrue(state['notify_on'])
        self.assertEqual(len(state['pending']), 1)
        status, state = self.call(self.adm, '/api/items/%s/approve' % item_id, {})
        self.assertEqual(state['kids'][0]['balance'], 3)
        status, view = self.call(self.kid, '/k/%s/api/state' % token)
        self.assertEqual(view['balance'], 3)

    def test_children_cannot_reach_parent_pages(self):
        for path in ('/', '/api/state', '/api/suggestions', '/api/kids'):
            status, _ = self.call(self.kid, path)
            self.assertIn(status, (200, 404), path)
        status, body = self.call(self.kid, '/api/state')
        self.assertEqual(status, 404)
        status, body = self.call(self.kid, '/api/kids', {'name': 'X', 'age': 5})
        self.assertEqual(status, 404)
        status, body = self.call(self.kid, '/')
        self.assertEqual(status, 200)
        self.assertNotIn('Oversigt', body)

    def test_wrong_link_gives_404_and_no_page(self):
        status, body = self.call(self.kid, '/k/forkertlink12345/')
        self.assertEqual(status, 404)
        status, body = self.call(self.kid, '/k/forkertlink12345/api/state')
        self.assertEqual(status, 404)

    def test_post_needs_json(self):
        status, body = self.call(self.adm, '/api/kids', {'name': 'A', 'age': 5},
                                 ctype='text/plain')
        self.assertEqual(status, 415)

    def test_suggestions_use_the_rooms_from_home_assistant(self):
        status, data = self.call(self.adm, '/api/suggestions')
        self.assertEqual(status, 200)
        rooms = {r['room'] for r in data['rows']}
        self.assertEqual(rooms, {'Køkken', 'Bryggers', 'Have', 'Vaskemaskine', 'Tørretumbler',
                                 'Hele huset'})
        titles = {r['title'] for r in data['rows']}
        self.assertIn('Hæng vasketøjet op', titles)
        self.assertNotIn('Tøm opvaskemaskinen', titles)
        self.assertTrue(any(r['found'] for r in data['rows']))

    def test_setup_creates_chosen_tasks_once(self):
        rows = [{'title': 'Test-opgave', 'price': 4, 'room': 'Køkken', 'age_min': 5,
                 'repeat': 'daily'}]
        _, state = self.call(self.adm, '/api/setup', {'rows': rows})
        count = len([t for t in state['tasks'] if t['title'] == 'Test-opgave'])
        _, state = self.call(self.adm, '/api/setup', {'rows': rows})
        again = len([t for t in state['tasks'] if t['title'] == 'Test-opgave'])
        self.assertEqual((count, again), (1, 1))

    def test_parent_server_can_be_limited_to_ingress(self):
        locked, _ = serve(self.app, 'admin', 0, allow_from={'172.30.32.2'}, host='127.0.0.1')
        try:
            base = 'http://127.0.0.1:%d' % locked.server_address[1]
            status, _ = self.call(base, '/api/state')
            self.assertEqual(status, 403)
        finally:
            locked.shutdown()


if __name__ == '__main__':
    unittest.main()
