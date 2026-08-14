from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils.embeds import success_embed, error_embed, base_embed
from config import COLOR

WIN_REWARD_DEFAULT = 40
DRAW_REWARD_DEFAULT = 10


async def _reward(guild_id: int, user_id: int, amount: int) -> int:
    return await db.add_coins(guild_id, user_id, amount)


async def _get_rewards(guild_id: int) -> tuple[int, int]:
    config = await db.get_guild_config(guild_id)
    return config["game_win_reward"], config["game_draw_reward"]


def _validate_opponent(interaction: discord.Interaction, opponent: discord.Member):
    if opponent.id == interaction.user.id:
        return "No puedes jugar contra ti mismo."
    if opponent.bot:
        return "No puedes jugar contra un bot."
    return None


# ==================== 3 EN RAYA ====================

class TicTacToeButton(discord.ui.Button):
    def __init__(self, index: int):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=index // 3)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view
        await view.handle_move(interaction, self.index)


class TicTacToeView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=120)
        self.p1 = p1
        self.p2 = p2
        self.turn = p1
        self.board = [None] * 9
        for i in range(9):
            self.add_item(TicTacToeButton(i))

    def _symbol(self, player: discord.Member) -> str:
        return "❌" if player.id == self.p1.id else "⭕"

    def _check_winner(self):
        lines = [
            (0, 1, 2), (3, 4, 5), (6, 7, 8),
            (0, 3, 6), (1, 4, 7), (2, 5, 8),
            (0, 4, 8), (2, 4, 6),
        ]
        for a, b, c in lines:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                return self.board[a]
        if all(self.board):
            return "draw"
        return None

    async def handle_move(self, interaction: discord.Interaction, index: int):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await interaction.response.send_message(embed=error_embed("Esta partida no es tuya."), ephemeral=True)
            return
        if interaction.user.id != self.turn.id:
            await interaction.response.send_message(embed=error_embed("Espera tu turno."), ephemeral=True)
            return
        if self.board[index] is not None:
            await interaction.response.send_message(embed=error_embed("Esa casilla ya está ocupada."), ephemeral=True)
            return

        symbol = self._symbol(self.turn)
        self.board[index] = symbol
        button: discord.ui.Button = self.children[index]
        button.label = symbol
        button.disabled = True
        button.style = discord.ButtonStyle.danger if symbol == "❌" else discord.ButtonStyle.success

        result = self._check_winner()
        if result:
            for child in self.children:
                child.disabled = True
            win_reward, draw_reward = await _get_rewards(interaction.guild_id)
            if result == "draw":
                await _reward(interaction.guild_id, self.p1.id, draw_reward)
                await _reward(interaction.guild_id, self.p2.id, draw_reward)
                embed = base_embed(f"Empate entre {self.p1.mention} y {self.p2.mention}.\n💰 +{draw_reward} SoulCoins para ambos.", COLOR, title="🎲 3 en raya — Empate")
            else:
                winner = self.p1 if symbol == self._symbol(self.p1) else self.p2
                new_balance = await _reward(interaction.guild_id, winner.id, win_reward)
                embed = success_embed(f"🏆 ¡Gana {winner.mention}!\n💰 +{win_reward} SoulCoins (saldo: {new_balance})", title="🎲 3 en raya")
            self.stop()
        else:
            self.turn = self.p2 if self.turn.id == self.p1.id else self.p1
            embed = base_embed(
                f"❌ {self.p1.mention}  vs  ⭕ {self.p2.mention}\n\nTurno de: {self.turn.mention}", COLOR, title="🎲 3 en raya"
            )

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ==================== 4 EN RAYA (Connect 4) ====================

ROWS, COLS = 6, 7
DISC_EMPTY = "⚪"
DISC_P1 = "🔴"
DISC_P2 = "🟡"
COLUMN_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]


class ConnectFourButton(discord.ui.Button):
    def __init__(self, col: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=COLUMN_EMOJIS[col], row=col // 4)
        self.col = col

    async def callback(self, interaction: discord.Interaction):
        view: ConnectFourView = self.view
        await view.handle_move(interaction, self.col)


class ConnectFourView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=180)
        self.p1 = p1
        self.p2 = p2
        self.turn = p1
        self.board = [[DISC_EMPTY] * COLS for _ in range(ROWS)]
        for c in range(COLS):
            self.add_item(ConnectFourButton(c))

    def _disc(self, player: discord.Member) -> str:
        return DISC_P1 if player.id == self.p1.id else DISC_P2

    def _render(self) -> str:
        return "\n".join("".join(row) for row in self.board)

    def _drop(self, col: int, disc: str) -> bool:
        for row in reversed(range(ROWS)):
            if self.board[row][col] == DISC_EMPTY:
                self.board[row][col] = disc
                return True
        return False

    def _check_winner(self, disc: str) -> bool:
        for r in range(ROWS):
            for c in range(COLS - 3):
                if all(self.board[r][c + i] == disc for i in range(4)):
                    return True
        for c in range(COLS):
            for r in range(ROWS - 3):
                if all(self.board[r + i][c] == disc for i in range(4)):
                    return True
        for r in range(ROWS - 3):
            for c in range(COLS - 3):
                if all(self.board[r + i][c + i] == disc for i in range(4)):
                    return True
        for r in range(3, ROWS):
            for c in range(COLS - 3):
                if all(self.board[r - i][c + i] == disc for i in range(4)):
                    return True
        return False

    async def handle_move(self, interaction: discord.Interaction, col: int):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await interaction.response.send_message(embed=error_embed("Esta partida no es tuya."), ephemeral=True)
            return
        if interaction.user.id != self.turn.id:
            await interaction.response.send_message(embed=error_embed("Espera tu turno."), ephemeral=True)
            return

        disc = self._disc(self.turn)
        if not self._drop(col, disc):
            await interaction.response.send_message(embed=error_embed("Esa columna ya está llena."), ephemeral=True)
            return

        win_reward, draw_reward = await _get_rewards(interaction.guild_id)

        if self._check_winner(disc):
            for child in self.children:
                child.disabled = True
            new_balance = await _reward(interaction.guild_id, self.turn.id, win_reward)
            embed = success_embed(
                f"{self._render()}\n\n🏆 ¡Gana {self.turn.mention}!\n💰 +{win_reward} SoulCoins (saldo: {new_balance})",
                title="🔴🟡 4 en raya",
            )
            self.stop()
        elif all(self.board[0][c] != DISC_EMPTY for c in range(COLS)):
            for child in self.children:
                child.disabled = True
            await _reward(interaction.guild_id, self.p1.id, draw_reward)
            await _reward(interaction.guild_id, self.p2.id, draw_reward)
            embed = base_embed(f"{self._render()}\n\nEmpate. 💰 +{draw_reward} SoulCoins para ambos.", COLOR, title="🔴🟡 4 en raya — Empate")
            self.stop()
        else:
            self.turn = self.p2 if self.turn.id == self.p1.id else self.p1
            embed = base_embed(
                f"{self._render()}\n\n🔴 {self.p1.mention}  vs  🟡 {self.p2.mention}\nTurno de: {self.turn.mention}",
                COLOR, title="🔴🟡 4 en raya",
            )

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ==================== PIEDRA, PAPEL O TIJERA ====================

RPS_EMOJI = {"piedra": "🪨", "papel": "📄", "tijera": "✂️"}
RPS_BEATS = {"piedra": "tijera", "papel": "piedra", "tijera": "papel"}


class RPSView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=60)
        self.p1 = p1
        self.p2 = p2
        self.choices: dict[int, str] = {}

    async def _pick(self, interaction: discord.Interaction, choice: str):
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await interaction.response.send_message(embed=error_embed("Esta partida no es tuya."), ephemeral=True)
            return
        if interaction.user.id in self.choices:
            await interaction.response.send_message(embed=error_embed("Ya elegiste."), ephemeral=True)
            return

        self.choices[interaction.user.id] = choice
        await interaction.response.send_message(embed=success_embed(f"Elegiste {RPS_EMOJI[choice]} {choice}."), ephemeral=True)

        if len(self.choices) == 2:
            await self._resolve(interaction)

    async def _resolve(self, interaction: discord.Interaction):
        c1, c2 = self.choices[self.p1.id], self.choices[self.p2.id]
        for child in self.children:
            child.disabled = True

        result_line = f"{self.p1.mention}: {RPS_EMOJI[c1]} {c1}\n{self.p2.mention}: {RPS_EMOJI[c2]} {c2}"
        win_reward, draw_reward = await _get_rewards(interaction.guild_id)

        if c1 == c2:
            await _reward(interaction.guild_id, self.p1.id, draw_reward)
            await _reward(interaction.guild_id, self.p2.id, draw_reward)
            embed = base_embed(f"{result_line}\n\nEmpate. 💰 +{draw_reward} SoulCoins para ambos.", COLOR, title="✊ Piedra, papel o tijera")
        else:
            winner = self.p1 if RPS_BEATS[c1] == c2 else self.p2
            new_balance = await _reward(interaction.guild_id, winner.id, win_reward)
            embed = success_embed(f"{result_line}\n\n🏆 ¡Gana {winner.mention}!\n💰 +{win_reward} SoulCoins (saldo: {new_balance})", title="✊ Piedra, papel o tijera")

        await interaction.message.edit(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Piedra", emoji="🪨", style=discord.ButtonStyle.secondary)
    async def piedra(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "piedra")

    @discord.ui.button(label="Papel", emoji="📄", style=discord.ButtonStyle.secondary)
    async def papel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "papel")

    @discord.ui.button(label="Tijera", emoji="✂️", style=discord.ButtonStyle.secondary)
    async def tijera(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._pick(interaction, "tijera")

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ==================== COG ====================

class BoardGamesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="tictactoe", description="Reta a alguien a 3 en raya (sin apuesta)")
    @app_commands.describe(oponente="A quién retas")
    async def tictactoe(self, interaction: discord.Interaction, oponente: discord.Member):
        error = _validate_opponent(interaction, oponente)
        if error:
            await interaction.response.send_message(embed=error_embed(error), ephemeral=True)
            return

        view = TicTacToeView(interaction.user, oponente)
        embed = base_embed(f"❌ {interaction.user.mention}  vs  ⭕ {oponente.mention}\n\nTurno de: {interaction.user.mention}", COLOR, title="🎲 3 en raya")
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="connect4", description="Reta a alguien a 4 en raya (sin apuesta)")
    @app_commands.describe(oponente="A quién retas")
    async def connect4(self, interaction: discord.Interaction, oponente: discord.Member):
        error = _validate_opponent(interaction, oponente)
        if error:
            await interaction.response.send_message(embed=error_embed(error), ephemeral=True)
            return

        view = ConnectFourView(interaction.user, oponente)
        embed = base_embed(
            f"{view._render()}\n\n🔴 {interaction.user.mention}  vs  🟡 {oponente.mention}\nTurno de: {interaction.user.mention}",
            COLOR, title="🔴🟡 4 en raya",
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="rps", description="Reta a alguien a piedra, papel o tijera (sin apuesta)")
    @app_commands.describe(oponente="A quién retas")
    async def rps(self, interaction: discord.Interaction, oponente: discord.Member):
        error = _validate_opponent(interaction, oponente)
        if error:
            await interaction.response.send_message(embed=error_embed(error), ephemeral=True)
            return

        view = RPSView(interaction.user, oponente)
        embed = base_embed(
            f"{interaction.user.mention} reta a {oponente.mention}.\n\nAmbos elijan en privado 👇",
            COLOR, title="✊ Piedra, papel o tijera",
        )
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(BoardGamesCog(bot))
