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


class _CursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

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
        Convierte cada parámetro int/bool a str antes de enviarlo a libsql.

        Por qué: el binding de parámetros de la librería 'libsql' pierde precisión
        en enteros grandes (como los IDs de Discord, de 18-19 dígitos) porque los
        pasa por un float64 internamente. Enviarlos como texto evita ese paso;
        SQLite los reconvierte solo a INTEGER por afinidad de columna y se leen
        de vuelta como int de Python, sin ninguna pérdida. Números pequeños
        (XP, niveles, precios, contadores) no se ven afectados de ninguna forma.
        """
        return tuple(str(p) if isinstance(p, (int, bool)) else p for p in params)

    async def _reconnect(self):
        if not self._url or not self._auth:
            return
        try:
            new_conn = await asyncio.to_thread(libsql.connect, database=self._url, auth_token=self._auth)
            self._conn = new_conn
        except Exception:
            pass

    async def execute(self, sql: str, params=()) -> _CursorWrapper:
        try:
            cursor = await asyncio.to_thread(self._conn.execute, sql, self._safe_params(params))
            return _CursorWrapper(cursor)
        except ValueError as e:
            # Turso stream expirado (404 stream not found) — reconecta y reintenta 1 vez
            if "stream not found" in str(e).lower() or "stream_not_found" in str(e).lower():
                await self._reconnect()
                cursor = await asyncio.to_thread(self._conn.execute, sql, self._safe_params(params))
                return _CursorWrapper(cursor)
            raise
        except Exception as e:
            # libsql a veces envuelve el error como Hrana api error con stream not found
            if "stream not found" in str(e).lower():
                await self._reconnect()
                cursor = await asyncio.to_thread(self._conn.execute, sql, self._safe_params(params))
                return _CursorWrapper(cursor)
            raise

    async def executescript(self, script: str):
        # libsql sigue el modelo de sqlite3: separamos por ';' y ejecutamos una a una
        # para máxima compatibilidad (executescript no siempre está expuesto igual).
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for statement in statements:
            await asyncio.to_thread(self._conn.execute, statement)
        await self.commit()

    async def commit(self):
        try:
            await asyncio.to_thread(self._conn.commit)
        except ValueError as e:
            if "stream not found" in str(e).lower():
                await self._reconnect()
                await asyncio.to_thread(self._conn.commit)
            else:
                raise
        except Exception as e:
            if "stream not found" in str(e).lower():
                await self._reconnect()
                await asyncio.to_thread(self._conn.commit)
            else:
                raise

    async def close(self):
        await asyncio.to_thread(self._conn.close)


async def connect(url: str, auth_token: str) -> TursoConnection:
    conn = await asyncio.to_thread(libsql.connect, database=url, auth_token=auth_token)
    return TursoConnection(conn, url, auth_token)
