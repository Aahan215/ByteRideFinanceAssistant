#!/usr/bin/env bash
# Run this on the ONE Mac that hosts the model.
set -euo pipefail

command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com/download"; exit 1; }

RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
echo "Detected ${RAM_GB}GB RAM"

echo "--> pulling router + planner (always safe)"
ollama pull qwen3:0.6b
ollama pull qwen3:8b

if [ "$RAM_GB" -ge 24 ]; then
  echo "--> pulling escalation model"
  ollama pull gpt-oss:20b
else
  echo "!! ${RAM_GB}GB is tight for a 20B model. Skipping gpt-oss:20b."
  echo "   Set LLM_ESCALATE=qwen3:14b, or route escalations to API credits."
fi

echo
echo "--> sharing Ollama on the LAN so your team can reach it"
echo "    launchctl setenv OLLAMA_HOST 0.0.0.0:11434"
echo "    then quit and reopen the Ollama app"
echo
IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<your-ip>")
echo "Teammates set:  LLM_BASE_URL=http://${IP}:11434/v1"
