# 🧠 SoulBot System

Bot oficial de Discord de **SoulSeeker™**.

Elegante · Simple · Bajo consumo · Fácil de mantener.

## 🧩 Sistemas incluidos

- `/embed` — Crea embeds personalizados (descripción, título, color HEX y footer opcionales).
- Bienvenida + Invitaciones — Mensaje de bienvenida automático y tracking de invites.
- `/invites count` y `/invites leaderboard`.
- `/suggestion` — Sistema de sugerencias con votos y aprobación de Staff.
- `/setup invites` / `/setup suggestion` — Configuración por servidor (solo Staff).

## 📁 Estructura

```
soulbot/
├── main.py          # Punto de entrada
├── config.py         # Variables de entorno y constantes
├── database.py        # Capa SQLite (aiosqlite)
├── keep_alive.py       # Servidor Flask para UptimeRobot
├── cogs/
│   ├── embed.py
│   ├── welcome.py
│   ├── suggestions.py
│   └── setup.py
└── utils/
    └── embeds.py
```

## ⚙️ Instalación local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rellena tu DISCORD_TOKEN
python main.py
```

## 🚀 Despliegue en Render

1. Sube este repositorio a GitHub.
2. Crea un nuevo **Web Service** en Render conectado al repo (o usa `render.yaml`).
3. Configura la variable de entorno `DISCORD_TOKEN` (nunca la subas al código).
4. Render usará un disco persistente (`data/`) para que la base de datos SQLite
   sobreviva a los reinicios/redeploys.
5. Copia la URL pública de Render (ej: `https://soulbot.onrender.com`) y
   configúrala como monitor en **UptimeRobot** (HTTP, cada 5 min) para mantener
   el servicio despierto.

## 🔑 Permisos del bot (Discord Developer Portal)

Al invitar el bot, habilita:
- Scope `applications.commands` y `bot`.
- Permisos: Gestionar servidor (para leer invitaciones), Enviar mensajes, Insertar enlaces.
- Intent privilegiado: **Server Members Intent** (activarlo en el portal de Discord).

## 🛡️ Permisos internos

- `/setup ...` requiere permiso `Gestionar servidor` (Staff/Admin).
- `/suggestion` está disponible para cualquier usuario, solo en el canal configurado.
- Los botones de aprobar/denegar en sugerencias también requieren `Gestionar servidor`.

## 🔮 Próximos sistemas (no implementados aún)

Tickets, Logs, Ausencias de Staff, `/sanctions`, Niveles, Importación de Arcane,
Minijuegos, Economía SoulCoins.

---

**SoulSeeker™ | All rights reserved.**
