"""VisionSpark backend package.

Makes INFO logs from the ``app`` logger visible under uvicorn (Python's
last-resort handler drops INFO). Uvicorn's own logging is untouched.
"""

import logging

_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _app_logger.addHandler(logging.StreamHandler())
    _app_logger.setLevel(logging.INFO)
