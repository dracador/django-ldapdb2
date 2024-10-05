import hashlib


class UnsupportedHashAlgorithmError(ValueError):
    """Raised when an unsupported hash algorithm is used."""
    def __init__(self, algorithm: str):
        super().__init__(
            f'Unsupported algorithm: {algorithm}. '
            f'Supported algorithms: {hashlib.algorithms_available}. '
            f'Use SSHA$number for salted hashes.'
        )
