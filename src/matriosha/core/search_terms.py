"""Privacy-preserving keyword extraction for retrieval candidate selection."""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterable


_TOKEN_RE = re.compile(r"[\w][\w\-'.]{1,63}", re.UNICODE)
_STOPWORDS = {
    # English
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "have",
    "has",
    "are",
    "was",
    "were",
    "what",
    "which",
    "where",
    "when",
    "who",
    "whom",
    "whose",
    "why",
    "how",
    "should",
    "would",
    "could",
    "can",
    "may",
    "might",
    "must",
    "does",
    "did",
    "doing",
    "done",
    "use",
    "uses",
    "using",
    "used",
    "about",
    "into",
    "onto",
    "over",
    "under",
    "than",
    "then",
    "there",
    "their",
    "them",
    # German
    "und",
    "der",
    "die",
    "das",
    "ein",
    "eine",
    "einer",
    "eines",
    "mit",
    "für",
    "von",
    "ist",
    "sind",
    "was",
    "welche",
    "welcher",
    "welches",
    "wo",
    "wer",
    "wie",
    "warum",
    "den",
    "dem",
    "des",
    "zu",
    # Italian
    "il",
    "lo",
    "la",
    "gli",
    "le",
    "di",
    "del",
    "della",
    "dello",
    "dei",
    "degli",
    "che",
    "con",
    "per",
    "una",
    "uno",
    "un",
    "chi",
    "cosa",
    "quale",
    "quali",
    "dove",
    "come",
    "quando",
    "nel",
    "nella",
    "nei",
    "nelle",
    "in",
    # Spanish
    "el",
    "los",
    "las",
    "de",
    "que",
    "para",
    "con",
    "una",
    "uno",
    "un",
    "qué",
    "cual",
    "cuál",
    "donde",
    "dónde",
    "como",
    "cómo",
    # French
    "le",
    "les",
    "des",
    "du",
    "avec",
    "pour",
    "une",
    "un",
    "qui",
    "que",
    "quoi",
    "où",
    "comment",
}

# Small deterministic alias map for common cross-language recall.
# Aliases are normalized and HMACed like all other terms, so no plaintext is stored.
_ALIASES = {
    "italiano": ("italian", "italy"),
    "italiana": ("italian", "italy"),
    "italiane": ("italian", "italy"),
    "italiani": ("italian", "italy"),
    "risposta": ("answer", "answers"),
    "risposte": ("answer", "answers"),
    "preferisce": ("prefers", "prefer"),
    "preferisci": ("prefers", "prefer"),
    "preferire": ("prefers", "prefer"),
    "tedesco": ("german", "germany"),
    "tedesca": ("german", "germany"),
    "inglese": ("english",),
    "francese": ("french", "france"),
    "spagnolo": ("spanish", "spain"),
    "anmeldung": ("registration", "residence registration"),
    "steuer-id": ("tax id", "tax identification"),
    "steuerid": ("tax id", "tax identification"),
    "cloud run": ("cloudrun",),
    "cloudrun": ("cloud run",),
}


def build_retrieval_index_text(text: object, *, max_chars: int = 12000) -> str:
    """Build deterministic plaintext used only before local/keyed retrieval tokenization.

    The returned text is not a storage format. Callers should pass it into
    extract_search_terms() and then keyed_search_tokens() before persisting
    retrieval metadata.
    """
    if text is None:
        return ""
    value = str(text)
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    if max_chars > 0 and len(value) > max_chars:
        head = max_chars // 2
        tail = max_chars - head
        value = value[:head] + " " + value[-tail:]
    return value


def normalize_search_term(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = unicodedata.normalize("NFKC", value).strip().lower()
    cleaned = cleaned.strip(".,;:!?()[]{}<>\\\"'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) < 2:
        return None
    return cleaned[:128]


def extract_search_terms(*parts: object, max_terms: int = 96) -> list[str]:
    seen: set[str] = set()
    lexical_terms: list[str] = []
    phrase_terms: list[str] = []

    def is_weak_phrase(term: str) -> bool:
        pieces = [piece for piece in re.split(r"\s+", term) if piece]
        if len(pieces) <= 1:
            return term in _STOPWORDS
        return all(piece in _STOPWORDS for piece in pieces)

    def add_to(target: list[str], value: object) -> None:
        term = normalize_search_term(value)
        if term is None or term in seen:
            return
        if is_weak_phrase(term):
            return
        seen.add(term)
        target.append(term)

        for alias in _ALIASES.get(term, ()):
            alias_term = normalize_search_term(alias)
            if alias_term is None or alias_term in seen or is_weak_phrase(alias_term):
                continue
            seen.add(alias_term)
            target.append(alias_term)

    def add_regex_tokens(text: str) -> None:
        # Lexical tokens are the privacy-preserving candidate filter backbone.
        # Keep both head and tail tokens so long payloads do not hide important suffixes.
        matches = list(_TOKEN_RE.findall(text))
        if len(matches) > 400:
            matches = matches[:200] + matches[-200:]

        for match in matches:
            token = normalize_search_term(match)
            if token is None or token in _STOPWORDS:
                continue

            add_to(lexical_terms, token)

            # Technical identifiers: pandas.DataFrame -> dataframe.
            if "." in token:
                add_to(lexical_terms, token.rsplit(".", 1)[-1])

            # Hyphenated phrases: semantic-tail -> semantic, tail.
            if "-" in token:
                for piece in token.split("-"):
                    if len(piece) >= 2:
                        add_to(lexical_terms, piece)

            # CamelCase / PascalCase identifiers: DataFrame -> data, frame.
            camel_pieces = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", match)
            if len(camel_pieces) > 1:
                for piece in camel_pieces:
                    if len(piece) >= 2:
                        add_to(lexical_terms, piece)

    def add_from_text(text: str) -> None:
        add_regex_tokens(text)

    for part in parts:
        if part is None:
            continue

        if isinstance(part, (list, tuple, set)):
            for item in part:
                if isinstance(item, str):
                    add_from_text(item)
                else:
                    add_to(lexical_terms, item)
            continue

        if isinstance(part, str):
            add_from_text(part)
        else:
            add_to(lexical_terms, part)

    # Reserve most of the budget for exact lexical candidate matching.
    lexical_budget = max(32, int(max_terms * 0.75))
    base_terms = lexical_terms[:lexical_budget]
    for term in phrase_terms:
        if len(base_terms) >= max_terms:
            break
        if term not in base_terms:
            base_terms.append(term)

    return base_terms[:max_terms]


def keyed_search_tokens(
    terms: Iterable[str],
    data_key: bytes,
    *,
    namespace: str = "matriosha-search-v1",
) -> list[str]:
    if not data_key:
        raise ValueError("data_key is required for keyed search tokens")
    prefix = namespace.encode("utf-8") + b"\0"
    seen: set[str] = set()
    tokens: list[str] = []
    for term in terms:
        normalized = normalize_search_term(term)
        if normalized is None:
            continue
        digest = hmac.new(data_key, prefix + normalized.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"hmac-sha256:{digest}"
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens
