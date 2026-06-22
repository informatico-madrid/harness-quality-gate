"""Allow ``python -m harness_quality_gate`` entry point."""

import sys

from .cli import main

# reason: __main__ entry-point — module name mutations don't affect sys.exit semantics.
# audited: 2026-06-04
sys.exit(main(sys.argv[1:]))
