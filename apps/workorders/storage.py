"""Storage path for work-order photos.

The *validation* rules (size cap, extension whitelist, magic-byte sniffing,
Pillow re-encode) are not duplicated here: `forms.WorkOrderPhotoForm` calls
the very functions apps/assets/storage.py already uses for asset photos, so
there is exactly one implementation of "what counts as a safe image upload"
in the codebase.

By the time this function runs, `filename` is the server-generated
`<uuid>.<ext>` produced by `reencode_image` — the name the phone sent never
reaches the storage path, which closes path traversal by construction rather
than by escaping.
"""

import os
import uuid


def work_order_photo_upload_path(instance, filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    return f"workorders/photos/{uuid.uuid4().hex}{extension}"
