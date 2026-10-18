@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

set "PY_CMD=python"
if exist ".venv\Scripts\python.exe" set "PY_CMD=.venv\Scripts\python.exe"

for %%D in (data\logs models\voices) do if not exist "%%D" mkdir "%%D"

echo ====================================================
echo      Đang khởi động TTS Service (Ngọc Huyền)
echo      Địa chỉ: http://127.0.0.1:8010
echo ====================================================
echo.

"%PY_CMD%" -m uvicorn tts.server:app --host 127.0.0.1 --port 8010 --workers 1
pause
