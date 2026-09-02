from __future__ import annotations
import io
import os
import re
import asyncio

import aiohttp
from PIL import Image, ImageDraw, ImageFont
import time as _time

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
_avatar_cache: dict[str, tuple[bytes, float]] = {}
_AVATAR_TTL = 300
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
    # cache simple en memoria para no re-descargar el mismo avatar cada /lb
    now = _time.time()
    if url in _avatar_cache:
        data, ts = _avatar_cache[url]
        if now - ts < _AVATAR_TTL:
            return data
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=20, limit_per_host=10)) as session:
        async with session.get(url) as resp:
            data = await resp.read()
            _avatar_cache[url] = (data, now)
            # limpia cache si crece mucho
            if len(_avatar_cache) > 200:
                oldest = min(_avatar_cache, key=lambda k: _avatar_cache[k][1])
                _avatar_cache.pop(oldest, None)
            return data


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
    def _f(n): return f"{int(n):,}".replace(",", ".")
    # sombra texto username
    draw.text((223, 79), f"@{clean_name}", font=font_name, fill=(0,0,0,90))
    draw.text((222, 78), f"@{clean_name}", font=font_name, fill=(255, 255, 255, 255))
    stats_text = f"Nivel: {level} \u2022 XP: {_f(xp_current)}/{_f(xp_needed)} \u2022 Rank: #{rank}"
    draw.text((223, 139), stats_text, font=font_stats, fill=(0,0,0,60))
    draw.text((222, 138), stats_text, font=font_stats, fill=accent + (255,))
    if total_xp is not None:
        total_str = _f(total_xp)
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
    row_h = 80
    header_h = 100
    width = 700
    height = header_h + row_h * len(entries) + 40
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
    # diagonal accent
    overlay = Image.new("RGBA", (width, height), (0,0,0,0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon([(width-200,0),(width,0),(width,height),(width-340,height)], fill=ACCENT_DEFAULT+(30,))
    bg = Image.alpha_composite(bg, overlay)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,width,height], radius=22, fill=255)
    card.paste(bg, (0,0), mask)
    draw = ImageDraw.Draw(card)

    font_title = ImageFont.truetype(FONT_BOLD, 28)
    font_sub = ImageFont.truetype(FONT_REGULAR, 16)
    font_rank = ImageFont.truetype(FONT_BOLD, 22)
    font_user = ImageFont.truetype(FONT_BOLD, 20)
    font_stat = ImageFont.truetype(FONT_REGULAR, 16)

    # icono guild con sombra
    if guild_icon_url:
        try:
            icon_bytes = await _download(guild_icon_url)
            icon_img = Image.open(io.BytesIO(icon_bytes)).convert("RGBA").resize((56, 56), Image.LANCZOS)
            sh = Image.new("RGBA", (56,56), (0,0,0,0))
            ImageDraw.Draw(sh).ellipse((0,0,56,56), fill=(0,0,0,60))
            card.paste(sh, (26, 24), sh)
            icon_mask = Image.new("L", (56, 56), 0)
            ImageDraw.Draw(icon_mask).ellipse((0, 0, 56, 56), fill=255)
            card.paste(icon_img, (24, 22), icon_mask)
            draw.ellipse((24,22,80,78), outline=(255,255,255,35), width=1)
        except Exception:
            pass
        tx = 92
    else:
        tx = 24
    draw.text((tx, 22), _clean(guild_name).upper()[:28], font=font_title, fill=(255, 255, 255, 255))
    draw.text((tx, 56), f"Leaderboard \u2022 {period_label}", font=font_sub, fill=(160, 160, 165, 255))
    # pill de periodo activo
    pill_w = int(draw.textlength(period_label, font=font_sub)) + 24
    pill_x = width - pill_w - 24
    draw.rounded_rectangle([pill_x, 24, pill_x+pill_w, 54], radius=15, fill=ACCENT_DEFAULT + (255,))
    draw.text((pill_x+12, 30), period_label, font=font_sub, fill=(255,255,255,255))
    draw.line([(24, header_h - 10), (width - 24, header_h - 10)], fill=(55, 58, 63, 255), width=1)

    # medals — bigger circles with glow
    medal_colors = {
        0: ((255,215,0), (255,240,150)),    # gold
        1: ((192,192,192), (220,220,225)),   # silver
        2: ((205,127,80), (230,165,120)),    # bronze
    }

    avatars = await asyncio.gather(*[_safe_avatar(e["avatar_url"]) for e in entries])

    y = header_h
    for i, entry in enumerate(entries):
        row_bg = (38,40,45,255) if i%2==0 else (32,34,38,255)
        if i < 3:
            row_bg = (45,42,36,255) if i==0 else (42,44,48,255) if i==1 else (42,38,36,255)
        draw.rounded_rectangle([12, y-2, width-12, y+row_h-8], radius=16, fill=row_bg, outline=(55,58,63,40), width=1)

        # rank badge — big circle 44x44
        if i < 3:
            bg_c, glow_c = medal_colors[i]
            # glow behind medal
            draw.ellipse([16, y+14, 64, y+62], fill=glow_c + (60,))
            draw.ellipse([18, y+16, 62, y+60], fill=bg_c + (255,), outline=(255,255,255,50), width=2)
            rank_text = f"{i+1}"
            draw.text((40, y+38), rank_text, font=font_rank, fill=(60,40,0,255) if i==0 else (40,40,45,255) if i==1 else (60,30,15,255), anchor="mm")
        else:
            draw.ellipse([18, y+16, 62, y+60], fill=(55,58,63,255), outline=(70,74,80,255), width=1)
            draw.text((40, y+38), f"{i+1}", font=font_rank, fill=(200,200,205,255), anchor="mm")

        # avatar con borde — 48x48
        avatar_img = avatars[i].resize((48, 48), Image.LANCZOS)
        avatar_mask = Image.new("L", (48, 48), 0)
        ImageDraw.Draw(avatar_mask).ellipse((0, 0, 48, 48), fill=255)
        sh = Image.new("RGBA", (48,48), (0,0,0,0))
        ImageDraw.Draw(sh).ellipse((0,0,48,48), fill=(0,0,0,45))
        card.paste(sh, (72, y+14), sh)
        card.paste(avatar_img, (70, y+12), avatar_mask)
        draw.ellipse((70, y+12, 118, y+60), outline=(255,255,255,45), width=1)

        draw.text((130, y+12), _clean(entry["username"])[:20], font=font_user, fill=(255, 255, 255, 255))
        draw.text((130, y+38), entry["stat_text"][:44], font=font_stat, fill=(150, 155, 165, 255))

        # progress bar — WIDER (10px) with gradient
        if entry.get("ratio") is not None:
            bar_x, bar_y, bar_w, bar_h = 130, y+60, width - 130 - 24, 10
            draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=5, fill=(45, 48, 54, 255))
            fill_w = int(bar_w * min(1.0, entry["ratio"]))
            if fill_w > 0:
                fill_img = Image.new("RGBA", (fill_w, bar_h), (0,0,0,0))
                fd = ImageDraw.Draw(fill_img)
                for x in range(fill_w):
                    t = x / max(1, fill_w)
                    r = int(88*(1-t) + 120*t); g = int(101*(1-t) + 140*t); b = int(242*(1-t) + 255*t)
                    fd.line([(x,0),(x,bar_h)], fill=(r,g,b,255))
                fm = Image.new("L", (fill_w, bar_h), 0)
                ImageDraw.Draw(fm).rounded_rectangle([0,0,fill_w,bar_h], radius=5, fill=255)
                if fill_w < bar_w:
                    ImageDraw.Draw(fm).rectangle([fill_w-5,0,fill_w,bar_h], fill=255)
                card.paste(fill_img, (bar_x, bar_y), fm)

        y += row_h

    # footer brand
    draw.text((width//2, height-16), "SoulSeeker™ • SoulBot System", font=font_sub, fill=(110,114,120,255), anchor="mm")

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
    """Tarjeta de perfil/economía (Pillow) para /balance — 934x282 full size."""
    accent = _hex_to_rgb(accent_hex) if accent_hex else ACCENT_DEFAULT
    accent_light = tuple(min(255, c + 40) for c in accent)
    CARD_W, CARD_H = 934, 282

    base = Image.new("RGBA", (CARD_W, CARD_H), (0,0,0,0))
    bdraw = ImageDraw.Draw(base)
    for y in range(CARD_H):
        t = y / CARD_H
        r = int(BG_COLOR[0]*(1-t) + (BG_COLOR[0]+12)*t)
        g = int(BG_COLOR[1]*(1-t) + (BG_COLOR[1]+12)*t)
        b = int(BG_COLOR[2]*(1-t) + (BG_COLOR[2]+14)*t)
        bdraw.line([(0,y),(CARD_W,y)], fill=(r,g,b,255))
    # diagonal decorativa — más atrás para no tapar texto
    overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    shadow_poly = [(CARD_W - 280, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 440, CARD_H)]
    odraw.polygon(shadow_poly, fill=(0,0,0,60))
    odraw.polygon(
        [(CARD_W - 260, 0), (CARD_W, 0), (CARD_W, CARD_H), (CARD_W - 420, CARD_H)],
        fill=accent + (255,),
    )
    odraw.line([(CARD_W - 260, 0),(CARD_W - 420, CARD_H)], fill=accent_light + (90,), width=2)
    base = Image.alpha_composite(base, overlay)

    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W, CARD_H], radius=28, fill=255)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)
    draw = ImageDraw.Draw(card)

    # sombra avatar
    shadow = Image.new("RGBA", (150,150), (0,0,0,0))
    ImageDraw.Draw(shadow).ellipse((0,0,150,150), fill=(0,0,0,80))
    card.paste(shadow, (52, 70), shadow)
    # avatar circular
    try:
        avatar_bytes = await _download(avatar_url)
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150), Image.LANCZOS)
    except Exception:
        avatar_img = Image.new("RGBA", (150, 150), (80, 80, 80, 255))
    avatar_mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(avatar_mask).ellipse((0, 0, 150, 150), fill=255)
    card.paste(avatar_img, (48, 66), avatar_mask)
    draw.ellipse((48, 66, 198, 216), outline=(255, 255, 255, 255), width=4)
    draw.ellipse((50, 68, 196, 214), outline=accent + (180,), width=2)

    font_name = ImageFont.truetype(FONT_BOLD, 40)
    font_coins = ImageFont.truetype(FONT_BOLD, 48)
    font_label = ImageFont.truetype(FONT_REGULAR, 22)
    font_small = ImageFont.truetype(FONT_REGULAR, 20)

    def _f(n): return f"{int(n):,}".replace(",", ".")

    clean_name = _clean(username)[:22]
    draw.text((223, 79), f"@{clean_name}", font=font_name, fill=(0,0,0,90))
    draw.text((222, 78), f"@{clean_name}", font=font_name, fill=(255, 255, 255, 255))

    coins_str = _f(coins)
    draw.text((223, 141), f"{coins_str} SoulCoins", font=font_coins, fill=(0,0,0,90))
    draw.text((222, 140), f"{coins_str} SoulCoins", font=font_coins, fill=accent + (255,))

    draw.text((222, 200), "SoulSeeker Economy", font=font_label, fill=(170, 173, 178, 255))

    # badge monedita decorativo
    try:
        font_badge = ImageFont.truetype(FONT_BOLD, 18)
    except:
        font_badge = font_small
    bw = 120
    bx = CARD_W - bw - 24
    by = 22
    draw.rounded_rectangle([bx, by, bx+bw, by+34], radius=17, fill=(40,44,52,230), outline=accent + (120,), width=2)
    draw.text((bx + bw//2, by + 5), "COINS", font=font_badge, fill=accent + (255,), anchor="mt")

    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def render_suggestion(
    username: str,
    avatar_url: str,
    content: str,
    yes: int,
    no: int,
    status: str,
) -> io.BytesIO:
    """Tarjeta Pillow para sugerencias — usada si quieres 'todo en pillow'."""
    accent = {"pending": (88,101,242), "approved": (87,242,135), "denied": (237,66,69)}.get(status, (88,101,242))
    BG = (30,33,36)
    W, H = 800, 260
    base = Image.new("RGBA", (W,H), BG + (255,))
    bdraw = ImageDraw.Draw(base)
    for y in range(H):
        t=y/H
        r=int(BG[0]*(1-t)+(BG[0]+10)*t); g=int(BG[1]*(1-t)+(BG[1]+10)*t); b=int(BG[2]*(1-t)+(BG[2]+12)*t)
        bdraw.line([(0,y),(W,y)], fill=(r,g,b,255))
    # barra lateral acento
    bdraw.rectangle([0,0,8,H], fill=accent+(255,))
    mask = Image.new("L", (W,H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,W,H], radius=18, fill=255)
    card = Image.new("RGBA", (W,H), (0,0,0,0))
    card.paste(base, (0,0), mask)
    draw = ImageDraw.Draw(card)
    # avatar
    try:
        data = await _download(avatar_url)
        av = Image.open(io.BytesIO(data)).convert("RGBA").resize((64,64), Image.LANCZOS)
    except: av = Image.new("RGBA", (64,64), (80,80,80,255))
    am = Image.new("L", (64,64), 0); ImageDraw.Draw(am).ellipse((0,0,64,64), fill=255)
    card.paste(av, (24,24), am)
    draw.ellipse((24,24,88,88), outline=(255,255,255,40), width=1)
    font_b = ImageFont.truetype(FONT_BOLD, 20); font_r = ImageFont.truetype(FONT_REGULAR, 16); font_c = ImageFont.truetype(FONT_REGULAR, 18)
    draw.text((104, 28), _clean(username)[:20], font=font_b, fill=(255,255,255,255))
    status_lbl = {"pending":"PENDIENTE","approved":"APROBADA","denied":"DENEGADA"}.get(status,status.upper())
    draw.rounded_rectangle([W-110, 24, W-24, 48], radius=10, fill=accent+(255,))
    draw.text((W-67, 30), status_lbl, font=font_r, fill=(255,255,255,255), anchor="mm")
    # contenido warp
    max_w = W-48
    words = _clean(content).split(); lines=[]; cur=""
    for w in words:
        test=(cur+" "+w).strip()
        if draw.textlength(test, font=font_c) <= max_w:
            cur=test
        else:
            if cur: lines.append(cur)
            cur=w
    if cur: lines.append(cur)
    lines=lines[:4]
    y=100
    for ln in lines:
        draw.text((24, y), ln, font=font_c, fill=(220,221,224,255))
        y+=22
    # votos
    draw.text((24, H-36), f"🟢 {yes}  •  🔴 {no}", font=font_r, fill=(160,160,165,255))
    draw.text((W-24, H-36), "SoulSeeker™", font=font_r, fill=(110,114,120,255), anchor="rm")
    buf=io.BytesIO(); card.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf


async def render_daily_streak(username: str, avatar_url: str, amount: int, streak: int, streak_coins: int, streak_xp: int, balance: int) -> io.BytesIO:
    W, H = 934, 320
    BG = (18, 20, 28)
    accent = (88, 101, 242)
    accent_light = (120, 140, 255)
    base = Image.new("RGBA", (W, H), BG + (255,))
    bdraw = ImageDraw.Draw(base)
    for y in range(H):
        t = y / H
        r = int(18 + t*25); g = int(20 + t*15); b = int(28 + t*50)
        bdraw.line([(0,y),(W,y)], fill=(r,g,b,255))
    # diagonal accent sutil
    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon([(W-260,0),(W,0),(W,H),(W-420,H)], fill=accent+(40,))
    base = Image.alpha_composite(base, overlay)
    # streak bar 1-7 — big
    bar_total_w = W - 48
    cell_w = bar_total_w // 7
    for i in range(7):
        x0 = 24 + i * cell_w
        x1 = x0 + cell_w - 8
        y0, y1 = 210, 254
        if i+1 <= streak:
            col = accent_light + (255,) if i+1 < streak else (255,199,60,255)
        else:
            col = (55,58,63,255)
        ImageDraw.Draw(base).rounded_rectangle([x0,y0,x1,y1], radius=14, fill=col)
        try:
            f = ImageFont.truetype(FONT_BOLD, 20)
        except: f = ImageFont.load_default()
        ImageDraw.Draw(base).text(((x0+x1)//2, (y0+y1)//2), f"{i+1}", font=f, fill=(255,255,255,255), anchor="mm")
        if i+1 == 7:
            try: sf = ImageFont.truetype(FONT_BOLD, 12)
            except: sf = f
            ImageDraw.Draw(base).text(((x0+x1)//2, y1+12), "CAJA GRANDE", font=sf, fill=(255,199,60,255), anchor="mt")
    # check mark en los completados
    for i in range(streak):
        x0 = 24 + i * cell_w
        x1 = x0 + cell_w - 8
        try: chk = ImageFont.truetype(FONT_BOLD, 14)
        except: chk = ImageFont.load_default()
        ImageDraw.Draw(base).text(((x0+x1)//2, y0 - 14), "✓", font=chk, fill=(255,199,60,200), anchor="mm")

    mask = Image.new("L", (W,H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,W,H], radius=28, fill=255)
    card = Image.new("RGBA", (W,H), (0,0,0,0))
    card.paste(base, (0,0), mask)
    draw = ImageDraw.Draw(card)

    # avatar con sombra
    shadow = Image.new("RGBA", (90,90), (0,0,0,0))
    ImageDraw.Draw(shadow).ellipse((0,0,90,90), fill=(0,0,0,60))
    card.paste(shadow, (30, 28), shadow)
    try:
        data = await _download(avatar_url)
        av = Image.open(io.BytesIO(data)).convert("RGBA").resize((80,80), Image.LANCZOS)
    except: av = Image.new("RGBA", (80,80), (80,80,80,255))
    am = Image.new("L", (80,80), 0); ImageDraw.Draw(am).ellipse((0,0,80,80), fill=255)
    card.paste(av, (28, 26), am)
    draw.ellipse((28,26,108,106), outline=(255,255,255,40), width=2)

    font_name = ImageFont.truetype(FONT_BOLD, 30)
    font_reward = ImageFont.truetype(FONT_BOLD, 36)
    font_sub = ImageFont.truetype(FONT_REGULAR, 18)
    font_small = ImageFont.truetype(FONT_REGULAR, 15)

    clean_name = _clean(username)[:20]
    draw.text((126, 32), f"@{clean_name}", font=font_name, fill=(255,255,255,255))

    total_coins = amount + streak_coins
    draw.text((126, 72), f"+{total_coins} SoulCoins", font=font_reward, fill=accent + (255,))
    if streak_xp > 0:
        draw.text((126, 118), f"+{streak_xp} XP", font=font_sub, fill=(255,199,60,255))

    draw.text((126, 150), f"Balance: {balance:,} SoulCoins", font=font_sub, fill=(170,173,178,255))

    # streak label
    draw.text((24, 180), f"🔥 RACHA DÍA {streak}/7", font=font_sub, fill=(255,255,255,255))
    if streak == 7:
        draw.text((W-24, 180), "💎 ¡CAJA GRANDE!", font=font_sub, fill=(255,199,60,255), anchor="rm")

    draw.text((W//2, H-14), "SoulSeeker™ • Daily", font=font_small, fill=(110,114,120,255), anchor="mm")
    buf = io.BytesIO(); card.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

async def render_streaks_overview(username: str, avatar_url: str, streaks: list[dict]) -> io.BytesIO:
    # streaks: list of {type, current, max, label}
    W, H = 700, 260 + len(streaks)*54
    BG = (22, 24, 30)
    base = Image.new("RGBA", (W, H), BG + (255,))
    bdraw = ImageDraw.Draw(base)
    for y in range(H):
        t=y/H
        bdraw.line([(0,y),(W,y)], fill=(int(22+t*12), int(24+t*10), int(30+t*20),255))
    mask = Image.new("L", (W,H), 0); ImageDraw.Draw(mask).rounded_rectangle([0,0,W,H], radius=22, fill=255)
    card = Image.new("RGBA", (W,H), (0,0,0,0)); card.paste(base,(0,0),mask)
    draw = ImageDraw.Draw(card)
    try:
        data = await _download(avatar_url)
        av = Image.open(io.BytesIO(data)).convert("RGBA").resize((64,64), Image.LANCZOS)
    except: av = Image.new("RGBA", (64,64), (80,80,80,255))
    am = Image.new("L", (64,64), 0); ImageDraw.Draw(am).ellipse((0,0,64,64), fill=255)
    card.paste(av, (24,24), am)
    font_b = ImageFont.truetype(FONT_BOLD, 22) if os.path.exists(FONT_BOLD) else ImageFont.load_default()
    font_r = ImageFont.truetype(FONT_REGULAR, 16) if os.path.exists(FONT_REGULAR) else ImageFont.load_default()
    draw.text((104, 36), _clean(username)[:18], font=font_b, fill=(255,255,255,255))
    draw.text((104, 62), "Rachas", font=font_r, fill=(160,160,165,255))
    y=110
    for s in streaks:
        label = s.get("label","")
        cur = s.get("current",0); mx = s.get("max",0)
        draw.rounded_rectangle([24, y, W-24, y+44], radius=12, fill=(38,40,45,255), outline=(55,58,63,40), width=1)
        draw.text((32, y+10), label[:28], font=font_r, fill=(255,255,255,255))
        draw.text((W-24, y+10), f"{cur} días (récord {mx})", font=font_r, fill=(88,101,242,255), anchor="rm")
        y+=54
    draw.text((W//2, H-14), "SoulSeeker™ • Rachas", font=font_r, fill=(110,114,120,255), anchor="mm")
    buf=io.BytesIO(); card.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

async def render_boss_card(boss_name: str, current_hp: int, max_hp: int, top: list[tuple[str,int]], image_url: str | None = None) -> io.BytesIO:
    W, H = 934, 360
    BG = (20, 16, 16)
    accent = (231, 76, 60)
    accent_light = (255, 120, 100)
    base = Image.new("RGBA", (W,H), BG+(255,))
    bdraw = ImageDraw.Draw(base)
    for y in range(H):
        t=y/H
        bdraw.line([(0,y),(W,y)], fill=(int(20+t*30), int(16+t*10), int(16+t*10),255))
    # diagonal accent rojo sutil
    overlay = Image.new("RGBA", (W,H), (0,0,0,0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon([(W-240,0),(W,0),(W,H),(W-400,H)], fill=accent+(30,))
    base = Image.alpha_composite(base, overlay)
    # boss image left — bigger
    if image_url:
        try:
            data = await _download(image_url)
            bimg = Image.open(io.BytesIO(data)).convert("RGBA").resize((280,280), Image.LANCZOS)
            m = Image.new("L", (280,280), 0); ImageDraw.Draw(m).rounded_rectangle([0,0,280,280], radius=28, fill=255)
            base.paste(bimg, (28,48), m)
            ImageDraw.Draw(base).rounded_rectangle([28,48,312,328], radius=28, outline=accent+(180,), width=3)
        except: pass
    mask = Image.new("L", (W,H), 0); ImageDraw.Draw(mask).rounded_rectangle([0,0,W,H], radius=28, fill=255)
    card = Image.new("RGBA", (W,H), (0,0,0,0)); card.paste(base,(0,0),mask)
    draw = ImageDraw.Draw(card)
    font_b = ImageFont.truetype(FONT_BOLD, 34)
    font_r = ImageFont.truetype(FONT_REGULAR, 20)
    font_s = ImageFont.truetype(FONT_REGULAR, 16)
    font_small = ImageFont.truetype(FONT_REGULAR, 14)
    tx = 340 if image_url else 28
    draw.text((tx, 32), f"👹 {_clean(boss_name)[:22]}", font=font_b, fill=(255,255,255,255))
    # HP bar — thicker
    pct = current_hp / max_hp if max_hp else 0
    bar_x, bar_y, bar_w, bar_h = tx, 84, W - tx - 28, 30
    ImageDraw.Draw(card).rounded_rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+bar_h], radius=15, fill=(45,40,40,255), outline=(60,40,40,255), width=1)
    fill_w = int(bar_w * pct)
    if fill_w>4:
        fimg = Image.new("RGBA", (fill_w, bar_h), (0,0,0,0))
        fd = ImageDraw.Draw(fimg)
        for x in range(fill_w):
            t=x/max(1,fill_w)
            r=int(231*(1-t)+255*t); g=int(76*(1-t)+100*t); b=int(60*(1-t)+60*t)
            fd.line([(x,0),(x,bar_h)], fill=(r,g,b,255))
        fm = Image.new("L", (fill_w, bar_h), 0); ImageDraw.Draw(fm).rounded_rectangle([0,0,fill_w,bar_h], radius=15, fill=255)
        if pct<0.98: ImageDraw.Draw(fm).rectangle([fill_w-15,0,fill_w,bar_h], fill=255)
        card.paste(fimg, (bar_x, bar_y), fm)
    draw.text((bar_x+bar_w//2, bar_y+7), f"{int(pct*100)}%  {current_hp:,}/{max_hp:,}", font=font_s, fill=(255,255,255,255), anchor="mm")
    # top damage
    draw.text((tx, 132), "⚔️ Top daño:", font=font_r, fill=accent + (255,))
    y=164
    medal_colors = [(255,215,0),(192,192,192),(205,127,80)]
    for i,(name,dmg) in enumerate(top[:3]):
        mc = medal_colors[i] if i < 3 else (200,200,200)
        # medal dot
        draw.ellipse([tx, y+4, tx+16, y+20], fill=mc+(255,))
        draw.text((tx+24, y), f"{_clean(name)[:18]} — {dmg:,}", font=font_r, fill=(255,255,255,255) if i==0 else (200,200,200,255))
        y+=30
    draw.text((W//2, H-16), "SoulSeeker™ • Boss Semanal", font=font_small, fill=(110,114,120,255), anchor="mm")
    buf=io.BytesIO(); card.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

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
