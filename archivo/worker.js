// Archivo de las páginas oficiales que lee congreso-extractor, y el descargador
// que lo llena sin parar.
//
// Las fuentes del Congreso limitan las peticiones (el SIL tras ~100 seguidas,
// el Senado tras ~10) y las corridas de GitHub Actions no alcanzaban a bajar
// todo en sus 6 h. Aquí la descarga va aparte y perpetua: cada minuto, por cada
// sitio, se baja lo pendiente al ritmo que ese sitio tolera y se guarda en R2.
// El extractor procesa lo que hay en el archivo sin tocar la red y pide (POST
// /pedir) lo que le faltó o ya está viejo; eso es lo que se descarga después.
//
// El Worker no interpreta páginas: guarda bytes bajo la clave que calcula el
// extractor (`red._ruta`), con su URL, fecha de consulta y sha256.

// Pausa mínima entre peticiones a cada sitio (ms), si solo responde desde
// México (se pide por el Worker egress-mx; el SIL, además, no contesta a
// Cloudflare fuera de México) y cuántas páginas baja como máximo por minuto.
// La pausa sube sola si el sitio bloquea y baja poco a poco mientras no bloquee.
export const SITIOS = {
  "sil.gobernacion.gob.mx": { pausa: 6000, mx: true, cupo: 8 },
  "www.senado.gob.mx": { pausa: 15000, mx: true, cupo: 3 },
  "gaceta.diputados.gob.mx": { pausa: 3000, mx: true, cupo: 5 },
  "dof.gob.mx": { pausa: 2000, cupo: 2 },
  "sidof.segob.gob.mx": { pausa: 2000, cupo: 2 },
};
// Páginas que los firewalls sirven con estado 200 (iguales a `red.BLOQUEOS`).
export const BLOQUEOS = ["This page can't be displayed", "_Incapsula_Resource"];
const AGENTE = "Mozilla/5.0 (compatible; OpenCodice/1.0; +https://github.com/OpenCodice)";
// Cada invocación del cron trabaja menos de un minuto: así no se enciman.
const DURACION = 50_000;
const PAUSA_MAX = 120_000;
const MAX_INTENTOS = 6;
// Una página que falló de forma definitiva (404…) se vuelve a intentar si el
// extractor la pide de nuevo pasado este tiempo.
const REINTENTAR_FALLIDA = 24 * 3600_000;

export function bloqueado(bytes) {
  const inicio = new TextDecoder("latin1").decode(bytes.subarray(0, 3000));
  return BLOQUEOS.some((b) => inicio.includes(b));
}

// Espera tras el n-ésimo bloqueo seguido: 10 min, 20, 40… hasta 6 h.
export function esperaBloqueo(n) {
  return Math.min(10 * 60_000 * 2 ** Math.max(0, n - 1), 6 * 3600_000);
}

function iguales(a, b) {
  const ea = new TextEncoder().encode(a);
  const eb = new TextEncoder().encode(b);
  return ea.length === eb.length && crypto.subtle.timingSafeEqual(ea, eb);
}

function autorizado(request, secreto) {
  const token = (request.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  return Boolean(secreto) && iguales(token, secreto);
}

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const sha256 = async (datos) => hex(await crypto.subtle.digest("SHA-256", datos));
const desdeBase64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const json = (datos, status = 200) => new Response(JSON.stringify(datos, null, 1), {
  status, headers: { "Content-Type": "application/json; charset=utf-8" } });
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
const clavePagina = (clave) => `paginas/${clave}`;

// ---------------------------------------------------------------- descarga

async function pedirFuente(env, p) {
  const cuerpo = p.cuerpo ? desdeBase64(p.cuerpo) : undefined;
  const cabeceras = { "User-Agent": AGENTE };
  if (cuerpo) cabeceras["Content-Type"] = "application/x-www-form-urlencoded";
  const host = new URL(p.url).hostname;
  if (SITIOS[host].mx) {
    cabeceras.Authorization = `Bearer ${env.EGRESS_TOKEN}`;
    return env.EGRESS.fetch(`https://egress-mx/?url=${encodeURIComponent(p.url)}`, {
      method: cuerpo ? "POST" : "GET", body: cuerpo, headers: cabeceras,
      signal: AbortSignal.timeout(90_000),
    });
  }
  return fetch(p.url, {
    method: cuerpo ? "POST" : "GET", body: cuerpo, headers: cabeceras, redirect: "follow",
    signal: AbortSignal.timeout(90_000),
  });
}

// Resultado de una descarga: "guardada", "bloqueo", "reintentar" o "fallida".
async function descargar(env, p) {
  let r, bytes;
  try {
    r = await pedirFuente(env, p);
    bytes = new Uint8Array(await r.arrayBuffer());
  } catch (e) {
    return { estado: "reintentar", error: String(e).slice(0, 300) };
  }
  if (r.status === 429 || r.status === 403 || (r.status === 200 && bloqueado(bytes))) {
    return { estado: "bloqueo", error: `estado ${r.status}` };
  }
  if (r.status >= 500) return { estado: "reintentar", error: `estado ${r.status}` };
  if (r.status !== 200) {
    return { estado: "fallida", error: `estado ${r.status}: ${new TextDecoder().decode(bytes.subarray(0, 200))}` };
  }
  const consultado = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  await env.ARCHIVO.put(clavePagina(p.clave), bytes, {
    customMetadata: { url: p.url, consultado, sha256: await sha256(bytes) },
  });
  return { estado: "guardada" };
}

// Lo que un sitio puede bajar en una invocación: su ritmo, con un tope para
// no pasar de los límites por invocación de Workers (subpeticiones a R2 y D1).
function cupo(host, pausa) {
  return Math.min(SITIOS[host].cupo, Math.floor(DURACION / pausa));
}

async function trabajarSitio(env, sitio, pedidas, fin, cambios) {
  const base = SITIOS[sitio.host].pausa;
  const cuenta = { host: sitio.host, descargadas: 0, fallidas: 0, bloqueos: 0, ya_estaban: 0 };
  for (const p of pedidas) {
    if (Date.now() + sitio.pausa_ms > fin) break;
    // Lo que falta (prioridad 1) puede haber llegado por otra pedida o la siembra.
    if (p.prioridad > 0 && await env.ARCHIVO.head(clavePagina(p.clave))) {
      cambios.push(env.DB.prepare("DELETE FROM pedidas WHERE clave = ?").bind(p.clave));
      cuenta.ya_estaban++;
      continue;
    }
    const t0 = Date.now();
    const r = await descargar(env, p);
    if (r.estado === "guardada") {
      cambios.push(env.DB.prepare("DELETE FROM pedidas WHERE clave = ?").bind(p.clave));
      sitio.bloqueos = 0;
      cuenta.descargadas++;
    } else if (r.estado === "bloqueo") {
      sitio.bloqueos++;
      sitio.ultimo_bloqueo = Date.now();
      sitio.espera_hasta = Date.now() + esperaBloqueo(sitio.bloqueos);
      sitio.pausa_ms = Math.min(PAUSA_MAX, Math.round(sitio.pausa_ms * 1.25));
      cuenta.bloqueos++;
      break;
    } else {
      const intentos = p.intentos + 1;
      const definitiva = r.estado === "fallida" || intentos >= MAX_INTENTOS;
      cambios.push(env.DB.prepare(
        "UPDATE pedidas SET intentos = ?, error = ?, estado = ?, siguiente = ?, actualizada = ? WHERE clave = ?")
        .bind(intentos, r.error, definitiva ? "fallida" : "pendiente",
              Date.now() + 60_000 * 4 ** intentos, Date.now(), p.clave));
      if (definitiva) cuenta.fallidas++;
    }
    await dormir(Math.max(0, sitio.pausa_ms - (Date.now() - t0)));
  }
  // Sin bloqueos en la última hora, la pausa vuelve poco a poco a su mínimo.
  if (sitio.pausa_ms > base && Date.now() - sitio.ultimo_bloqueo > 3600_000) {
    sitio.pausa_ms = Math.max(base, Math.round(sitio.pausa_ms * 0.9));
  }
  cambios.push(env.DB.prepare(
    `UPDATE sitios SET pausa_ms = ?, bloqueos = ?, ultimo_bloqueo = ?, espera_hasta = ?,
     descargadas = descargadas + ? WHERE host = ?`)
    .bind(sitio.pausa_ms, sitio.bloqueos, sitio.ultimo_bloqueo, sitio.espera_hasta, cuenta.descargadas, sitio.host));
  return cuenta;
}

async function ronda(env) {
  const ahora = Date.now();
  const fin = ahora + DURACION;
  // Una sola ronda a la vez: si la anterior sigue, esta no hace nada.
  const turno = await env.DB.prepare("UPDATE turno SET hasta = ? WHERE id = 1 AND hasta < ?")
    .bind(fin + 30_000, ahora).run();
  if (turno.meta.changes !== 1) return [];
  const cambios = [];
  try {
    await env.DB.batch(Object.entries(SITIOS).map(([host, c]) =>
      env.DB.prepare("INSERT OR IGNORE INTO sitios (host, pausa_ms) VALUES (?, ?)").bind(host, c.pausa)));
    const sitios = (await env.DB.prepare("SELECT * FROM sitios").all()).results
      .filter((s) => SITIOS[s.host] && s.espera_hasta < ahora);
    const trabajos = await Promise.all(sitios.map(async (s) => {
      const pedidas = (await env.DB.prepare(
        `SELECT * FROM pedidas WHERE host = ? AND estado = 'pendiente' AND siguiente <= ?
         ORDER BY prioridad DESC, creada LIMIT ?`).bind(s.host, ahora, cupo(s.host, s.pausa_ms)).all()).results;
      return pedidas.length ? trabajarSitio(env, s, pedidas, fin, cambios) : null;
    }));
    return trabajos.filter(Boolean);
  } finally {
    cambios.push(env.DB.prepare("UPDATE turno SET hasta = 0 WHERE id = 1"));
    await env.DB.batch(cambios);
  }
}

// ---------------------------------------------------------------- API

// Lo que el extractor pide: [{clave, texto, url, cuerpo?, prioridad?}], donde
// `texto` es lo que se hashea para la clave (URL y, en un POST, sus datos).
async function encolar(env, pedidas) {
  if (!Array.isArray(pedidas) || pedidas.length > 1000) throw new Error("se espera una lista de hasta 1000");
  const ahora = Date.now();
  const sentencias = [];
  for (const p of pedidas) {
    const host = new URL(p.url).hostname;
    if (!SITIOS[host]) throw new Error(`sitio no permitido: ${host}`);
    if (!/^[0-9a-f]{64}$/.test(p.clave) || typeof p.texto !== "string" || !p.texto.startsWith(p.url)
        || await sha256(new TextEncoder().encode(p.texto)) !== p.clave) {
      throw new Error(`clave que no corresponde a su URL: ${p.url}`);
    }
    sentencias.push(env.DB.prepare(
      `INSERT INTO pedidas (clave, url, host, cuerpo, prioridad, creada, siguiente, actualizada)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0, ?6)
       ON CONFLICT (clave) DO UPDATE SET
         prioridad = max(prioridad, excluded.prioridad),
         estado = CASE WHEN estado = 'fallida' AND actualizada < ?7 THEN 'pendiente' ELSE estado END,
         intentos = CASE WHEN estado = 'fallida' AND actualizada < ?7 THEN 0 ELSE intentos END,
         siguiente = CASE WHEN estado = 'fallida' AND actualizada < ?7 THEN 0 ELSE siguiente END
       -- Pedir otra vez lo mismo no escribe nada (las escrituras de D1 tienen tope diario).
       WHERE excluded.prioridad > prioridad OR (estado = 'fallida' AND actualizada < ?7)`)
      .bind(p.clave, p.url, host, p.cuerpo ?? null, p.prioridad ?? 0, ahora, ahora - REINTENTAR_FALLIDA));
  }
  for (let i = 0; i < sentencias.length; i += 100) await env.DB.batch(sentencias.slice(i, i + 100));
  return sentencias.length;
}

async function pagina(env, clave) {
  const o = await env.ARCHIVO.get(clavePagina(clave));
  if (o) {
    return new Response(o.body, { headers: {
      "Content-Type": "application/octet-stream",
      "X-Url": o.customMetadata.url, "X-Consultado": o.customMetadata.consultado,
      "X-Sha256": o.customMetadata.sha256 } });
  }
  const p = await env.DB.prepare("SELECT estado, error FROM pedidas WHERE clave = ?").bind(clave).first();
  // 410: la fuente respondió con un error definitivo; 404: todavía no se baja.
  if (p?.estado === "fallida") return new Response(p.error ?? "fallida", { status: 410 });
  return new Response("pendiente\n", { status: 404 });
}

async function estado(env) {
  const sitios = (await env.DB.prepare("SELECT * FROM sitios ORDER BY host").all()).results;
  const colas = (await env.DB.prepare(
    "SELECT host, estado, prioridad, count(*) AS n FROM pedidas GROUP BY host, estado, prioridad").all()).results;
  return { sitios, colas };
}

// Siembra desde el caché de las corridas de Actions anteriores al archivo: una
// página por petición, con el cuerpo tal cual (sin decodificar nada aquí). Solo
// existe mientras el Worker tenga el secret SIEMBRA (se borra al terminar).
async function sembrar(env, request, clave) {
  const url = request.headers.get("X-Url") ?? "";
  const texto = decodeURIComponent(request.headers.get("X-Texto") ?? "");
  const consultado = request.headers.get("X-Consultado") ?? "";
  const huella = request.headers.get("X-Sha256") ?? "";
  let host;
  try { host = new URL(url).hostname; } catch { host = ""; }
  if (!SITIOS[host] || !texto.startsWith(url) || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(consultado)
      || !/^[0-9a-f]{64}$/.test(huella) || await sha256(new TextEncoder().encode(texto)) !== clave) {
    return new Response("página inválida\n", { status: 400 });
  }
  if (await env.ARCHIVO.head(clavePagina(clave))) return json({ nueva: false });
  await env.ARCHIVO.put(clavePagina(clave), request.body, { customMetadata: { url, consultado, sha256: huella } });
  return json({ nueva: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const siembra = url.pathname.match(/^\/sembrar\/([0-9a-f]{64})$/);
    if (siembra && ["PUT", "HEAD"].includes(request.method)) {
      if (!autorizado(request, env.SIEMBRA)) return new Response("no autorizado\n", { status: 401 });
      // HEAD: si ya está, la siembra no la vuelve a mandar.
      if (request.method === "HEAD") {
        return new Response(null, { status: await env.ARCHIVO.head(clavePagina(siembra[1])) ? 200 : 404 });
      }
      return sembrar(env, request, siembra[1]);
    }
    if (!autorizado(request, env.TOKEN)) return new Response("no autorizado\n", { status: 401 });
    const m = url.pathname.match(/^\/pagina\/([0-9a-f]{64})$/);
    if (m && request.method === "GET") return pagina(env, m[1]);
    if (url.pathname === "/pedir" && request.method === "POST") {
      try {
        return json({ encoladas: await encolar(env, await request.json()) });
      } catch (e) {
        return new Response(`${e.message}\n`, { status: 400 });
      }
    }
    if (url.pathname === "/estado") return json(await estado(env));
    return new Response("no encontrado\n", { status: 404 });
  },

  async scheduled(evento, env) {
    for (const c of await ronda(env)) {
      if (c.descargadas || c.bloqueos || c.fallidas) console.log(JSON.stringify(c));
    }
  },
};
