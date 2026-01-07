import re
from collections import Counter

def extract_placeholders(text: str | None) -> set[str]:
    if not text:
        return set()

    found: set[str] = set()

    percent_patterns = [
        r"%(?!%)\([A-Za-z_][A-Za-z0-9_]*\)[sdfox]",  # %(name)s
        r"%(?!%)\d+\$[sdfox]",  # %1$s
        r"%(?!%)[sdfox]",  # %s
    ]
    for pattern in percent_patterns:
        found.update(re.findall(pattern, text))

    # Curly placeholders: {0}, {name} (no nesting)
    found.update(re.findall(r"\{[^{}]+\}", text))

    return found


def extract_html_tags(text: str | None) -> dict[str, int]:
    if not text:
        return {}

    # Keep the list tight and heuristic-driven.
    tag_names = "b|i|strong|em|span|a"
    pattern = re.compile(rf"<\s*(/)?\s*({tag_names})\b[^>]*>", re.IGNORECASE)

    counts: Counter[str] = Counter()
    for match in pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).lower()
        key = f"{tag}_{'close' if is_close else 'open'}"
        counts[key] += 1

    return dict(counts)


def compute_qa_flags(source: str | None, target: str | None) -> list[dict]:
    src = source or ""
    tgt = target or ""

    flags: list[dict] = []

    src_placeholders = extract_placeholders(src)
    tgt_placeholders = extract_placeholders(tgt)

    missing = sorted(src_placeholders - tgt_placeholders)
    if missing:
        flags.append(
            {
                "code": "missing_placeholder",
                "message": "Translation is missing placeholder(s) present in the source.",
                "details": {"missing": missing},
            }
        )

    extra = sorted(tgt_placeholders - src_placeholders)
    if extra:
        flags.append(
            {
                "code": "extra_placeholder",
                "message": "Translation contains placeholder(s) not present in the source.",
                "details": {"extra": extra},
            }
        )

    if tgt.count("{") != tgt.count("}"):
        flags.append(
            {
                "code": "unbalanced_braces",
                "message": "Translation has unbalanced curly braces.",
                "details": {"open": tgt.count("{"), "close": tgt.count("}")},
            }
        )

    src_tags = extract_html_tags(src)
    tgt_tags = extract_html_tags(tgt)
    all_keys = sorted(set(src_tags.keys()) | set(tgt_tags.keys()))

    mismatches: dict[str, dict[str, int]] = {}
    for key in all_keys:
        s = int(src_tags.get(key, 0))
        t = int(tgt_tags.get(key, 0))
        if s != t:
            mismatches[key] = {"source": s, "target": t}

    if mismatches:
        flags.append(
            {
                "code": "html_tag_mismatch",
                "message": "Translation HTML tag counts do not match the source.",
                "details": {"mismatches": mismatches},
            }
        )

    if src.strip() and not tgt.strip():
        flags.append(
            {
                "code": "empty_translation",
                "message": "Translation is empty while the source is not.",
            }
        )

    return flags
