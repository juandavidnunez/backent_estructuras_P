@echo off
echo Starting SkyRoute Backend...
python -m uvicorn main:app --reload
pause
