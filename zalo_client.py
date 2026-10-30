"""Điều khiển Zalo Web bằng Playwright. Chỉ biết về Zalo, không biết Excel/GUI.

Lưu ý: Playwright sync API phải dùng trong CÙNG một thread với nơi khởi tạo,
nên hãy tạo ZaloClient bên trong thread gửi (BatchSender.run làm đúng việc này).
"""
import logging
import random
import time

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

import config as cfg

log = logging.getLogger(__name__)


class ContactNotFound(Exception):
    pass


class ZaloClient:
    def __init__(self, profile_dir: str = cfg.PROFILE_DIR, headless: bool = False):
        self.profile_dir = profile_dir
        self.headless = headless
        self._pw = None
        self._ctx = None
        self.page = None

    # ---------- vòng đời ----------
    def __enter__(self):
        self._pw = sync_playwright().start()
        self._launch(self.headless)
        return self

    def _launch(self, headless: bool) -> None:
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=headless,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def __exit__(self, *exc):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def open_and_login(self, on_login_needed=None) -> None:
        # Có cửa sổ thì báo quét QR sớm (QR đã hiện sẵn); vẫn chờ tiếp nếu phiên cũ chỉ tải chậm
        if self.open_zalo(30_000 if self.headless else 8_000):
            return
        if self.headless:
            # Chạy ẩn thì không quét QR được -> mở lại có cửa sổ (cùng profile).
            # Nếu có cửa sổ mà vào được ngay thì phiên vẫn còn, chỉ là Zalo không chạy được ở chế độ ẩn.
            log.info("Chạy ẩn không vào được Zalo, mở lại trình duyệt có cửa sổ...")
            self._ctx.close()
            self._launch(False)
            self.headless = False
            if self.open_zalo(15_000):
                log.warning("Phiên còn hạn nhưng Zalo không chạy ở chế độ ẩn, tiếp tục với cửa sổ")
                return
        log.info("Chưa đăng nhập, chờ quét QR...")
        if on_login_needed:
            on_login_needed()
        self.page.wait_for_selector(cfg.SEL_SEARCH_INPUT, timeout=cfg.LOGIN_TIMEOUT_MS)

    def open_zalo(self, timeout_ms: int = 30_000) -> bool:
        """Mở Zalo Web, trả về True nếu đã đăng nhập sẵn."""
        self.page.goto(cfg.ZALO_URL, timeout=60_000)
        try:
            self.page.wait_for_selector(cfg.SEL_SEARCH_INPUT, timeout=timeout_ms)
            return True
        except PWTimeout:
            return False

    def get_profile(self) -> dict:
        """Tài khoản đang đăng nhập: {"zalo_name", "uid", "avatar": bytes ảnh (nếu có)}. Lỗi thì trả {}."""
        page = self.page
        try:
            nav = page.locator(cfg.SEL_NAV_PROFILE).first
            nav.wait_for(state="attached", timeout=10_000)
            info = {"zalo_name": nav.get_attribute("title") or "",
                    "uid": page.evaluate("localStorage.getItem('sh_zlast_uid')") or ""}
        except Exception as e:
            log.warning("Không đọc được thông tin tài khoản: %s", e)
            return {}
        try:   # chưa đặt ảnh đại diện thì Zalo hiện chữ cái, không có <img>
            src = page.locator(cfg.SEL_NAV_AVATAR).first.get_attribute("src", timeout=3000)
            if src and src.startswith("http"):
                resp = page.request.get(src)
                if resp.ok:
                    info["avatar"] = resp.body()
        except Exception:
            pass
        return info

    # ---------- gửi tin ----------
    def send_message(self, phone: str, message: str) -> bool:
        """Gửi 1 tin. Trả về True nếu người nhận là người lạ (chưa kết bạn).
        Raise ContactNotFound nếu không tìm thấy, lỗi khác thì raise tiếp."""
        try:
            stranger = self._open_chat(phone)
            self._type_and_send(message)
            return stranger
        finally:
            self._clear_search()

    def _open_chat(self, phone: str) -> bool:
        page = self.page
        box = page.locator(cfg.SEL_SEARCH_INPUT).first
        box.click()
        box.fill("")
        box.fill(phone)
        time.sleep(random.uniform(1.6, 2.4))

        # Chỉ bấm vào kết quả chứa đúng SĐT. KHÔNG dùng "kết quả đầu tiên" làm dự phòng:
        # danh sách có thể là hội thoại cũ/được ghim -> gửi nhầm người.
        target = page.get_by_text(phone).first
        try:
            target.wait_for(state="visible", timeout=2500)
        except PWTimeout:
            raise ContactNotFound(phone) from None
        target.click(force=True)

        # Người chưa kết bạn: Zalo hiện popup hồ sơ có nút "Nhắn tin".
        # Lần tìm đầu tiên sau khi mở Zalo popup hiện chậm -> chờ ô soạn tin, chưa có thì thử lại.
        btn = page.get_by_role("button", name=cfg.TEXT_MESSAGE_BUTTON).first
        msg_box = page.locator(cfg.SEL_MESSAGE_BOX).last
        stranger = False
        for wait_ms in (2000, 6000):
            try:
                btn.wait_for(state="visible", timeout=wait_ms)
                btn.click()
                stranger = True
            except PWTimeout:
                pass
            try:
                msg_box.wait_for(state="visible", timeout=wait_ms)
                break
            except PWTimeout:
                continue
        else:
            raise RuntimeError(f"Không mở được khung chat của {phone}")

        time.sleep(random.uniform(1.3, 2.1))
        return stranger

    def _type_and_send(self, message: str) -> None:
        page = self.page
        box = page.locator(cfg.SEL_MESSAGE_BOX).last
        box.click()
        lines = message.replace("\r\n", "\n").split("\n")
        for i, line in enumerate(lines):
            if line:
                page.keyboard.insert_text(line)
            if i < len(lines) - 1:
                page.keyboard.press("Shift+Enter")   # xuống dòng, không gửi
        time.sleep(random.uniform(0.5, 0.9))
        page.keyboard.press("Enter")
        time.sleep(0.7)

    def _clear_search(self) -> None:
        try:
            box = self.page.locator(cfg.SEL_SEARCH_INPUT).first
            box.click()
            box.fill("")
        except Exception:
            pass