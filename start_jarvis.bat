@echo off
title J.A.R.V.I.S. — STARK INDUSTRIES
color 0B
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║     J.A.R.V.I.S. SYSTEM INITIALIZATION           ║
echo  ║     STARK INDUSTRIES // MALIBU-PRIMARY           ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  [1/3] Checking Python...
python --version 2>nul || (echo  ERROR: Python not found. Please install Python. & pause & exit /b)
echo.
echo  [2/3] Freeing port 8000 and installing dependencies...
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" 2>nul
timeout /t 1 /nobreak >nul
pip install -r requirements.txt -q
echo.
echo  [3/3] Starting J.A.R.V.I.S. Backend Server...
echo.
echo  System will open at: http://localhost:8000
echo  Press Ctrl+C to shutdown J.A.R.V.I.S.
echo.
set PYTHONUTF8=1
python server.py
pause
