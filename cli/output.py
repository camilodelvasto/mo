"""Formatted CLI output — ANSI colors and consistent structure for all commands."""
import sys

BOLD = '\033[1m'
DIM = '\033[2m'
CYAN = '\033[36m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
RED = '\033[31m'
RESET = '\033[0m'


def _supports_color() -> bool:
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"{code}{text}{RESET}" if _supports_color() else text


def header(command: str, content_name: str):
    """Print command header: what we're doing and to what."""
    print()
    print(f"{_c(BOLD, command)} {content_name}")


def detail(label: str, value: str):
    """Print an indented detail line with aligned columns."""
    padded = f"{label:<13}"
    print(f"  {_c(DIM, padded)} {value}")


def output_file(path: str):
    """Print the primary output file path."""
    print(f"  {_c(DIM, '→')} {_c(CYAN, path)}")


def output_dir(path: str):
    """Print the containing output directory."""
    print(f"  {_c(DIM, '  ')} {_c(DIM, path)}")


def note(text: str):
    """Print a note (e.g., PPTX effect disclaimer)."""
    print(f"  {_c(DIM, text)}")


def warning(text: str):
    """Print a warning: something the reader must act on (e.g., a staged deploy)."""
    print(f"  {_c(YELLOW, text)}")


def success(text: str):
    """Print a success message."""
    print(f"  {_c(GREEN, text)}")


def done():
    """Print trailing newline."""
    print()
