<?php
/**
 * A8 — Assertion on tautology.
 *
 * Detects assertions that always evaluate to the same result regardless
 * of the system being tested:
 *  - assertEquals(1, 1), assertEquals(2, 2), etc.
 *  - assertTrue(true), assertFalse(false)
 *  - assertStringContainsString('x', 'x')
 *  - assertSame('hello', 'hello')
 *  - assertEmpty([]), assertNotEmpty(['x'])
 *
 * These assertions are meaningless because they always pass.
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
    $findings = visitA8Ast($src['ast'], $src['path']);
} else {
    $findings = visitA8Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A8.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA8Ast(array $ast, string $filePath): array
{
    $findings = [];

    $tautologyAssertions = [
        'assertEquals', 'assertSame', 'assertNotEquals', 'assertNotSame',
        'assertStringContainsString', 'assertStringNotContainsString',
    ];

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, $filePath, $tautologyAssertions): void {
        if (!($node instanceof \PhpParser\Node\Expr\MethodCall)) {
            return;
        }

        $name = $node->name;
        if (!($name instanceof \PhpParser\Node\Identifier)) {
            return;
        }

        $methodName = (string) $name;

        // Check method-call assertions: $this->assertEquals(1, 1)
        if (in_array($methodName, $tautologyAssertions, true) && isset($node->args[0], $node->args[1])) {
            $arg0 = $node->args[0]->value;
            $arg1 = $node->args[1]->value;
            if (isTautologyValue($arg0, $arg1)) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $node->getStartLine(),
                    'rule_id' => 'A8',
                    'severity' => 'error',
                    'message' => sprintf('%s(%s, %s) is a tautology — always %s', $methodName, exprVal($arg0), exprVal($arg1), tautologyType($methodName)),
                    'fix_hint' => 'Assert on actual system output, not hardcoded literals',
                ];
            }
        }

        // assertTrue(true) / assertFalse(false)
        if ($methodName === 'assertTrue') {
            if (isset($node->args[0])) {
                $arg = $node->args[0]->value;
                if ($arg instanceof \PhpParser\Node\Expr\ConstFetch
                    && $arg->name instanceof \PhpParser\Node\Name
                    && $arg->name->toString() === 'true') {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $node->getStartLine(),
                        'rule_id' => 'A8',
                        'severity' => 'error',
                        'message' => 'assertTrue(true) is always true — a tautology',
                        'fix_hint' => 'Assert on actual system output, not on literal true',
                    ];
                }
            }
        }
        if ($methodName === 'assertFalse') {
            if (isset($node->args[0])) {
                $arg = $node->args[0]->value;
                if ($arg instanceof \PhpParser\Node\Expr\ConstFetch
                    && $arg->name instanceof \PhpParser\Node\Name
                    && $arg->name->toString() === 'false') {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $node->getStartLine(),
                        'rule_id' => 'A8',
                        'severity' => 'error',
                        'message' => 'assertFalse(false) is always false — a tautology',
                        'fix_hint' => 'Assert on actual system output, not on literal false',
                    ];
                }
            }
        }

        // assertEmpty([]) / assertNotEmpty([...])
        if ($methodName === 'assertEmpty') {
            if (isset($node->args[0])) {
                $arg = $node->args[0]->value;
                if ($arg instanceof \PhpParser\Node\Expr\Array_ && $arg->items === []) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $node->getStartLine(),
                        'rule_id' => 'A8',
                        'severity' => 'error',
                        'message' => 'assertEmpty([]) is always true — a tautology',
                        'fix_hint' => 'Assert on actual system output, not on literal empty array',
                    ];
                }
            }
        }
        if ($methodName === 'assertNotEmpty') {
            if (isset($node->args[0])) {
                $arg = $node->args[0]->value;
                if ($arg instanceof \PhpParser\Node\Expr\Array_ && $arg->items !== []) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $node->getStartLine(),
                        'rule_id' => 'A8',
                        'severity' => 'error',
                        'message' => 'assertNotEmpty([...]) on a non-empty literal array is trivially true',
                        'fix_hint' => 'Assert on actual system output, not on literal arrays',
                    ];
                }
            }
        }

        // Function-call assertions: assertEquals(1, 1)
        if ($node instanceof \PhpParser\Node\Expr\FuncCall) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Identifier && in_array((string) $name, $tautologyAssertions, true)) {
                $args = $node->getArgs();
                if (isset($args[0], $args[1])) {
                    if (isTautologyValue($args[0]->value, $args[1]->value)) {
                        $findings[] = [
                            'file' => $filePath,
                            'line' => $node->getStartLine(),
                            'rule_id' => 'A8',
                            'severity' => 'error',
                            'message' => sprintf('%s(%s, %s) is a tautology — always %s', (string) $name, exprVal($args[0]->value), exprVal($args[1]->value), tautologyType((string) $name)),
                            'fix_hint' => 'Assert on actual system output, not hardcoded literals',
                        ];
                    }
                }
            }

            // assertEmpty([]) as function call
            if ((string) $name === 'assertEmpty' && isset($args[0])) {
                $arg = $args[0]->value;
                if ($arg instanceof \PhpParser\Node\Expr\Array_ && $arg->items === []) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $node->getStartLine(),
                        'rule_id' => 'A8',
                        'severity' => 'error',
                        'message' => 'assertEmpty([]) is always true — a tautology',
                        'fix_hint' => 'Assert on actual system output, not on literal empty array',
                    ];
                }
            }
        }
    });

    return $findings;
}

/**
 * Check if two AST expression nodes represent the same constant value.
 */
function isTautologyValue(\PhpParser\Node\Expr $a, \PhpParser\Node\Expr $b): bool
{
    return exprVal($a) === exprVal($b) && exprVal($a) !== null;
}

/**
 * Get a string representation of a literal/constant expression.
 */
function exprVal(\PhpParser\Node\Expr $node): ?string
{
    // String literal
    if ($node instanceof \PhpParser\Node\Scalar\String_) {
        return '":"' . $node->value . '"';
    }
    // Integer literal
    if ($node instanceof \PhpParser\Node\Scalar\LNumber) {
        return (string) $node->value;
    }
    // Float literal
    if ($node instanceof \PhpParser\Node\Scalar\DNumber) {
        return (string) $node->value;
    }
    // Boolean true/false
    if ($node instanceof \PhpParser\Node\Expr\ConstFetch
        && $node->name instanceof \PhpParser\Node\Name) {
        return $node->name->toString();
    }
    // Null
    if ($node instanceof \PhpParser\Node\Expr\ConstFetch
        && $node->name instanceof \PhpParser\Node\Name
        && $node->name->toString() === 'null') {
        return 'null';
    }
    // Empty array
    if ($node instanceof \PhpParser\Node\Expr\Array_ && $node->items === []) {
        return '[]';
    }
    // Non-empty array
    if ($node instanceof \PhpParser\Node\Expr\Array_ && $node->items !== []) {
        return '[...]';
    }

    return null;
}

/**
 * Describe what kind of tautology this assertion is.
 */
function tautologyType(string $method): string
{
    if (str_starts_with($method, 'assertNot')) {
        return 'always false';
    }
    return 'always true';
}

/**
 * Regex-based fallback for A8.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA8Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    foreach ($lines as $i => $line) {
        // assertEquals(X, X) / assertSame(X, X) where X is a literal
        if (preg_match('/->(assertEquals|assertSame)\s*\(\s*(\d+)\s*,\s*\2\s*\)/', $line, $m)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A8',
                'severity' => 'error',
                'message' => sprintf('%s(%s, %s) is a tautology (regex fallback)', $m[1], $m[2], $m[2]),
                'fix_hint' => 'Assert on actual system output, not hardcoded literals',
            ];
        }
        if (preg_match('/->(assertEquals|assertSame)\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*[\'"]\2[\'"]\s*\)/', $line, $m)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A8',
                'severity' => 'error',
                'message' => sprintf('%s("%s", "%s") is a tautology (regex fallback)', $m[1], $m[2], $m[2]),
                'fix_hint' => 'Assert on actual system output, not hardcoded literals',
            ];
        }
        // assertTrue(true) / assertFalse(false)
        if (preg_match('/->assertTrue\s*\(\s*true\s*\)/', $line)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A8',
                'severity' => 'error',
                'message' => 'assertTrue(true) is a tautology (regex fallback)',
                'fix_hint' => 'Assert on actual system output, not on literal true',
            ];
        }
        if (preg_match('/->assertFalse\s*\(\s*false\s*\)/', $line)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A8',
                'severity' => 'error',
                'message' => 'assertFalse(false) is a tautology (regex fallback)',
                'fix_hint' => 'Assert on actual system output, not on literal false',
            ];
        }
        // assertEmpty([])
        if (preg_match('/->assertEmpty\s*\(\s*\[\s*\]\s*\)/', $line)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A8',
                'severity' => 'error',
                'message' => 'assertEmpty([]) is a tautology (regex fallback)',
                'fix_hint' => 'Assert on actual system output, not on literal empty array',
            ];
        }
    }

    return $findings;
}
