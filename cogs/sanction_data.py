"""
Catálogo de infracciones de SoulBot.
Cada infracción tiene una "escalera" de sanciones: la primera posición es
la 1ª sanción, las siguientes son la reincidencia. Si el usuario reincide
más veces de las que tiene la escalera, se repite el último escalón.

Formato de cada escalón:
    "warn"          -> solo advertencia
    "warn_change"   -> advertencia + (si aplica) reseteo forzado de apodo
    "Xd"            -> baneo temporal de X días
    "perm"          -> baneo permanente
"""

INFRACTIONS: dict[str, dict] = {}


def _add(key: str, label: str, ladder: list[str]):
    INFRACTIONS[key] = {"label": label, "ladder": ladder}


# key                          label                                              escalera
_add("spam", "Spam", ["1d", "3d", "7d", "14d"])
_add("flood", "Flood", ["1d", "3d", "7d", "14d"])
_add("mayusculas", "Mayúsculas excesivas", ["warn", "1d", "3d"])
_add("chat_disruption", "Mensajes sin sentido (Chat Disruption)", ["warn", "1d", "3d"])
_add("ghost_ping", "Ghost Ping", ["warn", "1d", "3d", "7d"])
_add("publicidad", "Publicidad (servidores/redes)", ["7d", "30d", "perm"])
_add("autopromocion", "Auto-promoción reiterada", ["3d", "7d", "14d"])
_add("enlaces_maliciosos", "Enlaces maliciosos", ["perm"])
_add("phishing", "Phishing", ["perm"])
_add("malware", "Malware", ["perm"])
_add("scamming", "Scamming / Estafas", ["perm"])
_add("intento_estafa", "Intento de estafa", ["30d", "perm"])
_add("suplantacion", "Suplantación de identidad", ["14d", "30d", "perm"])
_add("cuentas_alt", "Uso de cuentas alternativas para evadir sanciones", ["perm"])
_add("evasion_ban", "Evasión de ban", ["perm"])
_add("toxicidad_leve", "Toxicidad leve", ["warn", "1d", "3d"])
_add("toxicidad_grave", "Toxicidad grave", ["7d", "14d", "30d"])
_add("acoso", "Acoso (Harassment)", ["14d", "perm"])
_add("amenazas", "Amenazas", ["30d", "perm"])
_add("amenazas_reales", "Amenazas reales o creíbles", ["perm"])
_add("discurso_odio", "Discurso de odio", ["30d", "perm"])
_add("racismo", "Racismo", ["30d", "perm"])
_add("xenofobia", "Xenofobia", ["30d", "perm"])
_add("homofobia", "Homofobia / Transfobia", ["30d", "perm"])
_add("nsfw", "Contenido NSFW", ["7d", "30d"])
_add("pornografia_extrema", "Pornografía extrema", ["perm"])
_add("gore_extremo", "Gore extremo", ["perm"])
_add("doxxing", "Doxxing", ["perm"])
_add("datos_personales", "Compartir datos personales", ["30d", "perm"])
_add("chantaje", "Chantaje", ["perm"])
_add("extorsion", "Extorsión", ["perm"])
_add("ingenieria_social", "Ingeniería social", ["30d", "perm"])
_add("robo_cuentas", "Intento de robo de cuentas", ["perm"])
_add("cheats_mc", "Uso de cheats / hacks (Minecraft)", ["30d", "perm"])
_add("cliente_modificado", "Cliente modificado no permitido", ["30d", "perm"])
_add("xray", "X-Ray", ["30d", "perm"])
_add("killaura", "KillAura", ["perm"])
_add("aim_assist", "Aim Assist", ["30d", "perm"])
_add("reach", "Reach", ["perm"])
_add("velocity", "Velocity", ["perm"])
_add("autoclicker", "AutoClicker", ["30d", "perm"])
_add("macro", "Macro", ["14d", "30d", "perm"])
_add("scripts", "Scripts no permitidos", ["30d", "perm"])
_add("mod_ilegal_cliente", "Modificaciones ilegales del cliente", ["30d", "perm"])
_add("bug_abuse", "Explotación de bugs (Bug Abuse)", ["14d", "30d", "perm"])
_add("duping", "Duplicación de objetos (Duping)", ["30d", "perm"])
_add("win_trading", "Boosting / Win Trading", ["14d", "30d"])
_add("griefing", "Griefing", ["7d", "30d"])
_add("teaming_ilegal", "Teaming ilegal", ["7d", "30d"])
_add("stream_sniping", "Stream Sniping (si aplica)", ["14d", "30d"])
_add("ban_evasion", "Ban Evasion", ["perm"])
_add("vpn_evasion", "Uso de VPN para evadir sanciones", ["30d", "perm"])
_add("abuso_reportes", "Abuso de reportes", ["warn", "7d"])
_add("reportes_falsos", "Reportes falsos reiterados", ["7d", "30d"])
_add("abuso_tickets", "Abuso de tickets", ["warn", "3d", "7d"])
_add("abuso_comandos", "Abuso de comandos", ["warn", "3d"])
_add("nick_ofensivo", "Nick ofensivo", ["warn_change", "7d"])
_add("avatar_ofensivo", "Avatar ofensivo", ["warn_change", "7d"])
_add("bio_ofensiva", "Estado/Bio ofensiva", ["warn_change", "7d"])
_add("evasion_filtros", "Evasión de filtros automáticos", ["7d", "30d"])
_add("publicidad_dm", "Publicidad por DM", ["14d", "perm"])
_add("incitacion_odio", "Incitación al odio", ["30d", "perm"])
_add("incitacion_autolesion", "Incitación al suicidio o autolesión", ["perm"])
_add("contenido_ilegal", "Distribución de contenido ilegal", ["perm"])
_add("venta_cuentas", "Venta de cuentas robadas", ["perm"])
_add("venta_software_malicioso", "Venta de software malicioso", ["perm"])
_add("compraventa_hacks", "Compra/venta de hacks para el servidor", ["30d", "perm"])
_add("comprometer_servidor", "Intento de comprometer el servidor", ["perm"])


def infraction_choices() -> list[tuple[str, str]]:
    """Lista (key, label) para autocompletado."""
    return [(key, data["label"]) for key, data in INFRACTIONS.items()]


def get_punishment(key: str, previous_count: int) -> str:
    """Devuelve el código de sanción ('warn', 'warn_change', 'Xd', 'perm') según reincidencia."""
    ladder = INFRACTIONS[key]["ladder"]
    index = min(previous_count, len(ladder) - 1)
    return ladder[index]
