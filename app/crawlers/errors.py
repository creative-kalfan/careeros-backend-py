"""Typed crawler errors used for target health decisions."""


class BoardNotFoundError(Exception):
    """The source explicitly reported that an ATS board does not exist."""
