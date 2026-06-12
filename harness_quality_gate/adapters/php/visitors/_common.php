<?php
/**
 * Shared helpers for weak-test PHP visitors.
 *
 * Provides:
 *  - common_parse_file()    — parse a PHP file into AST (or raw content fallback)
 *  - common_walk_ast()      — recursive AST walker for nikic/php-parser nodes
 *  - common_emit()          — print findings as JSON to stdout and exit
 */
declare(strict_types=1);

/**
 * Parse a PHP file and return ['ast' => ..., 'content' => ..., 'path' => ...].
 *
 * When nikic/php-parser is present, *ast* holds the parsed AST array.
 * Otherwise *ast* is null and *content* holds the raw file text.
 *
 * @return array{ast: list<object>|null, content: string, path: string}
 */
function common_parse_file(string $filePath): array
{
    $content = file_get_contents($filePath);
    if ($content === false) {
        return ['ast' => null, 'content' => '', 'path' => $filePath];
    }

    $ast = null;

    // Try nikic/php-parser
    $autoloader = __DIR__ . '/vendor/autoload.php';
    if (is_file($autoloader)) {
        require_once $autoloader;
    }

    if (class_exists(\PhpParser\ParserFactory::class)) {
        $parser = (new \PhpParser\ParserFactory())->createForNewestSupportedVersion();
        try {
            $ast = $parser->parse($content);
        } catch (\PhpParser\Error $e) {
            $ast = null;
        }
    }

    return ['ast' => $ast, 'content' => $content, 'path' => $filePath];
}

/**
 * Recursively walk a nikic/PHP-Parser AST and invoke $callback on each node.
 *
 * @param list<object> $nodes
 */
function common_walk_ast(array $nodes, callable $callback): void
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
            common_walk_ast($subNodes, $callback);
        }
    }
}

/**
 * Emit findings as JSON array on stdout and exit.
 *
 * @param list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> $findings
 */
function common_emit(array $findings): void
{
    echo json_encode($findings, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit(0);
}
