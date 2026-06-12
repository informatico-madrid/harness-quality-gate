<?php
/**
 * God Class visitor — detects classes with excessive lines of code.
 *
 * Rule: GOD-001  "Class exceeds %d lines of code"
 * Threshold: 300 lines (configurable).
 *
 * When nikic/php-parser is installed it does a proper AST walk.
 * Otherwise it falls back to a brace-counting heuristic.
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
    $findings = visitGodClass($ast ?? [], $filePath);
} else {
    // ---------------------------------------------------------------
    // 2.  Regex fallback
    // ---------------------------------------------------------------
    $findings = regexFallback($filePath, $content, 300);
}

echo json_encode($findings, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

// -----------------------------------------------------------------------
// nikic/php-parser AST visitor (procedural — returns list of arrays)
// -----------------------------------------------------------------------

/** @param list<object> $ast  * @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function visitGodClass(array $ast, string $filePath): array
{
    $findings = [];
    walk($ast, $filePath, static function (\PhpParser\Node $node) use (&$findings, $filePath): void {
        if ($node instanceof \PhpParser\Node\Stmt\Class_) {
            $startLine = $node->getStartLine();
            $endLine = $node->getEndLine();
            $lineCount = $endLine - $startLine + 1;
            $className = className($node);

            if ($lineCount > 300) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $startLine,
                    'rule_id' => 'GOD-001',
                    'severity' => 'critical',
                    'message' => sprintf('Class "%s" exceeds 300 lines of code (%d total)', $className, $lineCount),
                    'fix_hint' => 'Extract responsibilities into smaller classes',
                ];
            }

            $methodCount = 0;
            foreach ($node->getStmts() as $stmt) {
                if ($stmt instanceof \PhpParser\Node\Stmt\ClassMethod) {
                    $methodCount++;
                }
            }
            if ($methodCount > 15) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $startLine,
                    'rule_id' => 'GOD-002',
                    'severity' => 'major',
                    'message' => sprintf('Class "%s" has %d methods (exceeds 15)', $className, $methodCount),
                    'fix_hint' => 'Extract groups of related methods into separate classes',
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

/** Extract the fully-qualified class name from a Class_ node. */
function className(\PhpParser\Node\Stmt\Class_ $node): string
{
    $n = $node->namespacedName;
    return $n !== null ? $n->toString() : (string) $node->name;
}

// -----------------------------------------------------------------------
// Regex fallback — no nikic/php-parser required
// -----------------------------------------------------------------------

/** @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function regexFallback(string $filePath, string $content, int $threshold): array
{
    $findings = [];
    $lines = explode("\n", $content);
    $currentClass = '';
    $classStart = 0;
    $braceDepth = 0;
    $methodCount = 0;

    foreach ($lines as $i => $line) {
        // Detect class declaration
        if (preg_match('/^\s*(?:abstract|final)?\s*class\s+(\w+)/', $line, $m)) {
            if ($currentClass !== '' && $methodCount > 15) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $classStart + 1,
                    'rule_id' => 'GOD-002',
                    'severity' => 'major',
                    'message' => sprintf('Class "%s" has %d methods (exceeds 15)', $currentClass, $methodCount),
                    'fix_hint' => 'Extract groups of related methods into separate classes',
                ];
            }
            if ($currentClass !== '' && ($i - $classStart) > $threshold) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $classStart + 1,
                    'rule_id' => 'GOD-001',
                    'severity' => 'critical',
                    'message' => sprintf('Class "%s" exceeds %d lines of code (%d total)', $currentClass, $threshold, $i - $classStart),
                    'fix_hint' => 'Extract responsibilities into smaller classes',
                ];
            }
            $currentClass = $m[1];
            $classStart = $i;
            $braceDepth = 0;
            $methodCount = 0;
        }

        // Count opening braces for class scope
        $open = substr_count($line, '{');
        $close = substr_count($line, '}');
        $braceDepth += $open - $close;

        // Count method declarations inside the class
        if ($braceDepth > 0 && preg_match('/function\s+\w+/', $line)) {
            $methodCount++;
        }

        // Flush last class at EOF
        if ($braceDepth <= 0 && $currentClass !== '') {
            if ($methodCount > 15) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $classStart + 1,
                    'rule_id' => 'GOD-002',
                    'severity' => 'major',
                    'message' => sprintf('Class "%s" has %d methods (exceeds 15)', $currentClass, $methodCount),
                    'fix_hint' => 'Extract groups of related methods into separate classes',
                ];
            }
            $totalLines = $i - $classStart + 1;
            if ($totalLines > $threshold) {
                $findings[] = [
                    'file' => $filePath,
                    'line' => $classStart + 1,
                    'rule_id' => 'GOD-001',
                    'severity' => 'critical',
                    'message' => sprintf('Class "%s" exceeds %d lines of code (%d total)', $currentClass, $threshold, $totalLines),
                    'fix_hint' => 'Extract responsibilities into smaller classes',
                ];
            }
            $currentClass = '';
        }
    }

    return $findings;
}
