"""Owner password for one local ClipHunter installation."""
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

CONFIG = Path(os.environ.get('CLIPHUNTER_CONFIG_DIR', Path.home()/'.config'/'ClipHunter'))
PASSWORD_FILE = CONFIG/'password.json'


def legacy_password(root):
    if os.environ.get('APP_PASSWORD'):
        return os.environ['APP_PASSWORD']
    env = Path(root)/'.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('APP_PASSWORD='):
                return line.partition('=')[2].strip()
    return None


def configured(root):
    return PASSWORD_FILE.exists() or bool(legacy_password(root))


def verify(password, root):
    if not isinstance(password, str):
        return False
    if PASSWORD_FILE.exists():
        record = json.loads(PASSWORD_FILE.read_text())
        derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record['salt']),
                                 n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(derived, bytes.fromhex(record['hash']))
    legacy = legacy_password(root)
    return bool(legacy) and hmac.compare_digest(password.encode(), legacy.encode())


def set_password(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise ValueError('Choose a password between 10 and 256 characters')
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CONFIG, 0o700)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    temporary = PASSWORD_FILE.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump({'salt':salt.hex(), 'hash':digest.hex()}, stream)
    os.replace(temporary, PASSWORD_FILE)
    os.chmod(PASSWORD_FILE, 0o600)
