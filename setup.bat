@echo off
setlocal
cd /d "%~dp0"
echo ===== PCInsight setup =====
where python >nul 2>nul
if errorlevel 1 goto nopython
if exist ".venv\Scripts\python.exe" goto havevenv
echo Creating the virtual environment ...
python -m venv .venv
if errorlevel 1 goto fail
:havevenv
call ".venv\Scripts\activate.bat"
echo Updating pip ...
python -m pip install --upgrade pip
echo Installing PCInsight and its requirements ...
python -m pip install -e ".[dev]"
if errorlevel 1 goto fail
echo.
echo Setup complete.
echo   run.bat   starts PCInsight
echo   test.bat  runs the tests and saves the results to text files
echo.
pause
exit /b 0
:nopython
echo Python was not found.
echo Install Python 3.10, 3.11 or 3.12 from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during installation, then run setup.bat again.
pause
exit /b 1
:fail
echo.
echo Something went wrong. Please copy the messages above and send them to me.
pause
exit /b 1
