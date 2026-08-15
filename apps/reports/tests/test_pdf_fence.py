"""The fence around WeasyPrint's resource loading.

A PDF renderer fetches whatever the markup points at, long after the view's
company check has finished. These tests are the proof that it can only ever
reach two things: this project's own static files, and the specific uploads the
document was built from.

None of them needs WeasyPrint installed — the fetcher is a plain function, and
that is the point of keeping it one.
"""

import tempfile
from pathlib import Path

import pytest
from django.test import SimpleTestCase, override_settings

from apps.reports import documents, pdf

REFUSED_URLS = [
    "http://evil.example/pixel.png",
    "https://evil.example/pixel.png",
    "file:///etc/passwd",
    "file://C:/Windows/win.ini",
    "data:image/png;base64,iVBORw0KGgo=",
    "ftp://evil.example/x",
    "//evil.example/pixel.png",
    "pixel.png",
    "../../config/settings.py",
    "",
]


class ExternalResourcesTests(SimpleTestCase):
    def test_every_url_outside_our_scheme_is_refused(self):
        for url in REFUSED_URLS:
            with self.subTest(url=url), pytest.raises(pdf.ResourceDenied):
                pdf.fetch(url)

    def test_unknown_internal_path_is_refused(self):
        with pytest.raises(pdf.ResourceDenied):
            pdf.fetch("vectron:secretos/llaves.txt")


class StaticResourcesTests(SimpleTestCase):
    def test_the_print_stylesheet_resolves(self):
        result = pdf.fetch(pdf.static_url(documents.STYLESHEET))

        with result.open() as handle:
            content = handle.read()
        assert b"@page" in content
        assert result.content_type == "text/css"

    def test_the_brand_mark_resolves(self):
        result = pdf.fetch(pdf.static_url(documents.BRAND_MARK))

        with result.open() as handle:
            assert b"svg" in handle.read()

    def test_traversal_out_of_the_static_tree_is_refused(self):
        for relative in ["../config/settings.py", "css/../../../.env", "/etc/passwd", "css\\x"]:
            with self.subTest(relative=relative), pytest.raises(pdf.ResourceDenied):
                pdf.fetch(pdf.static_url(relative))

    def test_a_static_file_that_does_not_exist_is_refused(self):
        with pytest.raises(pdf.ResourceDenied):
            pdf.fetch(pdf.static_url("css/no-existe.css"))


class MediaResourcesTests(SimpleTestCase):
    """The allow-list is the tenant check: it is built from objects already
    fetched through the scoped manager, so "not on the list" and "not this
    company's file" are the same sentence."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "workorders").mkdir()
        self.mine = "workorders/mia.jpg"
        self.theirs = "workorders/ajena.jpg"
        (self.root / self.mine).write_bytes(b"\xff\xd8\xff mine")
        (self.root / self.theirs).write_bytes(b"\xff\xd8\xff theirs")

    def test_an_allow_listed_upload_resolves(self):
        with override_settings(MEDIA_ROOT=self.root):
            result = pdf.fetch(pdf.media_url(self.mine), {self.mine})

        with result.open() as handle:
            assert handle.read().endswith(b"mine")

    def test_an_upload_outside_the_allow_list_is_refused(self):
        """Another company's photo exists on disk and is still unreachable."""
        with override_settings(MEDIA_ROOT=self.root), pytest.raises(pdf.ResourceDenied):
            pdf.fetch(pdf.media_url(self.theirs), {self.mine})

    def test_an_empty_allow_list_reaches_nothing(self):
        with override_settings(MEDIA_ROOT=self.root), pytest.raises(pdf.ResourceDenied):
            pdf.fetch(pdf.media_url(self.mine))

    def test_traversal_is_refused_even_if_the_string_is_allow_listed(self):
        escape = "../../.env"
        with override_settings(MEDIA_ROOT=self.root), pytest.raises(pdf.ResourceDenied):
            pdf.fetch(pdf.media_url(escape), {escape})

    def test_a_missing_file_is_refused_rather_than_crashing(self):
        missing = "workorders/borrada.jpg"
        with override_settings(MEDIA_ROOT=self.root), pytest.raises(pdf.ResourceDenied):
            pdf.fetch(pdf.media_url(missing), {missing})


class UrlFetcherTests(SimpleTestCase):
    def test_the_fetcher_handed_to_weasyprint_carries_the_allow_list(self):
        fetcher = pdf.make_url_fetcher(["workorders/nope.jpg"])

        with pytest.raises(pdf.ResourceDenied):
            fetcher("https://evil.example/x.png")

    def test_a_refusal_does_not_need_the_engine(self):
        """The denial path must not import WeasyPrint.

        It is the reason `fetch` returns a `Resource` of ours: on a machine
        with no GTK, an engine-first fetcher would answer "no puedo imprimir"
        to a URL that should have been answered with "no".
        """
        fetcher = pdf.make_url_fetcher()

        with pytest.raises(pdf.ResourceDenied):
            fetcher("file:///etc/passwd")

    @pytest.mark.skipif(
        not pdf.engine_available(),
        reason="Sin las librerías nativas de WeasyPrint (en Windows: GTK). Corre en CI.",
    )
    def test_the_fetcher_returns_weasyprints_own_response_type(self):
        """Brief 08 carry-over. WeasyPrint 69 still accepts the dict this used
        to return, with a DeprecationWarning, and drops it next version —
        `isinstance` against the real class is what proves we are off it."""
        from weasyprint.urls import URLFetcherResponse

        fetcher = pdf.make_url_fetcher()
        response = fetcher(pdf.static_url(documents.STYLESHEET))

        assert isinstance(response, URLFetcherResponse)
        assert response.content_type == "text/css"
        try:
            assert b"@page" in response.read()
        finally:
            response.close()
