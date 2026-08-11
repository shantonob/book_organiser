import os
import re

try:
    import spacy
    _nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
except Exception:
    _nlp = None

SEPARATORS = [r"\s+[-–—]\s+", r"\s+[-–—]"]
AUTHOR_IN_PARENS = re.compile(r"\(([^)]+)\)\s*$")
SERIES_PATTERN = re.compile(
    r"\(?\s*(?:#|Vol\.?|Volume|Book|Part|Pt\.?)\s*\.?\s*(\d+)\s*\)?"
    r"|\(?\s*[-–—]\s*(\d+)\s*\)?\s*$"
)
YEAR = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")

# Words that commonly appear in titles but rarely in author names
_NON_NAME_WORDS = {
    "the", "and", "for", "with", "from", "into", "over", "under", "about",
    "book", "guide", "manual", "introduction", "intro", "practical",
    "complete", "essential", "modern", "advanced", "beginner",
    "professional", "expert", "illustrated", "collection", "anthology",
    "learning", "programming", "coding", "development", "design",
    "analysis", "theory", "practice", "applications", "volume",
    "edition", "series", "trilogy", "omnibus", "boxed", "set",
    "science", "scientific", "engineering", "mathematics", "math",
    "physics", "chemistry", "biology", "history", "philosophy",
    "english", "french", "german", "spanish", "chinese", "japanese",
}


def _split_author_title(cleaned):
    """Try common patterns to split author and title."""

    # Collect all possible splits across all separators
    candidates = []
    for sep in SEPARATORS:
        parts = re.split(sep, cleaned, maxsplit=1)
        if len(parts) == 2 and len(parts[0]) > 1 and len(parts[1]) > 1:
            candidates.append((parts[0].strip(), parts[1].strip()))

    # Score each direction and pick the best
    best_score = -1
    best_result = None

    for left, right in candidates:
        for a_candidate, t_candidate, direction in [(left, right, "left"), (right, left, "right")]:
            if len(a_candidate.split()) > 5 or not _looks_like_name(a_candidate):
                continue
            score = 0

            # ═══ STRONG AUTHOR SIGNALS ═══
            # Comma-separated "Last, First" is a strong author signal
            if "," in a_candidate and not a_candidate.endswith(","):
                score += 4
            # Initials pattern (J. R. R. Tolkien)
            if re.search(r"\b[A-Z]\.", a_candidate):
                score += 2

            # ═══ STRONG TITLE SIGNALS (negative for author) ═══
            # Starts with article → very likely a title, not an author
            a_lower = a_candidate.lower()
            a_first = a_candidate.split()[0].lower()
            if a_first in ("the", "a", "an"):
                score -= 4
            # Contains apostrophe-s (possessive) → likely title
            if "'s" in a_lower:
                score -= 3
            # Contains title-like structural words
            tlike = {"the", "a", "an", "of", "in", "on", "at", "for", "with", "and", "to", "by"}
            if any(f" {w} " in f" {a_lower} " for w in tlike):
                score -= 2

            # ═══ CONTEXTUAL SIGNALS ═══
            word_count = len(a_candidate.split())
            # Single word is rarely an author name
            if word_count == 1:
                score -= 3
            # Short names (2-3 words) slightly preferred
            if 2 <= word_count <= 3:
                score += 1

            # If left side starts with digit, skip as author
            if direction == "left" and cleaned[0].isdigit():
                continue
            # If left side contains non-alpha chars like ".qxd", skip as author
            if direction == "left" and re.search(r"\.[a-z]{2,4}$", left):
                continue
            # Prefer "Author - Title" direction slightly
            if direction == "left":
                score += 1

            # ═══ SPACY POS HINT ═══
            if _nlp and direction == "left":
                doc = _nlp(a_candidate)
                pos_tags = [t.pos_ for t in doc]
                # If author candidate has common nouns/adjectives/verbs → likely title
                non_proper = sum(1 for p in pos_tags if p in ("NOUN", "VERB", "ADJ", "ADV"))
                if non_proper >= len(pos_tags) // 2:
                    score -= 2

            if score > best_score or (score == best_score and direction == "right" and best_result is not None):
                best_score = score
                best_result = (a_candidate, t_candidate)

    if best_result:
        return best_result

    # Pattern: Title (Author)
    m = AUTHOR_IN_PARENS.search(cleaned)
    if m:
        candidate_author = m.group(1).strip()
        # strip series info from candidate (e.g. "Robert Langdon, #2" → "Robert Langdon")
        candidate_author = re.sub(r",\s*#?\d+.*", "", candidate_author).strip()
        title_part = cleaned[:m.start()].strip()
        if candidate_author and _looks_like_name(candidate_author):
            return candidate_author, title_part

    # Pattern: Author_Title (underscore between author and title)
    parts = cleaned.split("_", 1)
    if len(parts) == 2:
        a, t = parts[0].strip(), parts[1].strip()
        if len(a) > 1 and len(t) > 1 and len(a.split()) <= 4 and _looks_like_name(a):
            return a, t

    return None, cleaned


def _looks_like_name(text):
    """Heuristic: looks like a personal name (not a title fragment)."""
    text = text.replace("_", " ")
    words = text.split()
    if len(words) < 2 or len(words) > 5:
        return False
    # All words must start with uppercase (abbreviations like "J.K." are OK)
    for w in words:
        clean = w.rstrip(".")
        if not clean or not clean[0].isupper():
            return False
    # No words containing digits
    if any(any(c.isdigit() for c in w) for w in words):
        return False
    # No entirely non-name words
    if any(w.lower().strip(".") in _NON_NAME_WORDS for w in words):
        return False
    common_titles = {"mr", "mrs", "ms", "dr", "prof", "sir", "lord", "madam"}
    if words[0].lower().strip(".") in common_titles:
        return True
    # Single-word "names" are usually not real author names
    if len(words) == 2:
        w0, w1 = words[0].rstrip("."), words[1].rstrip(".")
        # Both must be 2+ chars and not look like common nouns
        if len(w0) < 2 or len(w1) < 2:
            return False
        # "Word Word" pattern where second word is a very short common word
        if w1.lower() in {"of", "in", "on", "at", "to", "by", "the", "and", "for", "a", "an"}:
            return False
    # Check for non-name suffixes (like .qxd, .pdf) that slipped through
    return not re.search(r"\.[a-z]{2,4}$", text, re.IGNORECASE)


def _spacy_author_hint(text):
    """Use spaCy NER to find PERSON entities as author hints."""
    if not _nlp:
        return None
    doc = _nlp(text)
    persons = [ent.text for ent in doc.ents if ent.label_ == "PERSON"]
    if persons:
        return max(persons, key=len)
    return None


def _strip_trailing_year(cleaned):
    """Remove a trailing year (YYYY) from the filename string."""
    parts = re.split(r"\s+[-–—]\s+(?=\d{4}$)", cleaned)
    if len(parts) == 2:
        return parts[0].strip()
    parts = re.split(r"\s+(?=\d{4}$)", cleaned)
    if len(parts) == 2 and YEAR.match(parts[1]):
        return parts[0].strip()
    return cleaned


def enrich_from_filename(fname):
    """Parse author, title, year, series from a cleaned filename string.

    Returns a dict with any of: title, author, year, series_name, series_num.
    Only populated when confidently extracted.
    """
    result = {}

    # Strip extension, clean
    base = os.path.splitext(fname)[0]
    year_match = YEAR.search(base)
    if year_match:
        result["year"] = int(year_match.group(0))

    # Try to extract series info before the main split
    series_match = SERIES_PATTERN.search(base)
    series_num = None
    if series_match:
        series_num = series_match.group(1) or series_match.group(2)
        base = SERIES_PATTERN.sub("", base).strip()

    # Remove trailing year for cleaner splitting
    cleaned = _strip_trailing_year(base)

    author, title = _split_author_title(cleaned)
    if author:
        result["author"] = author
        result["title"] = title
    else:
        result["title"] = cleaned
        if _nlp:
            hint = _spacy_author_hint(cleaned)
            if hint and _looks_like_name(hint):
                result["author"] = hint
                before, _, after = cleaned.partition(hint)
                result["title"] = (before + after).strip(" -–—()_").strip()

    if series_num:
        result["series_num"] = series_num

    return result
