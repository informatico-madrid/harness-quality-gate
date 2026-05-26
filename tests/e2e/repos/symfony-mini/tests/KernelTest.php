<?php

declare(strict_types=1);

namespace App\Tests;

use App\Kernel;
use PHPUnit\Framework\TestCase;

class KernelTest extends TestCase
{
    public function testHandleReturnsString(): void
    {
        $kernel = new Kernel();
        $result = $kernel->handle();
        $this->assertIsString($result);
        $this->assertEquals('Hello from symfony-mini', $result);
    }
}
