# Guía para matar mutantes al 100% (mutmut)

Manual operativo para los subagentes que cierran supervivientes de mutmut.
El flujo de ejecución (comandos, caché, coverage, lectura de resultados) está
en [MUTATION_TESTING.md](MUTATION_TESTING.md) y en la cabecera del `Makefile`.
Este documento es el **punto de entrada** — el contenido completo se ha dividido
en archivos navegables dentro del directorio [`MUTANT_KILLING_GUIDE/`](MUTANT_KILLING_GUIDE/).

**Para la IA**: Usa este índice para saltar directamente a la sección que necesitas.
Cada entrada enlaza al shard correspondiente. Las primeras secciones de introducción, fundamentos Son obligatorias.

---

## Índice navegable

### Introducción

- [TL;DR — Árbol de decisión](MUTANT_KILLING_GUIDE/tldr-rbol-de-decisin-si-solo-lees-una-cosa-lee-esto.md) — *Si solo lees una cosa, lee esto*
- [0. Reglas de oro (no negociables)](MUTANT_KILLING_GUIDE/0-reglas-de-oro-no-negociables.md)

### Fundamentos

- [1. Bucle de trabajo por superviviente](MUTANT_KILLING_GUIDE/1-bucle-de-trabajo-por-superviviente.md)
- [2. Qué muta mutmut (para saber qué buscar en el diff)](MUTANT_KILLING_GUIDE/2-qu-muta-mutmut-para-saber-qu-buscar-en-el-diff.md)
- [3. Triage: clasifica antes de actuar](MUTANT_KILLING_GUIDE/3-triage-clasifica-antes-de-actuar.md)

### Técnicas para matar mutantes

- [4. Catálogo de técnicas para matar](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md)
  - [4.1 Asersiones densas](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#41-asersiones-densas-la-tcnica-base-de-este-repo)
  - [4.2 Fronteras exactas](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#42-fronteras-exactas-mata)
  - [4.3 Strings exactos: mensajes, logs, claves](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#43-strings-exactos-mensajes-logs-claves)
  - [4.4 Spies sobre dependencias](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#44-spies-sobre-dependencias-mata-kwargs-flags-timeouts-rutas)
  - [4.5 Defaults de parámetros](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#45-defaults-de-parmetros)
  - [4.6 Acumuladores y aritmética](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#46-acumuladores-y-aritmtica)
  - [4.7 break ↔ continue y early-returns](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#47-y-early-returns)
  - [4.8 Ramas booleanas (and ↔ or)](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#48-ramas-booleanas)
  - [4.9 Property-based testing](MUTANT_KILLING_GUIDE/4-catlogo-de-tcnicas-para-matar.md#49-property-based-testing-cuando-los-ejemplos-no-llegan)

### Equivalentes (presuntos) y solución por tipo

- [5. Taxonomía de (presuntos) equivalentes](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md)
  - [Tipo A — Equivalente "solo rendimiento"](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-a-equivalente-solo-rendimiento-orden-de-comprobaciones)
  - [Tipo B — Frontera inalcanzable](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-b-frontera-inalcanzable-con-invariante)
  - [Tipo C — Default muerto](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-c-default-muerto-cuando-siempre-existe-kwarg-default-nunca-usado)
  - [Tipo D — Código defensivo inalcanzable](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-d-cdigo-defensivo-inalcanzable-ramas-imposibles-re-raise-genricos)
  - [Tipo E — Constantes de tuning](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-e-constantes-de-tuning-timeouts-tamaos-de-buffer-sleeps)
  - [Tipo F — String interno consistente](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-f-string-interno-consistente-clave-usada-solo-dentro-del-mdulo)
  - [Tipo G — is ↔ == con singletons](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-g-con-singletons-sentinels)
  - [Tipo H — Mensajes/representaciones "que no importan"](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-h-mensajesrepresentaciones-que-no-importan)
  - [Tipo I — Mutación con efecto solo en rendimiento](MUTANT_KILLING_GUIDE/5-taxonoma-de-presuntos-equivalentes-y-solucin-por-tipo.md#tipo-i-mutacin-con-efecto-solo-en-el-rendimiento-de-la-suite-timeouts)

### Estrategia y política

- [6. Estrategia de campaña (para el coordinador)](MUTANT_KILLING_GUIDE/6-estrategia-de-campaa-para-el-coordinador.md)
- [7. Política de pragmas (último recurso)](MUTANT_KILLING_GUIDE/7-poltica-de-pragmas-ltimo-recurso.md)
- [8. Checklist por mutante (resumen ejecutable)](MUTANT_KILLING_GUIDE/8-checklist-por-mutante-resumen-ejecutable.md)

---

## PARTE II — Casos difíciles (H1–H17)

Casos con supervivientes reales de este repo. Cada caso incluye: diff, por qué
sobrevive, y receta exacta.

- [H1. Passthrough de argumentos a colaboradores mockeados ⭐](MUTANT_KILLING_GUIDE/h1-passthrough-de-argumentos-a-colaboradores-mockeados-el-n-1-de-este-repo.md) — *el nº 1 de este repo*
- [H2. Valores no deterministas: tiempo, duraciones, redondeos](MUTANT_KILLING_GUIDE/h2-valores-no-deterministas-tiempo-duraciones-redondeos.md)
- [H3. Logging con placeholders %](MUTANT_KILLING_GUIDE/h3-logging-con-placeholders.md)
- [H4. Tablas de verdad incompletas en condiciones compuestas](MUTANT_KILLING_GUIDE/h4-tablas-de-verdad-incompletas-en-condiciones-compuestas.md)
- [H5. El orquestador sobre-mockeado](MUTANT_KILLING_GUIDE/h5-el-orquestador-sobre-mockeado-mutantes-dentro-de-lo-mockeado-jams-mueren-ah.md)
- [H6. Manejo de errores: except que tragan y fallbacks](MUTANT_KILLING_GUIDE/h6-manejo-de-errores-except-que-tragan-y-fallbacks.md)
- [H7. Listas argv y orden de elementos](MUTANT_KILLING_GUIDE/h7-listas-argv-y-orden-de-elementos.md)
- [H8. break/continue y early-return en loops puros](MUTANT_KILLING_GUIDE/h8-breakcontinue-y-early-return-en-loops-puros-el-equivalente-clsico-que-no-lo-es.md)
- [H9. Mutantes ⏰ (timeout) y 🤔 (suspicious)](MUTANT_KILLING_GUIDE/h9-mutantes-timeout-y-suspicious.md)
- [H10. Estado global, caches y singletons](MUTANT_KILLING_GUIDE/h10-estado-global-caches-y-singletons.md)
- [H11. Mutantes que requieren inputs "imposibles de construir"](MUTANT_KILLING_GUIDE/h11-mutantes-que-requieren-inputs-imposibles-de-construir.md)
- [H12. El mutante que "deberías haber matado" y sigue vivo](MUTANT_KILLING_GUIDE/h12-el-mutante-que-deberas-haber-matado-y-sigue-vivo-debugging-del-propio-test.md)
- [H13. `monkeypatch.chdir` rompe la recolección de stats de mutmut](MUTANT_KILLING_GUIDE/h13-monkeypatchchdir-rompe-la-recoleccin-de-stats-de-mutmut.md)
- [H14. La trampa del XX-wrap: el substring ingenuo NO mata strings](MUTANT_KILLING_GUIDE/h14-la-trampa-del-xx-wrap-el-substring-ingenuo-no-mata-strings.md)
- [H15. Gemelos falsy en inicializadores](MUTANT_KILLING_GUIDE/h15-gemelos-falsy-en-inicializadores-none-falsenone-none.md)
- [H16. Exit -24 (SIGXCPU) en runs paralelos](MUTANT_KILLING_GUIDE/h16-exit-24-sigxcpu-en-runs-paralelos-casi-siempre-es-flake-no-timeout.md)
- [H17. Inputs sobre-mockeados que se vuelven bombas de memoria bajo mutación 💣](MUTANT_KILLING_GUIDE/h17-inputs-sobre-mockeados-que-se-vuelven-bombas-de-memoria-bajo-mutacion.md) — *el `MagicMock` que un mutante arrastra a un OOM de 46 GB*

---

## Medición y fuentes

- [Protocolo de medición fiable](MUTANT_KILLING_GUIDE/protocolo-de-medicin-fiable-aprendido-a-base-de-nmeros-absurdos.md) — *aprendido a base de números absurdos*
- [Fuentes](MUTANT_KILLING_GUIDE/fuentes.md)
