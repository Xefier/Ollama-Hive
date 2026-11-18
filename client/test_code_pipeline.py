#!/usr/bin/env python3
"""Tests of the code pipeline's own logic: answer parsing, splicing, choosing a try and the C# scanner. No rig, no
Unity project. Run: python client/test_code_pipeline.py"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import code_index
import code_pipeline as pipeline

EXCERPTS = {"kind": "excerpts", "path": "Assets/A.cs", "name": "A.cs", "segments": 2}
WHOLE = {"kind": "whole", "path": "Assets/B.cs", "name": "B.cs"}

SOURCE = '''using UnityEngine;
namespace Game
{
    /// <summary>A lamp.</summary>
    public class Lamp : MonoBehaviour, ISwitch
    {
        [SerializeField] float baseRange = 3f; // metres
        public const string DieingEvent = "Dieing";
        public float Range => baseRange;
        public bool IsOn { get; private set; }
        public event System.Action<bool> Switched;

        void Awake()
        {
            if (IsOn) { SetOn(true); }
        }

        public void SetOn(bool on)
        {
            IsOn = on;
            Switched?.Invoke(on);
        }

        public void SetOn(bool on, bool quiet) { IsOn = on; }

        enum Mode { Off, On }
    }
}
'''


class Answers(unittest.TestCase):
    def test_excerpts_in_one_block(self):
        values, problem = pipeline.normalise("```csharp\n// FILE: A.cs\none\n// ...\ntwo\n```", [EXCERPTS])
        self.assertIsNone(problem)
        self.assertEqual(values, [["one", "two"]])

    def test_thinking_leak_and_answer_given_twice(self):
        answer = "```csharp\n// FILE: A.cs\nold\n// ...\nold\n```\n</think>\n```csharp\n// FILE: A.cs\none\n// ...\ntwo\n```"
        self.assertEqual(pipeline.normalise(answer, [EXCERPTS])[0], [["one", "two"]])

    def test_one_file_split_over_two_blocks(self):
        answer = "```csharp\n// FILE: A.cs\none\n```\n```csharp\n// FILE: A.cs\ntwo\n```"
        self.assertEqual(pipeline.normalise(answer, [EXCERPTS])[0], [["one", "two"]])

    def test_trailing_snippet_without_file_line_is_ignored(self):
        answer = "```csharp\n// FILE: B.cs\nclass B {}\n```\nKey change:\n```csharp\nx = 1;\n```"
        self.assertEqual(pipeline.normalise(answer, [WHOLE])[0], ["class B {}\n"])

    def test_blocks_without_file_lines_go_in_order(self):
        answer = "```csharp\none\n// ...\ntwo\n```\n```cs\nclass B {}\n```"
        self.assertEqual(pipeline.normalise(answer, [EXCERPTS, WHOLE])[0], [["one", "two"], "class B {}\n"])

    def test_wrong_number_of_excerpts_is_a_format_error(self):
        values, problem = pipeline.normalise("```csharp\n// FILE: A.cs\none\n```", [EXCERPTS])
        self.assertIsNone(values)
        self.assertTrue(problem.startswith("format:"))

    def test_a_file_not_answered_is_unchanged(self):
        given = [dict(EXCERPTS, shown=["a", "b"]), dict(WHOLE, shown="class B {}\n")]
        values, problem = pipeline.normalise("```csharp\n// FILE: B.cs\nclass B { int x; }\n```", given)
        self.assertIsNone(problem)
        self.assertEqual(values, [["a", "b"], "class B { int x; }\n"])
        # but a new file has nothing to fall back on
        new = {"kind": "new", "path": "Assets/C.cs", "name": "C.cs"}
        self.assertTrue(pipeline.normalise("```csharp\n// FILE: B.cs\nclass B {}\n```", [given[1], new])[1].startswith("format:"))

    def test_no_code(self):
        self.assertTrue(pipeline.normalise("Run this: pip install x", [WHOLE])[1].startswith("format:"))

    def test_canonical_round_trip(self):
        values = [["one", "two"], "class B {}\n"]
        again, problem = pipeline.normalise(pipeline.canonical(values, [EXCERPTS, WHOLE]), [EXCERPTS, WHOLE])
        self.assertIsNone(problem)
        self.assertEqual(again, values)

    def test_needs(self):
        answer = "NEED: Fusion.NetworkObject\n- NEED: `Lamp.SetOn`\nNEED: how a death is announced.\nNEED: nothing"
        self.assertEqual(pipeline.parse_needs(answer), ["Fusion.NetworkObject", "Lamp.SetOn", "how a death is announced"])


class Splicing(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(pipeline.parse_ranges("5-6, 2", 10), [(2, 2), (5, 6)])
        for bad in ("0-3", "4-12", "3-5,5-6", "a-b"):
            self.assertRaises(pipeline.PipelineError, pipeline.parse_ranges, bad, 10)

    def test_splice_replaces_each_range(self):
        part = dict(EXCERPTS, text="1\n2\n3\n4\n5\n6", ranges=[(2, 2), (5, 6)])
        self.assertEqual(pipeline.splice([["two\ntwo-and-a-half", "five"]], [part]),
                         {"Assets/A.cs": "1\ntwo\ntwo-and-a-half\n3\n4\nfive"})


class Choosing(unittest.TestCase):
    @staticmethod
    def result(at, status, errors=0, retried=False, values=True):
        return {"at": at, "status": status, "errors": ["e"] * errors, "first": {} if retried else None,
                "values": [] if values else None, "answer": "a\nb" if at else "a\nc"}

    def test_first_compiling_without_retry_wins(self):
        results = [self.result(0, "compiles", retried=True), self.result(1, "errors", 2), self.result(2, "compiles")]
        self.assertEqual(pipeline.choose(results), 2)

    def test_fewest_errors_when_none_compiles(self):
        results = [self.result(0, "errors", 3), self.result(1, "errors", 1), self.result(2, "format", values=False)]
        self.assertEqual(pipeline.choose(results), 1)

    def test_no_code_at_all(self):
        self.assertIsNone(pipeline.choose([self.result(0, "format", values=False)]))


class Scanner(unittest.TestCase):
    def test_signatures(self):
        types = code_index.signatures(SOURCE)
        self.assertEqual(sorted(types), ["Lamp", "Mode"])
        self.assertEqual(types["Lamp"]["head"], "public class Lamp : MonoBehaviour, ISwitch")
        self.assertEqual(types["Lamp"]["ns"], "Game")
        self.assertEqual(code_index.signatures("namespace A.B;\nclass C { int x; }")["C"]["ns"], "A.B")
        names = [code_index.member_name(member) for member in types["Lamp"]["members"]]
        self.assertEqual(names, ["baseRange", "DieingEvent", "Range", "IsOn", "Switched", "Awake", "SetOn", "SetOn"])
        self.assertEqual(types["Mode"]["members"], ["Off, On"])
        self.assertEqual(code_index.bases_of(types["Lamp"]["head"]), ["MonoBehaviour", "ISwitch"])
        self.assertEqual(code_index.usings(SOURCE), ["UnityEngine", "Game"])

    def test_member_source(self):
        both = code_index.member_source(SOURCE, "Lamp", "SetOn")
        self.assertIn("Switched?.Invoke(on);", both)
        self.assertIn("public void SetOn(bool on, bool quiet) { IsOn = on; }", both)
        self.assertNotIn("Awake", both)
        self.assertEqual(code_index.member_source(SOURCE, "Lamp", "Range").strip(), "public float Range => baseRange;")
        self.assertEqual(code_index.member_source(SOURCE, "Lamp", "baseRange").strip(), "[SerializeField] float baseRange = 3f;")
        self.assertIsNone(code_index.member_source(SOURCE, "Lamp", "Missing"))

    def test_names_in_code_and_prose(self):
        code = "Lamp lamp = new Lamp(); lamp.SetOn(true); Physics.Raycast(a, b); // Never this\nvar x = (Mode)1;"
        self.assertEqual(sorted(pipeline.type_names(code)), ["Lamp", "Mode", "Physics"])
        self.assertEqual(pipeline.prose_names("When the Light_Base wakes, `Saves.Current` and EntityRespawnReset matter."),
                         ["Saves", "Current", "Light_Base", "EntityRespawnReset"])

    def test_description_words(self):
        self.assertEqual(code_index.query_words("how the player's death is announced"), ["player", "death", "announc"])
        self.assertEqual(code_index.words_of("OnPlayerDeaths_HUD"), {"on", "player", "death", "hud"})


if __name__ == "__main__":
    unittest.main()
