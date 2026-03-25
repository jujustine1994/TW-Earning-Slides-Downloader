"""
TW Earning Slides Downloader — 法說會簡報批次下載工具
從公開資訊觀測站下載法人說明會 PDF，依日期範圍自動掃描。
"""

import os
import json
import queue
import threading
from datetime import date, datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import requests
from bs4 import BeautifulSoup


# ---- 常數 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MOPS_URL = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
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
    """
    parts = roc_date_str.strip().split("/")
    if len(parts) != 3:
        return ""
    roc_y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
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
def fetch_company_list() -> dict[str, str]:
    """
    從 MOPS 抓取四個市場的公司清單，回傳 {公司代號: market_code} 字典。
    失敗時拋出例外（由呼叫者顯示錯誤訊息）。
    """
    companies: dict[str, str] = {}
    fetch_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    for market_code, _ in MARKET_CODES:
        url = MARKET_LIST_URLS[market_code]
        resp = requests.get(url, headers=fetch_headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            co_id = cells[0].get_text(strip=True)
            # 公司代號：4-6 位數字或英數字，排除空值與中文標題列
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
    POST 到 MOPS 查詢單一月份的法說會記錄。
    回傳 list of {date: str (YYYYMMDD), zh_url: str, en_url: str}。
    表格為空或無符合列時回傳 []。
    """
    data = {
        "market": market,
        "year": str(roc_year(year)),
        "month": str(month),
        "co_id": co_id,
    }
    try:
        resp = requests.post(MOPS_URL, data=data, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
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

        # 中文檔案：column 6；英文檔案：column 7
        zh_link = cells[6].find("a")
        en_link = cells[7].find("a")
        zh_url = zh_link["href"] if zh_link and zh_link.get("href") else ""
        en_url = en_link["href"] if en_link and en_link.get("href") else ""

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
    response = requests.get(url, stream=True, headers=HEADERS, timeout=30)
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
        self.start_var = tk.StringVar(value="20150101")
        self.end_var = tk.StringVar(value="20260325")
        ttk.Entry(date_frame, textvariable=self.start_var, width=12).pack(side="left")
        ttk.Label(date_frame, text="  ~  ").pack(side="left")
        ttk.Entry(date_frame, textvariable=self.end_var, width=12).pack(side="left")

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
        self.cache_label = ttk.Label(cache_frame, text="公司清單：載入中...", foreground="gray")
        self.cache_label.pack(side="left")
        self.btn_update_cache = ttk.Button(cache_frame, text="立即更新", command=self._update_cache)
        self.btn_update_cache.pack(side="left", padx=(10, 0))

        # 開始按鈕
        frame_btn = tk.Frame(self.root)
        frame_btn.grid(row=1, column=0, pady=8)
        self.btn_start = ttk.Button(frame_btn, text="▶  開始下載", command=self._start, width=20)
        self.btn_start.pack(ipady=6)

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
            self.cache_label.config(text="公司清單：尚未建立，建議點「立即更新」", foreground="orange")
        else:
            age = cache_age_days(updated_at)
            display_date = f"{updated_at[:4]}-{updated_at[4:6]}-{updated_at[6:]}"
            if age > CACHE_MAX_DAYS:
                self.cache_label.config(
                    text=f"公司清單：{display_date}（已 {age} 天，建議更新）",
                    foreground="orange"
                )
            else:
                self.cache_label.config(
                    text=f"公司清單：{display_date}（{len(companies)} 家公司）",
                    foreground="gray"
                )

    def _update_cache(self):
        """手動更新公司清單（背景執行）。"""
        if self.is_running:
            messagebox.showwarning("提示", "下載進行中，請完成後再更新。")
            return
        self.btn_update_cache.config(state="disabled")
        self.cache_label.config(text="公司清單：更新中...", foreground="gray")

        def _worker():
            try:
                companies = fetch_company_list()
                save_company_list(companies)
                self._companies = companies
                updated_at = date.today().strftime("%Y%m%d")
                display_date = f"{updated_at[:4]}-{updated_at[4:6]}-{updated_at[6:]}"
                self.msg_queue.put(("cache_ok", f"公司清單：{display_date}（{len(companies)} 家公司）"))
            except Exception as e:
                self.msg_queue.put(("cache_err", f"更新失敗：{e}"))

        threading.Thread(target=_worker, daemon=True).start()

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
        start = self.start_var.get().strip()
        end = self.end_var.get().strip()
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
        start = self.start_var.get().strip()
        end = self.end_var.get().strip()
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

            downloaded = 0
            for i, (year, month) in enumerate(months):
                label = f"{year}/{month}"
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
                elif msg_type == "cache_ok":
                    self.cache_label.config(text=data, foreground="gray")
                    self.btn_update_cache.config(state="normal")
                elif msg_type == "cache_err":
                    self.cache_label.config(text=data, foreground="red")
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
