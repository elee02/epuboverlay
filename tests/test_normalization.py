import unittest
from epuboverlay.normalization import (
    harmonize_punctuation,
    expand_numerals,
    resolve_contractions,
    resolve_heteronyms,
    apply_custom_lexicon,
    normalize_text,
    detect_text_language,
    NARRATION_SCENARIOS,
)
from epuboverlay.pipeline import split_into_sentences
from epuboverlay.synthesizers import (
    AVAILABLE_SYNTHESIZERS,
    POCKET_LANGUAGES,
    QWEN3_LANGUAGES,
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

    def test_detect_text_language_scripts_and_hints(self) -> None:
        self.assertEqual(detect_text_language("Привет, мир! Это тест."), "ru")
        self.assertEqual(detect_text_language("안녕하세요, 반갑습니다."), "ko")
        self.assertEqual(detect_text_language("こんにちは、世界。"), "ja")
        self.assertEqual(detect_text_language("你好，世界。"), "zh")
        self.assertEqual(detect_text_language("مرحبا بالعالم"), "ar")
        self.assertEqual(detect_text_language("Guten Tag", hint="german_24l"), "de")
        self.assertEqual(detect_text_language("Hola mundo", hint="Spanish"), "es")

    def test_multilingual_normalization_never_injects_english_into_non_english(self) -> None:
        settings = {
            "expand_numerals": True,
            "resolve_contractions": True,
            "resolve_heteronyms": True,
            "harmonize_punctuation": True,
            "custom_lexicon": [],
        }
        ru_text = "В 2026 году вышло 5 книг."
        ru_norm = normalize_text(ru_text, settings)
        # Should never inject English words like "two thousand" into Russian text
        self.assertNotIn("thousand", ru_norm)
        self.assertNotIn("five", ru_norm)

        ko_text = "2026년에 3권의 책을 읽었습니다."
        ko_norm = normalize_text(ko_text, settings)
        self.assertNotIn("thousand", ko_norm)
        self.assertNotIn("three", ko_norm)

        ar_text = "في عام 2026 قرأت 3 كتب."
        ar_norm = normalize_text(ar_text, settings)
        self.assertNotIn("thousand", ar_norm)

    def test_multilingual_sentence_splitting(self) -> None:
        ru_sentences = split_into_sentences("Первое предложение. Второе предложение! Третье?")
        self.assertEqual(len(ru_sentences), 3)

        cjk_sentences = split_into_sentences("これは最初の文です。これは二番目の文です！")
        self.assertEqual(len(cjk_sentences), 2)

        ar_sentences = split_into_sentences("هل هذا كتاب؟ نعم، إنه كتاب رائع.")
        self.assertEqual(len(ar_sentences), 2)

    def test_narration_scenarios_and_synthesizer_registry(self) -> None:
        for key in (
            "custom",
            "fiction_audiobook",
            "technical_docs",
            "executive_briefing",
            "language_learning",
            "dramatic_dialogue",
        ):
            self.assertIn(key, NARRATION_SCENARIOS)

        for synth in ("dummy", "kokoro", "pocket-tts", "qwen3-tts", "f5-tts"):
            self.assertIn(synth, AVAILABLE_SYNTHESIZERS)

        self.assertIn("german_24l", POCKET_LANGUAGES)
        self.assertIn("spanish_24l", POCKET_LANGUAGES)
        self.assertIn("ru", QWEN3_LANGUAGES)
        self.assertIn("ko", QWEN3_LANGUAGES)

if __name__ == "__main__":
    unittest.main()
