#!/bin/bash
cd "/Users/deebee/.hermes/hermes-agent/projects/ccf-chatbot/CCF Chatbot"
export PORT=9090
export USE_LLM=true
exec /Users/deebee/.hermes/hermes-agent/projects/ccf-chatbot/.venv/bin/python server.py