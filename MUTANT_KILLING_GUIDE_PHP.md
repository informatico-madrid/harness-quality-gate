# Guía para matar mutantes al 100% en PHP (Infection)

Manual operativo para los subagentes que cierran mutantes escapados de
**Infection** en repos PHP validados por esta skill. NO es una traducción de
la guía Python ([MUTANT_KILLING_GUIDE.md](MUTANT_KILLING_GUIDE.md)): PHP tiene
su propio motor de mutación (Infection ≥ 0.29), sus propios mutadores, sus
propias trampas (`assertEquals` débil, visibilidad, casts con `strict_types`)
y un gate distinto.

---

## 0. El gate PHP de esta skill (lo que tienes que pasar)

A diferencia de Python (mutación en L3B con mutmut), en PHP la mutación corre
en **L1** junto a tests y coverage, con Infection y umbral duro (FR-13/FR-14):

| Condición de fallo | Regla |
|---|---|
| `MSI < 100` | Gate duro `--min-msi=100` |
| `Covered MSI < 100` | Gate duro `--min-covered-msi=100` |
| `escaped > 0` | Cualquier mutante escapado suspende |
| `timed_out > 0` | **Timeouts cuentan como escapados** (`timeoutsAsEscaped`, `maxTimeouts=0`) |
| `errors` | El parser de esta skill los cuenta como `escaped` (fatal error en el mutante ≠ matado limpiamente) |

Consecuencias prácticas:

1. **Covered MSI = 100 implica que `not covered` también te bloquea** vía MSI
   global: una línea mutable sin cobertura es un mutante `uncovered` que baja
   el MSI. Primero cobertura completa, luego matar.
2. **No existe "85% es suficiente" aquí.** El objetivo es 0 escapados.
3. Pest sin `pest-plugin-mutate` → la mutación se marca `mutation_skipped`
   (TD-6). Solución: `composer require --dev pestphp/pest-plugin-mutate`.
4. Driver de cobertura: **PCOV** (preferido, rápido) o Xdebug. Sin driver,
   Infection no puede ni empezar ("0 covered mutants" / infra error).

---

## 1. Bucle de trabajo por mutante escapado

```bash
# 1. Run completo con log detallado (el harness ya pasa --min-msi=100)
vendor/bin/infection --threads=max --show-mutations --logger-text=infection.log

# 2. Leer los escapados: infection.log lista cada mutante con archivo:línea,
#    el mutador aplicado y el diff exacto
grep -A 12 "Escaped mutants" infection.log | head -60

# 3. Iterar SOLO sobre el archivo afectado (mucho más rápido)
vendor/bin/infection --threads=max --filter=src/Invoice/TaxCalculator.php --show-mutations

# 4. Escribir/reforzar el test y verificar que pasa con el código original
vendor/bin/phpunit --filter TaxCalculatorTest      # o: vendor/bin/pest --filter=...

# 5. Re-lanzar Infection sobre el archivo hasta 0 escapados
```

Trucos de alcance:

- `--filter=path/File.php` — un solo archivo (tu herramienta principal).
- `--mutators=ConditionalBoundary,Coalesce` — re-ejecutar solo los mutadores
  que se te resisten.
- `--git-diff-lines --git-diff-base=main` — solo líneas tocadas en la rama.

**Regla del test nuevo** (idéntica a Python): el test debe (a) pasar en verde
con el código original y (b) fallar con el mutante. Si Infection sigue
reportando el escapado tras tu test, el test no ejecuta esa rama o la asersión
es débil (ver §3).

---

## 2. Qué muta Infection (tabla de mutadores → cómo matarlos)

Infection trabaja sobre el AST con ~100 mutadores. Los que importan, agrupados:

| Grupo | Ejemplo de mutación | Qué necesita el test |
|---|---|---|
| Aritmética | `+` ↔ `-`, `*` ↔ `/`, `%` → `*`, `**`, `+=` → `-=` | Valores asimétricos (3 y 5, nunca 0/1/2) y `assertSame` del resultado exacto |
| Frontera condicional | `>` ↔ `>=`, `<` ↔ `<=` | Input EXACTAMENTE en el límite (§4.2) |
| Negación condicional | `==` ↔ `!=`, `===` ↔ `!==`, `instanceof` invertido | Caso positivo Y negativo |
| Booleanos | `&&` ↔ `\|\|`, `true` ↔ `false`, `!` eliminado | Tabla de verdad mínima: cada operando decide solo |
| Enteros | `IncrementInteger`/`DecrementInteger`: `n` → `n±1`; `0` → `1` | `assertSame` del valor exacto donde se usa |
| Valores de retorno | `return $this` → `return null`; `new X()` → `null`; negación de int/float; array → primer item | Asersión del objeto devuelto (encadenamiento fluido, identidad) |
| Eliminación | `MethodCallRemoval`, `FunctionCallRemoval`, `ArrayItemRemoval`, `CloneRemoval`, `Throw_` eliminado | Mock con `expects($this->once())` / `assertSame` del array completo / `expectException` |
| Bucles | `Foreach_` itera array vacío; `While_`/`For_` con condición `false`; `break` ↔ `continue` | ≥2 elementos con efectos observables por elemento; contar invocaciones |
| Unwrap | `UnwrapArrayMap`, `UnwrapStrToLower`, `UnwrapTrim`, `UnwrapArrayFilter`… (la llamada se sustituye por su argumento) | Input donde la función SÍ transforma: mayúsculas para `strtolower`, espacios para `trim`, elementos filtrables para `array_filter` |
| Casts | `(int)`, `(string)`, `(array)`, `(bool)` eliminados | Input del "tipo equivocado" que el cast normaliza (p. ej. `"5"` para `(int)`) |
| Coalesce | `$a ?? $b` → `$b ?? $a`; `??=` mutado | Test con null Y con valor presente |
| Concatenación | `Concat` invierte operandos; `ConcatOperandRemoval` | `assertSame` del string COMPLETO |
| Regex | `PregQuote` unwrap, `PregMatchMatches` | Inputs que matchean, que no matchean, y captura de grupos |
| Visibilidad | `public` → `protected`, `protected` → `private` | Ver §5.V — es feedback de diseño, no solo de tests |
| Ternario / Match | operandos invertidos, `MatchArmRemoval` | Un test por brazo del match / ternario |
| Yield | `YieldValue` mutado | `iterator_to_array()` + `assertSame` de la lista completa |

---

## 3. Las 3 trampas PHP que generan el 80% de los escapados

### T1. `assertEquals` es comparación débil (`==`) — usa SIEMPRE `assertSame`

La trampa nº 1 de PHP, sin equivalente en Python:

```php
$this->assertEquals(1, $result);    // PASA con $result = "1", 1.0, true  ← mutantes de cast/tipo SOBREVIVEN
$this->assertSame(1, $result);      // exige int 1 — mata casts, IncrementInteger según tipo, etc.
```

`assertEquals` deja vivos: eliminación de casts, mutaciones `===` ↔ `==`,
`ReturnValue` que cambia tipo, `0` ↔ `false` ↔ `""`. Regla del repo:
**`assertSame`/`assertNotSame` por defecto**; `assertEquals` solo para objetos
de valor con igualdad estructural intencionada (fechas, Money), y entonces
añade asersión del tipo: `assertInstanceOf`.

Lo mismo en condiciones de producción: con `declare(strict_types=1)` y
comparaciones `===`, generas MENOS mutantes ambiguos.

### T2. Mocks sin expectativas estrictas

Un mock de PHPUnit sin `expects()` acepta cualquier cosa — todos los mutantes
de passthrough de argumentos y `MethodCallRemoval` sobreviven:

```php
// DÉBIL — sobreviven MethodCallRemoval y mutaciones de args:
$mailer = $this->createMock(Mailer::class);

// FUERTE — mata eliminación de llamada Y mutación de cada argumento:
$mailer->expects($this->once())
    ->method('send')
    ->with(
        $this->identicalTo($user),            // identidad (=== en PHP) — equivalente al `is` de Python
        $this->identicalTo('welcome'),
        $this->callback(fn ($opts) => $opts === ['locale' => 'es', 'retry' => 3]),  // array COMPLETO
    );
```

Con Mockery (Pest): `shouldReceive('send')->once()->withArgs(...)` con
comparación estricta. Para colaboradores void (loggers): inyecta un
**PSR-3 test logger** (`psr/log` TestLogger o spy propio) y asserta
`records` exactos — mata `MethodCallRemoval` sobre `$this->logger->info(...)`.

### T3. Cobertura que no cubre = mutantes `uncovered` que bajan el MSI

Con el gate en MSI global 100, una rama sin test es un escapado garantizado.
Antes de "matar", verifica que `Covered Code MSI` y `MSI` coinciden — si no,
te faltan líneas por cubrir, no asersiones por endurecer. PCOV debe estar
activo (este harness lo sondea y añade `--initial-tests-php-options=-dextension=pcov.so`
si hace falta; en local: `php -m | grep pcov`).

---

## 4. Catálogo de técnicas (recetas PHP)

### 4.1 Asersiones densas

```php
$this->assertSame(
    [
        'rule_id'  => 'PHP.AT.001',
        'severity' => 'error',
        'message'  => 'Mensaje exacto con sus {placeholders}',
        'line'     => 42,
    ],
    $finding->toArray(),
);
```

`assertSame` de la estructura completa mata: strings mutados, enteros ±1,
`ArrayItemRemoval`, `Concat`, orden de claves no (los arrays PHP son ordenados:
también mata reordenaciones).

### 4.2 Fronteras exactas con data providers

```php
#[DataProvider('msiProvider')]
public function testGate(float $msi, bool $expected): void
{
    $this->assertSame($expected, $this->gate->passes($msi));
}

public static function msiProvider(): array
{
    return [
        'debajo'        => [99.99, false],
        'EN el límite'  => [100.0, true],   // ← el único caso que distingue > de >=
        'encima'        => [100.01, true],
    ];
}
```

### 4.3 Excepciones: tipo Y mensaje exactos

```php
$this->expectException(InvoiceOverflowException::class);
$this->expectExceptionMessage('Total 10001 exceeds hard limit 10000');  // mata mutaciones del mensaje y de los números interpolados
$this->calculator->total($items);
```

`expectExceptionMessage` con el mensaje COMPLETO (no `expectExceptionMessageMatches`
con un fragmento permisivo). Mata también `Throw_` (eliminación del throw):
sin throw, el test falla por "exception not thrown".

### 4.4 Tiempo, aleatoriedad y E/S: inyección de reloj

`new \DateTimeImmutable()` inline es inmutable de matar. Refactor a PSR-20:

```php
public function __construct(private readonly ClockInterface $clock) {}
```

En tests, `Symfony\Component\Clock\MockClock` (o un stub PSR-20) congela el
tiempo → `assertSame('2026-06-09T21:00:00+00:00', $r->format(DATE_ATOM))`
mata mutaciones de formato, offsets `+1` en días/segundos, etc. Igual para
`random_int`/`uniqid`: envuélvelos en un servicio inyectable.

### 4.5 Bucles y `Foreach_` (array vacío)

Infection convierte `foreach ($items as $item)` en `foreach ([] as $item)`.
Para matarlo el test necesita ≥1 elemento CON efecto observable; para
`break` ↔ `continue`, ≥2 elementos y conteo de invocaciones:

```php
$processor->expects($this->exactly(1))->method('handle');  // continue habría dado 2
```

### 4.6 Unwrap y casts: elige inputs que la función realmente transforma

- `strtolower` unwrap → input `'AbC'`, nunca `'abc'`.
- `trim` unwrap → input `'  x  '`.
- `array_unique` unwrap → input con duplicados.
- `(int) $row['qty']` (cast removal) → pasa `'7'` (string de la BD), asserta
  `assertSame(7, ...)` (¡no `assertEquals`, ver T1!).

Si el input "ya transformado" es el ÚNICO posible (tipado estricto garantiza
string lowercase…), el cast/llamada es código muerto → elimínalo (§5.C).

---

## 5. Taxonomía de (presuntos) equivalentes en PHP

> Igual que en Python: "equivalente" se PRUEBA. La mayoría se elimina con un
> refactor que hace imposible el mutante. Política del repo: cero
> `@infection-ignore-all` sobre lógica.

### Tipo V — Mutantes de visibilidad (`public` → `protected`) — exclusivos de PHP

Si el mutante escapa, **ningún test llama a ese método desde fuera** — y quizá
nadie lo hace. Es feedback de diseño, no un falso positivo:
- Método parte de la API → añade un test que lo invoque directamente (el
  mutante muere con `Error: Call to protected method`).
- Método solo usado internamente → **baja la visibilidad en producción**
  (el mutante desaparece y el diseño mejora).
- Última opción (entidad de framework que exige public): ignore del mutador
  `PublicVisibility` en `infection.json5` acotado por clase, con comentario.

### Tipo A — Solo rendimiento (`break` ↔ `continue`, `Foreach_` en colección ya vacía)

Receta de conteo (§4.5). Si el cuerpo es puro de verdad: refactor a
`array_filter`/`array_find` (8.4+)/`array_any` — la sentencia mutable desaparece.

### Tipo B — Frontera inalcanzable por invariante de tipos

`if (count($x) > 0)` con `count() >= 0` garantizado → `if ($x !== [])`.
Con `strict_types` y tipos nativos, muchas comprobaciones defensivas son
código muerto: bórralas y PHPStan (L3A, nivel alto) te confirma que sobraban.

### Tipo C — Default muerto en `??` / parámetros por defecto

`$config['timeout'] ?? 600` cuando la clave siempre existe:
- ¿Puede faltar en algún input legal (JSON externo, array de usuario)?
  → test con la clave AUSENTE que observe el 600.
- ¿Garantizada por contrato/tipos? → accede directo `$config['timeout']`
  (mejor diagnóstico) o tipa con un Value Object/DTO y el `??` desaparece.

### Tipo D — Código defensivo inalcanzable (`catch` imposibles, re-throws)

Mock del colaborador con `willThrowException(new ConnectionError(...))` y
asserta el manejo exacto. Si NI con mocks es alcanzable → código muerto;
el dead-code-detector de L4 (ShipMonk) lo confirmará.

### Tipo E — Constantes de tuning (timeouts, chunk sizes)

Igual que Python: si la constante viaja a un colaborador, el mock con
`with($this->identicalTo(600))` la mata SIEMPRE. Solo es candidata a ignore
si jamás sale de la función ni altera ningún resultado observable.

### Tipo F — Strings internos / claves de array consistentes

Claves de arrays asociativos usadas en escritura+lectura: test de ida y
vuelta por la API pública, o `assertSame` del array serializado (JSON de
respuesta) donde la clave es contrato. Extrae literales repetidos a
`private const` y asserta el valor de la constante pública si la hay.

---

## 6. Casos difíciles específicos de PHP

### PH1. Clases `final` y métodos `static`: el colaborador inmockeable

`createMock(FinalClass::class)` falla. Opciones en orden de preferencia:
1. **Extrae una interfaz** y mockea la interfaz (mejor diseño, mutante matable).
2. Usa la clase real con datos controlados (test sociable — válido y a menudo
   más fuerte que el mock).
3. `Mockery` con alias/overload — frágil, último recurso, nunca en código nuevo.

### PH2. Mutantes en `match` y enums

`MatchArmRemoval` elimina brazos. Un data provider con **un caso por brazo**
+ caso default (o `UnhandledMatchError` esperado) mata toda la familia. Para
enums: itera `Enum::cases()` en el provider — a prueba de brazos nuevos.

### PH3. Timeouts (⏰ = escapado aquí): bucles infinitos por `While_`/`For_`

`maxTimeouts=0` y `timeoutsAsEscaped=true`: UN timeout suspende. Casi siempre
es una condición de salida mutada a `true`/invertida. Receta: test unitario
rápido y directo de la condición de salida con la frontera exacta, para que
el mutante muera por asersión ANTES de colgar la suite. Revisa también el
`timeout` de Infection vs la duración real del test más lento.

### PH4. Errors ≈ escaped (particularidad del parser de esta skill)

Un mutante que provoca **fatal error** (TypeError por firma mutada, etc.)
cuenta como escapado en el checkpoint. No lo ignores: normalmente significa
que ningún test ejecuta esa llamada con tipos reales. Añade el test de
integración fina (sin mocks en esa frontera) y pasará a `killed`.

### PH5. Pest: mutación vía plugin

Proyecto Pest sin `pest-plugin-mutate` → `mutation_skipped` (TD-6) y el
checkpoint lleva el `fix_hint`. Instala el plugin; las técnicas son las
mismas (Pest usa expectations `expect($x)->toBe(...)` — `toBe` es estricto
como `assertSame`; **evita `toEqual`**, es la misma trampa T1).

### PH6. Cobertura por driver: PCOV vs Xdebug

Síntomas: "0 covered mutants", covered MSI = 0, o infra error con exit ≠ 0
sin stats. No es un problema de tests: es el driver. `php -m | grep -E 'pcov|xdebug'`;
con ambos cargados, deja solo PCOV (el doctor de esta skill avisa:
`DOCTOR_WARN_XDEBUG_PCOV`). En CI el harness localiza `pcov.so` automáticamente.

### PH7. El orquestador sobre-mockeado (igual que Python, sintaxis PHP)

No puedes matar mutantes DE `TaxCalculator` desde tests de `InvoiceService`
que lo mockean. Dos niveles: el servicio asserta cableado (`identicalTo` en
cada arg) y el calculador asserta matemática con `assertSame`. Localiza el
archivo del mutante en `infection.log` y testea ESA clase.

### PH8. Debugging del test "correcto" que no mata

1. ¿El test corre en la suite que Infection ejecuta? (testsuite de
   `phpunit.xml` / `--testsuite`; un test en `tests/Integration/` excluido
   no mata nada).
2. ¿La línea está cubierta? Mira el reporte de cobertura — `uncovered` ≠
   asersión débil.
3. Reproduce el mutante a mano: aplica el diff de `infection.log` al archivo,
   corre el test, debe FALLAR; revierte (`git checkout -- src/`).
4. ¿Asersión débil? Busca `assertEquals`/`assertTrue($x == ...)`/`toEqual` y
   endurece (T1).
5. Caché rara de Infection: borra `.infection` / `tmpDir` configurado y relanza.

---

## 7. Política de supresión (último recurso)

Regla del repo: **cero supresiones sobre lógica**. El mecanismo PHP auditado
es la anotación `@infection-ignore-all` con metadatos en las **5 líneas
anteriores** (mismo auditor que Python, selector PHP):

```php
// reason: timeout=600 es default de API pública; el mutante (601) no es observable por ningún consumidor — tipo E agotado §4/§5.
// audited: 2026-06-09
/** @infection-ignore-all */
private const DEFAULT_TIMEOUT = 600;
```

- `reason:` y `audited:` deben aparecer en las 5 líneas previas (regex del
  `allow_list_auditor`, case-insensitive).
- Verificación: `python -m harness_quality_gate audit-ignores <repo>` → exit 0.
- Alternativa NO auditada (evitar): ignores globales por mutador en
  `infection.json5` — solo aceptable para `PublicVisibility` acotado por
  clase y con comentario en el propio json5.

---

## 8. Checklist por mutante escapado

```text
[ ] infection.log — leer mutador + diff + archivo:línea
[ ] ¿Línea cubierta? Si uncovered → primero un test que la ejecute
[ ] ¿assertEquals / toEqual / assertTrue($a == $b)? → assertSame / toBe (T1)
[ ] ¿Mock sin expects()->with(identicalTo(...))? → endurecer (T2)
[ ] ¿Frontera / aritmética / unwrap / cast? → receta §4 con input transformador
[ ] ¿Visibilidad? → test directo o BAJAR visibilidad en producción (§5.V)
[ ] ¿Sigue vivo? → aplicar el diff a mano, correr el test, revertir (PH8)
[ ] ¿Equivalente probado? → refactor que lo elimina; si imposible,
    @infection-ignore-all + reason + audited y audit-ignores en verde
[ ] Final: vendor/bin/infection → MSI 100 / Covered 100 / 0 escaped / 0 timeouts
```

---

## Fuentes

- [Infection — documentación oficial](https://infection.github.io/guide/) (uso, configuración, `--filter`, loggers)
- [Infection — catálogo de mutadores](https://infection.github.io/guide/mutators.html)
- [Infection — How to disable mutations / @infection-ignore-all](https://infection.github.io/guide/how-to-disable-mutants.html)
- [PHPUnit — assertions (assertSame vs assertEquals)](https://docs.phpunit.de/en/11.5/assertions.html)
- [Pest — Mutation Testing (pest-plugin-mutate)](https://pestphp.com/docs/mutation-testing)
- [PSR-20 Clock](https://www.php-fig.org/psr/psr-20/) / [Symfony Clock MockClock](https://symfony.com/doc/current/components/clock.html)
- [Mutation testing — Wikipedia](https://en.wikipedia.org/wiki/Mutation_testing) (problema del mutante equivalente)
