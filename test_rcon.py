"""Diagnostico rapido para el sync /code del SoulBot.
Uso (dentro del venv):  python test_rcon.py
Verifica: RCON del server, Postgres (tabla aegis_links) y el mapeo de roles.
"""
from __future__ import annotations

import os
import socket
import struct
import sys

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*a, **k):
        return False

load_dotenv()

RCON_HOST = os.getenv("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
RCON_PASS = os.getenv("RCON_PASS", "")
POSTGRES_URL = os.getenv("POSTGRES_URL", "")


def rcon_packet(pkt_id: int, body: str, req_id: int = 1) -> bytes:
    payload = struct.pack("<ii", req_id, pkt_id) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def rcon_read(sock) -> tuple[int, int, str]:
    length = struct.unpack("<i", sock.recv(4))[0]
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            break
        data += chunk
    req_id, pkt_id = struct.unpack("<ii", data[:8])
    body = data[8:-2].decode("utf-8", "replace")
    return req_id, pkt_id, body


def test_rcon() -> bool:
    print(f"\n[1/2] RCON -> {RCON_HOST}:{RCON_PORT}")
    if not RCON_PASS:
        print("  ! RCON_PASS vacio en .env")
        return False
    try:
        s = socket.create_connection((RCON_HOST, RCON_PORT), timeout=5)
    except Exception as e:
        print(f"  X No se conecta (server reiniciado con enable-rcon=true?): {e}")
        return False
    s.sendall(rcon_packet(3, RCON_PASS, 1))  # AUTH
    rid, pid, _ = rcon_read(s)
    if rid == -1:
        print("  X Auth fallo (password incorrecto)")
        s.close()
        return False
    s.sendall(rcon_packet(2, "list", 2))  # EXEC
    rid, pid, resp = rcon_read(s)
    print(f"  OK RCON responde: {resp.strip()[:120]}")
    s.close()
    return True


def test_postgres() -> bool:
    print("\n[2/2] Postgres -> aegis_links")
    if not POSTGRES_URL:
        print("  ! POSTGRES_URL vacio en .env")
        return False
    try:
        import psycopg2  # noqa
    except Exception:
        print("  ! psycopg2-binary no instalado (pip install psycopg2-binary)")
        return False
    try:
        url = POSTGRES_URL
        if url.startswith("postgresql://"):
            url = url[len("postgresql://"):]
        userinfo, _, rest = url.partition("@")
        user = userinfo.split(":")[0] if ":" in userinfo else userinfo
        pw = userinfo.split(":", 1)[1] if ":" in userinfo else ""
        dbname = rest.split("/")[1] if "/" in rest else ""
        host = rest.split("/")[0].split(":")[0]
        port = int((rest.split("/")[0].split(":") + ["5432"])[1]) if ":" in rest.split("/")[0] else 5432
        conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=pw, sslmode="require", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='aegis_links'")
        ok = cur.fetchone() is not None
        cur.close()
        conn.close()
        print(f"  {'OK' if ok else 'X'} tabla aegis_links {'existe' if ok else 'NO existe (arranca Soulguard para crearla)'}")
        return ok
    except Exception as e:
        print(f"  X Error Postgres: {e}")
        return False


if __name__ == "__main__":
    a = test_rcon()
    b = test_postgres()
    print("\nRESULTADO:")
    print(f"  RCON    : {'OK' if a else 'MAL'}")
    print(f"  Postgres: {'OK' if b else 'MAL'}")
    sys.exit(0 if (a and b) else 1)
