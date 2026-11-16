# congreso-extractor — guía para agentes

Código que genera [`congreso-mexicano`](https://github.com/OpenCodice/congreso-mexicano)
desde el SIL de Gobernación y el DOF. Paquete `congreso/`, sin dependencias
fuera de la biblioteca estándar de Python 3.12.

## Mapa

- `tablas.py` — aplana el HTML del SIL a filas de celdas (texto, clases,
  enlaces). Los parsers eligen filas por su forma, no por selectores.
- `sil.py` — URL y parsers del SIL: padrón, perfil, buscador de votaciones,
  detalle y lista nominal, trámites, seguimiento e historial de un expediente.
- `dof.py` — API de SIDOF: sumario del día y resolución (documento, fecha) →
  decretos que lo nombran.
- `padron.py`, `votaciones.py`, `decretos.py` — arman los registros Popolo y
  sus extensiones; `validar.py`, los invariantes del repo de datos.
- `red.py` — descargas con pausa, reintentos y caché en `.cache/` (no se
  versiona); cada dato guarda URL, fecha de consulta y sha256.
- `catalogos.py` — entidades (claves de `leyes-estatales`), partidos y cámaras.

## Comandos

```bash
python3 -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara diputados
python3 -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara senado
python3 -m congreso votaciones --out ../congreso-mexicano --legislatura 66 [--asunto 5135887]
python3 -m congreso decretos   --out ../congreso-mexicano --repos ..
python3 -m congreso validar    --out ../congreso-mexicano
python3 -m pytest -q
```

El orden importa: las votaciones necesitan el padrón y los decretos, los
expedientes. `decretos` lee los trailers de los repos de leyes clonados en
`--repos`.

## Actualización

`.github/workflows/actualizar-congreso.yml` corre los cuatro pasos, valida y
abre en `congreso-mexicano` un PR `verificado` con un commit por tipo de dato
(`scripts/commits.py`: padrón, votaciones, decretos; trailer `Tipo`). Su
`revisar-pr` corre `validar` y lo fusiona con rebase. Un expediente que no
cuadra se omite y se anota en el PR; el resto se publica. Falta sumarlo al
Worker `scheduler` de `constitucion-extractor`, después de las vigilancias de
leyes de cada lunes.

## Red

El SIL clásico (sil.gobernacion.gob.mx) y SIDOF responden desde cualquier
país. `nsil.gobernacion.gob.mx`, `diputados.gob.mx` (SITL, Gaceta) y
`senado.gob.mx` no responden desde fuera de México; para usarlos habría que
pasar por el Worker `egress-mx` de `constitucion-extractor`.

## Reglas

- Fidelidad: un dato sale de una fuente oficial y cita su URL y huella. Ante
  la duda (un voto sin mandato, dos decretos indistinguibles), no se publica o
  queda como candidato; nunca se adivina.
- Un cambio a un parser lleva su prueba con un fixture real en `tests/fixtures/`.
