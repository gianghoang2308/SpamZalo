"""Danh sách tài khoản Zalo. Mỗi tài khoản có thư mục profile Chromium riêng (giữ phiên đăng nhập)."""
import json
import shutil
import time
from pathlib import Path

import config as cfg

# Tài khoản cũ (trước khi có đa tài khoản) dùng thư mục zalo_profile -> giữ nguyên để khỏi quét QR lại
DEFAULT_ACCOUNTS = [{"name": "Tài khoản 1", "profile": "zalo_profile"}]


def load() -> list[dict]:
    try:
        data = json.loads(cfg.ACCOUNTS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data
    except (FileNotFoundError, ValueError):
        pass
    return [dict(a) for a in DEFAULT_ACCOUNTS]


def save(accounts: list[dict]) -> None:
    cfg.ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")


def new_account(name: str) -> dict:
    return {"name": name, "profile": f"{cfg.PROFILES_SUBDIR}/acc_{int(time.time() * 1000)}"}


def profile_dir(account: dict) -> str:
    return str(cfg.BASE_DIR / account["profile"])


def find(accounts: list[dict], name: str) -> dict | None:
    return next((a for a in accounts if a["name"].lower() == name.lower()), None)


def has_profile(account: dict) -> bool:
    return Path(profile_dir(account)).is_dir()


def avatar_path(account: dict) -> Path:
    # Nằm trong thư mục profile -> đăng xuất (xóa profile) là mất luôn
    return Path(profile_dir(account)) / "tool_avatar.jpg"


def apply_profile(account: dict, info: dict) -> None:
    """Ghi thông tin Zalo (tên, uid, ảnh) lấy được sau khi đăng nhập vào tài khoản."""
    account["zalo_name"] = info.get("zalo_name", "")
    account["uid"] = info.get("uid", "")
    if info.get("avatar"):
        avatar_path(account).write_bytes(info["avatar"])


def clear_profile(account: dict) -> None:
    account.pop("zalo_name", None)
    account.pop("uid", None)


def delete_profile(account: dict) -> None:
    shutil.rmtree(profile_dir(account), ignore_errors=True)
    clear_profile(account)
