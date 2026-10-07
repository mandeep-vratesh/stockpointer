@echo off
setlocal

for /f %%D in ('powershell -NoProfile -Command "$d=[datetime]'2026-06-04'; $end=[datetime]'2026-10-04'; while($d -le $end){ if($d.DayOfWeek -notin @('Saturday','Sunday') -and $d -ne [datetime]'2026-09-14'){ $d.ToString('yyyy-MM-dd') }; $d=$d.AddDays(1) }"') do (
    echo.
    echo ==========================================
    echo Processing %%D
    echo ==========================================

    python ../main.py --date %%D --skip-upload

    if errorlevel 1 (
        echo [ERROR] %%D failed - continuing...
    ) else (
        echo [SUCCESS] %%D completed
    )
)

echo.
echo All dates processed.
pause