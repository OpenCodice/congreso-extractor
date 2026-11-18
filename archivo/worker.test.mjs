// Pruebas del ritmo por sitio y de /salud: node --test (sin dependencias).
import assert from "node:assert/strict";
import { timingSafeEqual } from "node:crypto";
import { test } from "node:test";

import worker, {
  DURACION, PAUSA_MAX, SITIOS, cupo, esperaBloqueo, esperaSiguiente, resumenSalud,
  trasBloqueo, trasGuardada, trasRonda,
} from "./worker.js";

const SENADO = "www.senado.gob.mx";
const MINUTO = 60_000;
const HORA = 3600_000;

// Una invocación del cron para un sitio, con el reloj simulado: las mismas
// decisiones que `trabajarSitio`, sin red. `responde(t)` dice si el sitio
// sirve la página o la bloquea. Devuelve el sitio y las horas de sus peticiones.
function invocacion(sitio, ahora, pendientes, responde) {
  const peticiones = [];
  if (!(sitio.espera_hasta < ahora) || !pendientes) return { sitio, peticiones };
  const fin = ahora + DURACION;
  let reloj = ahora, ultima = 0, descargadas = 0, bloqueada = false;
  for (let i = 0; i < Math.min(pendientes, cupo(sitio.host, sitio.pausa_ms)); i++) {
    const espera = esperaSiguiente({ hechas: peticiones.length, ultima, pausa: sitio.pausa_ms, ahora: reloj, fin });
    if (espera === null) break;
    reloj += espera;
    ultima = reloj;
    peticiones.push(reloj);
    reloj += 500;
    if (responde(ultima)) {
      sitio = trasGuardada(sitio);
      descargadas++;
    } else {
      sitio = trasBloqueo(sitio, reloj);
      bloqueada = true;
      break;
    }
  }
  return { sitio: trasRonda(sitio, { descargadas, bloqueada, ultima }, reloj), peticiones };
}

function simular(sitio, desde, minutos, responde, pendientes = 1000) {
  const peticiones = [];
  for (let m = 0; m < minutos; m++) {
    const r = invocacion(sitio, desde + m * MINUTO, pendientes - peticiones.length, responde);
    sitio = r.sitio;
    peticiones.push(...r.peticiones);
  }
  return { sitio, peticiones };
}

test("el cupo nunca es cero, por larga que sea la pausa", () => {
  for (const host of Object.keys(SITIOS)) {
    assert.equal(cupo(host, SITIOS[host].pausa), SITIOS[host].cupo);
    for (const pausa of [DURACION, DURACION + 1, 57_224, PAUSA_MAX]) assert.equal(cupo(host, pausa), 1);
  }
  assert.equal(cupo(SENADO, 20_000), 2);
});

test("la primera petición de una invocación sale siempre; las demás, solo si cabe su pausa", () => {
  const fin = DURACION;
  assert.equal(esperaSiguiente({ hechas: 0, ultima: 0, pausa: PAUSA_MAX, ahora: 0, fin }), 0);
  assert.equal(esperaSiguiente({ hechas: 1, ultima: 0, pausa: 15_000, ahora: 2_000, fin }), 13_000);
  assert.equal(esperaSiguiente({ hechas: 2, ultima: 15_000, pausa: 15_000, ahora: 31_000, fin }), 0);
  assert.equal(esperaSiguiente({ hechas: 3, ultima: 31_000, pausa: 15_000, ahora: 32_000, fin }), null);
  assert.equal(esperaSiguiente({ hechas: 1, ultima: 0, pausa: 57_224, ahora: 1_000, fin }), null);
});

test("seis bloqueos, cada uno tras una descarga, dejan la pausa del Senado en 57 224 ms", () => {
  let sitio = { host: SENADO, pausa_ms: 15_000, bloqueos: 0, ultimo_bloqueo: 0, espera_hasta: 0 };
  for (let i = 0; i < 6; i++) sitio = trasBloqueo(trasGuardada(sitio), 1_000_000 + i * 11 * MINUTO);
  assert.equal(sitio.pausa_ms, 57_224);
  assert.equal(sitio.bloqueos, 1);
  assert.equal(sitio.espera_hasta - sitio.ultimo_bloqueo, esperaBloqueo(1));
});

test("el Senado con pausa de 57 224 ms se vuelve a intentar y converge a su pausa base", () => {
  const bloqueo = 1_794_978_422_991;
  const atascado = { host: SENADO, pausa_ms: 57_224, bloqueos: 1, ultimo_bloqueo: bloqueo,
                     espera_hasta: bloqueo + 10 * MINUTO };
  const desde = bloqueo + 5 * HORA;

  const primera = invocacion(atascado, desde, 302, () => true);
  assert.equal(primera.peticiones.length, 1);
  assert.equal(primera.sitio.pausa_ms, 51_502);
  assert.equal(primera.sitio.bloqueos, 0);

  const { sitio, peticiones } = simular(atascado, desde, 30, () => true);
  assert.equal(sitio.pausa_ms, SITIOS[SENADO].pausa);
  // 13 invocaciones de bajada (57 224 × 0.9¹³ < 15 000) y el resto ya a su ritmo normal.
  const bajada = simular(atascado, desde, 13, () => true);
  assert.equal(bajada.sitio.pausa_ms, SITIOS[SENADO].pausa);
  assert.ok(simular(atascado, desde, 12, () => true).sitio.pausa_ms > SITIOS[SENADO].pausa);
  assert.equal(simular(sitio, desde + 30 * MINUTO, 1, () => true).peticiones.length, SITIOS[SENADO].cupo);
  // Nunca dos peticiones más juntas que la pausa base.
  for (let i = 1; i < peticiones.length; i++) {
    assert.ok(peticiones[i] - peticiones[i - 1] >= SITIOS[SENADO].pausa, `peticiones ${i - 1} y ${i}`);
  }
});

test("un sitio que sigue bloqueando recibe sondeos cada vez más espaciados, no un martilleo", () => {
  const atascado = { host: SENADO, pausa_ms: 57_224, bloqueos: 1, ultimo_bloqueo: 0, espera_hasta: 0 };
  const desde = 5 * HORA;
  const { sitio, peticiones } = simular(atascado, desde, 24 * 60, () => false);
  assert.equal(sitio.pausa_ms, PAUSA_MAX);
  // 10, 20, 40… min entre sondeos, con tope de 6 h: en un día, 8.
  assert.equal(peticiones.length, 8);
  const esperas = peticiones.slice(1).map((t, i) => t - peticiones[i]);
  esperas.forEach((e, i) => assert.ok(e >= esperaBloqueo(i + 2), `sondeo ${i + 1}`));

  // Con la pausa en su máximo y el sitio ya sin bloquear: un sondeo por pausa
  // (más de un minuto), y con cada éxito baja hasta la base.
  const libre = { ...sitio, espera_hasta: 0 };
  const despues = desde + 30 * HORA;
  const dos = simular(libre, despues, 4, () => true);
  assert.deepEqual(dos.peticiones.map((t) => Math.round((t - despues) / MINUTO)), [0, 2]);
  assert.equal(simular(libre, despues, 60, () => true).sitio.pausa_ms, SITIOS[SENADO].pausa);
});

test("la pausa no baja sin descargas ni antes de una hora del último bloqueo", () => {
  const sitio = { host: SENADO, pausa_ms: 30_000, bloqueos: 0, ultimo_bloqueo: 0, espera_hasta: 0 };
  assert.equal(trasRonda(sitio, { descargadas: 0, bloqueada: false, ultima: 0 }, 2 * HORA).pausa_ms, 30_000);
  assert.equal(trasRonda({ ...sitio, ultimo_bloqueo: 2 * HORA - MINUTO },
    { descargadas: 1, bloqueada: false, ultima: 2 * HORA }, 2 * HORA).pausa_ms, 30_000);
  const bajo = trasRonda(sitio, { descargadas: 1, bloqueada: false, ultima: 2 * HORA }, 2 * HORA + 500);
  assert.equal(bajo.pausa_ms, 27_000);
  assert.equal(bajo.espera_hasta, 2 * HORA + 27_000);
  // Tras un bloqueo manda su espera, no la pausa.
  const bloqueado = trasBloqueo(sitio, 2 * HORA);
  assert.deepEqual(trasRonda(bloqueado, { descargadas: 1, bloqueada: true, ultima: 2 * HORA }, 2 * HORA), bloqueado);
});

test("resumenSalud: por sitio, pausa, pendientes, la más antigua y el último éxito", () => {
  const ahora = Date.UTC(2026, 10, 18, 10, 0, 0);
  const r = resumenSalud(
    [{ host: SENADO, pausa_ms: 57_224, bloqueos: 1, ultimo_bloqueo: ahora - 5 * HORA, espera_hasta: ahora - 4 * HORA },
     { host: "sitio.ajeno.mx", pausa_ms: 1, bloqueos: 0, ultimo_bloqueo: 0, espera_hasta: 0 }],
    [{ host: SENADO, n: 302, creada: ahora - 7 * HORA }],
    [{ host: "sil.gobernacion.gob.mx", ultimo: ahora - MINUTO }],
    ahora);
  assert.equal(r.ahora, "2026-11-18T10:00:00Z");
  assert.deepEqual(Object.keys(r.sitios).sort(), Object.keys(SITIOS).sort());
  assert.deepEqual(r.sitios[SENADO], {
    pausa_ms: 57_224, pausa_base_ms: 15_000, bloqueos_seguidos: 1, ultimo_bloqueo: "2026-11-18T05:00:00Z",
    en_espera_hasta: null, pendientes: 302, pendiente_mas_antigua: "2026-11-18T03:00:00Z", ultimo_exito: null,
  });
  assert.deepEqual(r.sitios["sil.gobernacion.gob.mx"], {
    pausa_ms: 6000, pausa_base_ms: 6000, bloqueos_seguidos: 0, ultimo_bloqueo: null,
    en_espera_hasta: null, pendientes: 0, pendiente_mas_antigua: null, ultimo_exito: "2026-11-18T09:59:00Z",
  });
});

// D1 de mentira: responde cada consulta por el nombre de su tabla.
function base(tablas) {
  return { prepare: (sql) => ({ all: async () => {
    const tabla = sql.match(/FROM (\w+)/)[1];
    if (!(tabla in tablas)) throw new Error(`no such table: ${tabla}`);
    return { results: tablas[tabla] };
  } }) };
}

test("GET /salud pide el mismo token que el resto y no falla si aún no hay tabla de éxitos", async () => {
  // Node no trae la extensión de Workers que compara en tiempo constante.
  crypto.subtle.timingSafeEqual ??= timingSafeEqual;
  const env = { TOKEN: "secreto", DB: base({
    sitios: [{ host: SENADO, pausa_ms: 57_224, bloqueos: 1, ultimo_bloqueo: 1, espera_hasta: 2 }],
    pedidas: [{ host: SENADO, n: 302, creada: Date.UTC(2026, 10, 18, 3, 7) }],
  }) };
  const pedir = (cabeceras) => worker.fetch(new Request("https://archivo/salud", { headers: cabeceras }), env);
  assert.equal((await pedir({})).status, 401);
  assert.equal((await pedir({ Authorization: "Bearer otro" })).status, 401);
  const r = await pedir({ Authorization: "Bearer secreto" });
  assert.equal(r.status, 200);
  const cuerpo = await r.json();
  assert.equal(cuerpo.sitios[SENADO].pendientes, 302);
  assert.equal(cuerpo.sitios[SENADO].pendiente_mas_antigua, "2026-11-18T03:07:00Z");
  assert.equal(cuerpo.sitios[SENADO].ultimo_exito, null);
  assert.ok(!JSON.stringify(cuerpo).includes("secreto"));
});
