@echo off
cd /d "%~dp0"
python run_data_editor.py
if errorlevel 1 pause
