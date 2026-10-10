"""Convenience runner: python obf.py INPUT -o OUTPUT [options]."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from jarobf.cli import main

if __name__ == "__main__":
    sys.exit(main())
