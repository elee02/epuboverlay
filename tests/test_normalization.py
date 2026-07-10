import unittest
from epuboverlay.normalization import (
    harmonize_punctuation,
    expand_numerals,
    resolve_contractions,
    resolve_heteronyms,
    apply_custom_lexicon,
    normalize_text,
)

class NormalizationTests(unittest.TestCase):
    def test_harmonize_punctuation(self) -> None:
        text = "“Hello,” she said—with standard… smart quotes."
        expected = '"Hello," she said-with standard... smart quotes.'
        self.assertEqual(harmonize_punctuation(text), expected)

    def test_expand_numerals(self) -> None:
        # Test integer expansion (can be "two thousand and twenty-six" or "two thousand twenty-six")
        val = expand_numerals("In 2026, we will succeed.")
        self.assertTrue("twenty-six" in val)
        self.assertTrue("two thousand" in val)
        # Test decimal expansion
        self.assertIn("point five", expand_numerals("We have 1.5 liters of water."))
        # Test comma-separated integer expansion
        self.assertIn("thousand", expand_numerals("Price is 1,000 dollars."))

    def test_resolve_contractions(self) -> None:
        self.assertEqual(resolve_contractions("won't"), "will not")
        self.assertEqual(resolve_contractions("Won't"), "Will not")
        self.assertEqual(resolve_contractions("WON'T"), "WILL NOT")
        self.assertEqual(resolve_contractions("I'm happy because it's working."), "I am happy because it is working.")

    def test_resolve_heteronyms(self) -> None:
        # Test "read" heteronym rules
        self.assertEqual(resolve_heteronyms("I read yesterday."), "I red yesterday.")
        self.assertEqual(resolve_heteronyms("We had read the book."), "We had red the book.")
        self.assertEqual(resolve_heteronyms("to read"), "to reed")
        
        # Test "wind" rules
        self.assertEqual(resolve_heteronyms("wind the clock"), "wynd the clock")
        self.assertEqual(resolve_heteronyms("the strong wind"), "the strong wind")

        # Test "live" rules
        self.assertEqual(resolve_heteronyms("live music"), "lyve music")

    def test_apply_custom_lexicon(self) -> None:
        lexicon = [
            {"word": "LLaMA", "replacement": "lama"},
            {"word": "GUI", "replacement": "gooey"}
        ]
        text = "The LLaMA model and its GUI."
        expected = "The lama model and its gooey."
        self.assertEqual(apply_custom_lexicon(text, lexicon), expected)

    def test_normalize_text_full_chain(self) -> None:
        settings = {
            "expand_numerals": True,
            "resolve_contractions": True,
            "resolve_heteronyms": True,
            "harmonize_punctuation": True,
            "custom_lexicon": [
                {"word": "LLaMA", "replacement": "lama"}
            ]
        }
        text = "“We won't use LLaMA in 2026,” I read yesterday."
        # Harmonize quote: "We
        # Contraction: won't -> will not
        # Lexicon: LLaMA -> lama
        # Numeral: 2026 -> two thousand [and] twenty-six
        # Heteronym: read yesterday -> red yesterday
        val = normalize_text(text, settings)
        self.assertTrue(val.startswith('"We will not use lama in'))
        self.assertTrue(val.endswith('twenty-six," I red yesterday.'))

if __name__ == "__main__":
    unittest.main()
