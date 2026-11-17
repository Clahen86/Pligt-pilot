"""Web-push til børnenes telefoner (VAPID + aes128gcm, RFC 8030/8291/8292).

Kræver pakken `cryptography`. Mangler den, er web-push bare slået fra.
"""
import base64
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger('pligt')

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

RECORD_SIZE = 4096


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def unb64u(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload, p256dh, auth, salt=None, ephemeral=None):
    """Krypterer en besked til en telefon (RFC 8291). Returnerer kroppen til push-tjenesten."""
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    ephemeral = ephemeral or ec.generate_private_key(ec.SECP256R1())
    as_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = ephemeral.exchange(ec.ECDH(), ua_key)
    ikm = _hkdf(auth_secret, shared, b'WebPush: info\x00' + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    record = payload + b'\x02'          # 0x02 = sidste (og eneste) blok
    if len(record) + 16 > RECORD_SIZE:
        raise ValueError('Beskeden er for lang')
    cipher = AESGCM(cek).encrypt(nonce, record, None)
    return salt + RECORD_SIZE.to_bytes(4, 'big') + bytes([len(as_public)]) + as_public + cipher


def decrypt(body, ua_private, auth):
    """Modtagersiden. Bruges kun i tests."""
    salt, as_public = body[:16], body[21:21 + body[20]]
    ua_public = ua_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), as_public))
    ikm = _hkdf(unb64u(auth), shared, b'WebPush: info\x00' + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + body[20]:], None)
    return plain.rstrip(b'\x00')[:-1]


class Vapid:
    """Serverens nøgle. Gemmes, så tilmeldingerne ikke mister gyldighed ved genstart."""

    def __init__(self, path=None):
        self.key = None
        if path and os.path.exists(path):
            with open(path, 'rb') as f:
                self.key = serialization.load_pem_private_key(f.read(), password=None)
        if self.key is None:
            self.key = ec.generate_private_key(ec.SECP256R1())
            if path:
                os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
                pem = self.key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption())
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'wb') as f:
                    f.write(pem)

    @property
    def public(self):
        return b64u(self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))

    def header(self, endpoint, subject='mailto:pligt-pilot@example.com', now=None):
        parts = urllib.parse.urlsplit(endpoint)
        claims = {'aud': '%s://%s' % (parts.scheme, parts.netloc),
                  'exp': int(now or time.time()) + 12 * 3600, 'sub': subject}
        head = b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
        body = b64u(json.dumps(claims, separators=(',', ':')).encode())
        signing = (head + '.' + body).encode('ascii')
        r, s = decode_dss_signature(self.key.sign(signing, ec.ECDSA(hashes.SHA256())))
        token = head + '.' + body + '.' + b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
        return 'vapid t=%s, k=%s' % (token, self.public)


class Pusher:
    def __init__(self, store, vapid):
        self.store = store
        self.vapid = vapid

    def send_kid(self, kid, title, message, url=None):
        """Sender til alle barnets tilmeldte enheder i baggrunden. Returnerer antal enheder."""
        subs = list(kid.get('push') or [])
        if not subs:
            return 0
        payload = json.dumps({'title': title, 'body': message, 'url': url or ''},
                             ensure_ascii=False).encode('utf-8')

        def work():
            for sub in subs:
                try:
                    self._post(sub, payload)
                except urllib.error.HTTPError as err:
                    if err.code in (404, 410):      # telefonen har afmeldt sig
                        self.store.remove_push(kid['id'], sub['endpoint'])
                    else:
                        log.warning('Push fejlede (%s)', err.code)
                except Exception as err:  # noqa: BLE001
                    log.warning('Push fejlede: %s', err)

        threading.Thread(target=work, daemon=True).start()
        return len(subs)

    def _post(self, sub, payload):
        body = encrypt(payload, sub['keys']['p256dh'], sub['keys']['auth'])
        req = urllib.request.Request(sub['endpoint'], data=body, method='POST', headers={
            'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream',
            'TTL': '86400', 'Urgency': 'high',
            'Authorization': self.vapid.header(sub['endpoint'])})
        urllib.request.urlopen(req, timeout=10).read()
