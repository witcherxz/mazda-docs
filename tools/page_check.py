"""Check free-form pages against their inputs: format, lengths, link IDs, numbers and codes.

usage: page_check.py CRUNCH_DIR ID [ID ...]
A number or Latin code on the page that appears nowhere in the inputs is an error,
because the prompt forbids facts from outside them. It does not check meaning.
"""
import pathlib
import re
import sys

from solutions import numbers

ALLOWED_NUMS = {"1", "2", "3"}  # list counters and section numbers the renderer may add


def inputs_text(folder):
    parts = [folder / "article.txt", folder / "links.txt"] + sorted((folder / "docs").glob("*.txt"))
    return "\n".join(p.read_text(encoding="utf8") for p in parts if p.exists())


def check(folder):
    errs, warns = [], []
    raw = (folder / "page.md").read_text(encoding="utf8")
    m = re.match(r"---\ntitle: ([^\n]*)\nsummary: ([^\n]*)\n---\n(.*)", raw, re.S)
    if not m:
        return ["front matter missing or malformed"], warns, {}
    title, summary, rest = m.groups()
    body, sep, tail = rest.rpartition("---\nunclear:")
    if not sep:
        errs.append("unclear section missing")
        body = rest
    links_n = len((folder / "links.txt").read_text(encoding="utf8").splitlines())
    if len(title) > 60:
        errs.append(f"title {len(title)} chars > 60")
    if len(summary) > 160:
        errs.append(f"summary {len(summary)} chars > 160")
    if re.search(r"^# ", body, re.M):
        errs.append("uses a # heading")
    cited = {int(x) for x in re.findall(r"\]\(L(\d+)\)", body)}
    bad = sorted(n for n in cited if not 1 <= n <= links_n)
    if bad:
        errs.append(f"unknown link IDs {bad}")
    om = re.search(r"^omit:(.*)$", tail, re.M)
    omit = {int(x) for x in re.findall(r"\d+", om.group(1))} if om else set()
    if omit & cited:
        warns.append(f"omitted links also cited {sorted(omit & cited)}")
    src = inputs_text(folder)
    page = title + "\n" + summary + "\n" + re.sub(r"\]\(L\d+\)", "]", body)
    new_nums = sorted(numbers(page) - numbers(src) - ALLOWED_NUMS, key=lambda x: (len(x), x))
    if new_nums:
        errs.append(f"numbers not in inputs {new_nums}")
    squash = re.sub(r"[\s-]", "", src).lower()
    codes = {w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", page)}
    new_codes = sorted(w for w in codes if re.sub(r"-", "", w).lower() not in squash)
    if new_codes:
        warns.append(f"Latin words not in inputs {new_codes[:12]}")
    unclear = [x for x in tail.splitlines() if x.startswith("- ")]
    if any(re.search(r"[A-Za-z]{4,} [A-Za-z]{4,} [A-Za-z]{4,}", x) for x in unclear):
        warns.append("unclear notes look English")
    words = len(re.findall(r"\S+", body))
    parts_words = sum(len(re.findall(r"\S+", blk)) for blk in
                      re.findall(r"\*\*القطع[^\n]*\n(?:- [^\n]*\n?)*", body))
    stats = {"words": words, "words_outside_parts": words - parts_words, "cited": len(cited),
             "links": links_n, "omit": len(omit), "unclear": len(unclear)}
    return errs, warns, stats


def main():
    crunch = pathlib.Path(sys.argv[1])
    failed = 0
    for aid in sys.argv[2:]:
        folder = crunch / aid
        if not (folder / "page.md").exists():
            print(f"{aid}: MISSING page.md"); failed += 1; continue
        errs, warns, st = check(folder)
        failed += bool(errs)
        print(f"{aid}: {'FAIL' if errs else 'ok'} {st}")
        for e in errs:
            print("   error:", e)
        for w in warns:
            print("   warn:", w)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
