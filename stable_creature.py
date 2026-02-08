"""
Backward-compatible wrapper.

The real implementation has moved to src/anima_mcp/stable_creature.py
so it's a proper package module with relative imports.

This wrapper exists so the Pi's systemd service keeps working
until it's updated to use the new entry point:
    anima-creature (defined in pyproject.toml)
"""
from src.anima_mcp.stable_creature import run_creature

if __name__ == "__main__":
    run_creature()
