"""Estado global de mantenimiento, compartido entre cogs (AutoMod, Niveles, etc.)."""
_enabled = False


def is_maintenance() -> bool:
    return _enabled


def set_maintenance(value: bool):
    global _enabled
    _enabled = value
