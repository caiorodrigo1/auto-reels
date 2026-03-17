@echo off
cd /d C:\Projects\auto-reels
C:\Users\caior\.local\bin\poetry.exe run auto-reels run >> C:\Projects\auto-reels\scheduler.log 2>&1
