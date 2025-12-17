comandos = [
cd onedrive; cd desktop; cd "sistema cam"; clear; python main.py
]
@echo off
cd /d "%USERPROFILE%\OneDrive\Desktop\sistema cam"
cls
call venv\Scripts\activate
python main.py
pause
