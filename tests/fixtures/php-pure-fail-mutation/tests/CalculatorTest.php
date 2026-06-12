<?php

namespace CalculatorTest;

use Calculator\Calculator;
use PHPUnit\Framework\TestCase;

final class CalculatorTest extends TestCase
{
    private Calculator $calculator;

    protected function setUp(): void
    {
        $this->calculator = new Calculator();
    }

    public function testAddPositiveNumbers(): void
    {
        $this->assertSame(5, $this->calculator->add(2, 3));
    }

    public function testAddZeroLeft(): void
    {
        // BUG: This test only covers the left-zero branch,
        // but NOT the right-zero branch ($b === 0 when $a !== 0)
        // Infection will mutate the `$b === 0` condition to `$b !== 0`
        // and the test will NOT detect it.
        $this->assertSame(5, $this->calculator->add(0, 5));
    }

    // NOTE: Missing testAddZeroRight() — this is intentional!
    // The gap between testAddZeroLeft and the general case means
    // the mutation $b === 0 -> $b !== 0 will escape.
}
