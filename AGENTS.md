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
- `asuntos.py` — iniciativas, proposiciones con punto de acuerdo y dictámenes
  en sentido negativo de la legislatura, desde el buscador avanzado del SIL
  (por meses; un mes que pasa de 999 filas se parte). El autor se liga por
  `Referencia`; un registro solo se reescribe si cambió lo que dice la fuente.
- `padron.py`, `votaciones.py`, `decretos.py` — arman los registros Popolo y
  sus extensiones; `validar.py`, los invariantes del repo de datos.
- `lecturas.py` — páginas que el parser no leyó: el fallo, la lectura del
  agente y su verificación determinista; `scripts/regresion.py` compara dos
  versiones de los parsers sobre las páginas en caché.
- `residuos.py` — los decretos que `decretos` no liga a su expediente, para el
  agente: pendientes, verificación de sus citas y aplicación del registro
  `resoluciones/decretos/` (un lote por corrida; no se edita a mano).
  Los briefs y el lanzador, en `scripts/agente/`.
- `red.py` — descargas con pausa, reintentos y caché en `.cache/` (no se
  versiona); cada dato guarda URL, fecha de consulta y sha256. Con
  `CONGRESO_ARCHIVO`, lee del archivo en vez de la red (ver «Red»).
- `archivo/` — el Worker `congreso-archivo`: archivo de páginas en R2 y
  descargador perpetuo (su `README.md`).
- `catalogos.py` — entidades (claves de `leyes-estatales`), partidos y cámaras.

## Comandos

```bash
python3 -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara diputados
python3 -m congreso padron     --out ../congreso-mexicano --legislatura 66 --camara senado
python3 -m congreso votaciones --out ../congreso-mexicano --legislatura 66 [--asunto 5135887]
EGRESS_MX_TOKEN=… python3 -m congreso senado --out ../congreso-mexicano --legislatura 66
EGRESS_MX_TOKEN=… python3 -m congreso gaceta --out ../congreso-mexicano --legislatura 66
python3 -m congreso asuntos    --out ../congreso-mexicano --legislatura 66 [--tipo 11]
python3 -m congreso decretos   --out ../congreso-mexicano --repos ..
python3 -m congreso validar    --out ../congreso-mexicano
python3 -m congreso residuos pendientes --out ../congreso-mexicano --repos .. --trabajo /tmp/r
python3 -m pytest -q
```

El orden importa: las votaciones necesitan el padrón; las del Senado y la
Gaceta, las del SIL (para ligarse); los asuntos, el padrón y los expedientes;
los decretos, los expedientes. `decretos` lee los trailers de los repos de leyes clonados en
`--repos`.

## Actualización

`.github/workflows/actualizar-congreso.yml` corre los pasos leyendo del archivo
(ver «Red»), valida y abre en `congreso-mexicano` un PR `verificado` con un
commit por tipo de dato
(`scripts/commits.py`: padrón, votaciones, asuntos, decretos y fuentes;
trailer `Tipo`). El repo de datos no tiene workflows: su PR lo valida y
fusiona `revisar-pr.yml` de este repo, que llaman `actualizar-congreso.yml` y
`resolver-residuos.yml` al abrirlo (y se lanza a mano con `gh workflow run
revisar-pr.yml -f pr=N`). Su job `validar`, sin secretos, corre
`scripts/validar_pr.sh` sobre el sha de la cabeza del PR: `congreso validar` y
`scripts/validar_commits.py` (un `Tipo` conocido por commit, que solo toca sus
carpetas, sin merges). `fusionar`, con PR_TOKEN, lo fusiona con rebase atado a
ese sha, solo si es de una rama `datos/` del mismo repo y trae `verificado`.
main de congreso-mexicano exige PR, historial lineal y aplica a los admins: un
cambio a mano (la documentación, `Tipo: indice`) también va por PR. Un
expediente que no cuadra se anota en el PR; el resto se publica.

Lo lanza el Worker `scheduler` de `constitucion-extractor` cada hora. Las
corridas `publicar=no` («solo pedir», unos minutos) recorren todo para pedirle
al archivo lo nuevo: una cadena de páginas (listado → votación → lista) se
completa en unas horas. La de las 18:00 UTC (`publicar=si`, también la de a
mano) además lee con el agente, abre el PR y, al fusionarse, avisa a
`constitucion-web` (`repository_dispatch` datos-actualizados) para que la web
se regenere. Lo que el archivo todavía no tiene no se publica ni cuenta como
retirado: un expediente o una votación esperan completos (`pendientes_de_descarga`
en el resumen del PR), y un paso que depende de una sola página (un listado,
o los decretos, que necesitan todos sus sumarios) se queda como estaba.

Al terminar con éxito una corrida que publica, `resolver-residuos.yml` lleva al agente lo que quedó
sin ligar: uno propone el expediente con citas, `residuos para-juicio` deja
pasar solo las propuestas cuyas citas están en su fuente (sin la nota del que
propuso), y otro agente confirma o rechaza. El veredicto, confirmado o no, se
registra en `resoluciones/` (un decreto ya juzgado con los mismos candidatos no
vuelve al agente) y los decretos se regeneran con él en un PR. El agente corre
sin credenciales en disco: el checkout no las guarda y los repos se clonan sin
token.

Dentro de la actualización, una página del Senado o la Gaceta que el parser
no lee (un formato nuevo) se guarda como fallo (`congreso/lecturas.py`) y la
lee un agente (`scripts/agente/leer.sh`, `brief-leer.md`, sin más secreto que
el suyo). Su lectura, con la forma exacta que daría el parser, solo se acepta
si pasa `lecturas verificar`: cada nombre y cada cifra están en la página, las
listas suman los totales que declara la fuente (o la otra página de la misma
votación, leída por el parser) y las etiquetas son las del catálogo. Lo
aceptado queda en `lecturas/{fuente}/{tipo}/{sha256}.json` (no se edita a
mano), sirve solo para esa página exacta y la votación lo dice en `lecturas`.
Hay dos rondas (en la Gaceta, la lista se pide con lo que dice la tabla).
Cuando el parser ya lee una página con lectura, manda el parser y, si los dos
difieren, se avisa en el PR.

Al terminar cada actualización que publica, `reparar-parsers.yml` toma su artefacto
`fallos` (las páginas del Senado y la Gaceta que el parser no leyó; ver
`congreso/lecturas.py`) y, si hay, un agente (`scripts/agente/reparar.sh`,
`brief-reparar.md`) corrige `senado.py`/`gaceta.py` (o, para un bloqueo nuevo,
`red.BLOQUEOS`) con un fixture real y su prueba; si la página es un bloqueo o
un error de la fuente, no la "arregla": lo reporta. Su cambio sale como parche
y otro job, sobre un checkout limpio con el caché y los fallos descargados de
nuevo, corre las compuertas (`scripts/agente/compuertas_reparar.py`): solo
toca los parsers y `tests/`, sin borrar ni modificar fixtures, y cada fixture
nuevo es byte por byte una página descargada; pruebas nuevas en verde, y las
de antes, tal como estaban, contra el código nuevo; `scripts/regresion.py` sin
regresiones; cada fallo que dice resolver ahora se lee, y ninguna página que
el cambio lee distinto contradice su lectura verificada. Un tercer job, sin
correr código del agente, aplica ese mismo parche (por sha256), lo publica en
main y relanza la actualización (una vez cada 12 h a lo más).

`scripts/regresion.py` sirve también a mano, antes de tocar un parser: lee
cada página del caché (y de una carpeta de fallos) con el código de una
revisión y con el árbol de trabajo, y sale con 1 si algo que se leía cambia:
`python scripts/regresion.py --cache .cache --antes HEAD [--fallos DIR]`.

## Red

En CI nada se descarga de las fuentes: lo hace el Worker `congreso-archivo`
(`archivo/`, ver su `README.md`), cada minuto y al ritmo de cada sitio, y lo
guarda en R2. Con `CONGRESO_ARCHIVO` (su URL) y `CONGRESO_ARCHIVO_TOKEN`,
`red.obtener` lee la página del archivo (y la guarda en `.cache/`, que queda
como copia local). Si no está, la anota y lanza `red.Pendiente`: ese expediente
o esa votación se omiten en esta corrida, sin error ni retiro. Si está pero es
más vieja que su vigencia, se usa (su fecha de consulta es la real) y se pide
otra, a lo más una vez al día. Al terminar cada comando, lo anotado se manda al
archivo (`red.enviar_pedidas`). `red.anticipar` pide de una vez las páginas que
se van a leer después (la tabla de una votación del Senado, los trámites de
cada dictamen), para no esperar una vuelta por página. `sembrar-archivo.yml`
sube al archivo una copia local (el caché de Actions).

Sin `CONGRESO_ARCHIVO` (en local), `red.obtener` descarga directo. El SIL
clásico (sil.gobernacion.gob.mx) y SIDOF responden desde cualquier país salvo
desde Cloudflare fuera de México; el SIL limita a ~100 peticiones seguidas
(`red.BLOQUEOS`). El sitio del Senado y la Gaceta solo responden desde México:
`red.VIA_MX` los pide por el Worker `egress-mx` de `constitucion-extractor`
(GET y POST de formulario), con el secret `EGRESS_MX_TOKEN`, que solo existe en
GitHub; en local esos dos pasos no corren. Para explorar páginas nuevas de esas
fuentes: `gh workflow run sondear-mx.yml -f urls="…" [-f datos="…"]` deja lo
descargado como artefacto. El SITL (sitl.diputados.gob.mx) responde 403 aun
desde México. Al Senado (Incapsula) se le pide cada 12 s
(`CONGRESO_PAUSA_SENADO`) y, ante un bloqueo, se espera 2 y 10 min; cada
comando descarga a lo más 120 min de él (`CONGRESO_PRESUPUESTO_SENADO`). Una
respuesta cortada a medias (`IncompleteRead`) se reintenta.

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
