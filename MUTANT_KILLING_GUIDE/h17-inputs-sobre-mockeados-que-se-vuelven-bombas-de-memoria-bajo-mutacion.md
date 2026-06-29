# H17. Inputs sobre-mockeados que se vuelven bombas de memoria/bucle bajo mutación

Distinto de H5 (mockear *colaboradores* → supervivencia silenciosa). Aquí el
veneno es mockear el **input** con un `MagicMock`: el test funciona en el happy
path porque una guarda temprana corta antes de tocarlo, pero un mutante que
**bypassea esa guarda** mete el `MagicMock` en código que lo trata como
stream/iterable.

**Caso real (2026-06-24)**: el test de "binary not found" hacía
`adapter.invoke(repo=MagicMock())`. En el original, `resolve_tool` lanza
`ToolNotAvailable` y se retorna temprano — el `MagicMock` nunca se usa. Pero el
mutante `binary = str(resolve_tool(...))` → `binary = str(None)` **omite**
`resolve_tool`, así que `invoke` sigue hasta
`yaml.safe_load(repo.read_bytes())`. yaml trata el `MagicMock` como un stream y
llama `.read(n)` en bucle; cada llamada devuelve **otro `MagicMock` no-vacío**,
así que yaml lee infinitamente acumulando → **46 GB de RAM** y el worker muere.

**Síntoma engañoso**: el mutante NO aparece como superviviente limpio (`0`) ni
como ⏰; sale como `-24` (SIGXCPU) o, bajo `ulimit`, como `exit=3` (pytest
INTERNAL ERROR por `MemoryError` durante la captura de salida). Es un
superviviente *disfrazado* de flake (ver H16).

**Receta**:
1. **Inputs reales, no `MagicMock`**, en cualquier test cuyo mutante pueda
   saltarse la guarda temprana: usa `tmp_path` (un `Path` real) como `repo`. El
   mutante entonces ejecuta el camino real y tu aserción lo mata limpiamente —
   sin OOM. (El `MagicMock` solo "funcionaba" porque el happy path nunca lo
   tocaba; cualquier mutación que abra ese camino lo convierte en bomba.)
2. **Red de seguridad operativa**: corre mutmut con un límite de memoria
   virtual por proceso para que un mutante descontrolado reciba `MemoryError`
   (cuenta como matado) en vez de tumbar la máquina y la swap:
   ```bash
   ( ulimit -v 4194304; uv run mutmut run --max-children=20 )   # 4 GB virtual/proceso
   ```
   La suite normal usa <100 MB de RSS; 4 GB da margen de sobra y caza el
   runaway. (Sin esto, un solo mutante puede llevar un worker a 46 GB y meter
   el servidor en swap-death.)
3. **Diagnóstico**: el mutante culpable es el más LENTO del board
   (`durations_by_key` en el `.meta`) — el blowup tarda segundos en llegar al
   límite. Aíslalo single-child bajo `ulimit` y mira qué test revienta:
   `( ulimit -v 2097152; MUTANT_UNDER_TEST=<id> pytest tests/unit/<archivo> )`.
