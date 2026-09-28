"""Tokenizer for keyword (full-text) search.

PostgreSQL has no Korean text-search dictionary, and Korean attaches particles to
words ("장애의", "장애가"), so exact word matching misses most hits. Hangul runs are
indexed as overlapping character bigrams instead ("장애의" -> "장애", "애의"), which a
query for "장애" matches. Latin/number runs are kept whole ("sev2", "e403").
"""

import re

_TOKEN = re.compile(r"[0-9a-z]+|[가-힣]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _TOKEN.finditer(text.lower()):
        word = match.group()
        if "가" <= word[0] <= "힣" and len(word) > 1:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
        else:
            tokens.append(word)
    return tokens


def to_search_text(text: str) -> str:
    """Space-joined tokens, stored per chunk and indexed with to_tsvector('simple', ...)."""
    return " ".join(tokenize(text))


def to_tsquery(text: str) -> str | None:
    """OR-query over unique tokens. Tokens are [0-9a-z가-힣] only, so no escaping is needed."""
    unique = list(dict.fromkeys(tokenize(text)))
    return " | ".join(unique) or None
