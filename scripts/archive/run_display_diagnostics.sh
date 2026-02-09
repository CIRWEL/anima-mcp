#!/bin/bash
# Run display diagnostics to fix grey screen

cd "$(dirname "$0")/.."
python3 -m anima_mcp.display_diagnostics
