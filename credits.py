"""credits.py — Credit-based key system for the Stripe Checker bot.

Credits deducted only when 3DS is bypassed (tds_bypassed=True).
Admins / Owners have unlimited access — no credits deducted.

Plans:
  7-day  → 100 credits  ($10)
  15-day → 250 credits  ($20)
  30-day → 600 credits  ($25)
"""

import json
import os
import random
import string
import time

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
CREDITS_FILE = os.path.join(BASE_DIR, "credits.json")
CKEYS_FILE   = os.path.join(BASE_DIR, "ckeys.json")

# ── Plans ─────────────────────────────────────────────────────────────────────
PLANS = {
    "7":  {"credits": 100, "days": 7,  "price": "$10", "label": "Starter"},
    "15": {"credits": 250, "days": 15, "price": "$20", "label": "Pro"},
    "30": {"credits": 600, "days": 30, "price": "$25", "label": "Elite"},
}


# ══════════════════════════════════════════════════════════════════════════════
#  JSON HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
#  CREDIT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def get_entry(user_id: int) -> dict:
    """Raw entry from credits.json for a user."""
    data = _load(CREDITS_FILE)
    return data.get(str(user_id), {"credits": 0, "expires": 0})


def get_credits(user_id: int) -> int:
    """Return available credits (0 if expired)."""
    entry = get_entry(user_id)
    exp   = entry.get("expires", 0)
    if exp != 0 and time.time() > exp:
        return 0
    return int(entry.get("credits", 0))


def has_credits(user_id: int) -> bool:
    return get_credits(user_id) > 0



def expiry_str(user_id: int) -> str:
    """Human-readable expiry string."""
    entry = get_entry(user_id)
    exp   = entry.get("expires", 0)
    if exp == 0:
        return "No plan"
    remaining = exp - time.time()
    if remaining <= 0:
        return "Expired"
    days  = int(remaining // 86400)
    hours = int((remaining % 86400) // 3600)
    mins  = int((remaining % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {mins}m"


def add_credits(user_id: int, credits: int, days: int, by: int = 0, plan: str = "") -> None:
    """Add credits + extend or set plan duration."""
    data  = _load(CREDITS_FILE)
    uid   = str(user_id)
    entry = data.get(uid, {"credits": 0, "expires": 0})
    now   = time.time()

    cur_exp = entry.get("expires", 0)
    # Stack duration if plan is still active; otherwise start fresh
    if cur_exp and cur_exp > now:
        new_exp = cur_exp + days * 86400
    else:
        new_exp = now + days * 86400

    entry["credits"]    = int(entry.get("credits", 0)) + credits
    entry["expires"]    = new_exp
    entry["last_topup"] = int(now)
    entry["topped_by"]  = by
    if plan:
        entry["plan"] = plan

    data[uid] = entry
    _save(CREDITS_FILE, data)


def deduct_credit(user_id: int) -> bool:
    """Deduct 1 credit. Returns True if successful, False if no credits / expired."""
    data  = _load(CREDITS_FILE)
    uid   = str(user_id)
    entry = data.get(uid, {"credits": 0, "expires": 0})

    exp = entry.get("expires", 0)
    if exp != 0 and time.time() > exp:
        entry["credits"] = 0
        data[uid] = entry
        _save(CREDITS_FILE, data)
        return False

    credits = int(entry.get("credits", 0))
    if credits <= 0:
        return False

    entry["credits"]   = credits - 1
    entry["last_used"] = int(time.time())
    data[uid] = entry
    _save(CREDITS_FILE, data)
    return True


def set_credits(user_id: int, credits: int, days: int, by: int = 0, plan: str = "") -> None:
    """Set (overwrite) credits and duration for a user (admin use)."""
    data  = _load(CREDITS_FILE)
    uid   = str(user_id)
    now   = time.time()
    data[uid] = {
        "credits":    credits,
        "expires":    now + days * 86400,
        "last_topup": int(now),
        "topped_by":  by,
        "plan":       plan,
    }
    _save(CREDITS_FILE, data)


# ══════════════════════════════════════════════════════════════════════════════
#  KEY GENERATION & REDEMPTION
# ══════════════════════════════════════════════════════════════════════════════

def generate_key(credits: int, days: int, created_by: int = 0, max_uses: int = 1) -> str:
    """Generate a credit key (format: XXXX-XXXXX-XXXX uppercase)."""
    data    = _load(CKEYS_FILE)
    charset = string.ascii_uppercase + string.digits
    p1  = "".join(random.choices(charset, k=4))
    p2  = "".join(random.choices(charset, k=5))
    p3  = "".join(random.choices(charset, k=4))
    key = f"{p1}-{p2}-{p3}"
    data[key] = {
        "credits":     credits,
        "days":        days,
        "created_by":  created_by,
        "created_at":  int(time.time()),
        "max_uses":    max(1, max_uses),
        "redeemed_by": [],
    }
    _save(CKEYS_FILE, data)
    return key


def redeem_key(user_id: int, key: str) -> tuple[bool, str, dict]:
    """
    Redeem a credit key for a user.
    Returns (success, message, info_dict).
    info_dict has: credits, days, slots_left, max_uses
    """
    data        = _load(CKEYS_FILE)
    if key not in data:
        return False, "Invalid key", {}

    entry       = data[key]
    redeemed_by = list(entry.get("redeemed_by") or [])
    max_uses    = int(entry.get("max_uses", 1))

    if user_id in redeemed_by:
        return False, "You already redeemed this key", {}
    if len(redeemed_by) >= max_uses:
        return False, "Key fully used — no slots left", {}

    credits = int(entry.get("credits", 0))
    days    = int(entry.get("days", 0))

    redeemed_by.append(user_id)
    entry["redeemed_by"]      = redeemed_by
    entry["last_redeemed_at"] = int(time.time())
    data[key] = entry
    _save(CKEYS_FILE, data)

    add_credits(user_id, credits, days, by=0)

    slots_left = max_uses - len(redeemed_by)
    return True, "OK", {
        "credits":   credits,
        "days":      days,
        "slots_left": slots_left,
        "max_uses":  max_uses,
    }


