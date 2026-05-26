<?php
/**
 * Feature Envy visitor — detects methods that access another class's
 * properties/fields more than their own.
 *
 * Rule: FE-001  "Method accesses foreign object N times"
 * Threshold: 3 foreign accesses.
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
    $findings = visitFeatureEnvy($ast ?? [], $filePath);
} else {
    $findings = regexFallback($filePath, $content, 3);
}

echo json_encode($findings, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

// -----------------------------------------------------------------------
// nikic/PHP-Parser AST visitor (procedural)
// -----------------------------------------------------------------------

/** @param list<object> $ast  * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function visitFeatureEnvy(array $ast, string $filePath): array
{
    $findings = [];
    $methodForeignAccesses = 0;
    $currentMethod = '';
    $currentMethodLine = 0;
    $inMethod = false;

    walk($ast, $filePath, static function (\PhpParser\Node $node) use (&$findings, &$methodForeignAccesses, &$currentMethod, &$currentMethodLine, &$inMethod, $filePath): void {
        if ($node instanceof \PhpParser\Node\Stmt\ClassMethod) {
            // Flush previous method
            if ($inMethod && $methodForeignAccesses > 3) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $currentMethodLine,
                    'rule_id' => 'FE-001',
                    'severity' => 'major',
                    'message' => sprintf('Method "%s" has %d foreign accesses (exceeds 3)', $currentMethod, $methodForeignAccesses),
                    'fix_hint' => 'Move method to the class whose properties it accesses most',
                ];
            }
            $inMethod = true;
            $currentMethod = (string) $node->name;
            $currentMethodLine = $node->getStartLine();
            $methodForeignAccesses = 0;
        }

        if ($inMethod) {
            if ($node instanceof \PhpParser\Node\Expr\MethodCall) {
                $var = $node->var;
                if (!($var instanceof \PhpParser\Node\Expr\Variable) || $var->name !== 'this') {
                    $methodForeignAccesses++;
                }
            } elseif ($node instanceof \PhpParser\Node\Expr\PropertyFetch) {
                $var = $node->var;
                if (!($var instanceof \PhpParser\Node\Expr\Variable) || $var->name !== 'this') {
                    $methodForeignAccesses++;
                }
            }
        }
    });

    // Flush last method
    if ($inMethod && $methodForeignAccesses > 3) {
        $findings[] = [
            'file' => $filePath,
            'line' => $currentMethodLine,
            'rule_id' => 'FE-001',
            'severity' => 'major',
            'message' => sprintf('Method "%s" has %d foreign accesses (exceeds 3)', $currentMethod, $methodForeignAccesses),
            'fix_hint' => 'Move method to the class whose properties it accesses most',
        ];
    }

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
        $children = $node->getSubNodeNames();
        $subNodes = [];
        foreach ($children as $child) {
            $val = $node->$child;
            if (is_iterable($val)) {
                foreach ($val as $item) {
                    if ($item instanceof \PhpParser\Node) {
                        $subNodes[] = $item;
                    }
                }
            }
        }
        if (!empty($subNodes)) {
            walk($subNodes, $filePath, $callback);
        }
    }
}

// -----------------------------------------------------------------------
// Regex fallback
// -----------------------------------------------------------------------

/** @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function regexFallback(string $filePath, string $content, int $threshold): array
{
    $findings = [];
    $lines = explode("\n", $content);

    $inMethod = false;
    $methodName = '';
    $foreignAccesses = 0;
    $methodStart = 0;

    foreach ($lines as $i => $line) {
        if (preg_match('/function\s+(\w+)\s*\(/', $line, $m)) {
            if ($inMethod && $foreignAccesses > $threshold) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $methodStart + 1,
                    'rule_id' => 'FE-001',
                    'severity' => 'major',
                    'message' => sprintf('Method "%s" has %d foreign accesses (exceeds %d)', $methodName, $foreignAccesses, $threshold),
                    'fix_hint' => 'Move method to the class whose properties it accesses most',
                ];
            }
            $inMethod = true;
            $methodName = $m[1];
            $foreignAccesses = 0;
            $methodStart = $i;
        }

        if ($inMethod) {
            $matches = [];
            preg_match_all('/(?<!\$this->)\$(\w+)\s*->/', $line, $matches);
            $foreignAccesses += count($matches[0]);
        }
    }

    // Flush last method
    if ($inMethod && $foreignAccesses > $threshold) {
        $findings[] = [
            'file' => $filePath,
            'line' => $methodStart + 1,
            'rule_id' => 'FE-001',
            'severity' => 'major',
            'message' => sprintf('Method "%s" has %d foreign accesses (exceeds %d)', $methodName, $foreignAccesses, $threshold),
            'fix_hint' => 'Move method to the class whose properties it accesses most',
        ];
    }

    return $findings;
}
