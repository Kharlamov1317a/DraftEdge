@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo DraftEdge is starting.
echo Computer: http://localhost:8501
echo iPhone on the same Wi-Fi: find this computer's IPv4 address with ipconfig,
echo then open http://YOUR-IPV4:8501 in Safari.
echo Keep this window and the computer awake while using LAN mode.
echo.
streamlit run app.py --server.address=0.0.0.0 --server.port=8501
endlocal
