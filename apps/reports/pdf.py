"""PDF rendering, and the fence WeasyPrint runs behind.

A PDF renderer is a small browser: it is handed markup and it goes and fetches
whatever that markup points at. Left alone it will happily open
`http://evil.example/x`, `file:///etc/passwd` or — the one that matters here —
another tenant's photo, because by the time WeasyPrint asks for a resource the
company check that guards every view has long since finished.

So the resources are enumerated, not filtered. Every internal URL uses a scheme
of our own (`vectron:`), and there is exactly one fetcher, which answers only
two questions:

- `vectron:static/<path>` — a file of this project's own static tree, found
  through Django's static finders. Nothing else in the filesystem is reachable.
- `vectron:media/<name>` — an uploaded file, and only if `<name>` is in the
  allow-list built by `documents.py` from the very objects being rendered.
  Those objects were already resolved through the tenant-scoped manager, so a
  name that is not on the list is, by construction, not this tenant's file.

Everything else — `http:`, `https:`, `file:`, `data:`, a bare relative path —
raises. `base_url` is `None` for the same reason: a relative URL has nothing to
resolve against and fails closed instead of falling back to the working
directory.
"""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders

INTERNAL_SCHEME = "vectron"
STATIC_PREFIX = "static/"
MEDIA_PREFIX = "media/"

PDF_ENGINE_MESSAGE = (
    "No se pudo generar el PDF: falta el motor de impresión en el servidor. "
    "Avisa al administrador de la plataforma."
)


class ResourceDenied(Exception):
    """A resource the document asked for is outside the fence."""


class PdfEngineUnavailable(Exception):
    """WeasyPrint (or its native libraries) is not installed on this machine."""


# --- Internal URLs ----------------------------------------------------------


def static_url(relative_path: str) -> str:
    """URL for a file of this project's static tree, e.g. `css/vectron-pdf.css`."""
    return f"{INTERNAL_SCHEME}:{STATIC_PREFIX}{relative_path}"


def media_url(storage_name: str) -> str:
    """URL for an uploaded file, by its *storage* name (`FieldFile.name`)."""
    return f"{INTERNAL_SCHEME}:{MEDIA_PREFIX}{storage_name}"


# --- The fetcher ------------------------------------------------------------


def fetch(url: str, allowed_media_names=()) -> dict:
    """Resolve one internal URL, or refuse. The whole fence, in one function."""
    scheme, separator, rest = url.partition(":")
    if not separator or scheme != INTERNAL_SCHEME:
        raise ResourceDenied(
            f"El documento pidió un recurso externo y fue rechazado: {url!r}."
        )

    if rest.startswith(STATIC_PREFIX):
        path = _resolve_static(rest[len(STATIC_PREFIX) :])
    elif rest.startswith(MEDIA_PREFIX):
        path = _resolve_media(rest[len(MEDIA_PREFIX) :], allowed_media_names)
    else:
        raise ResourceDenied(f"Ruta interna no reconocida: {url!r}.")

    return {
        "file_obj": path.open("rb"),
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    }


def make_url_fetcher(allowed_media_names=()):
    """The callable handed to WeasyPrint, closed over this document's allow-list."""
    allowed = frozenset(allowed_media_names)

    def url_fetcher(url: str) -> dict:
        return fetch(url, allowed)

    return url_fetcher


def _reject_traversal(relative_path: str) -> None:
    # Checked before anything touches the filesystem. `..` and an absolute path
    # are the two ways a relative-looking string escapes its root; a backslash
    # is the Windows spelling of the same trick.
    if (
        not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
        or ".." in relative_path.split("/")
    ):
        raise ResourceDenied(f"Ruta no permitida: {relative_path!r}.")


def _resolve_static(relative_path: str) -> Path:
    _reject_traversal(relative_path)
    # `finders.find` only ever looks inside the locations declared in
    # STATICFILES_FINDERS (STATICFILES_DIRS plus each app's own `static/`), so
    # a path it resolves is a project static file by definition. The traversal
    # check above is what stops the argument itself from pointing elsewhere.
    found = finders.find(relative_path)
    if not found:
        raise ResourceDenied(f"Recurso estático inexistente: {relative_path!r}.")
    return Path(found)


def _resolve_media(storage_name: str, allowed_media_names) -> Path:
    _reject_traversal(storage_name)
    if storage_name not in allowed_media_names:
        # The allow-list is the tenant check. It is built in documents.py from
        # objects already fetched through the scoped manager, so "not on the
        # list" and "not this company's file" are the same sentence.
        raise ResourceDenied(f"Ese archivo no pertenece a este documento: {storage_name!r}.")
    media_root = Path(settings.MEDIA_ROOT).resolve()
    path = (media_root / storage_name).resolve()
    # Belt and braces: even with the allow-list satisfied, the resolved path
    # must still land inside MEDIA_ROOT (symlinks do not count as inside).
    if not path.is_relative_to(media_root) or not path.is_file():
        raise ResourceDenied(f"Archivo de media inaccesible: {storage_name!r}.")
    return path


# --- Rendering --------------------------------------------------------------


def _load_engine():
    try:
        from weasyprint import HTML
    except Exception as error:  # ImportError, or OSError when GTK is missing
        raise PdfEngineUnavailable(PDF_ENGINE_MESSAGE) from error
    return HTML


def engine_available() -> bool:
    """Whether this machine can render a PDF at all. Used by the tests to skip."""
    try:
        _load_engine()
    except PdfEngineUnavailable:
        return False
    return True


def render(html: str, *, allowed_media_names=()) -> bytes:
    """HTML in, PDF bytes out. Nothing is written to disk, here or anywhere."""
    html_class = _load_engine()
    document = html_class(
        string=html,
        # No base URL: a relative or protocol-less URL in the template must
        # fail, not quietly resolve against the working directory.
        base_url=None,
        url_fetcher=make_url_fetcher(allowed_media_names),
    )
    return document.write_pdf()
