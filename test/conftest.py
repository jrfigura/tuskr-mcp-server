import sys
from pathlib import Path

# src/main.py imports its sibling as a top-level `import tuskr_client`, so src/
# has to be importable in its own right before `src.main` can be loaded. Doing
# it here keeps the test modules free of import-order workarounds.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
