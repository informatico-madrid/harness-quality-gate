# H18. `inspect.signature` NO mata mutaciones de valor-por-defecto (el trampolín conserva la firma)

**Síntoma:** un mutante `def f(..., cap: int = 5)` → `= 6` sobrevive aunque tengas
un test `assert inspect.signature(f).parameters["cap"].default == 5`.

**Por qué:** mutmut genera un *trampolín*. La función pública `f` pasa a ser un
**dispatcher** que conserva la **firma original** (`cap: int = 5`) y delega la
llamada a `x_f__mutmut_N`, donde vive el cuerpo mutado (`= 6`). `inspect.signature(f)`
lee la firma del **dispatcher** → ve `5` → tu assert pasa **también bajo el mutante**
→ sobrevive. La introspección de firma es **estructuralmente ciega** a las
mutaciones de default. (Verificable: `grep "def build_graph" mutants/src/.../graph.py`
muestra el dispatcher con la firma intacta y `x_..._mutmut_1` con el `= 6`.)

**Solución — matar por COMPORTAMIENTO observable del default:** llama a la función
**omitiendo** el argumento y observa un efecto del valor por defecto.
`build_graph()` (sin pasar `cap`) → `assert graph.config["recursion_limit"] == 50`
mata el mutante SÓLO si ese 50 depende del default de forma **no saturada**.

**Trampa de saturación:** si el default solo se usa dentro de `max(50, cap*2+20)`,
entonces `cap=5` y `cap=6` dan **ambos 50** → no hay comportamiento observable →
el mutante es de verdad inmatable. Pero eso es una **señal de diseño**, no un
equivalente inocente: el parámetro apenas influye, o es una fuente de verdad
duplicada/desconectada de la real. Arréglalo (elimina/reconecta el parámetro) y el
mutante muere solo. Ver [H19](h19-coverage-gap-por-tier-el-mutante-vivo-que-solo-cubre-integration-excluido.md)
y la tripartición en [3. Triage](3-triage-clasifica-antes-de-actuar.md).
