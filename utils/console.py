from __future__ import annotations
"""Consola de administración vía stdin (consola del panel tipo Pterodactyl).

Comandos:
  help                              - muestra ayuda
  servers                           - lista servidores donde está el bot
  say <canal_id> <texto>            - habla como SoulBot en un canal
  dm <usuario_id> <texto>           - envía un DM como SoulBot
  stop                              - apaga el bot
"""
import asyncio
import sys


async def console_loop(bot):
    print("[consola] SoulBot console lista. Escribe 'help'.", flush=True)
    while True:
        try:
            line = await asyncio.to_thread(sys.stdin.readline)
        except Exception:
            await asyncio.sleep(5)
            continue
        if not line:
            await asyncio.sleep(5)
            continue
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "help":
            print("Comandos: help | servers | say <canal_id> <texto> | dm <usuario_id> <texto> | stop", flush=True)
        elif cmd == "servers":
            for g in bot.guilds:
                print(f" - {g.name} ({g.id}) [{g.member_count} miembros]", flush=True)
            if not bot.guilds:
                print("(en ningún servidor todavía)", flush=True)
        elif cmd == "say" and len(parts) == 3:
            try:
                ch = bot.get_channel(int(parts[1])) or await bot.fetch_channel(int(parts[1]))
                await ch.send(parts[2])
                print(f"[consola] Enviado a #{getattr(ch, 'name', parts[1])}", flush=True)
            except Exception as e:
                print(f"[consola] Error: {e}", flush=True)
        elif cmd == "dm" and len(parts) == 3:
            try:
                u = bot.get_user(int(parts[1])) or await bot.fetch_user(int(parts[1]))
                await u.send(parts[2])
                print(f"[consola] DM enviado a {u}", flush=True)
            except Exception as e:
                print(f"[consola] Error: {e}", flush=True)
        elif cmd == "stop":
            print("[consola] Apagando...", flush=True)
            await bot.close()
            return
        else:
            print("[consola] Comando no válido. Escribe 'help'.", flush=True)
