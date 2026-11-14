@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name ScreenToAgent ^
  --icon assets\ScreenToAgent.ico ^
  main.py

if errorlevel 1 (
  echo.
  echo Build failed.
  exit /b 1
)

echo.
echo Built: %CD%\dist\ScreenToAgent.exe
endlocal
