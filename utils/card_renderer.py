from __future__ import annotations
import io
import os
import re
import asyncio

import aiohttp
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
FONT_BOLD = os.path.join(FONT_DIR, "Outfit-Bold.ttf")
FONT_REGULAR = os.path.join(FONT_DIR, "Outfit-Regular.ttf")

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "]+"
)


def _clean(text: str) -> str:
    """Quita emoji Unicode del texto (la fuente Outfit no tiene esos glifos, salen como tofu)."""
    return _EMOJI_RE.sub("", text).strip()

CARD_W, CARD_H = 934, 282
BG_COLOR = (30, 33, 36)
ACCENT_DEFAULT = (43, 191, 179)   # teal, como en el ejemplo de referencia
TRACK_COLOR = (255, 255, 255)
FILL_COLOR = (88, 101, 242)       # azul SoulSeeker (Blurple)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


async def _download(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()


async def render_card(
    username: str,
    avatar_url: str,
    level: int,
    xp_current: int,
    xp_needed: int,
    rank: int,
    accent_hex: str | None = None,
    total_xp: int | None = None,
) -> io.BytesIO:
    accent = _hex_to_rgb(accent_hex) if accent_hex else ACCENT_DEFAULT

    base = Image.new("RGBA", (CARD_W, CARD_H), BG_COLOR + (255,))

    # Forma diagonal decorativa a la derecha (igual que en el ejemplo)
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(
        [(CARD_W - 200, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 360, CARD_H)],
        fill=accent + (255,),
    )
    base = Image.alpha_composite(base, overlay)

    # Esquinas redondeadas de toda la tarjeta
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=28, fill=255)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)

    draw = ImageDraw.Draw(card)

    # Avatar circular con borde blanco
    try:
        avatar_bytes = await _download(avatar_url)
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150))
    except Exception:
        avatar_img = Image.new("RGBA", (150, 150), (80, 80, 80, 255))

    avatar_mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(avatar_mask).ellipse((0, 0, 150, 150), fill=255)
    card.paste(avatar_img, (48, 66), avatar_mask)
    draw.ellipse((48, 66, 198, 216), outline=(255, 255, 255, 255), width=4)

    font_name = ImageFont.truetype(FONT_BOLD, 40)
    font_stats = ImageFont.truetype(FONT_REGULAR, 25)

    draw.text((222, 78), f"@{_clean(username)}", font=font_name, fill=(255, 255, 255, 255))
    stats_text = f"Nivel: {level} • XP: {xp_current}/{xp_needed} • Rank: #{rank}"
    draw.text((222, 138), stats_text, font=font_stats, fill=accent + (255,))
    if total_xp is not None:
        draw.text((222, 168), f"XP Total: {total_xp:,}", font=font_stats, fill=(200, 203, 208, 255))

    # Barra de progreso
    bar_x, bar_y, bar_w, bar_h = 222, 190, 560, 26
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=13, fill=TRACK_COLOR + (255,))
    ratio = min(1.0, xp_current / xp_needed) if xp_needed else 0
    fill_w = int(bar_w * ratio)
    if fill_w > 0:
        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + max(fill_w, bar_h), bar_y + bar_h], radius=13, fill=FILL_COLOR + (255,)
        )

    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def _safe_avatar(url: str) -> Image.Image:
    try:
        data = await _download(url)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return Image.new("RGBA", (128, 128), (80, 80, 80, 255))


async def render_leaderboard(
    guild_name: str,
    guild_icon_url: str | None,
    entries: list[dict],
    period_label: str,
) -> io.BytesIO:
    """
    entries: lista de dicts con {username, avatar_url, stat_text, ratio}
    ratio: 0.0-1.0, progreso a mostrar en la mini barra de cada fila (opcional, puede ser None)
    """
    row_h = 64
    header_h = 90
    width = 620
    height = header_h + row_h * len(entries) + 24

    card = Image.new("RGBA", (width, height), BG_COLOR + (255,))
    draw = ImageDraw.Draw(card)

    font_title = ImageFont.truetype(FONT_BOLD, 26)
    font_sub = ImageFont.truetype(FONT_REGULAR, 16)
    font_rank = ImageFont.truetype(FONT_BOLD, 20)
    font_user = ImageFont.truetype(FONT_BOLD, 19)
    font_stat = ImageFont.truetype(FONT_REGULAR, 16)

    if guild_icon_url:
        try:
            icon_bytes = await _download(guild_icon_url)
            icon_img = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((48, 48))
            icon_mask = Image.new("L", (48, 48), 0)
            ImageDraw.Draw(icon_mask).ellipse((0, 0, 48, 48), fill=255)
            card.paste(icon_img, (24, 20), icon_mask)
        except Exception:
            pass

    draw.text((84, 20), _clean(guild_name).upper(), font=font_title, fill=(255, 255, 255, 255))
    draw.text((84, 54), f"Leaderboard • {period_label}", font=font_sub, fill=(160, 160, 165, 255))
    draw.line([(24, header_h - 6), (width - 24, header_h - 6)], fill=(55, 58, 63, 255), width=2)

    medal_colors = {0: (255, 199, 60), 1: (200, 200, 205), 2: (205, 127, 80)}

    avatars = await asyncio.gather(*[_safe_avatar(e["avatar_url"]) for e in entries])

    y = header_h
    for i, entry in enumerate(entries):
        rank_color = medal_colors.get(i, (150, 150, 155))

        draw.text((24, y + 18), f"#{i + 1}", font=font_rank, fill=rank_color + (255,))

        avatar_img = avatars[i].resize((40, 40))
        avatar_mask = Image.new("L", (40, 40), 0)
        ImageDraw.Draw(avatar_mask).ellipse((0, 0, 40, 40), fill=255)
        card.paste(avatar_img, (70, y + 12), avatar_mask)

        draw.text((122, y + 8), _clean(entry["username"]), font=font_user, fill=(255, 255, 255, 255))
        draw.text((122, y + 32), entry["stat_text"], font=font_stat, fill=(150, 155, 160, 255))

        if entry.get("ratio") is not None:
            bar_x, bar_y, bar_w, bar_h = 122, y + 54, width - 122 - 24, 4
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=2, fill=(50, 53, 58, 255))
            fill_w = int(bar_w * min(1.0, entry["ratio"]))
            if fill_w > 0:
                draw.rounded_rectangle([bar_x, bar_y, bar_x + max(fill_w, bar_h), bar_y + bar_h], radius=2, fill=FILL_COLOR + (255,))

        y += row_h

    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def render_banner(title: str, subtitle: str, guild_icon_url: str | None = None, accent_hex: str | None = None) -> io.BytesIO:
    """Banner decorativo genérico (usado por el panel de tickets y similares)."""
    accent = _hex_to_rgb(accent_hex) if accent_hex else ACCENT_DEFAULT
    width, height = 934, 200

    base = Image.new("RGBA", (width, height), BG_COLOR + (255,))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(
        [(width - 220, 0), (width, 0), (width, height), (width - 380, height)],
        fill=accent + (255,),
    )
    base = Image.alpha_composite(base, overlay)

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width, height], radius=24, fill=255)
    banner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    banner.paste(base, (0, 0), mask)

    draw = ImageDraw.Draw(banner)

    text_x = 48
    if guild_icon_url:
        try:
            icon_bytes = await _download(guild_icon_url)
            icon_img = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((72, 72))
            icon_mask = Image.new("L", (72, 72), 0)
            ImageDraw.Draw(icon_mask).ellipse((0, 0, 72, 72), fill=255)
            banner.paste(icon_img, (48, (height - 72) // 2), icon_mask)
            text_x = 140
        except Exception:
            pass

    font_title = ImageFont.truetype(FONT_BOLD, 38)
    font_sub = ImageFont.truetype(FONT_REGULAR, 20)
    draw.text((text_x, 68), _clean(title), font=font_title, fill=(255, 255, 255, 255))
    draw.text((text_x, 118), subtitle, font=font_sub, fill=(180, 183, 188, 255))

    buffer = io.BytesIO()
    banner.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def render_sanction(
    username: str,
    avatar_url: str,
    action: str,
    reason: str,
    sanction_id,
    count: int = 1,
    accent_hex: str | None = None,
) -> io.BytesIO:
    """Tarjeta de sanción (Pillow) para el comando /sanction auto."""
    accent = _hex_to_rgb(accent_hex) if accent_hex else ACCENT_DEFAULT
    CARD_W, CARD_H = 934, 312

    base = Image.new("RGBA", (CARD_W, CARD_H), BG_COLOR + (255,))
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(
        [(CARD_W - 220, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 380, CARD_H)],
        fill=accent + (255,),
    )
    base = Image.alpha_composite(base, overlay)

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=28, fill=255)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)

    draw = ImageDraw.Draw(card)

    try:
        avatar_bytes = await _download(avatar_url)
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150))
    except Exception:
        avatar_img = Image.new("RGBA", (150, 150), (80, 80, 80, 255))
    avatar_mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(avatar_mask).ellipse((0, 0, 150, 150), fill=255)
    card.paste(avatar_img, (48, 66), avatar_mask)
    draw.ellipse((48, 66, 198, 216), outline=(255, 255, 255, 255), width=4)

    font_name = ImageFont.truetype(FONT_BOLD, 38)
    font_meta = ImageFont.truetype(FONT_REGULAR, 22)
    font_reason = ImageFont.truetype(FONT_REGULAR, 22)

    action_label = {"warn": "ADVERTENCIA", "ban": "BAN", "unban": "DESBANEO"}.get(action, str(action).upper())
    draw.text((222, 70), f"@{_clean(username)}", font=font_name, fill=(255, 255, 255, 255))
    draw.text((222, 120), f"Sanción: {action_label}", font=font_meta, fill=accent + (255,))
    draw.text((222, 154), f"ID #{sanction_id}  •  Reincidencia #{count}", font=font_meta, fill=(170, 173, 178, 255))

    reason_text = _clean(reason or "Sin razón")
    max_w = 640
    lines, cur = [], ""
    for w in reason_text.split():
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font_reason) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lines = lines[:3]
    y = 196
    for ln in lines:
        draw.text((222, y), ln, font=font_reason, fill=(210, 213, 218, 255))
        y += 30

    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def render_welcome(
    username: str,
    avatar_url: str,
    guild_name: str,
    guild_icon_url: str | None,
    member_count: int,
    accent_hex: str | None = None,
) -> io.BytesIO:
    """Tarjeta de bienvenida (Pillow) para on_member_join."""
    accent = _hex_to_rgb(accent_hex) if accent_hex else ACCENT_DEFAULT
    CARD_W, CARD_H = 934, 312

    base = Image.new("RGBA", (CARD_W, CARD_H), BG_COLOR + (255,))
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(
        [(CARD_W - 220, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 380, CARD_H)],
        fill=accent + (255,),
    )
    base = Image.alpha_composite(base, overlay)

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=28, fill=255)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)

    draw = ImageDraw.Draw(card)

    try:
        avatar_bytes = await _download(avatar_url)
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150))
    except Exception:
        avatar_img = Image.new("RGBA", (150, 150), (80, 80, 80, 255))
    avatar_mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(avatar_mask).ellipse((0, 0, 150, 150), fill=255)
    card.paste(avatar_img, (48, 66), avatar_mask)
    draw.ellipse((48, 66, 198, 216), outline=(255, 255, 255, 255), width=4)

    font_welcome = ImageFont.truetype(FONT_BOLD, 30)
    font_name = ImageFont.truetype(FONT_BOLD, 40)
    font_sub = ImageFont.truetype(FONT_REGULAR, 22)

    draw.text((222, 70), "¡BIENVENIDO/A!", font=font_welcome, fill=accent + (255,))
    draw.text((222, 116), f"@{_clean(username)}", font=font_name, fill=(255, 255, 255, 255))
    draw.text((222, 168), f"a {_clean(guild_name)}", font=font_sub, fill=(200, 203, 208, 255))
    draw.text((222, 206), f"Miembros totales: {member_count}", font=font_sub, fill=(170, 173, 178, 255))

    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def render_profile(
    username: str,
    avatar_url: str,
    coins: int,
    accent_hex: str | None = None,
) -> io.BytesIO:
    """Tarjeta de perfil/economía (Pillow) para /balance."""
    accent = _hex_to_rgb(accent_hex) if accent_hex else ACCENT_DEFAULT
    CARD_W, CARD_H = 520, 280

    base = Image.new("RGBA", (CARD_W, CARD_H), BG_COLOR + (255,))
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(
        [(CARD_W - 120, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 220, CARD_H)],
        fill=accent + (255,),
    )
    base = Image.alpha_composite(base, overlay)

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=28, fill=255)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)

    draw = ImageDraw.Draw(card)

    try:
        avatar_bytes = await _download(avatar_url)
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((130, 130))
    except Exception:
        avatar_img = Image.new("RGBA", (130, 130), (80, 80, 80, 255))
    avatar_mask = Image.new("L", (130, 130), 0)
    ImageDraw.Draw(avatar_mask).ellipse((0, 0, 130, 130), fill=255)
    card.paste(avatar_img, (40, 75), avatar_mask)
    draw.ellipse((40, 75, 170, 205), outline=(255, 255, 255, 255), width=4)

    font_name = ImageFont.truetype(FONT_BOLD, 30)
    font_coins = ImageFont.truetype(FONT_BOLD, 34)
    font_label = ImageFont.truetype(FONT_REGULAR, 18)

    draw.text((200, 90), f"@{_clean(username)}", font=font_name, fill=(255, 255, 255, 255))
    draw.text((200, 140), f"{coins:,} SoulCoins", font=font_coins, fill=accent + (255,))
    draw.text((200, 184), "SoulSeeker Economy", font=font_label, fill=(170, 173, 178, 255))

    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# Paleta de acentos por categoría (determinista por nombre, sin necesidad de guardar color en DB)
CATEGORY_PALETTE = [
    "#2BBFB3",  # teal
    "#5865F2",  # blurple
    "#EB459E",  # rosa
    "#F1C40F",  # amarillo
    "#ED4245",  # rojo
    "#57F287",  # verde
    "#FF9F43",  # naranja
]


def category_accent(label: str) -> str:
    """Color determinista por nombre de categoría — misma categoría siempre el mismo color."""
    index = sum(ord(c) for c in label) % len(CATEGORY_PALETTE)
    return CATEGORY_PALETTE[index]
