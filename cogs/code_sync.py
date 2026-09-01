from __future__ import annotations

import asyncio
import re
import secrets
import socket
import string
import struct
import time
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


# ── Seguridad RCON ──────────────────────────────────────
_MCNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
_MCROLE_RE = re.compile(r"^[A-Za-z0-9_ ]{1,32}$")
_RCON_LAST: dict[int, float] = {}  # discord_id -> timestamp

def sanitize_mcname(name: str) -> str | None:
    name = (name or "").strip()
    return name if _MCNAME_RE.match(name) else None

def sanitize_mcrole(role: str) -> str | None:
    # roles de Soulrole vienen en minúsculas con espacios (ej. "leyenda soulseeker")
    r = (role or "").strip().lower()
    return r if _MCROLE_RE.match(r) else None

def check_rcon_cooldown(discord_id: int, seconds: int = 10) -> bool:
    now = time.time()
    last = _RCON_LAST.get(discord_id, 0)
    if now - last < seconds:
        return False
    _RCON_LAST[discord_id] = now
    return True

def is_public_rcon() -> bool:
    host = (RCON_HOST or "").lower()
    return "bore.pub" in host or "trycloudflare.com" in host or "localhost.run" in host or "playit.gg" in host

def is_private_host(host: str) -> bool:
    import ipaddress
    h = (host or "").strip().lower()
    if h in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        # Tailscale usa 100.64/10 CGNAT, también privado RFC1918 y loopback
        return ip.is_private or ip.is_loopback or str(ip).startswith("100.")
    except ValueError:
        return False  # hostname -> no es IP privada

def rcon_allowed() -> bool:
    from config import RCON_ALLOW_PUBLIC
    if is_public_rcon() and not RCON_ALLOW_PUBLIC:
        log("RCON bloqueado: host público sin RCON_ALLOW_PUBLIC=1. Cambia a Tailscale 100.x.x.x")
        return False
    return True


# ----------------------------- RCON ---------------------------------------
def rcon_command(cmd: str, host: str = RCON_HOST, port: int = RCON_PORT,
                 password: str = RCON_PASS, timeout: float = 5.0) -> Optional[str]:
    """Cliente RCON minimo (protocolo Minecraft). Devuelve la respuesta o None."""
    # Nunca loguear la contraseña
    if not rcon_allowed():
        return None
    if is_public_rcon():
        log("RCON: AVISO usas bore.pub/túnel público — la contraseña viaja sin cifrado. Cambia a Tailscale 100.x.x.x en producción.")
    elif not is_private_host(host):
        log(f"RCON: host {host} no es IP privada/Tailscale — verifica firewall. Usa 100.x.x.x.")
    # Sanitizar comando: solo permitir chars seguros (evita inyección ; && etc.)
    if ";" in cmd or "&&" in cmd or "||" in cmd or "\n" in cmd or "`" in cmd or "$(" in cmd:
        log(f"RCON: comando bloqueado por caracteres inseguros: {cmd[:60]}")
        return None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        log(f"RCON: no se pudo conectar a {host}:{port} — {e}")
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
        cur.execute("SELECT code,uuid,mcname,discord_id,expires,role FROM aegis_links WHERE code=%s", (code,))
        row = cur.fetchone()
        if not row:
            return None
        code_v, uuid_v, mcname_v, discord_v, expires_v, role_v = row
        if expires_v and expires_v < time.time() * 1000:
            return None
        return {"code": code_v, "uuid": uuid_v, "mcname": mcname_v,
                "discord_id": discord_v, "expires": expires_v, "role": role_v}
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


def _connect_postgres():
    import psycopg2
    url = POSTGRES_URL
    if url.startswith("postgresql://"):
        url = url[len("postgresql://"):]
    userinfo, _, rest = url.partition("@")
    user = userinfo.split(":")[0] if ":" in userinfo else userinfo
    pw = userinfo.split(":", 1)[1] if ":" in userinfo else POSTGRES_PASS
    dbname = rest.split("/")[1] if "/" in rest else ""
    return psycopg2.connect(host=rest.split("/")[0].split(":")[0],
                            port=int((rest.split("/")[0].split(":") + ["5432"])[1]) if ":" in rest.split("/")[0] else 5432,
                            dbname=dbname, user=user or POSTGRES_USER, password=pw or POSTGRES_PASS,
                            sslmode="require", connect_timeout=5)


def consume_link(code: str) -> bool:
    if not POSTGRES_URL:
        return False
    conn = None
    try:
        conn = _connect_postgres()
        cur = conn.cursor()
        cur.execute("DELETE FROM aegis_links WHERE code=%s", (code,))
        conn.commit()
        return True
    except Exception as e:
        log(f"Postgres consume error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def generate_giveaway_code(role_id: str, creator_id: str):
    if not POSTGRES_URL:
        log("POSTGRES_URL no configurada")
        return None
    alphabet = string.ascii_uppercase + string.digits
    conn = None
    try:
        conn = _connect_postgres()
        cur = conn.cursor()
        for _ in range(8):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            cur.execute("SELECT 1 FROM aegis_links WHERE code=%s", (code,))
            if cur.fetchone():
                continue
            expires = int(time.time() * 1000) + 7 * 24 * 3600 * 1000
            try:
                cur.execute(
                    "INSERT INTO aegis_links (code,uuid,mcname,discord_id,expires,role) "
                    "VALUES (%s,NULL,NULL,NULL,%s,%s)",
                    (code, expires, str(role_id)))
                conn.commit()
                return code
            except psycopg2.IntegrityError:
                conn.rollback()
                continue
        return None
    except Exception as e:
        log(f"Postgres giveaway error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def migrate_role_column():
    if not POSTGRES_URL:
        return
    conn = None
    try:
        conn = _connect_postgres()
        cur = conn.cursor()
        stmts = [
            ("ALTER TABLE aegis_links ADD COLUMN role TEXT",
             "Columna 'role' agregada a aegis_links"),
            ("ALTER TABLE aegis_links ALTER COLUMN uuid DROP NOT NULL",
             "Columna 'uuid' ahora acepta NULL (codigos de regalo)"),
        ]
        for stmt, label in stmts:
            try:
                cur.execute(stmt)
                conn.commit()
                log(label)
            except Exception as e:
                conn.rollback()
                msg = str(e).lower()
                if "already exists" in msg or "duplicate" in msg:
                    pass
                else:
                    log(f"migrate ignorado ({stmt}): {e}")
    except Exception as e:
        log(f"migrate error: {e}")
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
        # rate-limit 10s por usuario para no spamear RCON/Postgres
        if not check_rcon_cooldown(interaction.user.id, 10):
            await interaction.response.send_message(embed=error_embed("Espera unos segundos", "Estás ejecutando /code muy rápido. Prueba en 10s."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        codigo = (codigo or "").strip().upper()
        if not re.match(r"^[A-Z0-9]{6,8}$", codigo):
            await interaction.followup.send(embed=error_embed("Código inválido", "Debe ser de 6-8 caracteres alfanuméricos (ej. `AB12CD`)."))
            return
        try:
            link = await asyncio.to_thread(fetch_link, codigo)
        except Exception:
            link = None
        if not link:
            await interaction.followup.send(embed=error_embed(
                "Codigo invalido", "Ese codigo no existe o ya caduco (10 min). Usa /code en Minecraft para generar uno."))
            return
        if not await asyncio.to_thread(bind_link, codigo, str(interaction.user.id)):
            await interaction.followup.send(embed=error_embed(
                "Error", "No pude guardar la vinculacion en la base de datos."))
            return

        # Codigo de regalo (gift): no tiene mcname/uuid, solo role -> asigna rol y consume sin validar nick
        gift_role = link.get("role")
        if gift_role:
            # es un codigo de regalo, no necesita cuenta MC
            if interaction.guild is not None:
                role = interaction.guild.get_role(int(gift_role))
                if role:
                    try:
                        await interaction.user.add_roles(role, reason="Codigo de regalo SoulSeeker")
                    except discord.HTTPException:
                        pass
                    await asyncio.to_thread(consume_link, codigo.strip())
                    await interaction.followup.send(embed=base_embed(f"Código de regalo canjeado ✅\nHas recibido {role.mention} (7 días de validez).", color=COLOR_SUCCESS, title="¡Regalo canjeado!"))
                    return
                else:
                    await interaction.followup.send(embed=error_embed("Rol no encontrado", "El rol de este código ya no existe."))
                    return
            else:
                await interaction.followup.send(embed=error_embed("Error", "No pude asignar el rol."))
                return

        raw_name = link["mcname"] or link["uuid"] or ""
        mcname = sanitize_mcname(raw_name)
        if not mcname:
            await interaction.followup.send(embed=error_embed("Nombre de Minecraft inválido", f"`{raw_name[:20]}` no parece un nick válido. Contacta staff."))
            return
        mc_roles_list = await asyncio.to_thread(mc_roles, mcname)
        member = interaction.user
        dc_role_ids = {str(r.id) for r in member.roles}

        added_mc = []
        added_dc = []
        # DC -> MC (con sanitización)
        for dcid, mcrole in DC_ROLE_TO_MC.items():
            sm = sanitize_mcrole(mcrole)
            if not sm:
                continue
            if dcid in dc_role_ids and sm not in mc_roles_list:
                resp = await asyncio.to_thread(rcon_command, f"role adduser {mcname} {sm}")
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

        # Codigo de regalo: asignar rol y consumir (una sola vez)
        gift_role = link.get("role")
        if gift_role and interaction.guild is not None:
            role = interaction.guild.get_role(int(gift_role))
            if role:
                try:
                    await member.add_roles(role, reason="Codigo de regalo SoulSeeker")
                    added_dc.append(f"regalo: {role.name}")
                except discord.HTTPException:
                    pass
            await asyncio.to_thread(consume_link, codigo.strip())

        lines = [f"Cuenta de Minecraft **{mcname}** vinculada correctamente.", ""]
        lines.append("• Roles agregados en Minecraft: " + (", ".join(added_mc) if added_mc else "ninguno"))
        lines.append("• Roles agregados en Discord: " + (", ".join(added_dc) if added_dc else "ninguno"))
        if not added_mc and not added_dc:
            lines.append("• Tus roles ya estaban sincronizados en ambas plataformas.")
        try:
            await interaction.followup.send(embed=base_embed("\n".join(lines), color=COLOR_SUCCESS, title="Vinculacion completa"))
        except discord.NotFound:
            pass


    @app_commands.command(name="codegenerate", description="Genera un codigo de regalo que otorga un rol al canjearlo")
    @app_commands.describe(rol="Rol que recibira quien canjee el codigo")
    @app_commands.checks.has_permissions(administrator=True)
    async def codegenerate(self, interaction: discord.Interaction, rol: discord.Role):
        await interaction.response.defer(ephemeral=True)
        code = await asyncio.to_thread(generate_giveaway_code, str(rol.id), str(interaction.user.id))
        if not code:
            await interaction.followup.send(embed=error_embed(
                "Error", "No pude generar el codigo. Intentalo de nuevo."))
            return
        await interaction.followup.send(embed=success_embed(
            "Codigo de regalo generado",
            f"**Codigo:** `{code}`\n**Rol:** {rol.mention}\n**Valido:** 7 dias\n\n"
            f"Quien lo canjee con `/code {code}` recibira el rol automaticamente."))

async def setup(bot: commands.Bot):
    await asyncio.to_thread(migrate_role_column)
    await bot.add_cog(CodeSyncCog(bot))
