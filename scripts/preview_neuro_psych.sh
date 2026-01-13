#!/bin/bash
# Quick preview of neuro/psych framing doc

cd "$(dirname "$0")/.."

./scripts/preview_markdown.sh docs/NEURO_PSYCH_FRAMING.md html

# Auto-open in browser
open docs/NEURO_PSYCH_FRAMING.html 2>/dev/null || echo "Open docs/NEURO_PSYCH_FRAMING.html in your browser"

