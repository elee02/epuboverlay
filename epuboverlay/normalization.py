"""Text normalization engine for preprocessing text before speech synthesis."""
from __future__ import annotations

import re

try:
    from num2words import num2words
    HAS_NUM2WORDS = True
except ImportError:
    HAS_NUM2WORDS = False


def harmonize_punctuation(text: str) -> str:
    """Standardize smart quotes, em/en dashes, and Unicode ellipses to standard ASCII."""
    replacements = {
        "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
        "‘": "'", "’": "'", "‚": "'", "‹": "'", "›": "'",
        "—": "-", "–": "-", "―": "-",
        "…": "...",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text


def fallback_num2int(n: int) -> str:
    """Fallback integer to words converter."""
    if n == 0:
        return "zero"

    units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
             "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    if n < 0:
        return "minus " + fallback_num2int(-n)

    parts = []

    # Billions
    if n >= 1000000000:
        parts.append(fallback_num2int(n // 1000000000) + " billion")
        n %= 1000000000

    # Millions
    if n >= 1000000:
        parts.append(fallback_num2int(n // 1000000) + " million")
        n %= 1000000

    # Thousands
    if n >= 1000:
        parts.append(fallback_num2int(n // 1000) + " thousand")
        n %= 1000

    # Hundreds
    if n >= 100:
        parts.append(units[n // 100] + " hundred")
        n %= 100

    # Tens & Units
    if n > 0:
        if n < 20:
            parts.append(units[n])
        else:
            t = tens[n // 10]
            u = units[n % 10]
            if u:
                parts.append(f"{t}-{u}")
            else:
                parts.append(t)

    return " ".join(parts)


def fallback_num2words(val: int | float) -> str:
    """Fallback float/int to words converter."""
    if isinstance(val, float):
        parts = str(val).split(".")
        int_words = fallback_num2int(int(parts[0]))
        dec_words = " point " + " ".join(fallback_num2int(int(d)) for d in parts[1])
        return int_words + dec_words
    return fallback_num2int(val)


def expand_numerals(text: str) -> str:
    """Find digit sequences in text and expand them into words."""
    pattern = r"\b\d+(?:,\d{3})*(?:\.\d+)?\b"

    def repl(match: re.Match) -> str:
        num_str = match.group(0).replace(",", "")
        try:
            if "." in num_str:
                val: int | float = float(num_str)
            else:
                val = int(num_str)

            if HAS_NUM2WORDS:
                return num2words(val)
            else:
                return fallback_num2words(val)
        except Exception:
            return match.group(0)

    return re.sub(pattern, repl, text)


def resolve_contractions(text: str) -> str:
    """Expand common English contractions while preserving capitalization style."""
    contractions_map = {
        "won't": "will not",
        "can't": "cannot",
        "don't": "do not",
        "aren't": "are not",
        "isn't": "is not",
        "wasn't": "was not",
        "weren't": "were not",
        "haven't": "have not",
        "hasn't": "has not",
        "hadn't": "had not",
        "shouldn't": "should not",
        "wouldn't": "would not",
        "couldn't": "could not",
        "mustn't": "must not",
        "doesn't": "does not",
        "didn't": "did not",
        "it's": "it is",
        "he's": "he is",
        "she's": "she is",
        "that's": "that is",
        "there's": "there is",
        "what's": "what is",
        "who's": "who is",
        "i'm": "i am",
        "i've": "i have",
        "you've": "you have",
        "we've": "we have",
        "they've": "they have",
        "i'll": "i will",
        "you'll": "you will",
        "he'll": "he will",
        "she'll": "she will",
        "we'll": "we will",
        "they'll": "they will",
        "i'd": "i would",
        "you'd": "you would",
        "he'd": "he would",
        "she'd": "she would",
        "we'd": "we would",
        "they'd": "they would",
    }

    sorted_keys = sorted(contractions_map.keys(), key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted_keys) + r")\b", re.IGNORECASE)

    def repl(match: re.Match) -> str:
        matched_str = match.group(1)
        lower_match = matched_str.lower()
        expansion = contractions_map.get(lower_match, matched_str)

        if matched_str.isupper():
            return expansion.upper()
        elif matched_str[0].isupper():
            return expansion[0].upper() + expansion[1:]
        return expansion

    return pattern.sub(repl, text)


def resolve_heteronyms(text: str) -> str:
    """Apply simple context-based rules to resolve common heteronyms."""
    rules = [
        # read
        (r"\bread\b(\s+(?:yesterday|last year|last week|last night))", "red\\1"),
        (r"\b(had|has|have|was|were|been)\s+read\b", "\\1 red"),
        (r"\b(to)\s+read\b", "\\1 reed"),
        (r"\b(will|would|should|can|could|may|might|must)\s+read\b", "\\1 reed"),
        # wind
        (r"\bwind\b(\s+(?:the\s+)?(?:clock|watch|spring|key|up))", "wynd\\1"),
        # live
        (r"\blive\b(\s+(?:show|music|performance|broadcast|concert|stream|recording|audience|action|wire|animal|organism))", "lyve\\1"),
        # lead
        (r"\blead\b(\s+(?:pipe|pencil|shield|bullet|paint|poisoning|apron))", "led\\1"),
        (r"\b(the|heavy|sinker)\s+lead\b", "\\1 led"),
        # tear
        (r"\b(a|one|single|salty|eye|drop\s+of)\s+tear\b", "\\1 teer"),
        (r"\btear\b(\s+(?:down|up|apart|away|into|off|out))", "tair\\1"),
    ]
    for pattern, repl in rules:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def apply_custom_lexicon(text: str, lexicon: list[dict[str, str]]) -> str:
    """Apply user-defined whole-word substitution mappings."""
    for entry in lexicon:
        word = entry.get("word", "").strip()
        replacement = entry.get("replacement", "").strip()
        if not word:
            continue

        pattern = r"\b" + re.escape(word) + r"\b"
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def normalize_text(text: str, settings: dict | None = None) -> str:
    """Run the text normalization chain using the configured settings."""
    if not settings:
        return text

    if settings.get("harmonize_punctuation", True):
        text = harmonize_punctuation(text)

    if settings.get("resolve_contractions", True):
        text = resolve_contractions(text)

    # Lexicon replacements should generally run before numerical expansions
    # in case a custom lexicon word contains digits or vice-versa.
    custom_lexicon = settings.get("custom_lexicon")
    if custom_lexicon:
        text = apply_custom_lexicon(text, custom_lexicon)

    if settings.get("expand_numerals", True):
        text = expand_numerals(text)

    if settings.get("resolve_heteronyms", True):
        text = resolve_heteronyms(text)

    return text
