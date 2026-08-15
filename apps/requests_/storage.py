"""Storage path for the photo attached to a failure report.

The *validation* rules (size cap, extension whitelist, magic-byte sniffing,
Pillow re-encode) are not duplicated here: `forms.MaintenanceRequestForm` calls
the same functions apps/assets/storage.py already uses, so there is exactly one
implementation of "what counts as a safe image upload" in the codebase — the
same arrangement apps/workorders/storage.py describes.

By the time this runs, `filename` is the server-generated `<uuid>.<ext>`
produced by `reencode_image`: the name the phone sent never reaches the storage
path, which closes path traversal by construction rather than by escaping.
"""

import os
import uuid


def request_photo_upload_path(instance, filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    return f"requests/photos/{uuid.uuid4().hex}{extension}"
