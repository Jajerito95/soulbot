from __future__ import annotations
from typing import Optional
import discord
from config import BRAND, COLOR_SUCCESS, COLOR_ERROR


def base_embed(description: str, color: int, title: Optional[str] = None, footer: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(description=description, color=color)
    if title:
        embed.title = title
    embed.set_footer(text=footer or BRAND)
    return embed


def success_embed(description: str, title: Optional[str] = "✨ Éxito") -> discord.Embed:
    return base_embed(description, COLOR_SUCCESS, title)


def error_embed(description: str, title: Optional[str] = "⚠️ Error") -> discord.Embed:
    return base_embed(description, COLOR_ERROR, title)


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
