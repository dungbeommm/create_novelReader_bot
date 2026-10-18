@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set "PY_CMD=python"
if exist ".venv\Scripts\python.exe" set "PY_CMD=.venv\Scripts\python.exe"

if not exist ".env" (
    echo [THÔNG BÁO] Chưa tìm thấy file .env
    echo Đang tạo file .env từ .env.example...
    copy .env.example .env >nul
    echo.
    echo Vui lòng mở file .env và điền:
    echo   1. TELEGRAM_BOT_TOKEN (Token tạo từ @BotFather)
    echo   2. ALLOWED_USER_IDS (ID số Telegram của bạn, ví dụ lấy từ @userinfobot)
    echo.
    echo Sau khi điền xong, hãy chạy lại file này!
    echo.
    pause
    exit /b 1
)

for %%D in (data\telegram data\logs output_text output_audio models\translation models\voices) do if not exist "%%D" mkdir "%%D"

echo ====================================================
echo        Đang khởi động Telegram Bot...
echo ====================================================
echo Lưu ý: Nếu dùng chức năng tạo audio (mặc định), hãy chạy
echo thêm start_tts.bat ở một cửa sổ khác để tạo audio.
echo ====================================================
echo.

"%PY_CMD%" telegram/bot.py
pause
