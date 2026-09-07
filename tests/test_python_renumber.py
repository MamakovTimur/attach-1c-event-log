from __future__ import annotations

import unittest

from tools import attach_event_log as engine


SAMPLE = (
    "{20260819070002,N,\r\n"
    "{0,0},1,1,1,144608,1,I,\"line\nwith \"\"quotes\"\"\",0,\r\n"
    "{0,7},\"\",1,1,0,1,0,\r\n"
    "{0}\r\n"
    "},\r\n"
)


def reference_maps() -> dict[int, dict[int, int]]:
    return {
        1: {1: 11},
        2: {1: 22},
        3: {1: 33},
        4: {1: 44},
        5: {0: 55, 7: 77},
        6: {1: 66},
        7: {1: 77},
        8: {0: 88},
    }


class PythonRenumberTests(unittest.TestCase):
    def test_direct_renumber_preserves_layout_and_payload(self) -> None:
        result = engine.renumber_record_preserving_breaks(SAMPLE, reference_maps())
        self.assertEqual(result.count("\r\n"), SAMPLE.count("\r\n"))
        self.assertEqual(result.count("\n") - result.count("\r\n"), 1)
        self.assertIn('"line\nwith ""quotes"""', result)
        self.assertIn("144608", result)  # session number is not a dictionary ref
        self.assertIn("{0,7}", result)
        self.assertIn('"line\nwith ""quotes""",55,', result)
        self.assertIn(",11,22,33,144608,44,", result.replace("\r\n", ""))
        self.assertIn(',66,77,88,1,0,', result.replace("\r\n", ""))

    def test_no_mapping_returns_byte_equivalent_text(self) -> None:
        maps = {obj_type: {} for obj_type in range(1, 9)}
        self.assertEqual(
            engine.renumber_record_preserving_breaks(SAMPLE, maps),
            SAMPLE,
        )

    def test_token_spans_ignore_commas_in_strings_and_nested_values(self) -> None:
        spans = engine.top_level_token_spans('{1,"a,b",{2,3},4}')
        values = ['{1,"a,b",{2,3},4}'[start:end] for start, end in spans]
        self.assertEqual(values, ["1", '"a,b"', "{2,3}", "4"])


if __name__ == "__main__":
    unittest.main()
