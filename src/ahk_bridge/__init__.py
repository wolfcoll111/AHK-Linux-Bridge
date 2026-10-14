"""AHK-Linux-Bridge: AHK v2 subset runtime for Linux."""
from .parser import parse_script, Script, HOTKEY_RE, HOTSTRING_RE
from .runtime import Runtime
from .input_abstract import InputSimulator, detect_backend

__all__ = ["parse_script", "Script", "Runtime", "InputSimulator", "detect_backend"]
__version__ = "0.1.0"
