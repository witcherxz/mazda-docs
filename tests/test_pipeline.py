"""Unit tests for the extraction rules. Run: python3 -m unittest discover -s tests"""
import os, sys, unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import common, hub, render, satellites, store

W = hub.W
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')


def para(xml):
    return ET.fromstring(f"<w:p {NS}>{xml}</w:p>")


class Normalization(unittest.TestCase):
    def test_alef_and_taa_forms_collapse(self):
        self.assertEqual(common.norm_ar("إطارٌ"), common.norm_ar("اطار"))
        self.assertEqual(common.norm_ar("سيارة"), common.norm_ar("سياره"))
        self.assertEqual(common.norm_ar("  مِفتاح  "), "مفتاح")

    def test_slug_is_stable_across_spelling_variants(self):
        self.assertEqual(common.slug("الزجاج الجانبي"), common.slug("الزجاج الجانبى"))

    def test_real_name_rejects_source_markers(self):
        for marker in ["2", ">", "*", " > 3 ", "cx9"]:
            self.assertFalse(common.real_name(marker), marker)
        for name in ["بواجي", "الزجاج الجانبي", "MAF Sensor"]:
            self.assertTrue(common.real_name(name), name)

    def test_classify_link_kinds(self):
        cases = {"https://t.me/Mazda3Group/1": "telegram",
                 "https://youtu.be/x": "youtube",
                 "https://docs.google.com/document/d/abc/edit": "google-doc",
                 "https://example.com/a": "web",
                 "#kix.abc": "internal-anchor"}
        for url, kind in cases.items():
            self.assertEqual(common.classify(url), kind, url)

    def test_facets_read_model_year_engine(self):
        f = common.facets("مازدا 6 2015-2019 محرك 2.5 توربو")
        self.assertIn("mazda6", f["models"])
        self.assertIn("2.5", f["engines"])
        self.assertEqual(f["turbo"], "turbo")
        self.assertEqual(f["years"], [[2015, 2019]])

    def test_mangled_google_doc_url_is_rebuilt_from_its_id(self):
        broken = ("https://docs.google.com/document/d/1F4SRmTDX97YmFXg5YWR_7PDk8Z4tUIkDNEk"
                  "gHEafPOQ/edit%20%D9%85%D9%84%D8%A7")
        self.assertEqual(common.normalize_url(broken),
                         "https://docs.google.com/document/d/"
                         "1F4SRmTDX97YmFXg5YWR_7PDk8Z4tUIkDNEkgHEafPOQ/edit")

    def test_normalize_leaves_other_links_and_anchors_alone(self):
        self.assertEqual(common.normalize_url("#kix.abc"), "#kix.abc")
        self.assertEqual(common.normalize_url(" https://t.me/x/1 "), "https://t.me/x/1")

    def test_facets_detect_naturally_aspirated(self):
        self.assertEqual(common.facets("محرك 2.0 بدون توربو")["turbo"], "na")


class HyperlinkMerging(unittest.TestCase):
    """Google Docs splits one anchor across elements whenever formatting changes."""

    def test_split_anchor_runs_merge_into_one_link(self):
        rels = {"rId1": "https://example.com/a"}
        p = para('<w:hyperlink r:id="rId1"><w:r><w:t>انوار </w:t></w:r></w:hyperlink>'
                 '<w:hyperlink r:id="rId1"><w:r><w:t>م3 </w:t></w:r></w:hyperlink>'
                 '<w:hyperlink r:id="rId1"><w:r><w:t>كاملة</w:t></w:r></w:hyperlink>')
        toks = hub.tokens(p, rels)
        self.assertEqual(len(toks), 1)
        self.assertEqual(toks[0][1], "انوار م3 كاملة")

    def test_different_targets_stay_separate(self):
        rels = {"rId1": "https://a.example", "rId2": "https://b.example"}
        p = para('<w:hyperlink r:id="rId1"><w:r><w:t>اسم</w:t></w:r></w:hyperlink>'
                 '<w:hyperlink r:id="rId2"><w:r><w:t>2</w:t></w:r></w:hyperlink>')
        self.assertEqual(len(hub.tokens(p, rels)), 2)

    def test_internal_anchor_becomes_hash_target(self):
        p = para('<w:hyperlink w:anchor="kix.abc"><w:r><w:t>جدول</w:t></w:r></w:hyperlink>')
        self.assertEqual(hub.tokens(p, {})[0][2], "#kix.abc")


class Intervals(unittest.TestCase):
    def test_kilometre_forms(self):
        cases = {"الصيانة الاولى لأول 1,000 كيلو او 6 اشهر": (1000, 6),
                 "كل 3500 كيلو او شهر": (3500, 1),
                 "تتكرر كل 16 الف كيلو او سنة": (16000, 12),
                 "تتكرر كل40 الف": (40000, None),
                 "تتكرر كل ٦٠ الف": (60000, None),
                 "تتكرر كل 240 الف كيلو": (240000, None)}
        for label, expected in cases.items():
            self.assertEqual(hub.parse_interval(label), expected, label)

    def test_millilitre_row_is_not_an_interval(self):
        km, _ = hub.parse_interval("زيت الفرامل تغيير 1000 ملي:")
        self.assertIsNone(km)


class Satellites(unittest.TestCase):
    HTML = """<html><head><title>قطع الغيار</title></head><body>
      <h1 id="s1">مصادر الشراء</h1>
      <p><a href="https://www.google.com/url?q=https://t.me/x/1&amp;sa=D">ارقام القطع</a>
         <a href="https://www.google.com/url?q=https://t.me/x/2&amp;sa=D">2</a>
         <a href="https://www.google.com/url?q=https://t.me/x/3&amp;sa=D">ب350 ريال</a></p>
    </body></html>"""

    def setUp(self):
        self.doc = satellites.parse(self.HTML, "docid123")
        self.by_name = {t["name"]: t for t in self.doc["topics"]}

    def test_title_and_sections(self):
        self.assertEqual(self.doc["title"], "قطع الغيار")
        self.assertEqual(self.doc["sections"][0]["title"], "مصادر الشراء")

    def test_heading_becomes_a_topic_holding_the_links_under_it(self):
        section = self.by_name["مصادر الشراء"]
        self.assertEqual(len(section["sources"]), 3)

    def test_strongly_named_link_also_gets_its_own_topic(self):
        self.assertIn("ارقام القطع", self.by_name)
        self.assertEqual(len(self.by_name["ارقام القطع"]["sources"]), 1)

    def test_price_and_marker_labels_do_not_become_topics(self):
        for junk in ["2", "ب350 ريال"]:
            self.assertNotIn(junk, self.by_name)

    def test_strong_name_rules(self):
        for good in ["ارقام القطع", "تنظيف الرديتر من الخارج"]:
            self.assertTrue(satellites.strong_name(good), good)
        for bad in ["2", "ب350 ريال", "بتاريخ 1/2023", "زيت", "42"]:
            self.assertFalse(satellites.strong_name(bad), bad)

    def test_google_redirect_is_unwrapped(self):
        self.assertEqual(self.by_name["ارقام القطع"]["sources"][0]["url"], "https://t.me/x/1")


class Store(unittest.TestCase):
    def setUp(self):
        self.db = store.connect(":memory:")

    def topic(self, tid, name, n=1):
        return {"id": tid, "name": name, "letter": "أ", "note": "", "norm": name,
                "f": {}, "n": n, "doc": "hub",
                "sources": [{"label": name, "url": f"https://e.com/{tid}/{i}", "kind": "web"}
                            for i in range(n)]}

    def test_first_run_does_not_log_every_topic_as_new(self):
        sync = store.Sync(self.db)
        sync.topics([self.topic("a", "بواجي"), self.topic("b", "زيت")])
        self.assertEqual(sync.changes, [])

    def test_second_run_reports_add_remove_and_source_count(self):
        first = store.Sync(self.db)
        first.topics([self.topic("a", "بواجي"), self.topic("b", "زيت")])
        first.commit({"sha": "x"})

        second = store.Sync(self.db)
        second.topics([self.topic("a", "بواجي", n=3), self.topic("c", "فلتر")])
        fields = {(c["entity"], c["id"], c["field"]) for c in second.changes}
        self.assertIn(("topic", "a", "sources"), fields)
        self.assertIn(("topic", "b", "removed"), fields)
        self.assertIn(("topic", "c", "added"), fields)

    def test_removed_topic_is_marked_gone_not_deleted(self):
        first = store.Sync(self.db)
        first.topics([self.topic("a", "بواجي")])
        first.commit({"sha": "x"})
        second = store.Sync(self.db)
        second.topics([])
        second.commit({"sha": "y"})
        row = self.db.execute("SELECT status FROM topic WHERE id='a'").fetchone()
        self.assertEqual(row["status"], "gone")


class Render(unittest.TestCase):
    def test_compact_drops_derivable_fields(self):
        data = {"topics": [{"name": "بواجي", "norm": "بواجي", "snorm": "x" * 400,
                            "f": {"models": [], "engines": ["2.0"]}, "n": 1,
                            "sources": [{"label": "a", "url": "https://e.com", "kind": "web"}]}],
                "articles": [{"norm": "y" * 9000,
                              "blocks": [{"t": "نص", "runs": [{"t": "نص"},
                                                              {"t": "رابط", "u": "u", "k": "web"}]}]}],
                "schedule": [{"replace": [{"t": "بند", "runs": [{"t": "بند", "u": "u", "k": "web"}]}],
                              "inspect": []}],
                "docs": [{"sections": [{"title": "s"}] * 40, "f": {"models": [], "years": [[2019, 2019]]}}]}
        small = render.compact(data)
        t = small["topics"][0]
        self.assertNotIn("norm", t)
        self.assertNotIn("kind", t["sources"][0])
        self.assertEqual(len(t["snorm"]), 160)
        self.assertEqual(t["f"], {"engines": ["2.0"]})            # empty facets dropped
        self.assertEqual(len(small["articles"][0]["norm"]), 3000)
        self.assertEqual(len(small["docs"][0]["sections"]), 25)
        block = small["articles"][0]["blocks"][0]
        self.assertNotIn("t", block)                      # rebuilt from the runs in the browser
        self.assertNotIn("k", block["runs"][1])           # kind derived from the URL
        self.assertEqual(block["runs"][1]["u"], "u")      # the link itself survives
        self.assertNotIn("k", small["schedule"][0]["replace"][0]["runs"][0])


SNAPSHOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "دليل صيانة مازدا.docx")


@unittest.skipUnless(os.path.exists(SNAPSHOT), "local snapshot not present")
class RealDocument(unittest.TestCase):
    """Guardrails: catch the day a parse rule silently stops finding things."""

    @classmethod
    def setUpClass(cls):
        with open(SNAPSHOT, "rb") as fh:
            cls.parsed = hub.parse(fh.read())

    def test_topic_and_link_volume(self):
        self.assertGreater(len(self.parsed["topics"]), 800)
        self.assertGreater(len(self.parsed["links"]), 6000)

    def test_every_topic_has_at_least_one_source(self):
        self.assertTrue(all(t["n"] >= 1 for t in self.parsed["topics"]))

    def test_schedule_is_a_full_matrix(self):
        sched = self.parsed["schedule"]
        self.assertEqual(len(sched), 14)
        self.assertGreaterEqual(sum(1 for s in sched if s["km"]), 10)

    def test_prose_keeps_links_inline_instead_of_duplicating_them(self):
        item = next(i for iv in self.parsed["schedule"] for i in iv["replace"]
                    if len(i["runs"]) > 3)
        linked = [r for r in item["runs"] if "u" in r]
        self.assertTrue(linked, "a prose item should carry inline links")
        # each linked phrase appears once, inside its run — not again as loose text
        for r in linked:
            plain = "".join(x["t"] for x in item["runs"] if "u" not in x)
            self.assertNotIn(r["t"], plain)

    def test_articles_and_anchor_resolution(self):
        self.assertGreater(len(self.parsed["articles"]), 10)
        self.assertGreater(len(self.parsed["anchors"]), 20)

    def test_no_marker_leaked_into_a_topic_name(self):
        bad = [t["name"] for t in self.parsed["topics"] if not common.real_name(t["name"])]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
