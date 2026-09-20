import re

# ── Taxonomy ────────────────────────────────────────────────────────────────
# Each category: (code, label, [(regex_pattern, weight), ...]).
# Patterns are matched against lowercase title, filename, subjects, description,
# authors and publisher. Pattern weight x signal weight accumulate per category,
# and the top 5 categories are returned with weights normalised to sum to 100.
# Keep codes consistent with the UDC division scheme used by /api/summary.

UDC_MAP = [
    (0, "Generalities", [
        (r"encyclopedi", 8), (r"dictionary", 8), (r"dictionnaire", 8), (r"bibliograph", 7),
        (r"almanac", 6), (r"atlas", 5), (r"reference", 6), (r"handbook of", 4),
        (r"library science", 8), (r"museum", 7), (r"journalis", 7), (r"newspaper", 6),
        (r"periodical", 6), (r"manuscript", 6), (r"archive", 6), (r"general knowledge", 8),
        (r"trivia", 5), (r"curiosities", 5), (r"yearbook", 6), (r"compendium", 6),
    ]),
    (400, "Languages & Linguistics", [
        (r"language", 5), (r"linguistic", 9), (r"grammar", 9), (r"vocabulary", 8),
        (r"phrasebook", 10), (r"phrase book", 10), (r"foreign language", 9),
        (r"learn french", 9), (r"learn spanish", 9), (r"learn german", 9), (r"learn italian", 9),
        (r"learn japanese", 9), (r"learn chinese", 9), (r"learn english", 9),
        (r"french course", 9), (r"spanish course", 9), (r"english course", 9),
        (r"word power", 7), (r"etymolog", 9), (r"pronunciation", 8), (r"idiom", 7),
        (r"translation stud", 7), (r"semantics", 8), (r"phonetics", 8), (r"morpholog", 7),
        (r"syntax", 7), (r"dictionary of", 5), (r"visual dictionary", 10),
        (r"bilingual dictionary", 10), (r"picture dictionary", 10), (r"phrasebook", 10),
        (r"vocabulary builder", 9), (r"dictionaries", 8),
    ]),
    (100, "Philosophy", [
        (r"philosoph", 10), (r"epistemolog", 10), (r"metaphysic", 10), (r"ontology", 9),
        (r"logic", 6), (r"aesthetic", 7), (r"consciousness", 6), (r"existentialis", 10),
        (r"nihilism", 9), (r"pragmatism", 9), (r"stoicism", 10), (r"stoic", 9),
        (r"nietzsche", 10), (r"plato", 9), (r"aristotle", 9), (r"kant", 9),
        (r"hegel", 9), (r"schopenhauer", 9), (r"wittgenstein", 9), (r"camus", 8),
        (r"kierkegaard", 9), (r"hume", 8), (r"descartes", 9), (r"spinoza", 9),
        (r"phenomenolog", 10), (r"epicurus", 9), (r"ancient greek", 4), (r"dialectic", 7),
        (r"philosopher", 10), (r"thinker", 4), (r"weltanschauung", 9),
    ]),
    (150, "Psychology", [
        (r"psycholog", 10), (r"psychiatry", 9), (r"psychoanalys", 9), (r"psychotherap", 9),
        (r"behaviorism", 9), (r"behavioural", 8), (r"behavioral", 9),
        (r"cognitive", 6), (r"neuropsycholog", 10), (r"social psycholog", 10),
        (r"personality", 8), (r"self[- ]help", 9), (r"self help", 9), (r"self improvement", 9),
        (r"self-esteem", 8), (r"self esteem", 8), (r"motivation", 7), (r"emotional intelligence", 9),
        (r"mindfulness", 8), (r"meditation", 5), (r"mental health", 7), (r"depression", 6),
        (r"anxiety", 7), (r"trauma", 6), (r"neurotic", 8), (r"subconscious", 9),
        (r"unconscious", 7), (r"habit", 6), (r"procrastination", 8), (r"discipline", 5),
        (r"mindset", 7), (r"psychology of", 10), (r"jordan peterson", 9), (r"brene brown", 8),
        (r"thinking[, ]+fast", 8), (r"atomic habits", 9), (r"cognitive behavioral", 10), (r"cbt", 8),
        (r"narcissis", 9), (r"introvert", 8), (r"happiness", 6),
        (r"ego", 6), (r"success", 7), (r"influence", 8), (r"persuasion", 8),
        (r"deep work", 9), (r"focus", 6), (r"how to analyze people", 9), (r"analyze people", 9),
        (r"grit", 8), (r"resilience", 7), (r"mastery", 7), (r"48 laws of power", 8),
        (r"laws of power", 8), (r"willpower", 8), (r"self awareness", 8), (r"body language", 7),
        (r"outliers", 8), (r"switch how", 7), (r"comfort crisis", 8), (r"mindful", 6),
        (r"simplify your life", 8), (r"declutter", 8), (r"minimalist", 8), (r"joy of less", 9),
        (r"gretchen rubin", 8), (r"how to win friends", 9), (r"kahneman", 9),
        (r"gladwell", 8), (r"robert greene", 9), (r"cal newport", 9),
        (r"essentialis", 8), (r"dream big", 7), (r"miracle morning", 9),
        (r"indistractable", 9), (r"mind over", 7),
        (r"as a man thinketh", 9), (r"thinketh", 8), (r"autopilot", 8),
        (r"12 rules for life", 9),
    ]),
    (170, "Ethics", [
        (r"ethic", 8), (r"moral", 7), (r"morality", 9), (r"virtue", 8), (r"righteous",
         8), (r"utilitarianis", 9), (r"deontolog", 9), (r"values", 5), (r"ethical", 9),
    ]),
    (200, "Religion. Theology", [
        (r"religio", 9), (r"theolog", 10), (r"bible", 9), (r"biblical", 10), (r"gospel", 8),
        (r"scripture", 9), (r"christian", 8), (r"buddhis", 9), (r"buddhism", 10),
        (r"hindu", 9), (r"hinduism", 10), (r"islam", 9), (r"islamic", 9), (r"quran", 10),
        (r"koran", 10), (r"judaism", 10), (r"jewish", 7), (r"torah", 10), (r"talmud", 9),
        (r"spiritual", 8), (r"spirituality", 10), (r"prayer", 6), (r"faith", 6),
        (r"meditation", 4), (r"mytholog", 8), (r"prophet", 7), (r"apostle", 7),
        (r"catholic", 7), (r"protestant", 8), (r"mormon", 8), (r"evangelical", 8),
        (r"confucianism", 10), (r"taoism", 10), (r"daoism", 10), (r"zen", 5), (r"kabbalah", 10),
        (r"god and", 5), (r"atheism", 8), (r"agnostic", 7), (r"sufi", 9), (r"mysticism", 8),
        (r"pilgrimage", 6), (r"church", 5), (r"guru", 7), (r"yoga", 5), (r"ayatollah", 9),
        (r"veda", 10), (r"vedic", 10), (r"upanishad", 10), (r"samhita", 10), (r"shiksha", 9),
        (r"shiksa", 9), (r"purana", 10), (r"sanskrit", 9), (r"mahatmyam", 9), (r"\bdevi\b", 6),
        (r"bhagavad", 10), (r"(^|[^a-z])gita", 9), (r"astra", 6), (r"karma", 8),
        (r"dharma", 9), (r"mantra", 8), (r"tantra", 9), (r"yajur", 9), (r"rigveda", 10),
        (r"bhakti", 9), (r"ayurveda", 9), (r"jyotish", 9), (r"vedang", 10),
        (r"astrology", 6), (r"horoscope", 7), (r"fortunetelling", 8), (r"occult", 7),
        (r"isorc", 5), (r"witchcraft", 7), (r"wicca", 8), (r"\bpagan\b", 6),
    ]),
    (300, "Social Sciences", [
        (r"sociolog", 10), (r"anthropolog", 10), (r"ethnograph", 9), (r"culture", 4),
        (r"cultural", 5), (r"social", 4), (r"demograph", 9), (r"urban", 4), (r"criminolog", 9),
        (r"social science", 10), (r"social work", 8), (r"sociology of", 10),
        (r"poverty", 7), (r"inequality", 6), (r"gender", 6), (r"feminism", 8), (r"racism", 7),
        (r"immigration", 6), (r"refugee", 6), (r"community", 4), (r"scholarship", 3),
        (r"society", 5), (r"population", 4), (r"class in", 4),
    ]),
    (320, "Political Science", [
        (r"politic", 8), (r"political", 9), (r"government", 7), (r"democracy", 8),
        (r"election", 7), (r"voting", 7), (r"geopolitic", 9), (r"diplomac", 8),
        (r"international relations", 10), (r"foreign policy", 9), (r"public policy", 8),
        (r"ideology", 7), (r"totalitarianis", 9), (r"fascism", 9), (r"authoritarian", 8),
        (r"dictator", 7), (r"president", 6), (r"parliament", 7), (r"senator", 7),
        (r"congress", 6), (r"treaty", 6), (r"cold war", 7), (r"communism", 7),
        (r"soviet", 6), (r"putin", 6), (r"trump", 5), (r"obama", 6), (r"biden", 5),
        (r"trump era", 7), (r"statecraft", 9), (r"coalition", 6),
    ]),
    (330, "Economics", [
        (r"economic", 10), (r"economics", 10), (r"economy", 9), (r"finance", 8),
        (r"financial", 7), (r"finances", 8), (r"investing", 9), (r"investment", 8),
        (r"investor", 8), (r"trading", 8), (r"stock market", 10), (r"bourse", 9),
        (r"macroeconomic", 10), (r"microeconomic", 10), (r"capitalis", 9), (r"capitalism", 10),
        (r"keynes", 10), (r"inflation", 8), (r"interest rate", 8), (r"bond", 6),
        (r"derivative", 7), (r"portfolio", 8), (r"dividend", 7), (r"cryptocurrency", 8),
        (r"bitcoin", 8), (r"forex", 8), (r"foreign exchange", 8), (r"wealth", 6),
        (r"money", 5), (r"monetary", 8), (r"fiscal", 8), (r"gdp", 8), (r"recession", 8),
        (r"austerity", 8), (r"globalization", 7), (r"trade", 5), (r"commodities", 8),
        (r"the wealth of nations", 10), (r"freakonomics", 10), (r"naked economics", 10),
        (r"billionaire", 7),
    ]),
    (340, "Law", [
        (r"\blaw\b", 7), (r"legal", 7), (r"constitution", 7), (r"constitutional", 8),
        (r"criminal law", 9), (r"civil law", 9), (r"jurisprudence", 10),
        (r"legislation", 8), (r"\bcourt", 7), (r"litigation", 9), (r"attorney", 8),
        (r"lawyer", 8), (r"legal defense", 9), (r"the rule of law", 10), (r"supreme court",
         9), (r"judg", 7), (r"verdict", 8), (r"evidence", 6), (r"justice", 6),
        (r"copyright", 7), (r"patent law", 10), (r"contract law", 10), (r"tort", 7),
        (r"international law", 10), (r"human rights law", 10), (r"immigration law", 9),
    ]),
    (355, "Military Science", [
        (r"military", 9), (r"warfare", 8), (r"\bwar\b", 7), (r"wars", 6), (r"army", 7),
        (r"navy", 7), (r"marines", 8), (r"air force", 8), (r"soldier", 7), (r"combat", 7),
        (r"battle", 6), (r"weapon", 7), (r"firearm", 7), (r"strategy", 6), (r"tactics", 7),
        (r"general ", 5), (r"special forces", 9), (r"naval", 7), (r"guerrilla", 8),
        (r"sniper", 8), (r"drone warfare", 9), (r"surrender", 6), (r"victory", 5),
        (r"warrior", 6), (r"kamikaze", 8),
        (r"\btank\b", 5), (r"tank warfare", 9), (r"armored", 7), (r"armoured", 7),
        (r"fighting vehicle", 8), (r"firearms", 8),
    ]),
    (370, "Education", [
        (r"education", 8), (r"educat", 4), (r"teaching", 8), (r"teach ", 4),
        (r"pedagog", 10), (r"curriculum", 9), (r"classroom", 8), (r"school", 4),
        (r"university", 4), (r"college", 4), (r"training", 4), (r"learning", 4),
        (r"study skills", 9), (r"homework", 7), (r"exam prep", 9), (r"textbook", 6),
        (r"lesson plan", 9), (r"homeschool", 8), (r"student", 5), (r"teacher", 6),
        (r"sat prep", 8), (r"gre prep", 8), (r"iq test", 7), (r"how to study", 9),
        (r"learning how to learn", 10), (r"montessori", 9), (r"education of", 8),
    ]),
    (500, "Natural Sciences. Mathematics", [
        (r"science", 5), (r"scientific", 6), (r"natural science", 10), (r"molecular", 4),
        (r"geoscienc", 8), (r"life sciences", 9), (r"physics", 3),
        (r"science of", 6), (r"a brief history of time", 9),
    ]),
]

UDC_SUB_MAP = [
    (4, "Computer Science", [
        (r"computer science", 10), (r"computing", 8), (r"information technology", 9),
        (r"it\u2019s", 0), (r"software engineering", 9), (r"cybersecur", 10),
        (r"network", 5), (r"operating system", 8), (r"database", 7), (r"data structure", 9),
        (r"computer architecture", 10), (r"computer network", 10), (r"linux", 7),
        (r"windows", 5), (r"unix", 7), (r"cloud computing", 9), (r"distributed systems", 9),
        (r"compiler", 8), (r"compilers", 8), (r"internet", 5), (r"web development", 8),
        (r"frontend", 8), (r"backend", 8), (r"rest api", 7), (r"microservice", 8),
        (r"docker", 7), (r"kubernetes", 8), (r"hacking", 8), (r"hacker", 7),
        (r"forensics", 6), (r"information systems", 9), (r"computer", 8),
        (r"digital electronics", 7), (r"encryption", 7), (r"cryptography", 8),
        (r"system design", 8), (r"systems design", 8), (r"architecture of", 6),
    ]),
    (5, "Programming", [
        (r"programming", 10), (r"programmer", 9), (r"coding", 8), (r"code ", 5),
        (r"software development", 9), (r"algorithm", 9), (r"algorithms", 9),
        (r"python", 8), (r"javascript", 8), (r"typescript", 8), (r"java programming", 10),
        (r"c programming", 10), (r"c\+\+", 8), (r"c#", 7), (r"golang", 8), (r"go programming", 9),
        (r"rust programming", 10), (r"ruby", 7), (r"php", 7), (r"sql", 7),
        (r"data structures and algorithms", 10), (r"learn to code", 9), (r"clean code", 9),
        (r"refactor", 8), (r"automate the boring", 10), (r"pragmatic programmer", 10),
        (r"computer programming", 10), (r"functional programming", 9),
        (r"object.orient", 8), (r"regex", 8), (r"regular expression", 8), (r"git and", 6),
        (r"bash", 6), (r"shell scripting", 8),
    ]),
    (6, "AI / Data Science", [
        (r"artificial intelligence", 10), (r"machine learning", 10), (r"deep learning", 10),
        (r"neural network", 10), (r"data science", 10), (r"data analytics", 9),
        (r"data mining", 9), (r"big data", 9), (r"computer vision", 9),
        (r"natural language processing", 10), (r"nlp", 7), (r"tensorflow", 8),
        (r"pytorch", 8), (r"chatgpt", 9), (r"gpt", 7), (r"large language model", 10),
        (r"llm", 7), (r"reinforcement learning", 10), (r"recommender system", 9),
        (r"data engineering", 8), (r"analytics", 6), (r"ai and", 8), (r"machine intelligence", 9),
        (r"statistical learning", 9), (r"prediction", 5), (r"intelligent agent", 9),
    ]),
    (510, "Mathematics", [
        (r"mathemat", 10), (r"calculus", 9), (r"algebra", 9), (r"geometry", 9),
        (r"trigonometr", 9), (r"statistics", 8), (r"statistic", 7), (r"probabil", 8),
        (r"differential", 8), (r"linear algebra", 10), (r"number theory", 9),
        (r"combinator", 9), (r"topolog", 8), (r"graph theory", 9), (r"optimization", 7),
        (r"matrix", 7), (r"arithmetic", 8), (r"fraction", 7), (r"equation", 6),
        (r"math", 7), (r"mathematical", 9), (r"geometry and", 8),
        (r"the art of statistics", 10), (r"concrete mathematics", 10),
        (r"how to prove", 7), (r"puzzle", 6), (r"game theory", 8),
        (r"set theory", 9), (r"chaos theory", 8), (r"fractal", 8),
    ]),
    (520, "Astronomy", [
        (r"astronom", 10), (r"astrophysics", 10), (r"cosmos", 8), (r"cosmolog", 9),
        (r"galaxy", 8), (r"universe", 7), (r"black hole", 9), (r"nebula", 8),
        (r"planet", 7), (r"planetary", 8), (r"starl", 7), (r"telescope", 8),
        (r"space exploration", 8), (r"nasa", 7), (r"rocket", 7), (r"orbit", 6),
        (r"solar system", 9), (r"exoplanet", 9), (r"mars", 6), (r"the moon", 6),
        (r"car sagan", 9), (r"hawking", 8), (r"stellar", 7), (r"gravitational", 6),
    ]),
    (530, "Physics", [
        (r"physics", 10), (r"physicist", 9), (r"mechanics", 7), (r"thermodynam", 9),
        (r"electromagnet", 9), (r"quantum", 9), (r"relativit", 9), (r"nuclear", 7),
        (r"optics", 8), (r"acoustics", 8), (r"particle physics", 10), (r"standard model", 8),
        (r"quantum mechanics", 10), (r"string theory", 9), (r"electrodynamics", 9),
        (r"condensed matter", 9), (r"laser", 7), (r"photon", 7), (r"einstein", 8),
        (r"fermion", 9), (r"boson", 9), (r"entropy", 7), (r"wave", 5),
        (r"electricity and magnetism", 9),
    ]),
    (540, "Chemistry", [
        (r"chemistr", 10), (r"chemistry", 10), (r"biochemist", 9), (r"organic chemistry", 10),
        (r"inorganic chemistry", 10), (r"molecular", 5), (r"chemical", 7), (r"periodic table", 9),
        (r"element", 5), (r"atom", 6), (r"molecule", 7), (r"reaction", 5),
        (r"laboratory", 5), (r"alchem", 7), (r"toxicol", 8), (r"elementary particles", 5),
    ]),
    (550, "Earth Sciences", [
        (r"geolog", 9), (r"earth science", 10), (r"climat", 7), (r"weather", 6),
        (r"meteorolog", 9), (r"seismolog", 9), (r"volcano", 8), (r"earthquake", 8),
        (r"oceanograph", 9), (r"hydrolog", 8), (r"ecology", 6), (r"environmental", 5),
        (r"mineral", 7), (r"rock", 5), (r"plate tectonic", 9), (r"glacier", 8),
        (r"fossil", 8), (r"paleontolog", 9), (r"climate change", 8), (r"global warming", 8),
    ]),
    (570, "Biology", [
        (r"biology", 10), (r"biological", 9), (r"genetic", 9), (r"genome", 9),
        (r"evolution", 8), (r"evolutionary", 9), (r"ecolog", 9), (r"neuroscien", 10),
        (r"molecular biology", 10), (r"cell biology", 10), (r"organism", 7),
        (r"botan", 8), (r"zoolog", 9), (r"microbiology", 10), (r"immunolog", 9),
        (r"virology", 9), (r"biotechnolog", 8), (r"gene", 6), (r"dna", 7),
        (r"rna", 7), (r"species", 6), (r"organism", 6), (r"cell", 5),
        (r"anatomy and physiology", 8), (r"darwin", 8), (r"crick", 8), (r"mendel", 8),
    ]),
    (610, "Medicine", [
        (r"medicine", 9), (r"medical", 8), (r"clinical", 8), (r"diagnos", 7),
        (r"surgery", 9), (r"surgical", 9), (r"pharma", 7), (r"pharmacolog", 9),
        (r"nursing", 8), (r"disease", 6), (r"anatomy", 8), (r"physiolog", 8),
        (r"patholog", 9), (r"epidemiol", 9), (r"pediatric", 8), (r"cardiology", 9),
        (r"neurology", 8), (r"oncology", 9), (r"psychiatry", 7), (r"dentistry", 8),
        (r"dental", 8), (r"emergency medicine", 10), (r"first aid", 8), (r"diagnostic", 8),
        (r"patient", 6), (r"hospital", 6), (r"doctor", 6), (r"physician", 7),
        (r"health care", 6), (r"healthcare", 7), (r"public health", 7), (r"vaccine", 8),
        (r"pandemic", 7), (r"infectious", 7), (r"antibiotic", 8), (r"insulin", 8),
        (r"medication", 8), (r"drugs", 6), (r"prescription", 7), (r"thyroid", 8),
    ]),
    (620, "Engineering", [
        (r"engineer", 8), (r"engineering", 9), (r"mechanical engineering", 10),
        (r"electrical engineering", 10), (r"civil engineering", 10),
        (r"electronic", 7), (r"electronics", 8), (r"robotic", 8), (r"robotics", 9),
        (r"aerospace", 9), (r"chemical engineering", 10), (r"structural", 6),
        (r"machinery", 6), (r"geotechnical", 9), (r"mechatronics", 9), (r"signal processing", 8),
        (r"embedded system", 8), (r"microcontroller", 8), (r"arduino", 8),
        (r"circuit", 7), (r"semiconductor", 8), (r"telecommunication", 8),
        (r"manufactur", 6), (r"industrial engineering", 10), (r"thermofluids", 8),
        (r"aircraft", 8), (r"aviation", 8), (r"steam engine", 8), (r"locomotive", 8),
        (r"internal combustion", 8), (r"propeller", 7), (r"machine shop", 7),
        (r"tool making", 8), (r"precision mechanics", 9), (r"mechanical", 7),
    ]),
    (630, "Agriculture", [
        (r"agricultur", 9), (r"farming", 8), (r"crop", 7), (r"soil", 5),
        (r"horticultur", 9), (r"viticultur", 9), (r"agronom", 9), (r"livestock", 8),
        (r"poultry", 8), (r"garden", 6), (r"gardening", 8), (r"orchard", 7),
        (r"hydroponic", 8), (r"aquaculture", 9), (r"bee.", 7), (r"winemaking", 9),
        (r"agronomy", 9), (r"compost", 8),
    ]),
    (640, "Cookery & Home Economics", [
        (r"cook", 8), (r"cooking", 10), (r"cookbook", 10), (r"cook book", 10), (r"recipe", 9),
        (r"baking", 9), (r"bake", 7), (r"kitchen", 7), (r"chef", 8), (r"cuisine", 9),
        (r"gastronom", 9), (r"food", 5), (r"dish", 5), (r"meal", 5), (r"dessert", 8),
        (r"pastry", 8), (r"bread", 7), (r"barbecue", 8), (r"sous vide", 8),
        (r"full vegan", 7), (r"vegans", 7), (r"vegetarian", 8), (r"gluten free", 8),
        (r"nutrition", 7), (r"home economics", 10),
        (r"fermentation", 7), (r"pickling", 8), (r"sourdough", 8),
        (r"coffee", 8), (r"cocktail", 9), (r"whiskey", 8), (r"whisky", 8),
        (r"cocktails", 9), (r"barista", 8), (r"espresso", 8),
        (r"\bdiy", 8), (r"do it yourself", 8), (r"home maintenance", 7),
        (r"handyman", 8), (r"home repair", 8),
    ]),
    (650, "Business & Management", [
        (r"business", 8), (r"management", 6), (r"manager", 6), (r"marketing", 8),
        (r"entrepreneur", 9), (r"startup", 8), (r"leadership", 7), (r"lead", 4),
        (r"strategy", 5), (r"operations", 5), (r"supply chain", 8), (r"sales", 6),
        (r"recruit", 7), (r"management consulting", 9), (r"organizational", 8),
        (r"organisational", 8), (r"corporate", 6), (r"branding", 8), (r"advertis", 7),
        (r"negotiation", 8), (r"pitch", 6), (r"lean", 5), (r"six sigma", 8),
        (r"product management", 9), (r"project management", 8), (r"agile", 7),
        (r"scrum", 7), (r"business model", 8),
        (r"productividad", 5), (r"productivity", 6), (r"working from home", 5),
        (r"the lean startup", 10), (r"zero to one", 9), (r"from good to great", 9),
        (r"\bmba\b", 10), (r"case study", 8), (r"business school", 9),
        (r"executive", 6), (r"hbr", 7), (r"personal mba", 10),
    ]),
    (657, "Accounting", [
        (r"accounting", 9), (r"accountancy", 9), (r"audit", 7), (r"bookkeeping", 9),
        (r"ledger", 7), (r"balance sheet", 8), (r"taxes", 6), (r"tax ", 5),
        (r"taxation", 8), (r"invoice", 6), (r"spreadsheet", 5), (r"financial statement", 8),
        (r"payroll", 8),
    ]),
    (700, "Arts. Recreation. Sport", [
        (r"\bart\b", 6), (r"arts", 7), (r"painting", 7), (r"sculpture", 8), (r"photograph", 6),
        (r"cinema", 7), (r"\bfilm", 6), (r"\bmovie", 6), (r"theatre", 7), (r"theater", 7),
        (r"dance", 7), (r"\bsport", 7), (r"sports", 8), (r"\bgame", 5), (r"design", 5),
        (r"fashion", 7), (r"drawing", 6), (r"craft", 6), (r"pottery", 8),
        (r"food and wine", 6), (r"wine", 6), (r"hobb", 6), (r"collect", 5),
        (r"chess", 7), (r"yoga", 5), (r"surfing", 7), (r"skiing", 7), (r"climbing", 6),
        (r"art of", 6), (r"makeup", 5), (r"jewel", 6), (r"illustration", 6),
        (r"animation", 6), (r"interior", 4), (r"furniture", 5),
    ]),
    (720, "Architecture", [
        (r"architect", 9), (r"architecture", 10), (r"building", 5), (r"urban design", 10),
        (r"construct", 6), (r"interior design", 9), (r"landscape architect", 9),
        (r"facade", 7), (r"blueprint", 7), (r"planning", 5), (r"dwelling", 6),
        (r"real estate", 5),
    ]),
    (740, "Drawing & Graphic Design", [
        (r"drawing", 7), (r"sketch", 8), (r"illustr", 7), (r"comic", 8), (r"comics", 9),
        (r"manga", 9), (r"graphic novel", 9), (r"graphic design", 9), (r"calligraphy", 8),
        (r"lettering", 7), (r"concept art", 8), (r"storyboard", 8), (r"ink drawing", 9),
        (r"pencil", 6), (r"watercolor", 8), (r"watercolour", 8), (r"doodle", 7),
        (r"typography", 7), (r"digital art", 9), (r"digital painting", 9),
        (r"digital work", 8), (r"blender", 8), (r"3d modelling", 8), (r"3d modeling", 8),
        (r"zbrush", 9), (r"concept artist", 8), (r"airbrush", 8), (r"airbrushing", 9),
    ]),
    (770, "Photography", [
        (r"photograph", 8), (r"photography", 10), (r"photo", 6), (r"camera", 8),
        (r"lens", 7), (r"exposure", 6), (r"photoshop", 7), (r"lightroom", 8),
        (r"portrait", 6), (r"street photography", 10), (r"landscape photography", 10),
        (r"dslr", 8), (r"mirrorless", 8), (r"digital photography", 10),
    ]),
    (780, "Music", [
        (r"music", 8), (r"musical", 7), (r"compos", 7), (r"composition", 8),
        (r"orchestra", 9), (r"instrument", 7), (r"piano", 8), (r"guitar", 8),
        (r"violin", 8), (r"symphon", 8), (r"opera", 8), (r"jazz", 7), (r"blues", 7),
        (r"classical music", 9), (r"song", 6), (r"singer", 7), (r"vinyl", 6),
        (r"\bdj\b", 7), (r"music theory", 9), (r"ableton", 8), (r"rock band", 7),
        (r"beatles", 8), (r"beethoven", 9), (r"mozart", 9), (r"bach", 7),
        (r"guitar chord", 9), (r"sheet music", 9),
    ]),
    (790, "Sports & Games", [
        (r"\bsport", 7), (r"sports", 8), (r"football", 7), (r"soccer", 7),
        (r"basketball", 8), (r"tennis", 8), (r"golf", 7), (r"cricket", 7),
        (r"rugby", 8), (r"boxing", 8), (r"martial arts", 8), (r"wrestling", 7),
        (r"olympic", 8), (r"athlet", 6), (r"fitness", 7), (r"gym", 6),
        (r"chess", 7), (r"poker", 7), (r"gaming", 6), (r"video game", 7),
        (r"board game", 7), (r"dungeons and dragons", 9), (r"card game", 7),
        (r"running", 6), (r"marathon", 8), (r"cycling", 8), (r"triathlon", 8),
        (r"sports illustrated", 9), (r"physical fitness", 8),
    ]),
    (800, "Literature", [
        (r"literature", 8), (r"literary", 8), (r"novel", 7), (r"novels", 7),
        (r"fiction", 7), (r"short story", 8), (r"short stories", 8), (r"poetry", 8),
        (r"poem", 7), (r"poems", 7), (r"prose", 7), (r"antholog", 7), (r"essay", 6),
        (r"essays", 7), (r"drama", 6), (r"play", 4), (r"plays", 5), (r"fantasy", 7),
        (r"science fiction", 8), (r"sci-fi", 8), (r"mystery", 7), (r"thriller", 7),
        (r"horror", 7), (r"romance", 6), (r"adventure", 6), (r"tale", 5),
        (r"fairy tale", 7), (r"classic", 5), (r"world literature", 9),
        (r"translation", 5), (r"the collected", 6), (r"great american novel", 9),
        (r"detective", 6), (r"crime fiction", 8), (r"literary criticism", 9),
        (r"book club", 6),
    ]),
    (810, "American Literature", [
        (r"american literature", 10), (r"american novel", 9), (r"american fiction", 9),
        (r"american poetry", 9), (r"american short stories", 9), (r"american classic", 8),
        (r"harlem renaissance", 9), (r"mark twain", 8), (r"hemingway", 8),
        (r"faulkner", 8), (r"toni morrison", 8), (r"fitzgerald", 8), (r"steinbeck", 8),
        (r"melville", 8), (r"edgar allen poe", 9), (r"poe,", 7), (r"walt whitman", 8),
        (r"emily dickinson", 8), (r"john updike", 8), (r"john steinbeck", 9),
        (r"james baldwin", 8), (r"flannery o'connor", 9), (r"kurt vonnegut", 8),
        (r"hitch", 5), (r"to kill a mockingbird", 10),
        (r"cormac mccarthy", 9), (r"mccarthy", 7), (r"pynchon", 8), (r"gravity.s rainbow", 9),
        (r"catch.?22", 8), (r"harper lee", 9), (r"salinger", 8), (r"the great gatsby", 9),
    ]),
    (820, "English Literature", [
        (r"english literature", 10), (r"british literature", 10),
        (r"english novel", 9), (r"british fiction", 9), (r"english poetry", 9),
        (r"shakespeare", 9), (r"shakespearean", 9), (r"austen", 8), (r"jane austen", 9),
        (r"dickens", 8), (r"charles dickens", 9), (r"orwell", 8), (r"george orwell", 9),
        (r"tolkein", 8), (r"tolkien", 9), (r"j. r. r. tolkien", 9), (r"c. s. lewis", 8),
        (r"conan doyle", 8), (r"agatha christie", 8), (r"wilde", 7), (r"oscar wilde", 9),
        (r"bront", 8), (r"virginia woolf", 9), (r"george eliot", 8), (r"james joyce", 8),
        (r"d. h. lawrence", 9), (r"john milton", 8), (r"william wordsworth", 9),
        (r"keats", 8), (r"byron", 8), (r"shelley", 7), (r"pride and prejudice", 10),
    ]),
    (830, "German Literature", [
        (r"german literature", 10), (r"german fiction", 9), (r"german novel", 9),
        (r"goethe", 9), (r"kafka", 8), (r"hesse", 8), (r"mann", 6), (r"thomas mann", 9),
        (r"brecht", 9), (r"grass", 6), (r"die blechtrommel", 9), (r"winnetou", 9),
        (r"schiller", 9), (r"auf deutsch", 8), (r"deutsche literatur", 10),
    ]),
    (840, "French Literature", [
        (r"french literature", 10), (r"french fiction", 9), (r"french novel", 9),
        (r"hugo", 8), (r"v. hugo", 8), (r"balzac", 8), (r"flaubert", 8),
        (r"proust", 9), (r"camus", 8), (r"sartre", 8), (r"zola", 8), (r"maupassant", 9),
        (r"dumas", 8), (r"les misérables", 9), (r"de laclos", 8), (r"stendhal", 9),
        (r"molière", 9), (r"littérature", 8),
    ]),
    (850, "Italian Literature", [
        (r"italian literature", 10), (r"italian fiction", 9), (r"italian novel", 9),
        (r"dante", 9), (r"boccaccio", 9), (r"machiavelli", 8), (r"calvino", 8),
        (r"eco and", 7), (r"umberto eco", 9), (r"the divine comedy", 9),
        (r"petrarch", 9), (r"italia", 5), (r"letteratura italiana", 10),
    ]),
    (860, "Spanish Literature", [
        (r"spanish literature", 10), (r"latin american literature", 10),
        (r"spanish fiction", 9), (r"spanish novel", 9), (r"cervantes", 9),
        (r"borges", 9), (r"márquez", 9), (r"garcía márquez", 10), (r"pablo neruda", 9),
        (r"isabel allende", 9), (r"rulfo", 9), (r"literatura española", 10),
        (r"español", 6), (r"don quijote", 10),
    ]),
    (880, "Classical Greek & Latin Literature", [
        (r"greek literature", 10), (r"latin literature", 10), (r"ancient greek", 7),
        (r"iliad", 9), (r"odyssey", 9), (r"aeneid", 9), (r"homer", 9), (r"euripides", 9),
        (r"sophocles", 9), (r"aeschylus", 9), (r"virgil", 9), (r"ovid", 9),
        (r"the odyssey", 9), (r"greek tragedy", 9), (r"the iliad", 9),
    ]),
    (891, "Russian Literature", [
        (r"russian literature", 10), (r"russian fiction", 9), (r"russian novel", 9),
        (r"dostoevsky", 9), (r"dostoyevsky", 9), (r"tolstoy", 9), (r"leo tolstoy", 10),
        (r"chekhov", 9), (r"turgenev", 9), (r"gogol", 9), (r"pushkin", 9),
        (r"solzhenitsyn", 9), (r"nabokov", 8), (r"brothers karamazov", 10),
        (r"war and peace", 10), (r"crime and punishment", 10),
    ]),
    (892, "Arabic & Semitic Literature", [
        (r"arabic literature", 10), (r"hebrew literature", 10), (r"arab", 5),
        (r"hebrew", 6), (r"thousand and one nights", 9), (r"arabian nights", 9),
        (r"gibran", 9), (r"kahlil gibran", 10),
    ]),
    (895, "East Asian Literature", [
        (r"chinese literature", 10), (r"japanese literature", 10), (r"korean literature", 10),
        (r"haiku", 9), (r"murakami", 9), (r"haruki murakami", 10), (r"genji", 9),
        (r"wuxia", 9), (r"japanese fiction", 9),
    ]),
    (910, "Geography & Travel", [
        (r"geograph", 9), (r"\btravel", 8), (r"travels", 8), (r"traveller", 8),
        (r"traveler", 8), (r"tour", 6), (r"tourism", 7), (r"explor", 7),
        (r"cartograph", 9), (r"country", 5), (r"continent", 7), (r"destination", 6),
        (r"backpacking", 8), (r"wanderlust", 8), (r"road trip", 8), (r"lonely planet", 8),
        (r"topographic", 9), (r"mapping", 5), (r"geographical", 9),
        (r"travel guide", 9), (r"guide to", 4), (r"(^|[^a-z])japan([^a-z]|$)", 5),
        (r"(^|[^a-z])india([^a-z]|$)", 4), (r"(^|[^a-z])africa([^a-z]|$)", 4),
        (r"(^|[^a-z])australia([^a-z]|$)", 5), (r"(^|[^a-z])asia([^a-z]|$)", 5),
    ]),
    (920, "Biography", [
        (r"biograph", 9), (r"autobiograph", 9), (r"memoir", 8), (r"life story", 9),
        (r"life and times", 8), (r"the autobiography", 10), (r"my autobiography", 10),
        (r"reminiscence", 7), (r"portrait of the artist", 7), (r"and biography", 9),
        (r"bios", 5),
    ]),
    (940, "European History", [
        (r"european history", 10), (r"europe ", 6), (r"historical europe", 9),
        (r"roman empire", 8), (r"ancient rome", 8), (r"ancient greece", 8),
        (r"world war", 8), (r"wwii", 8), (r"wwi", 8), (r"holocaust", 8),
        (r"nazi", 7), (r"france ", 5), (r"germany ", 5), (r"italy ", 5),
        (r"medieval", 7), (r"middle ages", 8), (r"crusade", 7), (r"viking", 7),
        (r"renaissance", 7), (r"enlightenment", 7), (r"french revolution", 9),
        (r"victorian england", 8), (r"the tudors", 8), (r"anglo.saxon", 8),
        (r"byzantine", 8), (r"ottomans", 8), (r"golden horde", 8), (r"visigoth", 8),
        (r"habsburg", 8), (r"napoleon", 8), (r"history of europe", 10),
    ]),
]

# ── Per-signal multipliers ──────────────────────────────────────────────────
SIGNAL_WEIGHTS = {
    "title": 3.0,
    "filename": 2.0,
    "subjects": 2.0,
    "description": 1.2,
    "authors": 0.9,
    "publisher": 0.6,
}

TOP_N = 5


def _compile(cats):
    return [(code, label, [(re.compile(p, re.I), w) for p, w in patterns]) for code, label, patterns in cats]


_ALL = _compile(UDC_MAP) + _compile(UDC_SUB_MAP)

# Build a quick lookup: "000" -> "Generalities", "004" -> "Computer Science", etc.
UDC_LABELS = {}
for code, label, _ in UDC_MAP:
    UDC_LABELS[f"{code:03d}"] = label
for code, label, _ in UDC_SUB_MAP:
    UDC_LABELS[f"{code:03d}"] = label

# ── Non-Latin script fallback ────────────────────────────────────────────────
# When no keyword in the taxonomy matches (e.g. titles in Devanagari, Cyrillic,
# Arabic or CJK), fall back to the written script so foreign-language books still
# land on a plausible UDC division instead of bare "000 Generalities".
# (code, label, compiled regex over a Unicode block)
_SCRIPT_FALLBACKS = [
    ("880", "Classical Greek & Latin Literature",
     re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")),            # Greek
    ("891", "Russian & Slavic Literatures",
     re.compile(r"[\u0400-\u04ff\u0500-\u052f]")),            # Cyrillic
    ("892", "Arabic & Semitic Literatures",
     re.compile(r"[\u0590-\u05ff\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")),  # Hebrew + Arabic
    ("200", "Religion. Theology",
     re.compile(r"[\u0900-\u097f\u0980-\u09ff\u0a00-\u0a7f\u0a80-\u0aff\u0b00-\u0b7f"
                r"\u0b80-\u0bff\u0c00-\u0c7f\u0c80-\u0cff\u0d00-\u0d7f\u0d80-\u0dff"
                r"\u0de0-\u0dff\u0e00-\u0e7f]")),             # Indic scripts + Tai
    ("895", "East Asian Literatures",
     re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\u3400-\u4dbf\uac00-\ud7af]")),     # JP + CJK + Hangul
]


def _script_category(text):
    """Return (code, label) for a non-Latin script, else None."""
    for code, label, rx in _SCRIPT_FALLBACKS:
        if rx.search(text):
            return code, label
    return None


def _texts(title, authors, subjects, description, filename, publisher):
    parts = []
    if title:
        parts.append((str(title), "title"))
    if filename:
        import os
        stem = os.path.splitext(str(filename))[0]
        stem = re.sub(r"[_\-\+]+", " ", stem)
        parts.append((stem, "filename"))
    if subjects:
        if isinstance(subjects, (list, tuple)):
            s = " ".join(str(x) for x in subjects)
        else:
            s = str(subjects)
        parts.append((s, "subjects"))
    if description:
        parts.append((str(description), "description"))
    if authors:
        if isinstance(authors, (list, tuple)):
            a = " ".join(str(x) for x in authors)
        else:
            a = str(authors)
        parts.append((a, "authors"))
    if publisher:
        parts.append((str(publisher), "publisher"))
    return [(text.lower(), kind) for text, kind in parts]


def classify(title, authors=None, subjects=None, description=None, filename=None, publisher=None):
    all_tags = classify_all(title, authors, subjects, description, filename, publisher)
    if not all_tags:
        return "000", "Generalities"
    best = all_tags[0]
    return best["tag"], best["tag_label"]


def classify_all(title, authors=None, subjects=None, description=None, filename=None, publisher=None):
    """Return the top-N ranked UDC categories.

    Each dict: {"tag", "tag_label", "score", "weight"} where weight is the
    percentage share of the top-N total score (sums to 100).
    """
    signals = _texts(title, authors, subjects, description, filename, publisher)
    if not signals:
        return [{"tag": "000", "tag_label": "Generalities", "score": 0, "weight": 100}]

    results = []
    for code, label, patterns in _ALL:
        score = 0.0
        for text, kind in signals:
            mult = SIGNAL_WEIGHTS.get(kind, 1.0)
            for rx, pweight in patterns:
                if rx.search(text):
                    score += pweight * mult
        if score > 0:
            results.append({"tag": f"{code:03d}", "tag_label": label, "score": score})

    if not results:
        joined = " ".join(text for text, _ in signals)
        script = _script_category(joined)
        if script:
            return [{"tag": script[0], "tag_label": script[1], "score": 0, "weight": 100}]
        return [{"tag": "000", "tag_label": "Generalities", "score": 0, "weight": 100}]

    results.sort(key=lambda x: -x["score"])
    top = results[:TOP_N]

    total = sum(r["score"] for r in top)
    if total <= 0:
        top[0]["weight"] = 100
        for r in top[1:]:
            r["weight"] = 0
    else:
        weights = [round(r["score"] / total * 100) for r in top]
        diff = 100 - sum(weights)
        if diff:
            # Give the rounding remainder to the best match
            weights[0] += diff
        for r, w in zip(top, weights):
            r["weight"] = w

    return top


# ── Bulk backfill ────────────────────────────────────────────────────────────
def uncategorized_masters(conn):
    """Master files that have no meaningful UDC code yet."""
    return conn.execute(
        "SELECT COUNT(*) FROM files f "
        "LEFT JOIN metadata m ON m.file_id = f.id "
        "WHERE f.is_master = 1 "
        "AND (m.udc_code IS NULL OR m.udc_code = '' OR m.udc_code = '000')"
    ).fetchone()[0]


def reclassify_masters(conn, limit=None, force=False):
    """Re-run classification for master books and persist the primary UDC code
    plus the top-N weighted categories.

    Books whose UDC was set manually (enrich_source == 'manual') are skipped
    unless force=True. Returns a stats dict.
    """
    from db import get_category_scores  # noqa: F401  (imports the module, ensures schema)
    from db import save_category_scores, set_tags, upsert_metadata

    sql = (
        "SELECT f.id, f.filename, m.title, m.authors, m.subjects, m.description, "
        "       m.publisher, m.udc_code, m.enrich_source "
        "FROM files f LEFT JOIN metadata m ON m.file_id = f.id "
        "WHERE f.is_master = 1"
    )
    if not force:
        sql += " AND (m.enrich_source IS NULL OR m.enrich_source != 'manual')"
    if force:
        sql += " AND (m.udc_code IS NULL OR m.udc_code = '' OR m.udc_code = '000')"
    sql += " ORDER BY f.id"

    rows = conn.execute(sql).fetchall()

    stats = {"scanned": 0, "categorized": 0, "uncat": 0, "manual_skipped": 0, "limit": limit}
    changed_any = False

    for r in rows:
        if limit and stats["scanned"] >= limit:
            stats["limit_reached"] = True
            break
        stats["scanned"] += 1

        title = r["title"] or ""
        authors = r["authors"] or ""
        subjects = r["subjects"] or ""
        description = r["description"] or ""
        filename = r["filename"] or ""
        publisher = r["publisher"] or ""

        tags = classify_all(title, authors, subjects, description, filename, publisher)
        primary = tags[0]

        old = r["udc_code"] or ""
        if primary["tag"] != old:
            upsert_metadata(conn, r["id"], udc_code=primary["tag"], udc_label=primary["tag_label"])
        save_category_scores(conn, r["id"], tags)
        set_tags(conn, r["id"], tags, tag_type="udc")
        stats["categorized"] += 1 if (primary["tag"] != "000" and primary["weight"] >= 40) else 0
        if primary["tag"] == "000":
            stats["uncat"] += 1
        changed_any = True

    if changed_any:
        conn.commit()

    stats["uncategorized_before"] = uncategorized_masters(conn)
    return stats