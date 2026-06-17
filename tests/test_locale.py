"""Tests for the local i18n package that shadows stdlib locale."""


class TestLocaleCompatibility:
    """Keep stdlib locale behavior available for subprocess and text I/O."""

    def test_stdlib_getencoding_is_exposed(self):
        import locale

        assert hasattr(locale, "getencoding")
        assert callable(locale.getencoding)
        assert isinstance(locale.getencoding(), str)

    def test_translation_helpers_still_work(self):
        import locale

        previous_lang = locale._current_lang
        try:
            locale.set_lang("en_US")
            assert locale.t("play.start") == "Start"
            assert locale.t("missing.key") == "missing.key"
        finally:
            locale.set_lang(previous_lang)