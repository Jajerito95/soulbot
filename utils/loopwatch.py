from __future__ import annotations
"""Forense del event loop: detecta bloqueos y vuelca stacks de todos los hilos.

Cuando el loop se atasca >threshold segundos, imprime el stack de cada hilo.
El hilo que esté en `run_forever/_run_once` con tu código debajo es el culpable.
"""
import asyncio
import sys
import time
import traceback


async def loop_watch(bot, interval: int = 5, threshold: float = 8.0):
    print(f"[loopwatch] vigilando bloqueos >{threshold}s", flush=True)
    last = time.monotonic()
    while True:
        await asyncio.sleep(interval)
        now = time.monotonic()
        lag = now - last - interval
        last = now
        if lag < threshold:
            continue
        print(f"[loopwatch] ⚠️ loop bloqueado {lag:.1f}s — stacks:", flush=True)
        try:
            for tid, frame in sys._current_frames().items():
                print(f"--- hilo {tid} ---", flush=True)
                traceback.print_stack(frame, file=sys.stdout)
        except Exception as e:
            print(f"[loopwatch] no pude volcar stacks: {e}", flush=True)
