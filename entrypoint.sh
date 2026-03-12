#!/bin/bash
set -e

echo "=== Running seed_presets.py ==="
python seed_presets.py || echo "⚠ Seed failed (non-fatal), continuing..."

echo "=== Starting gunicorn ==="
exec gunicorn app:app --bind 0.0.0.0:10000 --workers 2 --timeout 300 --keep-alive 5
