"""Điểm khởi chạy duy nhất.

    python main.py                  -> mở giao diện (GUI)
    python main.py ds.xlsx          -> chạy tự động (CLI), bỏ qua dòng đã gửi
    python main.py ds.xlsx --delay 20 --limit 50
"""
import importlib.util
import sys

REQUIRED = {
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "playwright": "playwright",
    "customtkinter": "customtkinter",
}


def check_dependencies(need_gui: bool) -> bool:
    missing = [pip for mod, pip in REQUIRED.items()
               if (need_gui or mod != "customtkinter") and importlib.util.find_spec(mod) is None]
    if missing:
        print("Thiếu thư viện:", ", ".join(missing))
        print("Cài bằng: pip install -r requirements.txt")
        print("Sau đó:   playwright install chromium")
        return False
    return True


def main():
    # Task Scheduler / chuyển hướng ra file dùng cp1252 -> in tiếng Việt sẽ crash
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    use_cli = len(sys.argv) > 1   # có bất kỳ tham số nào (kể cả --delay đứng trước file) -> CLI

    if not check_dependencies(need_gui=not use_cli):
        sys.exit(1)

    if use_cli:
        import cli
        cli.main()
    else:
        import gui
        gui.main()


if __name__ == "__main__":
    main()