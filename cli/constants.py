"""CLI-level constants.

SHELL names the active renderer shell environment.
When a Tauri compositor arrives, this becomes "shell-tauri" or is
set at mount time by the compositor. One place, one change.
"""

SHELL = "shell-web"
