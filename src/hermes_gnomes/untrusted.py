"""Prompt injection defense helpers.

Third-party content (customer DMs, social comments, scraped text) is wrapped in
<UNTRUSTED_INPUT> tags before reaching the LLM. The system rule in SOUL.md says
the LLM must never follow instructions inside those tags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape

# Substrings commonly associated with prompt injection attempts.
# Case-insensitive literal search. Cheap first-line check before LLM.
INJECTION_MARKERS = [
    "ignore previous",
    "ignore all previous",
    "disregard previous",
    "disregard above",
    "system override",
    "system:",
    "you are now",
    "you are a helpful",
    "jailbreak",
    "developer mode",
    "dan mode",
    "new instructions",
    "reveal your prompt",
    "reveal your system",
    "print your instructions",
    "print your prompt",
    "<untrusted",
    "</untrusted",
]


@dataclass
class UntrustedCheckResult:
    """Result of scanning LLM output for leaks or policy violations."""

    safe: bool
    reasons: list[str] = field(default_factory=list)


def wrap_untrusted(text: str, source: str, **attributes: str) -> str:
    """Wrap third-party text in an <UNTRUSTED_INPUT> tag.

    The inner text has any literal <UNTRUSTED_INPUT> or </UNTRUSTED_INPUT>
    substrings HTML-escaped so an attacker cannot close the wrapper.
    """
    safe_text = text.replace("<UNTRUSTED_INPUT", "&lt;UNTRUSTED_INPUT").replace(
        "</UNTRUSTED_INPUT>", "&lt;/UNTRUSTED_INPUT&gt;"
    )
    attr_str = f' source="{escape(source, quote=True)}"'
    for k, v in attributes.items():
        attr_str += f' {k}="{escape(str(v), quote=True)}"'
    return f"<UNTRUSTED_INPUT{attr_str}>\n{safe_text}\n</UNTRUSTED_INPUT>"


def scan_for_injection_markers(text: str) -> list[str]:
    """Return the list of injection markers found in text (case-insensitive)."""
    lowered = text.lower()
    return [marker for marker in INJECTION_MARKERS if marker in lowered]


def check_output_for_leaks(output: str) -> UntrustedCheckResult:
    """Scan LLM output before publication. Catches confused-model errors.

    Returns unsafe if:
    - Output contains a stray </UNTRUSTED_INPUT> tag (LLM got confused).
    - Output appears to reveal system prompt content.
    """
    reasons: list[str] = []

    if re.search(r"</?UNTRUSTED_[A-Z_]+>", output):
        reasons.append("leftover_untrusted_tag")

    system_leak_patterns = [
        r"system prompt",
        r"my instructions",
        r"my system",
        r"i was told to",
        r"i was instructed",
    ]
    lowered = output.lower()
    if any(re.search(p, lowered) for p in system_leak_patterns):
        reasons.append("system_prompt_leak")

    return UntrustedCheckResult(safe=not reasons, reasons=reasons)
