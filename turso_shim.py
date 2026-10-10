"""
Adaptador para usar Turso (libSQL, compatible con SQLite) con la misma
interfaz async que aiosqlite, para no tener que tocar ninguna consulta
ya escrita en database.py.

Por qué: Render Free no soporta discos persistentes, así que SQLite local
se borra en cada redeploy. Turso da una base SQLite-compatible gratis y
persistente en la nube.
"""
from __future__ import annotations
import asyncio
import libsql

# Errores transitorios de Turso/Hrana: merece la pena reconectar y reintentar
# (el stream se expira o la conexión HTTP se corta a mitad). No son bugs del SQL.
_TRANSIENT = (
    "stream not found", "stream_not_found",
    "connection closed before message completed",
    "connection reset", "connection aborted", "connection refused",
    "stream was idle", "sqlite_busy", "http error", "502", "503", "504",
    "timed out", "timeout", "broken pipe", "remotedisconnected", "incompleteread",
)


def _is_transient(e: Exception) -> bool:
    s = str(e).lower()
    return any(tok in s for tok in _TRANSIENT)


class _CursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    async def fetchone(self):
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self):
        return await asyncio.to_thread(self._cursor.fetchall)


class TursoConnection:
    def __init__(self, conn, url: str | None = None, auth_token: str | None = None):
        self._conn = conn
        self._url = url
        self._auth = auth_token

    @staticmethod
    def _safe_params(params):
        """
        Convierte parámetros antes de enviarlos a libsql.

        Por qué: el binding de parámetros de la librería 'libsql' pierde precisión
        en enteros grandes (como los IDs de Discord, de 18-19 dígitos) porque los
        pasa por un float64 internamente. Enviarlos como texto evita ese paso;
        SQLite los reconvierte solo a INTEGER por afinidad de columna y se leen
        de vuelta como int de Python, sin ninguna pérdida. Números pequeños
        (XP, niveles, precios, contadores) no se ven afectados de ninguna forma.
        Los bool van como 0/1 (no como "True"/"False").
        """
        def _conv(p):
            if isinstance(p, bool):
                return int(p)
            if isinstance(p, int):
                return str(p)
            return p
        return tuple(_conv(p) for p in params)

    async def _reconnect(self):
        if not self._url or not self._auth:
            return
        try:
            new_conn = await asyncio.to_thread(libsql.connect, database=self._url, auth_token=self._auth)
            self._conn = new_conn
        except Exception:
            pass

    async def execute(self, sql: str, params=()) -> _CursorWrapper:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                cursor = await asyncio.to_thread(self._conn.execute, sql, self._safe_params(params))
                return _CursorWrapper(cursor)
            except Exception as e:
                last_exc = e
                if not _is_transient(e):
                    raise
                # Turso stream expirado / conexión cortada — reconecta y reintenta con backoff
                await self._reconnect()
                await asyncio.sleep(0.3 * (attempt + 1))
        raise last_exc if last_exc else RuntimeError("execute falló")

    async def executescript(self, script: str):
        # libsql sigue el modelo de sqlite3: separamos por ';' y ejecutamos una a una
        # para máxima compatibilidad (executescript no siempre está expuesto igual).
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for statement in statements:
            await asyncio.to_thread(self._conn.execute, statement)
        await self.commit()

    async def commit(self):
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                await asyncio.to_thread(self._conn.commit)
                return
            except Exception as e:
                last_exc = e
                if not _is_transient(e):
                    raise
                await self._reconnect()
                await asyncio.sleep(0.3 * (attempt + 1))
        raise last_exc if last_exc else RuntimeError("commit falló")

    async def close(self):
        await asyncio.to_thread(self._conn.close)


async def connect(url: str, auth_token: str) -> TursoConnection:
    conn = await asyncio.to_thread(libsql.connect, database=url, auth_token=auth_token)
    return TursoConnection(conn, url, auth_token)
