"""auth.py — Authentication, premium access, key generation, admin & ban management."""

import json
import os
import time
import string
import random

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
ADMINS_FILE  = os.path.join(BASE_DIR, "admins.json")
PREMIUM_FILE = os.path.join(BASE_DIR, "premium.json")
KEYS_FILE    = os.path.join(BASE_DIR, "keys.json")
BANNED_FILE  = os.path.join(BASE_DIR, "banned.json")
NOPECHA_FILE = os.path.join(BASE_DIR, "nopecha.json")
USERS_FILE   = os.path.join(BASE_DIR, "users.txt")

# ── Sole owner ────────────────────────────────────────────────────────────────
OWNER_IDS = {8000346393}

# ── CC limits per role ────────────────────────────────────────────────────────
CC_LIMITS = {
    "owner":   20000,
    "admin":   15000,
    "premium": 10000,
    "free":    200,
}

# ── mtime-based cache for hot permission files ────────────────────────────────
_json_cache: dict[str, dict | list] = {}
_json_mtime: dict[str, float] = {}

def _load_json_cached(path: str):
    """Return cached parse of *path* unless the file was modified on disk."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    prev = _json_mtime.get(path)
    if prev is not None and prev == mt and path in _json_cache:
        return _json_cache[path]
    data = _load_json(path)
    _json_cache[path] = data
    _json_mtime[path] = mt
    return data


# ══════════════════════════════════════════════════════════════════════════════
#  GENERIC JSON HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _json_cache[path] = data
    try:
        _json_mtime[path] = os.path.getmtime(path)
    except OSError:
        _json_mtime.pop(path, None)


# ══════════════════════════════════════════════════════════════════════════════
#  USERS  (users.txt — pipe-delimited: id|username|full_name)
# ══════════════════════════════════════════════════════════════════════════════

def save_user(user_id: int, username: str | None, full_name: str | None) -> None:
    """Upsert a user record into users.txt (id|username|name).
    Existing entries are updated in-place; new ones appended."""
    uid   = str(user_id)
    uname = (username or "none").strip()
    name  = (full_name or "").replace("|", " ").strip()
    try:
        lines: list[str] = []
        found = False
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
        new_lines: list[str] = []
        for line in lines:
            parts = line.strip().split("|")
            if parts and parts[0] == uid:
                new_lines.append(f"{uid}|{uname}|{name}\n")
                found = True
            else:
                new_lines.append(line if line.endswith("\n") else line + "\n")
        if not found:
            new_lines.append(f"{uid}|{uname}|{name}\n")
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass



# ══════════════════════════════════════════════════════════════════════════════
#  OWNER
# ══════════════════════════════════════════════════════════════════════════════

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


# ══════════════════════════════════════════════════════════════════════════════
#  ADMINS  (admins.json)
# ══════════════════════════════════════════════════════════════════════════════

def load_admins() -> list:
    data = _load_json_cached(ADMINS_FILE)
    return data.get("admins", [])

def save_admins(admins: list):
    _save_json(ADMINS_FILE, {"admins": admins})

def add_admin(user_id: int) -> bool:
    admins = load_admins()
    if user_id not in admins:
        admins.append(user_id)
        save_admins(admins)
        return True
    return False

def remove_admin(user_id: int) -> bool:
    admins = load_admins()
    if user_id in admins:
        admins.remove(user_id)
        save_admins(admins)
        return True
    return False

def is_admin(user_id: int) -> bool:
    return user_id in load_admins() or is_owner(user_id)


# ══════════════════════════════════════════════════════════════════════════════
#  PREMIUM  (premium.json)
# ══════════════════════════════════════════════════════════════════════════════

def load_premium() -> dict:
    return _load_json_cached(PREMIUM_FILE)

def save_premium(data: dict):
    _save_json(PREMIUM_FILE, data)

def auth_user(user_id: int, days: int = 0, by: int = 0):
    """Grant premium. days=0 → lifetime."""
    data = load_premium()
    expires = 0 if days == 0 else int(time.time()) + (days * 86400)
    data[str(user_id)] = {
        "expires": expires,
        "authorized_by": by,
        "authorized_at": int(time.time()),
    }
    save_premium(data)


def is_premium(user_id: int) -> bool:
    if is_owner(user_id) or user_id in load_admins():
        return True
    data = load_premium()
    entry = data.get(str(user_id))
    if not entry:
        return False
    expires = entry.get("expires", 0)
    if expires == 0:
        return True   # lifetime
    return time.time() < expires


# ══════════════════════════════════════════════════════════════════════════════
#  KEYS  (keys.json)
# ══════════════════════════════════════════════════════════════════════════════

def load_keys() -> dict:
    return _load_json(KEYS_FILE)

def save_keys(data: dict):
    _save_json(KEYS_FILE, data)


def redeem_key(user_id: int, key: str) -> tuple[bool, str]:
    """Try to redeem a key. Returns (success, info_message)."""
    data = load_keys()
    if key not in data:
        return False, "Invalid key"
    entry = data[key]
    days = entry.get("days", 0)
    redeemed = entry.get("redeemed_by")

    if redeemed is not None and not isinstance(redeemed, list):
        return False, "Key already redeemed"

    if isinstance(redeemed, list):
        redeemers = list(redeemed)
        max_uses = int(entry.get("max_uses") or 1)
    else:
        redeemers = []
        max_uses = int(entry.get("max_uses") or 1)

    if user_id in redeemers:
        return False, "You already redeemed this key"

    if len(redeemers) >= max_uses:
        return False, "Key fully redeemed (no slots left)"

    redeemers.append(user_id)
    entry["redeemed_by"] = redeemers
    entry["redeemed_at"] = int(time.time())
    entry["max_uses"] = max_uses
    save_keys(data)
    auth_user(user_id, days=days, by=0)
    left = max_uses - len(redeemers)
    return True, f"{days} days ({left}/{max_uses} slots left)"


# ══════════════════════════════════════════════════════════════════════════════
#  BANNED  (banned.json)
# ══════════════════════════════════════════════════════════════════════════════

def load_banned() -> list:
    data = _load_json_cached(BANNED_FILE)
    if isinstance(data, list):
        return data
    return data.get("banned", [])

def save_banned(banned: list):
    _save_json(BANNED_FILE, {"banned": banned})

def ban_user(user_id: int) -> bool:
    banned = load_banned()
    if user_id not in banned:
        banned.append(user_id)
        save_banned(banned)
        return True
    return False

def unban_user(user_id: int) -> bool:
    banned = load_banned()
    if user_id in banned:
        banned.remove(user_id)
        save_banned(banned)
        return True
    return False

def is_banned(user_id: int) -> bool:
    return user_id in load_banned()


# ══════════════════════════════════════════════════════════════════════════════
#  ROLE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_user_role(user_id: int) -> str:
    if is_owner(user_id):
        return "owner"
    if user_id in load_admins():
        return "admin"
    if is_premium(user_id):
        return "premium"
    return "free"


# ══════════════════════════════════════════════════════════════════════════════
#  NOPECHA API KEY  (nopecha.json — per-user captcha solver key)
# ══════════════════════════════════════════════════════════════════════════════

def get_nopecha_key(user_id: int) -> str:
    """Return the NopeCHA API key set by this user, or '' if none."""
    return _load_json(NOPECHA_FILE).get(str(user_id), "")


