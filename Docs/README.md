# Docs

A sample of the planning and specification documents this project is built from.

## Plans

Every feature in this project starts as a numbered implementation plan (`plans/<number>-<name>.md` in the full repo) before any code is written — task-by-task, tests-first, with explicit interfaces and constraints. Two examples are included here:

- **`045-reverb-effect-phase-a.md`** — adding the Dattorro plate reverb effect. Shows the general shape of these plans: an offline DSP port verified against a public-domain reference implementation, a mono/stereo upmixing edge case worked out up front, and a task broken down with failing tests written before the implementation.
- **`099-formant-live-preview.md`** — adding a real-time Web Audio preview for the Formant effect. A more involved example: a hand-written FFT plus LPC-based envelope warping in the browser, deliberately *not* a 1:1 port of the backend's `pyworld`-based algorithm, with the tradeoff reasoned through explicitly.

These are two out of over a hundred plans (111 as of this writing) written over the project's development.

## Specifications

- **`backend_specification_1.md`** — module layout, engine integration, and the desktop-packaging setup (Tauri/PyInstaller).
- **`frontend-specification.md`** — the full data model, API route table, and client-side state management, written as a reference for rebuilding or migrating the frontend.

See the main [README](../README.md) for the project overview, screenshots, and setup instructions.
