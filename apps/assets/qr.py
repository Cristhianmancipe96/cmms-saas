"""The QR code on the machine: the URL it carries and the SVG that gets printed.

Three decisions live here rather than in a view or a template, because a
printed sticker is the one artefact of this product that cannot be patched
after the fact:

1. **The label encodes `qr_uuid`, never the primary key.** `Asset.qr_uuid`
   (brief 02) is a non-editable uuid4. A sequential id on a sticker is an
   invitation to type `/e/2` and, worse, tells anyone holding one label how
   many machines the company owns. The uuid says nothing and guesses at
   nothing: 122 random bits.
2. **The URL is absolute and comes from `settings.SITE_URL`.** A phone's
   camera app opens whatever string the QR contains, with no page for a
   relative path to resolve against. And the base URL is configuration, not
   `request.build_absolute_uri`: the sticker outlives the request, so it must
   point at the deployment the plant actually uses — not at whichever host
   (a proxy, a LAN address, localhost) happened to render the label.
3. **The QR is inline SVG.** No image file to store, no `/media/` URL to
   gate, no JavaScript library: vector print output that stays sharp at any
   sticker size, generated server-side and dropped straight into the page.
"""

from urllib.parse import urlparse

import segno
from django.conf import settings
from django.urls import reverse
from django.utils.safestring import SafeString, mark_safe

# ~15% of the code can be destroyed and still read. A sticker on a machine
# lives in grease, steam and forklift traffic; the default (L, ~7%) is sized
# for a screen, not for a plant floor. Higher levels (Q, H) would buy more
# tolerance at the cost of a denser grid, which is worse on a small label.
QR_ERROR_LEVEL = "m"

# Quiet zone in modules. Scanners need clear space around the pattern; below
# 2 they start failing on exactly the labels that are already dirty.
QR_BORDER = 2


# Hosts that mean "this computer" and nobody else's. A label printed against
# one of them is a sticker that works on the developer's laptop and nowhere in
# the plant — a silent no-op, glued to a machine.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def asset_scan_url(asset) -> str:
    """The absolute `/e/<qr_uuid>` URL a phone opens after scanning."""
    return f"{settings.SITE_URL.rstrip('/')}{reverse('asset_scan', args=[asset.qr_uuid])}"


def is_local_url(url: str) -> bool:
    """Would a sticker carrying this URL be readable from anywhere else?

    Checked and shown on the label screen rather than left to whoever
    remembers `.env`: an unset `SITE_URL` produces a page that looks entirely
    correct and a QR that resolves only on the machine that printed it. The
    mistake is invisible until someone is standing in front of a stopped
    machine with a phone.
    """
    return urlparse(url).hostname in LOCAL_HOSTS


def qr_svg(data: str, *, css_class: str = "vt-qr") -> SafeString:
    """Render `data` as an inline `<svg>` sized by CSS, not by attributes.

    `mark_safe` is safe here by construction, not by inspection: the only
    input is a URL built from `SITE_URL` plus a UUID, and segno emits it as
    path coordinates — the string never appears in the markup at all.
    """
    return mark_safe(
        segno.make(data, error=QR_ERROR_LEVEL).svg_inline(
            omitsize=True,  # viewBox instead of width/height: CSS decides the size
            border=QR_BORDER,
            svgclass=css_class,
            lineclass=None,
            dark="#000000",  # print black, in both themes — a scanner reads ink
        )
    )
