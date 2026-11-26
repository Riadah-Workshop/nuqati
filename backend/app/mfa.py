"""Two-step sign-in (TOTP, RFC 6238) for dashboard accounts: the parts that need no web framework and no database.

What lives here: settings, the TOTP algorithm, encryption of the stored secret, recovery codes and the short-lived
tokens of the sign-in steps. The routes are in `features/mfa_accounts.py`; the storage is migration 0002.

Settings (all optional; with none of them set nothing changes for anyone):

    NUQATI_MFA_KEY             at least 32 characters. Turns two-step sign-in on: users may enrol. The TOTP secrets are
                               stored encrypted with a key derived from this value (AES-256-GCM), so a database backup
                               does not contain usable secrets. It is NOT the token-signing secret on purpose: an
                               emergency rotation of NUQATI_AUTH_SECRET must not lock every enrolled person out.
    NUQATI_MFA_KEY_PREVIOUS    old key, used only to read secrets while rotating; a secret read with it is
                               re-encrypted with the current key the next time its owner signs in.
    NUQATI_MFA_REQUIRED_ROLES  comma separated roles that must have it (for example "super_admin,company_admin").
                               A person in such a role who is not enrolled is taken to the setup screen after the
                               password and gets a session only when the setup is finished.
    NUQATI_MFA_ISSUER          name shown in the authenticator app (default "Nuqati").

A wrong combination (a role list without a key, a short key, an unknown role, "driver") stops the API at start-up,
like a malformed NUQATI_AUTH_SECRET_PREVIOUS does, so a typo is noticed at once.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from urllib.parse import quote

TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_WINDOW = 1  # accept the previous and the next 30-second step as well (clock drift of a phone)
SECRET_BYTES = 20  # 160 bits, the size RFC 4226 recommends
RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: codes are read from paper
RECOVERY_LENGTH = 12  # 60 bits
RECOVERY_ROUNDS = 20_000  # per-code salt; the codes are random, so a slow hash is only a second line of defence
CHALLENGE_MINUTES = 5
SETUP_MINUTES = 15
LOCK_AFTER_FAILURES = 5
FIRST_LOCK_SECONDS = 15 * 60
MAX_LOCK_SECONDS = 24 * 3600
DASHBOARD_ROLES = {"super_admin", "workshop_staff", "company_admin", "fleet_manager", "representative"}


class MfaKeyError(Exception):
    """A stored secret cannot be read with the configured key(s): the key is missing, wrong or was changed."""


# ------------------------------------------------------------------------------------------------ settings
def _clean(name: str) -> str:
    return os.environ.get(name, "").strip()


def enabled() -> bool:
    """Two-step sign-in is available (a key is configured)."""
    return bool(_clean("NUQATI_MFA_KEY"))


def issuer() -> str:
    return (_clean("NUQATI_MFA_ISSUER") or "Nuqati")[:60]


def required_roles() -> set[str]:
    return {role.strip() for role in _clean("NUQATI_MFA_REQUIRED_ROLES").split(",") if role.strip()}


def validate_settings() -> None:
    key, previous, roles = _clean("NUQATI_MFA_KEY"), _clean("NUQATI_MFA_KEY_PREVIOUS"), required_roles()
    if key and len(key) < 32:
        raise RuntimeError("NUQATI_MFA_KEY must be at least 32 characters when set")
    if previous and not key:
        raise RuntimeError("NUQATI_MFA_KEY_PREVIOUS is set but NUQATI_MFA_KEY is not")
    if previous and len(previous) < 32:
        raise RuntimeError("NUQATI_MFA_KEY_PREVIOUS must be at least 32 characters when set")
    unknown = sorted(roles - DASHBOARD_ROLES)
    if unknown:
        raise RuntimeError(f"NUQATI_MFA_REQUIRED_ROLES names roles that cannot use two-step sign-in: {', '.join(unknown)} "
                           f"(allowed: {', '.join(sorted(DASHBOARD_ROLES))})")
    if roles and not key:
        raise RuntimeError("NUQATI_MFA_REQUIRED_ROLES is set but NUQATI_MFA_KEY is not: the roles could never sign in")


def _keys() -> list[bytes]:
    keys = [_clean("NUQATI_MFA_KEY"), _clean("NUQATI_MFA_KEY_PREVIOUS")]
    return [value.encode() for value in keys if value]


def _derive(key: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"nuqati-mfa-secret-v1").derive(key)


# ------------------------------------------------------------------------------------------------ secrets at rest
def _associated(user_id: int) -> bytes:
    return f"nuqati-mfa|{int(user_id)}".encode()  # a stored value cannot be moved to another account's row


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def encrypt_secret(raw: bytes, user_id: int) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    keys = _keys()
    if not keys:
        raise MfaKeyError("NUQATI_MFA_KEY is not set")
    nonce = os.urandom(12)
    sealed = AESGCM(_derive(keys[0])).encrypt(nonce, raw, _associated(user_id))
    return "v1:" + base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt_secret(stored: str, user_id: int) -> tuple[bytes, bool]:
    """Returns (secret, needs_reencrypt). `needs_reencrypt` is true when only the previous key could read it."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    keys = _keys()
    if not keys:
        raise MfaKeyError("NUQATI_MFA_KEY is not set")
    try:
        version, _, payload = stored.partition(":")
        blob = base64.urlsafe_b64decode(payload.encode())
        if version != "v1" or len(blob) < 12 + 16:
            raise ValueError("unknown format")
    except (ValueError, TypeError) as exc:
        raise MfaKeyError("stored secret has an unknown format") from exc
    for index, key in enumerate(keys):
        try:
            return AESGCM(_derive(key)).decrypt(blob[:12], blob[12:], _associated(user_id)), index > 0
        except InvalidTag:
            continue
    raise MfaKeyError("stored secret cannot be read with the configured NUQATI_MFA_KEY")


# ------------------------------------------------------------------------------------------------ TOTP
def totp_code(secret: bytes, step: int) -> str:
    mac = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()  # RFC 6238 default; authenticator apps expect SHA-1
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // TOTP_PERIOD)


def normalize_code(value: str) -> str:
    return "".join(str(value or "").split()).replace("-", "").upper()


def looks_like_totp(value: str) -> bool:
    code = normalize_code(value)
    return len(code) == TOTP_DIGITS and code.isdigit()


def looks_like_recovery(value: str) -> bool:
    code = normalize_code(value)
    return len(code) == RECOVERY_LENGTH and all(ch in RECOVERY_ALPHABET for ch in code)


def verify_totp(secret: bytes, code: str, *, last_step: int | None = None, now: float | None = None) -> int | None:
    """The matching time step, or None. A step that is not newer than `last_step` is refused (a code works once)."""
    if not looks_like_totp(code):
        return None
    wanted = normalize_code(code)
    matched = None
    middle = current_step(now)
    for step in range(middle - TOTP_WINDOW, middle + TOTP_WINDOW + 1):  # always try all of them: constant work
        if hmac.compare_digest(totp_code(secret, step), wanted) and (last_step is None or step > last_step):
            matched = step if matched is None else max(matched, step)
    return matched


def secret_text(secret: bytes) -> str:
    """The key as an authenticator app wants it typed: Base32 without padding."""
    return base64.b32encode(secret).decode().rstrip("=")


def grouped(text: str) -> str:
    return " ".join(text[i:i + 4] for i in range(0, len(text), 4))


def otpauth_uri(secret: bytes, account: str) -> str:
    name = issuer()
    return (f"otpauth://totp/{quote(name, safe='')}:{quote(account, safe='@')}"
            f"?secret={secret_text(secret)}&issuer={quote(name, safe='')}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}")


# ------------------------------------------------------------------------------------------------ recovery codes
def new_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, RECOVERY_LENGTH, 4))


def hash_recovery_code(code: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = os.urandom(16) if salt is None else salt
    digest = hashlib.pbkdf2_hmac("sha256", normalize_code(code).encode(), salt, RECOVERY_ROUNDS)
    return salt.hex(), digest.hex()


def recovery_code_matches(code: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        _, digest = hash_recovery_code(code, bytes.fromhex(salt_hex))
    except ValueError:
        return False
    return hmac.compare_digest(digest, hash_hex)


# ------------------------------------------------------------------------------------------------ lock-out of guessing
def lock_seconds(failures: int) -> int:
    """0 until LOCK_AFTER_FAILURES wrong codes in a row, then 15 min, 30 min, 1 h ... at most 24 h (every 5th failure)."""
    if failures < LOCK_AFTER_FAILURES or failures % LOCK_AFTER_FAILURES:
        return 0
    return min(FIRST_LOCK_SECONDS * 2 ** (failures // LOCK_AFTER_FAILURES - 1), MAX_LOCK_SECONDS)


# ------------------------------------------------------------------------------------------------ step tokens
def _sign(claims: dict) -> str:
    from .auth import secret

    body = base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return body + "." + hmac.digest(secret(), body.encode(), "sha256").hex()  # same value as hmac.new(...).hexdigest()


def encode_step_token(user, kind: str) -> str:
    """kind 'mfa': the password was right, a code is still needed. kind 'mfa_setup': the role needs two-step sign-in
    and the account has none yet. Neither is an access token: `current_user` refuses any `typ` but 'access'."""
    minutes = CHALLENGE_MINUTES if kind == "mfa" else SETUP_MINUTES
    return _sign({"sub": user.id, "exp": int(time.time()) + minutes * 60, "ver": int(getattr(user, "auth_version", 0)), "typ": kind})


def _signature_ok(body: str, sig: str) -> bool:
    """Only the current secret: these tokens live 5 or 15 minutes, so during a planned rotation of NUQATI_AUTH_SECRET a
    person who is between password and code simply enters the password again (the access tokens keep their longer window)."""
    from .auth import secret

    return hmac.compare_digest(hmac.digest(secret(), body.encode(), "sha256").hex(), sig)


def decode_step_token(token: str, kinds: tuple[str, ...]) -> dict | None:
    """The claims when the signature, the expiry and the type are right, otherwise None."""
    try:
        body, sig = token.split(".")
        if not _signature_ok(body, sig):
            return None
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if claims["exp"] < time.time() or claims.get("typ") not in kinds:
            return None
        int(claims["sub"])
        return claims
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
