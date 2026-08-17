"""Make the repo root importable so tests can `import ui.server` (the UI package
is not installed the way `steemer` is). Works locally and in the reaper container.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
