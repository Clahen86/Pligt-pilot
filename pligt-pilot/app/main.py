"""Start Pligt-pilot.

I Home Assistant: indstillinger læses fra /data/options.json, data gemmes i /data.
Udvikling: sæt PP_DATA_DIR, PP_KID_PORT og PP_ADMIN_PORT.
"""
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ha import HomeAssistant  # noqa: E402
from house import Automation  # noqa: E402
from server import App, serve  # noqa: E402
from store import Store  # noqa: E402


def load_options():
    path = os.environ.get('PP_OPTIONS', '/data/options.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    options = load_options()
    data_dir = os.environ.get('PP_DATA_DIR', '/data')
    store = Store(os.path.join(data_dir, 'pligt.json'))
    if options.get('weekly_goal'):
        store.set_setting('goal', options['weekly_goal'])

    token = os.environ.get('SUPERVISOR_TOKEN', '')
    base = os.environ.get('PP_HA_URL') or ('http://supervisor/core/api' if token else '')
    ha = HomeAssistant(base, token or os.environ.get('PP_HA_TOKEN', ''),
                       options.get('notify_service', ''))
    app = App(store, ha, options)
    Automation(store, ha).run()

    kid_port = int(os.environ.get('PP_KID_PORT', '8099'))
    admin_port = int(os.environ.get('PP_ADMIN_PORT', '8100'))
    # I Home Assistant må kun Supervisorens ingress-adresse nå forældresiden.
    allow = os.environ.get('PP_ADMIN_ALLOW', '172.30.32.2' if token else '')
    allow_from = {a.strip() for a in allow.split(',') if a.strip()} or None

    serve(app, 'kid', kid_port)
    serve(app, 'admin', admin_port, allow_from)
    logging.info('Pligt-pilot kører. Børn: port %d, forældre: port %d', kid_port, admin_port)
    while True:
        time.sleep(3600)


if __name__ == '__main__':
    main()
