@echo off
rem Double-click to open the local UI in your browser (Windows).
chcp 65001 >nul
cd /d "%~dp0"
where ffmpeg >nul 2>nul || (echo ffmpeg is missing. Install it in a terminal with:  winget install Gyan.FFmpeg & echo then open a new window and run this file again. & pause & exit /b 1)
where uv >nul 2>nul || (echo uv is missing. Install it in a terminal with:  winget install astral-sh.uv & echo then open a new window and run this file again. & pause & exit /b 1)
echo Preparing the AI engine. The first time this downloads about 1 GB and takes a few minutes.
uv run -q --script engine\nemotron.py --help >nul || (echo Could not prepare the AI engine, see the message above. & pause & exit /b 1)
uv run --script ui\server.py
pause
