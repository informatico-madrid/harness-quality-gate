<?php
/**
 * A4 — Overly-broad expectException.
 *
 * Detects calls to:
 *  - $this->expectException(\Throwable::class)
 *  - $this->expectException(\Exception::class)
 *  - $this->expectException(\RuntimeException::class)
 *  - $this->expectExceptionMessage('')  (empty expected message)
 *  - $this->expectExceptionMessageMatches('.*')  (wildcard regex)
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
    $findings = visitA4Ast($src['ast'], $src['path']);
} else {
    $findings = visitA4Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A4.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA4Ast(array $ast, string $filePath): array
{
    $findings = [];

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, $filePath): void {
        if (!($node instanceof \PhpParser\Node\Expr\MethodCall)) {
            return;
        }

        $name = $node->name;
        if (!($name instanceof \PhpParser\Node\Identifier)) {
            return;
        }

        $methodName = (string) $name;

        // Check expectException with broad exception types
        if ($methodName === 'expectException') {
            $firstArg = $node->args[0] ?? null;
            if ($firstArg instanceof \PhpParser\Node\Arg) {
                $argVal = $firstArg->value;
                // Throwable::class or Exception::class
                if ($argVal instanceof \PhpParser\Node\Expr\ClassConstFetch
                    && $argVal->class instanceof \PhpParser\Node\Name) {
                    $className = $argVal->class->toString();
                    if (in_array($className, ['Throwable', 'Exception', 'RuntimeException', 'Error'], true)) {
                        $findings[] = [
                            'file' => $filePath,
                            'line' => $node->getStartLine(),
                            'rule_id' => 'A4',
                            'severity' => 'warning',
                            'message' => sprintf(
                                'expectException(%s::class) is too broad — catches all %s',
                                $className,
                                $className
                            ),
                            'fix_hint' => 'Expect the specific exception type you actually expect',
                        ];
                    }
                }
            }
        }

        // expectExceptionMessage with empty string
        if ($methodName === 'expectExceptionMessage') {
            $firstArg = $node->args[0] ?? null;
            if ($firstArg instanceof \PhpParser\Node\Arg
                && $firstArg->value instanceof \PhpParser\Node\Scalar\String_
                && $firstArg->value->value === '') {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $node->getStartLine(),
                    'rule_id' => 'A4',
                    'severity' => 'warning',
                    'message' => 'expectExceptionMessage("") sets an empty expected message',
                    'fix_hint' => 'Provide the specific expected exception message or remove this call',
                ];
            }
        }

        // expectExceptionMessageMatches with wildcard
        if ($methodName === 'expectExceptionMessageMatches') {
            $firstArg = $node->args[0] ?? null;
            if ($firstArg instanceof \PhpParser\Node\Arg
                && $firstArg->value instanceof \PhpParser\Node\Scalar\String_) {
                $pattern = $firstArg->value->value;
                if (preg_match('/^\(\/\.\*\/\)$|^\.\*$|^\(\/.*\/\)$/', $pattern)) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $node->getStartLine(),
                        'rule_id' => 'A4',
                        'severity' => 'warning',
                        'message' => 'expectExceptionMessageMatches() uses a wildcard pattern',
                        'fix_hint' => 'Match the specific expected message pattern',
                    ];
                }
            }
        }
    });

    return $findings;
}

/**
 * Regex-based fallback for A4.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA4Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    foreach ($lines as $i => $line) {
        // Broad exception types
        if (preg_match('/->expectException\s*\(\s*[\\\'"]*(Throwable|Exception|RuntimeException|Error)[\\\'"]*::class\s*\)/', $line, $m)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A4',
                'severity' => 'warning',
                'message' => sprintf('expectException(%s::class) is too broad (regex fallback)', $m[1]),
                'fix_hint' => 'Expect the specific exception type you actually expect',
            ];
        }

        // Empty expected message
        if (preg_match('/->expectExceptionMessage\s*\(\s*[\'"][\'"]\s*\)/', $line)) {
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A4',
                'severity' => 'warning',
                'message' => 'expectExceptionMessage("") is empty (regex fallback)',
                'fix_hint' => 'Provide the specific expected exception message',
            ];
        }
    }

    return $findings;
}
