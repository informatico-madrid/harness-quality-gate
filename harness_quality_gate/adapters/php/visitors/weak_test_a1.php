<?php
/**
 * A1 — Zero-assertion test methods.
 *
 * Detects test methods (names starting with test_) inside PHPUnit test classes
 * that contain zero assertion calls (assertEquals, assertTrue, assertFalse,
 * assertNotEquals, assertSame, assertNotSame, assertNull, assertNotNull,
 * assertContains, assertNotContains, assertThat, assertFileExists, etc.).
 *
 * Falls back to regex when nikic/php-parser is unavailable.
 */
declare(strict_types=1);

require_once __DIR__ . '/_common.php';

$filePath = $argv[1] ?? null;
if ($filePath === null || !is_file($filePath)) {
    echo json_encode([]);
    exit(0);
}

$src = common_parse_file($filePath);
$findings = [];

if ($src['ast'] !== null) {
    $findings = visitA1Ast($src['ast'], $src['path']);
} else {
    $findings = visitA1Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection: test methods with no assertion calls.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA1Ast(array $ast, string $filePath): array
{
    $findings = [];
    $assertionCalls = [
        'assertEquals', 'assertNotEquals', 'assertTrue', 'assertFalse',
        'assertSame', 'assertNotSame', 'assertNull', 'assertNotNull',
        'assertContains', 'assertNotContains', 'assertEmpty', 'assertNotEmpty',
        'assertGreaterThan', 'assertGreaterThanOrEqual',
        'assertLessThan', 'assertLessThanOrEqual',
        'assertMatchesRegularExpression', 'assertStringMatchesFormatFile',
        'assertFileExists', 'assertDirectoryExists', 'assertIsArray',
        'assertIsBool', 'assertIsFloat', 'assertIsInt', 'assertIsString',
        'assertObjectType', 'assertInternalType', 'assertRegExp',
        'assertThat', 'assertCount', 'assertGreaterThan', 'assertSameSize',
        'assertNotSameSize', 'assertAttributeEquals',
    ];

    $inTestClass = false;
    $testMethodName = '';
    $testMethodLine = 0;
    $hasAssertion = false;

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, &$inTestClass, &$testMethodName, &$testMethodLine, &$hasAssertion, $filePath, $assertionCalls): void {
        // Detect test class
        if ($node instanceof \PhpParser\Node\Stmt\Class_ && !empty($node->name)) {
            $className = (string) $node->name;
            $inTestClass = str_ends_with($className, 'Test');
            return;
        }

        if (!($node instanceof \PhpParser\Node\Stmt\ClassMethod)) {
            return;
        }

        // Detect test method: name starts with "test"
        $methodName = (string) $node->name;
        if ($inTestClass && str_starts_with($methodName, 'test')) {
            $testMethodName = $methodName;
            $testMethodLine = $node->getStartLine();
            $hasAssertion = false;
        } else {
            // Flush previous test method
            if ($inTestClass && $testMethodName !== '' && !$hasAssertion) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $testMethodLine,
                    'rule_id' => 'A1',
                    'severity' => 'error',
                    'message' => sprintf('Test method "%s" has no assertions', $testMethodName),
                    'fix_hint' => 'Add assertions (assertEquals, assertTrue, etc.) to verify behaviour',
                ];
            }
            $testMethodName = '';
            return;
        }

        // Check for assertion calls inside this test method
        if ($node instanceof \PhpParser\Node\Expr\MethodCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier && in_array((string) $name, $assertionCalls, true)) {
                $hasAssertion = true;
            }
            // Also check $this->assertEquals(...)
            if ($node->var instanceof \PhpParser\Node\Expr\Variable && ($node->var->name === 'this' || $node->var->name === 'assertThat')) {
                // Already handled above via $node->name
            }
        }

        // Static calls: self::assertEquals(), static::assertTrue()
        if ($node instanceof \PhpParser\Node\Expr\StaticCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier && in_array((string) $name, $assertionCalls, true)) {
                $hasAssertion = true;
            }
        }

        // Function call assertions: assertEquals() (plain function)
        if ($node instanceof \PhpParser\Node\Expr\FuncCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier && in_array((string) $name, $assertionCalls, true)) {
                $hasAssertion = true;
            }
        }
    });

    // Flush last method
    if ($inTestClass && $testMethodName !== '' && !$hasAssertion) {
        $findings[] = [
            'file' => $filePath,
            'line' => $testMethodLine,
            'rule_id' => 'A1',
            'severity' => 'error',
            'message' => sprintf('Test method "%s" has no assertions', $testMethodName),
            'fix_hint' => 'Add assertions (assertEquals, assertTrue, etc.) to verify behaviour',
        ];
    }

    return $findings;
}

/**
 * Regex-based fallback for A1.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA1Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    $inTestClass = false;
    $testMethodName = '';
    $testMethodLine = 0;
    $braceDepth = 0;

    foreach ($lines as $i => $line) {
        // Detect test class
        if (preg_match('/^\s*(?:abstract\s+)?class\s+(\w+Test)\s*(?:extends|{)/', $line, $m)) {
            $inTestClass = true;
            $braceDepth = 0;
            continue;
        }
        if (preg_match('/^\s*(?:abstract\s+)?class\s+(\w+)\s*(?:extends)/', $line, $m)) {
            $inTestClass = str_ends_with($m[1], 'Test');
            $braceDepth = 0;
            continue;
        }

        if ($inTestClass) {
            $braceDepth += substr_count($line, '{') - substr_count($line, '}');

            // Detect test method
            if (preg_match('/^\s*public\s+function\s+(test\w+)\s*\(/', $line, $m)) {
                if ($testMethodName !== '' && $braceDepth > 0) {
                    // Check if previous method had assertions — simplified: flag all
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $testMethodLine,
                        'rule_id' => 'A1',
                        'severity' => 'error',
                        'message' => sprintf('Test method "%s" may have no assertions (regex fallback)', $testMethodName),
                        'fix_hint' => 'Add assertions to verify behaviour',
                    ];
                }
                $testMethodName = $m[1];
                $testMethodLine = $i + 1;
            }

            // Check for assertion calls inside method body
            if ($testMethodName !== '' && preg_match('/(assertEquals|assertTrue|assertFalse|assertSame|assertNotSame|assertNull|assertNotNull|assertContains|assertEmpty|assertGreaterThan|assertLessThan|assertMatchesRegularExpression|assertThat)\s*\(/', $line)) {
                $testMethodName = ''; // mark as having assertion
            }
        }
    }

    // Flush last method
    if ($inTestClass && $testMethodName !== '') {
        $findings[] = [
            'file' => $filePath,
            'line' => $testMethodLine,
            'rule_id' => 'A1',
            'severity' => 'error',
            'message' => sprintf('Test method "%s" may have no assertions (regex fallback)', $testMethodName),
            'fix_hint' => 'Add assertions to verify behaviour',
        ];
    }

    return $findings;
}
