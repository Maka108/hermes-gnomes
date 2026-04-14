"""Phase 0A stub entry point for hermes-gnomes.

Keeps systemd happy with a long-running process during Phase 0A. Phase 1
replaces this with the real event loop (Telegram polling, LLM adapter,
approval queue watcher, scheduler tick).
"""

from __future__ import annotations

import signal
import threading

_STOP_EVENT = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    """Signal handler must be reentrancy-safe: only set a flag."""
    _STOP_EVENT.set()


def main() -> int:
    """Wait on an Event until SIGTERM/SIGINT sets it, then exit cleanly."""
    print("hermes-gnomes Phase 0A stub: up. waiting for signal.", flush=True)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    _STOP_EVENT.wait()
    print("hermes-gnomes stub: signal received, exiting cleanly.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
