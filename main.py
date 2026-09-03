import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from ui import Flip7LobbyView, GameSession

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Bot setup
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Channel-level game session tracking to avoid cross-channel interference
active_sessions: dict[int, GameSession] = {}  # channel_id -> GameSession


@bot.event
async def on_ready():
    """Triggered when the bot is connected and ready."""
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.tree.command(name="ping", description="Check bot latency.")
async def ping(interaction: discord.Interaction):
    """Simple latency verification."""
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! 🏓 Latency: `{latency_ms}ms`")


@bot.tree.command(name="flip7", description="Start a new multiplayer game of Flip 7 with friends!")
@app_commands.describe(target_score="Points needed to win the match (default 200, or 100 for a quick match)")
async def start_flip7(interaction: discord.Interaction, target_score: int = 200):
    """Spawns a matchmaking lobby where friends can join, add bots, and start."""
    channel_id = interaction.channel_id

    # Check if an active session is running in this channel
    session = active_sessions.get(channel_id)
    if session and session.is_active:
        await interaction.response.send_message(
            "⚠️ A game is already in progress or gathering players in this channel! "
            "Finish the current game or run `/flip7_stop` to cancel it.",
            ephemeral=True
        )
        return

    if target_score < 20 or target_score > 1000:
        await interaction.response.send_message("Target score must be between 20 and 1000 points.", ephemeral=True)
        return

    new_session = GameSession(channel_id, interaction.user, target_score=target_score)
    lobby = Flip7LobbyView(new_session)
    new_session.current_view = lobby
    active_sessions[channel_id] = new_session

    embed = lobby.create_lobby_embed()
    await interaction.response.send_message(embed=embed, view=lobby)
    new_session.message = await interaction.original_response()
    lobby.message = new_session.message


@bot.tree.command(name="flip7_stop", description="Cancel the ongoing Flip 7 game or lobby in this channel.")
async def stop_flip7(interaction: discord.Interaction):
    """Stops the active game in the channel."""
    channel_id = interaction.channel_id
    session = active_sessions.get(channel_id)

    if not session or not session.is_active:
        await interaction.response.send_message("There is no active Flip 7 game in this channel to stop.", ephemeral=True)
        return

    # Check permissions: Host or Manage Messages
    is_host = session.host.id == interaction.user.id
    has_perm = interaction.user.guild_permissions.manage_messages if interaction.guild else True

    if not is_host and not has_perm:
        await interaction.response.send_message("Only the game host or a moderator can cancel the game.", ephemeral=True)
        return

    session.stop()
    del active_sessions[channel_id]

    stop_embed = discord.Embed(
        title="🛑 Game Cancelled",
        description=f"The active Flip 7 game was stopped by <@{interaction.user.id}>.",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=stop_embed)


@bot.tree.command(name="flip7_rules", description="Learn how to play Flip 7 (rules, cards, and scoring).")
async def flip7_rules(interaction: discord.Interaction):
    """Displays comprehensive rules and card breakdown."""
    embed = discord.Embed(
        title="🃏 How to Play Flip 7",
        description=(
            "**Flip 7** is a fast-paced press-your-luck card game! "
            "Players take turns flipping cards to bank points without busting. "
            "First to reach the target score (**default 200 pts**) wins the match!\n"
        ),
        color=discord.Color.gold()
    )

    embed.add_field(
        name="🎯 Gameplay & Turns",
        value=(
            "On your turn, choose to **Hit** 🃏 or **Stay** 🛑:\n"
            "• **Hit:** Flip another card from the deck.\n"
            "• **Duplicate Number:** If you flip a number you already have in front of you, you **BUST** 💥! You get 0 points this round.\n"
            "• **Stay:** Lock in your points and bank your cards for this round."
        ),
        inline=False
    )

    embed.add_field(
        name="🌟 Special Actions & Cards",
        value=(
            "• `[🛡️ Second Chance]` Shields you from your next duplicate bust! Max 1 shield held at a time. Extra copies must be passed.\n"
            "• `[❄️ Freeze]` Forces a player (yourself or an opponent) to immediately stay and bank their current points.\n"
            "• `[⚡ Flip Three]` Forces the target player to immediately flip the next 3 cards from the deck!\n"
            "• `[➕ +2 to +10]` Flat point bonus added to your round score.\n"
            "• `[✖️ x2]` Doubles the sum of your number cards!"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 The Flip 7 Bonus (+15 pts)",
        value=(
            "If any player collects **7 unique number cards** (including `[0]`), "
            "they trigger **FLIP 7**! They get a **+15 bonus** and the round ends **immediately** for all players!"
        ),
        inline=False
    )

    embed.add_field(
        name="🧮 Scoring Formula",
        value="`Round Score = (Sum of Numbers × 2 if x2) + Flat Modifiers + 15 (if Flip 7)`",
        inline=False
    )

    embed.set_footer(text="Start a game anytime with /flip7!")
    await interaction.response.send_message(embed=embed)


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN environment variable is missing from .env file.")

    bot.run(TOKEN)