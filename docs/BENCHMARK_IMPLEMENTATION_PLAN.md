# Benchmark implementation plan

1. Audit existing APIs/tests and local hardware; preserve existing behavior. Baseline 62 tests.
2. Add opt-in bounded TTL/LRU response cache, single-hop fallback and request metadata; default off.
3. Add native Ollama adapter with usage/timing metadata and bounded requests; keep existing adapters.
4. Implement A/B/C plus simulated D contract tests over real localhost TCP, fixed seed/workloads.
5. After Mock acceptance, start the installed Ollama with one loaded model, run Qwen2.5 0.5B/1.5B D/E
   at context 1024, output cap 64, initial concurrency 1, then 2 subject to memory guard.
6. Persist raw CSV/JSON, hardware/model/config manifests and per-repeat cold/warm summaries;
   generate offline HTML dashboard and screenshots, document failures/regressions, update CI.
7. Run tests/lint/demos and actual benchmarks; privacy review, commit and push normal updates.

Cold means process/model unloaded, not OS page-cache eviction. No paid API, no 3B requirement,
no synthetic performance numbers. Missing real model scenarios remain explicitly untested.
