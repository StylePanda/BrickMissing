@echo off
setlocal
title BrickMissing 8.0 - Beenden
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if(-not $c){Write-Host 'BrickMissing laeuft nicht.'; exit 0}; $p=Get-Process -Id $c.OwningProcess -ErrorAction Stop; if($p.ProcessName -notmatch 'python'){Write-Error 'Port 8000 wird nicht von Python verwendet. Abbruch.'; exit 2}; Stop-Process -Id $p.Id; Write-Host 'BrickMissing Django wurde beendet.'"
if errorlevel 1 pause
