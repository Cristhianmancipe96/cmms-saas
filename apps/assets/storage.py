"""Upload validation and path generation for asset photos and documents.

Security rules (CLAUDE.md #1, brief 02 criterion 5): whitelist extension and
sniffed content, cap size, re-encode images with Pillow to strip any active
payload or EXIF data, and never let a user-supplied filename reach the
storage path (that closes path traversal by construction, not by escaping).
"""

import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

# On-disk size is a poor proxy for decode-time cost: a solid-color PNG at
# 13000x13000px compresses under 1 MB but decodes to ~1 GB of native memory
# once Pillow loads and converts it. Reject by pixel count before that ever
# happens — this cap is far above any real phone photo (~40 MP) and far
# below Pillow's own MAX_IMAGE_PIXELS bomb threshold, so it fires first.
MAX_IMAGE_PIXELS = 40_000_000

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}

_PIL_FORMAT_BY_EXTENSION = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}

_PDF_MAGIC = b"%PDF-"


def _extension_of(filename: str) -> str:
    # rsplit-based suffix, same idea as pathlib.Path.suffix: only the LAST
    # dot-segment counts, so "manual.pdf.exe" is judged on ".exe" — a double
    # extension can never smuggle a forbidden type past this check.
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _reject(message: str):
    raise ValidationError(message)


def validate_upload_size(uploaded_file):
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        _reject("El archivo supera el tamaño máximo permitido de 10 MB.")


def validate_image_upload(uploaded_file) -> str:
    """Validate an image-only upload (main photo). Returns the normalized extension."""
    validate_upload_size(uploaded_file)
    extension = _extension_of(uploaded_file.name or "")
    if extension not in IMAGE_EXTENSIONS:
        _reject("Formato no permitido. Usa una imagen JPG, PNG o WEBP.")
    _verify_is_real_image(uploaded_file)
    return extension


def validate_document_upload(uploaded_file) -> str:
    """Validate a document upload (image or PDF). Returns the normalized extension."""
    validate_upload_size(uploaded_file)
    extension = _extension_of(uploaded_file.name or "")
    if extension not in DOCUMENT_EXTENSIONS:
        _reject("Formato no permitido. Usa una imagen JPG, PNG, WEBP o un PDF.")
    if extension == ".pdf":
        _verify_is_real_pdf(uploaded_file)
    else:
        _verify_is_real_image(uploaded_file)
    return extension


def _verify_is_real_image(uploaded_file):
    """Reject spoofed content-type / non-image bytes wearing an image extension,
    and reject decompression bombs before any full pixel decode is attempted.
    """
    uploaded_file.seek(0)
    try:
        with Image.open(uploaded_file) as probe:
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS:
                _reject("La imagen es demasiado grande. Reduce su resolución e inténtalo de nuevo.")
            probe.verify()
    except Image.DecompressionBombError:
        _reject("La imagen es demasiado grande. Reduce su resolución e inténtalo de nuevo.")
    except (UnidentifiedImageError, OSError, ValueError):
        _reject("El archivo no es una imagen válida.")
    finally:
        uploaded_file.seek(0)


def _verify_is_real_pdf(uploaded_file):
    """Reject spoofed content-type / non-PDF bytes wearing a .pdf extension."""
    uploaded_file.seek(0)
    header = uploaded_file.read(len(_PDF_MAGIC))
    uploaded_file.seek(0)
    if header != _PDF_MAGIC:
        _reject("El archivo no es un PDF válido.")


def reencode_image(uploaded_file, extension: str) -> ContentFile:
    """Re-save the image through Pillow so EXIF and any active payload are dropped.

    Callers are expected to run this only after _verify_is_real_image has
    passed, but the pixel-count guard is repeated here too: this is the
    function that actually pays the decode cost, and it must be safe to call
    on its own, not just safe when callers behave.
    """
    uploaded_file.seek(0)
    pil_format = _PIL_FORMAT_BY_EXTENSION[extension]
    with Image.open(uploaded_file) as source:
        width, height = source.size
        if width * height > MAX_IMAGE_PIXELS:
            _reject("La imagen es demasiado grande. Reduce su resolución e inténtalo de nuevo.")
        source.load()
        image = source.convert("RGB") if pil_format == "JPEG" else source.convert("RGBA")
        buffer = io.BytesIO()
        if pil_format == "JPEG":
            image.save(buffer, format=pil_format, quality=88, optimize=True)
        else:
            image.save(buffer, format=pil_format)
    buffer.seek(0)
    return ContentFile(buffer.read(), name=f"{uuid.uuid4().hex}{extension}")


def random_storage_name(extension: str) -> str:
    """A server-generated, non-guessable filename — never derived from user input."""
    return f"{uuid.uuid4().hex}{extension}"


def asset_photo_upload_path(instance, filename):
    extension = _extension_of(filename)
    return f"assets/photos/{uuid.uuid4().hex}{extension}"


def asset_document_upload_path(instance, filename):
    extension = _extension_of(filename)
    return f"assets/documents/{uuid.uuid4().hex}{extension}"
