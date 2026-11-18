-- Cola de descargas del archivo (ver worker.js).
CREATE TABLE IF NOT EXISTS pedidas (
  clave TEXT PRIMARY KEY,          -- sha256 de la URL (y los datos del POST), como red._ruta
  url TEXT NOT NULL,
  host TEXT NOT NULL,
  cuerpo TEXT,                     -- cuerpo del POST en base64, tal como se envía
  prioridad INTEGER NOT NULL DEFAULT 0,  -- 1: falta en el archivo; 0: refrescar una copia vieja
  estado TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | fallida
  intentos INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  creada INTEGER NOT NULL,
  siguiente INTEGER NOT NULL DEFAULT 0,
  actualizada INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS pedidas_turno ON pedidas (host, estado, prioridad DESC, creada);

-- Ritmo y bloqueos de cada sitio.
CREATE TABLE IF NOT EXISTS sitios (
  host TEXT PRIMARY KEY,
  pausa_ms INTEGER NOT NULL,
  bloqueos INTEGER NOT NULL DEFAULT 0,
  ultimo_bloqueo INTEGER NOT NULL DEFAULT 0,
  espera_hasta INTEGER NOT NULL DEFAULT 0,
  descargadas INTEGER NOT NULL DEFAULT 0
);

-- Una sola ronda del cron a la vez.
CREATE TABLE IF NOT EXISTS turno (id INTEGER PRIMARY KEY, hasta INTEGER NOT NULL);
INSERT OR IGNORE INTO turno (id, hasta) VALUES (1, 0);

-- Última descarga lograda de cada sitio, para /salud (el Worker la crea si falta).
CREATE TABLE IF NOT EXISTS exitos (host TEXT PRIMARY KEY, ultimo INTEGER NOT NULL);
