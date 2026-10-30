"""Chạy tự động không cần giao diện, phù hợp đặt lịch (Task Scheduler / cron).

Ví dụ:
    python cli.py ds.xlsx
    python cli.py ds.xlsx --delay 20 --limit 50
    python cli.py ds.xlsx --account "Tài khoản 2"   (tên tab trong GUI)
Các dòng đã "Thành công" sẽ được bỏ qua, kết quả ghi ngược vào chính file Excel.
"""
import argparse
import logging

import accounts
import config as cfg
from data_store import ContactStore
from sender import BatchSender


def main():
    ap = argparse.ArgumentParser(description="Gửi tin Zalo từ file Excel")
    ap.add_argument("file", help="Đường dẫn file Excel")
    ap.add_argument("--delay", type=int, default=cfg.DEFAULT_DELAY, help="Giây giữa 2 tin")
    ap.add_argument("--limit", type=int, default=None, help="Tối đa số tin mỗi lần chạy")
    ap.add_argument("--account", default=None, help="Tên tài khoản (tên tab trong GUI), mặc định tài khoản đầu tiên")
    ap.add_argument("--max-per-hour", type=int, default=None,
                    help="Tối đa số tin trong 1 giờ (mặc định: giá trị đặt trên GUI của tài khoản)")
    ap.add_argument("--show", action="store_true", help="Hiện cửa sổ trình duyệt (mặc định chạy ẩn)")
    args = ap.parse_args()

    accs = accounts.load()
    account = accounts.find(accs, args.account) if args.account else accs[0]
    if account is None:
        ap.error(f"Không có tài khoản '{args.account}'. Có: " + ", ".join(a["name"] for a in accs))

    if args.delay < cfg.MIN_DELAY:
        ap.error(f"--delay phải >= {cfg.MIN_DELAY}")
    if args.max_per_hour is not None and args.max_per_hour < 1:
        ap.error("--max-per-hour phải >= 1")

    cfg.setup_logging(console=True)
    store = ContactStore()
    store.load(args.file)

    sender = BatchSender(
        store,
        on_status=lambda i, s: logging.info("Dòng %d: %s", i + 1, s),
        on_login_needed=lambda: print(f">> Quét QR đăng nhập Zalo ({account['name']}) trong cửa sổ trình duyệt..."),
        profile_dir=accounts.profile_dir(account),
        headless=not args.show,
        max_per_hour=args.max_per_hour or account.get("max_per_hour", cfg.DEFAULT_MAX_PER_HOUR),
        on_wait=lambda secs, remaining: print(f">> Đủ giới hạn tin/giờ, còn {remaining} người - gửi tiếp sau {int(secs)} giây...", end="\r"),
    )
    ok, fail = sender.run(store.indices(), args.delay, skip_done=True, limit=args.limit)
    print(f"Xong: {ok} thành công, {fail} thất bại. Kết quả đã ghi vào {store.path}")


if __name__ == "__main__":
    main()