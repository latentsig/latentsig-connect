class VisionUnavailable(Exception):
    """The configured vision provider could not return a usable response."""


class VisionConfigurationError(Exception):
    """Vision extraction is not configured for this deployment."""
