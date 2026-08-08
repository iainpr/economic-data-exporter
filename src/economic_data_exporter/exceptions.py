"""Typed application exceptions."""


class EconomicDataError(Exception):
    """Base exception for expected application failures."""


class ValidationError(EconomicDataError):
    pass


class AuthenticationError(EconomicDataError):
    pass


class RateLimitError(EconomicDataError):
    pass


class NetworkError(EconomicDataError):
    pass


class SourceUnavailableError(EconomicDataError):
    pass


class SourceNotFoundError(SourceUnavailableError):
    """Provider reports that the requested resource does not exist."""


class ParsingError(EconomicDataError):
    pass


class ExportError(EconomicDataError):
    pass


class CancelledError(EconomicDataError):
    pass
