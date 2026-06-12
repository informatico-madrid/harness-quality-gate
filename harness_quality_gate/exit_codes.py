# Exit codes for quality-gate tool invocations.
# NFR-15: deterministic exit-code mapping.

PASS: int = 0
FAIL: int = 1
UNSUPPORTED: int = 2
INFRA_INCOMPLETE: int = 3
CONFIG_INVALID: int = 4
INTERNAL_ERROR: int = 5
