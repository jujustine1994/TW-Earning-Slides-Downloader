# CHANGELOG

## 現狀

功能已完整實作：
- [x] 市場別自動偵測（上市/上櫃/興櫃/公開發行）
- [x] 日期範圍逐月掃描
- [x] 中文優先、英文 fallback
- [x] 命名 YYYYMMDD_zh.pdf / YYYYMMDD_en.pdf（含衝突流水號）
- [x] Tkinter GUI + 背景 thread
- [x] 公司清單本地快取（company_market.json）
- [x] 防爬蟲延遲開關（1~3 秒隨機間隔）
- [x] 說明視窗（含彩色重點標示）

## 更新記錄

### 2026-03-25（第二版）
- 修正：MOPS 查詢 URL 改為正確的 AJAX 端點（ajax_t100sb02_1）
- 修正：POST 加入 firstin=1，修正查無資料問題
- 修正：PDF URL 由相對路徑補全為完整 URL（/nas/STR/...）
- 修正：parse_roc_date 支援多天日期格式（115/03/03 ~ 115/03/06）
- 修正：download_pdf 加入 verify=False（MOPS SSL 憑證問題）
- 新增：日期欄位 placeholder 提示（YYYYMMDD）
- 新增：防爬蟲延遲開關（勾選後每次查詢間隔 1~3 秒）
- 新增：說明視窗（功能說明、操作步驟、資料來源、含彩色重點）
- 更新：unit tests 配合 Session mock 調整（21 tests passing）

### 2026-03-25
- 新增：專案初始化、設計文件、實作計畫
- 新增：launcher（BAT + PS1）
- 新增：main.py（完整功能）
- 新增：unit tests（21 tests passing）
- 新增：README.md、ARCHITECTURE.md
