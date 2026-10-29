"""Multilingual text normalization engine and Narration Scenario Profiles for speech synthesis."""
from __future__ import annotations

import re
from typing import Any

try:
    from num2words import num2words
    HAS_NUM2WORDS = True
except ImportError:
    HAS_NUM2WORDS = False


# Studio-crafted Narration Scenario Profiles
NARRATION_SCENARIOS: dict[str, dict[str, Any]] = {
    "custom": {
        "id": "custom",
        "title": "Custom Studio",
        "icon": "🎛️",
        "description": "Manual control over all acoustic, pacing, and emotional parameters.",
        "speed": 1.0,
        "max_chars": 150,
        "temp": 0.7,
        "lsd_decode_steps": 1,
        "noise_clamp": None,
        "eos_threshold": -4.0,
        "frames_after_eos": None,
        "instruct": "",
        "emotion_tag": "",
    },
    "fiction_audiobook": {
        "id": "fiction_audiobook",
        "title": "Fiction & Literary",
        "icon": "📖",
        "description": "Warm, expressive storytelling with natural dramatic pauses and subtle emotional nuance.",
        "speed": 0.98,
        "max_chars": 160,
        "temp": 0.75,
        "lsd_decode_steps": 2,
        "noise_clamp": 2.8,
        "eos_threshold": -4.1,
        "frames_after_eos": 2,
        "instruct": "Narrate with warm literary expressiveness, natural dramatic pacing, and subtle emotional nuance.",
        "emotion_tag": "(soft tone)",
    },
    "technical_docs": {
        "id": "technical_docs",
        "title": "Technical & Academic",
        "icon": "🔬",
        "description": "Crisp articulation, low prosodic variance, and high consonant precision for dense documents.",
        "speed": 1.0,
        "max_chars": 180,
        "temp": 0.50,
        "lsd_decode_steps": 4,
        "noise_clamp": 2.2,
        "eos_threshold": -4.0,
        "frames_after_eos": 1,
        "instruct": "Speak with clear, authoritative, and precise articulation suitable for technical and scientific documentation.",
        "emotion_tag": "(serious)",
    },
    "executive_briefing": {
        "id": "executive_briefing",
        "title": "Executive Briefing",
        "icon": "🎙️",
        "description": "Polished, confident broadcast cadence optimized for reports, memos, and news summaries.",
        "speed": 1.08,
        "max_chars": 170,
        "temp": 0.60,
        "lsd_decode_steps": 2,
        "noise_clamp": 2.5,
        "eos_threshold": -3.9,
        "frames_after_eos": 1,
        "instruct": "Deliver in a polished, confident, and engaging broadcast briefing style with crisp sentence transitions.",
        "emotion_tag": "",
    },
    "language_learning": {
        "id": "language_learning",
        "title": "Language Shadowing",
        "icon": "🌍",
        "description": "Deliberate enunciation, shorter phrase chunks, and extended trailing pauses for polyglot study.",
        "speed": 0.88,
        "max_chars": 100,
        "temp": 0.55,
        "lsd_decode_steps": 4,
        "noise_clamp": 2.2,
        "eos_threshold": -4.2,
        "frames_after_eos": 6,
        "instruct": "Enunciate every syllable clearly and deliberately at a measured, learner-friendly pace.",
        "emotion_tag": "(soft tone)",
    },
    "dramatic_dialogue": {
        "id": "dramatic_dialogue",
        "title": "Dramatic Dialogue",
        "icon": "🎭",
        "description": "High dynamic range, vivid emotional inflection, and multi-voice dialogue state switching.",
        "speed": 0.96,
        "max_chars": 140,
        "temp": 0.82,
        "lsd_decode_steps": 3,
        "noise_clamp": 3.0,
        "eos_threshold": -4.3,
        "frames_after_eos": 2,
        "instruct": "Perform with rich theatrical emotion, distinct character inflection, and expressive intonation.",
        "emotion_tag": "(excited)",
    },
}


_LANG_CODE_TO_ISO: dict[str, str] = {
    "a": "en",
    "b": "en",
    "en": "en",
    "english": "en",
    "english_2026-04": "en",
    "english_2026-01": "en",
    "ru": "ru",
    "russian": "ru",
    "ko": "ko",
    "korean": "ko",
    "j": "ja",
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    "z": "zh",
    "zh": "zh",
    "chinese": "zh",
    "de": "de",
    "german": "de",
    "german_24l": "de",
    "e": "es",
    "es": "es",
    "spanish": "es",
    "spanish_24l": "es",
    "ar": "ar",
    "arabic": "ar",
    "f": "fr",
    "fr": "fr",
    "french": "fr",
    "french_24l": "fr",
    "i": "it",
    "it": "it",
    "italian": "it",
    "italian_24l": "it",
    "p": "pt",
    "pt": "pt",
    "portuguese": "pt",
    "portuguese_24l": "pt",
    "h": "hi",
    "hi": "hi",
}

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_HANGUL_RE = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
_KANA_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")
_CJK_RE = re.compile(r"[\u4E00-\u9FFF]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")


def detect_text_language(text: str, hint: str | None = None) -> str:
    """Resolve ISO language code ('en', 'ru', 'ko', 'ja', 'zh', 'de', 'es', 'ar', etc.)
    from an explicit hint or Unicode script inspection.
    """
    if hint:
        cleaned = hint.strip().lower()
        if cleaned in _LANG_CODE_TO_ISO:
            return _LANG_CODE_TO_ISO[cleaned]

    if _HANGUL_RE.search(text):
        return "ko"
    if _KANA_RE.search(text):
        return "ja"
    if _ARABIC_RE.search(text):
        return "ar"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _CJK_RE.search(text):
        return "zh"
    return "en"


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
    """Fallback integer to English words converter."""
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
    """Fallback float/int to English words converter."""
    if isinstance(val, float):
        parts = str(val).split(".")
        int_words = fallback_num2int(int(parts[0]))
        dec_words = " point " + " ".join(fallback_num2int(int(d)) for d in parts[1])
        return int_words + dec_words
    return fallback_num2int(val)


def expand_numerals(text: str, lang: str = "en") -> str:
    """Find digit sequences in text and expand them into words for the target language."""
    resolved_lang = detect_text_language(text, hint=lang if lang and lang != "auto" else None)
    pattern = r"\b\d+(?:,\d{3})*(?:\.\d+)?\b"

    def repl(match: re.Match) -> str:
        num_str = match.group(0).replace(",", "")
        try:
            if "." in num_str:
                val: int | float = float(num_str)
            else:
                val = int(num_str)

            if HAS_NUM2WORDS:
                try:
                    return num2words(val, lang=resolved_lang)
                except NotImplementedError:
                    if resolved_lang == "en":
                        return num2words(val)
                    return match.group(0)
            else:
                # Only use English fallback when text/language is English;
                # never corrupt Russian/Korean/Japanese/Chinese/German/Spanish/Arabic with English number words.
                if resolved_lang == "en":
                    return fallback_num2words(val)
                return match.group(0)
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
    """Apply context-based rules to resolve common English heteronyms."""
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
    """Run the language-aware text normalization chain using the configured settings."""
    if not settings:
        return text

    lang_hint = (
        settings.get("language")
        or settings.get("pocket_language")
        or settings.get("lang_code")
        or None
    )
    lang = detect_text_language(text, hint=lang_hint if lang_hint != "auto" else None)

    if settings.get("harmonize_punctuation", True):
        text = harmonize_punctuation(text)

    if settings.get("resolve_contractions", True) and lang == "en":
        text = resolve_contractions(text)

    # Lexicon replacements run before numerical expansions in case a custom lexicon
    # word contains digits or vice-versa.
    custom_lexicon = settings.get("custom_lexicon")
    if custom_lexicon:
        text = apply_custom_lexicon(text, custom_lexicon)

    if settings.get("expand_numerals", True):
        text = expand_numerals(text, lang=lang)

    if settings.get("resolve_heteronyms", True) and lang == "en":
        text = resolve_heteronyms(text)

    return text
