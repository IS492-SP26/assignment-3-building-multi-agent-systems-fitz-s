"""
macOS Keychain secret resolver.

Created: 2026-05-07
Last reused or audited: 2026-05-07
Authority basis: Plan §Secrets, user requirement (no secrets in .env)

Resolves secrets from macOS Keychain via openclaw resolver. Never logs values.
Translates Fitz Constraint #4 (data provenance) to credential handling: a key
without provable provenance (Keychain) does not enter the process env.
"""
import json, subprocess, os
from functools import lru_cache

KEYCHAIN_RESOLVER = "/Users/leofitz/.openclaw/bin/keychain_resolver.py"

@lru_cache(maxsize=8)
def get_secret(secret_id: str) -> str | None:
    try:
        req = json.dumps({"protocolVersion": 1, "ids": [secret_id]}).encode()
        out = subprocess.check_output([KEYCHAIN_RESOLVER], input=req, timeout=5)
        return json.loads(out)["values"].get(secret_id)
    except Exception:
        return None

def inject_into_env(secret_id: str, env_var: str) -> bool:
    """Inject a keychain secret into os.environ. Returns True on success."""
    val = get_secret(secret_id)
    if val:
        os.environ[env_var] = val
        return True
    return False
