#!/bin/bash
# Start the CCF chatbot server with LLM-powered answers
cd "$(dirname "$0")"
source .venv/bin/activate

# Read OpenRouter API key from Hermes .env
HERMES_ENV="$HOME/.hermes/.env"
if [ -f "$HERMES_ENV" ]; then
    API_KEY=$(grep "^OPENROUTER_API_KEY=" "$HERMES_ENV" | head -1 | cut -d= -f2-)
fi

export USE_LLM=true
export OPENROUTER_API_KEY="$API_KEY"
export PORT=9090

echo "Starting CCF chatbot with LLM mode..."
echo "USE_LLM=true"
echo "OPENROUTER_API_KEY=${API_KEY:0:12}..."

python server.py