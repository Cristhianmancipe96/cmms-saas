"""Test-run configuration that must never reach production.

`PASSWORD_HASHERS` lives here rather than in `config/settings.py` behind an
"am I running under pytest?" sniff: a production setting that weakens itself
when an environment variable looks a certain way is one mistyped variable away
from hashing real customer passwords with MD5. This file only exists inside
the repo, is only read by pytest, and cannot be imported by a deployed
process.

The cost it removes is real: the suite creates a user per factory call and
PBKDF2 is deliberately slow, so the default hasher spends most of the wall
clock hashing "testpass123" over and over.
"""


def pytest_configure():
    from django.conf import settings

    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
