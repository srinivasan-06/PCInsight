@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto nosetup
call ".venv\Scripts\activate.bat"
python -m pcinsight
if errorlevel 1 pause
exit /b %errorlevel%
:nosetup
echo PCInsight is not set up yet. Double-click setup.bat first.
pause
exit /b 1
