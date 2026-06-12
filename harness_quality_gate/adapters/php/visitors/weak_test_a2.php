<?php
/**
 * A2-PHP — Only mocks, no real interaction (TD-13).
 *
 * Detects test methods where every non-stdlib class reference is created
 * via createMock()/createStub() and there are zero assertions on real
 * return values (assertSame/assertEquals on non-mock objects).
 *
 * The heuristic:
 *  - Count createMock/createStub calls (mock creations)
 *  - Count method calls on real instances (not mock objects)
 *  - Count assertSame/assertEquals on non-mock return values
 *  - If mock creations > 0 AND (real method calls == 0 AND real assertions == 0), flag.
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
    $findings = visitA2Ast($src['ast'], $src['path']);
} else {
    $findings = visitA2Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A2-PHP.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA2Ast(array $ast, string $filePath): array
{
    $findings = [];
    $inTestClass = false;
    $currentTest = '';
    $currentTestLine = 0;
    $mockCreations = 0;
    $realMethodCalls = 0;
    $realAssertions = 0;

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, &$inTestClass, &$currentTest, &$currentTestLine, &$mockCreations, &$realMethodCalls, &$realAssertions, $filePath): void {
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

        // Flush previous test method
        if ($inTestClass && $currentTest !== '' && str_starts_with($methodName, 'test') === false) {
            if ($mockCreations > 0 && $realMethodCalls === 0 && $realAssertions === 0) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $currentTestLine,
                    'rule_id' => 'A2-PHP',
                    'severity' => 'error',
                    'message' => sprintf(
                        'Test method "%s" uses %d mock(s) but has zero real interactions and zero real assertions',
                        $currentTest,
                        $mockCreations
                    ),
                    'fix_hint' => 'Add real instance interactions and assertions to prove the system works',
                ];
            }
            $currentTest = '';
            return;
        }

        // Test method
        if ($inTestClass && str_starts_with($methodName, 'test')) {
            // Flush previous
            if ($currentTest !== '') {
                // already flushed above
            }
            $currentTest = $methodName;
            $currentTestLine = $node->getStartLine();
            $mockCreations = 0;
            $realMethodCalls = 0;
            $realAssertions = 0;
        }

        if ($currentTest === '') {
            return;
        }

        // Count createMock / createStub calls
        if ($node instanceof \PhpParser\Node\Expr\MethodCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier) {
                $n = (string) $name;
                if ($n === 'createMock' || $n === 'createStub') {
                    $mockCreations++;
                }
                // Check for assertions on real return values
                if (in_array($n, ['assertEquals', 'assertSame', 'assertNotEquals', 'assertNotSame', 'assertStringEqualsFile', 'assertFileEquals'], true)) {
                    // Likely a real assertion — count it
                    $realAssertions++;
                }
            }
        }

        // Count static mock creation
        if ($node instanceof \PhpParser\Node\Expr\StaticCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier) {
                $n = (string) $name;
                if ($n === 'createMock' || $n === 'createStub') {
                    $mockCreations++;
                }
            }
        }
    });

    // Flush last method
    if ($inTestClass && $currentTest !== '') {
        if ($mockCreations > 0 && $realMethodCalls === 0 && $realAssertions === 0) {
            $findings[] = [
                'file' => $filePath,
                'line' => $currentTestLine,
                'rule_id' => 'A2-PHP',
                'severity' => 'error',
                'message' => sprintf(
                    'Test method "%s" uses %d mock(s) but has zero real interactions and zero real assertions',
                    $currentTest,
                    $mockCreations
                ),
                'fix_hint' => 'Add real instance interactions and assertions to prove the system works',
            ];
        }
    }

    return $findings;
}

/**
 * Regex-based fallback for A2-PHP.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA2Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    $inTestClass = false;
    $currentTest = '';
    $currentTestLine = 0;
    $mockCreations = 0;
    $realAssertions = 0;

    foreach ($lines as $i => $line) {
        // Detect test class
        if (preg_match('/class\s+(\w+Test)\s*(?:extends|{)/', $line, $m)) {
            $inTestClass = true;
            continue;
        }

        if ($inTestClass) {
            // Detect test method
            if (preg_match('/function\s+(test\w+)\s*\(/', $line, $m)) {
                if ($currentTest !== '' && $mockCreations > 0 && $realAssertions === 0) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $currentTestLine,
                        'rule_id' => 'A2-PHP',
                        'severity' => 'error',
                        'message' => sprintf(
                            'Test method "%s" has %d mock creation(s) but no real assertions (regex fallback)',
                            $currentTest,
                            $mockCreations
                        ),
                        'fix_hint' => 'Add real instance interactions and assertions',
                    ];
                }
                $currentTest = $m[1];
                $currentTestLine = $i + 1;
                $mockCreations = 0;
                $realAssertions = 0;
            }

            // Count mock creations
            if ($currentTest !== '' && preg_match('/(createMock|createStub)\s*\(/', $line)) {
                $mockCreations++;
            }

            // Count real assertions
            if ($currentTest !== '' && preg_match('/(assertEquals|assertSame|assertNotEquals|assertNotSame|assertStringEqualsFile)\s*\(/', $line)) {
                $realAssertions++;
            }
        }
    }

    // Flush last method
    if ($inTestClass && $currentTest !== '' && $mockCreations > 0 && $realAssertions === 0) {
        $findings[] = [
            'file' => $filePath,
            'line' => $currentTestLine,
            'rule_id' => 'A2-PHP',
            'severity' => 'error',
            'message' => sprintf(
                'Test method "%s" has %d mock creation(s) but no real assertions (regex fallback)',
                $currentTest,
                $mockCreations
            ),
            'fix_hint' => 'Add real instance interactions and assertions',
        ];
    }

    return $findings;
}
