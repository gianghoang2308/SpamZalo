"""Xử lý dữ liệu Excel (đọc, ghi, quản lý trạng thái)."""
import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

import config as cfg

log = logging.getLogger(__name__)


def is_valid_phone(phone: str) -> bool:
    if not phone:
        return False
    phone_str = str(phone).strip()
    clean_phone = re.sub(r'\D', '', phone_str)
    return len(clean_phone) >= 10

def normalize_phone(phone: str) -> str:
    """Excel lưu SĐT dạng số sẽ mất số 0 đầu ("328296951") hoặc thành "328296951.0"."""
    phone = re.sub(r'\.0+$', '', str(phone).strip())
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 9 and not digits.startswith('0'):
        return '0' + digits
    return phone

def format_date(value: str) -> str:
    """Ô ngày trong Excel đọc ra "2026-11-20 00:00:00" -> "20/11/2026". Ô dạng chữ giữ nguyên."""
    m = re.match(r'^(\d{4}-\d{2}-\d{2})', value)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").strftime("%d/%m/%Y")
    return value

def format_money(value: str) -> str:
    """"2000000" / "2000000.0" -> "2.000.000". Ô đã có chữ/định dạng sẵn thì giữ nguyên."""
    digits = re.sub(r'\.0+$', '', value)
    return f"{int(digits):,}".replace(",", ".") if digits.isdigit() else value

def _norm(header) -> str:
    return " ".join(str(header).lower().split())

# Tên cột do app quản lý: tên nội bộ -> tiêu đề ghi ra Excel (đọc vào chấp nhận cả 2 kiểu)
APP_COLUMNS = {'trangthai': 'Trạng thái', 'thongbao': 'Thông báo'}

# Trường dữ liệu -> các tên cột Excel chấp nhận (đã viết thường)
FIELD_ALIASES = {
    'sdt': ['sdt', 'sđt', 'số điện thoại', 'điện thoại', 'phone'],
    'hoten': ['hoten', 'họ tên', 'họ tên khách hàng', 'họ và tên', 'tên khách hàng', 'khách hàng', 'tên'],
    'mahd': ['mahd', 'mã hợp đồng', 'mã hđ', 'số hợp đồng', 'hợp đồng'],
    'han': ['han', 'hạn thanh toán', 'hạn', 'ngày đến hạn', 'ngày thanh toán'],
    'sotien': ['sotien', 'số tiền', 'số tiền thanh toán', 'số tiền cần thanh toán', 'tiền'],
    'noidung': ['noidung', 'nội dung', 'message', 'tin nhắn'],
}
FORMATTERS = {'sdt': normalize_phone, 'han': format_date, 'sotien': format_money}

# Biến dùng được trong nội dung tin nhắn, ví dụ "Kính gửi {hoten}" -> nhãn hiện trên nút chèn
PLACEHOLDER_LABELS = {'hoten': 'Tên khách', 'mahd': 'Số hợp đồng', 'han': 'Hạn thanh toán',
                      'sotien': 'Số tiền', 'sdt': 'SĐT'}
PLACEHOLDERS = list(PLACEHOLDER_LABELS)
# Dữ liệu giả để xem trước mẫu khi chưa import Excel
SAMPLE_VALUES = {'hoten': 'Nguyễn Văn A', 'mahd': 'HD000123', 'han': '20/11/2026',
                 'sotien': '2.000.000', 'sdt': '0901234567'}


# {bất kỳ tên cột Excel nào}, ví dụ {hoten}, {Họ tên khách hàng}, {địa chỉ}
PLACEHOLDER_RE = re.compile(r'\{([^{}\n]+)\}')


def field_for(name: str) -> str | None:
    """Tên biến -> trường chuẩn (hoten, mahd...) nếu là tên ngắn hoặc 1 tên cột quen thuộc."""
    n = _norm(name)
    if n in PLACEHOLDER_LABELS:
        return n
    return next((f for f in PLACEHOLDERS if n in FIELD_ALIASES[f]), None)


def sample_value(name: str) -> str | None:
    field = field_for(name)
    return SAMPLE_VALUES[field] if field else None


def fill_placeholders(text: str, get) -> str:
    """Thay {tên} bằng get(tên). get trả None (không có cột đó) thì giữ nguyên {tên}."""
    def sub(m):
        val = get(m.group(1))
        return m.group(0) if val is None else val
    return PLACEHOLDER_RE.sub(sub, text)

class ContactStore:
    def __init__(self):
        self.df = None
        self.path = None
        self.loaded = False
        self._headers = {}   # tên nội bộ -> tiêu đề gốc trong file, để ghi lại y nguyên
        self._cols = {}      # trường (FIELD_ALIASES) -> tên cột thực tế trong df

    def load(self, filepath: str):
        self.path = Path(filepath)
        self.df = pd.read_excel(self.path, dtype=str)
        aliases = {title.lower(): key for key, title in APP_COLUMNS.items()}
        originals = [str(c).strip() for c in self.df.columns]
        keys = [aliases.get(_norm(c), _norm(c)) for c in originals]
        self._headers = dict(zip(keys, originals))
        self._headers.update(APP_COLUMNS)
        self.df.columns = keys
        self._cols = {field: next((a for a in names if a in self.df.columns), None)
                      for field, names in FIELD_ALIASES.items()}
        if 'trangthai' not in self.df.columns:
            self.df['trangthai'] = cfg.STATUS_PENDING
        if 'thongbao' not in self.df.columns:
            self.df['thongbao'] = ""
        self.loaded = True

    def __len__(self):
        return len(self.df) if self.loaded else 0

    def indices(self) -> list[int]:
        if not self.loaded:
            return []
        return list(self.df.index)

    def field(self, idx: int, field: str) -> str:
        """Giá trị đã định dạng để hiển thị/điền vào tin nhắn (ngày dd/mm/yyyy, tiền 2.000.000)."""
        col = self._cols.get(field)
        if not col:
            return ""
        val = self.df.at[idx, col]
        if pd.isna(val):
            return ""
        val = str(val).strip()
        return FORMATTERS[field](val) if field in FORMATTERS else val

    def value(self, idx: int, name: str) -> str | None:
        """Giá trị của biến {name} cho dòng idx; None nếu file không có cột tương ứng."""
        field = field_for(name)
        if field:
            return self.field(idx, field) if self._cols.get(field) else None
        col = _norm(name)
        if col not in self.df.columns or col in APP_COLUMNS or col == self._cols.get('noidung'):
            return None
        val = self.df.at[idx, col]
        if pd.isna(val):
            return ""
        return format_date(re.sub(r'\.0$', '', str(val).strip()))   # số "12.0" -> "12", ngày -> dd/mm/yyyy

    def placeholder_chips(self) -> list[tuple[str, str]]:
        """(tên biến để chèn, nhãn nút) cho mọi cột thông tin khách trong file."""
        chips = [(f, PLACEHOLDER_LABELS[f]) for f in PLACEHOLDERS if self._cols.get(f)]
        mapped = set(self._cols.values())
        for col in self.df.columns:
            if col not in mapped and col not in APP_COLUMNS:
                chips.append((self._headers.get(col, col), self._headers.get(col, col)))
        return chips

    def phone(self, idx: int) -> str:
        return self.field(idx, 'sdt')

    def message(self, idx: int) -> str:
        """Nội dung gốc (chưa thay biến)."""
        return self.field(idx, 'noidung')

    def render_message(self, idx: int, text: str | None = None) -> str:
        """Nội dung sẽ gửi: thay {hoten}, {mahd}... và {tên cột bất kỳ} bằng dữ liệu của dòng."""
        text = self.message(idx) if text is None else text
        return fill_placeholders(text, lambda name: self.value(idx, name))

    def unresolved(self, idx: int) -> list[str]:
        """Các biến {…} trong nội dung dòng idx mà file không có cột tương ứng."""
        return [m.group(0) for m in PLACEHOLDER_RE.finditer(self.message(idx)) if self.value(idx, m.group(1)) is None]

    def set_message(self, idx: int, text: str):
        if not self._cols.get('noidung'):
            self.df['noidung'] = ""
            self._headers['noidung'] = 'Nội dung'
            self._cols['noidung'] = 'noidung'
        self.df.at[idx, self._cols['noidung']] = text

    def status(self, idx: int) -> str:
        if 'trangthai' in self.df.columns:
            val = self.df.at[idx, 'trangthai']
            return str(val).strip() if pd.notna(val) else cfg.STATUS_PENDING
        return cfg.STATUS_PENDING

    def set_status(self, idx: int, status: str):
        if self.loaded and 'trangthai' in self.df.columns:
            self.df.at[idx, 'trangthai'] = status

    def set_note(self, idx: int, note: str):
        if self.loaded:
            self.df.at[idx, 'thongbao'] = note

    def save(self, filepath: str | None = None) -> bool:
        """Trả về False nếu không ghi được (thường do file đang mở trong Excel)."""
        if not self.loaded:
            return False
        save_path = Path(filepath) if filepath else self.path
        try:
            self.df.rename(columns=self._headers).to_excel(save_path, index=False)
            return True
        except PermissionError:
            log.warning("Không lưu được %s (file đang mở trong Excel?)", save_path)
            return False
