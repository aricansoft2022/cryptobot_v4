"""Ensure ``src`` is importable when running pytest without installation.

This is a belt-and-suspenders fallback for the ``pythonpath`` setting in
``pyproject.toml`` so the test suite runs on any pytest version.
"""
import os
import sys

SRC = os.path.join(os.path.dirname(__file__), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
