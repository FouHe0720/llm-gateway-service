#!/usr/bin/env bash
set -euo pipefail
# Uses an existing official Ollama installation. No sudo, download or model deletion.
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_CONTEXT_LENGTH=1024
export OLLAMA_MAX_QUEUE=8
export OLLAMA_NOPRUNE=true
export OLLAMA_NO_CLOUD=true
exec ollama serve
