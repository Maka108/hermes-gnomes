"""Prompt injection defense helpers.

Three-layer defense for third-party content reaching the LLM:

1. **wrap_untrusted** — pre-LLM structural escape. Wraps text in an
   <UNTRUSTED_INPUT> tag and mangles any literal UNTRUSTED_* tags in the
   content (case-insensitive, whitespace-tolerant) so attackers can't close
   the wrapper or forge a new one.
2. **scan_for_injection_markers** — cheap pre-LLM keyword screen.
   Substring match against a list of known jailbreak phrases.
3. **check_output_for_leaks** — post-LLM leak detector. Catches
   confused-model errors that leak system prompt content or leave
   leftover UNTRUSTED_* tags in publishable output.

The system rule in SOUL.md tells the LLM never to follow instructions
inside <UNTRUSTED_*> tags. This module enforces the wrapping contract and
provides the output-side tripwire.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape

__all__ = [
    "INJECTION_MARKERS",
    "UntrustedCheckResult",
    "check_output_for_leaks",
    "scan_for_injection_markers",
    "wrap_untrusted",
]

# Substrings commonly associated with prompt injection attempts.
# Case-insensitive substring search. Cheap first-line screen before LLM.
# Stored as tuple to prevent accidental mutation by callers.
INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous",
    "ignore all previous",
    "ignore above",
    "disregard previous",
    "disregard above",
    "disregard the above",
    "forget everything",
    "forget all",
    "forget your",
    "from now on",
    "above all else",
    "system override",
    "system:",
    "you are now",
    "you are a helpful",
    "act as",
    "pretend you are",
    "roleplay as",
    "do anything now",
    "jailbreak",
    "developer mode",
    "dan mode",
    "admin mode",
    "god mode",
    "new instructions",
    "reveal your prompt",
    "reveal your system",
    "print your instructions",
    "print your prompt",
    "<untrusted",
    "</untrusted",
    "<|im_start|>",
    "<|endoftext|>",
    "### system",
    "### instruction",
    "begin system",
)


# Matches any <UNTRUSTED_* or </UNTRUSTED_* opening/closing sequence in any
# case with tolerant whitespace. Used by wrap_untrusted to mangle attacker
# attempts and by check_output_for_leaks to detect leftover tags.
_UNTRUSTED_TAG_RE = re.compile(
    r"<\s*/?\s*UNTRUSTED_[A-Z0-9_]*[^>]*>?",
    re.IGNORECASE,
)


@dataclass
class UntrustedCheckResult:
    """Result of scanning LLM output for leaks or policy violations."""

    safe: bool
    reasons: list[str] = field(default_factory=list)


def wrap_untrusted(text: str, source: str, **attributes: str) -> str:
    """Wrap third-party text in an <UNTRUSTED_INPUT> tag.

    Any UNTRUSTED_* tag fragments (in any case, with or without whitespace,
    with or without closing `>`) inside `text` are mangled so an attacker
    cannot forge or close the wrapper. The outer tag is ALWAYS upper-case
    literal ``<UNTRUSTED_INPUT>`` so downstream checks can look for it
    exactly.

    Attribute *values* are HTML-escaped. Attribute *names* must be valid
    Python identifiers (enforced) so callers can only pass literal keys.
    """
    # Mangle attacker-controlled tag fragments by HTML-escaping the entire
    # match. html.escape converts '<' -> '&lt;' and '>' -> '&gt;', which
    # makes any attacker-supplied tag inert regardless of case, whitespace,
    # or partial closure.
    safe_text = _UNTRUSTED_TAG_RE.sub(lambda m: escape(m.group(0), quote=False), text)

    attr_str = f' source="{escape(source, quote=True)}"'
    for k, v in attributes.items():
        if not k.isidentifier():
            raise ValueError(f"attribute name must be a Python identifier: {k!r}")
        attr_str += f' {k}="{escape(str(v), quote=True)}"'
    return f"<UNTRUSTED_INPUT{attr_str}>\n{safe_text}\n</UNTRUSTED_INPUT>"


def scan_for_injection_markers(text: str) -> list[str]:
    """Return the list of injection markers found in text (case-insensitive).

    O(n*m) where n=len(text), m=len(INJECTION_MARKERS). Fine for DM-sized
    input; chunk before calling on large scraped blobs.
    """
    lowered = text.lower()
    return [marker for marker in INJECTION_MARKERS if marker in lowered]


def check_output_for_leaks(output: str) -> UntrustedCheckResult:
    """Scan LLM output before publication. Catches confused-model errors.

    Returns unsafe if:
    - Output contains any UNTRUSTED_* tag fragment (case-insensitive).
      Reason: ``leftover_untrusted_tag`` — the LLM got confused and echoed
      a wrapper tag into its reply.
    - Output appears to reveal system-prompt content via a tight set of
      phrases. Patterns are scoped to avoid the "my system is Linux"
      false positive. Reason: ``system_prompt_leak``.
    """
    reasons: list[str] = []

    if _UNTRUSTED_TAG_RE.search(output):
        reasons.append("leftover_untrusted_tag")

    # Tight, word-bounded patterns to minimize false positives in a
    # customer-service context where "my system" and "I was told to ship
    # it Tuesday" are legitimate.
    system_leak_patterns = [
        r"\b(my |the )?system prompt\b",
        r"\bmy (initial |original )?instructions (are|were|say|said)\b",
        r"\bmy system (prompt|message|instructions)\b",
        r"\bi was (told|instructed) to (say|respond|reply|never|always|ignore|pretend)\b",
        r"\breveal (my|the) (system|prompt|instructions)\b",
    ]
    lowered = output.lower()
    if any(re.search(p, lowered) for p in system_leak_patterns):
        reasons.append("system_prompt_leak")

    return UntrustedCheckResult(safe=not reasons, reasons=reasons)
