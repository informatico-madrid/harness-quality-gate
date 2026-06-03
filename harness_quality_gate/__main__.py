"""Allow ``python -m harness_quality_gate`` entry point."""

import sys

from .cli import main

sys.exit(main(sys.argv[1:]))  # pragma: no mutate
