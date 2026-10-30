"""Vòng lặp gửi hàng loạt, dùng chung cho GUI và CLI."""
import json
import logging
import random
import threading
import time
from pathlib import Path

import config as cfg
from data_store import ContactStore, is_valid_phone
from zalo_client import ContactNotFound, ZaloClient

log = logging.getLogger(__name__)


# ---------- lịch sử gửi (giới hạn số tin / giờ) ----------
# Lưu trong thư mục profile của tài khoản -> tắt mở lại tool vẫn không vượt giới hạn
def _history_path(profile_dir: str) -> Path:
    return Path(profile_dir) / cfg.SEND_HISTORY_FILE


def load_history(profile_dir: str) -> list[float]:
    """Mốc thời gian các tin gửi thành công trong 1 giờ qua (cũ -> mới)."""
    try:
        data = json.loads(_history_path(profile_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    now = time.time()
    return sorted(t for t in data if isinstance(t, (int, float)) and now - t < cfg.RATE_WINDOW)


def save_history(profile_dir: str, history: list[float]) -> None:
    try:
        _history_path(profile_dir).write_text(json.dumps(history), encoding="utf-8")
    except OSError as e:   # profile chưa tạo/đang bị xóa -> chỉ mất bộ đếm, không chặn việc gửi
        log.warning("Không lưu được lịch sử gửi: %s", e)


class BatchSender:
    def __init__(self, store: ContactStore, on_status=None, on_login_needed=None, on_profile=None,
                 profile_dir: str = cfg.PROFILE_DIR, headless: bool = cfg.DEFAULT_HEADLESS,
                 max_per_hour: int = cfg.DEFAULT_MAX_PER_HOUR, on_quota=None, on_wait=None):
        """
        on_status(idx, status): gọi mỗi khi trạng thái 1 dòng đổi (từ thread gửi).
        on_login_needed(): gọi khi cần người dùng quét QR.
        on_profile(info): gọi sau khi vào được Zalo, info như ZaloClient.get_profile().
        on_quota(sent): số tin đã gửi trong 1 giờ qua (gọi lúc bắt đầu và sau mỗi tin thành công).
        on_wait(seconds, remaining): đủ max_per_hour tin/giờ -> chờ thêm `seconds` giây rồi tự gửi đợt tiếp,
            `remaining` = số người còn lại chưa gửi (gọi lại mỗi giây trong lúc chờ).
        """
        self.store = store
        self.on_status = on_status
        self.on_login_needed = on_login_needed
        self.on_profile = on_profile
        self.profile_dir = profile_dir
        self.headless = headless
        self.max_per_hour = max_per_hour
        self.on_quota = on_quota
        self.on_wait = on_wait
        self._history: list[float] = []
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def _sleep(self, seconds: float) -> None:
        """Ngủ nhưng thoát ngay khi bấm Dừng."""
        end = time.time() + seconds
        while time.time() < end and not self._stop.is_set():
            time.sleep(0.3)

    def _set(self, idx: int, status: str, save: bool = False) -> None:
        self.store.set_status(idx, status)
        if self.on_status:
            self.on_status(idx, status)
        if save:
            self.store.save()

    # ---------- giới hạn tin / giờ ----------
    def _prune_history(self) -> None:
        now = time.time()
        self._history = [t for t in self._history if now - t < cfg.RATE_WINDOW]

    def _wait_for_quota(self, remaining: int) -> None:
        """Đủ max_per_hour tin trong 60 phút gần nhất thì chờ tới khi tin cũ nhất ra khỏi khung 1 giờ,
        sau đó vòng gửi chạy tiếp -> cứ mỗi giờ tối đa max_per_hour tin cho tới hết danh sách."""
        while not self._stop.is_set():
            self._prune_history()
            if len(self._history) < self.max_per_hour:
                return
            wait = self._history[0] + cfg.RATE_WINDOW - time.time()
            log.info("Đủ %d tin/giờ, chờ %d giây", self.max_per_hour, wait)
            if self.on_wait:
                self.on_wait(wait, remaining)
            self._sleep(min(wait, 1))   # cập nhật đếm ngược mỗi giây

    def _record_sent(self) -> None:
        self._history.append(time.time())
        self._prune_history()
        save_history(self.profile_dir, self._history)
        if self.on_quota:
            self.on_quota(len(self._history))

    def run(self, indices, delay: int, skip_done: bool = False, limit: int | None = None):
        """Trả về (thành công, thất bại)."""
        self._stop.clear()
        todo = [i for i in indices
                if not (skip_done and self.store.status(i) == cfg.STATUS_OK)]
        if limit:
            todo = todo[:limit]

        self._history = load_history(self.profile_dir)
        if self.on_quota:
            self.on_quota(len(self._history))

        success = failed = 0
        with ZaloClient(self.profile_dir, headless=self.headless) as client:
            client.open_and_login(self.on_login_needed)
            if self.on_profile:
                self.on_profile(client.get_profile())

            for n, idx in enumerate(todo):
                if self._stop.is_set():
                    break

                phone = self.store.phone(idx)
                if not is_valid_phone(phone):
                    self._set(idx, cfg.STATUS_INVALID, save=True)
                    failed += 1
                    continue

                self._wait_for_quota(remaining=len(todo) - n)
                if self._stop.is_set():
                    break

                self._set(idx, cfg.STATUS_SENDING)
                try:
                    client.send_message(phone, self.store.render_message(idx))
                    self._set(idx, cfg.STATUS_OK, save=True)
                    self._record_sent()
                    success += 1
                    log.info("OK  %s", phone)
                except ContactNotFound:
                    self._set(idx, cfg.STATUS_NOT_FOUND, save=True)
                    failed += 1
                    log.warning("Không tìm thấy %s", phone)
                except Exception as e:
                    self._set(idx, cfg.STATUS_ERROR, save=True)
                    failed += 1
                    # Thay đổi ở đây: In chi tiết lỗi ra màn hình CMD
                    log.error("Lỗi khi gửi %s: %s", phone, str(e))

                if n < len(todo) - 1 and not self._stop.is_set():
                    self._sleep(delay + random.uniform(0, cfg.DELAY_JITTER))

        return success, failed
