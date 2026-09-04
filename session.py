import asyncio
import functools
import json
import os
import discord
from discord.ui import LayoutView
from aiohttp.client_exceptions import ClientConnectorError
from typing import Optional, Dict
from engine import Flip7Engine

SAVES_DIR = "./game_saves"
os.makedirs(SAVES_DIR, exist_ok=True)

# Tracks active channel game sessions in memory
active_sessions: Dict[int, "GameSession"] = {}


def auto_retry(max_retries: int = 3, initial_delay: float = 0.5, backoff_factor: float = 2.0):
    """Decorator that retries an async function upon network or transient HTTP errors."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (ClientConnectorError, discord.GatewayNotFound, OSError) as e:
                    if attempt == max_retries:
                        print(f"[Network Retry Error] Max retries ({max_retries}) reached for {func.__name__}: {e}")
                        raise
                    print(f"[Network Drop] {func.__name__} failed (attempt {attempt}/{max_retries}). Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    delay *= backoff_factor
                except discord.HTTPException as e:
                    if e.status in (429, 500, 502, 503, 504) and attempt < max_retries:
                        retry_after = getattr(e, 'retry_after', delay)
                        print(f"[Discord API Error {e.status}] Retrying {func.__name__} in {retry_after:.1f}s...")
                        await asyncio.sleep(retry_after or delay)
                        delay *= backoff_factor
                    else:
                        raise
        return wrapper
    return decorator


async def safe_interaction_defer(interaction: discord.Interaction):
    """Defers an interaction safely, ignoring 404s if network delay caused token expiration."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.NotFound:
        pass


class GameSession:
    """Represents an active game session bound to a Discord channel."""
    def __init__(self, channel_id: int, host: discord.User, target_score: int = 200):
        self.channel_id = channel_id
        self.host = host
        self.target_score = target_score
        self.engine = Flip7Engine(target_score=target_score)
        self.engine.add_player(host.id, host.display_name, is_bot=False)
        self.current_view: Optional[LayoutView] = None
        self.message: Optional[discord.Message] = None
        self.is_active: bool = True

    def save_to_disk(self):
        """Saves current session state to a JSON file."""
        if not self.is_active:
            return
            
        file_path = os.path.join(SAVES_DIR, f"game_{self.channel_id}.json")
        data = {
            "channel_id": self.channel_id,
            "host_id": self.host.id,
            "host_name": self.host.display_name,
            "target_score": self.target_score,
            "message_id": self.message.id if self.message else None,
            "engine": self.engine.to_dict()
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    def delete_saved_state(self):
        """Deletes the JSON file when the game naturally ends or is cancelled."""
        file_path = os.path.join(SAVES_DIR, f"game_{self.channel_id}.json")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    def stop(self):
        self.is_active = False
        self.delete_saved_state()
        if self.current_view and not self.current_view.is_finished():
            self.current_view.stop()