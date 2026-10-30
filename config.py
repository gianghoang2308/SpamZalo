"""Cấu hình chung. Khi Zalo đổi giao diện, chỉ cần sửa các SEL_* ở đây."""
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = str(BASE_DIR / "zalo_profile")   # profile mặc định (tài khoản 1)
PROFILES_SUBDIR = "zalo_profiles"               # profile của các tài khoản thêm sau
ACCOUNTS_FILE = BASE_DIR / "accounts.json"     # danh sách tài khoản (tên tab -> thư mục profile)
TEMPLATES_FILE = BASE_DIR / "templates.json"   # mẫu nội dung tin nhắn ở cột phải
LOG_FILE = BASE_DIR / "zalo_sender.log"
EXPORT_DIR = BASE_DIR / "File Excel"           # nơi lưu file khi bấm "Xuất Excel"
EXPORT_NAME_FORMAT = "%d-%m-%y_%H-%M-%S"       # Windows không cho "/" và ":" trong tên file
ZALO_URL = "https://chat.zalo.me"
DEFAULT_HEADLESS = True   # gửi tin bằng trình duyệt chạy ẩn; tự hiện cửa sổ khi cần quét QR

# ---- Thời gian ----
DEFAULT_DELAY = 15        # giây giữa 2 tin
MIN_DELAY = 5
DELAY_JITTER = 5          # cộng thêm ngẫu nhiên 0..5 giây
DEFAULT_MAX_PER_HOUR = 30   # tối đa số tin gửi thành công trong 60 phút (mỗi tài khoản, sửa được trên GUI)
RATE_WINDOW = 3600          # giây
SEND_HISTORY_FILE = "send_history.json"   # mốc thời gian các tin đã gửi, nằm trong thư mục profile của tài khoản
LOGIN_TIMEOUT_MS = 600_000  # Tăng lên 10 phút để bạn có thời gian quét QR thoải mái

# ---- Trạng thái ----
STATUS_PENDING = "Chưa gửi"
STATUS_SENDING = "Đang gửi..."
STATUS_OK = "Thành công"
STATUS_NOT_FOUND = "Không tìm thấy"
STATUS_INVALID = "SĐT không hợp lệ"
STATUS_ERROR = "Lỗi"

# ---- Cột "Thông báo" (chi tiết cho từng dòng) ----
NOTE_NOT_FOUND = "Không tìm thấy"
NOTE_INVALID = "SĐT không hợp lệ (cần ít nhất 10 số)"
NOTE_SENT_FRIEND = "Đã gửi (bạn bè) lúc {time}"
NOTE_SENT_STRANGER = "Đã gửi (người lạ) lúc {time}"
NOTE_ERROR = "Lỗi: {reason}"

# ---- Selector Zalo Web (CẦN KIỂM TRA bằng: playwright codegen https://chat.zalo.me) ----
SEL_SEARCH_INPUT = '#contact-search-input'   # đã kiểm tra 28/10/2026: ô này không có placeholder
SEL_MESSAGE_BOX = 'div[contenteditable="true"]'
SEL_NAV_PROFILE = '.nav__tabs__zalo'          # avatar góc trên trái, thuộc tính title = tên Zalo đang đăng nhập
SEL_NAV_AVATAR = '.nav__tabs__zalo img'
TEXT_MESSAGE_BUTTON = "Nhắn tin"   # nút trong popup hồ sơ khi tìm người chưa kết bạn


def setup_logging(console: bool = True) -> None:
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )