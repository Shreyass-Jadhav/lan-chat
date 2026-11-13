@echo off
cd /d "%~dp0"
python -m pip install -r requirements-tls.txt --quiet
python make_cert.py
pause
