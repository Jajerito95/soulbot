from __future__ import annotations
import random
import time

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

GAME_COOLDOWN = 10  # segundos entre partidas por usuario, evita spam a la API

SLOT_EMOJIS = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
SLOT_WEIGHTS = [30, 25, 20, 15, 7, 3]  # 💎 y 7️⃣ son más raros

TRIVIA_QUESTIONS = [
    ("¿Cuántos lados tiene un hexágono?", ["6", "5", "8", "7"], 0),
    ("¿Qué gas respiran principalmente los humanos?", ["Oxígeno", "Nitrógeno", "CO2", "Helio"], 0),
    ("¿Cuál es el planeta más cercano al Sol?", ["Mercurio", "Venus", "Tierra", "Marte"], 0),
    ("¿En qué continente está Egipto?", ["África", "Asia", "Europa", "Oceanía"], 0),
    ("¿Cuánto es 9 x 7?", ["63", "56", "72", "54"], 0),
    ("¿Qué animal es conocido como 'el rey de la selva'?", ["León", "Tigre", "Elefante", "Gorila"], 0),
    ("¿Cuál es el idioma más hablado del mundo?", ["Mandarín", "Inglés", "Español", "Hindi"], 0),
    ("¿Cuántos huesos tiene el cuerpo humano adulto?", ["206", "180", "220", "150"], 0),
]

TRIVIA_REWARD = 50


class TriviaView(discord.ui.View):
    def __init__(self, correct_index: int, reward: int, author_id: int):
        super().__init__(timeout=15)
        self.correct_index = correct_index
        self.reward = reward
        self.author_id = author_id
        self.answered = False

    async def _answer(self, interaction: discord.Interaction, index: int):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=error_embed("Esta trivia no es tuya."), ephemeral=True)
            return
        if self.answered:
            await interaction.response.send_message(embed=error_embed("Ya respondiste esta trivia."), ephemeral=True)
            return
        self.answered = True

        for child in self.children:
            child.disabled = True

        if index == self.correct_index:
            new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, self.reward)
            embed = success_embed(f"¡Correcto! 🎉\n💰 +{self.reward} SoulCoins\n👛 Saldo: **{new_balance}**", title="🧠 Trivia")
        else:
            embed = error_embed("Respuesta incorrecta. ¡Suerte la próxima!", title="🧠 Trivia")

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="A", style=discord.ButtonStyle.secondary)
    async def a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._answer(interaction, 0)

    @discord.ui.button(label="B", style=discord.ButtonStyle.secondary)
    async def b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._answer(interaction, 1)

    @discord.ui.button(label="C", style=discord.ButtonStyle.secondary)
    async def c(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._answer(interaction, 2)

    @discord.ui.button(label="D", style=discord.ButtonStyle.secondary)
    async def d(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._answer(interaction, 3)


class MinigamesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns: dict[int, float] = {}

    def _check_cooldown(self, user_id: int) -> float:
        """Devuelve segundos restantes de cooldown (0 si puede jugar)."""
        now = time.time()
        last = self.cooldowns.get(user_id, 0)
        remaining = GAME_COOLDOWN - (now - last)
        return max(0, remaining)

    def _set_cooldown(self, user_id: int):
        self.cooldowns[user_id] = time.time()

    @app_commands.command(name="coinflip", description="Apuesta SoulCoins a cara o cruz")
    @app_commands.describe(apuesta="Cantidad a apostar", eleccion="Cara o cruz")
    @app_commands.choices(eleccion=[
        app_commands.Choice(name="Cara", value="cara"),
        app_commands.Choice(name="Cruz", value="cruz"),
    ])
    async def coinflip(self, interaction: discord.Interaction, apuesta: app_commands.Range[int, 10, None], eleccion: app_commands.Choice[str]):
        remaining = self._check_cooldown(interaction.user.id)
        if remaining:
            await interaction.response.send_message(embed=error_embed(f"Espera **{remaining:.0f}s** antes de jugar de nuevo."), ephemeral=True)
            return

        balance = await db.get_balance(interaction.guild_id, interaction.user.id)
        if balance < apuesta:
            await interaction.response.send_message(embed=error_embed(f"No tienes suficientes SoulCoins. Tu saldo: **{balance}**"), ephemeral=True)
            return

        self._set_cooldown(interaction.user.id)
        result = random.choice(["cara", "cruz"])
        won = result == eleccion.value

        if won:
            new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, apuesta)
            embed = success_embed(f"🪙 Salió **{result}**. ¡Ganaste **{apuesta}** SoulCoins!\n👛 Saldo: **{new_balance}**", title="🎲 Coinflip")
        else:
            new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, -apuesta)
            embed = error_embed(f"🪙 Salió **{result}**. Perdiste **{apuesta}** SoulCoins.\n👛 Saldo: **{new_balance}**", title="🎲 Coinflip")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slots", description="Juega a la tragaperras con tus SoulCoins")
    @app_commands.describe(apuesta="Cantidad a apostar")
    async def slots(self, interaction: discord.Interaction, apuesta: app_commands.Range[int, 10, None]):
        remaining = self._check_cooldown(interaction.user.id)
        if remaining:
            await interaction.response.send_message(embed=error_embed(f"Espera **{remaining:.0f}s** antes de jugar de nuevo."), ephemeral=True)
            return

        balance = await db.get_balance(interaction.guild_id, interaction.user.id)
        if balance < apuesta:
            await interaction.response.send_message(embed=error_embed(f"No tienes suficientes SoulCoins. Tu saldo: **{balance}**"), ephemeral=True)
            return

        self._set_cooldown(interaction.user.id)
        reels = random.choices(SLOT_EMOJIS, weights=SLOT_WEIGHTS, k=3)
        display = " ".join(reels)

        if reels[0] == reels[1] == reels[2]:
            multiplier = 10 if reels[0] in ("💎", "7️⃣") else 5
            winnings = apuesta * multiplier
            new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, winnings)
            embed = success_embed(f"{display}\n\n🎉 ¡Triple! Ganaste **{winnings}** SoulCoins (x{multiplier})\n👛 Saldo: **{new_balance}**", title="🎰 Slots")
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            winnings = apuesta * 2
            new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, winnings)
            embed = success_embed(f"{display}\n\n✨ Pareja. Ganaste **{winnings}** SoulCoins (x2)\n👛 Saldo: **{new_balance}**", title="🎰 Slots")
        else:
            new_balance = await db.add_coins(interaction.guild_id, interaction.user.id, -apuesta)
            embed = error_embed(f"{display}\n\nSin suerte. Perdiste **{apuesta}** SoulCoins.\n👛 Saldo: **{new_balance}**", title="🎰 Slots")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="trivia", description="Responde una pregunta y gana SoulCoins")
    async def trivia(self, interaction: discord.Interaction):
        remaining = self._check_cooldown(interaction.user.id)
        if remaining:
            await interaction.response.send_message(embed=error_embed(f"Espera **{remaining:.0f}s** antes de jugar de nuevo."), ephemeral=True)
            return

        self._set_cooldown(interaction.user.id)
        question, options, correct_index = random.choice(TRIVIA_QUESTIONS)

        # Barajamos las opciones para que la correcta no esté siempre en la misma posición
        correct_text = options[correct_index]
        shuffled = options.copy()
        random.shuffle(shuffled)
        correct_index = shuffled.index(correct_text)

        config = await db.get_guild_config(interaction.guild_id)
        reward = config["trivia_reward"]

        letters = ["A", "B", "C", "D"]
        options_text = "\n".join(f"**{letters[i]}.** {opt}" for i, opt in enumerate(shuffled))
        embed = base_embed(f"{question}\n\n{options_text}\n\n⏱️ Tienes 15 segundos.", COLOR, title="🧠 Trivia")

        view = TriviaView(correct_index, reward, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(MinigamesCog(bot))
