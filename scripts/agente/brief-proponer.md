# Ligar decretos del DOF con su expediente del SIL

`congreso-mexicano` liga cada decreto publicado en el DOF con el expediente
legislativo (del Sistema de Información Legislativa, SIL) que lo produjo. El
código lo hace solo cuando no hay duda; estos decretos quedaron sin ligar
porque había varios candidatos parecidos, o porque la fecha que da el SIL no
coincide con la del DOF. Tu trabajo es leerlos como lo haría una persona y
decir, para cada decreto, cuál de sus candidatos es su expediente, o que
ninguno lo es.

El enlace se publica sin revisión humana como un hecho ("este decreto salió
de este expediente"). Un enlace equivocado es peor que ninguno.

## Qué tienes

`__PENDIENTES__`, con un objeto por decreto:

- `titulo`, `fecha`, `documentos` (claves de las leyes que reforma) y
  `texto_dof`: el archivo con el texto completo del decreto. Al final suele
  decir quiénes lo firmaron y la fecha en que el Congreso lo aprobó
  ("Ciudad de México, a … .- Dip. … Presidenta.- Sen. …").
- `candidatos`: expedientes del SIL que nombran a una de esas leyes y no
  están ligados a otro decreto, con su denominación, su fecha de publicación
  en el DOF según el SIL (`null` si el SIL no la registra), su último estatus,
  sus trámites, y `archivo` con el expediente completo (asuntos, cronología,
  votaciones).

## Qué decidir

El expediente correcto es el de la minuta que se convirtió en ese decreto:
su denominación describe las mismas reformas (mismos artículos, misma
materia) y su cronología termina en la aprobación por ambas cámaras (y, si
es constitucional, la declaratoria) antes de la fecha del decreto.

- Elige un candidato solo si el texto del decreto y el expediente lo
  sostienen sin duda: mismos artículos o misma materia, y fechas
  compatibles.
- Si ninguno encaja, o dos encajan igual de bien, `"expediente": null`.
  Ante la duda, `null`.
- No inventes candidatos: solo puedes elegir entre los listados.

## Citas

Cada elección lleva al menos una cita del decreto (`"fuente": "dof"`) y una
del expediente (`"fuente": "expediente"`) que la justifiquen. Son copias
textuales de al menos 20 caracteres: un programa comprobará que cada una
aparece tal cual en `texto_dof` o en el archivo del expediente (sin importar
mayúsculas, acentos ni espacios), y descartará la elección si no.

## Límites

- No modifiques nada fuera de `__TRABAJO__`. No hagas commit ni push.
- No necesitas internet: todo está en los archivos.

## Entrega

Escribe `__SALIDA__`:

```json
{"decretos": [
  {"decreto": "dof-5787417", "expediente": "sil-5071820",
   "citas": [{"fuente": "dof", "texto": "…"}, {"fuente": "expediente", "texto": "…"}],
   "nota": "por qué: mismos artículos …; el SIL registra la publicación un día después"}
]}
```

Un objeto por cada decreto de `__PENDIENTES__`, aun los que dejes en `null`.
