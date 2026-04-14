"""Phase 0A stub entry point for hermes-gnomes.

Keeps systemd happy with a long-running process during Phase 0A. Phase 1
replaces this with the real event loop (Telegram polling, LLM adapter,
approval queue watcher, scheduler tick).
"""

from __future__ import annotations

import signal
import sys
import time


def main() -> int:
    """Sleep forever, exiting gracefully on SIGTERM/SIGINT."""
    print("hermes-gnomes Phase 0A stub: up. sleeping until signaled.", flush=True)

    def _handle_signal(signum: int, _frame: object) -> None:
        print(f"hermes-gnomes stub: received signal {signum}, exiting.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
