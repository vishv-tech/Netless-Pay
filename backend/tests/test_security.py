import base64
import secrets
from uuid import uuid4

import pytest

from app.security import DeviceCipher, check_password_policy, normalize_phone, random_token, token_hash


def test_authenticated_encryption_binds_identity_and_version():
    cipher = DeviceCipher(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    device, participant, secret = uuid4(), uuid4(), random_token()
    encrypted = cipher.encrypt(secret, device, participant, 1)
    assert secret.encode() not in encrypted
    assert encrypted != cipher.encrypt(secret, device, participant, 1)
    assert cipher.matches(encrypted, secret, device, participant, 1)
    assert not cipher.matches(encrypted, secret, uuid4(), participant, 1)
    assert not cipher.matches(encrypted, secret, device, uuid4(), 1)
    assert not cipher.matches(encrypted, secret, device, participant, 2)
    damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    assert not cipher.matches(damaged, secret, device, participant, 1)


@pytest.mark.parametrize("key", ["", "invalid", base64.b64encode(b"short").decode()])
def test_master_key_fails_closed(key):
    with pytest.raises(ValueError, match="DEVICE_MASTER_KEY"):
        DeviceCipher(key)


@pytest.mark.parametrize("password", ["short", "onlyletterslongenough", "12345678901234", "myPassword-is-long-7", "a" * 129])
def test_minimum_password_policy(password):
    with pytest.raises(ValueError):
        check_password_policy(password)


def test_phone_normalization_and_token_domain_separation():
    assert normalize_phone("91-98765-43210") == "+919876543210"
    with pytest.raises(ValueError):
        normalize_phone("+1 9876543210")
    raw = random_token()
    assert len(raw) >= 40
    assert token_hash("session", raw) != token_hash("enrollment", raw)


def test_bootstrap_rejects_password_command_line(monkeypatch, capsys):
    from app.bootstrap import main
    monkeypatch.setattr("sys.argv", ["bootstrap", "create-admin", "--password", "not-a-real-credential"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "not-a-real-credential" not in captured.out + captured.err
    # Argparse rejects the option before any database access or password prompt.
