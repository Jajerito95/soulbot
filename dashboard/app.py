from __future__ import annotations
import os
import datetime
import requests
from functools import wraps

from flask import Flask, request, redirect, session, render_template, url_for, abort
from dotenv import load_dotenv

import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", "cambia-esto-en-produccion")

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")  # ej: https://tu-dashboard.onrender.com/callback
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "ReyChroxito")

DISCORD_API = "https://discord.com/api/v10"
OAUTH_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"


# ---------- decoradores de acceso ----------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if not session.get("is_staff"):
            return redirect(url_for("staff_login"))
        return view(*args, **kwargs)
    return wrapped


# ---------- Discord API helpers ----------

def bot_headers():
    return {"Authorization": f"Bot {BOT_TOKEN}"}


def is_member_of_guild(user_id: int) -> bool:
    r = requests.get(f"{DISCORD_API}/guilds/{GUILD_ID}/members/{user_id}", headers=bot_headers())
    return r.status_code == 200


def get_member_avatar(user: dict) -> str:
    if user.get("avatar"):
        return f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


# ---------- login con Discord (OAuth2) ----------

@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard_home"))
    return render_template("login.html")


@app.route("/login")
def login():
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
    }
    query_string = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return redirect(f"{OAUTH_AUTHORIZE_URL}?{query_string}")


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("home"))

    token_resp = requests.post(
        OAUTH_TOKEN_URL,
        data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if token_resp.status_code != 200:
        return "Error autenticando con Discord.", 400

    access_token = token_resp.json()["access_token"]
    user_resp = requests.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {access_token}"})
    user = user_resp.json()

    if not is_member_of_guild(int(user["id"])):
        return render_template("not_member.html")

    session["user"] = {"id": user["id"], "username": user["username"], "avatar": get_member_avatar(user)}
    return redirect(url_for("dashboard_home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------- dashboard personal (todo el mundo) ----------

@app.route("/me")
@login_required
def dashboard_home():
    user_id = int(session["user"]["id"])

    level_row = db.query_one("SELECT xp, level FROM levels WHERE guild_id = ? AND user_id = ?", (GUILD_ID, user_id))
    xp, level = level_row if level_row else (0, 0)

    balance_row = db.query_one("SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?", (GUILD_ID, user_id))
    balance = balance_row[0] if balance_row else 0

    tickets = db.query(
        "SELECT id, category, status, created_at, closed_at FROM tickets WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 10",
        (GUILD_ID, user_id),
    )

    sanctions = db.query(
        "SELECT id, action, reason, created_at FROM staff_actions WHERE guild_id = ? AND target_id = ? ORDER BY created_at DESC LIMIT 10",
        (GUILD_ID, user_id),
    )

    return render_template(
        "dashboard.html", user=session["user"], xp=xp, level=level, balance=balance,
        tickets=tickets, sanctions=sanctions, is_staff=session.get("is_staff", False),
    )


@app.route("/me/stats")
@login_required
def dashboard_stats():
    user_id = int(session["user"]["id"])
    period = request.args.get("periodo", "week")
    days = {"day": 1, "week": 7, "month": 30}.get(period, 7)
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()

    xp_gained = db.query_one(
        "SELECT COALESCE(SUM(amount), 0) FROM xp_events WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
        (GUILD_ID, user_id, cutoff),
    )[0]

    earned = db.query_one(
        "SELECT COALESCE(SUM(amount), 0) FROM economy_transactions WHERE guild_id = ? AND user_id = ? AND amount > 0 AND created_at >= ?",
        (GUILD_ID, user_id, cutoff),
    )[0]
    spent = db.query_one(
        "SELECT COALESCE(SUM(-amount), 0) FROM economy_transactions WHERE guild_id = ? AND user_id = ? AND amount < 0 AND created_at >= ?",
        (GUILD_ID, user_id, cutoff),
    )[0]

    return {"periodo": period, "xp_ganada": xp_gained, "coins_ganadas": earned, "coins_gastadas": spent}


@app.route("/me/ticket/<int:ticket_id>")
@login_required
def view_transcript(ticket_id: int):
    user_id = int(session["user"]["id"])
    row = db.query_one("SELECT channel_id, user_id FROM tickets WHERE id = ? AND guild_id = ?", (ticket_id, GUILD_ID))
    if not row or row[1] != user_id:
        abort(403)
    channel_id = row[0]
    public_url = os.getenv("BOT_PUBLIC_URL", "")
    return redirect(f"{public_url}/transcripts/{channel_id}.html")


# ---------- acceso Staff (contraseña, tras el login de Discord) ----------

@app.route("/staff/login", methods=["GET", "POST"])
@login_required
def staff_login():
    if request.method == "POST":
        if request.form.get("password") == STAFF_PASSWORD:
            session["is_staff"] = True
            return redirect(url_for("staff_panel"))
        return render_template("staff_login.html", error="Contraseña incorrecta.")
    return render_template("staff_login.html", error=None)


@app.route("/staff")
@staff_required
def staff_panel():
    config = db.get_guild_config(GUILD_ID)

    open_tickets = db.query_one("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'", (GUILD_ID,))[0]
    pending_appeals = db.query_one("SELECT COUNT(*) FROM appeals WHERE guild_id = ? AND status = 'pending'", (GUILD_ID,))[0]
    total_members_tracked = db.query_one("SELECT COUNT(*) FROM levels WHERE guild_id = ?", (GUILD_ID,))[0]

    appeals = db.query(
        "SELECT id, sanction_id, user_id, reason, status FROM appeals WHERE guild_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 20",
        (GUILD_ID,),
    )

    return render_template(
        "staff_panel.html", user=session["user"], config=config,
        open_tickets=open_tickets, pending_appeals=pending_appeals, total_members_tracked=total_members_tracked,
        appeals=appeals,
    )


@app.route("/staff/modules", methods=["POST"])
@staff_required
def staff_toggle_module():
    module_map = {
        "levels_enabled": "levels_enabled", "automod_enabled": "automod_enabled",
        "tickets_paused": "tickets_paused", "xp_weekend_enabled": "xp_weekend_enabled",
    }
    column = module_map.get(request.form.get("module"))
    if column:
        current = db.get_guild_config(GUILD_ID)[column]
        db.update_guild_config(GUILD_ID, **{column: 0 if current else 1})
    return redirect(url_for("staff_panel"))


@app.route("/staff/appeal/<int:appeal_id>/<action>", methods=["POST"])
@staff_required
def staff_resolve_appeal(appeal_id: int, action: str):
    if action not in ("approve", "deny"):
        abort(400)
    status = "approved" if action == "approve" else "denied"
    db.execute(
        "UPDATE appeals SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, int(session["user"]["id"]), appeal_id),
    )

    if status == "approved":
        appeal = db.query_one("SELECT sanction_id, user_id FROM appeals WHERE id = ?", (appeal_id,))
        sanction_id, target_id = appeal
        sanction = db.query_one("SELECT action FROM staff_actions WHERE id = ?", (sanction_id,))
        if sanction and sanction[0] == "ban":
            requests.delete(f"{DISCORD_API}/guilds/{GUILD_ID}/bans/{target_id}", headers=bot_headers())

    return redirect(url_for("staff_panel"))


@app.route("/staff/ban", methods=["POST"])
@staff_required
def staff_ban_user():
    target_id = request.form.get("user_id")
    reason = request.form.get("reason", "Baneado desde el Dashboard")
    if not target_id or not target_id.isdigit():
        abort(400)
    requests.put(
        f"{DISCORD_API}/guilds/{GUILD_ID}/bans/{target_id}",
        headers={**bot_headers(), "X-Audit-Log-Reason": reason},
        json={},
    )
    db.execute(
        "INSERT INTO staff_actions (guild_id, target_id, staff_id, action, reason) VALUES (?, ?, ?, 'ban', ?)",
        (GUILD_ID, int(target_id), int(session["user"]["id"]), reason),
    )
    return redirect(url_for("staff_panel"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
