<?php
/**
 * A7 — Only constructor + instanceof.
 *
 * Detects test methods that only:
 *  - Instantiate the SUT (new SomeClass())
 *  - Run instanceof checks on it
 *
 * This is a weak test because it only verifies that instanceof returns true
 * (which is always the case for a correctly-typed constructor) without
 * testing any actual behaviour.
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
    $findings = visitA7Ast($src['ast'], $src['path']);
} else {
    $findings = visitA7Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A7.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA7Ast(array $ast, string $filePath): array
{
    $findings = [];
    $inTestClass = false;
    $currentTest = '';
    $currentTestLine = 0;
    $hasInstanceof = false;
    $hasNewInstance = false;
    $hasBehaviorAssertion = false;
    $hasMethodCall = false;

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, &$inTestClass, &$currentTest, &$currentTestLine, &$hasInstanceof, &$hasNewInstance, &$hasBehaviorAssertion, &$hasMethodCall, $filePath): void {
        // Detect test class
        if ($node instanceof \PhpParser\Node\Stmt\Class_ && !empty($node->name)) {
            $className = (string) $node->name;
            $inTestClass = str_ends_with($className, 'Test');
            return;
        }

        if (!($node instanceof \PhpParser\Node\Stmt\ClassMethod)) {
            return;
        }

        $methodName = (string) $node->name;

        // Flush previous test
        if ($inTestClass && $currentTest !== '' && str_starts_with($methodName, 'test') === false) {
            if ($hasInstanceof && $hasNewInstance && !$hasBehaviorAssertion && !$hasMethodCall) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $currentTestLine,
                    'rule_id' => 'A7',
                    'severity' => 'warning',
                    'message' => sprintf('Test "%s" only creates an instance and checks instanceof — no behaviour tested', $currentTest),
                    'fix_hint' => 'Test actual behaviour (method calls, return values), not just instantiation',
                ];
            }
            $currentTest = '';
            return;
        }

        if ($inTestClass && str_starts_with($methodName, 'test')) {
            $currentTest = $methodName;
            $currentTestLine = $node->getStartLine();
            $hasInstanceof = false;
            $hasNewInstance = false;
            $hasBehaviorAssertion = false;
            $hasMethodCall = false;
        }

        if ($currentTest === '') {
            return;
        }

        // Detect instanceof checks
        if ($node instanceof \PhpParser\Node\Expr\Instanceof_
            && $node->names instanceof \PhpParser\Node\Name) {
            $hasInstanceof = true;
        }

        // Detect new Class() — instantiation
        if ($node instanceof \PhpParser\Node\Expr\New_
            && $node->class instanceof \PhpParser\Node\Name) {
            $hasNewInstance = true;
        }

        // Detect behaviour assertions
        $assertionNames = [
            'assertEquals', 'assertTrue', 'assertFalse', 'assertSame', 'assertNotSame',
            'assertNull', 'assertNotNull', 'assertContains', 'assertEmpty',
            'assertGreaterThan', 'assertLessThan', 'assertMatchesRegularExpression',
            'assertThat', 'assertIsArray', 'assertIsBool', 'assertIsInt', 'assertIsString',
        ];
        if ($node instanceof \PhpParser\Node\Expr\MethodCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier && in_array((string) $name, $assertionNames, true)) {
                $hasBehaviorAssertion = true;
            }
        }
        if ($node instanceof \PhpParser\Node\Expr\FuncCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier && in_array((string) $name, $assertionNames, true)) {
                $hasBehaviorAssertion = true;
            }
        }

        // Detect method calls on the created instance (behaviour)
        if ($node instanceof \PhpParser\Node\Expr\MethodCall) {
            // Check if it's called on a variable that was just created with 'new'
            $hasMethodCall = true;
        }
    });

    // Flush last test
    if ($inTestClass && $currentTest !== '' && $hasInstanceof && $hasNewInstance && !$hasBehaviorAssertion && !$hasMethodCall) {
        $findings[] = [
            'file' => $filePath,
            'line' => $currentTestLine,
            'rule_id' => 'A7',
            'severity' => 'warning',
            'message' => sprintf('Test "%s" only creates an instance and checks instanceof — no behaviour tested', $currentTest),
            'fix_hint' => 'Test actual behaviour (method calls, return values), not just instantiation',
        ];
    }

    return $findings;
}

/**
 * Regex-based fallback for A7.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA7Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    $inTestClass = false;
    $currentTest = '';
    $currentTestLine = 0;
    $hasInstanceof = false;
    $hasNew = false;
    $hasBehavior = false;
    $braceDepth = 0;

    foreach ($lines as $i => $line) {
        // Detect test class
        if (preg_match('/class\s+(\w+Test)\s*(?:extends|{)/', $line, $m)) {
            $inTestClass = true;
            $braceDepth = 0;
            continue;
        }

        if ($inTestClass) {
            $braceDepth += substr_count($line, '{') - substr_count($line, '}');

            // Detect test method
            if (preg_match('/function\s+(test\w+)\s*\(/', $line, $m)) {
                if ($currentTest !== '' && $hasInstanceof && $hasNew && !$hasBehavior) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $currentTestLine,
                        'rule_id' => 'A7',
                        'severity' => 'warning',
                        'message' => sprintf('Test "%s" only does instanceof + new (regex fallback)', $currentTest),
                        'fix_hint' => 'Test actual behaviour, not just instantiation',
                    ];
                }
                $currentTest = $m[1];
                $currentTestLine = $i + 1;
                $hasInstanceof = false;
                $hasNew = false;
                $hasBehavior = false;
            }

            if ($currentTest !== '' && $braceDepth > 0) {
                if (preg_match('/\binstanceof\s+\w+/', $line)) {
                    $hasInstanceof = true;
                }
                if (preg_match('/\bnew\s+\w+\s*\(/', $line)) {
                    $hasNew = true;
                }
                if (preg_match('/->(assertEquals|assertTrue|assertFalse|assertSame|assertNotSame|assertNull|assertNotNull)\s*\(/', $line)) {
                    $hasBehavior = true;
                }
            }
        }
    }

    // Flush last
    if ($inTestClass && $currentTest !== '' && $hasInstanceof && $hasNew && !$hasBehavior) {
        $findings[] = [
            'file' => $filePath,
            'line' => $currentTestLine,
            'rule_id' => 'A7',
            'severity' => 'warning',
            'message' => sprintf('Test "%s" only does instanceof + new (regex fallback)', $currentTest),
            'fix_hint' => 'Test actual behaviour, not just instantiation',
        ];
    }

    return $findings;
}
