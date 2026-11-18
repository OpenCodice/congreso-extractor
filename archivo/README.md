# congreso-archivo

Worker de Cloudflare que guarda en R2 las páginas oficiales que lee
congreso-extractor y las descarga sin parar, cada sitio a su ritmo.

Las fuentes del Congreso limitan las peticiones (el SIL bloquea tras ~100
seguidas; el Senado, tras ~10) y una corrida de GitHub Actions no alcanzaba a
bajar todo en sus 6 h. Por eso la descarga va aparte:

- **Cron cada minuto.** Por cada sitio de `SITIOS` baja lo pendiente con su
  pausa mínima y un tope por minuto. Ante un bloqueo (las páginas de firewall de
  `BLOQUEOS`, 403 o 429), ese sitio espera 10 min, luego 20, 40… hasta 6 h, y
  su pausa sube; sin bloqueos en una hora, la pausa baja un 10 % en cada
  vuelta en la que descargó algo, hasta su mínimo. Un sitio nunca se deja de
  intentar: si su pausa ya no cabe en una vuelta (más de 50 s), recibe una sola
  petición cada vez que la pausa se cumple (`espera_hasta`), y con cada éxito
  baja. Una falla de red se reintenta (hasta 6 veces, cada vez más espaciado);
  un error de la fuente (404…) queda `fallida`. El SIL, el Senado y la Gaceta se
  piden por el Worker `egress-mx` (service binding), que corre en México.
- **R2 `congreso-archivo`.** `paginas/{clave}`: los bytes tal como llegaron, con
  `url`, `consultado` y `sha256`. La clave la calcula el extractor
  (`red._ruta`: sha256 de la URL y, en un POST, de sus datos).
- **D1 `congreso-archivo`** (`schema.sql`): la cola `pedidas`, el estado de
  cada sitio (`sitios`) y su última descarga lograda (`exitos`, que el Worker
  crea si falta).

API (con `Authorization: Bearer <TOKEN>`):

- `GET /pagina/{clave}`: la página, con `X-Url`, `X-Consultado`, `X-Sha256`;
  404 si todavía no se baja, 410 si la fuente respondió con un error.
- `POST /pedir`: `[{clave, texto, url, cuerpo?, prioridad}]` (hasta 1000;
  `texto` es lo que se hashea para la clave y se comprueba; `cuerpo`, el POST en
  base64; prioridad 1 si falta, 0 para refrescar una copia vieja).
- `GET /estado`: la cola por sitio y el estado de cada sitio.
- `GET /salud`: por sitio, `pausa_ms` (y su mínimo, `pausa_base_ms`),
  `pendientes`, `pendiente_mas_antigua`, `ultimo_exito`, `bloqueos_seguidos`,
  `ultimo_bloqueo` y `en_espera_hasta`. Es lo que mira el supervisor para saber
  si el archivo avanza: pendientes viejas sin un éxito reciente es un sitio
  atorado.
- `PUT /sembrar/{clave}` (con el token `SIEMBRA`, solo mientras exista): sube
  una página de una copia local. Ver `.github/workflows/sembrar-archivo.yml`.

Secrets del Worker: `TOKEN` (en GitHub, el secret de repo
`CONGRESO_ARCHIVO_TOKEN` de congreso-extractor), `EGRESS_TOKEN` (el mismo
valor que `TOKEN_ARCHIVO` de egress-mx) y, solo para sembrar, `SIEMBRA`.

La lógica del ritmo (cupo, pausas, esperas) son funciones puras con pruebas:
`node --test` dentro de `archivo/`, sin dependencias.

Se despliega solo: `.github/workflows/desplegar-workers.yml`, en cada push a
main que toque `archivo/`, corre `node --check`, `node --test` y `wrangler
deploy --dry-run`, despliega y comprueba que quedó un despliegue nuevo. Usa
los secrets de repo `CLOUDFLARE_API_TOKEN` y `CLOUDFLARE_ACCOUNT_ID`; sin
ellos prueba, avisa y no despliega. El agente que repara parsers no puede
tocar `archivo/` (sus compuertas solo dejan pasar los parsers y `tests/`).

El esquema de D1 no se aplica al desplegar. Un cambio a `schema.sql` que el
Worker no pueda crear solo va a mano, antes del push:

```bash
cd archivo
npx wrangler d1 execute congreso-archivo --remote --file schema.sql
```
