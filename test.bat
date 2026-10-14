@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto nosetup
call ".venv\Scripts\activate.bat"
echo Running the automated tests ...
python -m pytest > test-output.txt 2>&1
type test-output.txt
echo.
echo Running the real-computer checks (reads this PC; sends a few harmless network probes) ...
python -m pytest tests\test_system_integration.py -s > integration-output.txt 2>&1
type integration-output.txt
echo.
echo ------------------------------------------------------------
echo Results were also saved next to this file:
echo   test-output.txt         (automated tests)
echo   integration-output.txt  (what PCInsight found on this PC)
echo Send me those two files if anything failed.
pause
exit /b 0
:nosetup
echo PCInsight is not set up yet. Double-click setup.bat first.
pause
exit /b 1
