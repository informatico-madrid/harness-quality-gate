<?php
/**
 * Long Parameter List visitor — detects methods with too many parameters.
 *
 * Rule: LPL-001  "Method has N parameters (exceeds threshold of %d)"
 * Threshold: 5 parameters.
 *
 * Falls back to regex-based heuristic when nikic/php-parser is unavailable.
 */
declare(strict_types=1);

// -----------------------------------------------------------------------
// 0.  Parse CLI arguments
// -----------------------------------------------------------------------

$filePath = $argv[1] ?? null;
if ($filePath === null || !is_file($filePath)) {
    echo json_encode([]);
    exit(0);
}

$content = file_get_contents($filePath);
if ($content === false) {
    echo json_encode([]);
    exit(0);
}

// -----------------------------------------------------------------------
// 1.  Try nikic/php-parser
// -----------------------------------------------------------------------

$autoloader = __DIR__ . '/vendor/autoload.php';
if (is_file($autoloader)) {
    require_once $autoloader;
}

$hasParser = class_exists(\PhpParser\ParserFactory::class);
$findings = [];

if ($hasParser) {
    $parser = (new \PhpParser\ParserFactory())->createForNewestSupportedVersion();
    $ast = $parser->parse($content);
    $findings = visitLongParamList($ast ?? [], $filePath, 5);
} else {
    $findings = regexFallback($filePath, $content, 5);
}

echo json_encode($findings, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

// -----------------------------------------------------------------------
// nikic/PHP-Parser AST visitor (procedural)
// -----------------------------------------------------------------------

/** @param list<object> $ast  * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function visitLongParamList(array $ast, string $filePath, int $threshold): array
{
    $findings = [];

    walk($ast, $filePath, static function (\PhpParser\Node $node) use (&$findings, $filePath, $threshold): void {
        if ($node instanceof \PhpParser\Node\Stmt\ClassMethod) {
            $paramCount = count($node->getParams());
            if ($paramCount > $threshold) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $node->getStartLine(),
                    'rule_id' => 'LPL-001',
                    'severity' => 'minor',
                    'message' => sprintf('Method "%s" has %d parameters (exceeds threshold of %d)', (string) $node->name, $paramCount, $threshold),
                    'fix_hint' => 'Extract parameters into a dedicated value object or data class',
                ];
            }
        }
    });

    return $findings;
}

/** Recursively walk a nikic/PHP-Parser AST. */
function walk(array $nodes, string $filePath, callable $callback): void
{
    foreach ($nodes as $node) {
        if (!($node instanceof \PhpParser\Node)) {
            continue;
        }
        $callback($node);
        $subNodes = getSubNodes($node);
        if (!empty($subNodes)) {
            walk($subNodes, $filePath, $callback);
        }
    }
}

/** Extract child nodes from a PHP-Parser node. */
function getSubNodes(\PhpParser\Node $node): array
{
    $subNodes = [];
    foreach ($node->getSubNodeNames() as $child) {
        $val = $node->$child;
        if (is_iterable($val)) {
            foreach ($val as $item) {
                if ($item instanceof \PhpParser\Node) {
                    $subNodes[] = $item;
                }
            }
        }
    }
    return $subNodes;
}

// -----------------------------------------------------------------------
// Regex fallback
// -----------------------------------------------------------------------

/** @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function regexFallback(string $filePath, string $content, int $threshold): array
{
    $findings = [];
    $lines = explode("\n", $content);
    $currentMethod = '';
    $currentLine = 0;

    foreach ($lines as $i => $line) {
        // Match method signature
        if (preg_match('/function\s+(\w+)\s*\(/', $line, $m)) {
            $currentMethod = $m[1];
            $currentLine = $i;
        }

        if ($currentMethod && preg_match('/function\s+\w+\s*\(([^)]*)\)/', $line, $m)) {
            $params = $m[1];
            if (trim($params) !== '') {
                // Count parameters by splitting on comma, accounting for multi-line
                $paramList = preg_split('/,\s*(?![^()]*\))/', $params);
                $paramCount = count(array_filter(array_map('trim', $paramList)));

                if ($paramCount > $threshold) {
                    $findings[] = [
                        'file' => $filePath,
                        'line' => $currentLine + 1,
                        'rule_id' => 'LPL-001',
                        'severity' => 'minor',
                        'message' => sprintf('Method "%s" has %d parameters (exceeds threshold of %d)', $currentMethod, $paramCount, $threshold),
                        'fix_hint' => 'Extract parameters into a dedicated value object or data class',
                    ];
                }
            }
            $currentMethod = '';
        }
    }

    return $findings;
}
