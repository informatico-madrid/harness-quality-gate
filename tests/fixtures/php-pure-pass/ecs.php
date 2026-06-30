<?php

declare(strict_types=1);

use Symplify\EasyCodingStandard\Config\ECSConfig;

// Pure-pass smoke fixture: PSR-12 over src/ only, skipping vendor/var. The
// adapter passes the repo root as the scan path (which overrides withPaths), so
// withSkip keeps ECS off the installed vendor/ tree. Without this file ECS 12.x
// prompts interactively for config generation and blocks on stdin until the
// adapter's 300s timeout — the CI hang this fixes.
return ECSConfig::configure()
    ->withPaths([__DIR__ . '/src'])
    ->withSkip([__DIR__ . '/vendor', __DIR__ . '/var'])
    ->withPreparedSets(psr12: true);
