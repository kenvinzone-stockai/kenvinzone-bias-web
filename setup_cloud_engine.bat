@echo off
chcp 65001 >nul
echo ========================================================
echo   KENVINZONE BIAS WEB - THIET LAP CLOUD ENGINE
echo ========================================================

set "SRC=%~dp0..\market-bias-platform"
set "DEST=%~dp0engine"

if not exist "%SRC%" (
    echo [LOI] Khong tim thay thu muc: %SRC%
    pause
    exit /b 1
)

echo [1/7] Sao chep thu muc core...
xcopy /E /I /Y "%SRC%\core" "%DEST%\core" >nul

echo [2/7] Sao chep thu muc bias...
xcopy /E /I /Y "%SRC%\bias" "%DEST%\bias" >nul

echo [3/7] Sao chep thu muc metrics...
xcopy /E /I /Y "%SRC%\metrics" "%DEST%\metrics" >nul

echo [4/7] Sao chep thu muc plugins...
xcopy /E /I /Y "%SRC%\plugins" "%DEST%\plugins" >nul

echo [5/7] Sao chep thu muc ingestion...
xcopy /E /I /Y "%SRC%\ingestion" "%DEST%\ingestion" >nul

echo [6/7] Sao chep thu muc scripts...
xcopy /E /I /Y "%SRC%\scripts" "%DEST%\scripts" >nul

echo [7/7] Sao chep database SQLite market_bias.db...
if not exist "%DEST%\data" mkdir "%DEST%\data"
copy /y "%SRC%\data\market_bias.db" "%DEST%\data\market_bias.db" >nul

echo ========================================================
echo  DA THIET LAP XONG CLOUD ENGINE VAO KENVINZONE-BIAS-WEB!
echo  Toan bo ma nguon tinh toan da san sang trong thu muc engine.
echo ========================================================
pause
