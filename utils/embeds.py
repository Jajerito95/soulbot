from __future__ import annotations
from typing import Optional
import discord
from config import BRAND, COLOR, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_INFO

# Icono del bot para el footer de todos los embeds. Se rellena en on_ready (main.py)
# para que cada embed lleve la identidad visual de SoulBot de forma consistente.
_footer_icon_url: Optional[str] = None


def set_footer_icon(url: str):
    global _footer_icon_url
    _footer_icon_url = url


def get_footer_icon() -> Optional[str]:
    return _footer_icon_url


def base_embed(description: str, color: int = COLOR, title: Optional[str] = None, footer: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(description=description, color=color)
    if title:
        embed.title = title
    embed.set_footer(text=footer or BRAND, icon_url=_footer_icon_url)
    embed.timestamp = discord.utils.utcnow()
    return embed


def success_embed(description: str, title: Optional[str] = "✅ Listo") -> discord.Embed:
    return base_embed(description, COLOR_SUCCESS, title)


def error_embed(description: str, title: Optional[str] = "❌ Error") -> discord.Embed:
    return base_embed(description, COLOR_ERROR, title)


def warning_embed(description: str, title: Optional[str] = "⚠️ Aviso") -> discord.Embed:
    return base_embed(description, COLOR_WARNING, title)


def info_embed(description: str, title: Optional[str] = "ℹ️ Información") -> discord.Embed:
    return base_embed(description, COLOR_INFO, title)


def is_valid_hex(value: str) -> bool:
    v = value.strip().lstrip("#")
    if len(v) != 6:
        return False
    try:
        int(v, 16)
        return True
    except ValueError:
        return False


def hex_to_int(value: str) -> int:
    return int(value.strip().lstrip("#"), 16)
