"""Regression coverage for the brief 11c-1 bug.

Django tokenizes `{# ... #}` with a regex compiled WITHOUT `re.DOTALL`
(`django.template.base.tag_re`), so `.` cannot cross a newline. A `{# #}`
comment that spans more than one line is therefore never recognised as a tag
at all — the literal text, opening and closing braces included, renders
straight into the page. `{% comment %}...{% endcomment %}` is a real block
tag parsed by `Parser.parse()`, which has no such limit, and is what the rest
of this codebase already uses for every multi-line comment.

Two independent guards, because they fail differently: the static one catches
the mistake anywhere in the template tree, including partials no view test
happens to render; the rendered one proves it the way a person on the demo
actually would — by loading the page and reading it.
"""

import re
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.tests.factories import AdminUserFactory, CompanyFactory, SiteFactory
from apps.assets.tests.factories import AssetFactory
from apps.workorders.tests.factories import AssignedWorkOrderFactory, WorkOrderChecklistItemFactory

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"

# Mirrors django.template.base.tag_re's own (non-DOTALL) pairing: the first
# `#}` found after a `{#` is where Django's lexer would also look. If that
# span contains a newline, it is exactly the span Django cannot parse as a
# comment tag — re.DOTALL here is what lets *this* regex see across lines to
# find that span, not a claim that Django's lexer behaves the same way.
COMMENT_SPAN = re.compile(r"\{#.*?#\}", re.DOTALL)


class NoMultilineDjangoCommentsTests(TestCase):
    def test_no_template_has_a_multiline_hash_comment(self):
        offenders = []
        for path in sorted(TEMPLATES_DIR.rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            for match in COMMENT_SPAN.finditer(text):
                if "\n" in match.group():
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.relative_to(TEMPLATES_DIR.parent)}:{line}")

        assert not offenders, (
            "Multi-line {# #} comment(s) found — these render as literal "
            "text instead of being stripped (see module docstring). Use "
            "{% comment %}...{% endcomment %} instead:\n" + "\n".join(offenders)
        )


class NoLeakedCommentSyntaxOnScreenTests(TestCase):
    """Renders the main authenticated screens and asserts no Django comment
    delimiter reaches the response body."""

    def setUp(self):
        self.company = CompanyFactory()
        self.admin = AdminUserFactory(company=self.company)
        self.site = SiteFactory(company=self.company)
        self.asset = AssetFactory(company=self.company, site=self.site)
        self.work_order = AssignedWorkOrderFactory(asset=self.asset)
        WorkOrderChecklistItemFactory(work_order=self.work_order)

        self.client = Client()
        self.client.force_login(self.admin)

    def assert_screen_is_clean(self, url):
        response = self.client.get(url)
        assert response.status_code == 200, f"GET {url} devolvió {response.status_code}"
        page = response.content.decode()
        leaked = "{#" in page or "#}" in page
        assert not leaked, f"{url} filtró la sintaxis de un comentario Django:\n{page}"

    # Every one of these extends base.html, so each also re-proves the
    # top-bar fix; asset_detail and user_list are the two screens the bug
    # was actually seen on.
    def test_home(self):
        self.assert_screen_is_clean(reverse("home"))

    def test_asset_detail(self):
        self.assert_screen_is_clean(reverse("asset_detail", args=[self.asset.pk]))

    def test_user_list(self):
        self.assert_screen_is_clean(reverse("user_list"))

    def test_kpi_dashboard(self):
        self.assert_screen_is_clean(reverse("kpi_dashboard"))

    def test_work_order_execute(self):
        self.assert_screen_is_clean(reverse("workorder_execute", args=[self.work_order.pk]))

    def test_work_order_list(self):
        self.assert_screen_is_clean(reverse("workorder_list"))
