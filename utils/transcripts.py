from __future__ import annotations
import html
import os
import discord

from config import DATA_DIR

TRANSCRIPTS_DIR = os.path.join(DATA_DIR, "transcripts")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Transcript — {channel_name}</title>
<style>
  body {{ background:#313338; color:#dbdee1; font-family:'gg sans',Segoe UI,Arial,sans-serif; margin:0; padding:24px; }}
  .header {{ font-size:20px; font-weight:700; margin-bottom:4px; }}
  .subheader {{ color:#949ba4; font-size:13px; margin-bottom:20px; }}
  .msg {{ display:flex; gap:14px; padding:8px 0; }}
  .avatar {{ width:40px; height:40px; border-radius:50%; flex-shrink:0; }}
  .author {{ font-weight:600; color:#f2f3f5; }}
  .timestamp {{ color:#949ba4; font-size:12px; margin-left:8px; font-weight:400; }}
  .content {{ white-space:pre-wrap; word-wrap:break-word; }}
  .attachment {{ color:#00a8fc; }}
  hr {{ border:none; border-top:1px solid #3f4147; margin:16px 0; }}
</style>
</head>
<body>
  <div class="header">🎫 Transcript — {channel_name}</div>
  <div class="subheader">SoulBot System • SoulSeeker™ | All rights reserved.</div>
  <hr>
  {messages}
</body>
</html>
"""

MSG_TEMPLATE = """<div class="msg">
  <img class="avatar" src="{avatar}">
  <div>
    <span class="author">{author}</span><span class="timestamp">{time}</span>
    <div class="content">{content}{attachments}</div>
  </div>
</div>
"""


async def generate_transcript(channel: discord.TextChannel) -> str:
    """Genera el HTML del transcript y devuelve la ruta del archivo guardado."""
    messages_html = []
    async for msg in channel.history(limit=1000, oldest_first=True):
        content = html.escape(msg.content or "*(sin contenido de texto)*")
        attachments = ""
        for att in msg.attachments:
            attachments += f'<br><a class="attachment" href="{att.url}">📎 {html.escape(att.filename)}</a>'

        messages_html.append(
            MSG_TEMPLATE.format(
                avatar=msg.author.display_avatar.url,
                author=html.escape(msg.author.display_name),
                time=msg.created_at.strftime("%d/%m/%Y %H:%M"),
                content=content,
                attachments=attachments,
            )
        )

    full_html = TEMPLATE.format(channel_name=html.escape(channel.name), messages="\n".join(messages_html))

    path = os.path.join(TRANSCRIPTS_DIR, f"{channel.id}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(full_html)
    return path
