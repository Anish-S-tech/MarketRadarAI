"""Text normalisation and block-level diffing that ignore noise (dates, nonces, counters, whitespace)."""

import difflib
import hashlib
import re

NOISE_PATTERNS = [
    re.compile(r"\b[0-9a-f]{16,}\b", re.I),  # hashes / nonces
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),  # uuids
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s?(am|pm|utc|gmt)?\b", re.I),  # times
    re.compile(r"©\s?\d{4}(\s?[-–]\s?\d{4})?"),  # copyright years
    re.compile(r"\b(updated|last updated|posted)\s*:?\s*\d+\s+(minutes?|hours?|days?)\s+ago\b", re.I),
    re.compile(r"\bcsrf[_-]?token\S*", re.I),
]
DROP_LINE_PATTERNS = [
    re.compile(r"^(accept|reject)( all)? cookies?$", re.I),
    re.compile(r"we use cookies", re.I),
    re.compile(r"^skip to (main )?content$", re.I),
]


def normalize_text(text: str, extra_ignore_patterns: list[str] | None = None) -> str:
    extra = [re.compile(p, re.I) for p in (extra_ignore_patterns or [])]
    out: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        for pat in NOISE_PATTERNS + extra:
            line = pat.sub("", line).strip()
        if not line or any(p.search(line) for p in DROP_LINE_PATTERNS):
            continue
        if out and out[-1] == line:
            continue
        out.append(line)
    return "\n".join(out)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def block_diff(old: str, new: str) -> dict[str, list[str]]:
    """Line/paragraph level diff. Modified lines appear as removed+added pairs."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    added: list[str] = []
    removed: list[str] = []
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(old_lines[i1:i2])
        if tag in ("replace", "insert"):
            added.extend(new_lines[j1:j2])
    # Lines that merely moved are not changes
    moved = set(added) & set(removed)
    return {
        "added": [a for a in added if a not in moved],
        "removed": [r for r in removed if r not in moved],
    }


def unified_diff(old: str, new: str, context: int = 2) -> str:
    return "\n".join(
        difflib.unified_diff(old.splitlines(), new.splitlines(), "before", "after", n=context, lineterm="")
    )
