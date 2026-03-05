"""
Placeholder protection for the translation pipeline.

Many Voyant UI strings contain interpolation tokens that must survive
translation unchanged — e.g. {0}, %(name)s, %s, <b>, <strong>.

Strategy
--------
Before calling any translation engine, `protect()` replaces every recognised
placeholder/tag with a numbered sentinel string (§0§, §1§, …) that is very
unlikely to appear naturally in any language.  After translation, `restore()`
swaps the sentinels back.

The round-trip is lossless: a sentinel that gets duplicated or dropped by the
engine will produce an odd-looking string that the QA layer will catch.
"""

from __future__ import annotations

import re

# The sentinel format.  § (U+00A7 SECTION SIGN) is uncommon in NLP corpora
# and not a valid ICU/Java placeholder character, so it won't be mistaken for
# source content.
_SENTINEL_FMT = "\u00a7{n}\u00a7"

# Ordered list of (name, pattern) pairs.  Patterns are tried in order;
# first match wins for each token found.  We capture the full token text.
_PLACEHOLDER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # ICU select/plural blocks: {count, plural, one {# item} other {# items}}
    ("icu_block", re.compile(r"\{[^{}]*,\s*(?:plural|select|selectordinal)[^{}]*\}", re.DOTALL)),
    # Named percent: %(name)s  %(name)d  %(name)f
    ("pct_named", re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)[sdfoxX%]")),
    # Positional percent: %1$s  %2$d
    ("pct_pos", re.compile(r"%\d+\$[sdfoxX%]")),
    # Simple percent: %s  %d  %f  %% (literal percent)
    ("pct_simple", re.compile(r"%%|%[sdfoxX]")),
    # Curly single-token: {0}  {name}  {count}
    ("curly", re.compile(r"\{[A-Za-z0-9_]+\}")),
    # HTML/XML tags (open and close, with optional attributes)
    ("html_tag", re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?>", re.IGNORECASE)),
    # HTML entities: &amp;  &#9878;  &#65039;
    ("html_entity", re.compile(r"&(?:[A-Za-z][A-Za-z0-9]*|\#\d+|\#x[0-9A-Fa-f]+);")),
]


def protect(text: str) -> tuple[str, dict[str, str]]:
    """Replace all placeholders in *text* with numbered sentinels.

    Returns
    -------
    protected : str
        *text* with every placeholder replaced by ``§N§``.
    restore_map : dict[str, str]
        Mapping ``"§N§" → original_token`` for use by :func:`restore`.
    """
    if not text:
        return text, {}

    restore_map: dict[str, str] = {}
    counter = 0
    result = text

    for _name, pattern in _PLACEHOLDER_PATTERNS:
        def replacer(m: re.Match[str]) -> str:
            nonlocal counter
            sentinel = _SENTINEL_FMT.format(n=counter)
            restore_map[sentinel] = m.group(0)
            counter += 1
            return sentinel

        result = pattern.sub(replacer, result)

    return result, restore_map


def restore(text: str, restore_map: dict[str, str]) -> str:
    """Replace sentinels in *text* back to their original placeholder tokens.

    Sentinels that the translation engine introduced, duplicated, or dropped
    are left as-is (they will be caught by the QA layer).
    """
    if not text or not restore_map:
        return text

    for sentinel, original in restore_map.items():
        text = text.replace(sentinel, original)

    return text
