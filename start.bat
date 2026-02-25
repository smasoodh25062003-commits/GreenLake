@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
pip install -r requirements.txt
python main.py
pause
