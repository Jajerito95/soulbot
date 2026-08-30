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
    accent_light = tuple(min(255, c + 40) for c in accent)
    # base con gradiente sutil vertical
    base = Image.new("RGBA", (CARD_W, CARD_H), (0,0,0,0))
    bdraw = ImageDraw.Draw(base)
    for y in range(CARD_H):
        t = y / CARD_H
        r = int(BG_COLOR[0]*(1-t) + (BG_COLOR[0]+12)*t)
        g = int(BG_COLOR[1]*(1-t) + (BG_COLOR[1]+12)*t)
        b = int(BG_COLOR[2]*(1-t) + (BG_COLOR[2]+14)*t)
        bdraw.line([(0,y),(CARD_W,y)], fill=(r,g,b,255))
    # diagonal decorativa: gradiente accent -> accent_light + sombra
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # sombra del overlay
    shadow_poly = [(CARD_W - 204, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 364, CARD_H)]
    odraw.polygon(shadow_poly, fill=(0,0,0,60))
    odraw.polygon(
        [(CARD_W - 200, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 360, CARD_H)],
        fill=accent + (255,),
    )
    # highlight interior diagonal
    odraw.line([(CARD_W - 200, 0),(CARD_W - 360, CARD_H)], fill=accent_light + (90,), width=2)
    base = Image.alpha_composite(base, overlay)

    # esquinas redondeadas
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=28, fill=255)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)

    draw = ImageDraw.Draw(card)

    # sombra avatar
    shadow = Image.new("RGBA", (150,150), (0,0,0,0))
    ImageDraw.Draw(shadow).ellipse((0,0,150,150), fill=(0,0,0,80))
    card.paste(shadow, (52, 70), shadow)
    # avatar circular con borde blanco
    try:
        avatar_bytes = await _download(avatar_url)
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150), Image.LANCZOS)
    except Exception:
        avatar_img = Image.new("RGBA", (150, 150), (80, 80, 80, 255))
    avatar_mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(avatar_mask).ellipse((0, 0, 150, 150), fill=255)
    card.paste(avatar_img, (48, 66), avatar_mask)
    draw.ellipse((48, 66, 198, 216), outline=(255, 255, 255, 255), width=4)
    # anillo interior acento
    draw.ellipse((50, 68, 196, 214), outline=accent + (180,), width=2)

    font_name = ImageFont.truetype(FONT_BOLD, 40)
    font_stats = ImageFont.truetype(FONT_REGULAR, 22)
    font_small = ImageFont.truetype(FONT_REGULAR, 20)

    # username truncado para no invadir overlay
    clean_name = _clean(username)[:18]
    # sombra texto username
    draw.text((223, 79), f"@{clean_name}", font=font_name, fill=(0,0,0,90))
    draw.text((222, 78), f"@{clean_name}", font=font_name, fill=(255, 255, 255, 255))
    stats_text = f"Nivel: {level} \u2022 XP: {xp_current}/{xp_needed} \u2022 Rank: #{rank}"
    draw.text((223, 139), stats_text, font=font_stats, fill=(0,0,0,60))
    draw.text((222, 138), stats_text, font=font_stats, fill=accent + (255,))
    if total_xp is not None:
        total_str = f"{total_xp:,}".replace(",", ".")
        draw.text((222, 166), f"XP Total: {total_str}", font=font_small, fill=(200, 203, 208, 255))

    # badge rank top-right (evita overlay también)
    badge_text = f"#{rank}"
    try:
        font_badge = ImageFont.truetype(FONT_BOLD, 22)
    except: font_badge = font_small
    bw = int(draw.textlength(badge_text, font=font_badge)) + 28
    bx = CARD_W - bw - 24
    by = 22
    # fondo badge
    badge_bg = (40,44,52,230) if rank > 3 else (int(accent[0]*0.8), int(accent[1]*0.8), int(accent[2]*0.8), 255)
    draw.rounded_rectangle([bx, by, bx+bw, by+30], radius=15, fill=badge_bg, outline=(255,255,255,40), width=1)
    draw.text((bx+14, by+4), badge_text, font=font_badge, fill=(255,255,255,255))

    # Barra de progreso mejorada (no invade overlay)
    bar_x, bar_y, bar_w, bar_h = 222, 196, 520, 22
    # track con sombra interior
    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=11, fill=(45, 48, 54, 255), outline=(60,64,72,255), width=1)
    draw.rounded_rectangle([bar_x+1, bar_y+1, bar_x + bar_w-1, bar_y + bar_h-1], radius=10, fill=(35, 38, 44, 255))
    ratio = min(1.0, xp_current / xp_needed) if xp_needed else 0
    fill_w = int(bar_w * ratio)
    if fill_w > 4:
        # fill con gradiente horizontal accent
        fill_img = Image.new("RGBA", (fill_w, bar_h), (0,0,0,0))
        fdraw = ImageDraw.Draw(fill_img)
        for x in range(fill_w):
            t = x / max(1, fill_w)
            r = int(accent[0]*(1-t) + accent_light[0]*t)
            g = int(accent[1]*(1-t) + accent_light[1]*t)
            b = int(accent[2]*(1-t) + accent_light[2]*t)
            fdraw.line([(x,0),(x,bar_h)], fill=(r,g,b,255))
        # máscara redondeada para fill
        fill_mask = Image.new("L", (fill_w, bar_h), 0)
        ImageDraw.Draw(fill_mask).rounded_rectangle([0,0,fill_w,bar_h], radius=11, fill=255)
        # recorta esquinas derechas si no es 100%
        if ratio < 0.98:
            # quita redondeo derecho para que no se vea hueco
            ImageDraw.Draw(fill_mask).rectangle([fill_w-11,0,fill_w,bar_h], fill=255)
        card.paste(fill_img, (bar_x, bar_y), fill_mask)
        # highlight superior
        draw.rounded_rectangle([bar_x, bar_y, bar_x+fill_w, bar_y+6], radius=6, fill=(255,255,255,45))
    # porcentaje dentro de la barra
    pct = f"{int(ratio*100)}%"
    try:
        font_pct = ImageFont.truetype(FONT_BOLD, 14)
    except: font_pct = font_small
    # elige color según si está sobre fill o track
    px = bar_x + bar_w//2
    draw.text((px+1, bar_y+3), pct, font=font_pct, fill=(0,0,0,90), anchor="mm")
    draw.text((px, bar_y+2), pct, font=font_pct, fill=(255,255,255,255), anchor="mm")

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
    row_h = 72
    header_h = 92
    width = 640
    height = header_h + row_h * len(entries) + 32
    # fondo con gradiente sutil
    card = Image.new("RGBA", (width, height), (0,0,0,0))
    bg = Image.new("RGBA", (width, height), BG_COLOR + (255,))
    bdraw = ImageDraw.Draw(bg)
    for y in range(height):
        t = y/height
        r = int(BG_COLOR[0]*(1-t) + (BG_COLOR[0]+10)*t)
        g = int(BG_COLOR[1]*(1-t) + (BG_COLOR[1]+10)*t)
        b = int(BG_COLOR[2]*(1-t) + (BG_COLOR[2]+12)*t)
        bdraw.line([(0,y),(width,y)], fill=(r,g,b,255))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,width,height], radius=22, fill=255)
    card.paste(bg, (0,0), mask)
    draw = ImageDraw.Draw(card)

    font_title = ImageFont.truetype(FONT_BOLD, 26)
    font_sub = ImageFont.truetype(FONT_REGULAR, 15)
    font_rank = ImageFont.truetype(FONT_BOLD, 20)
    font_user = ImageFont.truetype(FONT_BOLD, 19)
    font_stat = ImageFont.truetype(FONT_REGULAR, 15)

    # icono guild con sombra
    if guild_icon_url:
        try:
            icon_bytes = await _download(guild_icon_url)
            icon_img = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((52, 52), Image.LANCZOS)
            sh = Image.new("RGBA", (52,52), (0,0,0,0))
            ImageDraw.Draw(sh).ellipse((0,0,52,52), fill=(0,0,0,60))
            card.paste(sh, (26, 22), sh)
            icon_mask = Image.new("L", (52, 52), 0)
            ImageDraw.Draw(icon_mask).ellipse((0, 0, 52, 52), fill=255)
            card.paste(icon_img, (24, 20), icon_mask)
            draw.ellipse((24,20,76,72), outline=(255,255,255,35), width=1)
        except Exception:
            pass
        tx = 88
    else:
        tx = 24
    draw.text((tx, 20), _clean(guild_name).upper()[:28], font=font_title, fill=(255, 255, 255, 255))
    draw.text((tx, 52), f"Leaderboard \u2022 {period_label}", font=font_sub, fill=(160, 160, 165, 255))
    # pill de periodo activo
    pill_w = int(draw.textlength(period_label, font=font_sub)) + 24
    pill_x = width - pill_w - 24
    draw.rounded_rectangle([pill_x, 24, pill_x+pill_w, 52], radius=14, fill=ACCENT_DEFAULT + (255,))
    draw.text((pill_x+12, 30), period_label, font=font_sub, fill=(255,255,255,255))
    draw.line([(24, header_h - 10), (width - 24, header_h - 10)], fill=(55, 58, 63, 255), width=1)

    medal_bg = {0: (255,199,60), 1: (190,195,200), 2: (205,127,80)}
    medal_fg = {0: (60,45,0), 1: (45,45,48), 2: (60,30,15)}

    avatars = await asyncio.gather(*[_safe_avatar(e["avatar_url"]) for e in entries])

    y = header_h
    for i, entry in enumerate(entries):
        # fondo fila alterno + hover
        row_bg = (38,40,45,255) if i%2==0 else (32,34,38,255)
        if i < 3:
            row_bg = (45,42,36,255) if i==0 else (42,44,48,255) if i==1 else (42,38,36,255)
        draw.rounded_rectangle([12, y-2, width-12, y+row_h-6], radius=14, fill=row_bg, outline=(55,58,63,30), width=1)
        # rank badge circular
        bg_c = medal_bg.get(i, (55,58,63))
        fg_c = medal_fg.get(i, (220,221,224))
        # círculo rank
        draw.ellipse([20, y+16, 52, y+48], fill=bg_c + (255,), outline=(255,255,255,30), width=1)
        draw.text((36, y+24), f"{i+1}", font=font_rank, fill=fg_c + (255,), anchor="mm")
        # avatar con borde
        avatar_img = avatars[i].resize((44, 44), Image.LANCZOS)
        avatar_mask = Image.new("L", (44, 44), 0)
        ImageDraw.Draw(avatar_mask).ellipse((0, 0, 44, 44), fill=255)
        # sombra avatar
        sh = Image.new("RGBA", (44,44), (0,0,0,0))
        ImageDraw.Draw(sh).ellipse((0,0,44,44), fill=(0,0,0,45))
        card.paste(sh, (66, y+14), sh)
        card.paste(avatar_img, (64, y+12), avatar_mask)
        draw.ellipse((64, y+12, 108, y+56), outline=(255,255,255,45), width=1)

        draw.text((120, y+12), _clean(entry["username"])[:18], font=font_user, fill=(255, 255, 255, 255))
        draw.text((120, y+36), entry["stat_text"][:42], font=font_stat, fill=(150, 155, 165, 255))

        if entry.get("ratio") is not None:
            bar_x, bar_y, bar_w, bar_h = 120, y+56, width - 120 - 24, 6
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=3, fill=(45, 48, 54, 255))
            fill_w = int(bar_w * min(1.0, entry["ratio"]))
            if fill_w > 0:
                # gradiente fill
                fill_img = Image.new("RGBA", (fill_w, bar_h), (0,0,0,0))
                fd = ImageDraw.Draw(fill_img)
                for x in range(fill_w):
                    t = x / max(1, fill_w)
                    r = int(88*(1-t) + 120*t); g = int(101*(1-t) + 140*t); b = int(242*(1-t) + 255*t)
                    fd.line([(x,0),(x,bar_h)], fill=(r,g,b,255))
                fm = Image.new("L", (fill_w, bar_h), 0)
                ImageDraw.Draw(fm).rounded_rectangle([0,0,fill_w,bar_h], radius=3, fill=255)
                if fill_w < bar_w:
                    ImageDraw.Draw(fm).rectangle([fill_w-3,0,fill_w,bar_h], fill=255)
                card.paste(fill_img, (bar_x, bar_y), fm)

        y += row_h

    # footer brand
    draw.text((width//2, height-14), "SoulSeeker™ • SoulBot System", font=font_sub, fill=(110,114,120,255), anchor="mm")

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
