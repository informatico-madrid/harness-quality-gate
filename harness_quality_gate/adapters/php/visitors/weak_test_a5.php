<?php
/**
 * A5 — markTestSkipped / markTestIncomplete abuse.
 *
 * Detects test methods that call:
 *  - $this->markTestSkipped()
 *  - $this->markTestIncomplete()
 *
 * These are anti-patterns — the test should be removed or fixed rather
 * than perpetually skipped/incomplete.
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
    $findings = visitA5Ast($src['ast'], $src['path']);
} else {
    $findings = visitA5Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A5.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA5Ast(array $ast, string $filePath): array
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

        if ($methodName === 'markTestSkipped') {
            $msg = '';
            if ($node->args !== []) {
                $firstArg = $node->args[0]->value;
                if ($firstArg instanceof \PhpParser\Node\Scalar\String_) {
                    $msg = ' — ' . $firstArg->value;
                }
            }
            $findings[] = [
                'file' => $filePath,
                'line' => $node->getStartLine(),
                'rule_id' => 'A5',
                'severity' => 'warning',
                'message' => "markTestSkipped() called in test code$msg",
                'fix_hint' => 'Fix or remove the test rather than skipping it permanently',
            ];
        }

        if ($methodName === 'markTestIncomplete') {
            $msg = '';
            if ($node->args !== []) {
                $firstArg = $node->args[0]->value;
                if ($firstArg instanceof \PhpParser\Node\Scalar\String_) {
                    $msg = ' — ' . $firstArg->value;
                }
            }
            $findings[] = [
                'file' => $filePath,
                'line' => $node->getStartLine(),
                'rule_id' => 'A5',
                'severity' => 'warning',
                'message' => "markTestIncomplete() called in test code$msg",
                'fix_hint' => 'Complete the test implementation rather than marking it incomplete',
            ];
        }
    });

    return $findings;
}

/**
 * Regex-based fallback for A5.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA5Regex(string $filePath, string $content): array
{
    $findings = [];
    $lines = explode("\n", $content);

    foreach ($lines as $i => $line) {
        if (preg_match("/->markTestSkipped\\s*\\(\\s*[\\'\\x22]([^\\'\\x22]*)[\\'\\x22]?\\s*\\)/", $line, $m)) {
            $msg = $m[1] !== '' ? ' — ' . $m[1] : '';
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A5',
                'severity' => 'warning',
                'message' => "markTestSkipped() called in test code$msg (regex fallback)",
                'fix_hint' => 'Fix or remove the test rather than skipping it permanently',
            ];
        } elseif (preg_match("/->markTestIncomplete\\s*\\(\\s*[\\'\\x22]([^\\'\\x22]*)[\\'\\x22]?\\s*\\)/", $line, $m)) {
            $msg = $m[1] !== '' ? ' — ' . $m[1] : '';
            $findings[] = [
                'file' => $filePath,
                'line' => $i + 1,
                'rule_id' => 'A5',
                'severity' => 'warning',
                'message' => "markTestIncomplete() called in test code$msg (regex fallback)",
                'fix_hint' => 'Complete the test implementation rather than marking it incomplete',
            ];
        }
    }

    return $findings;
}
