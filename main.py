"""
TW Earning Slides Downloader — 法說會簡報批次下載工具
從公開資訊觀測站下載法人說明會 PDF，依日期範圍自動掃描。
"""

import os
import json
import queue
import random
import threading
import time
from datetime import date, datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---- 常數 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MOPS_BASE = "https://mopsov.twse.com.tw"
MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
MOPS_MAIN_URL = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
COMPANY_MARKET_FILE = os.path.join(SCRIPT_DIR, "company_market.json")
CACHE_MAX_DAYS = 90  # 超過 90 天自動提示更新

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
MARKET_CODES = [
    ("sii",  "上市"),
    ("otc",  "上櫃"),
    ("rotc", "興櫃"),
    ("pub",  "公開發行"),
]

# 公司清單抓取 URL（靜態參數，從 MOPS t51sb01 頁面取得）
MARKET_LIST_URLS = {
    "sii":  "https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca765118e1d5d55f2907af83df59ae82756caca30645f4a87baa01551cc98a6ff0816cbaad9c5c8c6df699b1ac8bf50f27c999868a65d5f5dd71b407c4d61b426833ab8c",
    "otc":  "https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca7651189431092059e57ec5acce2508557bbb820645f4a87baa01551cc98a6ff0816cbaad9c5c8c6df699b1ac8bf50f27c999868a65d5f5dd71b407c4d61b426833ab8c",
    "rotc": "https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca765118150b1250f6b0d18c5da95b58aafad725152f445b9d55dd4c51df9e26ea7918af4de96261009bdfefb47812fc6ed9b9145701ed44236616fb09e84fed0c84caa6",
    "pub":  "https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca765118f332b2e68ee1973efdd894533684e6040645f4a87baa01551cc98a6ff0816cbaad9c5c8c6df699b1ac8bf50f27c999868a65d5f5dd71b407c4d61b426833ab8c",
}


# ---- 日期工具 ----
def date_range_to_months(start: str, end: str) -> list[tuple[int, int]]:
    """
    將 YYYYMMDD 字串範圍展開為 (year, month) tuple 清單，由舊到新。
    例：('20150101', '20150301') → [(2015,1),(2015,2),(2015,3)]
    """
    sy, sm = int(start[:4]), int(start[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    months = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def roc_year(western_year: int) -> int:
    """西元年轉民國年。例：2026 → 115"""
    return western_year - 1911


def parse_roc_date(roc_date_str: str) -> str:
    """
    將民國日期字串轉為西元 YYYYMMDD。
    例：'115/01/15' → '20260115'
    '114/3/5' → '20250305'
    '115/03/03 ~ 115/03/06' → '20260303'（取第一個日期）
    """
    first = roc_date_str.strip().split("~")[0].strip()
    parts = first.split("/")
    if len(parts) != 3:
        return ""
    try:
        roc_y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return ""
    western_y = roc_y + 1911
    return f"{western_y}{m:02d}{d:02d}"


def build_save_path(date_str: str, lang: str, output_dir: str) -> str:
    """
    建立不衝突的儲存路徑。
    第一個檔案：YYYYMMDD_zh.pdf
    衝突時加流水號：YYYYMMDD_zh_2.pdf、YYYYMMDD_zh_3.pdf
    使用 os.path.exists() 做 filesystem-based 判斷。
    """
    base = os.path.join(output_dir, f"{date_str}_{lang}.pdf")
    if not os.path.exists(base):
        return base
    counter = 2
    while True:
        candidate = os.path.join(output_dir, f"{date_str}_{lang}_{counter}.pdf")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


# ---- 公司清單快取 ----
_LIST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://mopsov.twse.com.tw/mops/web/t51sb01",
    "Connection": "keep-alive",
}


def _make_list_session() -> requests.Session:
    """建立已取得 session cookie 的 requests.Session。"""
    session = requests.Session()
    session.get("https://mopsov.twse.com.tw/mops/web/t51sb01",
                headers=_LIST_HEADERS, timeout=30, verify=False)
    return session


def _fetch_one_market(market_code: str, session: requests.Session) -> dict[str, str]:
    """抓取單一市場的公司清單，回傳 {公司代號: market_code}。"""
    companies: dict[str, str] = {}
    url = MARKET_LIST_URLS[market_code]
    resp = session.get(url, headers=_LIST_HEADERS, timeout=30, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        co_id = cells[0].get_text(strip=True)
        if co_id and 2 <= len(co_id) <= 6 and co_id.isalnum():
            companies[co_id] = market_code
    return companies


def save_company_list(companies: dict[str, str]) -> None:
    """將公司清單與更新日期存入 company_market.json。"""
    data = {
        "updated_at": date.today().strftime("%Y%m%d"),
        "companies": companies,
    }
    with open(COMPANY_MARKET_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_company_list() -> tuple[dict[str, str], str]:
    """
    載入本地快取。
    回傳 (companies dict, updated_at str)。
    快取不存在時回傳 ({}, "")。
    """
    if not os.path.exists(COMPANY_MARKET_FILE):
        return {}, ""
    with open(COMPANY_MARKET_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("companies", {}), data.get("updated_at", "")


def cache_age_days(updated_at: str) -> int:
    """回傳快取距今天數；updated_at 為空或格式錯誤時回傳 999。"""
    if not updated_at:
        return 999
    try:
        updated = datetime.strptime(updated_at, "%Y%m%d").date()
        return (date.today() - updated).days
    except ValueError:
        return 999


def lookup_market(co_id: str, companies: dict[str, str]) -> str | None:
    """從快取查公司市場別，找不到回傳 None。"""
    return companies.get(co_id)


# ---- MOPS 查詢 ----
def query_mops(market: str, year: int, month: int, co_id: str) -> list[dict]:
    """
    從 MOPS 查詢指定年月的法說會記錄。
    回傳 list of {date: str (YYYYMMDD), zh_url: str, en_url: str}。
    表格為空或無符合列時回傳 []。

    注意：MOPS AJAX API 一次回傳該公司全部記錄（不按年月過濾），
    本函式在 client 端依 year/month 篩選後回傳。
    """
    data = {
        "market": market,
        "co_id": co_id,
        "firstin": "1",
    }
    try:
        session = requests.Session()
        session.get(MOPS_MAIN_URL, headers=HEADERS, timeout=15, verify=False)
        resp = session.post(MOPS_URL, data=data, headers=HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    rows = soup.find_all("tr")
    results = []

    for row in rows:
        cells = row.find_all("td")
        # 需要至少 8 欄；第一欄必須符合公司代號
        if len(cells) < 8:
            continue
        if cells[0].get_text(strip=True) != co_id:
            continue

        roc_date_str = cells[2].get_text(strip=True)
        date_str = parse_roc_date(roc_date_str)
        if not date_str:
            continue

        # 依 year/month 篩選
        if int(date_str[:4]) != year or int(date_str[4:6]) != month:
            continue

        # 中文檔案：column 6；英文檔案：column 7（相對路徑補上 base URL）
        zh_link = cells[6].find("a")
        en_link = cells[7].find("a")
        zh_href = zh_link.get("href", "") if zh_link else ""
        en_href = en_link.get("href", "") if en_link else ""
        zh_url = (MOPS_BASE + zh_href) if zh_href.startswith("/") else zh_href
        en_url = (MOPS_BASE + en_href) if en_href.startswith("/") else en_href

        results.append({"date": date_str, "zh_url": zh_url, "en_url": en_url})

    return results


def detect_market(co_id: str, months: list[tuple[int, int]], companies: dict[str, str] | None = None) -> str | None:
    """
    市場別偵測：
    1. 若有快取（companies 不為空），直接查快取。
    2. 找不到或無快取時，fallback：逐月試誤。
    找不到回傳 None。
    """
    # 優先查快取
    if companies:
        result = lookup_market(co_id, companies)
        if result:
            return result

    # Fallback：試誤（從末尾往前掃，靜默跳過無資料月份）
    for year, month in reversed(months):
        for market_code, _ in MARKET_CODES:
            if query_mops(market_code, year, month, co_id):
                return market_code
    return None


# ---- PDF 下載 ----
def download_pdf(url: str, save_path: str) -> None:
    """
    下載 PDF 到指定路徑。
    失敗時拋出 requests.exceptions.RequestException（由呼叫者處理）。
    """
    response = requests.get(url, stream=True, headers=HEADERS, timeout=30, verify=False)
    response.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


# ---- GUI ----
class EarningSlideApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("法說會簡報下載器")
        self.root.resizable(False, False)

        self.msg_queue: queue.Queue = queue.Queue()
        self.is_running = False
        self._companies: dict[str, str] = {}

        self._build_ui()
        self._load_cache_on_startup()
        self._poll_queue()

    def _build_ui(self):
        pad = {"padx": 14, "pady": 6}

        # 查詢條件
        frame_query = ttk.LabelFrame(self.root, text=" 查詢條件 ", padding=8)
        frame_query.grid(row=0, column=0, sticky="ew", **pad)
        frame_query.columnconfigure(1, weight=1)

        ttk.Label(frame_query, text="公司代號：").grid(row=0, column=0, sticky="w", pady=4)
        self.co_id_var = tk.StringVar()
        ttk.Entry(frame_query, textvariable=self.co_id_var, width=12).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(frame_query, text="日期範圍：").grid(row=1, column=0, sticky="w", pady=4)
        date_frame = ttk.Frame(frame_query)
        date_frame.grid(row=1, column=1, sticky="w", pady=4)
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        PLACEHOLDER = "YYYYMMDD"
        self._start_entry = ttk.Entry(date_frame, textvariable=self.start_var, width=12,
                                      foreground="grey")
        self._start_entry.pack(side="left")
        ttk.Label(date_frame, text="  ~  ").pack(side="left")
        self._end_entry = ttk.Entry(date_frame, textvariable=self.end_var, width=12,
                                    foreground="grey")
        self._end_entry.pack(side="left")

        # 設定 placeholder
        for entry, var in ((self._start_entry, self.start_var),
                           (self._end_entry, self.end_var)):
            var.set(PLACEHOLDER)
            entry.bind("<FocusIn>",  lambda e, en=entry, v=var: self._ph_focus_in(en, v, PLACEHOLDER))
            entry.bind("<FocusOut>", lambda e, en=entry, v=var: self._ph_focus_out(en, v, PLACEHOLDER))

        ttk.Label(frame_query, text="儲存資料夾：").grid(row=2, column=0, sticky="w", pady=4)
        folder_frame = ttk.Frame(frame_query)
        folder_frame.grid(row=2, column=1, sticky="ew", pady=4)
        folder_frame.columnconfigure(0, weight=1)
        self.folder_var = tk.StringVar()
        ttk.Entry(folder_frame, textvariable=self.folder_var, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(folder_frame, text="選擇", command=self._select_folder).grid(row=0, column=1)

        # 公司清單快取狀態
        cache_frame = ttk.Frame(frame_query)
        cache_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        cache_frame.columnconfigure(0, weight=1)

        info_row = ttk.Frame(cache_frame)
        info_row.grid(row=0, column=0, sticky="ew")
        self.cache_label = ttk.Label(info_row, text="公司清單：載入中...",
                                     foreground="gray", wraplength=340, justify="left")
        self.cache_label.pack(side="left")
        self.btn_update_cache = ttk.Button(info_row, text="立即更新", command=self._update_cache)
        self.btn_update_cache.pack(side="left", padx=(10, 0))

        self.cache_progress = ttk.Progressbar(cache_frame, mode="determinate", length=340)
        # 預設隱藏，更新時才顯示

        # 延遲查詢選項
        self.delay_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame_query,
            text="防爬蟲延遲（每次查詢間隔 1~3 秒）",
            variable=self.delay_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 2))

        # 開始按鈕 + 說明按鈕
        frame_btn = tk.Frame(self.root)
        frame_btn.grid(row=1, column=0, pady=8)
        self.btn_start = ttk.Button(frame_btn, text="▶  開始下載", command=self._start, width=20)
        self.btn_start.pack(side="left", ipady=6, padx=(0, 8))
        ttk.Button(frame_btn, text="？  說明", command=self._show_help, width=10).pack(
            side="left", ipady=6
        )

        # 處理進度
        frame_progress = ttk.LabelFrame(self.root, text=" 處理進度 ", padding=8)
        frame_progress.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 14))

        self.progress_label = ttk.Label(frame_progress, text="等待開始...")
        self.progress_label.pack(anchor="w")
        self.progress_bar = ttk.Progressbar(frame_progress, mode="determinate")
        self.progress_bar.pack(fill="x", pady=(4, 8))
        self.log_text = scrolledtext.ScrolledText(
            frame_progress, width=60, height=12, state="disabled", font=("Consolas", 9)
        )
        self.log_text.pack(fill="x")

        # 開啟資料夾（完成後顯示）
        frame_output = tk.Frame(self.root)
        frame_output.grid(row=3, column=0, pady=(0, 12))
        self.btn_open_folder = ttk.Button(
            frame_output, text="開啟資料夾", command=self._open_output_folder
        )
        self._output_folder = ""

        self.root.columnconfigure(0, weight=1)

        # 初始 log
        self.log_text.config(state="normal")
        self.log_text.insert("1.0", "輸入公司代號與日期範圍，按「開始下載」。\n")
        self.log_text.config(state="disabled")

    # ---- 快取管理 ----
    def _load_cache_on_startup(self):
        """啟動時載入快取，若超過 90 天顯示警告（不自動更新，避免啟動卡頓）。"""
        companies, updated_at = load_company_list()
        self._companies = companies
        if not updated_at:
            self.cache_label.config(
                text="公司清單：尚未建立，建議點「立即更新」",
                foreground="#7B5C00"
            )
        else:
            age = cache_age_days(updated_at)
            display_date = f"{updated_at[:4]}-{updated_at[4:6]}-{updated_at[6:]}"
            if age > CACHE_MAX_DAYS:
                self.cache_label.config(
                    text=f"公司清單：上次更新 {display_date}（已 {age} 天，建議更新）",
                    foreground="#7B5C00"
                )
            else:
                self.cache_label.config(
                    text=f"公司清單：上次更新 {display_date}（{len(companies)} 家公司）",
                    foreground="gray"
                )

    def _update_cache(self):
        """手動更新公司清單（背景執行，逐市場回報進度）。"""
        if self.is_running:
            messagebox.showwarning("提示", "下載進行中，請完成後再更新。")
            return
        self.btn_update_cache.config(state="disabled")
        self.cache_label.config(text="公司清單：連線中...", foreground="gray")
        self.cache_progress["maximum"] = len(MARKET_CODES)
        self.cache_progress["value"] = 0
        self.cache_progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        def _worker():
            try:
                session = _make_list_session()
                companies: dict[str, str] = {}
                for i, (market_code, market_name) in enumerate(MARKET_CODES):
                    self.msg_queue.put(("cache_progress",
                                        (i, f"更新中：{market_name}（{i}/{len(MARKET_CODES)}）")))
                    result = _fetch_one_market(market_code, session)
                    companies.update(result)
                save_company_list(companies)
                self._companies = companies
                updated_at = date.today().strftime("%Y%m%d")
                display_date = f"{updated_at[:4]}-{updated_at[4:6]}-{updated_at[6:]}"
                self.msg_queue.put(("cache_ok",
                                    f"公司清單：上次更新 {display_date}（{len(companies)} 家公司）"))
            except Exception as e:
                short_err = str(e)[:60]
                self.msg_queue.put(("cache_err", f"更新失敗，請確認網路後重試"))

        threading.Thread(target=_worker, daemon=True).start()

    # ---- 說明視窗 ----
    def _show_help(self):
        win = tk.Toplevel(self.root)
        win.title("使用說明")
        win.resizable(False, False)
        win.grab_set()

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)

        txt = tk.Text(frame, width=56, height=26, font=("", 9),
                      relief="flat", wrap="word", state="normal",
                      cursor="arrow", bg=win.cget("bg"))
        txt.pack(anchor="w")

        # tag 定義
        txt.tag_config("heading",  foreground="#1155AA", font=("", 9, "bold"))
        txt.tag_config("url",      foreground="#0066CC", font=("Consolas", 9))
        txt.tag_config("code",     foreground="#2E7D32", font=("Consolas", 9))
        txt.tag_config("emphasis", foreground="#C75000", font=("", 9, "bold"))

        def h(text):   txt.insert("end", text, "heading")
        def u(text):   txt.insert("end", text, "url")
        def c(text):   txt.insert("end", text, "code")
        def em(text):  txt.insert("end", text, "emphasis")
        def t(text):   txt.insert("end", text)

        h("【功能說明】\n")
        t("從公開資訊觀測站（MOPS）批次下載法人說明會簡報 PDF。\n"
          "輸入公司代號與日期範圍後，工具會自動判斷市場別\n"
          "（上市／上櫃／興櫃／公開發行），逐月掃描並下載所有符合的簡報。\n\n")

        h("【操作步驟】\n")
        t("1. 輸入公司代號（例："); em("2330"); t("）\n")
        t("2. 輸入日期範圍（格式："); em("YYYYMMDD"); t("，例：20150101 ~ 20260325）\n")
        t("3. 選擇儲存資料夾\n")
        t("4. 按「"); em("▶ 開始下載"); t("」\n\n")

        h("【檔案命名規則】\n")
        c("  20260115_zh.pdf   "); t("← 中文版（優先下載）\n")
        c("  20260115_en.pdf   "); t("← 英文版（無中文版時）\n")
        c("  20260115_zh_2.pdf "); t("← 同日第 2 場\n\n")

        h("【資料來源】\n")
        t("法說會查詢頁面：\n  "); u("https://mopsov.twse.com.tw/mops/web/t100sb02_1\n")
        t("PDF 下載路徑：\n  "); u("https://mopsov.twse.com.tw/nas/STR/<檔名>.pdf\n\n")

        h("【防爬蟲延遲】\n")
        t("若 MOPS 擋下請求導致查無資料，可勾選「"); em("防爬蟲延遲"); t("」，\n")
        t("每次查詢之間會隨機等待 "); em("1~3 秒"); t("。")

        txt.config(state="disabled")
        ttk.Button(frame, text="關閉", command=win.destroy, width=10).pack(pady=(12, 0))

    # ---- Placeholder 工具 ----
    def _ph_focus_in(self, entry: ttk.Entry, var: tk.StringVar, placeholder: str):
        if var.get() == placeholder:
            var.set("")
            entry.configure(foreground="black")

    def _ph_focus_out(self, entry: ttk.Entry, var: tk.StringVar, placeholder: str):
        if not var.get().strip():
            var.set(placeholder)
            entry.configure(foreground="grey")

    def _get_date_value(self, var: tk.StringVar) -> str:
        """取得日期值，若為 placeholder 則回傳空字串。"""
        v = var.get().strip()
        return "" if v == "YYYYMMDD" else v

    # ---- UI 互動 ----
    def _select_folder(self):
        path = filedialog.askdirectory(title="選擇儲存資料夾")
        if path:
            self.folder_var.set(path)

    def _open_output_folder(self):
        if self._output_folder and os.path.exists(self._output_folder):
            os.startfile(self._output_folder)

    # ---- 驗證輸入 ----
    def _validate_inputs(self) -> bool:
        co_id = self.co_id_var.get().strip()
        start = self._get_date_value(self.start_var)
        end = self._get_date_value(self.end_var)
        folder = self.folder_var.get().strip()

        if not co_id:
            messagebox.showerror("錯誤", "請輸入公司代號")
            return False
        if len(start) != 8 or not start.isdigit():
            messagebox.showerror("錯誤", "起始日期格式錯誤，請輸入 YYYYMMDD（例：20150101）")
            return False
        if len(end) != 8 or not end.isdigit():
            messagebox.showerror("錯誤", "結束日期格式錯誤，請輸入 YYYYMMDD（例：20260325）")
            return False
        if start > end:
            messagebox.showerror("錯誤", "起始日期不能晚於結束日期")
            return False
        if not folder:
            messagebox.showerror("錯誤", "請選擇儲存資料夾")
            return False
        if not os.path.isdir(folder):
            messagebox.showerror("錯誤", f"資料夾不存在：{folder}")
            return False
        return True

    # ---- 執行 ----
    def _start(self):
        if not self._validate_inputs():
            return

        co_id = self.co_id_var.get().strip()
        start = self._get_date_value(self.start_var)
        end = self._get_date_value(self.end_var)
        folder = self.folder_var.get().strip()

        # 重置 UI
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.btn_open_folder.pack_forget()
        self.progress_bar["value"] = 0
        self.progress_bar.config(mode="indeterminate")
        self.progress_bar.start(10)
        self.progress_label.config(text="偵測市場別中...")
        self.is_running = True
        self.btn_start.config(state="disabled")
        self._output_folder = folder

        t = threading.Thread(
            target=self._worker,
            args=(co_id, start, end, folder, self._companies),
            daemon=True,
        )
        t.start()

    def _worker(self, co_id: str, start: str, end: str, output_dir: str, companies: dict):
        """背景執行緒：偵測市場別 → 逐月掃描 → 下載"""
        try:
            months = date_range_to_months(start, end)
            total = len(months)

            # 偵測市場別（快取優先）
            if companies:
                self._log("[INFO] 查詢公司清單快取...")
            else:
                self._log("[INFO] 無快取，以試誤方式偵測市場別...")
            market = detect_market(co_id, months, companies)
            if market is None:
                self._done(False, output_dir, "查無此公司的法說會記錄，請確認公司代號是否正確。")
                return

            market_name = next(name for code, name in MARKET_CODES if code == market)
            self._log(f"[INFO] 市場別確認：{market_name}")

            # 切換進度條為確定模式
            self.msg_queue.put(("progress_mode", "determinate"))
            self._set_progress(0, total, f"掃描中 0 / {total} 個月")

            use_delay = self.delay_var.get()
            downloaded = 0
            for i, (year, month) in enumerate(months):
                label = f"{year}/{month}"
                if use_delay and i > 0:
                    time.sleep(random.uniform(1, 3))
                records = query_mops(market, year, month, co_id)

                if not records:
                    self._log(f"[掃描] {label}  無資料")
                    self._set_progress(i + 1, total, f"掃描中 {i + 1} / {total} 個月")
                    continue

                for rec in records:
                    date_str = rec["date"]
                    zh_url = rec["zh_url"]
                    en_url = rec["en_url"]

                    if not zh_url and not en_url:
                        self._log(f"[掃描] {label}  無簡報")
                        continue

                    # 中文優先，沒有才用英文
                    if zh_url:
                        url, lang = zh_url, "zh"
                    else:
                        url, lang = en_url, "en"

                    save_path = build_save_path(date_str, lang, output_dir)
                    filename = os.path.basename(save_path)

                    try:
                        download_pdf(url, save_path)
                        downloaded += 1
                        self._log(f"[完成] {label}  {filename}")
                    except requests.exceptions.RequestException as e:
                        self._log(f"[失敗] {label}  {e}")

                self._set_progress(i + 1, total, f"掃描中 {i + 1} / {total} 個月")

            self._done(True, output_dir, f"完成！共下載 {downloaded} 個檔案。")

        except Exception as e:
            self._done(False, output_dir, f"發生錯誤：{e}")

    # ---- 執行緒安全 UI 更新 ----
    def _log(self, msg: str):
        self.msg_queue.put(("log", msg))

    def _set_progress(self, current: int, total: int, label: str):
        self.msg_queue.put(("progress", (current, total, label)))

    def _done(self, success: bool, folder: str, message: str):
        self.msg_queue.put(("done", (success, folder, message)))

    def _poll_queue(self):
        """每 100ms 從 queue 拉訊息更新 UI"""
        try:
            while True:
                msg_type, data = self.msg_queue.get_nowait()
                if msg_type == "log":
                    self.log_text.config(state="normal")
                    self.log_text.insert("end", data + "\n")
                    self.log_text.see("end")
                    self.log_text.config(state="disabled")
                elif msg_type == "progress":
                    current, total, label = data
                    self.progress_bar["maximum"] = total
                    self.progress_bar["value"] = current
                    self.progress_label.config(text=label)
                elif msg_type == "progress_mode":
                    self.progress_bar.stop()
                    self.progress_bar.config(mode=data)
                elif msg_type == "done":
                    success, folder, message = data
                    self.is_running = False
                    self.progress_bar.stop()
                    self.btn_start.config(state="normal")
                    if success:
                        self.progress_label.config(text="完成")
                        self.btn_open_folder.pack()
                        messagebox.showinfo("完成", message)
                    else:
                        self.progress_label.config(text="發生錯誤")
                        messagebox.showerror("錯誤", message)
                elif msg_type == "cache_progress":
                    current, label = data
                    self.cache_progress["value"] = current
                    self.cache_label.config(text=label, foreground="gray")
                elif msg_type == "cache_ok":
                    self.cache_progress.grid_remove()
                    self.cache_label.config(text=data, foreground="gray")
                    self.btn_update_cache.config(state="normal")
                elif msg_type == "cache_err":
                    self.cache_progress.grid_remove()
                    self.cache_label.config(text=data, foreground="#C0392B")
                    self.btn_update_cache.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)


# ---- CTH Banner ----
def show_cth_banner():
    b = "\033[90m"
    c = "\033[96m"
    y = "\033[93m"
    r = "\033[0m"

    print(f"{b}/*  ================================  *\\{r}")
    print(f"{b} *                                    *{r}")
    print(f"{b} *    {c}██████╗████████╗██╗  ██╗{b}        *{r}")
    print(f"{b} *   {c}██╔════╝   ██║   ██║  ██║{b}        *{r}")
    print(f"{b} *   {c}██║        ██║   ███████║{b}        *{r}")
    print(f"{b} *   {c}██║        ██║   ██╔══██║{b}        *{r}")
    print(f"{b} *   {c}╚██████╗   ██║   ██║  ██║{b}        *{r}")
    print(f"{b} *    {c}╚═════╝   ╚═╝   ╚═╝  ╚═╝{b}        *{r}")
    print(f"{b} *                                    *{r}")
    print(f"{b} *          {y}created by CTH{b}            *{r}")
    print(f"{b}\\*  ================================  */{r}")
    print()


# ---- 入口 ----
def main():
    show_cth_banner()
    root = tk.Tk()
    # 置頂顯示，避免被其他視窗遮住 (Pitfall #8)
    root.attributes("-topmost", True)
    root.update()
    root.attributes("-topmost", False)
    EarningSlideApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
