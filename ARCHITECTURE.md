# ARCHITECTURE

## 工具總覽

法說會簡報批次下載器。使用者提供公司代號與日期範圍，工具自動掃描 MOPS 並下載 PDF。

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `法說會簡報下載器.bat` | 雙擊入口，呼叫 launcher.ps1 |
| `launcher.ps1` | 環境檢查（Python、uv、venv）+ 啟動 main.py |
| `main.py` | 所有邏輯（日期計算、MOPS 查詢、PDF 下載）+ Tkinter GUI |
| `requirements.txt` | requests, beautifulsoup4 |
| `tests/test_logic.py` | 純函式單元測試（不含 GUI、不含真實 HTTP） |
| `venv/` | uv 建立的虛擬環境，不進 git |

## 執行流程

```
雙擊 BAT → launcher.ps1 → 環境檢查 → python main.py
  → show_cth_banner()
  → tk.Tk() + EarningSlideApp()
  → 使用者輸入 → 按「開始下載」
  → 背景 thread: detect_market() → query_mops() × N 月 → download_pdf()
  → queue → 主執行緒更新 UI
```

## 關鍵設定

| 變數 | 說明 |
|------|------|
| `MOPS_URL` | `https://mopsov.twse.com.tw/mops/web/t100sb02_1` |
| `MARKET_CODES` | `[("sii","上市"),("otc","上櫃"),("rotc","興櫃"),("pub","公開發行")]` |
| `HEADERS` | Content-Type + User-Agent for MOPS POST |

## HTML 解析邏輯

`query_mops()` POST 後解析 `<tr>` 列，以 `cells[0]` 比對公司代號篩選。
日期在 `cells[2]`（ROC 格式），PDF 連結在 `cells[6]`（中文）和 `cells[7]`（英文）。

**若 MOPS 改版導致欄位位移，需更新 column index 並記入 PITFALLS.md。**
