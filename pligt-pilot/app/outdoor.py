"""Opgaver ude: årstid, hyppighed og vejr ud fra opgavens titel (og rum).

Alle nøgleord står her, så de er lette at udvide. Et nøgleord passer, når et ord i titlen
begynder med det ('græs' passer også på 'græsset'). Slutter nøgleordet med mellemrum, skal
hele ordet passe ('is ' passer på 'is', men ikke på 'isabella').
"""
import datetime as dt
import re

MONTH_NAMES = ['januar', 'februar', 'marts', 'april', 'maj', 'juni', 'juli', 'august',
               'september', 'oktober', 'november', 'december']
EVERY = {7: 'én gang om ugen', 21: 'hver 3. uge'}

# Årstid og hyppighed. Den første regel, der passer, gælder.
# (navn, måneder, højst hver n. dag (0 = som opgaven selv), kun udendørs, nøgleord på da, en, de, sv og nb)
AUTO = [
    ('sne', (12, 1, 2, 3), 0, False,
     ['sne', 'isen', 'glat', 'strø salt', 'salt på', 'salte ',
      'snow', 'icy', 'grit', 'salt the',
      'schnee', 'glätte', 'streu', 'salz streu',
      'snö', 'sanda', 'salta ',
      'snø', 'strø ']),
    ('hæk', (5, 6, 7, 8, 9), 21, False,
     ['hæk', 'hedge', 'hecke', 'häck', 'hekk']),
    ('blade', (9, 10, 11), 7, False,
     ['løv', 'blade', 'leaves', 'leaf ', 'laub', 'blätter', 'löv']),
    ('havemøbler', (4, 5, 6, 7, 8, 9), 0, False,
     ['havemøbler', 'trampolin', 'garden furniture', 'patio furniture', 'trampoline',
      'gartenmöbel', 'trädgårdsmöbler', 'utemöbler', 'studsmatta', 'hagemøbler', 'utemøbler']),
    ('vanding', (5, 6, 7, 8, 9), 0, True,
     ['vand ', 'vande', 'vanding', 'water', 'gieß', 'giess', 'bewässer', 'vattna', 'vann ', 'vanne', 'vanning']),
    ('græs', (4, 5, 6, 7, 8, 9, 10), 7, False,
     ['græs', 'plæne', 'lawn', 'grass', 'mow', 'rasen', 'gras ', 'gräs', 'gress', 'plen ', 'plenen']),
]

# Udendørs: gives ikke ud i regn, storm og hagl. Rummet tæller med (fx "Have" eller "Ude").
OUTDOOR = [
    'græs', 'plæne', 'have ', 'haven', 'havearbejde', 'ude ', 'udenfor', 'udendørs', 'terrasse', 'bil ', 'bilen',
    'sne', 'hæk', 'løv', 'blade', 'fortov', 'indkørsel', 'carport', 'trampolin',
    'lawn', 'grass', 'garden', 'yard', 'outside', 'outdoor', 'patio', 'terrace', 'car ', 'snow', 'hedge',
    'leaves', 'driveway',
    'rasen', 'garten', 'draußen', 'draussen', 'auto ', 'schnee', 'hecke', 'laub', 'einfahrt',
    'gräs', 'trädgård', 'ute ', 'utomhus', 'altan', 'terrass', 'snö', 'häck', 'löv', 'uppfart',
    'gress', 'hage ', 'hagen', 'utendørs', 'snø', 'hekk', 'innkjørsel',
]

BAD_WEATHER = ('rainy', 'pouring', 'lightning', 'lightning-rainy', 'hail', 'windy', 'windy-variant', 'exceptional')
SNOWY = ('snowy', 'snowy-rainy')
UNKNOWN = ('', 'unavailable', 'unknown', 'none')
SNOW_HOURS = 24
FRESH = dt.timedelta(hours=1)        # ældre vejr end det regnes som ukendt


def _text(*parts):
    text = ' '.join(p or '' for p in parts).lower()
    return ' ' + re.sub(r'[^\w]+', ' ', text) + ' '


def _has(text, words):
    return any(' ' + w in text for w in words)


def is_outdoor(title, room=''):
    return _has(_text(title, room), OUTDOOR) or _has(_text(title), [w for r in AUTO if not r[3] for w in r[4]])


def is_snow(title, room=''):
    return _has(_text(title), AUTO[0][4])


def auto_rule(title, room=''):
    """Reglen for årstid og hyppighed ud fra titlen, eller None."""
    text = _text(title)
    for name, months, every, outdoor_only, words in AUTO:
        if _has(text, words) and (not outdoor_only or _has(_text(title, room), OUTDOOR)):
            return {'name': name, 'months': months, 'every': every}
    return None


def describe(rule):
    """'Automatisk: april–oktober, én gang om ugen' (på dansk; siden oversætter)."""
    if not rule:
        return None
    months = MONTH_NAMES[rule['months'][0] - 1] + '–' + MONTH_NAMES[rule['months'][-1] - 1]
    every = EVERY.get(rule['every'], '')
    return {'months': months, 'every': every,
            'text': 'Automatisk: ' + months + (', ' + every if every else '')}


def pick_weather(pairs):
    """Vælger husets vejr: weather.forecast_home, ellers en med 'home'/'hjem', ellers den første."""
    pairs = [(e, s) for e, s in (pairs or []) if str(e).startswith('weather.')]
    if not pairs:
        return None
    for e, s in pairs:
        if e == 'weather.forecast_home':
            return e, s
    pairs.sort(key=lambda p: (not any(w in p[0] for w in ('home', 'hjem')), p[0]))
    return pairs[0]


def blocks(weather, title, room, now):
    """Skal opgaven vente på grund af vejret? weather er det gemte vejr fra store."""
    weather = weather or {}
    if not weather.get('entity'):
        return False                         # intet vejr i huset: alt som før
    if is_snow(title, room):
        at = weather.get('snow_at')
        if not at or now - dt.datetime.fromisoformat(at) > dt.timedelta(hours=SNOW_HOURS):
            return True                      # sne-opgaver kun, når det har sneet det sidste døgn
    state = weather.get('state') or ''
    seen = weather.get('at')
    if seen and now - dt.datetime.fromisoformat(seen) > FRESH:
        state = ''                           # for gammelt: vi ved det ikke
    return state in BAD_WEATHER and is_outdoor(title, room)
