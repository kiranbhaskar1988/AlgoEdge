@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
color 0A
echo.
echo  ============================================================
echo   AlgoEdge - Windows Installer (Python 3.10/3.11/3.12)
echo  ============================================================
echo.
echo [1/6] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found.
    echo  Download Python 3.12 from: https://www.python.org/downloads/
    echo  IMPORTANT: Tick "Add Python to PATH" during install.
    pause & exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Found Python %PYVER%
echo.
echo [2/6] Creating virtual environment...
if exist venv rmdir /s /q venv
python -m venv venv
if %errorlevel% neq 0 ( echo  ERROR creating venv. & pause & exit /b 1 )
echo  Created.
echo.
echo [3/6] Activating...
call venv\Scripts\activate.bat
if %errorlevel% neq 0 (
    echo  ERROR activating venv. Run PowerShell as Admin and type:
    echo  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
    pause & exit /b 1
)
echo  Activated.
echo.
echo [4/6] Upgrading pip...
python -m pip install --upgrade pip --quiet --no-warn-script-location
echo  pip ready.
echo.
echo [5/6] Installing packages (no compilation needed)...
echo  numpy...
pip install "numpy>=1.26.0" --prefer-binary --quiet
echo  pandas...
pip install "pandas>=2.2.0" --prefer-binary --quiet
echo  pandas-ta...
pip install "pandas-ta>=0.4.67b0" --prefer-binary --quiet
echo  smartapi-python...
pip install "smartapi-python>=1.3.9" --prefer-binary --quiet
echo  pyotp...
pip install "pyotp>=2.9.0" --prefer-binary --quiet
echo  websocket-client...
pip install "websocket-client>=1.7.0" --prefer-binary --quiet
echo  flask...
pip install "flask>=3.0.0" "flask-socketio>=5.3.0" --prefer-binary --quiet
echo  utilities...
pip install "python-dotenv>=1.0.0" "schedule>=1.2.0" "requests>=2.31.0" "logzero>=1.7.0" "colorama>=0.4.6" "tabulate>=0.9.0" "python-dateutil>=2.9.0" "pytz>=2024.1" --prefer-binary --quiet
echo  All packages installed.
echo.
echo [6/6] Setup config files...
if not exist .env copy .env.example .env >nul && echo  Created .env && notepad .env
if not exist logs mkdir logs
if not exist data mkdir data
echo.
echo [Verifying installation...]
python verify.py
echo.
echo  ============================================================
echo   DONE! Next steps:
echo   1. Fill in .env with your Angel One credentials
echo   2. python verify.py
echo   3. python main.py --paper
echo   4. Open http://localhost:5000
echo  ============================================================
echo.
pause
