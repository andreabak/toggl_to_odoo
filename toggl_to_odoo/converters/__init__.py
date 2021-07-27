import os
import pkgutil
from typing import List

from ..utils import import_submodules


__path__: List[str]
__path__ = [os.path.abspath(path) for path in pkgutil.extend_path(__path__, __name__)]

__all__ = []


def import_converters():
    global __path__, __all__
    __all__ = import_submodules(__path__, globals(), package=__name__)
