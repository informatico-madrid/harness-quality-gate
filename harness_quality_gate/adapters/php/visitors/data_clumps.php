<?php
/**
 * Data Clumps visitor — detects groups of 2+ parameters that appear together
 * in multiple method signatures.
 *
 * Rule: DC-001  "Parameters %s co-occur in N methods"
 * Threshold: 2 co-occurrences for 2+ params.
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
// 1.  Try nikic/php-parser (skipped — regex fallback used always)
// -----------------------------------------------------------------------
// For data clumps detection we use a simpler regex approach that works
// without nikic/php-parser.
// -----------------------------------------------------------------------

$findings = regexFallback($filePath, $content, 2);
echo json_encode($findings, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

// -----------------------------------------------------------------------
// Regex fallback
// -----------------------------------------------------------------------

/** @return list<array{file:string,line:int,rule_id:string,severity:string,message:string,fix_hint:string}> */
function regexFallback(string $filePath, string $content, int $threshold): array
{
    $findings = [];
    $lines = explode("\n", $content);
    $paramMap = [];

    foreach ($lines as $line) {
        // Match method signatures: function name( ... )
        if (preg_match('/function\s+(\w+)\s*\(([^)]*)\)/', $line, $m)) {
            $params = array_filter(array_map('trim', explode(',', $m[2])));
            $paramNames = [];
            foreach ($params as $p) {
                if (preg_match('/\$(\w+)/', $p, $pm)) {
                    $paramNames[] = $pm[1];
                }
            }

            // Generate all 2-combinations of params
            for ($i = 0; $i < count($paramNames); $i++) {
                for ($j = $i + 1; $j < count($paramNames); $j++) {
                    $pair = implode(',', [$paramNames[$i], $paramNames[$j]]);
                    if (!isset($paramMap[$pair])) {
                        $paramMap[$pair] = 0;
                    }
                    $paramMap[$pair]++;
                }
            }
        }
    }

    foreach ($paramMap as $pair => $count) {
        if ($count >= $threshold) {
            $params = explode(',', $pair);
            $findings[] = [
                'file' => $filePath,
                'line' => 1,
                'rule_id' => 'DC-001',
                'severity' => 'minor',
                'message' => sprintf('Parameters %s co-occur in %d methods (threshold: %d)', implode(' & ', $params), $count, $threshold),
                'fix_hint' => 'Extract parameters into a dedicated value object or data class',
            ];
        }
    }

    return $findings;
}
