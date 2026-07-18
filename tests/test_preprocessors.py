import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from epuboverlay.preprocessors import (
    ends_with_terminal_punctuation,
    merge_consecutive_paragraphs,
    split_xhtml_by_anchors,
    get_preprocessor,
    MarkdownPreprocessor,
    TXTPreprocessor
)

class TestPreprocessors(unittest.TestCase):
    
    def test_ends_with_terminal_punctuation(self):
        self.assertTrue(ends_with_terminal_punctuation("This is a sentence."))
        self.assertTrue(ends_with_terminal_punctuation("Is this a question?"))
        self.assertTrue(ends_with_terminal_punctuation("Wow!"))
        self.assertTrue(ends_with_terminal_punctuation("He said, 'No'"))
        self.assertTrue(ends_with_terminal_punctuation("Quote ends.\""))
        
        self.assertFalse(ends_with_terminal_punctuation("This is a sentence fragment"))
        self.assertFalse(ends_with_terminal_punctuation("Sentence continuing on the next line "))
        self.assertTrue(ends_with_terminal_punctuation(""))  # Empty text defaults to True (safety)

    def test_merge_consecutive_paragraphs(self):
        # A simple XHTML snippet with hard line breaks to merge
        html_str = """
        <div class="calibre">
            <p class="calibre2">Why read this book to find out how to win friends? Why</p>
            <p class="calibre2">not study the technique of the greatest winner of friends</p>
            <p class="calibre2">the world has ever known?</p>
            <p class="calibre4">Different class won't merge</p>
            <p class="calibre2">Another separate sentence.</p>
            <p class="calibre2">This is continuing</p>
        </div>
        """
        root = ET.fromstring(html_str)
        merge_consecutive_paragraphs(root)
        
        paragraphs = list(root.findall(".//p"))
        # Expected:
        # Paragraph 1 & 2 & 3 merged into 1 (since 1 and 2 don't end in punctuation and classes match)
        # Paragraph 4 is untouched (different class)
        # Paragraph 5 is untouched (previous ends with '?')
        # Paragraph 6 is untouched (previous ends with '.')
        self.assertEqual(len(paragraphs), 4)
        
        self.assertIn("Why not study the technique", "".join(paragraphs[0].itertext()))
        self.assertEqual(paragraphs[1].text, "Different class won't merge")
        self.assertEqual(paragraphs[2].text, "Another separate sentence.")
        self.assertEqual(paragraphs[3].text, "This is continuing")

    def test_split_xhtml_by_anchors(self):
        html_str = """
        <html>
            <head><title>Test Book</title></head>
            <body>
                <div class="content">
                    <h1 id="intro">Introduction</h1>
                    <p>Welcome to the book.</p>
                    <h1 id="chap1">Chapter 1</h1>
                    <p>This is the first chapter.</p>
                </div>
            </body>
        </html>
        """
        root = ET.fromstring(html_str)
        anchors = ["intro", "chap1"]
        
        roots = split_xhtml_by_anchors(root, anchors)
        # Expected 3 sections:
        # Section 0: before "intro" (empty/only boilerplate container tags)
        # Section 1: "intro" to before "chap1" (contains Introduction header & paragraph)
        # Section 2: "chap1" onwards (contains Chapter 1 header & paragraph)
        self.assertEqual(len(roots), 3)
        
        # Verify Section 1
        sec1_text = " ".join("".join(roots[1].itertext()).split())
        self.assertIn("Introduction Welcome to the book.", sec1_text)
        self.assertNotIn("Chapter 1", sec1_text)
        
        # Verify Section 2
        sec2_text = " ".join("".join(roots[2].itertext()).split())
        self.assertIn("Chapter 1 This is the first chapter.", sec2_text)
        self.assertNotIn("Introduction", sec2_text)

    def test_markdown_preprocessor(self):
        md_content = """# Intro
This is a markdown introduction.

## Chapter 1
First chapter details.
Some lines.

# Conclusion
Final wrap up.
"""
        # Create a temp file
        tmp_path = Path("test_doc.md")
        tmp_path.write_text(md_content, encoding="utf-8")
        
        try:
            parser = MarkdownPreprocessor()
            self.assertTrue(parser.can_handle(tmp_path))
            
            sections = parser.extract_sections(tmp_path)
            self.assertEqual(len(sections), 3)
            self.assertEqual(sections[0].title, "Intro")
            self.assertEqual(sections[1].title, "Chapter 1")
            self.assertEqual(sections[2].title, "Conclusion")
            
            self.assertIn("markdown introduction.", sections[0].text_content)
            self.assertIn("First chapter details.", sections[1].text_content)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_txt_preprocessor(self):
        txt_content = """Introduction text is here.

Chapter 1
Some contents of chapter 1.

Section 2
Contents of section 2.
"""
        tmp_path = Path("test_doc.txt")
        tmp_path.write_text(txt_content, encoding="utf-8")
        
        try:
            parser = TXTPreprocessor()
            self.assertTrue(parser.can_handle(tmp_path))
            
            sections = parser.extract_sections(tmp_path)
            self.assertEqual(len(sections), 3)
            self.assertEqual(sections[0].title, "Introduction")
            self.assertEqual(sections[1].title, "Chapter 1")
            self.assertEqual(sections[2].title, "Section 2")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_find_heuristic_anchors(self):
        from epuboverlay.preprocessors.epub import find_heuristic_anchors
        
        # Test document with spaced headings, standalone headers, and summary list elements
        html_str = """
        <html>
            <body>
                <p>Some introductory paragraph before things begin.</p>
                <p>P R E F A C E</p>
                <p>This is the actual text of the preface, which is a bit longer than a single sentence so it builds up character count. Let's make sure it accumulates enough text to bypass the threshold for the next header. This is some extra dummy text to make sure the size exceeds five hundred characters. We need to add enough content here so that the distance is sufficient. Let's repeat some words: Dale Carnegie wrote a very famous book about how to win friends and influence people. It is a great book and has sold millions of copies all around the world.</p>
                <p>PART ONE</p>
                <p>This is a long body paragraph introducing the first part of the book. It needs to contain a sufficient number of characters to make sure that the PART ONE header is not discarded as a summary list item. Therefore, we write some useful text about the fundamental techniques in handling people, such as showing genuine interest, avoiding criticism, and understanding human psychology. We want to reach the five hundred character limit to successfully split this section. This is some extra text to make it even longer and completely exceed the threshold without any doubt.</p>
                <p>PRINCIPLE 1</p>
                <p>PRINCIPLE 2</p>
                <p>This is a summary of the principles that comes right at the beginning. Because these two candidates are so close to each other, they form a summary cluster and should be ignored! Let's write more text here too to build up characters for the next chapter. The principles are: don't criticize, condemn or complain. Give honest and sincere appreciation. Arouse in the other person an eager want. These are very important guidelines for handling relationships successfully.</p>
                <p>CHAPTER I</p>
                <p>This is the real chapter body. It contains a lot of text that describes the actual story or contents of the chapter. We write enough characters to make it exceed the 500-character threshold so that the next chapter is not ignored. Let's add more text to make it extremely long. The chapter explains why criticizing people is futile and only leads to resentment. It gives examples of criminals like Al Capone and Crowley who never blamed themselves for their actions, showing that human nature is to defend ourselves even when we are completely wrong.</p>
                <p>CHAPTER II</p>
                <p>This is the second chapter body text.</p>
            </body>
        </html>
        """
        root = ET.fromstring(html_str)
        anchors = find_heuristic_anchors(root)
        
        anchor_texts = [a[1] for a in anchors]
        self.assertIn("PREFACE", anchor_texts)
        self.assertIn("PART ONE", anchor_texts)
        self.assertIn("CHAPTER I", anchor_texts)
        self.assertIn("CHAPTER II", anchor_texts)
        
        # PRINCIPLE 1 and PRINCIPLE 2 should be filtered out because they are too close to each other
        self.assertNotIn("PRINCIPLE 1", anchor_texts)
        self.assertNotIn("PRINCIPLE 2", anchor_texts)

