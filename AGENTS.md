# congreso-extractor — guía para agentes

Código que genera [`congreso-mexicano`](https://github.com/OpenCodice/congreso-mexicano)
desde el SIL de Gobernación, el DOF, el sitio de votaciones del Senado y la
Gaceta Parlamentaria de Diputados. Paquete `congreso/`, sin dependencias
fuera de la biblioteca estándar de Python 3.12.

## Mapa

- `tablas.py` — aplana el HTML del SIL a filas de celdas (texto, clases,
  enlaces). Los parsers eligen filas por su forma, no por selectores.
- `sil.py` — URL y parsers del SIL: padrón, perfil, buscador de votaciones,
  detalle y lista nominal, trámites, seguimiento e historial de un expediente.
- `dof.py` — API de SIDOF: sumario del día y resolución (documento, fecha) →
  decretos que lo nombran.
- `senado.py`, `gaceta.py` — parsers de las votaciones nominales de cada
  cámara (todas, también las de lo particular, que el SIL no desglosa).
- `votaciones_senado.py`, `votaciones_gaceta.py` — sus VoteEvents
  (`senado-…`, `gaceta-…`); `cotejo.py`, cómo se ligan a la votación del SIL
  y qué se anota cuando difieren; `nombres.py`, cómo se liga el nombre de
  cada fuente a un mandato.
- `padron.py`, `votaciones.py`, `decretos.py` — arman los registros Popolo y
  sus extensiones; `validar.py`, los invariantes del repo de datos.
- `residuos.py` — los decretos que `decretos` no liga a su expediente, para el
  agente: pendientes, verificación de sus citas y aplicación del registro
  `resoluciones/decretos/` (un lote por corrida; no se edita a mano).
  Los briefs y el lanzador, en `scripts/agente/`.
- `red.py` — descargas con pausa, reintentos y caché en `.cache/` (no se
  versiona); cada dato guarda URL, fecha de consulta y sha256.
- `catalogos.py` — entidades (claves de `leyes-estatales`), partidos y cámaras.

## Comandos

```bash
python3 -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara diputados
python3 -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara senado
python3 -m congreso votaciones --out ../congreso-mexicano --legislatura 66 [--asunto 5135887]
EGRESS_MX_TOKEN=… python3 -m congreso senado --out ../congreso-mexicano --legislatura 66
EGRESS_MX_TOKEN=… python3 -m congreso gaceta --out ../congreso-mexicano --legislatura 66
python3 -m congreso decretos   --out ../congreso-mexicano --repos ..
python3 -m congreso validar    --out ../congreso-mexicano
python3 -m congreso residuos pendientes --out ../congreso-mexicano --repos .. --trabajo /tmp/r
python3 -m pytest -q
```

El orden importa: las votaciones necesitan el padrón; las del Senado y la
Gaceta, las del SIL (para ligarse); los decretos, los expedientes. `decretos` lee los trailers de los repos de leyes clonados en
`--repos`.

## Actualización

`.github/workflows/actualizar-congreso.yml` corre los cuatro pasos, valida y
abre en `congreso-mexicano` un PR `verificado` con un commit por tipo de dato
(`scripts/commits.py`: padrón, votaciones, decretos; trailer `Tipo`). Su
`revisar-pr` corre `validar` y lo fusiona con rebase. Un expediente que no
cuadra se omite y se anota en el PR; el resto se publica. Lo lanza el Worker
`scheduler` de `constitucion-extractor` cada lunes a las 18:00 UTC, después de
las vigilancias de leyes.

Al terminar con éxito, `resolver-residuos.yml` lleva al agente lo que quedó
sin ligar: uno propone el expediente con citas, `residuos para-juicio` deja
pasar solo las propuestas cuyas citas están en su fuente (sin la nota del que
propuso), y otro agente confirma o rechaza. El veredicto, confirmado o no, se
registra en `resoluciones/` (un decreto ya juzgado con los mismos candidatos no
vuelve al agente) y los decretos se regeneran con él en un PR. El agente corre
sin credenciales en disco: el checkout no las guarda y los repos se clonan sin
token.

## Red

El SIL clásico (sil.gobernacion.gob.mx) y SIDOF responden desde cualquier
país; el SIL limita a ~100 peticiones seguidas (`red.BLOQUEO`). El sitio del
Senado y la Gaceta solo responden desde México: `red.VIA_MX` los pide por el
Worker `egress-mx` de `constitucion-extractor` (GET y POST de formulario), con
el secret `EGRESS_MX_TOKEN`, que solo existe en GitHub; en local esos dos
pasos no corren. Para explorar páginas nuevas de esas fuentes:
`gh workflow run sondear-mx.yml -f urls="…" [-f datos="…"]` deja lo
descargado como artefacto. El SITL (sitl.diputados.gob.mx) responde 403 aun
desde México.

## Reglas

- Fidelidad: un dato sale de una fuente oficial y cita su URL y huella. Lo
  dudoso nunca se atribuye ni se adivina (un voto sin mandato único queda con
  el nombre de la fuente en `votos_faltantes`; dos decretos indistinguibles,
  como candidatos), pero lo que la fuente publica sí se registra: una votación
  que no cuadra consigo misma se publica con `inconsistencias`, sin ajustar
  sus conteos. Ensuciar o retirar una fuente no debe bastar para sacar algo
  del registro: solo se omite lo que no se pudo leer, y nada se borra (lo que
  la fuente retira queda con `retirada_de_la_fuente`).
- Un cambio a un parser lleva su prueba con un fixture real en `tests/fixtures/`.
