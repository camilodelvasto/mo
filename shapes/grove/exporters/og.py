"""Grove OG enforcer — validate grove-level Open Graph metadata."""


class OGError(Exception):
    """Raised when OG metadata is missing or incomplete."""
    pass


_REQUIRED_FIELDS = ("title", "description", "image")


def validate_grove_og(grove: dict) -> None:
    """Throw OGError if grove is missing og block or any required field."""
    if "og" not in grove:
        raise OGError("Grove config missing 'og' block")

    og = grove["og"]
    for field in _REQUIRED_FIELDS:
        if field not in og:
            raise OGError(f"Grove og missing required field '{field}'")
