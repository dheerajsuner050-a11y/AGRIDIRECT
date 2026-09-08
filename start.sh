#!/bin/sh
# start.sh — Railway-compatible entrypoint
# Railway always injects $PORT. We bind to 0.0.0.0 so the reverse proxy can reach us.
exec uvicorn main:app --host 0.0.0.0 --port "$PORT"
