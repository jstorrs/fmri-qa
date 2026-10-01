"""One `warn` for the whole package, attributed to the caller's own code.

A warning is only useful if it names the line the user can change. Hand-
counted frame offsets cannot do that here: the same helper is reached
through different public entry points (`run_qa` directly, or via `analyze`), so
no single number is right. Skipping every frame whose file lives in this
package attributes the warning to the first frame outside it, however deep the
call came from.
"""

import os
import warnings
from pathlib import Path

# The trailing separator keeps the prefix from also matching the sibling
# packages (the report and the launcher), which share this parent directory
# when installed side by side in site-packages.
_PACKAGE_DIR = str(Path(__file__).parent) + os.sep


def warn(message: str) -> None:
    """Issue `message` as a `UserWarning`, reported at the caller's code."""
    warnings.warn(message, UserWarning, skip_file_prefixes=(_PACKAGE_DIR,))
