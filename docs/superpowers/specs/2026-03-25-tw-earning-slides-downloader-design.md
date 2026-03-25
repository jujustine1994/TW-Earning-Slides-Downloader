# TW Earning Slides Downloader — 設計文件

**日期：** 2026-03-25
**類型：** Windows 工具（Python + Tkinter）

---

## 概述

從公開資訊觀測站（MOPS）批次下載法人說明會簡報 PDF。使用者輸入公司代號、日期範圍與儲存資料夾，工具自動判斷市場別，逐月掃描並下載所有符合的簡報。

---

## 架構與檔案結構

```
TW Earning Slides Downloader/
├── 法說會簡報下載器.bat       ← 雙擊入口（純英文路徑呼叫 launcher.ps1）
├── launcher.ps1               ← 環境檢查 + venv 建立 + 啟動 main.py
├── main.py                    ← Tkinter GUI + 下載邏輯
├── requirements.txt           ← requests, beautifulsoup4
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── PITFALLS.md
├── TODO.md
└── venv/                      ← uv 建立，不進 git
```

單一 `main.py`，不拆模組。Python 套件用 uv 管理。HTML 解析使用 Python 內建 `html.parser`（不需額外安裝 lxml）。

---

## GUI 介面

參考 SnapTranscript 的 LabelFrame + ttk 風格，由上到下：

```
┌──────────────────────────────────────┐
│  查詢條件                             │
│  公司代號：[        ]                 │
│  日期範圍：[20150101]  ~  [20260325]  │
│  儲存資料夾：[______________] [選擇]   │
├──────────────────────────────────────┤
│  ▶  開始下載                          │
├──────────────────────────────────────┤
│  處理進度                             │
│  [=========   ] 掃描中 45 / 135 個月  │
│  ┌─ log 區 ──────────────────────┐   │
│  │ [INFO] 偵測市場別：上市        │   │
│  │ [掃描] 2015/01  無資料         │   │
│  │ [完成] 2015/02  20150215_zh.pdf│   │
│  │ [掃描] 2015/03  無簡報         │   │
│  └────────────────────────────────┘  │
│  [開啟資料夾]（完成後顯示）            │
└──────────────────────────────────────┘
```

- 日期範圍：兩個獨立 Entry，格式 YYYYMMDD，錯誤時 messagebox 提示
- 開始按鈕：執行中停用，完成後恢復
- log 區：ScrolledText（唯讀），每月一行

---

## 核心邏輯

### 1. 計算月份清單

從日期範圍算出所有 YYYY/MM 組合，依時間順序排列（舊→新）。
例如 20150101～20260325 → 135 個月。

### 2. 市場別自動偵測

**定義：** 從日期範圍的結束月往前掃，找到第一個 MOPS 查詢有回傳資料列的月份，確認其市場別，並鎖定後續所有查詢使用同一市場別。

**偵測流程：**
對某一個月，依序 POST 四個市場別（上市→上櫃→興櫃→公開發行）：
- 若 HTML 回傳的表格有包含該公司代號的資料列 → 此市場別正確，鎖定
- 若表格為空或無符合列 → 換下一個市場別
- 四個都無資料 → **靜默跳過**（不寫 log），往前再試上一個月

> **注意：** 偵測階段跳過的月份**不寫任何 log**。「無資料」/「無簡報」log 只在主掃描階段產生。

偵測期間進度條顯示 indeterminate 模式，log 顯示 `[INFO] 偵測市場別中...`。
偵測完成後 log 顯示 `[INFO] 市場別確認：上市`，進度條切換為確定模式（0 / N 個月）。

若掃完整個日期範圍都找不到任何資料，彈出錯誤視窗：「查無此公司的法說會記錄，請確認公司代號是否正確。」

### 3. 逐月查詢

POST 到 `https://mopsov.twse.com.tw/mops/web/t100sb02_1`
（`mopsov` 子網域正確，為 MOPS 改版後的介面，非筆誤）

**請求格式：**
```
Content-Type: application/x-www-form-urlencoded
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
```

**POST 參數：**
| 參數 | 說明 | 範例 |
|------|------|------|
| `market` | 市場代碼 | sii（上市）/ otc（上櫃）/ rotc（興櫃）/ pub（公開發行） |
| `year` | 民國年（西元年 - 1911） | 114 |
| `month` | 月份（不補零） | 1 |
| `co_id` | 公司代號 | 2330 |

解析回傳 HTML，用 `html.parser` + BeautifulSoup 找「法人說明會簡報內容」欄位的連結。

### 4. 資料狀態定義

| 狀態 | 定義 | log 顯示 |
|------|------|---------|
| 無資料 | MOPS 查無此公司在該月的任何法說會記錄（表格為空） | `[掃描] 2015/01  無資料` |
| 無簡報 | 有法說會記錄，但中英文 PDF 連結皆為空 | `[掃描] 2015/03  無簡報` |
| 完成 | 成功下載 PDF | `[完成] 2015/02  20150215_zh.pdf` |
| 失敗 | PDF 連結存在但下載失敗（HTTP 錯誤） | `[失敗] 2015/04  HTTP 404` |

### 5. 語言選擇

每筆記錄：
- 中文檔案連結存在 → 下載中文
- 中文連結不存在，英文連結存在 → 下載英文
- 兩者皆無 → 標記「無簡報」

### 6. 檔案命名規則

日期取自 HTML 表格的「召開法人說明會日期」欄，轉換為西元年格式。

| 情況 | 檔名 |
|------|------|
| 中文簡報（唯一） | `20260115_zh.pdf` |
| 英文簡報（fallback） | `20260115_en.pdf` |
| 同一天第 2 場（中文） | `20260115_zh_2.pdf` |
| 同一天第 2 場（英文） | `20260115_en_2.pdf` |

命名衝突處理：下載前以 `os.path.exists()` 檢查目標路徑（filesystem-based），若存在則加 `_2`、`_3` 流水號。不使用 in-memory 計數器，以確保重複執行時不會覆蓋先前下載的檔案。

### 7. PDF 下載

```python
try:
    response = requests.get(url, stream=True, headers=headers, timeout=30)
    response.raise_for_status()  # 4xx/5xx 拋出 HTTPError
    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
except requests.exceptions.RequestException as e:
    # 涵蓋 HTTPError、ConnectionError、Timeout 等所有網路錯誤
    log(f"[失敗] {date}  {e}")
    continue  # 繼續處理下一筆
```

下載失敗時 log 顯示錯誤訊息，繼續處理下一筆，不中斷整批下載。

### 8. 執行緒架構

背景 thread 執行所有網路請求與下載，透過 queue 傳訊息回主執行緒更新 UI（與 SnapTranscript 相同模式）。

訊息格式：
| 類型 | payload | 說明 |
|------|---------|------|
| `"log"` | `str` | 寫入 log 區的一行文字 |
| `"progress"` | `(current: int, total: int, label: str)` | 更新進度條數值與標籤文字 |
| `"done"` | `(success: bool, output_folder: str)` | 完成或失敗，觸發 UI 恢復與開啟資料夾按鈕 |

`launcher.ps1` 環境檢查範圍：Python 3.10 以上、uv 是否安裝（winget 自動安裝）、venv 是否存在（不存在則建立並安裝套件）。

---

## 套件清單

| 套件 | 用途 |
|------|------|
| requests | HTTP 查詢與 PDF 下載 |
| beautifulsoup4 | HTML 解析（使用內建 html.parser） |

標準函式庫：tkinter、threading、queue、datetime

---

## .gitignore

```
venv/
__pycache__/
*.pyc
.env
*.log
```

---

## CTH Banner

入口在 `main.py` 的 `main()` 函式，套用 Python 版 CTH Banner（從 signature.md 直接複製）。
