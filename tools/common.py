"""Shared helpers: fetching, Arabic normalization, link classification, facets."""
import hashlib, os, re, time, urllib.request

HUB = "1Yj0AP9xVrkLqIf01mdelU4m4OcQR-NGxuTNYpGeiIvM"
DOCX = "https://docs.google.com/document/d/{}/export?format=docx"
MOBILE = "https://docs.google.com/document/d/{}/mobilebasic"
UA = "mazda-docs-sync/1.0 (community mirror; contact via repo)"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")

# ------------------------------------------------------------------ fetching
def fetch(url, ttl=0, timeout=300):
    """GET with an on-disk cache. ttl=0 always refetches, ttl>0 reuses fresh files."""
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:16])
    if ttl and os.path.exists(key) and time.time() - os.path.getmtime(key) < ttl:
        return open(key, "rb").read()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    body = urllib.request.urlopen(req, timeout=timeout).read()
    open(key, "wb").write(body)
    return body

# ------------------------------------------------------------- normalization
AR_DIAC = re.compile(r"[ً-ْـ]")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
LETTERS = re.compile(r"[ء-يA-Za-z]")

def norm_ar(s):
    s = AR_DIAC.sub("", s or "")
    s = re.sub(r"[أإآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه") \
         .replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip().lower()

def slug(name):
    return hashlib.sha1(norm_ar(name).encode()).hexdigest()[:12]

def real_name(t):
    """True for a topic label, false for an alternate-source marker (2, >, *, cx9)."""
    s = (t or "").strip(" >*,،()")
    return len(s) >= 4 and len(LETTERS.findall(s)) >= 3

# ------------------------------------------------------------ classification
KIND_RULES = [("t.me", "telegram"), ("youtu", "youtube"), ("docs.google.com", "google-doc"),
              ("drive.google", "gdrive"), ("web.archive.org", "archive"), ("goo.gl", "shortlink"),
              ("ibb.co", "image"), ("maps.app", "maps"), ("nhtsa", "nhtsa"),
              ("instagram", "instagram"), ("twitter", "twitter"), ("x.com", "twitter")]

def classify(url):
    if not url or url.startswith("#"):
        return "internal-anchor"
    if "#bookmark=" in url or "#heading=" in url:
        return "source-doc"          # a specific spot inside the community's own document
    for key, name in KIND_RULES:
        if key in url:
            return name
    return "web"

GDOC_ID = re.compile(r"docs\.google\.com/document/d/([A-Za-z0-9_-]{20,})")
def gdoc_id(url):
    m = GDOC_ID.search(url or "")
    return m.group(1) if m else None


def normalize_url(url):
    """Repair links the source doc mangled.

    Editing in Google Docs sometimes swallows the text after a URL into the href
    ("…/edit%20ملاحظات"), which 404s even though the document is fine. Rebuild any
    Google Docs link from its id, and trim stray whitespace elsewhere."""
    if not url or url.startswith("#"):
        return url
    gid = gdoc_id(url)
    if gid:
        return f"https://docs.google.com/document/d/{gid}/edit"
    return url.strip()

# -------------------------------------------------------------------- facets
MODELS = [
    ("mazda3", r"مازدا\s*٣|مازدا\s*3|\bم\s*3\b|\bم٣\b|mazda\s*3|\bm3\b"),
    ("mazda6", r"مازدا\s*٦|مازدا\s*6|\bم\s*6\b|\bم٦\b|mazda\s*6|\bm6\b"),
    ("mazda2", r"مازدا\s*2|\bم\s*2\b|mazda\s*2"),
    ("cx3", r"\bcx\s*-?\s*3\b"), ("cx5", r"\bcx\s*-?\s*5\b"), ("cx9", r"\bcx\s*-?\s*9\b"),
    ("cx30", r"\bcx\s*-?\s*30\b"), ("cx50", r"\bcx\s*-?\s*50\b"), ("cx60", r"\bcx\s*-?\s*60\b"),
    ("cx70", r"\bcx\s*-?\s*70\b"), ("cx90", r"\bcx\s*-?\s*90\b"),
    ("mx5", r"\bmx\s*-?\s*5\b"), ("mpv", r"\bmpv\b"),
]
ENGINES = [("1.6", r"\b1[.,]6\b"), ("2.0", r"\b2[.,]0\b"), ("2.5", r"\b2[.,]5\b"),
           ("3.5", r"\b3[.,]5\b"), ("3.7", r"\b3[.,]7\b")]
TRIMS = [("full", r"\bفل\b|فل\s*اوبشن"), ("standard", r"ستاندر"), ("signature", r"سقنتشر|سيقنتشر")]
YEARS = re.compile(r"\b(19[7-9]\d|20[0-4]\d)\s*[-–—]\s*(19[7-9]\d|20[0-4]\d)\b")
YEAR1 = re.compile(r"\b(19[7-9]\d|20[0-4]\d)\b")

def facets(text):
    t = (text or "").lower()
    f = {"models": [], "engines": [], "trims": [], "turbo": None, "years": []}
    for name, pat in MODELS:
        if re.search(pat, t, re.I): f["models"].append(name)
    for name, pat in ENGINES:
        if re.search(pat, t): f["engines"].append(name)
    for name, pat in TRIMS:
        if re.search(pat, t): f["trims"].append(name)
    if re.search(r"بدون\s*(تيربو|توربو)", t): f["turbo"] = "na"
    elif re.search(r"تيربو|توربو", t): f["turbo"] = "turbo"
    spans = [[int(a), int(b)] for a, b in YEARS.findall(t)]
    if not spans:
        spans = [[int(y), int(y)] for y in YEAR1.findall(t)]
    seen, uniq = set(), []
    for y in spans:
        k = tuple(y)
        if k not in seen and 1970 <= y[0] <= 2049 and y[1] >= y[0]:
            seen.add(k); uniq.append(y)
    f["years"] = uniq[:3]
    return f
