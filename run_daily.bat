@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d C:\Projects\auto-reels
auto-reels run --languages en,es >> output\daily.log 2>&1
