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

    // Covers the a==0 branch
    public function testAddFirstZero(): void
    {
        $this->assertSame(5, $this->calculator->add(0, 5));
    }

    // Covers the b==0 branch
    public function testAddSecondZero(): void
    {
        $this->assertSame(5, $this->calculator->add(5, 0));
    }

    // Covers the else (a+b) branch
    public function testAddPositiveNumbers(): void
    {
        $this->assertSame(5, $this->calculator->add(2, 3));
    }

    // Edge case: both zero covers both conditions
    public function testAddBothZero(): void
    {
        $this->assertSame(0, $this->calculator->add(0, 0));
    }

    // Kills DecrementInteger mutant on $a===0 branch (a=-1 must return 4, not 5)
    public function testAddNegativeFirst(): void
    {
        $this->assertSame(4, $this->calculator->add(-1, 5));
    }

    // Kills DecrementInteger mutant on $b===0 branch (b=-1 must return 4, not 5)
    public function testAddNegativeSecond(): void
    {
        $this->assertSame(4, $this->calculator->add(5, -1));
    }
}
