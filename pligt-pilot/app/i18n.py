"""Sprog. Dansk er grundsproget; de andre sprog ligger i lang/*.txt (dansk || en || de || sv || nb).

Oversættelsen sker ved at udskifte kendte danske tekststykker, så sætninger med navne og tal
(fx 'Emma ønsker sig: Ny bold') også bliver oversat. Samme algoritme findes i web/i18n.js.
"""
import glob
import os
import re

LANGS = ('da', 'en', 'de', 'sv', 'nb')
NAMES = {'da': 'Dansk', 'en': 'English', 'de': 'Deutsch', 'sv': 'Svenska', 'nb': 'Norsk'}
LOCALES = {'da': 'da-DK', 'en': 'en-GB', 'de': 'de-DE', 'sv': 'sv-SE', 'nb': 'nb-NO'}
DAYS = {
    'da': ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn'],
    'en': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    'de': ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'],
    'sv': ['Mån', 'Tis', 'Ons', 'Tors', 'Fre', 'Lör', 'Sön'],
    'nb': ['Man', 'Tir', 'Ons', 'Tor', 'Fre', 'Lør', 'Søn'],
}
WORD = 'A-Za-z0-9_ÆØÅæøå'
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lang')
_tables = None
_engines = {}


def _load():
    global _tables
    if _tables is not None:
        return _tables
    tables = {lang: {} for lang in LANGS if lang != 'da'}
    for path in sorted(glob.glob(os.path.join(_DIR, 'strings*.txt'))):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.rstrip('\n')
                if not line.strip() or line.startswith('#'):
                    continue
                parts = [p.strip() for p in line.split(' || ')]
                key = parts[0]
                for i, lang in enumerate(('en', 'de', 'sv', 'nb')):
                    value = parts[i + 1] if len(parts) > i + 1 else ''
                    if value:
                        tables[lang][key] = value
    _tables = tables
    return tables


def valid(lang):
    return lang if lang in LANGS else 'da'


def table(lang):
    """Ordbog til siderne (tom for dansk)."""
    return dict(_load().get(valid(lang), {}))


def _engine(lang):
    if lang not in _engines:
        tab = {k: v for k, v in _load()[lang].items() if not k.startswith('=')}
        keys = sorted(tab, key=len, reverse=True)
        parts = []
        for k in keys:
            piece = re.escape(k)
            if re.match('[%s]' % WORD, k[0]):
                piece = '(?<![%s])' % WORD + piece
            if re.match('[%s]' % WORD, k[-1]):
                piece += '(?![%s])' % WORD
            parts.append(piece)
        _engines[lang] = (re.compile('|'.join(parts)) if parts else None, tab)
    return _engines[lang]


def translate(lang, text):
    lang = valid(lang)
    if lang == 'da' or not text:
        return text
    exact = _load()[lang].get('=' + text.strip())
    if exact:
        return exact
    rx, tab = _engine(lang)
    if rx is None:
        return text
    return rx.sub(lambda m: tab[m.group(0)], text)
