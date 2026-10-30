"""Giao diện. Cột trái: danh sách tài khoản Zalo. Bên phải: mỗi tài khoản 1 tab riêng
(Excel, bảng, trình duyệt, luồng gửi riêng). Dữ liệu lấy từ ContactStore, không đọc ngược từ Treeview."""
import os
import random
import threading
from collections import Counter
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageDraw

import accounts
import config as cfg
import templates
from data_store import (PLACEHOLDER_LABELS, PLACEHOLDER_RE, ContactStore, fill_placeholders,
                        sample_value)
from sender import BatchSender, load_history
from zalo_client import ZaloClient

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

CHECKED, UNCHECKED = "☑", "☐"
AVATAR_SIZE = 44
COLOR_OK, COLOR_WARN, COLOR_ERR, COLOR_BUSY = "#2ecc71", "#e67e22", "#e74c3c", "#f1c40f"
BORDER_IDLE, BORDER_SELECTED = "#3a3a3a", "#1a73e8"

PREVIEW_CHARS = 28   # cột Nội dung chỉ hiện đoạn đầu, kích đúp để xem/sửa đầy đủ
PLACEHOLDER_HINT = "Gõ {tên cột Excel} để điền thông tin khách, ví dụ {hoten} {mahd} {địa chỉ}"
DEFAULT_CHIPS = list(PLACEHOLDER_LABELS.items())   # khi chưa import Excel
CHIPS_PER_ROW = 6

# (id, tiêu đề, độ rộng, căn lề)
COLUMNS = [
    ("check", "☑", 32, "center"),
    ("stt", "STT", 40, "center"),
    ("sdt", "SĐT", 100, "center"),
    ("hoten", "Họ tên", 150, "w"),
    ("mahd", "Mã hợp đồng", 110, "w"),
    ("han", "Hạn TT", 85, "center"),
    ("sotien", "Số tiền", 95, "e"),
    ("noidung", "Nội dung (kích đúp để sửa)", 200, "w"),
    ("trangthai", "Trạng thái", 105, "center"),
]


def preview(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= PREVIEW_CHARS else one_line[:PREVIEW_CHARS] + "…"


def round_avatar(path) -> ctk.CTkImage | None:
    try:
        img = Image.open(path).convert("RGBA").resize((AVATAR_SIZE * 2, AVATAR_SIZE * 2))
    except Exception:
        return None
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, *img.size), fill=255)
    img.putalpha(mask)
    return ctk.CTkImage(img, size=(AVATAR_SIZE, AVATAR_SIZE))


class TextDialog(ctk.CTkToplevel):
    """Popup soạn nội dung. Dùng cho sửa tin nhắn 1 dòng và nhập mẫu (có ô tên).
    resolve(tên biến) -> giá trị để xem trước, None nếu biến không khớp cột nào (tô đỏ).
    chips: [(tên biến, nhãn nút)] để chèn nhanh. on_save(name, text): name là None nếu không có ô tên."""

    def __init__(self, master, title: str, header: str, text: str, on_save, resolve,
                 chips: list[tuple[str, str]], preview_label: str,
                 name: str | None = None, readonly: bool = False, templates_list: list[dict] | None = None):
        super().__init__(master)
        self.title(title)
        self.geometry("720x640")
        self.transient(master.winfo_toplevel())
        self.after(100, self._focus)   # CTkToplevel trên Windows cần trễ mới grab/focus được
        self.on_save = on_save
        self.resolve = resolve

        if header:
            ctk.CTkLabel(self, text=header, justify="left", anchor="w").pack(fill="x", padx=15, pady=(12, 4))
        self.name_entry = None
        if name is not None:
            ctk.CTkLabel(self, text="Tên mẫu:", anchor="w").pack(fill="x", padx=15, pady=(8, 0))
            self.name_entry = ctk.CTkEntry(self)
            self.name_entry.insert(0, name)
            self.name_entry.pack(fill="x", padx=15, pady=(2, 6))
        # Nút chèn biến: bấm là chèn {hoten}... vào vị trí con trỏ, khi gửi tự thay bằng dữ liệu khách
        if templates_list and not readonly:   # lấy nhanh 1 mẫu làm nội dung riêng cho khách này
            by_name = {t["name"]: t["text"] for t in templates_list}
            pick = ctk.CTkFrame(self, fg_color="transparent")
            pick.pack(fill="x", padx=15, pady=(6, 0))
            ctk.CTkLabel(pick, text="Dùng mẫu:", text_color="gray").pack(side="left", padx=(0, 6))
            ctk.CTkOptionMenu(pick, values=list(by_name), width=260,
                              variable=ctk.StringVar(value="— Chọn mẫu —"),
                              command=lambda n: self._set_text(by_name[n])).pack(side="left")
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="x", padx=15, pady=(6, 0))
        ctk.CTkLabel(box, text="Chèn:", text_color="gray").grid(row=0, column=0, padx=(0, 4), sticky="w")
        for i, (key, label) in enumerate(chips):
            ctk.CTkButton(box, text=f"+ {label}", width=40, height=26, fg_color="#1f4e79", hover_color="#2a6aa5",
                          font=ctk.CTkFont(size=12), state="disabled" if readonly else "normal",
                          command=lambda k=key: self._insert_placeholder(k)
                          ).grid(row=i // CHIPS_PER_ROW, column=1 + i % CHIPS_PER_ROW, padx=2, pady=2, sticky="ew")
        ctk.CTkLabel(self, text=PLACEHOLDER_HINT + "\n(chữ xanh = đã nối dữ liệu khách, chữ đỏ = file không có cột này)",
                     text_color="gray", font=ctk.CTkFont(size=11), anchor="w", justify="left").pack(fill="x", padx=15)
        self.txt = ctk.CTkTextbox(self, wrap="word", height=160)
        self.txt.pack(fill="both", expand=True, padx=15, pady=4)
        self.txt.insert("1.0", text)
        self.txt.tag_config("ph", foreground="#5dade2")
        self.txt.tag_config("ph_bad", foreground="#ff6b6b")
        self.txt.bind("<KeyRelease>", lambda e: self._refresh())

        ctk.CTkLabel(self, text=preview_label, anchor="w", text_color="gray").pack(fill="x", padx=15)
        self.preview = ctk.CTkTextbox(self, wrap="word", height=130, fg_color="#1f1f1f")
        self.preview.pack(fill="both", expand=True, padx=15, pady=4)
        self._refresh()

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=10)
        ctk.CTkButton(row, text="Hủy", width=90, fg_color="#7f8c8d", hover_color="#95a5a6",
                      command=self.destroy).pack(side="right", padx=(5, 0))
        if readonly:
            self.txt.configure(state="disabled")
            ctk.CTkLabel(row, text="Đang gửi tin - chỉ xem, không sửa được", text_color=COLOR_WARN).pack(side="left")
        else:
            ctk.CTkButton(row, text="Lưu", width=90, fg_color="#27ae60", hover_color="#2ecc71",
                          command=self._save).pack(side="right")

    def _focus(self):
        self.grab_set()
        self.lift()
        (self.name_entry or self.txt).focus_set()

    def _text(self) -> str:
        return self.txt.get("1.0", "end-1c").strip()

    def _set_text(self, text: str):
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        self._refresh()

    def _insert_placeholder(self, key: str):
        self.txt.insert("insert", "{%s}" % key)
        self.txt.focus_set()
        self._refresh()

    def _refresh(self):
        """Tô màu các biến {…} và cập nhật ô xem trước."""
        for tag in ("ph", "ph_bad"):
            self.txt.tag_remove(tag, "1.0", "end")
        content = self.txt.get("1.0", "end-1c")
        for m in PLACEHOLDER_RE.finditer(content):
            tag = "ph" if self.resolve(m.group(1)) is not None else "ph_bad"
            self.txt.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        self._update_preview()

    def _update_preview(self):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", fill_placeholders(self._text(), self.resolve))
        self.preview.configure(state="disabled")

    def _save(self):
        text = self._text()
        name = self.name_entry.get().strip() if self.name_entry else None
        if not text or (self.name_entry and not name):
            messagebox.showwarning("Cảnh báo", "Chưa nhập đủ nội dung", parent=self)
            return
        self.on_save(name, text)
        self.destroy()


class AccountTab(ctk.CTkFrame):
    """Toàn bộ chức năng gửi tin cho 1 tài khoản Zalo."""

    def __init__(self, master, app: "ZaloSenderApp", account: dict):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.account = account
        self.store = ContactStore()
        self.sender: BatchSender | None = None
        self.is_running = False   # đang gửi / đăng nhập / kiểm tra (trình duyệt đang giữ profile)
        self.state_text, self.state_color = "", "gray"

        self._build_top()
        self._build_table()
        self._build_bottom()

    @property
    def name(self) -> str:
        return self.account["name"]

    # ================== DỰNG GIAO DIỆN ==================
    def _build_top(self):
        f = ctk.CTkFrame(self)
        f.pack(fill="x", padx=5, pady=(0, 8))
        self.btn_import = ctk.CTkButton(f, text="Import Excel", width=120, command=self.import_excel)
        self.btn_import.pack(side="left", padx=5)
        self.lbl_file = ctk.CTkLabel(f, text="Chưa chọn file Excel", text_color="gray")
        self.lbl_file.pack(side="left", padx=10)
        self.lbl_status = ctk.CTkLabel(f, text="Sẵn sàng", text_color="gray")
        self.lbl_status.pack(side="left", padx=15)
        ctk.CTkButton(f, text="Xuất Excel", width=100, command=self.export_excel).pack(side="right", padx=5)
        self.btn_logout = ctk.CTkButton(f, text="Đăng xuất", width=100, fg_color="#7f8c8d",
                                        hover_color="#95a5a6", command=self.logout)
        self.btn_logout.pack(side="right", padx=5)
        self.btn_login = ctk.CTkButton(f, text="Đăng nhập Zalo", width=130, fg_color="#8e44ad",
                                       hover_color="#9b59b6", command=self.login)
        self.btn_login.pack(side="right", padx=5)

    def _build_table(self):
        f = ctk.CTkFrame(self)
        f.pack(fill="both", expand=True, padx=5, pady=5)

        ids = [c[0] for c in COLUMNS]
        self.tree = ttk.Treeview(f, columns=ids, show="headings", selectmode="extended")
        for cid, title, width, anchor in COLUMNS:
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=width, anchor=anchor)

        sy = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(f, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        f.grid_rowconfigure(0, weight=1)
        f.grid_columnconfigure(0, weight=1)

        self.tree.bind("<Button-1>", self.on_click_check)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.app.on_customer_change())

    def _build_bottom(self):
        f = ctk.CTkFrame(self)
        f.pack(fill="x", padx=5, pady=8)
        ctk.CTkButton(f, text="Chọn tất cả", width=100, command=lambda: self._set_all(CHECKED)).pack(side="left", padx=5)
        ctk.CTkButton(f, text="Bỏ chọn", width=90, command=lambda: self._set_all(UNCHECKED)).pack(side="left", padx=5)

        ctk.CTkLabel(f, text="Khoảng cách (giây):").pack(side="left", padx=(20, 5))
        self.delay_var = ctk.StringVar(value=str(cfg.DEFAULT_DELAY))
        ctk.CTkEntry(f, width=60, textvariable=self.delay_var).pack(side="left")

        self.headless_var = ctk.BooleanVar(value=self.account.get("headless", cfg.DEFAULT_HEADLESS))
        ctk.CTkCheckBox(f, text="Chạy ẩn", variable=self.headless_var,
                        command=self._save_headless).pack(side="left", padx=(20, 5))

        self.btn_stop = ctk.CTkButton(f, text="Dừng", width=90, fg_color="#c0392b",
                                      hover_color="#e74c3c", state="disabled", command=self.stop_sending)
        self.btn_stop.pack(side="right", padx=5)
        self.btn_start = ctk.CTkButton(f, text="Gửi Zalo", width=110, fg_color="#27ae60",
                                       hover_color="#2ecc71", command=self.start_sending)
        self.btn_start.pack(side="right", padx=5)

        # Giới hạn số tin / giờ (BatchSender đếm tin thành công trong 60 phút gần nhất, đủ thì tự chờ)
        red_bold = dict(text_color=COLOR_ERR, font=ctk.CTkFont(size=14, weight="bold"))
        r = ctk.CTkFrame(self, fg_color="transparent")
        r.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(r, text="⚠ TỐI ĐA GỬI", **red_bold).pack(side="left")
        self.max_var = ctk.StringVar(value=str(self.account.get("max_per_hour", cfg.DEFAULT_MAX_PER_HOUR)))
        self.entry_max = ctk.CTkEntry(r, width=60, textvariable=self.max_var, justify="center",
                                      border_color=COLOR_ERR, **red_bold)
        self.entry_max.pack(side="left", padx=6)
        self.entry_max.bind("<FocusOut>", lambda e: self._read_max_per_hour(quiet=True))
        self.entry_max.bind("<Return>", lambda e: self._read_max_per_hour(quiet=True))
        ctk.CTkLabel(r, text="TIN NHẮN TRONG 1 GIỜ", **red_bold).pack(side="left")
        ctk.CTkLabel(r, text="(đủ số tin sẽ tự dừng chờ, hết 1 giờ tự gửi tiếp)",
                     text_color="gray", font=ctk.CTkFont(size=12)).pack(side="left", padx=10)
        self.lbl_quota = ctk.CTkLabel(r, text="", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_quota.pack(side="right", padx=5)
        self._show_quota(len(load_history(accounts.profile_dir(self.account))))

    def _read_max_per_hour(self, quiet: bool = False) -> int | None:
        """Đọc + lưu giới hạn tin/giờ của tài khoản. Sai thì báo lỗi (hoặc trả ô về giá trị cũ nếu quiet)."""
        old = self.account.get("max_per_hour", cfg.DEFAULT_MAX_PER_HOUR)
        try:
            value = int(self.max_var.get().strip())
            if value < 1:
                raise ValueError
        except ValueError:
            if quiet:
                self.max_var.set(str(old))
            else:
                messagebox.showerror("Lỗi", "Số tin tối đa trong 1 giờ phải là số nguyên ≥ 1")
            return None
        if value != old:
            self.account["max_per_hour"] = value
            accounts.save(self.app.accounts)
        self._show_quota(len(load_history(accounts.profile_dir(self.account))))
        return value

    def _show_quota(self, sent: int):
        limit = self.account.get("max_per_hour", cfg.DEFAULT_MAX_PER_HOUR)
        self.lbl_quota.configure(text=f"1 giờ qua đã gửi: {sent}/{limit} tin",
                                 text_color=COLOR_ERR if sent >= limit else COLOR_OK)

    def _show_waiting(self, seconds: float, remaining: int):
        m, s = divmod(int(seconds) + 1, 60)
        limit = self.sender.max_per_hour if self.sender else ""
        self._status(f"Đủ {limit} tin/giờ - còn {remaining} người, gửi đợt tiếp sau {m:02d}:{s:02d}", COLOR_ERR)

    # ================== BẢNG ==================
    def _populate(self):
        self.tree.delete(*self.tree.get_children())
        for idx in self.store.indices():
            f = self.store.field
            self.tree.insert("", "end", iid=str(idx), values=(
                CHECKED, idx + 1, f(idx, "sdt"), f(idx, "hoten"), f(idx, "mahd"),
                f(idx, "han"), f(idx, "sotien"), preview(self.store.message(idx)), self.store.status(idx),
            ))
        first = self.tree.get_children()
        if first:   # chọn sẵn khách đầu tiên để cột mẫu tin nhắn hiện nội dung đã điền
            self.tree.selection_set(first[0])
            self.tree.focus(first[0])
        self.app.on_customer_change()

    def on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item or self.tree.identify_column(event.x) == "#1":   # cột tích chọn: chỉ tích/bỏ tích
            return
        idx = int(item)
        f = self.store.field
        info = (f"Khách hàng: {f(idx, 'hoten') or '-'}    SĐT: {f(idx, 'sdt') or '-'}\n"
                f"Mã HĐ: {f(idx, 'mahd') or '-'}    Hạn TT: {f(idx, 'han') or '-'}    Số tiền: {f(idx, 'sotien') or '-'}")
        TextDialog(self, f"Nội dung tin nhắn - dòng {idx + 1}", info, self.store.message(idx),
                   on_save=lambda _name, text: self._save_messages([idx], text),
                   resolve=lambda name: self.store.value(idx, name), chips=self.store.placeholder_chips(),
                   preview_label="Xem trước tin sẽ gửi:",
                   templates_list=self.app.template_panel.templates,
                   readonly=self.is_running)

    def apply_template(self, name: str, text: str):
        """Gán mẫu cho khách đang chọn (dòng tô xanh; Ctrl/Shift để chọn nhiều).
        Ô ☑ chỉ quyết định ai được gửi, không liên quan tới mẫu."""
        if not self.store.loaded:
            messagebox.showwarning("Cảnh báo", f"[{self.name}] Chưa import file Excel")
            return
        if self.is_running:
            messagebox.showwarning("Cảnh báo", f"[{self.name}] Đang chạy, hãy dừng trước khi đổi nội dung")
            return
        rows = [int(i) for i in self.tree.selection()]
        if not rows:
            messagebox.showwarning("Cảnh báo", "Bấm chọn 1 khách trong bảng trước (Ctrl/Shift để chọn nhiều khách)")
            return
        if len(rows) > 1 and not messagebox.askyesno(
                "Áp dụng mẫu", f"Áp dụng mẫu \"{name}\" cho {len(rows)} khách đang chọn?"):
            return
        self._save_messages(rows, text)
        who = self.store.field(rows[0], "hoten") if len(rows) == 1 else f"{len(rows)} khách"
        self._status(f"Đã áp dụng mẫu \"{name}\" cho {who}", COLOR_OK)
        if len(rows) == 1:   # chuyển sang khách kế tiếp để chọn mẫu cho từng người liên tục
            nxt = self.tree.next(str(rows[0]))
            if nxt:
                self.tree.selection_set(nxt)
                self.tree.focus(nxt)
                self.tree.see(nxt)

    def random_templates(self, templates_list: list[dict]):
        """Mỗi người nhận (dòng đang tích ☑) được gán ngẫu nhiên 1 mẫu."""
        if not self.store.loaded:
            messagebox.showwarning("Cảnh báo", f"[{self.name}] Chưa import file Excel")
            return
        if self.is_running:
            messagebox.showwarning("Cảnh báo", f"[{self.name}] Đang chạy, hãy dừng trước khi đổi nội dung")
            return
        if not templates_list:
            messagebox.showwarning("Cảnh báo", "Chưa có mẫu nào")
            return
        rows = self._selected_indices()
        if not rows:
            messagebox.showwarning("Cảnh báo", "Chưa tích ☑ người nhận nào")
            return
        if not messagebox.askyesno("Random mẫu", f"Gán ngẫu nhiên 1 trong {len(templates_list)} mẫu cho "
                                                 f"{len(rows)} người nhận đã tích ở \"{self.name}\"?\n"
                                                 "Nội dung hiện tại của các dòng này sẽ bị thay."):
            return
        picks = {idx: random.choice(templates_list) for idx in rows}
        self._save_messages(rows, {idx: t["text"] for idx, t in picks.items()})
        counts = Counter(t["name"] for t in picks.values())
        self._status("Random: " + ", ".join(f"{n} ×{c}" for n, c in counts.most_common()), COLOR_OK)
        self.app.on_customer_change()

    def _save_messages(self, rows: list[int], text: str | dict[int, str]):
        """text: 1 nội dung cho mọi dòng, hoặc dict {dòng: nội dung riêng}."""
        for idx in rows:
            msg = text[idx] if isinstance(text, dict) else text
            self.store.set_message(idx, msg)
            self.tree.set(str(idx), "noidung", preview(msg))
        if self.store.save():
            self._status(f"Đã lưu nội dung {len(rows)} dòng", COLOR_OK)
        else:
            messagebox.showwarning("Chưa lưu vào file",
                                   "Không ghi được file Excel (đang mở trong Excel?).\n"
                                   "Nội dung mới vẫn được dùng khi gửi; đóng Excel rồi bấm Xuất Excel để lưu.")

    def on_click_check(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if item:
            cur = self.tree.set(item, "check")
            self.tree.set(item, "check", UNCHECKED if cur == CHECKED else CHECKED)

    def _set_all(self, mark):
        for item in self.tree.get_children():
            self.tree.set(item, "check", mark)

    def _selected_indices(self) -> list[int]:
        return [int(i) for i in self.tree.get_children() if self.tree.set(i, "check") == CHECKED]

    # ================== IMPORT / EXPORT ==================
    def import_excel(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not path:
            return
        other = self.app.tab_using_file(path, exclude=self)
        if other and not messagebox.askyesno(
                "Cảnh báo", f"File này đang mở ở tab \"{other.name}\".\n"
                            "Hai tab cùng ghi 1 file sẽ ghi đè trạng thái của nhau. Vẫn mở?"):
            return
        try:
            self.store.load(path)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không đọc được file Excel:\n{e}")
            return
        self._populate()
        self.lbl_file.configure(text=f"Excel: {os.path.basename(path)} ({len(self.store)} dòng)")
        self._status(f"Đã tải {len(self.store)} dòng", COLOR_OK)

    def export_excel(self):
        if not self.store.loaded:
            messagebox.showwarning("Cảnh báo", "Không có dữ liệu để xuất")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if path:
            self.store.save(path)
            messagebox.showinfo("Thành công", f"Đã xuất file:\n{path}")

    # ================== ĐĂNG NHẬP / THÔNG TIN TÀI KHOẢN ==================
    def login(self, on_done=None):
        """Kiểm tra ngầm trước; chưa đăng nhập thì hiện trình duyệt để quét QR. Xong tự đóng, phiên được lưu.
        on_done(): gọi khi xong (dù thành công hay không) - dùng cho "Đăng nhập tất cả"."""
        self._on_login_done = on_done
        self._set_running(True)
        self._status("Đang mở Zalo...", COLOR_BUSY)
        threading.Thread(target=self._login_worker, args=(False,), daemon=True).start()

    def check_login(self, on_done=None):
        """Chỉ kiểm tra ngầm (không bao giờ hiện trình duyệt) để cập nhật tên/ảnh ở cột trái."""
        self._on_login_done = on_done
        self._set_running(True)
        self._status("Đang kiểm tra...", COLOR_BUSY)
        threading.Thread(target=self._login_worker, args=(True,), daemon=True).start()

    def _login_worker(self, check_only: bool):
        # Chưa từng đăng nhập thì mở thẳng cửa sổ QR, khỏi chờ kiểm tra ngầm 30 giây
        headless = check_only or bool(self.account.get("zalo_name"))
        try:
            with ZaloClient(accounts.profile_dir(self.account), headless=headless) as client:
                if check_only:
                    if not client.open_zalo():
                        self.after(0, self._mark_logged_out)
                        return
                else:
                    client.open_and_login(lambda: self.after(0, self._need_login))
                info = client.get_profile()
            self.after(0, self._apply_profile, info, not check_only)
        except Exception as e:
            if not check_only:
                self.after(0, lambda: messagebox.showerror("Lỗi", f"[{self.name}] {e}"))
            self.after(0, self._status, "Đăng nhập thất bại" if not check_only else "Không kiểm tra được", COLOR_ERR)
        finally:
            self.after(0, self._login_finished)

    def _login_finished(self):
        self._set_running(False)
        callback, self._on_login_done = getattr(self, "_on_login_done", None), None
        if callback:
            callback()

    def _apply_profile(self, info: dict, announce: bool = False):
        if not info:
            return
        accounts.apply_profile(self.account, info)
        accounts.save(self.app.accounts)
        self._status(f"Đã đăng nhập: {self.account['zalo_name']}", COLOR_OK)
        self.app.refresh_card(self)
        dup = self.app.tab_with_uid(self.account.get("uid"), exclude=self)
        if dup:
            messagebox.showwarning(
                "Trùng tài khoản",
                f"\"{self.name}\" và \"{dup.name}\" đang đăng nhập CÙNG 1 Zalo ({self.account['zalo_name']}).\n"
                f"Hãy bấm Đăng xuất ở 1 tab rồi đăng nhập lại bằng tài khoản Zalo khác.")
        elif announce:
            messagebox.showinfo("Đăng nhập", f"[{self.name}] Đã đăng nhập Zalo: {self.account['zalo_name']}")

    def _mark_logged_out(self):
        accounts.clear_profile(self.account)
        accounts.save(self.app.accounts)
        self._status("Chưa đăng nhập", "gray")

    def logout(self):
        """Xóa phiên đăng nhập đã lưu của tài khoản này (giữ lại tab), lần sau phải quét QR lại."""
        if not messagebox.askyesno("Đăng xuất", f"Đăng xuất Zalo của \"{self.name}\"?\n"
                                                "Lần gửi sau sẽ phải quét QR lại."):
            return
        accounts.delete_profile(self.account)
        accounts.save(self.app.accounts)
        self._status("Đã đăng xuất", "gray")

    # ================== GỬI TIN ==================
    def start_sending(self):
        selected = self._selected_indices()
        if not selected:
            messagebox.showwarning("Cảnh báo", "Chưa chọn dòng nào để gửi")
            return
        try:
            delay = int(self.delay_var.get())
        except ValueError:
            messagebox.showerror("Lỗi", "Delay phải là số nguyên")
            return
        if delay < cfg.MIN_DELAY:
            messagebox.showwarning("Cảnh báo", f"Delay nên >= {cfg.MIN_DELAY} giây")
            return
        max_per_hour = self._read_max_per_hour()
        if max_per_hour is None:
            return
        bad ={idx + 1: self.store.unresolved(idx) for idx in selected}
        bad = {row: names for row, names in bad.items() if names}
        if bad:
            lines = "\n".join(f"  Dòng {row}: {' '.join(names)}" for row, names in list(bad.items())[:8])
            more = f"\n  ... và {len(bad) - 8} dòng khác" if len(bad) > 8 else ""
            if not messagebox.askyesno("Biến chưa nối dữ liệu",
                                       f"Nội dung có biến mà file Excel không có cột tương ứng:\n{lines}{more}\n\n"
                                       "Khách sẽ nhận nguyên chữ {…}. Vẫn gửi?"):
                return

        self.sender = BatchSender(
            self.store,
            on_status=lambda i, s: self.after(0, self._row_status, i, s),
            on_login_needed=lambda: self.after(0, self._need_login),
            on_profile=lambda info: self.after(0, self._apply_profile, info),
            profile_dir=accounts.profile_dir(self.account),
            headless=self.headless_var.get(),
            max_per_hour=max_per_hour,
            on_quota=lambda sent: self.after(0, self._show_quota, sent),
            on_wait=lambda secs, remaining: self.after(0, self._show_waiting, secs, remaining),
        )
        self._set_running(True)
        self._status("Đang gửi...", COLOR_BUSY)
        threading.Thread(target=self._worker, args=(selected, delay), daemon=True).start()

    def _worker(self, selected, delay):
        try:
            ok, fail = self.sender.run(selected, delay, skip_done=False)
            self.after(0, self._status, f"Hoàn thành: {ok} thành công, {fail} thất bại",
                       COLOR_OK if fail == 0 else COLOR_WARN)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Lỗi", f"[{self.name}] {e}"))
            self.after(0, self._status, "Lỗi kết nối", COLOR_ERR)
        finally:
            self.after(0, self._set_running, False)

    def stop_sending(self):
        if self.sender:
            self.sender.stop()
        self._status("Đang dừng...", COLOR_WARN)

    # ================== CALLBACK TỪ THREAD (đã qua self.after) ==================
    def _row_status(self, idx, status):
        iid = str(idx)
        if self.tree.exists(iid):
            self.tree.set(iid, "trangthai", status)

    def _need_login(self):
        self._status("Chờ quét QR trong trình duyệt", COLOR_ERR)
        self.app.select(self)
        messagebox.showinfo("Đăng nhập", f"[{self.name}] Hãy quét QR đăng nhập Zalo trong cửa sổ trình duyệt vừa mở.\n"
                                         "Chương trình sẽ tự chạy tiếp sau khi đăng nhập xong.")

    # ================== TIỆN ÍCH ==================
    def _save_headless(self):
        self.account["headless"] = self.headless_var.get()
        accounts.save(self.app.accounts)

    def _status(self, text, color="gray"):
        self.state_text, self.state_color = text, color
        self.lbl_status.configure(text=text, text_color=color)
        self.app.refresh_card(self)

    def _set_running(self, running: bool):
        self.is_running = running
        state = "disabled" if running else "normal"
        self.btn_start.configure(state=state)
        self.btn_import.configure(state=state)
        self.btn_login.configure(state=state)
        self.btn_logout.configure(state=state)   # trình duyệt đang mở thì profile bị khóa, không xóa được
        self.entry_max.configure(state=state)    # giới hạn tin/giờ cố định trong suốt lượt gửi
        # Nút Dừng chỉ có tác dụng khi đang gửi (đăng nhập thì đóng trình duyệt để hủy)
        self.btn_stop.configure(state="normal" if running and self.sender else "disabled")
        if not running:
            self.sender = None
        self.app.refresh_card(self)


class AccountCard(ctk.CTkFrame):
    """1 dòng ở cột trái: ảnh đại diện, tên tab, tên Zalo, trạng thái. Bấm vào để chuyển tab."""

    def __init__(self, master, tab: AccountTab):
        super().__init__(master, corner_radius=8, border_width=2, border_color=BORDER_IDLE)
        self.tab = tab
        self.grid_columnconfigure(1, weight=1)
        self.lbl_avatar = None
        self.lbl_title = ctk.CTkLabel(self, font=ctk.CTkFont(weight="bold"), anchor="w")
        self.lbl_zalo = ctk.CTkLabel(self, anchor="w", font=ctk.CTkFont(size=12))
        self.lbl_state = ctk.CTkLabel(self, anchor="w", font=ctk.CTkFont(size=11))
        self.lbl_title.grid(row=0, column=1, sticky="ew", padx=(8, 6), pady=(6, 0))
        self.lbl_zalo.grid(row=1, column=1, sticky="ew", padx=(8, 6))
        self.lbl_state.grid(row=2, column=1, sticky="ew", padx=(8, 6), pady=(0, 6))
        self._avatar_key = None
        for w in (self, self.lbl_title, self.lbl_zalo, self.lbl_state):
            self._bind_click(w)
        self.refresh()

    def _bind_click(self, widget):
        widget.bind("<Button-1>", lambda e: self.tab.app.select(self.tab))

    def _set_avatar(self):
        acc = self.tab.account
        path = accounts.avatar_path(acc)
        key = (acc.get("zalo_name"), path.stat().st_mtime if path.exists() else None)
        if key == self._avatar_key:
            return
        self._avatar_key = key
        if self.lbl_avatar:
            self.lbl_avatar.destroy()
        image = round_avatar(path) if path.exists() and acc.get("zalo_name") else None
        if image:
            self.lbl_avatar = ctk.CTkLabel(self, image=image, text="")
        else:   # chưa có ảnh: vòng tròn chữ cái đầu
            initial = (acc.get("zalo_name") or acc["name"]).strip()[:1].upper() or "?"
            self.lbl_avatar = ctk.CTkLabel(self, text=initial, width=AVATAR_SIZE, height=AVATAR_SIZE,
                                           corner_radius=AVATAR_SIZE // 2, fg_color="#34495e",
                                           font=ctk.CTkFont(size=18, weight="bold"))
        self.lbl_avatar.grid(row=0, column=0, rowspan=3, padx=(8, 0), pady=6)
        self._bind_click(self.lbl_avatar)

    def refresh(self, selected: bool = False):
        tab, acc = self.tab, self.tab.account
        self._set_avatar()
        self.lbl_title.configure(text=acc["name"])
        zalo = acc.get("zalo_name")
        self.lbl_zalo.configure(text=zalo or "Chưa đăng nhập", text_color="white" if zalo else "gray")
        if tab.is_running and tab.state_text:
            state, color = tab.state_text, tab.state_color
        elif zalo:
            state, color = "● Đã đăng nhập", COLOR_OK
        else:
            state, color = "○ Chưa đăng nhập", "gray"
        self.lbl_state.configure(text=state, text_color=color)
        self.configure(border_color=BORDER_SELECTED if selected else BORDER_IDLE)


class TemplatePanel(ctk.CTkFrame):
    """Cột phải: mẫu nội dung tin nhắn - sao chép, áp dụng cho dòng đã tích, thêm/sửa/xóa."""

    def __init__(self, master, app: "ZaloSenderApp"):
        super().__init__(master, width=290)
        self.pack_propagate(False)
        self.app = app
        self.templates = templates.load()

        ctk.CTkLabel(self, text="Mẫu tin nhắn", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(10, 0))
        ctk.CTkLabel(self, text=PLACEHOLDER_HINT, text_color="gray", font=ctk.CTkFont(size=11),
                     wraplength=260).pack(padx=8, pady=(0, 5))
        self.lbl_customer = ctk.CTkLabel(self, text="", wraplength=260, justify="left", anchor="w",
                                         font=ctk.CTkFont(size=12))
        self.lbl_customer.pack(fill="x", padx=10, pady=(0, 5))
        self.bodies: list[tuple[ctk.CTkLabel, dict]] = []
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=5)
        ctk.CTkButton(self, text="+ Nhập mẫu mới", command=self.add).pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkButton(self, text="🎲 Random mẫu cho người nhận", fg_color="#d35400", hover_color="#e67e22",
                      command=lambda: self.app.current_tab().random_templates(self.templates)
                      ).pack(fill="x", padx=10, pady=(4, 10))
        self.render()

    def render(self):
        for w in self.list.winfo_children():
            w.destroy()
        self.bodies = []
        for i, t in enumerate(self.templates):
            card = ctk.CTkFrame(self.list, corner_radius=8, border_width=1, border_color=BORDER_IDLE)
            card.pack(fill="x", pady=4)
            ctk.CTkLabel(card, text=t["name"], font=ctk.CTkFont(weight="bold"), anchor="w").pack(fill="x", padx=8, pady=(6, 0))
            body = ctk.CTkLabel(card, anchor="w", justify="left", wraplength=235, font=ctk.CTkFont(size=12))
            body.pack(fill="x", padx=8)
            self.bodies.append((body, t))
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=6)
            for text, color, cmd in (("Sao chép", "#1f6aa5", self.copy), ("Áp dụng", "#27ae60", self.apply),
                                     ("Sửa", "#34495e", self.edit), ("Xóa", "#7f8c8d", self.remove)):
                ctk.CTkButton(row, text=text, width=52, height=26, fg_color=color, font=ctk.CTkFont(size=12),
                              command=lambda c=cmd, n=i: c(n)).pack(side="left", padx=2, expand=True, fill="x")
        self.update_customer()

    def _filled(self, text: str) -> str:
        """Mẫu đã điền thông tin khách đang chọn; chưa chọn khách thì giữ nguyên {…}."""
        row = self.app.selected_customer()
        if not row:
            return text
        tab, idx = row
        return tab.store.render_message(idx, text)

    def update_customer(self):
        row = self.app.selected_customer()
        if row:
            tab, idx = row
            f = tab.store.field
            self.lbl_customer.configure(
                text=f"Khách đang chọn (dòng {idx + 1}): {f(idx, 'hoten') or '-'}\n"
                     f"HĐ {f(idx, 'mahd') or '-'} · {f(idx, 'sotien') or '-'}đ · hạn {f(idx, 'han') or '-'}",
                text_color=COLOR_OK)
        else:
            self.lbl_customer.configure(text="Chưa chọn khách - bấm vào 1 dòng trong bảng để điền thông tin vào mẫu",
                                        text_color=COLOR_WARN)
        for label, t in self.bodies:
            text = self._filled(t["text"])
            label.configure(text=text if len(text) <= 220 else text[:220] + "…",
                            text_color="white" if row else "#cfcfcf")

    def _save(self):
        templates.save(self.templates)
        self.render()

    def copy(self, i: int):
        t = self.templates[i]
        self.clipboard_clear()
        self.clipboard_append(self._filled(t["text"]))
        row = self.app.selected_customer()
        who = f" cho {row[0].store.field(row[1], 'hoten')}" if row else ""
        self.app.flash(f"Đã sao chép mẫu \"{t['name']}\"{who}")

    def apply(self, i: int):
        self.app.current_tab().apply_template(self.templates[i]["name"], self.templates[i]["text"])

    def add(self):
        TextDialog(self, "Nhập mẫu mới", "", "", name=f"Mẫu {len(self.templates) + 1}",
                   **self.app.template_context(),
                   on_save=lambda name, text: (self.templates.append({"name": name, "text": text}), self._save()))

    def edit(self, i: int):
        t = self.templates[i]
        TextDialog(self, "Sửa mẫu", "", t["text"], name=t["name"], **self.app.template_context(),
                   on_save=lambda name, text: (t.update(name=name, text=text), self._save()))

    def remove(self, i: int):
        if messagebox.askyesno("Xóa mẫu", f"Xóa mẫu \"{self.templates[i]['name']}\"?"):
            del self.templates[i]
            self._save()


class ZaloSenderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Zalo Sender - Pro Connect")
        self.geometry("1680x800")
        self.minsize(1450, 680)

        self._setup_style()
        self.accounts = accounts.load()
        self.tabs: dict[str, AccountTab] = {}
        self.cards: dict[int, AccountCard] = {}   # id(tab) -> card

        self._build_sidebar()
        self.template_panel = TemplatePanel(self, self)
        self.template_panel.pack(side="right", fill="y", padx=(0, 10), pady=8)
        self.tabview = ctk.CTkTabview(self, command=self._on_tab_change)
        self.tabview.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=8)
        for acc in self.accounts:
            self._add_tab(acc)
        self._on_tab_change()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Tài khoản đã có phiên lưu -> kiểm tra ngầm để hiện tên/ảnh Zalo ở cột trái
        self.after(500, self.check_all)

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", rowheight=28)
        style.configure("Treeview.Heading", background="#1f1f1f", foreground="white", relief="flat")
        style.map("Treeview", background=[("selected", "#1a73e8")])

    def _build_sidebar(self):
        f = ctk.CTkFrame(self, width=250)
        f.pack(side="left", fill="y", padx=10, pady=8)
        f.pack_propagate(False)
        ctk.CTkLabel(f, text="Tài khoản Zalo", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(10, 5))
        self.card_list = ctk.CTkScrollableFrame(f, fg_color="transparent")
        self.card_list.pack(fill="both", expand=True, padx=5)

        ctk.CTkButton(f, text="+ Thêm tài khoản", command=self.add_account).pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkButton(f, text="Đăng nhập tất cả", fg_color="#8e44ad", hover_color="#9b59b6",
                      command=self.login_all).pack(fill="x", padx=10, pady=4)
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(row, text="Đổi tên", width=70, command=self.rename_account).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(row, text="Xóa", width=70, fg_color="#7f8c8d", hover_color="#95a5a6",
                      command=self.remove_account).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(row, text="Làm mới", width=70, fg_color="#34495e", hover_color="#4a6278",
                      command=self.check_all).pack(side="left", expand=True, fill="x", padx=(3, 0))
        ctk.CTkLabel(f, text="Thêm tài khoản → quét QR bằng\nđiện thoại của tài khoản Zalo mới",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(pady=(4, 10))

    # ================== CỘT TRÁI ==================
    def refresh_card(self, tab: AccountTab):
        card = self.cards.get(id(tab))
        if card:
            card.refresh(selected=self.tabview.get() == tab.name)

    def _on_tab_change(self):
        for tab in self.tabs.values():
            self.refresh_card(tab)
        self.on_customer_change()

    def selected_customer(self) -> tuple[AccountTab, int] | None:
        """Khách đang được chọn (dòng tô xanh) trong bảng của tab đang mở."""
        tab = self.tabs.get(self.tabview.get()) if self.tabs else None
        if not tab or not tab.store.loaded:
            return None
        sel = tab.tree.selection()
        return (tab, int(sel[0])) if sel else None

    def on_customer_change(self):
        if hasattr(self, "template_panel"):
            self.template_panel.update_customer()

    def current_tab(self) -> AccountTab:
        return self.tabs[self.tabview.get()]

    def _preview_row(self) -> tuple[AccountTab, int] | None:
        """Dòng dùng để xem trước mẫu: khách đang chọn, không có thì dòng tích đầu tiên / dòng đầu."""
        if self.selected_customer():
            return self.selected_customer()
        tab = self.current_tab()
        if not tab.store.loaded or not len(tab.store):
            return None
        rows = tab._selected_indices() or tab.store.indices()
        return tab, rows[0]

    def template_context(self) -> dict:
        """resolve/chips/preview_label cho popup soạn mẫu, theo file Excel của tab đang mở."""
        row = self._preview_row()
        if not row:
            return dict(resolve=sample_value, chips=DEFAULT_CHIPS,
                        preview_label="Xem trước (dữ liệu mẫu - import Excel để dùng mọi cột của file):")
        tab, idx = row
        return dict(resolve=lambda name: tab.store.value(idx, name), chips=tab.store.placeholder_chips(),
                    preview_label=f"Xem trước với khách dòng {idx + 1} ({tab.store.field(idx, 'hoten')}):")

    def flash(self, text: str):
        self.current_tab()._status(text, COLOR_OK)

    def select(self, tab: AccountTab):
        self.tabview.set(tab.name)
        self._on_tab_change()

    def login_all(self):
        """Mở cửa sổ quét QR LẦN LƯỢT cho các tài khoản chưa đăng nhập (mở cùng lúc dễ quét nhầm cửa sổ)."""
        queue = [t for t in self.tabs.values() if not t.is_running and not t.account.get("zalo_name")]
        if not queue:
            messagebox.showinfo("Đăng nhập", "Tất cả tài khoản đã đăng nhập (hoặc đang chạy)")
            return
        names = "\n".join(f"  • {t.name}" for t in queue)
        if messagebox.askyesno("Đăng nhập tất cả",
                               f"Sẽ mở cửa sổ quét QR lần lượt cho {len(queue)} tài khoản:\n{names}\n\n"
                               "Mỗi cửa sổ hãy quét bằng 1 tài khoản Zalo KHÁC NHAU.\n"
                               "Quét xong cửa sổ tự đóng và chuyển sang tài khoản tiếp theo."):
            self._login_next(queue)

    def _login_next(self, queue: list[AccountTab]):
        while queue:
            tab = queue.pop(0)
            if tab in self.tabs.values() and not tab.is_running:   # có thể đã bị xóa/đang chạy trong lúc chờ
                self.select(tab)
                tab.login(on_done=lambda: self._login_next(queue))
                return

    def check_all(self):
        """Kiểm tra LẦN LƯỢT (mỗi lần 1 Chromium) - chạy cùng lúc 5 trình duyệt dễ làm máy hết RAM."""
        queue = [t for t in self.tabs.values() if not t.is_running and accounts.has_profile(t.account)]
        self._check_next(queue)

    def _check_next(self, queue: list[AccountTab]):
        while queue:
            tab = queue.pop(0)
            if tab in self.tabs.values() and not tab.is_running:
                tab.check_login(on_done=lambda: self._check_next(queue))
                return

    # ================== QUẢN LÝ TÀI KHOẢN ==================
    def _add_tab(self, acc: dict):
        self.tabview.add(acc["name"])
        tab = AccountTab(self.tabview.tab(acc["name"]), self, acc)
        tab.pack(fill="both", expand=True)
        self.tabs[acc["name"]] = tab
        card = AccountCard(self.card_list, tab)
        card.pack(fill="x", pady=4)
        self.cards[id(tab)] = card

    def _ask_name(self, title: str, initial: str = "") -> str | None:
        dlg = ctk.CTkInputDialog(title=title, text="Tên tài khoản (hiển thị trên tab):")
        if initial:   # CTkInputDialog không có giá trị mặc định và tạo ô nhập trễ 10ms
            dlg.after(50, lambda: dlg._entry.insert(0, initial))
        name = (dlg.get_input() or "").strip()
        if not name:
            return None
        if accounts.find(self.accounts, name):
            messagebox.showwarning("Cảnh báo", f"Đã có tài khoản tên \"{name}\"")
            return None
        return name

    def add_account(self):
        name = self._ask_name("Thêm tài khoản", f"Tài khoản {len(self.accounts) + 1}")
        if not name:
            return
        acc = accounts.new_account(name)
        self.accounts.append(acc)
        accounts.save(self.accounts)
        self._add_tab(acc)
        self.select(self.tabs[name])
        self.tabs[name].login()   # mở trình duyệt để quét QR luôn

    def rename_account(self):
        old = self.tabview.get()
        tab = self.tabs[old]
        if tab.is_running:
            messagebox.showwarning("Cảnh báo", "Tài khoản đang chạy, hãy dừng trước")
            return
        new = self._ask_name("Đổi tên tài khoản", old)
        if not new:
            return
        self.tabview.rename(old, new)
        tab.account["name"] = new
        self.tabs[new] = self.tabs.pop(old)
        accounts.save(self.accounts)
        self.select(tab)

    def remove_account(self):
        name = self.tabview.get()
        tab = self.tabs[name]
        if tab.is_running:
            messagebox.showwarning("Cảnh báo", "Tài khoản đang chạy, hãy dừng trước")
            return
        if len(self.accounts) == 1:
            messagebox.showwarning("Cảnh báo", "Phải giữ lại ít nhất 1 tài khoản")
            return
        if not messagebox.askyesno("Xóa tài khoản", f"Xóa tài khoản \"{name}\"?"):
            return
        wipe = messagebox.askyesno("Xóa tài khoản", "Xóa luôn dữ liệu đăng nhập (lần sau phải quét QR lại)?")
        acc = tab.account
        self.tabview.delete(name)
        del self.tabs[name]
        self.cards.pop(id(tab)).destroy()
        self.accounts.remove(acc)
        accounts.save(self.accounts)
        if wipe:
            accounts.delete_profile(acc)
        self._on_tab_change()

    def tab_using_file(self, path: str, exclude: AccountTab) -> AccountTab | None:
        target = os.path.normcase(os.path.abspath(path))
        for tab in self.tabs.values():
            if tab is not exclude and tab.store.path and os.path.normcase(os.path.abspath(tab.store.path)) == target:
                return tab
        return None

    def tab_with_uid(self, uid: str | None, exclude: AccountTab) -> AccountTab | None:
        if not uid:
            return None
        return next((t for t in self.tabs.values() if t is not exclude and t.account.get("uid") == uid), None)

    def _on_close(self):
        running = [t for t in self.tabs.values() if t.is_running]
        if running:
            names = ", ".join(t.name for t in running)
            if not messagebox.askyesno("Thoát", f"Đang chạy ở: {names}.\nBạn có chắc muốn thoát?"):
                return
            for t in running:
                if t.sender:
                    t.sender.stop()
        self.destroy()


def main():
    cfg.setup_logging(console=True)
    ZaloSenderApp().mainloop()


if __name__ == "__main__":
    main()
