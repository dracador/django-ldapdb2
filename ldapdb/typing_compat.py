# See https://github.com/astral-sh/ruff/issues/15952
import sys

if sys.version_info >= (3, 12):
    from typing import Self, override
else:
    from typing_extensions import Self, override

__all__ = ['Self', 'override']
