from __future__ import annotations

import asyncio
import re
import socket
import struct
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_INFO,
    RCON_HOST,
    RCON_PORT,
    RCON_PASS,
    POSTGRES_URL,
    POSTGRES_USER,
    POSTGRES_PASS,
    DC_ROLE_TO_MC,
    MC_ROLE_TO_DC,
)


# Embeds: reusar los del bot si existen, si no, definir minimos
try:
    from utils.embeds import success_embed, error_embed, base_embed
except Exception:  # pragma: no cover
    def success_embed(title, desc, color=COLOR_SUCCESS):
        return discord.Embed(title=title, description=desc, color=color)

    def error_embed(title, desc, color=COLOR_ERROR):
        return discord.Embed(title=title, description=desc, color=color)

    def base_embed(title, desc, color=COLOR_INFO):
        return discord.Embed(title=title, description=desc, color=color)


def strip_codes(text: str) -> str:
    """Quita codigos de color de Minecraft (&x y §x)."""
    return re.sub(r"[§&][0-9a-fk-or]", "", text or "", flags=re.IGNORECASE)


# ----------------------------- RCON ---------------------------------------
def rcon_command(cmd: str, host: str = RCON_HOST, port: int = RCON_PORT,
                 password: str = RCON_PASS, timeout: float = 5.0) -> Optional[str]:
    """Cliente RCON minimo (protocolo Minecraft). Devuelve la respuesta o None."""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        log(f"RCON: no se pudo conectar: {e}")
        return None

    def packet(req_id: int, ptype: int, body: str) -> bytes:
        payload = body.encode("utf-8", "replace") + b"\x00\x00"
        body_full = struct.pack("<ii", req_id, ptype) + payload
        return struct.pack("<i", len(body_full)) + body_full

    def read_packet() -> tuple[int, int, bytes]:
        hdr = _recv_exact(s, 4)
        if not hdr:
            return 0, 0, b""
        size = struct.unpack("<i", hdr)[0]
        data = _recv_exact(s, size)
        req_id, ptype = struct.unpack("<ii", data[:8])
        return req_id, ptype, data[8:]

    try:
        s.settimeout(timeout)
        s.sendall(packet(1, 3, password))  # auth
        rid, rtype, _ = read_packet()
        if rtype != 2:  # 2 = auth response
            log("RCON: fallo de autenticacion")
            return None
        s.sendall(packet(2, 2, cmd))  # command
        resp = b""
        while True:
            rid, rtype, body = read_packet()
            resp += body.rstrip(b"\x00")
            if rid == 2:
                break
        return resp.decode("utf-8", "replace")
    except OSError as e:
        log(f"RCON: error: {e}")
        return None
    finally:
        try:
            s.close()
        except OSError:
            pass


def _recv_exact(s: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def mc_roles(mcname: str) -> set[str]:
    out = rcon_command(f"role list {mcname}")
    if not out:
        return set()
    # Soulrole responde: "Roles de X: a, b, c"
    if ":" in out:
        out = out.split(":", 1)[1]
    roles = {strip_codes(r).strip().lower() for r in out.split(",")}
    roles.discard("")
    return roles


# ----------------------------- Postgres -----------------------------------
def fetch_link(code: str):
    try:
        import psycopg2
    except ImportError:
        log("Falta psycopg2: ejecuta 'pip install psycopg2-binary'")
        return None
    if not POSTGRES_URL:
        log("POSTGRES_URL no configurada")
        return None
    url = POSTGRES_URL
    if url.startswith("postgresql://"):
        url = url[len("postgresql://"):]
    userinfo, _, rest = url.partition("@")
    user = userinfo.split(":")[0] if ":" in userinfo else userinfo
    pw = userinfo.split(":", 1)[1] if ":" in userinfo else POSTGRES_PASS
    dbname = rest.split("/")[1] if "/" in rest else ""
    conn = None
    try:
        conn = psycopg2.connect(host=rest.split("/")[0].split(":")[0],
                                port=int((rest.split("/")[0].split(":") + ["5432"])[1]) if ":" in rest.split("/")[0] else 5432,
                                dbname=dbname, user=user or POSTGRES_USER, password=pw or POSTGRES_PASS,
                                sslmode="require", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT code,uuid,mcname,discord_id,expires FROM aegis_links WHERE code=%s", (code,))
        row = cur.fetchone()
        if not row:
            return None
        code_v, uuid_v, mcname_v, discord_v, expires_v = row
        if expires_v and expires_v < __import__("time").time() * 1000:
            return None
        return {"code": code_v, "uuid": uuid_v, "mcname": mcname_v,
                "discord_id": discord_v, "expires": expires_v}
    except Exception as e:
        log(f"Postgres link error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def bind_link(code: str, discord_id: str) -> bool:
    try:
        import psycopg2
    except ImportError:
        return False
    if not POSTGRES_URL:
        return False
    url = POSTGRES_URL
    if url.startswith("postgresql://"):
        url = url[len("postgresql://"):]
    userinfo, _, rest = url.partition("@")
    user = userinfo.split(":")[0] if ":" in userinfo else userinfo
    pw = userinfo.split(":", 1)[1] if ":" in userinfo else POSTGRES_PASS
    dbname = rest.split("/")[1] if "/" in rest else ""
    conn = None
    try:
        conn = psycopg2.connect(host=rest.split("/")[0].split(":")[0],
                                port=int((rest.split("/")[0].split(":") + ["5432"])[1]) if ":" in rest.split("/")[0] else 5432,
                                dbname=dbname, user=user or POSTGRES_USER, password=pw or POSTGRES_PASS,
                                sslmode="require", connect_timeout=5)
        cur = conn.cursor()
        cur.execute("UPDATE aegis_links SET discord_id=%s WHERE code=%s", (discord_id, code))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        log(f"Postgres bind error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def log(msg: str):
    print(f"[code_sync] {msg}")


class CodeSyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="code", description="Vincula tu cuenta de Minecraft con el codigo de /code")
    @app_commands.describe(codigo="El codigo de 6 digitos que te dio el servidor en Minecraft")
    async def code(self, interaction: discord.Interaction, codigo: str):
        await interaction.response.defer(ephemeral=True)
        try:
            link = await asyncio.to_thread(fetch_link, codigo.strip())
        except Exception:
            link = None
        if not link:
            await interaction.followup.send(embed=error_embed(
                "Codigo invalido", "Ese codigo no existe o ya caduco (10 min). Usa /code en Minecraft para generar uno."))
            return
        if not await asyncio.to_thread(bind_link, codigo.strip(), str(interaction.user.id)):
            await interaction.followup.send(embed=error_embed(
                "Error", "No pude guardar la vinculacion en la base de datos."))
            return

        mcname = link["mcname"] or link["uuid"]
        mc_roles_list = await asyncio.to_thread(mc_roles, mcname)
        member = interaction.user
        dc_role_ids = {str(r.id) for r in member.roles}

        added_mc = []
        added_dc = []
        # DC -> MC
        for dcid, mcrole in DC_ROLE_TO_MC.items():
            if dcid in dc_role_ids and mcrole.lower() not in mc_roles_list:
                resp = await asyncio.to_thread(rcon_command, f"role adduser {mcname} {mcrole}")
                if resp is not None:
                    added_mc.append(mcrole)
        # MC -> DC
        for mcrole, dcid in MC_ROLE_TO_DC.items():
            if mcrole.lower() in mc_roles_list and dcid not in dc_role_ids:
                role = interaction.guild.get_role(int(dcid))
                if role:
                    try:
                        await member.add_roles(role, reason="Sincronizacion SoulRole")
                        added_dc.append(mcrole)
                    except discord.HTTPException:
                        pass

        lines = [f"Cuenta de Minecraft **{mcname}** vinculada correctamente.", ""]
        lines.append("• Roles agregados en Minecraft: " + (", ".join(added_mc) if added_mc else "ninguno"))
        lines.append("• Roles agregados en Discord: " + (", ".join(added_dc) if added_dc else "ninguno"))
        if not added_mc and not added_dc:
            lines.append("• Tus roles ya estaban sincronizados en ambas plataformas.")
        try:
            await interaction.followup.send(embed=base_embed("Vinculacion completa", "\n".join(lines), color=COLOR_SUCCESS))
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(CodeSyncCog(bot))
