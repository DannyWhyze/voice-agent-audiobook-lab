@echo off
setlocal

set "PROJECT_ROOT=%~dp0"

echo Starting engine (s2.cpp) in a new window...
start "s2.cpp engine" cmd /k "cd /d "%PROJECT_ROOT%src\engine" && s2.exe --server --host 0.0.0.0 --port 3030 -c 0 -m s2-pro-q8_0.gguf -t tokenizer.json --no-vram-swap"

echo Starting orchestrator (FastAPI) in a new window...
start "orchestrator" cmd /k "cd /d "%PROJECT_ROOT%" && uv run uvicorn src.orchestrator.main:app --host 0.0.0.0 --port 8000"

echo.
echo Both started in separate windows. The engine takes about 10-15 seconds
echo to load the model (watch its window for "Server starting on ...").
echo Once it's up, open http://127.0.0.1:8000/ in your browser.
