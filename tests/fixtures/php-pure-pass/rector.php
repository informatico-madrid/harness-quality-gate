<?php

declare(strict_types=1);

use Rector\Config\RectorConfig;

// Pure-pass smoke fixture: scope Rector to src/ and register no rule sets so a
// clean codebase yields zero proposals (dry-run → no file_diffs → L3A PASS).
// Rule enforcement is covered by the rector_adapter unit tests, not this smoke.
// Without this file Rector 2.x prompts interactively for config generation and
// blocks on stdin until the adapter's 300s timeout — the CI hang this fixes.
return RectorConfig::configure()
    ->withPaths([__DIR__ . '/src']);
