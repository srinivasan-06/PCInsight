@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto nosetup
call ".venv\Scripts\activate.bat"
echo.
echo ============================================================
echo  PART 1 - automated tests with MOCKED system data
echo  (shows PCInsight handles problems correctly; does NOT prove
echo   hardware detection works on this or any other PC)
echo ============================================================
python -m pytest -m "not integration" > test-output.txt 2>&1
type test-output.txt
echo.
echo ============================================================
echo  PART 2 - REAL-COMPUTER integration tests (this PC only)
echo  Reads this PC and sends a few harmless network probes.
echo  Tip: run this once normally and once "as administrator"
echo  to see how permissions change what can be read.
echo ============================================================
python -m pytest -m integration -s -rs > integration-output.txt 2>&1
type integration-output.txt
echo.
echo ------------------------------------------------------------
echo Results were also saved next to this file:
echo   test-output.txt         (mocked automated tests)
echo   integration-output.txt  (what PCInsight found on this PC)
echo Send me those two files if anything failed.
pause
exit /b 0
:nosetup
echo PCInsight is not set up yet. Double-click setup.bat first.
pause
exit /b 1
