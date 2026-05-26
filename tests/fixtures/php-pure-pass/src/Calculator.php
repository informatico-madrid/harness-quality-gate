<?php

namespace Calculator;

class Calculator
{
    /**
     * Add two numbers. Returns the sum.
     * Branches: a==0, b==0, else
     */
    public function add(int $a, int $b): int
    {
        if ($a === 0) {
            return $b;
        }
        if ($b === 0) {
            return $a;
        }
        return $a + $b;
    }
}
