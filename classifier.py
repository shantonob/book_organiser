import re

UDC_MAP = [
    (0, "Generalities", [
        r"encyclopedia", r"encyclopaedia", r"dictionary", r"bibliograph",
        r"library", r"museum", r"journalis", r"newspaper", r"computer science",
        r"information science", r"knowledge", r"reference",
    ]),
    (1, "Philosophy. Psychology", [
        r"philosoph", r"psycholog", r"ethics", r"logic", r"metaphysic",
        r"epistemolog", r"aesthetic", r"consciousness", r"mind",
        r"ancient greek", r"stoic", r"existentialis", r"nietzsche",
        r"plato", r"aristotle", r"kant", r"hegel",
    ]),
    (2, "Religion. Theology", [
        r"religion", r"theolog", r"bible", r"biblical", r"spiritual",
        r"christian", r"buddhis", r"hindu", r"islam", r"quran",
        r"meditation", r"prayer", r"faith", r"mytholog", r"gospel",
    ]),
    (3, "Social Sciences", [
        r"sociolog", r"economic", r"politic", r"law", r"legal",
        r"government", r"education", r"finance", r"investing", r"business",
        r"management", r"marketing", r"accounting", r"trade", r"stock",
        r"economy", r"social", r"anthropolog", r"geograph", r"culture",
        r"history", r"war", r"diplomac", r"international", r"poverty",
        r"demograph", r"urban", r"criminolog", r"statistics",
    ]),
    (5, "Natural Sciences. Mathematics", [
        r"mathemat", r"physics", r"chemist", r"biology", r"botan",
        r"zoolog", r"geolog", r"astronom", r"ecolog", r"science",
        r"molecular", r"quantum", r"calculus", r"algebra", r"geometry",
        r"statistic", r"probabilit", r"differential", r"genetic",
        r"evolution", r"neuroscien", r"biolog", r"biochemist",
    ]),
    (6, "Applied Sciences. Medicine. Technology", [
        r"medicine", r"health", r"disease", r"diagnos", r"surgery",
        r"pharma", r"nursing", r"engineer", r"technolog", r"comput",
        r"software", r"programming", r"coding", r"algorithm", r"data",
        r"network", r"artificial", r"machine learning", r"robotics",
        r"electronic", r"mechanical", r"civil", r"electrical", r"architect",
        r"agricultur", r"manufactur", r"chemistry.*applied",
        r"clinical", r"therapy", r"anatomy", r"physiolog",
    ]),
    (7, "Arts. Recreation. Sport", [
        r"art", r"music", r"painting", r"sculpture", r"photograph",
        r"cinema", r"film", r"theatre", r"dance", r"sport", r"game",
        r"architecture", r"design", r"fashion", r"drawing", r"craft",
        r"pottery", r"cooking", r"recipe", r"food", r"wine",
        r"garden", r"hobb", r"collect", r"chess",
    ]),
    (8, "Language. Linguistics. Literature", [
        r"language", r"linguistic", r"grammar", r"vocabulary", r"english",
        r"french", r"spanish", r"german", r"chinese", r"japanese",
        r"russian", r"latin", r"translation", r"literature", r"novel",
        r"poetry", r"fiction", r"story", r"essay", r"drama", r"play",
        r"short story", r"antholog", r"classic", r"fairy tale",
        r"fantasy", r"science fiction", r"mystery", r"romance",
        r"thriller", r"horror", r"biography", r"autobiograph",
        r"memoir", r"poem", r"prose",
    ]),
    (9, "Geography. Biography. History", [
        r"geograph", r"travel", r"map", r"atlas", r"country",
        r"biograph", r"autobiograph", r"memoir", r"history",
        r"ancient", r"medieval", r"renaissance", r"world war",
        r"civilization", r"archaeolog", r"colonial", r"empire",
        r"kingdom", r"dynasty", r"revolution",
    ]),
]


def classify(title, authors=None, subjects=None, description=None):
    """Return (best_code, best_label) — single best UDC match (backwards compat)."""
    all_tags = classify_all(title, authors, subjects, description)
    if not all_tags:
        return "000", "Generalities"
    best = all_tags[0]
    return best["tag"], best["tag_label"]


def classify_all(title, authors=None, subjects=None, description=None):
    """Return a list of {tag, tag_label, score} for ALL UDC classes that score > 0.
    Sorted by score descending.  Returns at least [{tag:'000', tag_label:'Generalities', score:0}]."""
    text = " ".join(filter(None, [title, authors, description]))
    text = text.lower()

    if subjects:
        text += " " + " ".join(subjects).lower()

    results = []
    for code, label, patterns in UDC_MAP:
        score = sum(10 if re.search(p, text) else 0 for p in patterns)
        if score > 0:
            results.append({"tag": f"{code:03d}", "tag_label": label, "score": score})

    results.sort(key=lambda x: -x["score"])
    if not results:
        results.append({"tag": "000", "tag_label": "Generalities", "score": 0})
    return results
