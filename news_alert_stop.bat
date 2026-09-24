@echo off
rem Stop the background news_alert (restart loop included).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'news_alert\.(bat|py)' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo stopped.
