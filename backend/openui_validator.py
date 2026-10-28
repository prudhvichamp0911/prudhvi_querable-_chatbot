"""Server-side validation with the official OpenUI parser.

Runs ``openui_test/scripts/openui-validator.mjs`` as one long-lived Node
process and talks to it over stdin/stdout (one JSON line per request). The
parser is ``createParser`` from ``@openuidev/lang-core`` with the same
``openuiChatLibrary`` the browser renders, so "valid" here means the
renderer will show every component.

If Node or the frontend dependencies are missing, ``validate`` returns
``None`` and callers fall back to the Python sanitizer alone.
"""

import json
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from backend.observability import logger

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "openui_test"
SCRIPT = FRONTEND_DIR / "scripts" / "openui-validator.mjs"

_process = None
_lock = threading.Lock()
_disabled_reason = None


def _start():
    global _process, _disabled_reason
    node = shutil.which("node")
    if not node:
        _disabled_reason = "node not found"
        return None
    if not (FRONTEND_DIR / "node_modules" / "@openuidev" / "lang-core").exists():
        _disabled_reason = "frontend dependencies not installed (npm install in openui_test/)"
        return None
    _process = subprocess.Popen(
        [node, str(SCRIPT)],
        cwd=str(FRONTEND_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    return _process


def validate(text):
    """Return the parser verdict dict, or None if validation is unavailable."""

    global _process
    with _lock:
        if _disabled_reason:
            return None
        try:
            if _process is None or _process.poll() is not None:
                if _start() is None:
                    logger.warning("OpenUI validator disabled: %s", _disabled_reason)
                    return None
            request_id = uuid.uuid4().hex
            _process.stdin.write(json.dumps({"id": request_id, "text": text}) + "\n")
            _process.stdin.flush()
            line = _process.stdout.readline()
            if not line:
                raise RuntimeError("validator exited")
            verdict = json.loads(line)
            if verdict.get("id") != request_id:
                raise RuntimeError("validator response out of order")
            return verdict
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning("OpenUI validator failed: %s", error)
            if _process is not None:
                _process.kill()
            _process = None
            return None


def status():
    if _disabled_reason:
        return f"disabled: {_disabled_reason}"
    return "ready" if _process is not None and _process.poll() is None else "idle"
