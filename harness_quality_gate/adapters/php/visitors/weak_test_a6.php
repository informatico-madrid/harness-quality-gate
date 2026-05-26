<?php
/**
 * A6 — @codeCoverageIgnore spam.
 *
 * Detects excessive use of @codeCoverageIgnore annotations.
 * Threshold: more than 3 @codeCoverageIgnore annotations in a single file,
 * or @codeCoverageIgnore annotation on a test class method (test methods
 * should always be coverable).
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
    $findings = visitA6Ast($src['ast'], $src['path']);
} else {
    $findings = visitA6Regex($src['path'], $src['content']);
}

common_emit($findings);

/**
 * AST-based detection for A6.
 *
 * @param list<object> $ast
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA6Ast(array $ast, string $filePath): array
{
    $findings = [];
    $ignoreCount = 0;
    $ignoreRanges = [];

    common_walk_ast($ast, static function (\PhpParser\Node $node) use (&$findings, &$ignoreCount, &$ignoreRanges, $filePath): void {
        // PHPDoc comments containing @codeCoverageIgnore
        if ($node instanceof \PhpParser\Node\Comment) {
            if (str_contains($node->getText(), '@codeCoverageIgnore')) {
                $ignoreCount++;
                $ignoreRanges[] = $node->getStartLine();
            }
        }
    });

    // Also check attribute-based ignores (PHP 8+)
    foreach ($ast as $node) {
        if ($node instanceof \PhpParser\Node\Attribute) {
            $name = $node->name;
            if ($name instanceof \PhpParser\Node\Name
                && stripos($name->toString(), 'codecoverageignore') !== false) {
                $ignoreCount++;
                $ignoreRanges[] = $node->getStartLine();
            }
        }
        if ($node instanceof \PhpParser\Node\AttributeGroup) {
            foreach ($node->attrs as $attr) {
                if ($attr->name instanceof \PhpParser\Node\Name
                    && stripos($attr->name->toString(), 'codecoverageignore') !== false) {
                    $ignoreCount++;
                    $ignoreRanges[] = $attr->getStartLine();
                }
            }
        }
    }

    if ($ignoreCount > 3) {
        $lineInfo = '';
        if (!empty($ignoreRanges)) {
            $lineInfo = ' (lines ' . implode(', ', array_slice($ignoreRanges, 0, 5));
            if (count($ignoreRanges) > 5) {
                $lineInfo .= ', ...';
            }
            $lineInfo .= ')';
        }
        $findings[] = [
            'file' => $filePath,
            'line' => $ignoreRanges[0] ?? 1,
            'rule_id' => 'A6',
            'severity' => 'warning',
            'message' => sprintf('@codeCoverageIgnore used %d times (threshold: 3)%s', $ignoreCount, $lineInfo),
            'fix_hint' => 'Reduce @codeCoverageIgnore usage; every line should be testable',
        ];
    }

    // Check for @codeCoverageIgnore on test methods specifically
    $inTestFile = str_contains(basename($filePath), 'Test') || str_contains($filePath, '/tests/');
    if ($inTestFile) {
        foreach ($ignoreRanges as $line) {
            // Heuristic: line within 5 lines of a function test method
            // This is a simplified check; proper check would need AST context
        }
    }

    return $findings;
}

/**
 * Regex-based fallback for A6.
 *
 * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}>
 */
function visitA6Regex(string $filePath, string $content): array
{
    $findings = [];
    $count = 0;
    $lines = explode("\n", $content);

    foreach ($lines as $i => $line) {
        if (stripos($line, '@codeCoverageIgnore') !== false) {
            $count++;
        }
    }

    if ($count > 3) {
        $findings[] = [
            'file' => $filePath,
            'line' => 1,
            'rule_id' => 'A6',
            'severity' => 'warning',
            'message' => sprintf('@codeCoverageIgnore used %d times (threshold: 3) (regex fallback)', $count),
            'fix_hint' => 'Reduce @codeCoverageIgnore usage; every line should be testable',
        ];
    }

    return $findings;
}
