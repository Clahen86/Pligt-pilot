import datetime as dt
import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pligt-pilot', 'app'))

from ha import HomeAssistant  # noqa: E402
from server import App, make_tls, serve  # noqa: E402
import push  # noqa: E402
from house import Automation, find_sensors, step  # noqa: E402
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

    def finish(self, kid, title=None):
        for i in self.kid_items(kid):
            if i['status'] == 'todo' and (title is None or i['title'] == title):
                self.store.mark_done(kid['token'], i['id'])
                self.store.decide(i['id'], True)
                return i

    def test_birthday_sets_age_and_unlocks_tasks(self):
        kid = self.store.add_kid('Ida', birthday='2017-11-20')  # 8 år i dag
        self.assertEqual(kid['age'], 8)
        self.store.add_task('Støvsug', 10, age_min=9)
        self.assertEqual(self.kid_items(kid), [])
        self.clock.advance(days=4)  # 20. nov. bliver hun 9
        self.assertEqual(len(self.kid_items(kid)), 1)
        self.assertEqual(self.store.admin_state()['kids'][-1]['age'], 9)
        self.assertTrue(self.store.kid_view(kid['token'])['birthday_today'])
        self.clock.advance(days=1)
        self.assertFalse(self.store.kid_view(kid['token'])['birthday_today'])
        with self.assertRaises(Problem):
            self.store.add_kid('Fremtid', birthday='2999-01-01')

    def test_birthday_notice_only_once_the_evening_before(self):
        self.store.add_kid('Ida', birthday='2017-11-17')
        self.assertEqual(self.store.birthday_notices(), [])        # kl. 08
        self.clock.advance(hours=9)
        notices = self.store.birthday_notices()
        self.assertEqual([(k['name'], a) for k, a in notices], [('Ida', 9)])
        self.assertEqual(self.store.birthday_notices(), [])

    def test_streak_counts_days_in_a_row_and_gives_badges(self):
        self.store.add_task('Dæk bord', 3)
        for _ in range(3):
            self.finish(self.emil)
            self.clock.advance(days=1)
        item = self.kid_items(self.emil)[0]
        self.assertEqual(item['streak'], 3)
        titles = {b['title'] for b in self.store.kid_view(self.emil['token'])['badges']}
        self.assertTrue({'Første opgave', '3 i træk'} <= titles)
        self.clock.advance(days=2)   # en dag sprunget over
        self.assertEqual(self.kid_items(self.emil)[0]['streak'], 0)

    def test_allowance_is_paid_once_a_week(self):
        self.store.update_kid(self.emil['id'], allowance=20)
        self.assertEqual(self.store.balance(self.emil['id']), 0)
        self.clock.advance(days=7)
        self.store.admin_state()
        self.store.admin_state()
        self.assertEqual(self.store.balance(self.emil['id']), 20)

    def test_penalty_for_missed_task_never_below_zero(self):
        self.store.set_setting('penalty', 5)
        self.store.add_task('Dæk bord', 3)
        self.finish(self.emil)                      # +3 kr
        self.clock.advance(days=1)
        self.store.admin_state()                    # dag 2 oprettes
        self.assertEqual(self.store.balance(self.emil['id']), 3)
        self.clock.advance(days=1)
        self.store.admin_state()                    # dag 2 blev ikke lavet: træk, højst saldoen
        self.assertEqual(self.store.balance(self.emil['id']), 0)
        self.assertEqual(self.store.balance(self.maja['id']), 0)

    def test_perfect_week_bonus(self):
        self.store.set_setting('perfect_bonus', 10)
        self.store.add_task('Dæk bord', 3)
        for _ in range(7):
            self.finish(self.emil)
            self.clock.advance(days=1)
        names = [c['name'] for c in self.store.admin_state()['perfect']]
        self.assertEqual(names, ['Emil'])    # Maja lavede ingenting
        before = self.store.balance(self.emil['id'])
        self.store.pay_perfect(self.emil['id'])
        self.assertEqual(self.store.balance(self.emil['id']), before + 10)
        self.assertEqual(self.store.admin_state()['perfect'], [])
        with self.assertRaises(Problem):
            self.store.pay_perfect(self.emil['id'])

    def test_family_goal_and_monthly_overview(self):
        self.store.set_family_goal('Tivoli', 100)
        self.store.add_task('Dæk bord', 3)
        self.finish(self.emil)
        self.finish(self.maja)
        goal = self.store.kid_view(self.emil['token'])['family']
        self.assertEqual((goal['saved'], goal['amount']), (6, 100))
        month = self.store.admin_state()['months'][0]
        self.assertEqual(month['label'], 'november')
        self.assertEqual(month['total'], 6)
        self.store.set_family_goal('', '')
        self.assertIsNone(self.store.kid_view(self.emil['token'])['family'])

    def test_photo_is_required_and_deleted_after_decision(self):
        self.store.add_task('Ryd værelset', 10, photo=True)
        item = self.kid_items(self.emil)[0]
        self.assertTrue(item['need_photo'])
        with self.assertRaises(Problem):
            self.store.mark_done(self.emil['token'], item['id'])
        with self.assertRaises(Problem):
            self.store.mark_done(self.emil['token'], item['id'], b'ikke et billede')
        self.store.mark_done(self.emil['token'], item['id'], b'\xff\xd8\xff' + b'x' * 100)
        self.assertTrue(self.store.admin_state()['pending'][0]['has_photo'])
        self.assertIsNotNone(self.store.photo(item['id']))
        self.store.decide(item['id'], True)
        self.assertIsNone(self.store.photo(item['id']))

    def test_house_rule_creates_one_open_job_that_cleans_itself_up(self):
        rule = self.store.add_rule('Vaskemaskine', 'sensor.vaskemaskine_effekt',
                                   'Flyt tøj til tørretumbleren', 5)
        task = self.store.fire_rule(rule['id'])
        self.assertTrue(task['open'])
        self.assertIsNone(self.store.fire_rule(rule['id']))     # ingen dubletter
        jobs = self.store.kid_view(self.emil['token'])['jobs']
        self.assertEqual([j['title'] for j in jobs], ['Flyt tøj til tørretumbleren'])
        self.store.claim(self.emil['token'], task['id'])
        self.assertEqual(self.store.kid_view(self.maja['token'])['jobs'], [])
        self.finish(self.emil, 'Flyt tøj til tørretumbleren')
        self.store.admin_state()
        self.assertEqual(self.store.data['tasks'], [])
        self.assertIsNotNone(self.store.fire_rule(rule['id']))  # næste vask
        with self.assertRaises(Problem):
            self.store.add_rule('X', 'ikke et id', 'T', 1)

    def test_machine_is_done_after_it_has_been_quiet_for_a_while(self):
        t0 = dt.datetime(2026, 11, 16, 12, 0)
        state, done = step(None, '1200', t0)           # watt
        self.assertFalse(done)
        state, done = step(state, '0.2', t0 + dt.timedelta(minutes=1))
        self.assertFalse(done)                          # kan være en pause
        state, done = step(state, '900', t0 + dt.timedelta(minutes=2))
        state, done = step(state, '0.2', t0 + dt.timedelta(minutes=3))
        state, done = step(state, '0.3', t0 + dt.timedelta(minutes=7))
        self.assertTrue(done)
        state, done = step(state, '0.3', t0 + dt.timedelta(minutes=20))
        self.assertFalse(done)                          # kun én gang
        state, _ = step(None, 'washing', t0)
        state, done = step(state, 'finished', t0 + dt.timedelta(minutes=5))
        state, done = step(state, 'finished', t0 + dt.timedelta(minutes=6))
        self.assertTrue(done)
        _, done = step(None, 'off', t0)                 # aldrig kørt: ikke færdig
        self.assertFalse(done)

    def test_reminder_is_sent_once_a_day(self):
        self.store.add_task('Dæk bord', 3)
        self.store.set_setting('reminder_time', '17:00')
        self.assertEqual(self.store.due_reminders(), [])
        self.clock.advance(hours=10)
        got = self.store.due_reminders()
        self.assertEqual(sorted(k['name'] for k, n in got), ['Emil', 'Maja'])
        self.assertEqual(self.store.due_reminders(), [])
        with self.assertRaises(Problem):
            self.store.set_setting('reminder_time', '25:99')

    def test_every_child_has_a_private_ntfy_topic(self):
        topics = {k['ntfy'] for k in self.store.data['kids']}
        self.assertEqual(len(topics), 2)
        self.assertTrue(all(len(x) > 12 for x in topics))
        self.assertFalse(self.store.admin_state()['kids'][0]['ntfy_on'])
        self.store.update_kid(self.emil['id'], ntfy_on=True)
        self.assertTrue(self.store.admin_state()['kids'][0]['ntfy_on'])

    def test_fairness_check_flags_odd_prices(self):
        self.assertEqual(self.store.fairness(5, 'daily')['level'], 'ok')
        self.assertEqual(self.store.fairness(80, 'daily')['level'], 'high')
        self.assertEqual(self.store.fairness(0, 'weekly')['level'], 'low')
        self.assertEqual(self.store.fairness('abc')['text'], '')
        for title in ('A', 'B', 'C'):
            self.store.add_task(title, 10, repeat='weekly')
        self.assertEqual(self.store.fairness(35, 'weekly')['level'], 'high')   # > 2,5 x median
        self.assertEqual(self.store.fairness(2, 'weekly')['level'], 'low')
        self.assertEqual(self.store.fairness(10, 'weekly')['level'], 'ok')
        state = self.store.admin_state()
        self.assertTrue(all(t['fair']['level'] == 'ok' for t in state['tasks']))

    def test_seasonal_task_only_in_its_season(self):
        self.store.add_task('Skovl sne', 15, repeat='weekly', season='vinter')
        self.store.add_task('Fej blade', 15, repeat='weekly', season='efterår')
        titles = [i['title'] for i in self.kid_items(self.emil)]
        self.assertEqual(titles, ['Fej blade'])                  # november er efterår
        self.clock.advance(days=30)                              # december
        titles = [i['title'] for i in self.kid_items(self.emil)]
        self.assertEqual(titles, ['Skovl sne'])
        with self.assertRaises(Problem):
            self.store.add_task('X', 1, season='regntid')

    def test_boss_is_beaten_together_and_bonus_goes_to_those_who_helped(self):
        self.store.set_setting('boss_hp', 3)
        self.store.set_setting('boss_bonus', 5)
        self.store.add_task('Dæk bord', 3)
        self.store.add_task('Ryd op', 3)
        self.finish(self.emil, 'Dæk bord')
        self.finish(self.emil, 'Ryd op')
        boss = self.store.admin_state()['boss']
        self.assertEqual((boss['hits'], boss['hp'], boss['defeated']), (2, 3, False))
        with self.assertRaises(Problem):
            self.store.pay_boss_bonus()
        self.finish(self.maja, 'Dæk bord')
        self.assertTrue(self.store.admin_state()['boss']['defeated'])
        self.assertTrue(self.store.kid_view(self.maja['token'])['boss']['defeated'])
        self.store.pay_boss_bonus()
        self.assertEqual(self.store.balance(self.maja['id']), 3 + 5)
        with self.assertRaises(Problem):
            self.store.pay_boss_bonus()
        self.store.set_setting('boss_hp', 0)
        self.assertIsNone(self.store.admin_state()['boss'])

    def test_surprise_task_appears_once_with_double_price_and_expires(self):
        import random
        self.store.add_task('Vask bilen', 10, surprise=True)
        self.assertEqual(self.kid_items(self.emil), [])           # skabelonen vises aldrig selv
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'], [])

        class Rng(random.Random):
            def random(self):
                return 0.1                                          # i dag er en overraskelsesdag
            def randint(self, a, b):
                return a                                            # kl. 15:00
        rng = Rng()
        self.assertIsNone(self.store.due_surprise(rng))             # kl. 08 er for tidligt
        self.clock.advance(hours=7, minutes=1)
        task = self.store.due_surprise(rng)
        self.assertEqual((task['price'], task['open']), (20, True))
        self.assertIsNone(self.store.due_surprise(rng))             # kun én gang om dagen
        jobs = self.store.kid_view(self.emil['token'])['jobs']
        self.assertEqual([(j['title'], j['price']) for j in jobs], [('Vask bilen', 20)])
        self.assertTrue(jobs[0]['expires'])
        self.clock.advance(minutes=91)                              # ingen tog den
        self.store.admin_state()
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'], [])

    def test_starter_pack_fits_ages_and_is_not_made_twice(self):
        made = self.store.add_starter_pack()
        self.assertGreater(made, 8)
        self.assertEqual(self.store.add_starter_pack(), 0)
        titles = {t['title']: t for t in self.store.data['tasks']}
        self.assertEqual(titles['Gør badeværelset rent']['age_min'], 13)
        self.assertEqual(titles['Fej løv']['season'], 'efterår')

    def test_approve_all_skips_photo_items_and_pays_everyone(self):
        self.store.add_task('A', 5)
        self.store.add_task('B', 7)
        for i in list(self.kid_items(self.emil)):
            self.store.mark_done(self.emil['token'], i['id'])
        self.store.data['items'][0]['photo'] = True
        done = self.store.decide_all()
        self.assertEqual(len(done), 1)
        self.assertEqual(len([i for i in self.store.data['items'] if i['status'] == 'wait']), 1)

    def test_duplicate_task_makes_an_independent_copy(self):
        task = self.store.add_task('Dæk bord', 6, kids=[self.emil['id']])
        copy = self.store.duplicate_task(task['id'])
        self.assertNotEqual(copy['id'], task['id'])
        self.assertEqual(copy['title'], 'Dæk bord (kopi)')
        copy['kids'].append('x')
        self.assertEqual(task['kids'], [self.emil['id']])

    def test_weekly_summary_is_sent_once_on_sunday_evening(self):
        self.store.add_task('Dæk bord', 6)
        for i in self.kid_items(self.emil):
            self.store.mark_done(self.emil['token'], i['id'])
            self.store.decide(i['id'], True)
        self.assertIsNone(self.store.weekly_summary())              # mandag
        self.clock.when = dt.datetime(2026, 11, 22, 17, 0)
        self.assertIsNone(self.store.weekly_summary())              # søndag, men for tidligt
        self.clock.when = dt.datetime(2026, 11, 22, 18, 5)
        text = self.store.weekly_summary()
        self.assertIn('Uge 47', text)
        self.assertIn('%s: 1 opgave, 6 kr.' % self.emil['name'], text)
        self.assertIsNone(self.store.weekly_summary())
        self.store.set_setting('weekly_summary', False)
        self.store.data['settings']['summary_week'] = ''
        self.assertIsNone(self.store.weekly_summary())

    def test_rewards_are_reserved_and_paid_after_approval(self):
        self.store.add_task('Dæk bord', 20)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        reward = self.store.add_reward('Fredagsfilm', 15)
        with self.assertRaises(Problem):
            self.store.buy_reward(self.emil['token'], self.store.add_reward('Dyr ting', 500)['id'])
        self.store.buy_reward(self.emil['token'], reward['id'])
        with self.assertRaises(Problem):
            self.store.buy_reward(self.emil['token'], reward['id'])      # kun én ad gangen
        self.assertEqual(self.store.kid_view(self.emil['token'])['spendable'], 5)
        self.store.decide_claim(self.store.data['claims'][0]['id'], True)
        self.assertEqual(self.store.balance(self.emil['id']), 5)
        self.assertEqual(self.store.data['ledger'][-1]['kind'], 'reward')

    def test_rejected_reward_costs_nothing(self):
        self.store.add_task('Dæk bord', 20)
        item = self.kid_items(self.emil)[0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.store.decide(item['id'], True)
        reward = self.store.add_reward('Fredagsfilm', 15)
        self.store.buy_reward(self.emil['token'], reward['id'])
        self.store.decide_claim(self.store.data['claims'][0]['id'], False)
        self.assertEqual(self.store.balance(self.emil['id']), 20)
        self.assertEqual(self.store.data['claims'], [])

    def test_wish_becomes_a_saving_goal_when_accepted(self):
        self.store.make_wish(self.emil['token'], 'Ny bold', 150)
        self.assertEqual(self.store.admin_state()['wishes'][0]['title'], 'Ny bold')
        self.store.decide_wish(self.emil['id'], True)
        self.assertEqual(self.store.kid_view(self.emil['token'])['saving']['title'], 'Ny bold')
        self.assertEqual(self.store.admin_state()['wishes'], [])

    def test_five_days_in_a_row_pays_a_bonus_once(self):
        self.store.add_task('Dæk bord', 5)
        for day in range(5):
            for item in self.kid_items(self.emil):
                if item['status'] == 'todo':
                    self.store.mark_done(self.emil['token'], item['id'])
                    self.store.decide(item['id'], True)
            self.clock.advance(days=1)
        bonuses = [e for e in self.store.data['ledger'] if e['kind'] == 'bonus']
        self.assertEqual(len(bonuses), 1)
        self.assertEqual(bonuses[0]['amount'], 5)
        self.assertIn('5 dage', bonuses[0]['note'])

    def test_pay_all_and_advice(self):
        self.store.add_task('Dæk bord', 6)
        for k in (self.emil,):
            for item in self.kid_items(k):
                self.store.mark_done(k['token'], item['id'])
                self.store.decide(item['id'], True)
        self.assertEqual(self.store.pay_all(), 6)
        with self.assertRaises(Problem):
            self.store.pay_all()
        self.store.touch(self.emil['token'])
        self.clock.advance(days=4)
        self.assertTrue(any('ikke åbnet' in a for a in self.store.advice()))
        self.assertIn(b'"kids"', self.store.backup())

    def test_tasks_get_a_picture_from_their_name_or_a_chosen_one(self):
        import icons
        self.assertEqual(icons.guess('Dæk bord'), '🍴')
        self.assertEqual(icons.guess('Empty the dishwasher'), '🍽️')
        self.assertEqual(icons.guess('Noget helt andet'), '⭐')
        task = self.store.add_task('Dæk bord', 5)
        view = self.store.kid_view(self.emil['token'])
        self.assertEqual(view['items'][0]['icon'], '🍴')
        self.store.update_task(task['id'], icon='🧸')
        self.assertEqual(self.store.kid_view(self.emil['token'])['items'][0]['icon'], '🧸')
        self.store.update_task(task['id'], icon='<script>')              # ugyldigt ikon ignoreres
        self.assertEqual(self.store.kid_view(self.emil['token'])['items'][0]['icon'], '🍴')

    def test_surprise_day_can_be_a_quiet_day(self):
        import random

        class Quiet(random.Random):
            def random(self):
                return 0.9
        self.store.add_task('Vask bilen', 10, surprise=True)
        self.clock.advance(hours=12)
        self.assertIsNone(self.store.due_surprise(Quiet()))

    def test_trade_moves_the_task_and_money_but_does_not_double_it(self):
        self.store.add_task('Dæk bord', 6)
        self.store.add_task('Betaler', 10)
        self.finish(self.emil, 'Betaler')                           # Emil har nu 10 kr.
        item = [i for i in self.kid_items(self.emil) if i['title'] == 'Dæk bord'][0]
        kid, receiver, trade, _ = self.store.offer_trade(self.emil['token'], item['id'],
                                                         self.maja['id'], 4)
        view = self.store.kid_view(self.maja['token'])
        self.assertEqual([(t['title'], t['amount']) for t in view['trades_in']], [('Dæk bord', 4)])
        self.assertEqual(len(self.store.kid_view(self.emil['token'])['trades_out']), 1)
        with self.assertRaises(Problem):
            self.store.accept_trade(self.emil['token'], trade['id'])   # ikke hans tilbud
        self.store.accept_trade(self.maja['token'], trade['id'])
        self.assertEqual(self.store.balance(self.emil['id']), 10 - 4)
        self.assertEqual(self.store.balance(self.maja['id']), 4)
        mine = [i['title'] for i in self.kid_items(self.emil)]
        self.assertNotIn('Dæk bord', mine)                          # og kommer ikke tilbage
        self.assertEqual([i['title'] for i in self.kid_items(self.maja)].count('Dæk bord'), 2)
        self.assertEqual(self.store.kid_view(self.maja['token'])['trades_in'], [])

    def test_trade_rules(self):
        self.store.add_task('Dæk bord', 6)
        self.store.add_task('Støvsug', 15, age_min=10)
        emil_items = {i['title']: i for i in self.kid_items(self.emil)}
        maja_items = {i['title']: i for i in self.kid_items(self.maja)}
        with self.assertRaises(Problem):                            # kan ikke betale uden penge
            self.store.offer_trade(self.emil['token'], emil_items['Dæk bord']['id'], self.maja['id'], 3)
        with self.assertRaises(Problem):                            # for lille til opgaven
            self.store.offer_trade(self.maja['token'], maja_items['Støvsug']['id'], self.emil['id'], 0)
        with self.assertRaises(Problem):                            # sin søsters opgave
            self.store.offer_trade(self.emil['token'], maja_items['Dæk bord']['id'], self.maja['id'], 0)
        with self.assertRaises(Problem):                            # sig selv
            self.store.offer_trade(self.emil['token'], emil_items['Dæk bord']['id'], self.emil['id'], 0)
        _, _, trade, _ = self.store.offer_trade(self.emil['token'], emil_items['Dæk bord']['id'],
                                                self.maja['id'], 0)
        with self.assertRaises(Problem):                            # to tilbud på samme opgave
            self.store.offer_trade(self.emil['token'], emil_items['Dæk bord']['id'], self.maja['id'], 0)
        self.store.end_trade(self.maja['token'], trade['id'])      # afvist
        self.assertEqual(self.store.kid_view(self.maja['token'])['trades_in'], [])
        _, _, trade, _ = self.store.offer_trade(self.emil['token'], emil_items['Dæk bord']['id'],
                                                self.maja['id'], 0)
        self.store.mark_done(self.emil['token'], emil_items['Dæk bord']['id'])   # selv lavet
        self.assertEqual(self.store.kid_view(self.maja['token'])['trades_in'], [])
        with self.assertRaises(Problem):
            self.store.accept_trade(self.maja['token'], trade['id'])
        self.store.set_setting('trading', False)
        with self.assertRaises(Problem):
            self.store.offer_trade(self.maja['token'], maja_items['Dæk bord']['id'], self.emil['id'], 0)

    def test_level_grows_with_approved_tasks(self):
        self.store.add_task('Dæk bord', 3, times=3)
        self.assertEqual(self.store.kid_view(self.emil['token'])['level']['name'], 'Ægget')
        for _ in range(3):
            self.finish(self.emil)
        level = self.store.kid_view(self.emil['token'])['level']
        self.assertEqual((level['n'], level['name'], level['next'], level['left']), (2, 'Ungen', 10, 7))

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


class FindSensorTests(unittest.TestCase):
    ENTITIES = [
        ['switch.vaskemaskine_stik', 'Vaskemaskine stik', '', ''],
        ['sensor.vaskemaskine_effekt', 'Vaskemaskine effekt', 'power', 'W'],
        ['sensor.vaskemaskine_energi', 'Vaskemaskine energi', 'energy', 'kWh'],
        ['sensor.vaskemaskine_spaending', 'Vaskemaskine spænding', 'voltage', 'V'],
        ['sensor.opvaskemaskine_effekt', 'Opvaskemaskine effekt', 'power', 'W'],
        ['binary_sensor.toerretumbler_koerer', 'Tørretumbler kører', '', ''],
        ['light.stue', 'Stue', '', ''],
    ]

    def test_best_sensor_is_the_power_meter_not_plug_or_energy(self):
        found = {f['preset']: f for f in find_sensors(self.ENTITIES)}
        self.assertEqual(found['Vaskemaskine']['best']['entity'], 'sensor.vaskemaskine_effekt')
        self.assertEqual([a['entity'] for a in found['Vaskemaskine']['alts']],
                         ['switch.vaskemaskine_stik'])
        self.assertEqual(found['Opvaskemaskine']['best']['entity'], 'sensor.opvaskemaskine_effekt')
        self.assertEqual(found['Tørretumbler']['best']['entity'], 'binary_sensor.toerretumbler_koerer')

    def test_washer_does_not_pick_the_dishwasher_and_existing_rules_are_skipped(self):
        found = find_sensors(self.ENTITIES, existing_names=['Opvaskemaskine'])
        self.assertEqual([f['preset'] for f in found], ['Vaskemaskine', 'Tørretumbler'])
        self.assertEqual(find_sensors([['light.stue', 'Stue', '', '']]), [])


class PushTests(unittest.TestCase):
    def test_encryption_matches_the_example_in_rfc_8291(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        eph = ec.derive_private_key(
            int.from_bytes(push.unb64u('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'),
            ec.SECP256R1())
        body = push.encrypt(
            b'When I grow up, I want to be a watermelon',
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg', salt=push.unb64u('DGv6ra1nlYgDCS1FRnbzlw'), ephemeral=eph)
        self.assertEqual(push.b64u(body), (
            'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocIn'
            'mYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQe'
            'xSgSxsj_Qulcy4a-fN'))

    def test_phone_can_decrypt_what_we_send(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        phone = ec.generate_private_key(ec.SECP256R1())
        public = push.b64u(phone.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        auth = push.b64u(os.urandom(16))
        text = json.dumps({'title': 'Ny opgave', 'body': 'Støvsug (15 kr.)'}, ensure_ascii=False)
        body = push.encrypt(text.encode('utf-8'), public, auth)
        self.assertEqual(push.decrypt(body, phone, auth).decode('utf-8'), text)
        with self.assertRaises(ValueError):
            push.encrypt(b'x' * 5000, public, auth)

    def test_vapid_header_is_a_valid_signed_token(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        v = push.Vapid()
        head = v.header('https://fcm.googleapis.com/fcm/send/abc', now=1_000_000)
        token = head.split('t=')[1].split(',')[0]
        h, c, sig = token.split('.')
        claims = json.loads(push.unb64u(c))
        self.assertEqual((claims['aud'], claims['exp']), ('https://fcm.googleapis.com', 1_043_200))
        raw = push.unb64u(sig)
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64u(v.public))
        pub.verify(der, (h + '.' + c).encode(), ec.ECDSA(hashes.SHA256()))   # kaster ved fejl

    def test_vapid_key_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'vapid.pem')
            self.assertEqual(push.Vapid(path).public, push.Vapid(path).public)
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), '0o600')

    def test_subscriptions_are_validated_limited_and_cleaned_up(self):
        store = Store(None, Clock(monday()))
        kid = store.add_kid('Emma', 9)
        good = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'A' * 87, 'auth': 'B' * 22}}
        store.add_push(kid['token'], good)
        store.add_push(kid['token'], good)                       # samme telefon to gange
        self.assertEqual(store.admin_state()['kids'][0]['push'], 1)
        for bad in ({}, {'endpoint': 'http://usikker/x', 'keys': good['keys']},
                    {'endpoint': good['endpoint'], 'keys': {'p256dh': '!', 'auth': 'x'}}):
            with self.assertRaises(Problem):
                store.add_push(kid['token'], bad)
        with self.assertRaises(Problem):
            store.add_push('forkert-token', good)
        for n in range(5):
            store.add_push(kid['token'], dict(good, endpoint='https://push.example/%d' % n))
        self.assertEqual(len(kid['push']), 3)
        store.remove_push(kid['id'], 'https://push.example/4')
        self.assertEqual(len(kid['push']), 2)

    def test_dead_subscription_is_removed_after_410(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        seen = []

        class Gone(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                seen.append((self.headers['Content-Encoding'], self.headers['Authorization'][:6]))
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(410)
                self.send_header('Content-Length', '0')
                self.end_headers()

        srv = HTTPServer(('127.0.0.1', 0), Gone)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        store = Store(None, Clock(monday()))
        kid = store.add_kid('Emma', 9)
        phone = ec.generate_private_key(ec.SECP256R1())
        pub = push.b64u(phone.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
        kid['push'] = [{'endpoint': 'http://127.0.0.1:%d/p' % srv.server_address[1],
                        'keys': {'p256dh': pub, 'auth': push.b64u(os.urandom(16))}}]
        pusher = push.Pusher(store, push.Vapid())
        self.assertEqual(pusher.send_kid(kid, 'Hej', 'Test'), 1)
        for _ in range(50):
            if not kid['push']:
                break
            threading.Event().wait(0.1)
        srv.shutdown()
        self.assertEqual(seen, [('aes128gcm', 'vapid ')])
        self.assertEqual(kid['push'], [])
        self.assertEqual(pusher.send_kid(kid, 'Hej', 'Test'), 0)


class StubHA:
    """Samler det, appen ville sende til Home Assistant."""
    enabled = True
    notify_service = 'mobile_app_far'

    def __init__(self):
        self.value = '0'
        self.sent = []

    def states(self, ids):
        return {i: self.value for i in ids}

    def notify_to(self, service, title, message, open_app=False):
        self.sent.append((service, title, message))

    def notify_kid(self, kid, title, message):
        if kid.get('notify') or kid.get('ntfy_on'):
            self.sent.append((kid.get('notify') or 'ntfy:' + kid['ntfy'], title, message))

    def notify(self, title, message):
        self.sent.append((self.notify_service, title, message))

    def celebrate(self, entity):
        self.sent.append(('light', entity))


class AutomationTests(unittest.TestCase):
    def test_finished_washer_creates_job_and_tells_children(self):
        clock = Clock(monday())
        store = Store(None, clock)
        store.add_kid('Emil', 8)
        kid = store.add_kid('Maja', 12)
        store.update_kid(kid['id'], notify='mobile_app_maja', ntfy_on=True)
        store.add_rule('Vaskemaskine', 'sensor.vask_effekt', 'Flyt tøj til tørretumbleren', 5)
        ha = StubHA()
        auto = Automation(store, ha, clock)
        ha.value = '1500'
        auto.tick()
        self.assertEqual(store.data['tasks'], [])
        ha.value = '0.5'
        for _ in range(10):
            clock.advance(minutes=1)
            auto.tick()
        self.assertEqual(len(store.data['tasks']), 1)
        self.assertEqual([m[0] for m in ha.sent], ['mobile_app_maja'])
        self.assertIn('Flyt tøj til tørretumbleren', ha.sent[0][2])

    def test_reminders_and_birthday_go_to_the_right_people(self):
        clock = Clock(monday())
        store = Store(None, clock)
        kid = store.add_kid('Maja', birthday='2014-11-17')
        store.update_kid(kid['id'], notify='mobile_app_maja')
        store.add_task('Dæk bord', 3)
        store.set_setting('reminder_time', '17:00')
        ha = StubHA()
        auto = Automation(store, ha, clock)
        auto.tick()
        self.assertEqual(ha.sent, [])
        clock.advance(hours=10)
        auto.tick()
        auto.tick()
        self.assertEqual([(m[0], m[1]) for m in ha.sent],
                         [('mobile_app_maja', 'Husk dine pligter'),
                          ('mobile_app_far', 'Fødselsdag i morgen')])


class NtfyTests(unittest.TestCase):
    def test_message_goes_to_ntfy_with_topic_and_link(self):
        got = []

        class Catch(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                got.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

        srv = HTTPServer(('127.0.0.1', 0), Catch)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        ha = HomeAssistant(ntfy_server='http://127.0.0.1:%d' % srv.server_address[1],
                           public_url='http://hjem:8099')
        kid = {'token': 'abcdefgh', 'ntfy': 'pligt-hemmeligt1234', 'ntfy_on': True, 'notify': ''}
        self.assertTrue(ha.notify_kid(kid, 'Ny opgave', 'Støvsug (15 kr.)'))
        for _ in range(50):
            if got:
                break
            threading.Event().wait(0.1)
        srv.shutdown()
        self.assertEqual(got[0]['topic'], 'pligt-hemmeligt1234')
        self.assertEqual(got[0]['message'], 'Støvsug (15 kr.)')
        self.assertEqual(got[0]['click'], 'http://hjem:8099/k/abcdefgh/')
        self.assertFalse(ha.notify_kid(dict(kid, ntfy_on=False), 'x', 'y'))
        self.assertFalse(ha.ntfy('../../ond', 'x', 'y'))


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 9)

    def test_translation_keeps_names_and_numbers(self):
        import i18n
        self.assertEqual(i18n.translate('en', 'Emma ønsker sig: Cykel'), 'Emma wishes for: Cykel')
        self.assertEqual(i18n.translate('da', 'Emma ønsker sig: Cykel'), 'Emma ønsker sig: Cykel')
        self.assertEqual(i18n.translate('de', 'Du har tjent'), 'Du hast verdient')
        self.assertEqual(i18n.translate('xx', 'Du har tjent'), 'Du har tjent')   # ukendt sprog: dansk

    def test_words_inside_other_words_are_left_alone(self):
        import i18n
        self.assertEqual(i18n.translate('en', 'foråret'), 'foråret')
        self.assertEqual(i18n.translate('en', '=Ny'), '=Ny')
        self.assertEqual(i18n.translate('en', 'Ny bold'), 'Ny bold')            # kun hele teksten 'Ny'
        self.assertEqual(i18n.translate('en', 'Ny'), 'New')

    def test_every_translation_row_has_english_german_and_swedish(self):
        import i18n
        i18n._tables = None
        tables = i18n._load()
        for key in tables['en']:
            for lang in ('de', 'sv', 'nb'):
                self.assertIn(key, tables[lang], '%s mangler %s' % (key, lang))

    def test_kid_language_overrides_the_house_language(self):
        self.store.set_setting('lang', 'de')
        self.assertEqual(self.store.lang_of(), 'de')
        self.assertEqual(self.store.lang_of(self.emil), 'de')
        self.store.update_kid(self.emil['id'], lang='en')
        self.assertEqual(self.store.lang_of(self.emil), 'en')
        self.assertEqual(self.store.kid_view(self.emil['token'])['bars'][0]['label'], 'Mon')
        self.store.update_kid(self.emil['id'], lang='')
        self.assertEqual(self.store.lang_of(self.emil), 'de')
        self.store.set_setting('lang', 'klingon')
        self.assertEqual(self.store.lang_of(), 'da')

    def test_starter_pack_is_created_in_the_house_language(self):
        self.store.set_setting('lang', 'en')
        self.store.add_starter_pack()
        titles = [t['title'] for t in self.store.data['tasks']]
        self.assertIn('Set the table', titles)
        self.assertEqual(self.store.add_starter_pack(), 0)

    def test_notifications_are_translated_for_the_receiver(self):
        sent = []

        class Ha(HomeAssistant):
            def notify_to(self, service, title, message, open_app=False):
                sent.append((title, message))
                return True
        ha = Ha(notify_service='x')
        App(self.store, ha)
        self.store.set_setting('lang', 'en')
        self.store.update_kid(self.emil['id'], lang='de', notify='mobile_app_x')
        ha.notify('Pligt-pilot', 'Emil er færdig med: Dæk bord (5 kr.). Åbn Pligter for at godkende.')
        ha.notify_kid(self.store._kid(self.emil['id']), 'Husk dine pligter', 'Du har 2 opgaver i dag.')
        self.assertIn('has finished', sent[0][1])
        self.assertEqual(sent[1], ('Denk an deine Pflichten', 'Du hast 2 Aufgaben heute.'))


class TlsPushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import datetime
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        cls.dir = tempfile.mkdtemp()
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
                .sign(key, hashes.SHA256()))
        cls.cert, cls.key = os.path.join(cls.dir, 'c.pem'), os.path.join(cls.dir, 'k.pem')
        with open(cls.cert, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(cls.key, 'wb') as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        cls.port = s.getsockname()[1]
        s.close()
        cls.store = Store(None, Clock(monday()))
        cls.kid = cls.store.add_kid('Emma', 9)
        app = App(cls.store, HomeAssistant())
        app.vapid = push.Vapid()
        cls.vapid = app.vapid
        cls.srv, _ = serve(app, 'kid', cls.port, host='127.0.0.1', tls=make_tls(cls.cert, cls.key))
        cls.ctx = ssl._create_unverified_context()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        try:
            r = urllib.request.urlopen('https://127.0.0.1:%d%s' % (self.port, path), context=self.ctx)
            return r.status, r.headers.get('Content-Type'), r.read()
        except urllib.error.HTTPError as err:
            return err.code, None, b''

    def test_child_site_works_over_https_with_files_needed_for_push(self):
        base = '/k/%s/' % self.kid['token']
        self.assertEqual(self.get(base)[0], 200)
        status, ctype, body = self.get(base + 'sw.js')
        self.assertEqual((status, ctype.split(';')[0]), (200, 'application/javascript'))
        self.assertIn(b'showNotification', body)
        manifest = json.loads(self.get(base + 'manifest.json')[2])
        self.assertEqual((manifest['display'], manifest['short_name']), ('standalone', 'Emma'))
        status, ctype, icon = self.get(base + 'icon.png')
        self.assertEqual((status, ctype, icon[:4]), (200, 'image/png', b'\x89PNG'))
        self.assertEqual(json.loads(self.get(base + 'api/push_key')[2])['key'], self.vapid.public)
        for path in ('sw.js', 'manifest.json', 'icon.png', 'api/push_key'):
            self.assertEqual(self.get('/k/forkerttoken123/' + path)[0], 404)

    def test_phone_can_register_for_push_but_not_with_rubbish(self):
        url = 'https://127.0.0.1:%d/k/%s/api/push' % (self.port, self.kid['token'])

        def post(sub):
            req = urllib.request.Request(url, json.dumps({'subscription': sub}).encode(),
                                         {'Content-Type': 'application/json'})
            try:
                return urllib.request.urlopen(req, context=self.ctx).status
            except urllib.error.HTTPError as err:
                return err.code
        good = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'A' * 87, 'auth': 'B' * 22}}
        self.assertEqual(post(good), 200)
        self.assertEqual(len(self.kid['push']), 1)
        self.assertEqual(post({'endpoint': 'http://x', 'keys': {}}), 400)


class LocalIpTests(unittest.TestCase):
    def test_finds_the_address_of_the_primary_network_card(self):
        ha = HomeAssistant('http://supervisor/core/api', 'tok')
        ha._get = lambda url: json.dumps({'data': {'interfaces': [
            {'interface': 'hassio', 'primary': False, 'ipv4': {'address': ['172.30.32.1/23']}},
            {'interface': 'eth0', 'primary': True,
             'ipv4': {'address': ['169.254.3.3/16', '192.168.1.50/24']}}]}})
        self.assertEqual(ha.local_ip(), '192.168.1.50')

    def test_falls_back_to_the_internal_url_in_home_assistant_settings(self):
        ha = HomeAssistant('http://supervisor/core/api', 'tok')

        def get(url):
            if url.endswith('/network/info'):
                raise OSError('403')
            return json.dumps({'internal_url': 'http://192.168.1.77:8123'})
        ha._get = get
        self.assertEqual(ha.local_ip(), '192.168.1.77')
        ha2 = HomeAssistant('http://supervisor/core/api', 'tok')
        ha2._get = lambda url: json.dumps({'internal_url': 'https://abc.ui.nabu.casa'}) \
            if url.endswith('/config') else (_ for _ in ()).throw(OSError('403'))
        self.assertEqual(ha2.local_ip(), '')

    def test_no_address_when_supervisor_does_not_answer(self):
        ha = HomeAssistant('http://supervisor/core/api', 'tok')

        def boom(url):
            raise OSError('nej')
        ha._get = boom
        self.assertEqual(ha.local_ip(), '')
        self.assertEqual(HomeAssistant().local_ip(), '')


class FakeHA(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
        FakeHA.calls.append((self.path, self.headers.get('Authorization'), body))
        if self.path == '/template' and 'entity_id' in body:
            out = json.dumps([['sensor.vaskemaskine_effekt', 'Vaskemaskine effekt'],
                              ['switch.tumbler', 'Tørretumbler'], ['light.stue', 'Stue']]).encode()
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

    def test_parent_link_gives_the_parent_page_without_login(self):
        status, state = self.call(self.adm, '/api/parents', {'name': 'Mor'})
        self.assertEqual(status, 200)
        token = state['parents'][-1]['token']
        status, page = self.call(self.kid, '/p/%s/' % token)
        self.assertEqual(status, 200)
        self.assertIn('Pligter', page)
        status, state = self.call(self.kid, '/p/%s/api/state' % token)
        self.assertEqual(status, 200)
        self.assertTrue(state['via_link'])
        self.assertEqual(state['parent_name'], 'Mor')
        self.assertEqual(state['parents'], [])
        status, state = self.call(self.kid, '/p/%s/api/tasks' % token, {'title': 'Fej løv', 'price': 4})
        self.assertEqual(status, 200)
        self.assertEqual(state['parents'], [])
        self.assertTrue(any(t['title'] == 'Fej løv' for t in state['tasks']))

    def test_parent_page_can_be_installed_as_an_app(self):
        status, state = self.call(self.adm, '/api/parents', {'name': 'Mormor'})
        token = state['parents'][-1]['token']
        status, manifest = self.call(self.kid, '/p/%s/manifest.json' % token)
        self.assertEqual(status, 200)
        self.assertIn('Mormor', manifest)
        self.assertEqual(self.call(self.kid, '/p/%s/sw.js' % token)[0], 200)
        with urllib.request.urlopen(self.kid + '/p/%s/icon.png' % token) as resp:
            self.assertEqual(resp.headers.get_content_type(), 'image/png')

    def test_parent_link_cannot_manage_parents_or_download_backup(self):
        status, state = self.call(self.adm, '/api/parents', {'name': 'Far'})
        token = state['parents'][-1]['token']
        self.assertEqual(self.call(self.kid, '/p/%s/api/backup' % token)[0], 403)
        self.assertEqual(self.call(self.kid, '/p/%s/api/parents' % token, {'name': 'X'})[0], 403)
        self.assertEqual(self.call(self.adm, '/api/backup')[0], 200)

    def test_wrong_or_renewed_parent_link_gives_404(self):
        self.assertEqual(self.call(self.kid, '/p/abcdefghij1234567890/api/state')[0], 404)
        status, state = self.call(self.adm, '/api/parents', {'name': 'Bedstefar'})
        old = state['parents'][-1]
        status, state = self.call(self.adm, '/api/parents/%s/newlink' % old['id'], {})
        self.assertEqual(self.call(self.kid, '/p/%s/api/state' % old['token'])[0], 404)
        new = [p for p in state['parents'] if p['id'] == old['id']][0]
        self.assertEqual(self.call(self.kid, '/p/%s/api/state' % new['token'])[0], 200)

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
                                 'Hele huset', 'Forår', 'Sommer', 'Efterår', 'Vinter'})
        seasonal = [r for r in data['rows'] if r['season']]
        self.assertTrue(seasonal and not any(r['on'] for r in seasonal))
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
