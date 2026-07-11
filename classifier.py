import re

UDC_SUB_MAP = [
    (4, "Computer Science", [r"computer science", r"computing", r"data process", r"information technology", r"software engineering", r"cybersecur"]),
    (5, "Programming", [r"programming", r"coding", r"software development", r"algorithm"]),
    (6, "AI / Data Science", [r"artificial intelligence", r"machine learning", r"deep learning", r"neural network", r"data scien", r"data mining", r"big data"]),
    (150, "Psychology", [r"psycholog", r"behavior", r"cognitive", r"mental", r"therapy", r"neuropsycholog", r"social psycholog", r"personality"]),
    (170, "Ethics", [r"ethic", r"moral", r"righteous", r"virtue"]),
    (330, "Economics", [r"economic", r"finance", r"investing", r"trading", r"stock", r"market", r"macroeconom", r"microeconom", r"capitalis"]),
    (340, "Law", [r"law", r"legal", r"constitution", r"criminal.*law", r"civil.*law", r"jurisprudence", r"legislation", r"court"]),
    (370, "Education", [r"education", r"teaching", r"pedagog", r"curriculum", r"learning", r"classroom", r"school", r"university", r"training"]),
    (510, "Mathematics", [r"mathemat", r"calculus", r"algebra", r"geometry", r"statistic", r"probabilit", r"differential", r"linear algebra", r"trigonometr"]),
    (530, "Physics", [r"physics", r"mechanic", r"thermodynam", r"electromagnet", r"quantum", r"relativit", r"nuclear", r"optics", r"wave"]),
    (540, "Chemistry", [r"chemist", r"biochemist", r"organic.*chem", r"inorganic.*chem", r"molecular", r"chemical"]),
    (570, "Biology", [r"biology", r"biolog", r"genetic", r"evolution", r"ecolog", r"neuroscien", r"molecular.*biol", r"cell.*biol", r"organism", r"botan", r"zoolog"]),
    (610, "Medicine", [r"medicine", r"clinical", r"diagnos", r"surgery", r"pharma", r"nursing", r"disease", r"therapy", r"anatomy", r"physiolog", r"patholog", r"epidemiol"]),
    (620, "Engineering", [r"engineer", r"mechanical", r"electrical", r"civil.*engineer", r"electronic", r"robotics", r"aerospace", r"chemical.*engineer"]),
    (630, "Agriculture", [r"agricultur", r"farm", r"crop", r"soil", r"horticultur", r"viticultur", r"agronom"]),
    (720, "Architecture", [r"architect", r"building", r"urban.*design", r"construct", r"interior.*design"]),
    (780, "Music", [r"music", r"compos", r"orchestra", r"instrument", r"piano", r"guitar", r"violin", r"symphon", r"opera", r"jazz", r"blues", r"classical.*music"]),
    (810, "American Literature", [r"american literature", r"american.*novel", r"american.*fiction", r"american.*poet"]),
    (820, "English Literature", [r"english literature", r"british literature", r"english.*novel", r"british.*fiction", r"shakespeare"]),
    (830, "German Literature", [r"german literature", r"german.*fiction", r"german.*novel"]),
    (840, "French Literature", [r"french literature", r"french.*fiction", r"french.*novel"]),
    (860, "Spanish Literature", [r"spanish literature", r"latin.*american.*literatur", r"spanish.*fiction"]),
    (910, "Geography", [r"geograph", r"travel", r"map", r"atlas", r"country", r"continent", r"explor", r"cartograph"]),
    (920, "Biography", [r"biograph", r"autobiograph", r"memoir", r"life.*story"]),
]

UDC_MAP = [
    (0, "Generalities", [
        r"encyclopedia", r"encyclopaedia", r"dictionary", r"bibliograph",
        r"library", r"museum", r"journalis", r"newspaper", r"reference",
        r"knowledge", r"manuscript", r"archive",
    ]),
    (100, "Philosophy. Psychology", [
        r"philosoph", r"ethics", r"logic", r"metaphysic",
        r"epistemolog", r"aesthetic", r"consciousness", r"mind",
        r"ancient greek", r"stoic", r"existentialis", r"nietzsche",
        r"plato", r"aristotle", r"kant", r"hegel", r"phenomenolog",
    ]),
    (200, "Religion. Theology", [
        r"religion", r"theolog", r"bible", r"biblical", r"spiritual",
        r"christian", r"buddhis", r"hindu", r"islam", r"quran",
        r"meditation", r"prayer", r"faith", r"mytholog", r"gospel",
        r"scripture", r"prophet", r"apostle", r"catholic", r"protestant",
    ]),
    (300, "Social Sciences", [
        r"sociolog", r"politic", r"government",
        r"business", r"management", r"marketing", r"accounting", r"trade",
        r"social", r"anthropolog", r"culture",
        r"war", r"diplomac", r"international", r"poverty",
        r"demograph", r"urban", r"criminolog",
    ]),
    (500, "Natural Sciences. Mathematics", [
        r"science", r"molecular",
        r"geolog", r"astronom",
    ]),
    (600, "Applied Sciences. Medicine. Technology", [
        r"technolog", r"comput",
        r"software", r"network",
        r"manufactur", r"chemistry.*applied",
    ]),
    (700, "Arts. Recreation. Sport", [
        r"art", r"painting", r"sculpture", r"photograph",
        r"cinema", r"film", r"theatre", r"dance", r"sport", r"game",
        r"design", r"fashion", r"drawing", r"craft",
        r"pottery", r"cooking", r"recipe", r"food", r"wine",
        r"garden", r"hobb", r"collect", r"chess",
    ]),
    (800, "Language. Linguistics. Literature", [
        r"language", r"linguistic", r"grammar", r"vocabulary",
        r"english", r"french", r"spanish", r"german", r"chinese", r"japanese",
        r"russian", r"latin", r"translation",
        r"literature", r"novel", r"poetry", r"fiction", r"story", r"essay",
        r"drama", r"play", r"short story", r"antholog", r"classic",
        r"fairy tale", r"fantasy", r"science fiction", r"mystery",
        r"romance", r"thriller", r"horror", r"poem", r"prose",
    ]),
    (900, "Geography. Biography. History", [
        r"history",
        r"ancient", r"medieval", r"renaissance", r"world war",
        r"civilization", r"archaeolog", r"colonial", r"empire",
        r"kingdom", r"dynasty", r"revolution",
    ]),
]

# Build a quick lookup: "000" -> "Generalities", "004" -> "Computer Science", etc.
UDC_LABELS = {}
for code, label, _ in UDC_MAP:
    UDC_LABELS[f"{code:03d}"] = label
for code, label, _ in UDC_SUB_MAP:
    UDC_LABELS[f"{code:03d}"] = label


def classify(title, authors=None, subjects=None, description=None):
    all_tags = classify_all(title, authors, subjects, description)
    if not all_tags:
        return "000", "Generalities"
    best = all_tags[0]
    return best["tag"], best["tag_label"]


def classify_all(title, authors=None, subjects=None, description=None):
    text = " ".join(filter(None, [title, authors, description]))
    text = text.lower()
    if subjects:
        text += " " + " ".join(subjects).lower()

    results = []

    # Score sub-classifications first (higher specificity)
    for code, label, patterns in UDC_SUB_MAP:
        score = sum(10 if re.search(p, text) else 0 for p in patterns)
        if score > 0:
            results.append({"tag": f"{code:03d}", "tag_label": label, "score": score})

    # Score major categories (lower specificity, fallback)
    for code, label, patterns in UDC_MAP:
        score = sum(10 if re.search(p, text) else 0 for p in patterns)
        if score > 0:
            results.append({"tag": f"{code:03d}", "tag_label": label, "score": score})

    # Deduplicate by tag code (prefer higher score)
    seen = {}
    for r in results:
        k = r["tag"]
        if k not in seen or r["score"] > seen[k]["score"]:
            seen[k] = r

    results = sorted(seen.values(), key=lambda x: -x["score"])
    if not results:
        results.append({"tag": "000", "tag_label": "Generalities", "score": 0})
    return results
