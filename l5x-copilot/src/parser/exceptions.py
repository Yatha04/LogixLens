class L5XParseError(Exception):
    """Raised when an L5X file cannot be parsed."""
    pass


class L5XValidationError(L5XParseError):
    """Raised when an L5X file fails structural validation."""
    pass
