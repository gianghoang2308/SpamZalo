"""Mẫu nội dung tin nhắn (cột phải của GUI). Lưu ở templates.json, dùng chung cho mọi tài khoản."""
import json

import config as cfg

DEFAULT_TEMPLATES = [
    {"name": "Nhắc thanh toán",
     "text": "Kính gửi Quý khách {hoten},\n"
             "Hợp đồng {mahd} của Quý khách có khoản thanh toán {sotien} đồng đến hạn ngày {han}.\n"
             "Quý khách vui lòng thanh toán đúng hạn để tránh phát sinh phí phạt. Xin cảm ơn!"},
    {"name": "Sắp đến hạn",
     "text": "Chào anh/chị {hoten}, hợp đồng {mahd} sẽ đến hạn thanh toán vào ngày {han} "
             "với số tiền {sotien} đồng. Anh/chị vui lòng sắp xếp thanh toán đúng hạn nhé. Trân trọng!"},
    {"name": "Quá hạn",
     "text": "Kính gửi Quý khách {hoten},\n"
             "Hợp đồng {mahd} đã quá hạn thanh toán từ ngày {han}, số tiền cần thanh toán: {sotien} đồng.\n"
             "Đề nghị Quý khách thanh toán sớm hoặc liên hệ lại để được hỗ trợ."},
    {"name": "Cảm ơn đã thanh toán",
     "text": "Cảm ơn Quý khách {hoten} đã thanh toán hợp đồng {mahd}. Chúc Quý khách một ngày tốt lành!"},
]


def load() -> list[dict]:
    try:
        data = json.loads(cfg.TEMPLATES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (FileNotFoundError, ValueError):
        pass
    return [dict(t) for t in DEFAULT_TEMPLATES]


def save(templates: list[dict]) -> None:
    cfg.TEMPLATES_FILE.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8")
