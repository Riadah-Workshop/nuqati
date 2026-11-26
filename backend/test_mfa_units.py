"""DB-free unit tests of two-step sign-in (app/mfa.py): the TOTP algorithm against the RFC 6238 test vectors,
the encryption of stored secrets, recovery codes, the guessing lock, the settings checks and the step tokens.
The routes and the storage are tested on PostgreSQL in test_mfa_postgres.py."""
import base64
import json
import os
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault('NUQATI_AUTH_SECRET', 'test-mfa-units-secret-which-is-long-enough-0000')
from app import mfa  # noqa: E402

KEY_A = 'a' * 40  # fixtures only; low-entropy on purpose so secret scanners do not mistake them for real keys
KEY_B = 'b' * 40
RFC_SECRET = b'12345678901234567890'  # the SHA-1 test secret of RFC 6238 appendix B


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for name in ('NUQATI_MFA_KEY', 'NUQATI_MFA_KEY_PREVIOUS', 'NUQATI_MFA_REQUIRED_ROLES', 'NUQATI_MFA_ISSUER'):
        monkeypatch.delenv(name, raising=False)


# ----------------------------------------------------------------------------- TOTP
@pytest.mark.parametrize('moment,expected', [
    (59, '287082'), (1111111109, '081804'), (1111111111, '050471'), (1234567890, '005924'), (2000000000, '279037'),
    (20000000000, '353130'),
])
def test_totp_matches_the_rfc_6238_vectors(moment, expected):
    assert mfa.totp_code(RFC_SECRET, moment // 30) == expected  # the RFC lists 8 digits; these are their last 6


def test_a_code_is_accepted_one_step_early_and_late_but_not_two():
    now = 1_700_000_000
    step = mfa.current_step(now)
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step), now=now) == step
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step - 1), now=now) == step - 1
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step + 1), now=now) == step + 1
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step - 2), now=now) is None
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step + 2), now=now) is None


def test_a_code_works_only_once():
    now = 1_700_000_000
    step = mfa.current_step(now)
    code = mfa.totp_code(RFC_SECRET, step)
    assert mfa.verify_totp(RFC_SECRET, code, now=now, last_step=step - 1) == step
    assert mfa.verify_totp(RFC_SECRET, code, now=now, last_step=step) is None, "the same step again is a replay"
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step - 1), now=now, last_step=step) is None, "an older step too"
    assert mfa.verify_totp(RFC_SECRET, mfa.totp_code(RFC_SECRET, step + 1), now=now, last_step=step) == step + 1


def test_spaces_and_a_dash_in_a_code_are_ignored_and_other_shapes_are_refused():
    now = 1_700_000_000
    code = mfa.totp_code(RFC_SECRET, mfa.current_step(now))
    assert mfa.verify_totp(RFC_SECRET, f'{code[:3]} {code[3:]}', now=now) is not None
    for bad in ('', '12345', '1234567', 'abcdef', '12345a', code + '0'):
        assert mfa.verify_totp(RFC_SECRET, bad, now=now) is None, bad


def test_the_wrong_secret_does_not_verify():
    now = 1_700_000_000
    code = mfa.totp_code(RFC_SECRET, mfa.current_step(now))
    assert mfa.verify_totp(b'another-secret-20-bytes', code, now=now) is None


def test_new_secrets_are_random_and_20_bytes():
    first, second = mfa.new_secret(), mfa.new_secret()
    assert len(first) == len(second) == 20 and first != second


def test_the_typed_key_is_base32_without_padding_and_round_trips():
    raw = mfa.new_secret()
    text = mfa.secret_text(raw)
    assert text.isalnum() and text.upper() == text and '=' not in text and len(text) == 32
    assert base64.b32decode(text) == raw
    assert mfa.grouped(text).replace(' ', '') == text and mfa.grouped(text).count(' ') == 7


def test_the_otpauth_link_names_issuer_account_and_parameters(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_ISSUER', 'Nuqati Test')
    uri = mfa.otpauth_uri(RFC_SECRET, 'a.b+c@example.com')
    assert uri.startswith('otpauth://totp/Nuqati%20Test:a.b%2Bc@example.com?')
    assert f'secret={mfa.secret_text(RFC_SECRET)}' in uri and 'issuer=Nuqati%20Test' in uri
    assert 'algorithm=SHA1' in uri and 'digits=6' in uri and 'period=30' in uri


# ----------------------------------------------------------------------------- secrets at rest
def test_a_stored_secret_is_encrypted_and_round_trips(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_A)
    stored = mfa.encrypt_secret(RFC_SECRET, 7)
    assert stored.startswith('v1:') and base64.b32encode(RFC_SECRET).decode().rstrip('=') not in stored
    assert RFC_SECRET not in base64.urlsafe_b64decode(stored[3:].encode())
    assert mfa.decrypt_secret(stored, 7) == (RFC_SECRET, False)
    assert mfa.encrypt_secret(RFC_SECRET, 7) != stored, "a fresh nonce every time"


def test_a_stored_secret_cannot_be_moved_to_another_account(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_A)
    stored = mfa.encrypt_secret(RFC_SECRET, 7)
    with pytest.raises(mfa.MfaKeyError):
        mfa.decrypt_secret(stored, 8)


def test_a_damaged_or_foreign_value_is_refused_not_guessed(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_A)
    stored = mfa.encrypt_secret(RFC_SECRET, 7)
    blob = bytearray(base64.urlsafe_b64decode(stored[3:].encode()))
    blob[-1] ^= 1
    for bad in ('v1:' + base64.urlsafe_b64encode(bytes(blob)).decode(), 'v2:' + stored[3:], 'plain text', 'v1:', ''):
        with pytest.raises(mfa.MfaKeyError):
            mfa.decrypt_secret(bad, 7)


def test_rotation_reads_with_the_previous_key_and_asks_for_re_encryption(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_A)
    old = mfa.encrypt_secret(RFC_SECRET, 7)
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_B)
    with pytest.raises(mfa.MfaKeyError):
        mfa.decrypt_secret(old, 7)
    monkeypatch.setenv('NUQATI_MFA_KEY_PREVIOUS', KEY_A)
    assert mfa.decrypt_secret(old, 7) == (RFC_SECRET, True)
    fresh = mfa.encrypt_secret(RFC_SECRET, 7)
    monkeypatch.delenv('NUQATI_MFA_KEY_PREVIOUS')
    assert mfa.decrypt_secret(fresh, 7) == (RFC_SECRET, False), "encrypted with the new key only"


def test_without_a_key_nothing_is_encrypted_or_read():
    with pytest.raises(mfa.MfaKeyError):
        mfa.encrypt_secret(RFC_SECRET, 7)
    with pytest.raises(mfa.MfaKeyError):
        mfa.decrypt_secret('v1:' + base64.urlsafe_b64encode(os.urandom(40)).decode(), 7)


def test_the_token_signing_secret_is_not_the_mfa_key(monkeypatch):
    """An emergency rotation of NUQATI_AUTH_SECRET must not make stored secrets unreadable."""
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_A)
    stored = mfa.encrypt_secret(RFC_SECRET, 7)
    monkeypatch.setenv('NUQATI_AUTH_SECRET', 'a-completely-different-signing-secret-0123456789')
    assert mfa.decrypt_secret(stored, 7)[0] == RFC_SECRET


# ----------------------------------------------------------------------------- settings
def test_with_no_setting_the_feature_is_off_and_valid():
    assert mfa.enabled() is False and mfa.required_roles() == set() and mfa.issuer() == 'Nuqati'
    mfa.validate_settings()


def test_a_key_switches_it_on_and_roles_are_listed(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY_A)
    monkeypatch.setenv('NUQATI_MFA_REQUIRED_ROLES', ' super_admin , company_admin,, ')
    mfa.validate_settings()
    assert mfa.enabled() and mfa.required_roles() == {'super_admin', 'company_admin'}


@pytest.mark.parametrize('settings,fragment', [
    ({'NUQATI_MFA_KEY': 'too-short'}, 'at least 32'),
    ({'NUQATI_MFA_KEY': KEY_A, 'NUQATI_MFA_KEY_PREVIOUS': 'short'}, 'PREVIOUS must be at least 32'),
    ({'NUQATI_MFA_KEY_PREVIOUS': KEY_B}, 'PREVIOUS is set but NUQATI_MFA_KEY is not'),
    ({'NUQATI_MFA_KEY': KEY_A, 'NUQATI_MFA_REQUIRED_ROLES': 'super_admin,driver'}, 'driver'),
    ({'NUQATI_MFA_KEY': KEY_A, 'NUQATI_MFA_REQUIRED_ROLES': 'superadmin'}, 'superadmin'),
    ({'NUQATI_MFA_REQUIRED_ROLES': 'super_admin'}, 'could never sign in'),
])
def test_a_wrong_combination_stops_the_start_with_a_clear_message(monkeypatch, settings, fragment):
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError) as caught:
        mfa.validate_settings()
    assert fragment in str(caught.value)


# ----------------------------------------------------------------------------- recovery codes
def test_recovery_codes_have_the_documented_shape_and_are_unique():
    codes = {mfa.new_recovery_code() for _ in range(200)}
    assert len(codes) == 200
    for code in codes:
        parts = code.split('-')
        assert [len(p) for p in parts] == [4, 4, 4]
        assert all(ch in mfa.RECOVERY_ALPHABET for ch in code.replace('-', ''))
        assert mfa.looks_like_recovery(code) and not mfa.looks_like_totp(code)


def test_a_recovery_code_is_stored_only_as_a_salted_hash_and_checks_in_any_notation():
    code = mfa.new_recovery_code()
    salt, digest = mfa.hash_recovery_code(code)
    assert code not in digest and code.replace('-', '') not in digest
    assert mfa.hash_recovery_code(code)[0] != salt, "a new salt every time"
    assert mfa.recovery_code_matches(code, salt, digest)
    assert mfa.recovery_code_matches(code.lower(), salt, digest)
    assert mfa.recovery_code_matches(code.replace('-', ' '), salt, digest)
    other = mfa.new_recovery_code()
    assert not mfa.recovery_code_matches(other, salt, digest)
    assert not mfa.recovery_code_matches(code, 'not hex', digest)


def test_the_two_kinds_of_code_are_told_apart():
    assert mfa.looks_like_totp('123456') and mfa.looks_like_totp('123 456')
    assert not mfa.looks_like_recovery('123456')
    assert not mfa.looks_like_totp('ABCD-EFGH-JKLM') and mfa.looks_like_recovery('abcd efgh jklm')
    assert not mfa.looks_like_recovery('ABCD-EFGH-JKL0'), "0 is not in the alphabet"


# ----------------------------------------------------------------------------- guessing lock
def test_the_lock_starts_at_the_fifth_wrong_code_and_grows_to_a_day():
    assert [mfa.lock_seconds(n) for n in range(1, 5)] == [0, 0, 0, 0]
    assert mfa.lock_seconds(5) == 15 * 60 and mfa.lock_seconds(10) == 30 * 60 and mfa.lock_seconds(15) == 60 * 60
    assert [mfa.lock_seconds(n) for n in (6, 7, 8, 9, 11)] == [0] * 5, "only every fifth failure sets a new lock"
    assert mfa.lock_seconds(500) == 24 * 3600


# ----------------------------------------------------------------------------- step tokens
def _user(auth_version=3):
    return SimpleNamespace(id=41, role='company_admin', auth_version=auth_version)


def test_a_step_token_carries_user_version_and_type_and_expires():
    for kind, minutes in (('mfa', 5), ('mfa_setup', 15)):
        token = mfa.encode_step_token(_user(), kind)
        claims = mfa.decode_step_token(token, (kind,))
        assert claims['sub'] == 41 and claims['ver'] == 3 and claims['typ'] == kind
        assert minutes * 60 - 5 <= claims['exp'] - time.time() <= minutes * 60 + 5


def test_a_step_token_is_refused_for_the_other_step_and_when_damaged_or_expired(monkeypatch):
    token = mfa.encode_step_token(_user(), 'mfa')
    assert mfa.decode_step_token(token, ('mfa_setup',)) is None
    assert mfa.decode_step_token(token, ('mfa', 'mfa_setup')) is not None
    body, sig = token.split('.')
    assert mfa.decode_step_token(body + '.' + '0' * len(sig), ('mfa',)) is None
    assert mfa.decode_step_token(token + 'x', ('mfa',)) is None
    for junk in ('', 'a.b', 'a.b.c', 'not a token'):
        assert mfa.decode_step_token(junk, ('mfa',)) is None
    later = time.time() + 6 * 60
    monkeypatch.setattr(mfa.time, 'time', lambda: later)  # mfa.time is the time module itself
    assert mfa.decode_step_token(token, ('mfa',)) is None, "expired after five minutes"


def test_an_access_token_is_not_a_step_token_and_a_step_token_is_not_an_access_token():
    from app.auth import encode_token

    access = encode_token(SimpleNamespace(id=41, role='company_admin', auth_version=3))
    assert mfa.decode_step_token(access, ('mfa', 'mfa_setup')) is None
    body = mfa.encode_step_token(_user(), 'mfa').split('.')[0]
    claims = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
    assert claims['typ'] != 'access', "current_user accepts only typ 'access'"


def test_a_step_token_made_with_another_signing_secret_is_refused(monkeypatch):
    token = mfa.encode_step_token(_user(), 'mfa')
    monkeypatch.setenv('NUQATI_AUTH_SECRET', 'a-completely-different-signing-secret-0123456789')
    assert mfa.decode_step_token(token, ('mfa',)) is None


def test_during_a_planned_rotation_an_old_step_token_is_not_accepted_but_nobody_is_locked_out(monkeypatch):
    """Access tokens keep working through NUQATI_AUTH_SECRET_PREVIOUS; the 5-minute step tokens do not (the person types the password again)."""
    token = mfa.encode_step_token(_user(), 'mfa')
    old = os.environ['NUQATI_AUTH_SECRET']
    monkeypatch.setenv('NUQATI_AUTH_SECRET', 'a-completely-different-signing-secret-0123456789')
    monkeypatch.setenv('NUQATI_AUTH_SECRET_PREVIOUS', old)
    assert mfa.decode_step_token(token, ('mfa',)) is None
    assert mfa.decode_step_token(mfa.encode_step_token(_user(), 'mfa'), ('mfa',)) is not None
