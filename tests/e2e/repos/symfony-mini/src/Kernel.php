<?php

namespace App;

/**
 * Minimal Symfony kernel for E2E gate testing.
 */
class Kernel
{
    public function handle(): string
    {
        return 'Hello from symfony-mini';
    }
}
