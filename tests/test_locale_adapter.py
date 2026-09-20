import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from xdg_pause import LocaleAdapter, DEFAULT_CONFIG


class TestLocaleAdapter(unittest.TestCase):
    def setUp(self):
        self.locales = DEFAULT_CONFIG["locales"]

    def test_hindi_seconds(self):
        adapter = LocaleAdapter(language="hi", locales_dict=self.locales)
        self.assertEqual(adapter.format_remaining(20), "20 सेकंड शेष है")
        self.assertEqual(adapter.format_remaining(1), "1 सेकंड शेष है")

    def test_hindi_minutes(self):
        adapter = LocaleAdapter(language="hi", locales_dict=self.locales)
        self.assertEqual(adapter.format_remaining(600), "10 मिनट शेष है")
        self.assertEqual(adapter.format_remaining(60), "1 मिनट शेष है")

    def test_hindi_minutes_and_seconds(self):
        adapter = LocaleAdapter(language="hi", locales_dict=self.locales)
        self.assertEqual(adapter.format_remaining(125), "2 मिनट 5 सेकंड शेष है")

    def test_english_plurals(self):
        adapter = LocaleAdapter(language="en", locales_dict=self.locales)
        # 1 second (singular) vs 5 seconds (plural)
        self.assertEqual(adapter.format_remaining(1), "1 second remaining")
        self.assertEqual(adapter.format_remaining(5), "5 seconds remaining")

        # 1 minute (singular) vs 5 minutes (plural)
        self.assertEqual(adapter.format_remaining(60), "1 minute remaining")
        self.assertEqual(adapter.format_remaining(300), "5 minutes remaining")

        # Minutes and seconds combination
        self.assertEqual(adapter.format_remaining(90), "1m 30s remaining")

    def test_resume_button_labels(self):
        adapter_hi = LocaleAdapter(language="hi", locales_dict=self.locales)
        self.assertEqual(adapter_hi.get_resume_button_label(), "वापस जाएं (Esc)")

        adapter_en = LocaleAdapter(language="en", locales_dict=self.locales)
        self.assertEqual(adapter_en.get_resume_button_label(), "Resume Work (Esc)")

    def test_unknown_language_fallback(self):
        adapter = LocaleAdapter(language="unknown_xyz", locales_dict=self.locales)
        # Should fallback to English
        self.assertEqual(adapter.format_remaining(10), "10 seconds remaining")

    def test_empty_locales_fallback(self):
        adapter = LocaleAdapter(language="any", locales_dict={})
        self.assertEqual(adapter.format_remaining(10), "10 seconds remaining")
        self.assertEqual(adapter.get_resume_button_label(), "Resume Work (Esc)")


if __name__ == "__main__":
    unittest.main()
