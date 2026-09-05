import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from game.session import GameSession, active_sessions, SAVES_DIR
from game.ui import Flip7LobbyView, Flip7GameView
from game.engine import Flip7Engine

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """Triggered when the bot is connected and ready."""
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")
    
    # Restore saved games on startup
    if os.path.exists(SAVES_DIR):
        for filename in os.listdir(SAVES_DIR):
            if filename.startswith("game_") and filename.endswith(".json"):
                file_path = os.path.join(SAVES_DIR, filename)
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)

                    channel_id = data["channel_id"]
                    host_id = data["host_id"]
                    
                    host_user = await bot.fetch_user(host_id)
                    
                    session = GameSession(channel_id, host_user, target_score=data["target_score"])
                    session.engine = Flip7Engine.from_dict(data["engine"])
                    
                    game_view = Flip7GameView(session)
                    session.current_view = game_view
                    
                    try:
                        channel = await bot.fetch_channel(channel_id)
                        if data.get("message_id"):
                            msg = await channel.fetch_message(data["message_id"])
                            session.message = msg
                            game_view.message = msg
                            
                            # Bind view persistent handlers with discord.py bot engine
                            bot.add_view(game_view, message_id=msg.id)
                            
                            # Re-build layout structure so interactive elements mount properly
                            game_view.build_game_layout()
                            await msg.edit(view=game_view)
                    except Exception as e:
                        print(f"Could not re-attach message for session in {channel_id}: {e}")

                    active_sessions[channel_id] = session
                    
                    # Auto-resume turn processing (handles bots or turn state restoration)
                    await game_view.start_turn_cycle()
                    print(f"✅ Restored active Flip 7 game in channel {channel_id}.")
                    
                except Exception as e:
                    print(f"❌ Failed to restore save file {filename}: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")


@bot.tree.command(name="flip7", description="Start a new multiplayer game of Flip 7 with friends!")
@app_commands.describe(target_score="Points needed to win the match (default 200, or 100 for a quick match)")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def start_flip7(interaction: discord.Interaction, target_score: int = 200):
    """Spawns a matchmaking lobby where friends can join, add bots, and start."""
    channel_id = interaction.channel_id

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

    await interaction.response.send_message(view=lobby)
    new_session.message = await interaction.original_response()
    lobby.message = new_session.message


@bot.tree.command(name="flip7_stop", description="Cancel the ongoing Flip 7 game or lobby in this channel.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def stop_flip7(interaction: discord.Interaction):
    """Stops the active game in the channel."""
    channel_id = interaction.channel_id
    session = active_sessions.get(channel_id)

    if not session or not session.is_active:
        await interaction.response.send_message("There is no active Flip 7 game in this channel to stop.", ephemeral=True)
        return

    is_host = session.host.id == interaction.user.id
    has_perm = interaction.user.guild_permissions.manage_messages if interaction.guild else True

    if not is_host and not has_perm:
        await interaction.response.send_message("Only the game host or a moderator can cancel the game.", ephemeral=True)
        return

    session.stop()
    if channel_id in active_sessions:
        del active_sessions[channel_id]

    await interaction.response.send_message(f"🛑 The active Flip 7 game was stopped by <@{interaction.user.id}>.")


@bot.tree.command(name="flip7_rules", description="Learn how to play Flip 7 (rules, cards, and scoring).")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
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
            "• `[⚡️ Flip Three]` Forces the target player to immediately flip the next 3 cards from the deck!\n"
            "• `[+2 to +10]` Flat point bonus added to your round score.\n"
            "• `[×2]` Doubles the sum of your number cards!"
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
        value="`Round Score = (Sum of Numbers × 2 if ×2) + Flat Modifiers + 15 (if Flip 7)`",
        inline=False
    )

    embed.set_footer(text="Start a game anytime with /flip7!")
    await interaction.response.send_message(embed=embed)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error.original, discord.NotFound):
        print("Interaction expired before response could be delivered (network timeout).")
        return

    if isinstance(error.original, (discord.HTTPException, OSError)):
        print(f"Network error during command execution: {error.original}")
        return

    print(f"Unhandled command error: {error}")


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN environment variable is missing from .env file.")

    bot.run(TOKEN)