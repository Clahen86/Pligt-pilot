"""Forslag til opgaver ud fra husets rum.

Hvert rum har en liste af (titel, pris i kr., laveste alder, gentagelse).
Rum fra Home Assistant matches på ord i navnet. Uden Home Assistant vises
alle forslag.
"""

CATALOG = [
    {
        'room': 'Køkken',
        'words': ['køkken', 'kitchen', 'spisestue', 'madrum'],
        'tasks': [
            ('Tøm opvaskemaskinen', 5, 6, 'daily'),
            ('Dæk bord', 3, 5, 'daily'),
            ('Tør køkkenbordet af', 3, 7, 'daily'),
            ('Tag madpakker ud af tasken', 2, 6, 'daily'),
        ],
    },
    {
        'room': 'Bryggers',
        'words': ['bryggers', 'vaskerum', 'utility', 'laundry', 'vaskeri', 'teknikrum'],
        'tasks': [
            ('Hæng vasketøjet op', 8, 8, 'daily'),
            ('Fold vasketøj', 8, 9, 'weekly'),
            ('Læg rent tøj på plads', 5, 7, 'weekly'),
        ],
    },
    {
        'room': 'Badeværelse',
        'words': ['bad', 'toilet', 'bathroom', 'wc'],
        'tasks': [
            ('Ryd badeværelset', 6, 8, 'weekly'),
            ('Tør vask og spejl af', 8, 10, 'weekly'),
        ],
    },
    {
        'room': 'Stue',
        'words': ['stue', 'living', 'opholdsrum', 'alrum'],
        'tasks': [
            ('Ryd stuen', 5, 5, 'daily'),
            ('Støvsug stuen', 15, 11, 'weekly'),
            ('Tør støv af', 10, 9, 'weekly'),
        ],
    },
    {
        'room': 'Værelser',
        'words': ['soveværelse', 'værelse', 'bedroom', 'børneværelse', 'kids room'],
        'tasks': [
            ('Ryd dit værelse', 10, 5, 'weekly'),
            ('Red din seng', 2, 5, 'daily'),
            ('Skift sengetøj', 15, 11, 'weekly'),
        ],
    },
    {
        'room': 'Have',
        'words': ['have', 'garden', 'terrasse', 'udenfor', 'carport', 'garage', 'indkørsel'],
        'tasks': [
            ('Vand blomsterne', 4, 7, 'daily'),
            ('Fej terrassen', 15, 10, 'weekly'),
            ('Saml grene og blade op', 8, 8, 'weekly'),
        ],
    },
    {
        'room': 'Entré',
        'words': ['entré', 'entre', 'gang', 'hall', 'forgang'],
        'tasks': [
            ('Ryd skoene', 3, 5, 'daily'),
            ('Fej entréen', 8, 9, 'weekly'),
        ],
    },
]

WHOLE_HOUSE = {
    'room': 'Hele huset',
    'tasks': [
        ('Sæt skraldespanden ud', 10, 9, 'weekly'),
        ('Tag posten ind', 3, 7, 'daily'),
        ('Tøm skraldespandene', 8, 8, 'weekly'),
    ],
}


def _rows(group, found):
    return [{'room': group['room'], 'title': t, 'price': p, 'age_min': a,
             'repeat': r, 'found': found} for (t, p, a, r) in group['tasks']]


def suggest(areas, kid_ages, existing_titles):
    """Returnerer forslag. 'on' er sand, når mindst ét barn er gammelt nok."""
    names = [str(a).lower() for a in (areas or [])]
    oldest = max(kid_ages) if kid_ages else 99
    rows = []
    for group in CATALOG:
        found = any(w in n for w in group['words'] for n in names)
        if names and not found:
            continue
        rows += _rows(group, found)
    rows += _rows(WHOLE_HOUSE, False)
    taken = {t.strip().lower() for t in existing_titles}
    for r in rows:
        r['exists'] = r['title'].strip().lower() in taken
        r['on'] = (not r['exists']) and r['age_min'] <= oldest
    return rows
