# Repository guide

## Entry points and checks

- Start with `README.md`, `docs/ARCHITECTURE.md`, and `docs/TECH_DECISIONS.md`.
- Build the app with `app.main:create_app --factory`; initialize providers in lifespan.
- Keep transport in `app/providers/`, orchestration in `app/services/`, HTTP contracts in `app/api/`.
- Run `make install`, `make lint test demo` in this repository root. Dependencies belong in `.venv`.
- Use `uv lock --default-index https://pypi.org/simple` after dependency changes; export runtime and dev
  requirements with `uv export --frozen [--extra dev] --no-emit-project --no-hashes -o ...`.

## Implementation notes

- Use `httpx.ASGITransport` with explicit app lifespan in async API tests. The installed Starlette
  deprecates httpx-backed TestClient; do not suppress that warning to make tests pass.
- Keep request middleware pure ASGI so streaming disconnects reach StreamingResponse.
- Provider stream generators must support aclose; preserve cancellation and semaphore release.
- Prove incrementality/cancellation with `tests/test_http_integration.py`, not buffered ASGI responses.
- Do not replay a stream after start. Keep Mock simulation explicit and usage unknown when absent.
- Keep Settings `hide_input_in_errors=True`; startup validation errors must not print credentials.
- Keep CPU/offline Mock as the default demo; do not enable paid endpoints during routine verification.

## Publication

- Review staged files and run `.venv/bin/python -m scripts.privacy_check` before public pushes.
- Commit no `.env`, machine-specific paths, private endpoint URLs, model weights, logs or credentials.
- Report real provider/Docker/CI validation only after running it. Never infer performance from smoke tests.

## Benchmarks

- `make benchmark-mock-quick` is the GPU-free smoke protocol; `make benchmark-mock` collects three repeats.
- Run actual Ollama experiments with one loaded model, context 1024, initial client concurrency 1.
- Keep `benchmarks/data/tasks.json` and its grader fixed after observing model answers; introduce a new
  dataset/protocol version for changes. Repeated trials do not increase the number of unique tasks.
- Preserve socket family with `serve(sockets=[sock])` in the subprocess harness. The installed Uvicorn
  `fd=` branch reconstructs AF_UNIX sockets and biased the initial TCP latency trial.
- Raw benchmark output is local by default; publish only reviewed run directories and measured screenshots.
- Use source snapshots/hashes when a run has a dirty worktree. Never update raw measurements to fit a narrative.
