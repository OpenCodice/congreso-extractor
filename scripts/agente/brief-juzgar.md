# Juzgar enlaces propuestos entre decretos del DOF y expedientes del SIL

Otro agente propuso, para cada decreto de `__PENDIENTES__`, el expediente del
SIL que lo produjo, con citas textuales que un programa ya comprobó que
existen en sus fuentes. Las propuestas están en `__PROPUESTAS__`. Tú no
propones: decides si cada propuesta es correcta.

El enlace se publica sin revisión humana como un hecho ("este decreto salió
de este expediente"). Un enlace equivocado es peor que ninguno.

En `__PENDIENTES__`, por decreto: `texto_dof` (el texto completo del
decreto), y en `candidatos` todos los expedientes que se consideraron, con
`archivo` (el expediente completo).

## Qué decidir por propuesta con expediente

Lee el decreto y el expediente propuesto, y también los demás candidatos:

- `confirmado`: el expediente es, sin duda, el de la minuta que se volvió
  ese decreto (describe las mismas reformas; su cronología termina en la
  aprobación de ambas cámaras antes de la fecha del decreto), y ningún otro
  candidato encaja igual de bien.
- `rechazado`: en cualquier otro caso, incluida la duda. Explica por qué.

Las citas solo prueban que el texto existe; no prueban que la elección sea
correcta. Juzga con todo el decreto y todo el expediente.

## Límites

- No modifiques nada fuera de `__TRABAJO__`. No hagas commit ni push.

## Entrega

Escribe `__SALIDA__`, con un objeto por cada propuesta que tenga expediente:

```json
{"decretos": [
  {"decreto": "dof-5787417", "veredicto": "confirmado", "nota": "qué revisaste"}
]}
```
