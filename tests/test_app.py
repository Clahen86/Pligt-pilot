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
from house import power_sensors, Automation, find_sensors, step  # noqa: E402
from store import Problem, Store, look_for  # noqa: E402


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

    def test_machine_rule_can_be_edited_and_the_open_job_follows(self):
        rule = self.store.add_rule('Vaskemaskine', 'sensor.vask', 'Flyt tøj', 2)
        task = self.store.fire_rule(rule['id'])
        self.store.update_rule(rule['id'], title='Flyt tøj til tørretumbleren', price='4')
        self.assertEqual((task['title'], task['price']), ('Flyt tøj til tørretumbleren', 4))
        now = self.store.admin_state()['house_now']
        self.assertEqual([(n['status'], n['kid'], n['machine']) for n in now], [('free', '', 'Vaskemaskine')])
        self.store.claim(self.emil['token'], task['id'])
        self.store.update_rule(rule['id'], price=9)
        self.assertEqual(task['price'], 4)                      # taget: prisen står fast
        self.assertEqual(self.store.admin_state()['house_now'][0]['kid'], 'Emil')
        with self.assertRaises(Problem):
            self.store.update_rule(rule['id'], title='')

    def test_machine_link_for_a_child_from_the_chat(self):
        self.store.add_rule('Vaskemaskine', 'sensor.vask', 'Flyt tøj', 2)
        self.assertEqual(self.store.machine_link('emil hansen', 'washer'), 'k/%s/?machine=washer' % self.emil['token'])
        self.assertIsNone(self.store.machine_link('Far', 'washer'))         # en voksen: tager den i chatten
        self.assertIsNone(self.store.machine_link('Emil', 'dryer'))         # ingen regel for tørretumbleren
        task = self.store.fire_rule(self.store.data['rules'][0]['id'])
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'][0]['machine'], 'washer')
        self.assertTrue(task)

    def test_sick_today_removes_school_chores_only(self):
        lunch = self.store.add_task('Madpakke ud af tasken', 2)
        self.store.add_task('Dæk bord', 3)
        self.assertTrue(self.store.admin_state()['tasks'][0]['school'])            # gættet ud fra navnet
        view = self.store.kid_view(self.emil['token'])
        self.assertTrue(view['has_school'])
        self.store.ask_sick(self.emil['token'])
        self.assertTrue([k for k in self.store.admin_state()['kids'] if k['name'] == 'Emil'][0]['sick_ask'])
        self.store.decide_sick(self.emil['id'], True)
        self.assertEqual([i['title'] for i in self.kid_items(self.emil)], ['Dæk bord'])
        self.assertTrue(self.store.kid_view(self.emil['token'])['sick'])
        self.assertEqual(len(self.kid_items(self.maja)), 2)                        # søskende er ikke syge
        self.clock.advance(days=1)
        self.assertEqual(sorted(i['title'] for i in self.kid_items(self.emil)), ['Dæk bord', 'Madpakke ud af tasken'])
        self.assertFalse(self.store.kid_view(self.emil['token'])['sick'])
        self.store.update_task(lunch['id'], school=False)                          # forælderen bestemmer
        self.store.set_sick(self.emil['id'], True)
        self.assertEqual(len(self.kid_items(self.emil)), 2)
        self.store.ask_sick(self.maja['token'])
        self.store.decide_sick(self.maja['id'], False)
        self.assertFalse(self.store.kid_view(self.maja['token'])['sick_ask'])

    def test_kid_page_look_follows_age(self):
        self.assertEqual(self.store.kid_view(self.emil['token'])['look'], look_for(self.emil))
        self.store.update_kid(self.emil['id'], age=6)
        self.assertEqual(self.store.kid_view(self.emil['token'])['look'], 'small')
        self.store.update_kid(self.emil['id'], age=10)
        self.assertEqual(self.store.kid_view(self.emil['token'])['look'], 'mid')
        self.store.update_kid(self.emil['id'], age=15)
        self.assertEqual(self.store.kid_view(self.emil['token'])['look'], 'teen')
        self.store.update_kid(self.emil['id'], look='small')                      # forælderen bestemmer
        self.assertEqual(self.store.kid_view(self.emil['token'])['look'], 'small')
        self.store.update_kid(self.emil['id'], look='')
        self.assertEqual(self.store.kid_view(self.emil['token'])['look'], 'teen')

    def test_parent_moves_or_frees_a_taken_job(self):
        job = self.store.add_task('Fej indkørslen', 10, open_job=True)
        kid, item = self.store.claim(self.emil['token'], job['id'])
        now = [n for n in self.store.admin_state()['house_now'] if n['task_id'] == job['id']]
        self.assertEqual((now[0]['kid'], now[0]['item_id']), ('Emil', item['id']))
        self.store.move_item(item['id'], self.maja['id'])                       # Maja lavede den
        self.assertEqual(self.kid_items(self.maja)[-1]['title'], 'Fej indkørslen')
        self.store.free_item(item['id'])                                        # ingen har den
        self.assertEqual([j['title'] for j in self.store.kid_view(self.emil['token'])['jobs']], ['Fej indkørslen'])
        self.assertEqual([n for n in self.store.admin_state()['house_now'] if n['task_id'] == job['id']], [])
        kid, item = self.store.claim(self.emil['token'], job['id'])
        self.store.mark_done(self.emil['token'], item['id'])
        with self.assertRaises(Problem):
            self.store.free_item(item['id'])                                    # meldt færdig: brug Afvis
        self.assertEqual([i['title'] for i in self.store.decide_all(self.maja['id'])], [])  # kun Majas
        self.assertEqual([i['title'] for i in self.store.decide_all(self.emil['id'])], ['Fej indkørslen'])

    def test_task_released_at_a_time(self):
        task = self.store.add_task('Tøm opvasken', 3)
        self.store.update_task(task['id'], release='15:30', days=[0, 2])
        with self.assertRaises(Problem):
            self.store.update_task(task['id'], release='25:00')
        self.assertEqual(self.kid_items(self.emil), [])                     # kl. 8: ikke endnu
        self.assertEqual(self.store.due_releases(), [])
        self.clock.advance(hours=7, minutes=30)
        self.assertEqual([i['title'] for i in self.kid_items(self.emil)], ['Tøm opvasken'])
        self.assertEqual(sorted(k['name'] for k, t in self.store.due_releases()), ['Emil', 'Maja'])
        self.assertEqual(self.store.due_releases(), [])                     # kun én besked om dagen
        job = self.store.add_task('Fej indkørslen', 10, open_job=True)
        self.store.update_task(job['id'], release='18:00')
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'], [])
        self.clock.advance(hours=3)
        self.assertEqual([j['title'] for j in self.store.kid_view(self.emil['token'])['jobs']], ['Fej indkørslen'])
        self.clock.advance(days=1)                                          # tirsdag: ikke en valgt dag
        self.assertEqual(self.store.due_releases()[0][1]['title'], 'Fej indkørslen')

    def test_how_to_do_a_task(self):
        task = self.store.add_task('Skraldet ud', 5, 'Køkken', 'once', True)
        self.store.update_task(task['id'], how='- Tøm spanden\n2. Ny pose i\n\n* Bær den ud *')
        self.assertEqual(task['how'], 'Tøm spanden\nNy pose i\nBær den ud')
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'][0]['how'], 'Tøm spanden\nNy pose i\nBær den ud')
        self.store.add_rule('Opvaskemaskine', 'sensor.opvask', 'Tøm opvasken', 3)
        self.store.fire_rule(self.store.data['rules'][0]['id'])
        job = [j for j in self.store.kid_view(self.emil['token'])['jobs'] if j['machine'] == 'dishwasher'][0]
        self.assertTrue(job['how'].startswith('Tøm opvaskemaskinen'))       # fast tekst til maskiner
        with self.assertRaises(Problem):
            self.store.set_setting('ai_entity', 'light.stue')
        self.store.set_setting('ai_entity', 'ai_task.gemini')

        class AI:
            asked = []

            def describe(self, entity, title, room, young, old, language, done):
                self.asked.append((entity, title, room, young, old, language, done))
                return '1. Tøm spanden\n2. Ny pose i\n- 10 +: Vask spanden\nFærdig når: spanden er tom'
        ai = AI()
        text = self.store.write_how(ai, 'Skraldet ud', 'Køkken')
        self.assertEqual(text, 'Tøm spanden\nNy pose i\n10+: Vask spanden\nFærdig når: spanden er tom')
        ages = [k['age'] for k in self.store.data['kids']]
        self.assertEqual(ai.asked[0], ('ai_task.gemini', 'Skraldet ud', 'Køkken', min(ages), max(ages), 'Dansk', 'Færdig når:'))
        self.store.update_task(task['id'], how=text)
        self.assertNotIn('Vask spanden', self.store.kid_view(self.emil['token'])['jobs'][0]['how'])     # Emil er 8
        self.assertIn('\nVask spanden\n', self.store.kid_view(self.maja['token'])['jobs'][0]['how'])  # Maja er 12
        ai.describe = lambda *a: ''
        with self.assertRaises(Problem):
            self.store.write_how(ai, 'Skraldet ud')

    def test_child_suggests_a_chore_with_a_picture_and_gets_it(self):
        jpeg = b'\xff\xd8\xff' + b'0' * 50
        with self.assertRaises(Problem):
            self.store.suggest(self.emil['token'])                     # intet billede og ingen tekst
        kid, sug = self.store.suggest(self.emil['token'], '', jpeg)
        self.assertEqual(self.store.photo(sug['id']), jpeg)
        self.assertEqual(self.store.kid_view(self.emil['token'])['suggestions'][0]['photo'], True)
        state = self.store.admin_state()
        self.assertEqual([(x['name'], x['photo']) for x in state['suggestions']], [('Emil', True)])
        with self.assertRaises(Problem):
            self.store.decide_suggestion(sug['id'], True, '', 5)        # et forslag uden tekst skal have et navn
        kid, task = self.store.decide_suggestion(sug['id'], True, 'Skraldet ud', 5)
        self.assertEqual([(i['title'], i['price']) for i in self.kid_items(self.emil)], [('Skraldet ud', 5)])
        self.assertEqual(self.kid_items(self.maja), [])
        self.assertIsNone(self.store.photo(sug['id']))
        self.assertEqual(self.store.data['suggestions'], [])

    def test_one_off_goes_only_to_chosen_kids_and_is_not_a_task(self):
        with self.assertRaises(Problem):
            self.store.one_off('Bær brænde ind', 15, [])              # intet barn valgt
        with self.assertRaises(Problem):
            self.store.one_off('', 15, [self.emil['id']])             # ingen tekst
        task, kids = self.store.one_off('Bær brænde ind', 15, [self.maja['id']])
        self.assertEqual([k['name'] for k in kids], ['Maja'])
        self.assertEqual([(i['title'], i['price']) for i in self.kid_items(self.maja)], [('Bær brænde ind', 15)])
        self.assertEqual(self.kid_items(self.emil), [])
        self.assertEqual(task['auto_rule'], 'given')                  # ikke en almindelig opgave under Opgaver
        self.assertFalse(task['active'])
        self.assertNotIn(task['id'], [q['id'] for q in self.store.admin_state().get('quick_choices', [])])

    def test_suggestions_can_be_withdrawn_refused_and_are_limited(self):
        for n in range(3):
            self.store.suggest(self.emil['token'], 'Forslag %d' % n)
        with self.assertRaises(Problem):
            self.store.suggest(self.emil['token'], 'Et for meget')
        first, second = self.store.data['suggestions'][:2]
        with self.assertRaises(Problem):
            self.store.cancel_suggestion(self.maja['token'], first['id'])  # ikke hendes
        self.store.cancel_suggestion(self.emil['token'], first['id'])
        kid, task = self.store.decide_suggestion(second['id'], False)
        self.assertIsNone(task)
        self.assertEqual(len(self.store.data['suggestions']), 1)
        self.store.delete_kid(self.emil['id'])
        self.assertEqual(self.store.data['suggestions'], [])

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

    def test_other_languages_and_power_list(self):
        rows = [['sensor.waschmaschine_leistung', 'Waschmaschine', 'power', 'W', 'Keller'],
                ['sensor.trockner_leistung', 'Trockner', 'power', 'W', 'Keller'],
                ['sensor.spuelmaschine', 'Spülmaschine', 'power', 'W', 'Küche'],
                ['sensor.stue_temp', 'Temp', 'temperature', '°C', 'Stue']]
        found = {f['preset']: f['best']['entity'] for f in find_sensors(rows)}
        self.assertEqual(found['Vaskemaskine'], 'sensor.waschmaschine_leistung')
        self.assertEqual(found['Tørretumbler'], 'sensor.trockner_leistung')
        from house import power_sensors
        power = power_sensors(rows)
        self.assertEqual(len(power), 3)
        self.assertEqual(power[0]['area'], 'Keller')


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
    def test_door_list_puts_the_machines_room_first(self):
        from house import door_candidates
        ents = [
            ['sensor.vask_effekt', 'Vask effekt', 'power', 'W', 'Vaskerum'],
            ['binary_sensor.myggbett_1', 'Myggbett 1', 'door', '', 'Vaskerum'],
            ['binary_sensor.entre_dor', 'Entre dør', 'door', '', 'Entre'],
            ['binary_sensor.vaskerum_pir', 'Vaskerum bevægelse', 'motion', '', 'Vaskerum'],
            ['binary_sensor.myggbett_1_batteri', 'Myggbett 1 Batteri', 'battery', '', 'Vaskerum'],
        ]
        got = [d['entity'] for d in door_candidates(ents, 'sensor.vask_effekt')]
        self.assertEqual(got, ['binary_sensor.myggbett_1', 'binary_sensor.entre_dor', 'binary_sensor.vaskerum_pir'])

    def test_machine_rules_find_their_door_sensor_by_themselves(self):
        clock = Clock(monday())
        store = Store(None, clock)
        wash = store.add_rule('Vaskemaskine', 'sensor.vask_effekt', 'Flyt tøj', 5)
        dry = store.add_rule('Tørretumbler', 'sensor.tumbler_effekt', 'Fold tøj', 5)
        dish = store.add_rule('Opvaskemaskine', 'sensor.opvask_effekt', 'Tøm den', 5)
        ha = StubHA()
        ha.entities = lambda: [
            ['binary_sensor.vaskemaskine_lage_contact', 'Vaskemaskine låge Dør', 'door', '', ''],
            ['binary_sensor.myggbett_door_window_sensor_dor', 'Tørretumbler Låge Dør', 'door', '', ''],
            ['binary_sensor.vaskerum_torretumbler_lage_batteri', 'Tørretumbler Låge Batteri', 'battery', '', ''],
            ['binary_sensor.vaskemaskine_korer', 'Vaskemaskine Kører', 'running', '', ''],
            ['binary_sensor.opvask_dor_1', 'Opvask dør 1', 'door', '', ''],
            ['binary_sensor.opvask_dor_2', 'Opvask dør 2', 'door', '', ''],     # two fit: the parent picks
        ]
        Automation(store, ha, clock).tick()
        self.assertEqual(wash.get('door'), 'binary_sensor.vaskemaskine_lage_contact')
        self.assertEqual(dry.get('door'), 'binary_sensor.myggbett_door_window_sensor_dor')
        self.assertFalse(dish.get('door'))
        store.update_rule(wash['id'], door='')      # the parent removes it: it stays away
        clock.advance(minutes=20)
        Automation(store, ha, clock).tick()
        self.assertFalse(wash.get('door'))

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


class MapHA(StubHA):
    """Som StubHA, men hver enhed har sin egen værdi (mangler den, svarer HA ikke for den)."""

    def __init__(self):
        super().__init__()
        self.values = {}

    def states(self, ids):
        return {i: self.values[i] for i in ids if i in self.values}


class HouseCleanupTests(unittest.TestCase):
    """Tømt-maskine: en LEDIG husopgave forsvinder igen af sig selv."""

    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 8)
        self.events = []
        self.store.listener = self.events.append
        self.rule = self.store.add_rule('Vaskemaskine', 'sensor.vask_effekt', 'Flyt tøj', 5,
                                        door='binary_sensor.vask_dor')
        self.ha = MapHA()
        self.auto = Automation(self.store, self.ha, self.clock)

    def jobs(self):
        return [t for t in self.store.data['tasks'] if t.get('auto_rule') == self.rule['id']]

    def test_machine_type_follows_the_shared_agreement(self):
        from store import machine_type
        self.assertEqual([machine_type(n) for n in ('Opvaskemaskine', 'Tørretumbler', 'Vaskemaskine',
                                                     'Dishwasher', 'Wäschetrockner', 'Torktumlare',
                                                     'Tvättmaskin', 'Waschmaschine', 'Andet', '')],
                         ['dishwasher', 'dryer', 'washer', 'dishwasher', 'dryer', 'dryer', 'washer',
                          'washer', 'other', 'other'])

    def test_door_sensor_is_checked_and_can_be_changed(self):
        with self.assertRaises(Problem):
            self.store.add_rule('X', 'sensor.x', 'T', 1, door='sensor.ikke_en_dor')
        self.store.update_rule(self.rule['id'], door='')
        self.assertEqual(self.store._rule(self.rule['id'])['door'], '')
        self.store.update_rule(self.rule['id'], door='binary_sensor.ny_dor')
        self.assertEqual(self.store.admin_state()['rules'][0]['door'], 'binary_sensor.ny_dor')

    def test_opening_the_door_removes_the_open_job(self):
        self.ha.values = {'sensor.vask_effekt': '0', 'binary_sensor.vask_dor': 'off'}
        self.auto.tick()
        self.store.fire_rule(self.rule['id'])
        for bad in ('unavailable', 'unknown', 'on'):     # efter 'unavailable' tæller 'on' ikke
            self.ha.values['binary_sensor.vask_dor'] = bad
            self.auto.tick()
        self.assertEqual(len(self.jobs()), 1)
        del self.ha.values['binary_sensor.vask_dor']    # manglende tilstand: intet sker
        self.auto.tick()
        self.assertEqual(len(self.jobs()), 1)
        self.ha.values['binary_sensor.vask_dor'] = 'off'
        self.auto.tick()
        self.ha.values['binary_sensor.vask_dor'] = 'on'
        self.auto.tick()
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.events[-1], {'kind': 'removed', 'source': 'machine', 'machine': 'washer',
                                           'title': 'Flyt tøj', 'kid': '',
                                           'task_id': self.events[-1]['task_id']})

    def test_a_taken_job_stays_when_the_door_opens(self):
        self.ha.values = {'sensor.vask_effekt': '0', 'binary_sensor.vask_dor': 'off'}
        self.auto.tick()
        task = self.store.fire_rule(self.rule['id'])
        self.store.claim(self.emil['token'], task['id'])
        self.assertEqual(self.events[-1]['kind'], 'taken')
        self.assertEqual(self.events[-1]['kid'], 'Emil')
        self.ha.values['binary_sensor.vask_dor'] = 'on'
        self.auto.tick()
        self.ha.values['sensor.vask_effekt'] = '1500'
        self.auto.tick()
        self.assertEqual(len(self.jobs()), 1)
        item = self.store.kid_view(self.emil['token'])['items'][0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.assertEqual((self.events[-1]['kind'], self.events[-1]['source'], self.events[-1]['machine']),
                         ('done', 'machine', 'washer'))

    def test_machine_starting_again_removes_the_open_job(self):
        self.store.fire_rule(self.rule['id'])
        self.ha.values = {'sensor.vask_effekt': 'unavailable'}
        self.auto.tick()
        self.assertEqual(len(self.jobs()), 1)
        self.ha.values = {'sensor.vask_effekt': '1200'}
        self.auto.tick()
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.events[-1]['kind'], 'removed')

    def test_open_job_is_removed_after_the_set_number_of_hours(self):
        self.store.fire_rule(self.rule['id'])
        self.clock.advance(hours=3, minutes=59)
        self.store.housekeeping()
        self.assertEqual(len(self.jobs()), 1)
        self.clock.advance(minutes=2)
        self.store.housekeeping()
        self.assertEqual(self.jobs(), [])
        self.assertEqual([e['kind'] for e in self.events], ['removed'])
        self.store.set_setting('auto_task_hours', 1)
        task = self.store.fire_rule(self.rule['id'])
        self.store.claim(self.emil['token'], task['id'])     # taget: bliver liggende
        self.clock.advance(hours=5)
        self.store.housekeeping()
        self.assertEqual(len(self.jobs()), 1)
        with self.assertRaises(Problem):
            self.store.set_setting('auto_task_hours', 100)

    def test_hus_chat_removes_an_open_job_of_the_same_machine_type(self):
        self.store.fire_rule(self.rule['id'])
        self.assertIsNone(self.store.drop_open_job(machine='dryer'))
        self.assertIsNone(self.store.drop_open_job(machine='other'))
        self.assertIsNotNone(self.store.drop_open_job(machine='washer'))
        self.assertEqual(self.jobs(), [])
        self.assertIsNone(self.store.drop_open_job(machine='washer'))

    def test_a_failing_listener_never_stops_anything(self):
        def boom(_):
            raise RuntimeError('HA er væk')
        self.store.listener = boom
        task = self.store.fire_rule(self.rule['id'])
        self.store.claim(self.emil['token'], task['id'])
        self.assertEqual(len(self.store.kid_view(self.emil['token'])['items']), 1)


class AllowanceRuleTests(unittest.TestCase):
    """Store børn får kun lommepenge, hvis de har nok godkendte opgaver i ugen."""

    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 8)
        self.maja = self.store.add_kid('Maja', 13)
        self.store.add_task('Dæk bord', 3)
        self.store.set_setting('min_tasks_age', 13)
        self.store.set_setting('min_tasks_week', 2)
        for kid in (self.emil, self.maja):
            self.store.update_kid(kid['id'], allowance=20)

    def finish(self, kid):
        for i in self.store.kid_view(kid['token'])['items']:
            if i['status'] == 'todo':
                self.store.mark_done(kid['token'], i['id'])
                self.store.decide(i['id'], True)
                return

    def allowance(self, kid):
        return sum(e['amount'] for e in self.store.data['ledger']
                   if e['kid_id'] == kid['id'] and e['kind'] == 'allowance')

    def test_too_few_tasks_holds_the_allowance_back_and_tells_the_child(self):
        self.finish(self.maja)
        rule = self.store.kid_view(self.maja['token'])['allowance_rule']
        self.assertEqual((rule['need'], rule['done'], rule['amount'], rule['held']), (2, 1, 20, 0))
        self.assertIsNone(self.store.kid_view(self.emil['token'])['allowance_rule'])   # for ung
        self.clock.advance(days=7)
        self.store.housekeeping()
        self.assertEqual(self.allowance(self.emil), 20)
        self.assertEqual(self.allowance(self.maja), 0)
        self.assertEqual(self.store.kid_view(self.maja['token'])['allowance_rule']['held'], 20)
        notes = self.store.allowance_notices()
        self.assertEqual([(k['name'], t) for k, t in notes],
                         [('Maja', 'Lommepengene for uge 47 er holdt tilbage: 1 af 2 opgaver godkendt.')])
        self.assertEqual(self.store.allowance_notices(), [])      # kun én gang
        maja = [k for k in self.store.admin_state()['kids'] if k['name'] == 'Maja'][0]
        self.assertEqual(maja['allowance_rule']['held'], 20)
        self.assertEqual(self.store.admin_state()['settings']['min_tasks_week'], 2)

    def test_enough_tasks_pays_and_late_approvals_release_the_money(self):
        self.finish(self.maja)
        self.clock.advance(days=1)
        self.finish(self.maja)
        self.clock.advance(days=6)
        self.store.housekeeping()
        self.assertEqual(self.allowance(self.maja), 20)
        # ugen efter: én godkendt og én, der venter, da ugen skifter
        self.finish(self.maja)
        self.clock.advance(days=1)
        item = [i for i in self.store.kid_view(self.maja['token'])['items'] if i['status'] == 'todo'][0]
        self.store.mark_done(self.maja['token'], item['id'])
        self.clock.advance(days=6)
        self.store.housekeeping()
        self.assertEqual(self.allowance(self.maja), 20)
        self.store.decide(item['id'], True)                       # forælderen godkender om mandagen
        self.store.housekeeping()
        self.assertEqual(self.allowance(self.maja), 40)
        self.store.housekeeping()
        self.assertEqual(self.allowance(self.maja), 40)

    def test_zero_age_means_no_requirement(self):
        self.store.set_setting('min_tasks_age', 0)
        self.clock.advance(days=7)
        self.store.housekeeping()
        self.assertEqual(self.allowance(self.maja), 20)
        self.assertIsNone(self.store.kid_view(self.maja['token'])['allowance_rule'])

    def test_automation_tells_the_child(self):
        self.store.update_kid(self.maja['id'], notify='mobile_app_maja')
        ha = StubHA()
        auto = Automation(self.store, ha, self.clock)
        self.clock.advance(days=7)
        auto.tick()
        self.assertEqual([(m[0], m[1]) for m in ha.sent], [('mobile_app_maja', 'Lommepenge')])


class DutyTests(unittest.TestCase):
    """Pligter uden betaling: med frist og træk, hvis de ikke bliver lavet."""

    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 8)
        self.maja = self.store.add_kid('Maja', 12)
        self.events = []
        self.store.listener = self.events.append
        self.store._credit(self.emil['id'], 10, 'bonus', 'Start')
        self.store._credit(self.maja['id'], 2, 'bonus', 'Start')

    def test_duty_is_shown_with_deadline_and_fine_is_taken_if_not_done(self):
        duty = self.store.add_duty('Ryd dit værelse', [self.emil['id'], self.maja['id']], '2026-11-17', '18:00', 5)
        self.assertEqual((duty['price'], duty['duty']), (0, {'due': '2026-11-17T18:00', 'fine': 5}))
        item = self.store.kid_view(self.emil['token'])['items'][0]
        self.assertEqual(item['duty'], {'due': '2026-11-17T18:00', 'fine': 5})
        self.assertEqual(item['price'], 0)
        maja_item = self.store.kid_view(self.maja['token'])['items'][0]
        self.store.mark_done(self.maja['token'], maja_item['id'])
        self.assertEqual(self.events[-1], {'kind': 'done', 'source': 'duty', 'title': 'Ryd dit værelse',
                                           'kid': 'Maja', 'task_id': duty['id']})
        self.clock.advance(days=1, hours=9, minutes=59)
        self.assertEqual(self.store.balance(self.emil['id']), 10)
        self.clock.advance(minutes=2)
        self.assertEqual(self.store.kid_view(self.emil['token'])['items'], [])   # ikke lavet igen
        self.assertEqual(self.store.balance(self.emil['id']), 5)
        self.assertEqual(self.store.balance(self.maja['id']), 2)                 # Maja nåede det
        entry = self.store.data['ledger'][-1]
        self.assertEqual((entry['kind'], entry['amount'], entry['note']), ('penalty', -5, 'Ryd dit værelse'))
        self.assertEqual(self.store.admin_state()['duties'][0]['kids'],
                         [{'name': 'Emil', 'color': self.emil['color'], 'status': 'missed'},
                          {'name': 'Maja', 'color': self.maja['color'], 'status': 'wait'}])
        self.clock.advance(days=8)
        self.store.housekeeping()
        self.assertEqual(self.store.admin_state()['duties'], [])

    def test_fine_never_goes_below_zero_and_whole_day_without_time(self):
        duty = self.store.add_duty('Fej', [self.maja['id']], '2026-11-16', '', 10)
        self.assertEqual(duty['duty']['due'], '2026-11-16T23:59')
        self.clock.advance(hours=16)
        self.store.housekeeping()
        self.assertEqual(self.store.balance(self.maja['id']), 0)

    def test_bad_duties_are_refused(self):
        for kids, date, time in (([], '2026-11-17', ''), (['nope'], '2026-11-17', ''),
                                 ([self.emil['id']], 'i morgen', ''), ([self.emil['id']], '2026-11-17', '25:00'),
                                 ([self.emil['id']], '2026-11-16', '07:00')):
            with self.assertRaises(Problem):
                self.store.add_duty('Ryd op', kids, date, time, 5)


class MealTests(unittest.TestCase):
    """Maddage fra Madplan."""

    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.silas = self.store.add_kid('Silas', 12)
        self.events = []
        self.store.listener = self.events.append

    def meal(self, **kw):
        data = {'person': 'person.silas', 'kid': 'silas', 'date': '2026-11-17', 'meal': 'Lasagne',
                'time': '18:00', 'recipe': 'Brun kødet.\nLæg lag.', 'ingredients': ['Hakket oksekød', 'Pasta'],
                'url': 'https://example.com/lasagne'}
        data.update(kw)
        return self.store.add_meal(data)

    def test_meal_day_appears_on_the_day_with_recipe_and_is_updated_not_doubled(self):
        task = self.meal()
        self.assertEqual((task['title'], task['price']), ('Maddag: Lasagne', 0))
        self.assertEqual(self.store.kid_view(self.silas['token'])['items'], [])   # først i morgen
        self.assertNotIn(task['id'], [t['id'] for t in self.store.admin_state()['duties']])
        self.store.set_setting('meal_price', 10)
        self.meal(meal='Tacos', ingredients=['Tortillas'])
        tasks = [t for t in self.store.data['tasks'] if t.get('meal')]
        self.assertEqual([(t['title'], t['price']) for t in tasks], [('Maddag: Tacos', 10)])
        self.clock.advance(days=1)
        items = self.store.kid_view(self.silas['token'])['items']
        self.assertEqual([(i['title'], i['price']) for i in items], [('Maddag: Tacos', 10)])
        self.assertEqual(items[0]['meal']['ingredients'], ['Tortillas'])
        self.assertEqual(items[0]['meal']['time'], '18:00')
        self.assertEqual(items[0]['meal']['url'], 'https://example.com/lasagne')
        self.store.mark_done(self.silas['token'], items[0]['id'])
        self.assertEqual(self.events[-1], {'kind': 'done', 'source': 'meal', 'meal': 'Tacos',
                                           'title': 'Maddag: Tacos', 'kid': 'Silas', 'task_id': tasks[0]['id']})

    def test_unknown_child_or_bad_data_is_ignored(self):
        self.assertIsNone(self.meal(kid='Bo', person='person.bo'))
        self.assertIsNone(self.meal(date='i morgen'))
        self.assertIsNone(self.meal(meal=''))
        self.assertIsNotNone(self.meal(kid='', person='person.silas'))     # navnet fra personen
        task = self.meal(url='javascript:alert(1)', time='sen', ingredients='ikke en liste')
        self.assertEqual((task['meal']['url'], task['meal']['time'], task['meal']['ingredients']), ('', '', []))

    def test_cook_is_told_once_on_the_day(self):
        sent = []

        class Ha(HomeAssistant):
            def notify_kid(self, kid, title, message):
                sent.append((kid['name'], title, message))
                return True
        app = App(self.store, Ha())
        today = self.clock().date().isoformat()
        app.ha_event('madplan_cook', {'kid': 'Silas', 'date': '2099-01-01', 'meal': 'Suppe'})
        self.assertEqual(sent, [])                      # ikke i dag: ingen besked endnu
        app.ha_event('madplan_cook', {'kid': 'Silas', 'date': today, 'meal': 'Lasagne', 'time': '18:00'})
        app.ha_event('madplan_cook', {'kid': 'Silas', 'date': today, 'meal': 'Lasagne', 'time': '18:00'})
        self.assertEqual(sent, [('Silas', 'Maddag', 'Du laver mad i dag: Lasagne. Klar kl. 18:00. Tryk for at se opskriften.')])

    def test_cook_is_only_marked_told_when_the_message_went_out(self):
        sent, ok = [], [False]

        class Ha(HomeAssistant):
            def notify_kid(self, kid, title, message):
                sent.append(kid['name'])
                return ok[0]
        app = App(self.store, Ha())
        today = self.clock().date().isoformat()
        with self.assertLogs('pligt', 'INFO') as logs:
            self.assertTrue(app.ha_event('madplan_cook', {'kid': 'Silas', 'date': today, 'meal': 'Suppe'}))
        self.assertIn('Maddag til Silas: Suppe %s' % today, '\n'.join(logs.output))
        self.assertIn('ikke sendt', '\n'.join(logs.output))
        meal = [t for t in self.store.data['tasks'] if t.get('meal')][0]['meal']
        self.assertNotIn('told', meal)                                      # ingen besked kom ud
        ok[0] = True
        app.ha_event('madplan_cook', {'kid': 'Silas', 'date': today, 'meal': 'Suppe'})
        app.ha_event('madplan_cook', {'kid': 'Silas', 'date': today, 'meal': 'Suppe'})
        self.assertEqual(sent, ['Silas', 'Silas'])                          # prøvet igen, så kun én gang
        meal = [t for t in self.store.data['tasks'] if t.get('meal')][0]['meal']
        self.assertEqual(meal['told'], today)
        with self.assertLogs('pligt', 'WARNING') as logs:
            self.assertFalse(app.ha_event('madplan_cook', {'kid': 'Bo', 'date': today, 'meal': 'Suppe'}))
        self.assertIn('passer ikke', logs.output[0])

    def test_meal_day_is_not_left_hanging(self):
        self.meal(date='2026-11-16')
        self.assertEqual(len(self.store.kid_view(self.silas['token'])['items']), 1)
        self.clock.advance(days=1)
        self.assertEqual(self.store.kid_view(self.silas['token'])['items'], [])
        self.assertEqual(self.store.balance(self.silas['id']), 0)
        self.clock.advance(days=2)
        self.store.housekeeping()
        self.assertEqual([t for t in self.store.data['tasks'] if t.get('meal')], [])


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

    def test_quick_button_texts_in_five_languages(self):
        import i18n
        self.assertEqual(i18n.translate('en', '+ Tilføj'), '+ Add')
        self.assertEqual(i18n.translate('de', '+ Tilføj'), '+ Hinzufügen')
        self.assertEqual(i18n.translate('sv', 'Hurtigknapper'), 'Snabbknappar')
        self.assertEqual(i18n.translate('nb', 'Fjernet fra hurtigknapperne'), 'Fjernet fra hurtigknappene')
        self.assertEqual(i18n.translate('en', 'Færdig'), 'Done')
        self.assertEqual(i18n.translate('en', 'Tilføj barn'), 'Add child')        # længste nøgle vinder stadig

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


class QuickTests(unittest.TestCase):
    """Hurtigknapper: giv en opgave for i dag fra Oversigt."""

    def setUp(self):
        self.clock = Clock(monday())
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 8)
        self.maja = self.store.add_kid('Maja', 12)

    def view(self, kid):
        return self.store.kid_view(kid['token'])

    def quick(self):
        return [q['title'] for q in self.store.admin_state()['quick']]

    def test_pinned_first_then_most_used_then_task_order(self):
        letters = 'ABCDEFGHIJ'
        for title in letters:
            self.store.add_task(title, 3, open_job=True)
        self.store.add_duty('Pligt', [self.emil['id']], '2026-11-20')
        off = self.store.add_task('Slukket', 3, open_job=True)
        self.store.update_task(off['id'], active=False)
        self.assertEqual(self.quick(), list('ABCDEFGH'))                     # ingen historik: rækkefølgen, højst 8
        ids = {t['title']: t['id'] for t in self.store.data['tasks']}
        for _ in range(2):
            self.store.give_task(ids['I'], self.emil['id'])
        self.store.update_task(ids['J'], quick=True)
        self.assertEqual(self.quick(), ['J', 'I'] + list('ABCDEF'))
        self.clock.advance(days=31)                                          # brug ældre end 30 dage tæller ikke
        self.assertEqual(self.quick(), ['J'] + list('ABCDEFG'))
        q = self.store.admin_state()['quick'][0]
        self.assertEqual((q['price'], q['quick'], sorted(q['kids'])), (3, True, sorted([self.emil['id'], self.maja['id']])))
        self.assertTrue(q['icon_shown'])

    def test_pinned_always_first_and_at_most_eight_in_all(self):
        tasks = [self.store.add_task('Opgave %d' % n, 2) for n in range(10)]
        for t in tasks[::-1][:9]:                                            # 9 fastgjorte: de 8 første vises
            self.store.update_task(t['id'], quick=True)
        quick = self.store.admin_state()['quick']
        self.assertEqual(len(quick), 8)
        self.assertTrue(all(q['quick'] for q in quick))
        self.assertNotIn('Opgave 0', [q['title'] for q in quick])

    def test_choices_list_every_giveable_task_with_its_pin(self):
        normal = self.store.add_task('Dæk bord', 3)
        self.store.update_task(normal['id'], quick=True)
        self.store.add_duty('Pligt', [self.emil['id']], '2026-11-20')
        self.store.add_task('Ryd sne', 30, season='vinter', auto_season=False)   # ikke i sæson i november
        off = self.store.add_task('Når jeg giver den', 3)
        self.store.update_task(off['id'], active=False)                   # kun når forælderen giver den: med
        self.store.add_task('Tøm vaskemaskinen', 5, 'Fra huset', 'once', True, auto_rule='abcdef1234')   # husets
        choices = self.store.admin_state()['quick_choices']
        self.assertEqual([(c['title'], c['price'], c['quick']) for c in choices],
                         [('Dæk bord', 3, True), ('Når jeg giver den', 3, False)])
        self.assertTrue(choices[0]['icon_shown'])
        self.store.update_task(normal['id'], quick=False)
        self.assertFalse(self.store.admin_state()['quick_choices'][0]['quick'])

    def test_quick_buttons_from_data_saved_by_older_versions(self):
        """Gemt af en ældre version: opgaver uden auto_season/quick/each/icon/season, items uden given/from_task."""
        old = {'kids': [dict(self.emil)],
               'tasks': [{'id': 'aaaaaa0001', 'title': 'Dæk bord', 'room': 'Køkken', 'price': 3, 'repeat': 'daily',
                          'open': False, 'kids': [], 'age_min': 4, 'age_max': 99, 'times': 1, 'active': True},
                         {'id': 'aaaaaa0002', 'title': 'Tøm opvaskeren', 'room': '', 'price': 4, 'repeat': 'daily',
                          'open': False, 'kids': None, 'active': True, 'quick': None}],
               'items': [{'id': 'bbbbbb0001', 'task_id': 'aaaaaa0002', 'kid_id': self.emil['id'], 'title': 'Tøm opvaskeren',
                          'price': 4, 'period': '2026-11-15', 'status': 'done', 'created': None,
                          'done_at': '2026-11-15T18:00:00'}],
               'ledger': []}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'pligt.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(old, f)
            store = Store(path, self.clock)
            state = store.admin_state()
        self.assertEqual(sorted(q['title'] for q in state['quick']), ['Dæk bord', 'Tøm opvaskeren'])
        self.assertEqual(len(state['quick_choices']), 2)

    def test_give_to_one_child_is_for_today_only(self):
        self.store.set_setting('penalty', 0)
        task = self.store.add_task('Vask bilen', 20, repeat='weekly', open_job=True)
        task_, kids, item = self.store.give_task(task['id'], self.emil['id'])
        self.assertEqual([k['name'] for k in kids], ['Emil'])
        mine = self.view(self.emil)['items']
        self.assertEqual([(i['title'], i['price'], i['of']) for i in mine], [('Vask bilen', 20, 1)])
        self.assertEqual(self.view(self.maja)['items'], [])
        self.assertEqual(len(self.view(self.maja)['jobs']), 1)               # den ledige opgave er der stadig
        self.clock.advance(days=1)
        self.assertEqual(self.view(self.emil)['items'], [])                 # kun i dag
        self.assertEqual(self.store.data['items'][0]['status'], 'missed')

    def test_given_daily_task_comes_on_top_of_the_normal_one(self):
        task = self.store.add_task('Dæk bord', 3)
        self.store.give_task(task['id'], self.emil['id'])
        self.assertEqual(len(self.view(self.emil)['items']), 2)
        self.assertEqual(len(self.view(self.maja)['items']), 1)

    def test_give_respects_age_pause_and_chosen_children(self):
        big = self.store.add_task('Slå græs', 40, age_min=11, season='', auto_season=False)
        with self.assertRaises(Problem):
            self.store.give_task(big['id'], self.emil['id'])                 # for ung
        self.assertEqual(self.store.admin_state()['quick'][0]['kids'], [self.maja['id']])
        self.store.update_kid(self.maja['id'], paused=True)
        with self.assertRaises(Problem):
            self.store.give_task(big['id'], self.maja['id'])                 # på pause
        with self.assertRaises(Problem):
            self.store.give_task(big['id'], None)                            # ingen kan tage den
        only = self.store.add_task('Pas kaninen', 5, kids=[self.emil['id']])
        with self.assertRaises(Problem):
            self.store.give_task(only['id'], self.maja['id'])
        with self.assertRaises(Problem):
            self.store.give_task(only['id'], 'abcdef1234')                  # findes ikke

    def test_open_for_everyone_today_first_come_first_served(self):
        task = self.store.add_task('Støvsug stuen', 10, age_min=0)
        job, kids, item = self.store.give_task(task['id'], None)
        self.assertIsNone(item)
        self.assertEqual(sorted(k['name'] for k in kids), ['Emil', 'Maja'])
        jobs = self.view(self.maja)['jobs']
        self.assertEqual([(j['title'], j['price'], j['expires']) for j in jobs], [('Støvsug stuen', 10, '')])
        self.store.claim(self.emil['token'], jobs[0]['task_id'])
        self.assertEqual(self.view(self.maja)['jobs'], [])
        mine = [i for i in self.view(self.emil)['items'] if i['title'] == 'Støvsug stuen']
        self.assertEqual(len(mine), 2)                                       # den normale + den ledige
        self.assertEqual(self.store.admin_state()['quick'][0]['title'], 'Støvsug stuen')
        # en ledig opgave, ingen tog, forsvinder ved dagens slutning (ikke efter 4 timer)
        job2, _, _ = self.store.give_task(task['id'], None)
        self.clock.advance(hours=6)
        self.assertTrue(any(t['id'] == job2['id'] for t in self.store.admin_state()['tasks']))
        self.clock.advance(hours=11)
        self.assertFalse(any(t['id'] == job2['id'] for t in self.store.admin_state()['tasks']))

    def test_each_is_guessed_from_the_title_in_five_languages(self):
        from store import guess_each
        for title in ('Ryd dit værelse', 'Red din seng', 'Smør madpakke', 'Læg beskidt tøj til vask', 'Pak skoletaske',
                      'Lav lektier', 'Sæt sko og jakke på plads', 'Ryd din egen tallerken af', 'Børst tænder',
                      'Make your bed', 'Tidy your own room', 'Do homework', 'Pack your lunchbox',
                      'Mach dein Bett', 'Bädda sängen', 'Gjør leksene'):
            self.assertTrue(guess_each(title), title)
        for title in ('Dæk bord', 'Ryd af bordet', 'Tøm opvaskeren', 'Tøm skraldespanden', 'Fodr kæledyr',
                      'Støvsug stuen', 'Tidy the living room', 'Set the table', 'Tisch decken', 'Vask bilen', ''):
            self.assertFalse(guess_each(title), title)

    def test_each_follows_the_title_until_the_parent_chooses(self):
        task = self.store.add_task('Dæk bord', 3)                           # gammel opgave uden feltet
        self.assertNotIn('each', self.store.data['tasks'][0])
        view = lambda: [t for t in self.store.admin_state()['tasks'] if t['id'] == task['id']][0]
        self.assertEqual((view()['each'], view()['each_auto']), (False, True))
        self.store.update_task(task['id'], title='Red din seng')
        self.assertTrue(view()['each'])
        self.assertTrue(self.store.admin_state()['quick'][0]['each'])
        self.store.update_task(task['id'], each=False)                      # forælderen vælger selv
        self.store.update_task(task['id'], title='Red din seng igen')
        self.assertEqual((view()['each'], view()['each_auto']), (False, False))
        self.store.update_task(task['id'], each=True, title='Dæk bord')
        self.assertTrue(view()['each'])

    def test_give_to_each_child_as_their_own_task_for_today(self):
        self.store.set_setting('penalty', 0)
        ida = self.store.add_kid('Ida', 3)
        task = self.store.add_task('Red din seng', 4, repeat='weekly', age_min=5)
        task_, kids, items = self.store.give_task(task['id'], 'all')
        self.assertEqual([k['name'] for k in kids], ['Emil', 'Maja'])      # Ida er for ung
        self.assertEqual(len(items), 2)
        for kid in (self.emil, self.maja):
            mine = [i for i in self.view(kid)['items'] if i['title'] == 'Red din seng']
            self.assertEqual(len(mine), 2)                                   # den ugentlige + dagens egen
        self.assertEqual(self.view(ida)['items'], [])
        self.store.update_kid(self.maja['id'], paused=True)
        _, kids, _ = self.store.give_task(task['id'], 'all')
        self.assertEqual([k['name'] for k in kids], ['Emil'])
        self.store.update_kid(self.emil['id'], paused=True)
        with self.assertRaises(Problem):
            self.store.give_task(task['id'], 'all')                          # ingen kan få den
        self.clock.advance(days=1)
        self.assertFalse([i for i in self.view(self.emil)['items'] if i.get('given')])

    def test_cannot_give_duties_or_off_season_tasks(self):
        duty = self.store.add_duty('Ryd op', [self.emil['id']], '2026-11-20')
        with self.assertRaises(Problem):
            self.store.give_task(duty['id'], self.emil['id'])
        sne = self.store.add_task('Ryd sne', 30, season='vinter')            # november er ikke vinter
        with self.assertRaises(Problem):
            self.store.give_task(sne['id'], self.maja['id'])
        self.assertNotIn('Ryd sne', self.quick())


class OnDemandTests(unittest.TestCase):
    """Kun når jeg giver den (active False) og faste dage."""

    def setUp(self):
        self.clock = Clock(monday())                       # mandag 16. november
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 8)
        self.maja = self.store.add_kid('Maja', 12)

    def items(self, kid):
        return self.store.kid_view(kid['token'])['items']

    def test_on_demand_tasks_never_come_by_themselves_but_can_be_given(self):
        self.store.set_setting('penalty', 2)
        task = self.store.add_task('Tøm opvaskeren', 5, active=False)
        job = self.store.add_task('Vask bilen', 20, open_job=True)
        self.store.update_task(job['id'], active=False)
        self.assertEqual(self.items(self.emil), [])
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'], [])
        state = self.store.admin_state()
        self.assertEqual(sorted(q['title'] for q in state['quick']), ['Tøm opvaskeren', 'Vask bilen'])
        self.assertEqual(len(state['quick_choices']), 2)
        self.store.give_task(task['id'], self.emil['id'])
        self.assertEqual([i['title'] for i in self.items(self.emil)], ['Tøm opvaskeren'])   # bliver ikke "misset"
        self.store.give_task(task['id'], 'all')
        self.assertEqual(len(self.items(self.maja)), 1)
        given, _, _ = self.store.give_task(job['id'], None)                 # først til mølle
        self.assertEqual([j['title'] for j in self.store.kid_view(self.maja['token'])['jobs']], ['Vask bilen'])
        self.assertTrue(given['active'])
        self.store._credit(self.emil['id'], 10, 'bonus')
        self.clock.advance(days=1)
        self.assertEqual(self.items(self.emil), [])                         # kommer ikke igen af sig selv
        self.assertEqual(self.store.balance(self.emil['id']), 6)             # givet to gange og glemt: to træk

    def test_switching_to_on_demand_takes_todays_task_away_without_penalty(self):
        self.store.set_setting('penalty', 2)
        self.store._credit(self.emil['id'], 10, 'bonus')
        task = self.store.add_task('Dæk bord', 3)
        self.assertEqual(len(self.items(self.emil)), 1)
        self.store.update_task(task['id'], active=False)
        self.assertEqual(self.items(self.emil), [])
        self.assertEqual(self.store.balance(self.emil['id']), 10)

    def test_duties_meals_house_tasks_and_season_still_cannot_be_given(self):
        duty = self.store.add_duty('Ryd op', [self.emil['id']], '2026-11-20')
        self.store.update_task(duty['id'], active=False)
        house = self.store.add_task('Tøm vaskemaskinen', 5, 'Fra huset', 'once', True, auto_rule='abcdef1234')
        self.store.update_task(house['id'], active=False)
        sne = self.store.add_task('Ryd sne', 30, season='vinter', auto_season=False, active=False)
        self.store.add_meal({'kid': 'Emil', 'date': '2026-11-16', 'meal': 'Suppe'})
        meal = [t for t in self.store.data['tasks'] if t.get('meal')][0]
        meal['active'] = False
        for t in (duty, house, sne, meal):
            with self.assertRaises(Problem):
                self.store.give_task(t['id'], self.emil['id'])
        self.assertEqual(self.store.admin_state()['quick_choices'], [])

    def test_missed_advice_ignores_on_demand_tasks(self):
        task = self.store.add_task('Dæk bord', 3)
        for day in range(4):
            self.store.kid_view(self.emil['token'])
            self.clock.advance(days=1)
        self.store.kid_view(self.emil['token'])
        self.store.touch(self.emil['token'])
        self.store.touch(self.maja['token'])
        self.assertTrue(any('er misset' in a for a in self.store.advice()))
        self.store.update_task(task['id'], active=False)
        self.assertFalse(any('er misset' in a for a in self.store.advice()))

    def test_on_demand_and_days_are_saved_and_copied(self):
        task = self.store.add_task('Støvsug', 10, active=False, days=[6])
        self.assertEqual((task['active'], task['days']), (False, [6]))
        copy = self.store.duplicate_task(task['id'])
        copy['days'].append(0)
        self.assertEqual(task['days'], [6])                                  # kopien har sin egen liste

    def test_daily_task_only_on_chosen_days(self):
        self.store.set_setting('penalty', 2)
        self.store._credit(self.emil['id'], 20, 'bonus')
        task = self.store.add_task('Tøm skraldespanden', 4, days=[2, 6])    # onsdag og søndag
        seen = []
        for _ in range(7):
            seen.append(len(self.items(self.emil)))
            self.clock.advance(days=1)
        self.items(self.emil)
        self.assertEqual(seen, [0, 0, 1, 0, 0, 0, 1])
        self.assertEqual(self.store.balance(self.emil['id']), 16)            # to glemte dage, ikke syv
        missed = [i for i in self.store.data['items'] if i['task_id'] == task['id'] and i['status'] == 'missed']
        self.assertEqual(len(missed), 4)                                     # 2 dage x 2 børn

    def test_weekly_task_comes_on_the_first_chosen_day_and_stays_open(self):
        task = self.store.add_task('Ryd dit værelse', 10, repeat='weekly', days=[3, 5])   # torsdag og lørdag
        seen = []
        for _ in range(7):
            seen.append(len(self.items(self.emil)))
            self.clock.advance(days=1)
        self.assertEqual(seen, [0, 0, 0, 1, 1, 1, 1])
        self.assertEqual(len([i for i in self.store.data['items'] if i['task_id'] == task['id']
                              and i['kid_id'] == self.emil['id']]), 1)
        self.store.update_task(task['id'], days=[])                         # tom: som før, hele ugen
        self.assertEqual(len(self.items(self.emil)), 1)

    def test_open_job_only_on_chosen_days(self):
        self.store.add_task('Vask bilen', 20, open_job=True, days=[5])
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'], [])
        self.clock.advance(days=5)
        self.assertEqual(len(self.store.kid_view(self.emil['token'])['jobs']), 1)

    def test_days_are_checked(self):
        task = self.store.add_task('Dæk bord', 3)
        for bad in ([7], [-1], ['x'], 'abc'):
            with self.assertRaises(Problem):
                self.store.update_task(task['id'], days=bad)
        self.store.update_task(task['id'], days=['6', 2, 2])
        self.assertEqual(self.store.data['tasks'][0]['days'], [2, 6])
        self.assertEqual(self.store.admin_state()['day_names'][6], 'Søn')
        self.store.set_setting('lang', 'en')
        self.assertEqual(self.store.admin_state()['day_names'][0], 'Mon')

    def test_texts_in_five_languages(self):
        import i18n
        self.assertEqual(i18n.translate('en', 'Kun når jeg giver den'), 'Only when I give it')
        self.assertEqual(i18n.translate('de', 'Fast'), 'Fest')
        self.assertEqual(i18n.translate('sv', 'Hver uge · Søndag'), 'Varje vecka · Söndag')
        self.assertEqual(i18n.translate('nb', 'Når jeg giver den'), 'Når jeg gir den')
        self.assertEqual(i18n.translate('en', 'Fast og fint'), 'Fast og fint')   # kun hele teksten 'Fast'


class NameTests(unittest.TestCase):
    """Navne udefra (Madplan, Hus-chat)."""

    def setUp(self):
        self.store = Store(None, Clock(monday()))
        self.dennis = self.store.add_kid('Dennis opgaver', 12)
        self.lilly = self.store.add_kid('Lilly Opgaver', 9)

    def test_first_word_or_whole_name_case_does_not_matter(self):
        self.assertIs(self.store.kid_by_name('Dennis'), self.dennis)
        self.assertIs(self.store.kid_by_name('lilly'), self.lilly)
        self.assertIs(self.store.kid_by_name(' dennis  OPGAVER '), self.dennis)
        self.assertIsNone(self.store.kid_by_name('Opgaver'))
        self.assertIsNone(self.store.kid_by_name('Den'))
        self.assertIsNone(self.store.kid_by_name(''))

    def test_several_children_match_gives_nothing_but_exact_name_wins(self):
        other = self.store.add_kid('Dennis', 7)
        self.assertIs(self.store.kid_by_name('Dennis'), other)              # helt ens vinder
        self.store.add_kid('Lilly Mus', 5)
        self.assertIsNone(self.store.kid_by_name('Lilly'))                  # to passer: ingen

    def test_meal_finds_the_child_by_first_word_or_person(self):
        task = self.store.add_meal({'kid': 'Dennis', 'date': '2026-11-17', 'meal': 'Suppe'})
        self.assertEqual(task['meal']['kid_id'], self.dennis['id'])
        task = self.store.add_meal({'kid': '', 'person': 'person.lilly', 'date': '2026-11-17', 'meal': 'Pizza'})
        self.assertEqual(task['meal']['kid_id'], self.lilly['id'])
        self.store.add_kid('Lilly Mus', 5)
        self.assertIsNone(self.store.add_meal({'kid': 'lilly', 'date': '2026-11-18', 'meal': 'Pizza'}))


class AutoSeasonTests(unittest.TestCase):
    """Årstid og hyppighed ud fra titlen."""

    def setUp(self):
        self.clock = Clock(monday())                       # 16. november
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 14)

    def titles(self):
        return [i['title'] for i in self.store.kid_view(self.emil['token'])['items'] if i['status'] == 'todo']

    def test_keywords_in_five_languages(self):
        import outdoor
        name = lambda title, room='': (outdoor.auto_rule(title, room) or {}).get('name')
        self.assertEqual([name(t) for t in ('Slå græs', 'Mow the lawn', 'Rasen mähen', 'Klipp gräset', 'Klipp plenen')],
                         ['græs'] * 5)
        self.assertEqual([name(t) for t in ('Klip hækken', 'Trim the hedge', 'Hecke schneiden', 'Klipp häcken', 'Klipp hekken')],
                         ['hæk'] * 5)
        self.assertEqual([name(t) for t in ('Fej løv', 'Rake leaves', 'Laub rechen', 'Kratta löv', 'Rake løv')],
                         ['blade'] * 5)
        self.assertEqual([name(t) for t in ('Ryd sne', 'Shovel snow', 'Schnee schippen', 'Skotta snö', 'Måke snø')],
                         ['sne'] * 5)
        self.assertEqual(name('Stil havemøblerne frem'), 'havemøbler')
        self.assertEqual(name('Fej trampolinen'), 'havemøbler')
        self.assertEqual(name('Vand blomster', 'Have'), 'vanding')
        self.assertIsNone(name('Vand blomster', 'Stue'))                     # vanding indenfor: hele året
        self.assertIsNone(name('Fyld salt i opvaskemaskinen'))
        self.assertIsNone(name('Dæk bord'))
        self.assertFalse(outdoor.is_outdoor('Ryd op uden at larme'))
        self.assertFalse(outdoor.is_outdoor('Tag billeder'))
        self.assertTrue(outdoor.is_outdoor('Vask bilen'))
        self.assertTrue(outdoor.is_outdoor('Fej', 'Terrasse'))
        self.assertTrue(outdoor.is_snow('Strø salt på trappen'))

    def test_lawn_april_to_october_and_at_most_weekly(self):
        self.store.add_task('Slå græs', 40)                                   # dagligt, uden sæson
        self.assertEqual(self.titles(), [])                                   # november
        self.clock.when = dt.datetime(2027, 4, 5, 8, 0)                       # en mandag i april
        self.assertEqual(self.titles(), ['Slå græs'])
        item = self.store.kid_view(self.emil['token'])['items'][0]
        self.store.mark_done(self.emil['token'], item['id'])
        self.clock.advance(days=1)
        self.assertEqual(self.titles(), [])                                   # højst én gang om ugen
        self.clock.advance(days=6)
        self.assertEqual(self.titles(), ['Slå græs'])

    def test_hedge_at_most_every_third_week_and_no_penalty_off_season(self):
        self.store.set_setting('penalty', 5)
        self.store.add_task('Klip hæk', 30, repeat='weekly')
        self.clock.when = dt.datetime(2027, 5, 3, 8, 0)
        while (self.clock.when.toordinal() - 1) // 7 % 3:                     # start på en blok af 3 uger
            self.clock.advance(days=7)
        weeks = []
        for week in range(9):
            self.store.housekeeping()
            for i in self.store.data['items']:
                if i['status'] == 'todo':
                    i['status'] = 'done'
                    weeks.append(week)
            self.clock.advance(days=7)
        self.assertEqual(len(weeks), 3)                                       # 9 uger: 3 gange
        self.assertEqual([b - a for a, b in zip(weeks, weeks[1:])], [3, 3])   # hver 3. uge
        # ikke lavet, da sæsonen sluttede: intet træk
        self.store.data['items'].clear()
        self.clock.when = dt.datetime(2027, 9, 27, 8, 0)
        self.store.housekeeping()
        self.store._credit(self.emil['id'], 50, 'bonus')
        self.clock.when = dt.datetime(2027, 10, 18, 8, 0)
        self.store.housekeeping()
        self.assertEqual(self.store.balance(self.emil['id']), 50)

    def test_parents_own_choice_wins(self):
        task = self.store.add_task('Slå græs', 40, repeat='weekly')
        self.assertEqual(self.titles(), [])
        self.store.update_task(task['id'], season='')                         # "Hele året" valgt med vilje
        self.assertFalse(self.store.data['tasks'][0]['auto_season'])
        self.assertEqual(self.titles(), ['Slå græs'])
        self.store.update_task(task['id'], season='auto')
        self.assertEqual(self.titles(), [])                                   # tilbage til automatik
        own = self.store.add_task('Slå græs i drivhuset', 10, season='vinter')
        self.assertFalse(own['auto_season'])
        state = {t['title']: t for t in self.store.admin_state()['tasks']}
        self.assertEqual(state['Slå græs']['auto']['text'], 'Automatisk: april–oktober, én gang om ugen')
        self.assertTrue(state['Slå græs']['auto_season'])
        self.assertFalse(state['Slå græs i drivhuset']['auto_season'])
        import i18n
        self.assertEqual(i18n.translate('en', state['Slå græs']['auto']['text']),
                         'Automatic: April–October, once a week')
        hedge = self.store.add_task('Klip hæk', 30)
        self.assertEqual(self.store.admin_state()['tasks'][-1]['auto']['text'],
                         'Automatisk: maj–september, hver 3. uge')
        self.assertTrue(hedge['auto_season'])

    def test_existing_tasks_get_automatic_seasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'pligt.json')
            old = {'kids': [], 'tasks': [
                {'id': 'a1', 'title': 'Slå græs', 'season': 'sommer', 'room': 'Have', 'repeat': 'weekly'},
                {'id': 'a2', 'title': 'Slå græs bag skuret', 'season': 'forår', 'room': '', 'repeat': 'weekly'},
                {'id': 'a3', 'title': 'Fej blade', 'season': '', 'room': '', 'repeat': 'weekly'}]}
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(old, f)
            store = Store(path, self.clock)
            self.assertEqual([t['auto_season'] for t in store.data['tasks']], [True, False, True])

    def test_starter_pack_uses_automatic_seasons(self):
        self.store.add_starter_pack()
        lawn = next(t for t in self.store.data['tasks'] if t['title'] == 'Slå græs')
        self.assertTrue(lawn['auto_season'])
        self.clock.when = dt.datetime(2027, 4, 12, 8, 0)                      # april: ikke sommer, men græs
        self.assertIn('Slå græs', self.titles())


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(dt.datetime(2026, 12, 7, 8, 0))   # en mandag i december
        self.store = Store(None, self.clock)
        self.emil = self.store.add_kid('Emil', 14)

    def titles(self, store=None):
        store = store or self.store
        return sorted(i['title'] for i in store.kid_view(self.emil['token'])['items'] if i['status'] == 'todo')

    def test_rain_holds_outdoor_tasks_until_a_dry_day_without_penalty(self):
        self.store.set_setting('penalty', 5)
        self.store._credit(self.emil['id'], 50, 'bonus')
        self.store.set_weather('weather.forecast_home', 'rainy')
        self.store.add_task('Vask bilen', 20, repeat='weekly')
        self.store.add_task('Fej', 5, room='Terrasse', open_job=True)
        self.store.add_task('Dæk bord', 3)
        self.assertEqual(self.titles(), ['Dæk bord'])
        self.assertEqual(self.store.kid_view(self.emil['token'])['jobs'], [])
        for state in ('pouring', 'lightning-rainy', 'hail', 'windy', 'exceptional'):
            self.store.set_weather('weather.forecast_home', state)
            self.assertEqual(self.titles(), ['Dæk bord'], state)
        self.store.set_weather('weather.forecast_home', 'cloudy')
        self.assertEqual(self.titles(), ['Dæk bord', 'Vask bilen'])
        self.assertEqual(len(self.store.kid_view(self.emil['token'])['jobs']), 1)
        self.assertEqual(self.store.balance(self.emil['id']), 50)

    def test_snow_tasks_only_after_snow_and_it_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'pligt.json')
            store = Store(path, self.clock)
            self.emil = store.add_kid('Emil', 14)
            store.add_task('Ryd sne', 30)
            store.set_weather('weather.forecast_home', 'cloudy')
            self.assertEqual(self.titles(store), [])
            store.set_weather('weather.forecast_home', 'snowy')
            self.assertEqual(self.titles(store), ['Ryd sne'])
            self.clock.advance(hours=12)
            again = Store(path, self.clock)                                   # genstart
            again.set_weather('weather.forecast_home', 'sunny')
            self.assertEqual(self.titles(again), ['Ryd sne'])                 # sneen huskes
            self.assertTrue(again.data['settings']['weather']['snow_at'])
            self.clock.advance(hours=13)                                      # næste dag, over et døgn siden
            again.set_weather('weather.forecast_home', 'sunny')
            self.assertEqual(self.titles(again), [])                          # over et døgn: ingen ny

    def test_unreadable_weather_changes_nothing_except_snow(self):
        self.store.add_task('Vask bilen', 20)
        self.store.add_task('Ryd sne', 30)
        self.assertEqual(self.titles(), ['Ryd sne', 'Vask bilen'])           # intet vejr i huset: som før
        self.store.data['items'].clear()
        self.store.set_weather('weather.forecast_home', 'unavailable')
        self.assertEqual(self.titles(), ['Vask bilen'])
        self.store.set_weather('weather.forecast_home', 'rainy')
        self.store.data['items'].clear()
        self.clock.advance(hours=2)                                           # vejret er ikke læst i 2 timer
        self.assertEqual(self.titles(), ['Vask bilen'])

    def test_house_reads_the_weather_every_five_minutes(self):
        class WeatherHA(StubHA):
            answer = None
            asked = 0

            def weather(self):
                WeatherHA.asked += 1
                return WeatherHA.answer
        ha = WeatherHA()
        auto = Automation(self.store, ha, self.clock)
        WeatherHA.answer = [('weather.other', 'sunny'), ('weather.forecast_home', 'rainy')]
        auto.tick()
        self.assertEqual(self.store.admin_state()['weather'], {'entity': 'weather.forecast_home', 'state': 'rainy'})
        WeatherHA.answer = None                                               # HA svarer ikke: behold
        self.clock.advance(minutes=1)
        auto.tick()
        self.assertEqual(WeatherHA.asked, 1)
        self.clock.advance(minutes=5)
        auto.tick()
        self.assertEqual(self.store.admin_state()['weather']['state'], 'rainy')
        WeatherHA.answer = []                                                 # intet vejr i huset
        self.clock.advance(minutes=5)
        auto.tick()
        self.assertIsNone(self.store.admin_state()['weather'])

    def test_weather_is_read_from_home_assistant(self):
        ha = HomeAssistant('http://127.0.0.1:9', 'x')
        ha._post = lambda path, payload, timeout=8: json.dumps(
            [['weather.forecast_home', 'rainy'], ['sensor.x', '1'], 'rod'])
        self.assertEqual(ha.weather(), [('weather.forecast_home', 'rainy')])
        self.assertIsNone(HomeAssistant().weather())

        def broken(*a, **k):
            raise OSError('nede')
        ha._post = broken
        self.assertIsNone(ha.weather())



class FakeHA(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode()
        FakeHA.calls.append((self.path, self.headers.get('Authorization'), body))
        if self.path == '/template' and 'area_entities' in body:
            out = json.dumps({'Vaskerum': ['binary_sensor.myggbett_1', 'sensor.vask_effekt']}).encode()
        elif self.path == '/template' and 'entity_id' in body:
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


    def do_GET(self):
        if self.path == '/states':
            rows = [{'entity_id': 'sensor.vaskemaskine_effekt', 'state': '0', 'attributes': {'friendly_name': 'Vaskemaskine effekt'}},
                    {'entity_id': 'switch.tumbler', 'state': 'off', 'attributes': {'friendly_name': 'Tørretumbler'}},
                    {'entity_id': 'light.stue', 'state': 'off', 'attributes': {'friendly_name': 'Stue'}},
                    {'entity_id': 'sensor.vask_effekt', 'state': '0', 'attributes': {'friendly_name': 'Vask effekt', 'unit_of_measurement': 'W'}},
                    {'entity_id': 'binary_sensor.entre_dor', 'state': 'off', 'attributes': {'friendly_name': 'Entre dør', 'device_class': 'door'}},
                    {'entity_id': 'binary_sensor.myggbett_1', 'state': 'on', 'attributes': {'friendly_name': 'Myggbett 1', 'device_class': 'door'}}]
            out = json.dumps(rows).encode()
        else:
            out = b'{}'
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

    def test_entities_come_from_the_states_and_rooms_from_a_small_template(self):
        ents = HomeAssistant('http://127.0.0.1:%d' % self.fake.server_address[1], 'hemmelig').entities()
        self.assertIn(['binary_sensor.myggbett_1', 'Myggbett 1', 'door', '', 'Vaskerum'], ents)
        from house import door_candidates
        self.assertEqual([d['entity'] for d in door_candidates(ents, 'sensor.vask_effekt')],
                         ['binary_sensor.myggbett_1', 'binary_sensor.entre_dor'])

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

    def test_kid_page_can_be_installed_and_offers_a_button(self):
        status, state = self.call(self.adm, '/api/kids', {'name': 'Ida', 'age': 9})
        token = state['kids'][-1]['token']
        status, page = self.call(self.kid, '/k/%s/' % token)
        self.assertIn('beforeinstallprompt', page)
        self.assertNotIn('<!--install-->', page)
        status, manifest = self.call(self.kid, '/k/%s/manifest.json' % token)
        self.assertIn('512x512', manifest)
        with urllib.request.urlopen(self.kid + '/k/%s/icon-512.png' % token) as resp:
            self.assertEqual(resp.headers.get_content_type(), 'image/png')

    def test_redirect_to_the_slash_is_relative_so_it_works_behind_home_assistant(self):
        status, state = self.call(self.adm, '/api/kids', {'name': 'Bo', 'age': 7})
        token = state['kids'][-1]['token']

        class NoFollow(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        try:
            urllib.request.build_opener(NoFollow).open(self.kid + '/k/%s' % token)
            self.fail('expected a redirect')
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 301)
            self.assertEqual(err.headers['Location'], token + '/')

    def test_outside_address_from_home_assistant_is_used_for_links(self):
        self.assertEqual(self.app.outside_url(), 'http://hjem.local:8099')
        self.app.learn_outside('https://abc.ui.nabu.casa/pligter')
        self.assertEqual(self.call(self.adm, '/api/state')[1]['public_url'], 'https://abc.ui.nabu.casa/pligter')
        self.assertEqual(self.app.ha.public_url, 'https://abc.ui.nabu.casa/pligter')
        self.app.learn_outside('javascript:alert(1)')  # never taken
        self.assertEqual(self.app.outside_url(), 'https://abc.ui.nabu.casa/pligter')
        self.app.learn_outside('')  # Home Assistant has no outside address any more: back to public_url
        self.assertEqual(self.app.outside_url(), 'http://hjem.local:8099')

    def test_only_home_assistant_may_say_hello(self):
        self.assertEqual(self.call(self.kid, '/_ha/hello')[0], 404)

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

    def test_ha_events_only_from_home_assistant(self):
        import server
        body = {'event': 'madplan_cook', 'data': {'kid': 'Lina', 'date': '2026-11-16', 'meal': 'Suppe'}}
        status, state = self.call(self.adm, '/api/kids', {'name': 'Lina', 'age': 11})
        token = state['kids'][-1]['token']
        self.assertEqual(self.call(self.kid, '/_ha/event', body)[0], 404)
        self.assertEqual(self.call(self.adm, '/_ha/event', body)[0], 404)
        old = server.HA_CORE
        server.HA_CORE = '127.0.0.1'
        try:
            status, answer = self.call(self.kid, '/_ha/event', body)
            self.assertEqual((status, answer), (200, {'ok': True, 'done': True}))
            items = [i for i in self.call(self.kid, '/k/%s/api/state' % token)[1]['items'] if i.get('meal')]
            self.assertEqual([i['title'] for i in items], ['Maddag: Suppe'])
            self.assertEqual(self.call(self.kid, '/_ha/event', {'event': 'noget_andet', 'data': {}})[1]['done'], False)
            self.store.add_rule('Tørretumbler', 'sensor.tumbler_effekt', 'Fold tøjet', 8)
            self.store.fire_rule(self.store.data['rules'][-1]['id'])
            answer = self.call(self.kid, '/_ha/event', {'event': 'hus_chat_machine',
                                                        'data': {'kind': 'emptied', 'machine': 'dryer', 'name': 'Far'}})[1]
            self.assertTrue(answer['done'])
            self.assertFalse(any(t['title'] == 'Fold tøjet' for t in self.store.data['tasks']))
        finally:
            server.HA_CORE = old
        # og Pligt-pilot fortæller selv Home Assistant, når en opgave fjernes eller laves
        item = items[0]
        self.call(self.kid, '/k/%s/api/items/%s/done' % (token, item['id']), {})
        import time
        for _ in range(40):
            fired = [json.loads(c[2]) for c in FakeHA.calls if c[0] == '/events/pligt_pilot_task']
            if len(fired) >= 2:
                break
            time.sleep(0.05)
        self.assertEqual([(f['kind'], f['source']) for f in fired], [('removed', 'machine'), ('done', 'meal')])
        self.assertEqual(fired[0]['machine'], 'dryer')

    def test_house_duty_and_settings_through_http(self):
        status, state = self.call(self.adm, '/api/kids', {'name': 'Otto', 'age': 13})
        kid = state['kids'][-1]
        status, state = self.call(self.adm, '/api/duties', {'title': 'Tøm opvaskeren', 'kids': [kid['id']],
                                                            'date': '2026-11-20', 'time': '17:00', 'fine': 5})
        self.assertEqual(status, 200)
        self.assertEqual(state['duties'][-1]['title'], 'Tøm opvaskeren')
        items = self.call(self.kid, '/k/%s/api/state' % kid['token'])[1]['items']
        self.assertEqual([i['duty'] for i in items if i['title'] == 'Tøm opvaskeren'],
                         [{'due': '2026-11-20T17:00', 'fine': 5}])
        status, _ = self.call(self.adm, '/api/duties', {'title': 'X', 'kids': [], 'date': '2026-11-20'})
        self.assertEqual(status, 400)
        status, state = self.call(self.adm, '/api/settings', {'auto_task_hours': 6, 'min_tasks_age': 13,
                                                              'min_tasks_week': 4, 'meal_price': 5})
        self.assertEqual({k: state['settings'][k] for k in ('auto_task_hours', 'min_tasks_age',
                                                            'min_tasks_week', 'meal_price')},
                         {'auto_task_hours': 6, 'min_tasks_age': 13, 'min_tasks_week': 4, 'meal_price': 5})
        self.call(self.adm, '/api/settings', {'min_tasks_age': 0, 'meal_price': 0})
        status, state = self.call(self.adm, '/api/rules', {'name': 'Opvaskemaskine', 'entity': 'sensor.opvask',
                                                           'title': 'Tøm den', 'price': 5,
                                                           'door': 'binary_sensor.opvask_dor'})
        rule = state['rules'][-1]
        self.assertEqual(rule['door'], 'binary_sensor.opvask_dor')
        status, state = self.call(self.adm, '/api/rules/%s' % rule['id'], {'door': ''})
        self.assertEqual(state['rules'][-1]['door'], '')
        self.assertEqual(self.call(self.adm, '/api/rules/%s' % rule['id'], {'door': 'light.x'})[0], 400)

    def test_give_a_task_from_the_overview_and_from_a_parent_link(self):
        status, state = self.call(self.adm, '/api/kids', {'name': 'Ida', 'age': 9})
        ida = [k for k in state['kids'] if k['name'] == 'Ida'][0]
        status, state = self.call(self.adm, '/api/tasks', {'title': 'Tøm opvasker', 'price': 6, 'open': True})
        task = [t for t in state['tasks'] if t['title'] == 'Tøm opvasker'][0]
        self.assertTrue(any(q['id'] == task['id'] for q in state['quick']))
        status, state = self.call(self.adm, '/api/tasks/%s/give' % task['id'], {'kid_id': ida['id']})
        self.assertEqual(status, 200)
        status, view = self.call(self.kid, '/k/%s/api/state' % ida['token'])
        self.assertIn('Tøm opvasker', [i['title'] for i in view['items']])
        status, state = self.call(self.adm, '/api/parents', {'name': 'Moster'})
        token = state['parents'][-1]['token']
        status, state = self.call(self.kid, '/p/%s/api/tasks/%s/give' % (token, task['id']), {'kid_id': None})
        self.assertEqual(status, 200)
        self.assertEqual(state['parents'], [])
        self.assertTrue(any(t.get('given_from') == task['id'] for t in state['tasks']))
        status, state = self.call(self.kid, '/p/%s/api/tasks/%s/give' % (token, task['id']), {'kid_id': 'all'})
        self.assertEqual(status, 200)
        status, view = self.call(self.kid, '/k/%s/api/state' % ida['token'])
        self.assertEqual([i['title'] for i in view['items']].count('Tøm opvasker'), 2)
        status, state = self.call(self.adm, '/api/tasks/%s' % task['id'], {'each': True})
        mine = [t for t in state['tasks'] if t['id'] == task['id']][0]
        self.assertEqual((mine['each'], mine['each_auto']), (True, False))
        status, err = self.call(self.kid, '/p/%s/api/tasks/%s/give' % ('x' * 24, task['id']), {'kid_id': None})
        self.assertEqual(status, 404)
        status, err = self.call(self.adm, '/api/tasks/%s/give' % task['id'], {'kid_id': 'abcdef1234'})
        self.assertEqual(status, 404)
        status, state = self.call(self.adm, '/api/tasks/%s' % task['id'], {'quick': True})
        self.assertTrue([t for t in state['tasks'] if t['id'] == task['id']][0]['quick'])
        self.assertEqual(state['quick'][0]['id'], task['id'])
        mine = [c for c in state['quick_choices'] if c['id'] == task['id']][0]
        self.assertTrue(mine['quick'])
        status, state = self.call(self.adm, '/api/tasks/%s' % task['id'], {'quick': False})   # langt tryk / Tilføj-arket
        self.assertFalse([c for c in state['quick_choices'] if c['id'] == task['id']][0]['quick'])

    def test_on_demand_and_days_through_http(self):
        status, state = self.call(self.adm, '/api/tasks', {'title': 'Fej trappen', 'price': 5, 'active': False,
                                                           'days': [6], 'open': True})
        self.assertEqual(status, 200)
        task = [t for t in state['tasks'] if t['title'] == 'Fej trappen'][0]
        self.assertEqual((task['active'], task['days']), (False, [6]))
        self.assertIn(task['id'], [c['id'] for c in state['quick_choices']])
        self.assertEqual(len(state['day_names']), 7)
        status, state = self.call(self.adm, '/api/tasks/%s' % task['id'], {'active': True, 'days': [0, 3]})
        task = [t for t in state['tasks'] if t['id'] == task['id']][0]
        self.assertEqual((task['active'], task['days']), (True, [0, 3]))
        status, err = self.call(self.adm, '/api/tasks/%s' % task['id'], {'days': [9]})
        self.assertEqual(status, 400)

    def test_new_task_from_the_sheet_keeps_who_and_quick_button(self):
        # arket "Ny opgave" sender hver sin/én af børnene og hurtigknap med det samme
        status, state = self.call(self.adm, '/api/tasks', {'title': 'Red din seng', 'price': 2, 'active': True,
                                                           'days': [0, 2], 'each': False, 'quick': True})
        self.assertEqual(status, 200)
        task = [t for t in state['tasks'] if t['title'] == 'Red din seng'][0]
        self.assertEqual((task['each'], task['each_auto'], task['quick'], task['days']), (False, False, True, [0, 2]))
        # uden valg gætter appen stadig ud fra navnet
        status, state = self.call(self.adm, '/api/tasks', {'title': 'Dæk bordet', 'price': 3, 'active': False})
        task = [t for t in state['tasks'] if t['title'] == 'Dæk bordet'][0]
        self.assertTrue(task['each_auto'])
        self.assertFalse(task.get('quick', False))
        # også fra en forælders eget link
        status, state = self.call(self.adm, '/api/parents', {'name': 'Far'})
        token = state['parents'][-1]['token']
        status, state = self.call(self.kid, '/p/%s/api/tasks' % token, {'title': 'Fej gangen', 'price': 4, 'each': True})
        self.assertEqual(status, 200)
        task = [t for t in state['tasks'] if t['title'] == 'Fej gangen'][0]
        self.assertEqual((task['each'], task['each_auto']), (True, False))
        status, _ = self.call(self.adm, '/api/tasks', {'title': '', 'price': 4, 'each': True})
        self.assertEqual(status, 400)

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
