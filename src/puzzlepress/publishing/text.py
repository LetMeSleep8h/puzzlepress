"""Deterministic text detectors for titles, descriptions and keywords.

Every detector returns the exact matched text so a finding can quote it.
Detectors that only suggest a problem (reviews, promotional wording, keyword
stuffing) feed warnings; unambiguous patterns (URLs, emails, prices, emojis,
invisible characters) feed errors. Nothing here rewrites the author's text.
"""

import re

PLACEHOLDERS = {"unknown", "n/a", "na", "blank", "none", "null", "not applicable"}
TAG = re.compile(r"<\s*/?\s*[A-Za-z][^<>]*>")
ANGLE = re.compile(r"[<>]")
URL = re.compile(
    r"\b(?:https?://\S+|www\.\S+|[a-z0-9-]+\.(?:com|net|org|io|co|uk|de|fr|es|it|info|biz|"
    r"shop|store|app|me|us|ca|au)\b(?:/\S*)?)",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
PRICE = re.compile(
    r"[$€£¥]\s?\d+(?:[.,]\d{2})?|\b\d+(?:[.,]\d{2})?\s?(?:usd|eur|gbp|dollars?|euros?|pounds?)\b",
    re.IGNORECASE,
)
REVIEW_REQUEST = re.compile(
    r"\b(?:leave|write|post)\s+(?:a|an|us\s+a|me\s+a)?\s*(?:honest\s+)?review\b|"
    r"\bplease\s+(?:review|rate)\b|\brate\s+(?:this|the|our|my)\s+book\b",
    re.IGNORECASE,
)
REVIEW_LIKE = re.compile(
    r"★|☆|\b(?:five|5)[\s-]stars?\b|\btestimonials?\b|\breviewers?\b|\breviews?\b|"
    r"[\"“][^\"”]{12,}[\"”]\s*[—–-]\s*\w",
    re.IGNORECASE,
)
PROMOTIONAL = re.compile(
    r"\b(?:limited[\s-]time|on\s+sale|sale\s+price|discount(?:ed)?|\d+\s?%\s?off|"
    r"free\s+shipping|today\s+only|available\s+now|pre-?order|new\s+release|"
    r"best[\s-]?sell(?:ing|er))\b|#\s?1\b",
    re.IGNORECASE,
)
TITLE_PROMOTIONAL = re.compile(
    r"\b(?:best[\s-]?sell(?:ing|er)|free|on\s+sale|new\s+release)\b|#\s?1\b", re.IGNORECASE
)
GENERIC_TITLE_WORDS = {"notebook", "journal", "gift", "gifts", "book", "books"}
INVISIBLE = {
    "­",
    "᠎",
    "​",
    "‌",
    "‍",
    "‎",
    "‏",
    "‪",
    "‫",
    "‬",
    "‭",
    "‮",
    "⁠",
    "⁡",
    "⁢",
    "⁣",
    "⁤",
    "﻿",
}
QUOTES = re.compile(r"[\"“”„«»]")
PROGRAMS = re.compile(r"\b(?:kindle\s+unlimited|kdp\s+select|kdp)\b", re.IGNORECASE)
SUBJECTIVE = re.compile(
    r"\b(?:best|bestselling|best-selling|bestseller|new|newest|on\s+sale|sale|free|"
    r"available\s+now|top|cheap|amazing)\b|#\s?1\b",
    re.IGNORECASE,
)
GENERIC_KEYWORDS = {"book", "books", "paperback", "puzzle book"}
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "your", "their", "into", "each",
    "every", "are", "you", "all", "its", "more", "have", "will", "also", "than", "them",
}  # fmt: skip


def is_placeholder(text: str) -> bool:
    return text.strip().casefold() in PLACEHOLDERS


def punctuation_only(text: str) -> bool:
    return not any(ch.isalnum() for ch in text)


def first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0).strip() if match else None


def emojis(text: str) -> list[str]:
    found: list[str] = []
    for ch in text:
        code = ord(ch)
        if (
            0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or 0x2B00 <= code <= 0x2BFF
            or code == 0xFE0F
        ) and ch not in found:
            found.append(ch)
    return found


def invisible(text: str) -> list[str]:
    return sorted({f"U+{ord(ch):04X}" for ch in text if ch in INVISIBLE})


def repeated_word(text: str) -> tuple[str, int] | None:
    """A word dominating the description: at least 6 uses and 8% of all words."""
    words = [w.casefold() for w in re.findall(r"[^\W\d_]{4,}", text)]
    total = len(re.findall(r"\w+", text))
    counts: dict[str, int] = {}
    for word in words:
        if word not in STOPWORDS:
            counts[word] = counts.get(word, 0) + 1
    if not counts:
        return None
    word, count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return (word, count) if count >= 6 and count >= 0.08 * total else None


def keyword_key(keyword: str) -> str:
    """Exact-duplicate key: case and repeated spaces do not make a new keyword."""
    return " ".join(keyword.casefold().split())


def keyword_variant(keyword: str) -> str:
    """Variant key: KDP asks not to repeat spacing, punctuation or plural variants."""
    return "".join(_singular(w) for w in re.findall(r"\w+", keyword.casefold()))


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("es") and word[:-2].endswith(("ch", "sh", "x", "s", "z")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_NUMBER = (
    r"(?:a|one)\s+hundred|\d{1,4}|(?:"
    + "|".join(_TENS)
    + r")(?:[\s-](?:"
    + "|".join(list(_UNITS)[:9])
    + r"))?|(?:"
    + "|".join(_UNITS)
    + r")"
)
# Up to two descriptive words between the number and the noun, never words that
# change what is counted ("8 words in each puzzle").
_GAP = (
    r"(?:[\s-]+(?!(?:in|of|per|from|with|on|each|the|a|an|and|or|to|for|by|words?|"
    r"letters?|pages?|solutions?)\b)[a-z]+){0,2}"
)
PUZZLE_CLAIM = re.compile(
    # A dimension ("14 x 14 grid") is not a count.
    rf"(?<![x×]\s)(?<![x×])\b({_NUMBER})\b(?!\s?[x×])"
    rf"{_GAP}[\s-]+(?:word[\s-]?search(?:es)?|puzzles?|grids?)\b",
    re.IGNORECASE,
)
SOLUTIONS = re.compile(r"\b(?:solutions?|answer\s+keys?|answers)\b", re.IGNORECASE)
# Coloring descriptions count drawings ("40 coloring pages", "twenty designs").
DRAWING_CLAIM = re.compile(
    rf"(?<![x×]\s)(?<![x×])\b({_NUMBER})\b(?!\s?[x×])"
    rf"{_GAP}[\s-]+(?:colou?ring[\s-]+pages?|drawings?|designs?|illustrations?|pictures?)\b",
    re.IGNORECASE,
)


def number_value(text: str) -> int:
    words = text.casefold().replace("-", " ").split()
    if words[0].isdigit():
        return int(words[0])
    if words[-1] == "hundred":
        return 100
    return sum(_TENS.get(w, 0) + _UNITS.get(w, 0) for w in words)


def drawing_claims(text: str) -> list[tuple[str, int]]:
    """Each (phrase, number) in which a coloring description counts its drawings."""
    return [(m.group(0), number_value(m.group(1))) for m in DRAWING_CLAIM.finditer(text)]


def puzzle_claims(text: str) -> list[tuple[str, int]]:
    """Each (phrase, number) in which the description counts its puzzles."""
    return [(m.group(0), number_value(m.group(1))) for m in PUZZLE_CLAIM.finditer(text)]
