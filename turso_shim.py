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
    def __init__(self, url: str, auth_token: str):
        self._conn = libsql.connect(database=url, auth_token=auth_token)

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

    async def execute(self, sql: str, params=()) -> _CursorWrapper:
        cursor = await asyncio.to_thread(self._conn.execute, sql, self._safe_params(params))
        return _CursorWrapper(cursor)

    async def executescript(self, script: str):
        # libsql sigue el modelo de sqlite3: separamos por ';' y ejecutamos una a una
        # para máxima compatibilidad (executescript no siempre está expuesto igual).
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for statement in statements:
            await asyncio.to_thread(self._conn.execute, statement)
        await self.commit()

    async def commit(self):
        await asyncio.to_thread(self._conn.commit)

    async def close(self):
        await asyncio.to_thread(self._conn.close)


async def connect(url: str, auth_token: str) -> TursoConnection:
    return TursoConnection(url, auth_token)
