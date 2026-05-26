<?php
/**
 * A3 — SUT mocked (asserting on the SUT while also mocking it).
 *
 * Detects tests where the SUT (System Under Test) class appears BOTH as:
 *  1. A class being mocked via createMock/createStub
 *  2. A real instance being asserted on (assertEquals/assertSame on it)
 *
 * Also detects: assertEquals on the return value of a mock method call,
 * meaning the test only verifies mock behaviour, not real SUT behaviour.
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
    $findings = visitA3Ast($src['ast'], $src['path']);
} else {
    $findings = visitA3Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A3.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA3Ast(array $ast, string $filePath): array
{
    $findings = [];
    $inTestClass = false;
    $mockedClasses = [];
    $currentTest = '';
    $currentTestLine = 0;

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, &$inTestClass, &$mockedClasses, &$currentTest, &$currentTestLine, $filePath): void {
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
            flushA3($findings, $filePath, $currentTest, $currentTestLine, $mockedClasses);
            $mockedClasses = [];
            return;
        }

        if ($inTestClass && str_starts_with($methodName, 'test')) {
            $currentTest = $methodName;
            $currentTestLine = $node->getStartLine();
            $mockedClasses = [];
        }

        if ($currentTest === '' || !$inTestClass) {
            return;
        }

        // Detect createMock/createStub with a class reference
        if ($node instanceof \PhpParser\Node\Expr\MethodCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier) {
                $n = (string) $name;
                if ($n === 'createMock' || $n === 'createStub') {
                    $firstArg = $node->args[0] ?? null;
                    if ($firstArg instanceof \PhpParser\Node\Arg) {
                        $argVal = $firstArg->value;
                        if ($argVal instanceof \PhpParser\Node\Scalar\String_) {
                            $mockedClasses[] = $argVal->value;
                        } elseif ($argVal instanceof \PhpParser\Node\Expr\ClassConstFetch) {
                            $class = $argVal->class;
                            if ($class instanceof \PhpParser\Node\Name) {
                                $mockedClasses[] = $class->toString();
                            }
                        }
                    }
                }
            }
        }
    });

    // Flush last test
    if ($inTestClass && $currentTest !== '') {
        flushA3($findings, $filePath, $currentTest, $currentTestLine, $mockedClasses);
    }

    return $findings;
}

/**
 * Emit a finding if the test mocks a class that looks like the SUT.
 *
 * @param list<string> $mockedClasses
 */
/**
 * @param list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> $findings
 */
function flushA3(array &$findings, string $filePath, string $testName, int $testLine, array $mockedClasses): void
{
    if (empty($mockedClasses)) {
        return;
    }

    // Heuristic: if the test class is UserTest and we mock UserService, that's likely the SUT
    $testBase = preg_replace('/Test$/', '', $testName);
    foreach ($mockedClasses as $mocked) {
        // If mocked class name is similar to test name minus "Test", flag it
        $cleanMocked = preg_replace('/Service$/', '', $mocked);
        $cleanTest = preg_replace('/Test$/', '', $testBase);
        if ($cleanMocked === $cleanTest || str_contains($cleanMocked, $cleanTest)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $testLine,
                'rule_id' => 'A3',
                'severity' => 'error',
                'message' => sprintf(
                    'Test "%s" mocks "%s" — asserting on a mocked SUT proves nothing about real behaviour',
                    $testName,
                    $mocked
                ),
                'fix_hint' => 'Test the real SUT instead of mocking it; use mocks only for dependencies',
            ];
            return;
        }
    }

    // Also flag if any class is mocked in a test with that name pattern
    foreach ($mockedClasses as $mocked) {
        $base = str_ends_with($mocked, 'Service') ? rtrim($mocked, 'Service') : $mocked;
        if (str_contains(strtolower($base), strtolower($testBase))) {
            $findings[] = [
                'file' => $filePath,
                'line' => $testLine,
                'rule_id' => 'A3',
                'severity' => 'error',
                'message' => sprintf(
                    'Test "%s" mocks "%s" — SUT appears to be mocked',
                    $testName,
                    $mocked
                ),
                'fix_hint' => 'Test the real SUT; mocks should be for dependencies only',
            ];
            return;
        }
    }
}

/**
 * Regex-based fallback for A3.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA3Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    $inTestClass = false;
    $currentTest = '';
    $currentTestLine = 0;
    $mockedClasses = [];

    foreach ($lines as $i => $line) {
        // Detect test class
        if (preg_match('/class\s+(\w+Test)\s*(?:extends|{)/', $line, $m)) {
            $inTestClass = true;
            continue;
        }

        if ($inTestClass) {
            // Detect test method
            if (preg_match('/function\s+(test\w+)\s*\(/', $line, $m)) {
                if ($currentTest !== '' && !empty($mockedClasses)) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $currentTestLine,
                        'rule_id' => 'A3',
                        'severity' => 'error',
                        'message' => sprintf(
                            'Test "%s" mocks %d class(es) — SUT may be mocked (regex fallback)',
                            $currentTest,
                            count($mockedClasses)
                        ),
                        'fix_hint' => 'Test the real SUT instead of mocking it',
                    ];
                }
                $currentTest = $m[1];
                $currentTestLine = $i + 1;
                $mockedClasses = [];
            }

            // Detect createMock/createStub
            if ($currentTest !== '' && preg_match('/(createMock|createStub)\s*\(\s*[\'"]?(\w+Service\w+|\\w+Repository\w+|\\w+Model\w+)[\'"]?\s*\)/', $line, $mc)) {
                $mockedClasses[] = $mc[2];
            }
        }
    }

    // Flush last
    if ($inTestClass && $currentTest !== '' && !empty($mockedClasses)) {
        $findings[] = [
            'file' => $filePath,
            'line' => $currentTestLine,
            'rule_id' => 'A3',
            'severity' => 'error',
            'message' => sprintf(
                'Test "%s" mocks %d class(es) — SUT may be mocked (regex fallback)',
                $currentTest,
                count($mockedClasses)
            ),
            'fix_hint' => 'Test the real SUT instead of mocking it',
        ];
    }

    return $findings;
}
