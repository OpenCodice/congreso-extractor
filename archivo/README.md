# congreso-archivo

Worker de Cloudflare que guarda en R2 las páginas oficiales que lee
congreso-extractor y las descarga sin parar, cada sitio a su ritmo.

Las fuentes del Congreso limitan las peticiones (el SIL bloquea tras ~100
seguidas; el Senado, tras ~10) y una corrida de GitHub Actions no alcanzaba a
bajar todo en sus 6 h. Por eso la descarga va aparte:

- **Cron cada minuto.** Por cada sitio de `SITIOS` baja lo pendiente con su
  pausa mínima y un tope por minuto. Ante un bloqueo (las páginas de firewall de
  `BLOQUEOS`, 403 o 429), ese sitio espera 10 min, luego 20, 40… hasta 6 h, y
  su pausa sube; sin bloqueos en una hora, la pausa vuelve poco a poco a su
  mínimo. Una falla de red se reintenta (hasta 6 veces, cada vez más espaciado);
  un error de la fuente (404…) queda `fallida`. El SIL, el Senado y la Gaceta se
  piden por el Worker `egress-mx` (service binding), que corre en México.
- **R2 `congreso-archivo`.** `paginas/{clave}`: los bytes tal como llegaron, con
  `url`, `consultado` y `sha256`. La clave la calcula el extractor
  (`red._ruta`: sha256 de la URL y, en un POST, de sus datos).
- **D1 `congreso-archivo`** (`schema.sql`): la cola `pedidas` y el estado de
  cada sitio (`sitios`).

API (con `Authorization: Bearer <TOKEN>`):

- `GET /pagina/{clave}`: la página, con `X-Url`, `X-Consultado`, `X-Sha256`;
  404 si todavía no se baja, 410 si la fuente respondió con un error.
- `POST /pedir`: `[{clave, texto, url, cuerpo?, prioridad}]` (hasta 1000;
  `texto` es lo que se hashea para la clave y se comprueba; `cuerpo`, el POST en
  base64; prioridad 1 si falta, 0 para refrescar una copia vieja).
- `GET /estado`: la cola por sitio y el estado de cada sitio.
- `PUT /sembrar/{clave}` (con el token `SIEMBRA`, solo mientras exista): sube
  una página de una copia local. Ver `.github/workflows/sembrar-archivo.yml`.

Secrets del Worker: `TOKEN` (en GitHub, el secret de repo
`CONGRESO_ARCHIVO_TOKEN` de congreso-extractor), `EGRESS_TOKEN` (el mismo
valor que `TOKEN_ARCHIVO` de egress-mx) y, solo para sembrar, `SIEMBRA`.

Se despliega a mano, como `egress-mx` y `scheduler`, para no guardar
credenciales de Cloudflare en este repo, en el que también publica el agente:

```bash
cd archivo
npx wrangler d1 execute congreso-archivo --remote --file schema.sql
npx wrangler deploy
```
