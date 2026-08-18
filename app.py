"""Local development entry point for alt_web01."""

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SOURCE_DIR))

from alt_web01 import create_app

app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
