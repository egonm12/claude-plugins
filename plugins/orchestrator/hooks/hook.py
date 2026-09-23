"""Entry point for every orchestrator hook: python3 hook.py <event>.

Reads the payload from stdin, runs the handler for the event and writes its
output. Any unexpected error exits 0 with no output, so a broken hook never
blocks a session and never shows a traceback.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from orchestrator_hooks import handlers, payload

        event = sys.argv[1] if len(sys.argv) > 1 else ""
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        handlers.debug_capture(event, raw, os.environ)
        result = handlers.run(event, payload.parse(raw), os.environ)
        if result.stdout:
            sys.stdout.buffer.write(result.stdout.encode("utf-8"))
            sys.stdout.buffer.flush()
        if result.stderr:
            sys.stderr.buffer.write(result.stderr.encode("utf-8"))
            sys.stderr.buffer.flush()
        return result.exit_code
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
