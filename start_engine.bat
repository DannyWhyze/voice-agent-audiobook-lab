@echo off
setlocal

set "PROJECT_ROOT=%~dp0"

echo Starting engine (s2.cpp) in this window...
cd /d "%PROJECT_ROOT%src\engine"
s2.exe --server --host 0.0.0.0 --port 3030 -c 0 -m s2-pro-q8_0.gguf -t tokenizer.json --no-vram-swap
