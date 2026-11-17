import csv
import json
import math
import os
import threading
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

import requests
import urllib3


CONFIG_FILE = "config.json"


class ZamanPardazAuthError(Exception):
    """خطای مربوط به کلید امنیتی یا عدم دسترسی"""
    pass


class ZamanPardazClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": api_key,
            "Accept": "application/json",
        })

    def get_traffics(
        self,
        date_from: str,
        date_to: str,
        page: int = 1,
        page_count: int = 100,
        user_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        endpoint = f"{self.base_url}/api/traffics/GetTraffics"
        params = {
            "page": page,
            "pagecount": page_count,
            "from": date_from,
            "to": date_to,
        }
        if user_code is not None and str(user_code).strip() != "":
            params["usercode"] = str(user_code).strip()

        response = self.session.get(
            endpoint,
            params=params,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()

        raw_text = response.text.strip().replace(" ", "").lower()
        if raw_text in ('{access:false}', '{"access":false}'):
            raise ZamanPardazAuthError(
                "کلید امنیتی وارد نشده، اشتباه است، غیرفعال شده یا تاریخ انقضای آن سر رسیده است."
            )

        data = response.json()
        if isinstance(data, dict) and data.get("access") is False:
            raise ZamanPardazAuthError("کلید امنیتی معتبر نیست.")

        # پشتیبانی از هر دو کلید traffics و taffics (مطابق مستندات)
        traffics_list = data.get("traffics")
        if traffics_list is None:
            traffics_list = data.get("taffics", [])

        return {
            "traffics": traffics_list,
            "total": data.get("total", 0),
        }

    def get_all_traffics(
        self,
        date_from: str,
        date_to: str,
        page_count: int = 100,
        user_code: Optional[str] = None,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        all_items: List[Dict[str, Any]] = []

        if progress_callback:
            progress_callback("در حال دریافت صفحه 1...")

        first_page = self.get_traffics(
            date_from=date_from,
            date_to=date_to,
            page=1,
            page_count=page_count,
            user_code=user_code,
        )

        items = first_page["traffics"]
        total = first_page["total"]
        all_items.extend(items)

        if total > len(all_items) and page_count > 0:
            total_pages = math.ceil(total / page_count)
            for page_num in range(2, total_pages + 1):
                if progress_callback:
                    progress_callback(f"در حال دریافت صفحه {page_num} از {total_pages}...")
                res = self.get_traffics(
                    date_from=date_from,
                    date_to=date_to,
                    page=page_num,
                    page_count=page_count,
                    user_code=user_code,
                )
                if not res["traffics"]:
                    break
                all_items.extend(res["traffics"])

        return all_items


class ZamanPardazApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("نرم‌افزار دریافت تردد زمان پرداز (API Client)")
        self.root.geometry("950x650")
        self.root.minsize(820, 560)

        self.default_font = ("Tahoma", 9)
        self.bold_font = ("Tahoma", 9, "bold")
        self.root.option_add("*Font", self.default_font)

        self.traffics_data: List[Dict[str, Any]] = []
        self.is_fetching = False
        self.auto_job_id: Optional[str] = None

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- بخش ۱: تنظیمات اتصال ---
        conn_frame = ttk.LabelFrame(main_frame, text=" تنظیمات اتصال به سرور / دستگاه ", padding=10)
        conn_frame.pack(fill=tk.X, pady=(0, 8))

        # ردیف اول تنظیمات اتصال
        ttk.Label(conn_frame, text="پروتکل:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.protocol_var = tk.StringVar(value="http")
        protocol_combo = ttk.Combobox(
            conn_frame, textvariable=self.protocol_var, values=["http", "https"], width=7, state="readonly"
        )
        protocol_combo.grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(conn_frame, text="IP یا دامنه:").grid(row=0, column=2, sticky=tk.W, padx=(12, 4), pady=4)
        self.host_var = tk.StringVar(value="192.168.1.100")
        ttk.Entry(conn_frame, textvariable=self.host_var, width=22).grid(row=0, column=3, sticky=tk.W, padx=4, pady=4)

        ttk.Label(conn_frame, text="پورت (اختیاری):").grid(row=0, column=4, sticky=tk.W, padx=(12, 4), pady=4)
        self.port_var = tk.StringVar(value="")
        ttk.Entry(conn_frame, textvariable=self.port_var, width=8).grid(row=0, column=5, sticky=tk.W, padx=4, pady=4)

        self.ignore_ssl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            conn_frame, text="نادیده گرفتن خطای SSL", variable=self.ignore_ssl_var
        ).grid(row=0, column=6, sticky=tk.W, padx=(12, 4), pady=4)

        # ردیف دوم تنظیمات اتصال
        ttk.Label(conn_frame, text="کلید امنیتی (Authorization):").grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=4, pady=4)
        self.api_key_var = tk.StringVar()
        self.api_entry = ttk.Entry(conn_frame, textvariable=self.api_key_var, width=42, show="*")
        self.api_entry.grid(row=1, column=2, columnspan=3, sticky=tk.EW, padx=4, pady=4)

        self.show_key_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            conn_frame, text="نمایش کلید", variable=self.show_key_var, command=self._toggle_api_key
        ).grid(row=1, column=5, sticky=tk.W, padx=4, pady=4)

        ttk.Button(conn_frame, text="ذخیره تنظیمات", command=self._save_config).grid(
            row=1, column=6, sticky=tk.E, padx=4, pady=4
        )

        # --- بخش ۲: فیلترها و دریافت خودکار ---
        filter_frame = ttk.LabelFrame(main_frame, text=" فیلتر گزارش و دریافت خودکار ", padding=10)
        filter_frame.pack(fill=tk.X, pady=(0, 8))

        today = date.today()
        week_ago = today - timedelta(days=7)

        ttk.Label(filter_frame, text="از تاریخ (YYYY-MM-DD):").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.from_var = tk.StringVar(value=week_ago.strftime("%Y-%m-%d"))
        ttk.Entry(filter_frame, textvariable=self.from_var, width=13).grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(filter_frame, text="تا تاریخ (YYYY-MM-DD):").grid(row=0, column=2, sticky=tk.W, padx=(12, 4), pady=4)
        self.to_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))
        ttk.Entry(filter_frame, textvariable=self.to_var, width=13).grid(row=0, column=3, sticky=tk.W, padx=4, pady=4)

        ttk.Label(filter_frame, text="کد پرسنلی (اختیاری):").grid(row=0, column=4, sticky=tk.W, padx=(12, 4), pady=4)
        self.usercode_var = tk.StringVar(value="")
        ttk.Entry(filter_frame, textvariable=self.usercode_var, width=12).grid(row=0, column=5, sticky=tk.W, padx=4, pady=4)

        ttk.Label(filter_frame, text="تعداد در صفحه:").grid(row=0, column=6, sticky=tk.W, padx=(12, 4), pady=4)
        self.pagecount_var = tk.StringVar(value="100")
        ttk.Entry(filter_frame, textvariable=self.pagecount_var, width=7).grid(row=0, column=7, sticky=tk.W, padx=4, pady=4)

        # ردیف دکمه‌ها و همگام‌سازی خودکار
        action_frame = ttk.Frame(filter_frame)
        action_frame.grid(row=1, column=0, columnspan=8, sticky=tk.EW, pady=(8, 0))

        self.fetch_btn = ttk.Button(
            action_frame, text="دریافت اطلاعات تردد", command=self.start_fetch_thread
        )
        self.fetch_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.export_btn = ttk.Button(
            action_frame, text="خروجی اکسل (CSV)", command=self.export_csv
        )
        self.export_btn.pack(side=tk.LEFT, padx=(0, 16))

        self.auto_sync_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            action_frame,
            text="دریافت خودکار هر",
            variable=self.auto_sync_var,
            command=self._toggle_auto_sync,
        ).pack(side=tk.LEFT)

        self.interval_var = tk.StringVar(value="60")
        ttk.Entry(action_frame, textvariable=self.interval_var, width=5).pack(side=tk.LEFT, padx=4)
        ttk.Label(action_frame, text="ثانیه").pack(side=tk.LEFT)

        # --- بخش ۳: جدول نمایش ترددها ---
        table_frame = ttk.Frame(main_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("row", "userCode", "verifyDate", "verifyType", "verifyState", "deviceNumber")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")

        headings = {
            "row": "ردیف",
            "userCode": "کد پرسنلی (userCode)",
            "verifyDate": "تاریخ و ساعت (verifyDate)",
            "verifyType": "نوع شناسایی (verifyType)",
            "verifyState": "حالت تردد (verifyState)",
            "deviceNumber": "شماره دستگاه (deviceNumber)",
        }
        widths = {
            "row": 60,
            "userCode": 140,
            "verifyDate": 210,
            "verifyType": 150,
            "verifyState": 150,
            "deviceNumber": 150,
        }

        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.CENTER)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # --- نوار وضعیت ---
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(8, 0))

        self.status_var = tk.StringVar(value="آماده اتصال. IP، پورت و کلید امنیتی را وارد کنید.")
        ttk.Label(status_frame, textvariable=self.status_var, font=self.bold_font).pack(side=tk.LEFT)

        self.count_var = tk.StringVar(value="تعداد رکورد: 0")
        ttk.Label(status_frame, textvariable=self.count_var, font=self.bold_font).pack(side=tk.RIGHT)

    def _toggle_api_key(self):
        self.api_entry.config(show="" if self.show_key_var.get() else "*")

    def _build_base_url(self) -> str:
        protocol = self.protocol_var.get().strip()
        host = self.host_var.get().strip()
        # حذف http:// یا https:// اگر کاربر به اشتباه وارد کرده باشد
        for prefix in ("https://", "http://"):
            if host.lower().startswith(prefix):
                host = host[len(prefix):]
        host = host.strip("/")

        if not host:
            raise ValueError("لطفاً آدرس IP یا دامنه را وارد کنید.")

        port = self.port_var.get().strip()
        if port:
            if not port.isdigit():
                raise ValueError("شماره پورت باید یک عدد معتبر باشد.")
            return f"{protocol}://{host}:{port}"
        return f"{protocol}://{host}"

    def _save_config(self, silent: bool = False):
        cfg = {
            "protocol": self.protocol_var.get(),
            "host": self.host_var.get(),
            "port": self.port_var.get(),
            "api_key": self.api_key_var.get(),
            "ignore_ssl": self.ignore_ssl_var.get(),
            "pagecount": self.pagecount_var.get(),
            "interval": self.interval_var.get(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            if not silent:
                messagebox.showinfo("ذخیره شد", "تنظیمات با موفقیت در فایل config.json ذخیره شد.")
        except Exception as e:
            if not silent:
                messagebox.showerror("خطا", f"خطا در ذخیره تنظیمات:\n{e}")

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.protocol_var.set(cfg.get("protocol", "http"))
            self.host_var.set(cfg.get("host", "192.168.1.100"))
            self.port_var.set(cfg.get("port", ""))
            self.api_key_var.set(cfg.get("api_key", ""))
            self.ignore_ssl_var.set(cfg.get("ignore_ssl", True))
            self.pagecount_var.set(cfg.get("pagecount", "100"))
            self.interval_var.set(cfg.get("interval", "60"))
        except Exception:
            pass

    def _toggle_auto_sync(self):
        if self.auto_sync_var.get():
            self.start_fetch_thread(from_auto=True)
        else:
            if self.auto_job_id is not None:
                self.root.after_cancel(self.auto_job_id)
                self.auto_job_id = None
            self.status_var.set("دریافت خودکار متوقف شد.")

    def _schedule_next_auto_sync(self):
        if self.auto_job_id is not None:
            self.root.after_cancel(self.auto_job_id)
            self.auto_job_id = None

        if not self.auto_sync_var.get():
            return

        try:
            seconds = int(self.interval_var.get().strip())
            if seconds < 5:
                seconds = 5
        except ValueError:
            seconds = 60

        self.auto_job_id = self.root.after(seconds * 1000, lambda: self.start_fetch_thread(from_auto=True))

    def start_fetch_thread(self, from_auto: bool = False):
        if self.is_fetching:
            return

        try:
            base_url = self._build_base_url()
            api_key = self.api_key_var.get().strip()
            if not api_key:
                raise ValueError("لطفاً کلید امنیتی (Authorization) را وارد کنید.")

            date_from = self.from_var.get().strip()
            date_to = self.to_var.get().strip()
            if not date_from or not date_to:
                raise ValueError("لطفاً تاریخ شروع و پایان را وارد کنید.")

            page_count = int(self.pagecount_var.get().strip() or "100")
            if page_count <= 0:
                raise ValueError("تعداد در صفحه باید بزرگ‌تر از صفر باشد.")

            user_code = self.usercode_var.get().strip() or None
            verify_ssl = not self.ignore_ssl_var.get()

        except ValueError as err:
            if from_auto:
                self.auto_sync_var.set(False)
            messagebox.showwarning("ورودی نامعتبر", str(err))
            return

        # ذخیره خودکار تنظیمات هنگام اجرای موفق
        self._save_config(silent=True)

        self.is_fetching = True
        self.fetch_btn.config(state=tk.DISABLED)
        self.status_var.set(f"در حال اتصال به {base_url} ...")

        thread = threading.Thread(
            target=self._fetch_worker,
            args=(base_url, api_key, verify_ssl, date_from, date_to, page_count, user_code, from_auto),
            daemon=True,
        )
        thread.start()

    def _fetch_worker(
        self,
        base_url: str,
        api_key: str,
        verify_ssl: bool,
        date_from: str,
        date_to: str,
        page_count: int,
        user_code: Optional[str],
        from_auto: bool,
    ):
        try:
            client = ZamanPardazClient(base_url=base_url, api_key=api_key, verify_ssl=verify_ssl)
            items = client.get_all_traffics(
                date_from=date_from,
                date_to=date_to,
                page_count=page_count,
                user_code=user_code,
                progress_callback=lambda msg: self.root.after(0, lambda m=msg: self.status_var.set(m)),
            )
            self.root.after(0, lambda: self._on_fetch_success(items))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._on_fetch_error(e, from_auto))

    def _on_fetch_success(self, items: List[Dict[str, Any]]):
        self.is_fetching = False
        self.fetch_btn.config(state=tk.NORMAL)
        self.traffics_data = items

        # پاک کردن و پر کردن مجدد جدول
        for row in self.tree.get_children():
            self.tree.delete(row)

        for idx, item in enumerate(items, start=1):
            self.tree.insert(
                "",
                tk.END,
                values=(
                    idx,
                    item.get("userCode", ""),
                    item.get("verifyDate", ""),
                    item.get("verifyType", ""),
                    item.get("verifyState", ""),
                    item.get("deviceNumber", ""),
                ),
            )

        now_str = datetime.now().strftime("%H:%M:%S")
        self.status_var.set(f"اطلاعات با موفقیت دریافت شد. (آخرین بروزرسانی: {now_str})")
        self.count_var.set(f"تعداد رکورد: {len(items)}")

        self._schedule_next_auto_sync()

    def _on_fetch_error(self, error: Exception, from_auto: bool):
        self.is_fetching = False
        self.fetch_btn.config(state=tk.NORMAL)

        if isinstance(error, ZamanPardazAuthError):
            msg = f"خطای احراز هویت: {error}"
        elif isinstance(error, requests.exceptions.ConnectionError):
            msg = "خطای اتصال: سرور یا IP/پورت مورد نظر در دسترس نیست."
        elif isinstance(error, requests.exceptions.Timeout):
            msg = "خطای زمان انتظار: سرور در زمان مقرر پاسخ نداد."
        else:
            msg = f"خطا: {error}"

        self.status_var.set(msg)
        if not from_auto:
            messagebox.showerror("خطا در دریافت اطلاعات", msg)
        else:
            # در حالت خودکار، پیام خطا در نوار وضعیت نمایش داده می‌شود و دفعه بعد دوباره تلاش می‌کند
            self._schedule_next_auto_sync()

    def export_csv(self):
        if not self.traffics_data:
            messagebox.showinfo("خالی", "هیچ ترددی برای ذخیره وجود ندارد. ابتدا اطلاعات را دریافت کنید.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=f"traffics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            title="ذخیره خروجی ترددها",
        )
        if not file_path:
            return

        try:
            fieldnames = ["verifyDate", "userCode", "verifyType", "verifyState", "deviceNumber"]
            with open(file_path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.traffics_data)
            messagebox.showinfo("موفق", f"تعداد {len(self.traffics_data)} رکورد با موفقیت ذخیره شد.")
        except Exception as e:
            messagebox.showerror("خطا", f"خطا در ذخیره فایل:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ZamanPardazApp(root)
    root.mainloop()
