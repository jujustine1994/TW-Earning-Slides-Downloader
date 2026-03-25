# TW Earning Slides Downloader 啟動器

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$host.UI.RawUI.WindowTitle = "TW Earning Slides Downloader"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Clear-Host
Write-Host "[INFO] Starting TW Earning Slides Downloader..." -ForegroundColor Green
Write-Host ""

# ======================================
# [1/3] 檢查 Python
# ======================================
Write-Host "[1/3] 檢查 Python 環境..." -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[WARNING] 未偵測到 Python，本程式需要 Python 才能執行。" -ForegroundColor Yellow
    $ans = Read-Host "是否要立即安裝 Python？[Y/n] - 直接按 Enter 代表同意"
    if ($ans -eq "" -or $ans -ieq "Y") {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host "[INFO] 透過 winget 安裝 Python，請稍候..." -ForegroundColor Gray
            winget install --id Python.Python.3 -e --silent --accept-source-agreements --accept-package-agreements
        } else {
            Write-Host "[ERROR] 找不到 winget，請手動至 https://www.python.org/ 下載安裝後重新執行。" -ForegroundColor Red
            Read-Host "按 Enter 關閉"; exit 1
        }
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
        if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
            Write-Host "[INFO] 安裝完成，請關閉視窗後重新點兩下啟動檔。" -ForegroundColor Yellow
            Read-Host "按 Enter 關閉"; exit 0
        }
        Write-Host "[OK] Python 安裝完成。" -ForegroundColor Green
    } else {
        Write-Host "已取消。" -ForegroundColor Gray; Read-Host "按 Enter 關閉"; exit 1
    }
} else {
    $pyVer = python --version 2>&1
    Write-Host "[OK] $pyVer 已安裝。" -ForegroundColor Green
}

# ======================================
# [2/3] 檢查 uv
# ======================================
Write-Host "[2/3] 檢查 uv 套件管理工具..." -ForegroundColor Cyan
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[WARNING] 找不到 uv，正在安裝..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + $env:PATH
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] uv 安裝失敗，請關閉視窗後重新點兩下啟動檔再試。" -ForegroundColor Red
        Read-Host "按 Enter 關閉"; exit 1
    }
    Write-Host "[OK] uv 安裝完成。" -ForegroundColor Green
} else {
    $uvVer = uv --version
    Write-Host "[OK] $uvVer 已安裝。" -ForegroundColor Green
}

# ======================================
# [3/3] 檢查虛擬環境
# ======================================
Write-Host "[3/3] 檢查虛擬環境..." -ForegroundColor Cyan
if (-not (Test-Path "venv")) {
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Cyan
    Write-Host "    法說會簡報下載器 - 首次安裝說明" -ForegroundColor Cyan
    Write-Host "  ============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  接下來程式會自動幫你安裝以下東西：" -ForegroundColor White
    Write-Host ""
    Write-Host "    1. Python 虛擬環境（venv）" -ForegroundColor Yellow
    Write-Host "       讓這個工具有獨立乾淨的執行空間，不影響電腦其他程式" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    2. requests" -ForegroundColor Yellow
    Write-Host "       用來連線公開資訊觀測站並下載 PDF 檔案" -ForegroundColor Gray
    Write-Host ""
    Write-Host "    3. beautifulsoup4" -ForegroundColor Yellow
    Write-Host "       用來解讀網頁內容，找出 PDF 下載連結" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  全程只需要一直按 Enter 同意即可。" -ForegroundColor Green
    Write-Host "  如果有任何疑問，可以把這段說明貼給 AI 詢問。" -ForegroundColor Green
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Cyan
    Write-Host ""
    $ans = Read-Host "[WARNING] 找不到虛擬環境，現在建立並安裝套件？[Y/n] - 直接按 Enter 代表同意"
    if ($ans -eq "" -or $ans -ieq "Y") {
        Write-Host "[INFO] 建立虛擬環境中..." -ForegroundColor Gray
        uv venv venv
        Write-Host "[INFO] 安裝套件中..." -ForegroundColor Gray
        uv pip install -r requirements.txt --python venv\Scripts\python.exe
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] 套件安裝失敗，請確認網路連線後重新執行。" -ForegroundColor Red
            Read-Host "按 Enter 關閉"; exit 1
        }
        Write-Host "[OK] 套件安裝完成。" -ForegroundColor Green
    } else {
        Write-Host "已取消。" -ForegroundColor Gray; Read-Host "按 Enter 關閉"; exit 1
    }
} else {
    Write-Host "[OK] 虛擬環境已就緒，檢查套件更新..." -ForegroundColor Green
    $broken = Get-ChildItem "venv\Lib\site-packages" -Directory -Filter "*dist-info" -ErrorAction SilentlyContinue | Where-Object {
        -not (Test-Path (Join-Path $_.FullName "METADATA"))
    }
    foreach ($dir in $broken) {
        Write-Host "[INFO] 清理損壞的套件資訊：$($dir.Name)" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $dir.FullName
    }
    uv pip install -r requirements.txt --python venv\Scripts\python.exe -q
}

. ".\venv\Scripts\Activate.ps1"

Write-Host ""
Write-Host "[START] 啟動中，請保持此視窗開啟..." -ForegroundColor Green
Write-Host ""

python main.py
$exitCode = $LASTEXITCODE

if (Test-Path "__pycache__") { Remove-Item -Recurse -Force "__pycache__" }

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] 程式意外停止，請回報上方錯誤訊息。" -ForegroundColor Red
    Read-Host "按 Enter 關閉"
} else {
    Write-Host ""
    Write-Host "5 秒後自動關閉..." -ForegroundColor Gray
    Start-Sleep -Seconds 5
}
