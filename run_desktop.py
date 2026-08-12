"""PyInstaller entry point: runs the orchestrator as a standalone executable."""

from __future__ import annotations

import multiprocessing

import uvicorn

from src.orchestrator.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000)
