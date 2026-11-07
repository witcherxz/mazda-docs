"""Tests for the draft checker: it is what stands between a model's output and a reader."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import solutions

ARTICLE = {"id": "abc", "title": "الريموت", "blocks": [
    {"runs": [{"t": "بطارية CR2032 بسعر 10 ريال "}, {"t": "فيديو", "u": "https://youtu.be/x"},
              {"t": " > "}, {"t": "2", "u": "https://t.me/group/1"}]},
    {"runs": [{"t": "   "}]},
]}
SOURCE = solutions.input_for(ARTICLE, set(), {"abc": ARTICLE})


def good():
    return {"article": "abc", "title": "بطارية الريموت في مازدا", "summary": "البطارية CR2032 بسعر 10 ريال.",
            "cases": [{"h": "البطارية", "items": [{"t": "رقم البطارية CR2032.", "links": [1, 2]}]}],
            "parts": [], "unplaced": [], "unclear": []}


class Inputs(unittest.TestCase):
    def test_links_become_numbered_markers(self):
        self.assertIn("[L1:فيديو]", SOURCE)
        self.assertIn("[L2:2]", SOURCE)
        self.assertIn("LINK_COUNT: 2", SOURCE)

    def test_links_land_past_the_documents_index(self):
        """Documents open with an A-Z index of the same names; the section itself comes later."""
        blocks = [{"t": "كراسي المكينة", "ids": []}, {"t": "ل", "ids": []},
                  {"t": "كراسي المكينة", "ids": []}, {"t": "الأعراض : رجة مع البنزين", "ids": []}]
        self.assertEqual(solutions.locate("كراسي المكينة", "https://d/edit", blocks)[1], 2)

    def test_an_exact_anchor_beats_a_label_match(self):
        blocks = [{"t": "الكفرات", "ids": []}, {"t": "نص آخر", "ids": ["h.abc"]}]
        self.assertEqual(solutions.locate("الكفرات", "https://d/edit#heading=h.abc", blocks)[1], 1)


class Checker(unittest.TestCase):
    def test_a_faithful_draft_passes(self):
        self.assertEqual(solutions.check(good(), SOURCE)[0], [])

    def test_a_number_not_in_the_source_fails(self):
        d = good()
        d["summary"] = "البطارية بسعر 75 ريال."
        self.assertTrue(any("75" in e for e in solutions.check(d, SOURCE)[0]))

    def test_a_number_inside_a_price_is_checked_too(self):
        d = good()
        d["parts"] = [{"part": "بطارية", "prices": [{"value": "99"}]}]
        self.assertTrue(any("99" in e for e in solutions.check(d, SOURCE)[0]))

    def test_a_dropped_link_fails(self):
        d = good()
        d["cases"][0]["items"][0]["links"] = [1]
        self.assertTrue(any("dropped" in e for e in solutions.check(d, SOURCE)[0]))

    def test_an_unknown_link_fails(self):
        d = good()
        d["cases"][0]["items"][0]["links"] = [1, 2, 99]
        self.assertTrue(any("unknown" in e for e in solutions.check(d, SOURCE)[0]))

    def test_a_latin_word_not_in_the_source_fails(self):
        d = good()
        d["summary"] = "البطارية CR2025."
        self.assertTrue(any("cr2025" in e for e in solutions.check(d, SOURCE)[0]))

    def test_part_numbers_split_by_a_space_in_the_source_still_match(self):
        source = SOURCE.replace("CR2032", "DY 1155")
        d = good()
        d["summary"] = d["cases"][0]["items"][0]["t"] = "الرقم DY1155 بسعر 10 ريال."
        self.assertFalse(any("Latin" in e for e in solutions.check(d, source)[0]))

    def test_an_overlong_title_fails(self):
        d = good()
        d["title"] = "ب" * 61
        self.assertTrue(any("title" in e for e in solutions.check(d, SOURCE)[0]))

    def test_source_changes_change_the_hash(self):
        self.assertNotEqual(solutions.input_hash(SOURCE), solutions.input_hash(SOURCE + "x"))


if __name__ == "__main__":
    unittest.main()
