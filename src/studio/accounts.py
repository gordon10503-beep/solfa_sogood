"""Hosted sign-in and one-use invitations for private score libraries."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from http.cookies import SimpleCookie, CookieError

LIFETIME = 7 * 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def invite(library):
    token = secrets.token_urlsafe(32)
    with library.connect() as db:
        db.execute("DELETE FROM studio_invites WHERE expires < ?", (time.time(),))
        db.execute("INSERT INTO studio_invites VALUES (?,?)", (digest(token), time.time()+LIFETIME))
    return token


def authenticate(library, admin_password, payload, registering=False):
    name = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not re.fullmatch(r"[a-z0-9_.-]{3,40}", name) or not 1 <= len(password) <= 256:
        raise ValueError("Use a username of 3–40 letters, numbers, dots, underscores or hyphens.")
    if registering:
        if name == "studio" or len(password) < 10:
            raise ValueError("Choose a personal username and a password of at least 10 characters.")
        with library.connect() as db:
            if db.execute("DELETE FROM studio_invites WHERE hash=? AND expires>? RETURNING hash",
                          (digest(str(payload.get("invite",""))), time.time())).fetchone() is None:
                raise ValueError("This invitation has expired or was already used.")
            salt = secrets.token_hex(16)
            row = db.execute("INSERT INTO studio_users VALUES (?,?,?,?) ON CONFLICT(name) DO NOTHING RETURNING name",
                             (name, salt, password_hash(password,salt), secrets.token_hex(16))).fetchone()
            if row is None:
                raise ValueError("Choose another username.")
    if name == "studio" and hmac.compare_digest(password.encode(), admin_password.encode()):
        return name, "public"
    with library.connect() as db:
        row = db.execute("SELECT * FROM studio_users WHERE name=?", (name,)).fetchone()
    actual = password_hash(password, row["salt"] if row else "00"*16)
    if not row or not hmac.compare_digest(actual,row["hash"]):
        raise ValueError("Check your username and password.")
    return name, "member_" + row["space"]


def session_cookie(identity, key):
    payload = base64.urlsafe_b64encode(json.dumps([*identity,int(time.time())+LIFETIME]).encode()).decode()
    signature = hmac.new(key.encode(),payload.encode(),"sha256").hexdigest()
    return f"solfa_session={payload}.{signature}; Path=/; Max-Age={LIFETIME}; Secure; HttpOnly; SameSite=Lax"


def session_identity(header, key):
    cookie = SimpleCookie()
    try:
        cookie.load(header or "")
        payload, signature = cookie["solfa_session"].value.split(".")
        if not hmac.compare_digest(hmac.new(key.encode(),payload.encode(),"sha256").hexdigest(),signature):
            return None
        name, schema, expiry = json.loads(base64.urlsafe_b64decode(payload))
        if time.time() < expiry:
            return name, schema
    except (ValueError, KeyError, CookieError, TypeError):
        pass
    return None
