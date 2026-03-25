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
| `COMPANY_MARKET_FILE` | `company_market.json`，本地公司清單快取，不進 git |
| `CACHE_MAX_DAYS` | 90，快取超過此天數顯示警告 |

## 公司清單 URL

從 MOPS `t51sb01` 頁面取得，為靜態參數（已驗證無痕視窗可直接存取）。
若日後失效，需重新從瀏覽器 DevTools Network 面板抓取新的 `parameters=` 值，更新 `main.py` 的 `MARKET_LIST_URLS`。

| 市場別 | URL |
|--------|-----|
| 上市（sii） | `https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca765118e1d5d55f2907af83df59ae82756caca30645f4a87baa01551cc98a6ff0816cbaad9c5c8c6df699b1ac8bf50f27c999868a65d5f5dd71b407c4d61b426833ab8c` |
| 上櫃（otc） | `https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca7651189431092059e57ec5acce2508557bbb820645f4a87baa01551cc98a6ff0816cbaad9c5c8c6df699b1ac8bf50f27c999868a65d5f5dd71b407c4d61b426833ab8c` |
| 興櫃（rotc） | `https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca765118150b1250f6b0d18c5da95b58aafad725152f445b9d55dd4c51df9e26ea7918af4de96261009bdfefb47812fc6ed9b9145701ed44236616fb09e84fed0c84caa6` |
| 公開發行（pub） | `https://mopsov.twse.com.tw/mops/web/ajax_t51sb01?parameters=32b138d25ee38c00fbf70ec5a53724971d1df89c34d9a0ef54fddd0eca765118f332b2e68ee1973efdd894533684e6040645f4a87baa01551cc98a6ff0816cbaad9c5c8c6df699b1ac8bf50f27c999868a65d5f5dd71b407c4d61b426833ab8c` |

## HTML 解析邏輯

`query_mops()` POST 後解析 `<tr>` 列，以 `cells[0]` 比對公司代號篩選。
日期在 `cells[2]`（ROC 格式），PDF 連結在 `cells[6]`（中文）和 `cells[7]`（英文）。

**若 MOPS 改版導致欄位位移，需更新 column index 並記入 PITFALLS.md。**
