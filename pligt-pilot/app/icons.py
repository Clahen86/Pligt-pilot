"""Billeder til opgaverne. Vælges af forælderen, ellers gættes de ud fra opgavens navn."""

ICONS = ['🍴', '🍽️', '🍳', '🗑️', '🧹', '🧺', '🛏️', '🧸', '🐶', '🚿', '🪟', '🌱', '🌸', '🍂', '❄️', '📬',
         '👟', '🚗', '🤖', '🧼', '📚', '🧽', '🛒', '🪴', '⭐', '✅']

# (ikon, nøgleord på dansk, engelsk, tysk, svensk og norsk)
GUESS = [
    ('🤖', ['robot']),
    ('🍽️', ['opvask', 'dishwasher', 'geschirr', 'diskmaskin', 'oppvask']),
    ('🍴', ['dæk bord', 'dekk bord', 'set the table', 'tisch decken', 'duka bord', 'bordet', 'madpak', 'lunch']),
    ('🍳', ['aftensmad', 'dinner', 'abendessen', 'middag', 'madlavning', 'cook']),
    ('🗑️', ['skrald', 'bin', 'müll', 'mull', 'sopt', 'søppel', 'soppel', 'garbage', 'trash']),
    ('🧺', ['vasketøj', 'tøj', 'laundry', 'wäsche', 'wasche', 'tvätt', 'tvatt', 'tørretumbler', 'dryer',
            'trockner', 'torktumlare', 'tørketrommel', 'vaskemaskin', 'washing', 'waschmaschine', 'tvättmaskin',
            'clothes', 'kläder', 'klær']),
    ('🛏️', ['seng', 'bed', 'bett', 'säng', 'sang', 'bädda']),
    ('🧸', ['legetøj', 'toys', 'spielzeug', 'leksak', 'leker', 'lekene']),
    ('🐶', ['kæledyr', 'pets', 'haustier', 'husdjur', 'kjæledyr', 'hund', 'dog', 'kat ', 'cat', 'kanin', 'rabbit',
            'fodr', 'feed']),
    ('🚿', ['badeværelse', 'bathroom', 'badezimmer', 'badrum', 'bad ', 'toilet']),
    ('🪟', ['vindue', 'window', 'fenster', 'fönster', 'vindu']),
    ('🍂', ['løv', 'blade', 'leaves', 'laub', 'blätter', 'blatter', 'löv', 'tagrende', 'gutter', 'dachrinne']),
    ('❄️', ['sne', 'snow', 'schnee', 'snö', 'snø', 'skovl', 'måk']),
    ('🌱', ['græs', 'lawn', 'rasen', 'gräs', 'gress', 'plæne', 'have', 'garden', 'garten', 'trädgård', 'hage',
            'luge', 'weed', 'jäten']),
    ('🌸', ['blomst', 'flower', 'blumen', 'blommor']),
    ('📬', ['post', 'mail']),
    ('👟', ['sko', 'shoe', 'schuh', 'skor', 'jakke', 'jacket']),
    ('🚗', ['bil ', 'bilen', 'car ', 'auto', 'garage']),
    ('🧼', ['rens', 'clean the', 'putzen', 'städa', 'gør rent', 'gjør rent']),
    ('🧹', ['støvsug', 'vacuum', 'saugen', 'dammsug', 'fej', 'sweep', 'fegen', 'sopa', 'fei ', 'ryd', 'tidy',
            'aufräum', 'städa', 'rydd', 'staub', 'stue', 'living room', 'wohnzimmer', 'vardagsrum']),
]


def guess(title, room=''):
    text = ' %s %s ' % ((title or '').lower(), (room or '').lower())
    for icon, words in GUESS:
        if any(w in text for w in words):
            return icon
    return '⭐'


def valid(icon):
    return icon if icon in ICONS else ''
