import sys
from pathlib import Path

# src/main.py imports its sibling with a flat `import tuskr_client`, so src/
# has to be importable in its own right, not only as the `src` package.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
