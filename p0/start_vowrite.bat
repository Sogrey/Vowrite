@echo off
rem Vowrite GUI resident launcher (no console window)
start "" "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0vowrite_gui.py"
