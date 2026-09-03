import asyncio
import discord
from discord.ui import View, Button, Select
from typing import Optional, List, Dict
from game import Flip7Engine, Player

BOT_NAMES = ["Alex", "Chloe", "Sam", "Leo", "Maya", "Jordan"]


class GameSession:
    """Represents an active game session bound to a Discord channel."""
    def __init__(self, channel_id: int, host: discord.User, target_score: int = 200):
        self.channel_id = channel_id
        self.host = host
        self.target_score = target_score
        self.engine = Flip7Engine(target_score=target_score)
        self.engine.add_player(host.id, host.display_name, is_bot=False)
        self.current_view: Optional[View] = None
        self.message: Optional[discord.Message] = None
        self.is_active: bool = True

    def stop(self):
        self.is_active = False
        if self.current_view and not self.current_view.is_finished():
            self.current_view.stop()


class FreezeTargetSelect(Select):
    """Dropdown to choose target for Freeze action card."""
    def __init__(self, game_view: "Flip7GameView", actor: Player):
        self.game_view = game_view
        self.engine = game_view.engine
        self.actor = actor

        options = []
        for p in self.engine.players.values():
            if p.status == "playing":
                label = f"{p.name} (You)" if p.id == actor.id else p.name
                desc = f"Hand: {p.get_round_score()} pts | Total: {p.total_score} pts"
                options.append(discord.SelectOption(label=label, value=str(p.id), description=desc[:100]))

        super().__init__(
            placeholder="❄️ Choose a player to Freeze...",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="No valid targets", value="none")]
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Only the active player can choose the target.", ephemeral=True)
            return

        target_id = int(self.values[0])
        target_p, _ = self.engine.resolve_freeze(self.actor.id, target_id)
        
        self.game_view.remove_item(self)
        if target_id == self.actor.id:
            self.game_view.action_log = f"❄️ **{self.actor.name}** froze **themselves**!"
        else:
            self.game_view.action_log = f"❄️ **{self.actor.name}** froze **{target_p.name}**!"
        
        await self.game_view.after_action(interaction)


class FlipThreeTargetSelect(Select):
    """Dropdown to choose target for Flip Three action card."""
    def __init__(self, game_view: "Flip7GameView", actor: Player):
        self.game_view = game_view
        self.engine = game_view.engine
        self.actor = actor

        options = []
        for p in self.engine.players.values():
            if p.status == "playing":
                label = f"{p.name} (You)" if p.id == actor.id else p.name
                desc = f"Cards: {len(p.hand)} | Round pts: {p.get_round_score()}"
                options.append(discord.SelectOption(label=label, value=str(p.id), description=desc[:100]))

        super().__init__(
            placeholder="⚡ Choose who flips 3 cards...",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="No valid targets", value="none")]
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Only the active player can choose the target.", ephemeral=True)
            return

        target_id = int(self.values[0])
        target_p = self.engine.players[target_id]
        results = self.engine.resolve_flip_three(self.actor.id, target_id)

        cards_str = " ".join(c.format_card() for c, _ in results)
        self.game_view.remove_item(self)
        
        target_name = "themselves" if target_id == self.actor.id else f"**{target_p.name}**"
        if target_p.status == "busted":
            self.game_view.action_log = f"⚡ **{self.actor.name}** forced {target_name} to Flip 3: {cards_str} 💥 **BUSTED!**"
        elif target_p.has_flip7_bonus():
            self.game_view.action_log = f"⚡ **{self.actor.name}** forced {target_name} to Flip 3: {cards_str} 🌟 **FLIP 7!**"
        else:
            self.game_view.action_log = f"⚡ **{self.actor.name}** forced {target_name} to Flip 3: {cards_str}"

        await self.game_view.after_action(interaction)


class PassSecondChanceSelect(Select):
    """Dropdown to pass an extra Second Chance shield to another player."""
    def __init__(self, game_view: "Flip7GameView", actor: Player, target_ids: Optional[List[int]] = None):
        self.game_view = game_view
        self.engine = game_view.engine
        self.actor = actor

        if target_ids is None:
            target_ids = [p.id for p in self.engine.players.values() if p.id != actor.id and p.status == "playing" and not p.has_second_chance]

        options = []
        for tid in target_ids:
            p = self.engine.players.get(tid)
            if p:
                options.append(discord.SelectOption(label=p.name, value=str(p.id)))

        super().__init__(
            placeholder="🛡️ Pass excess Second Chance to...",
            min_values=1,
            max_values=1,
            options=options if options else [discord.SelectOption(label="No targets", value="none")]
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.actor.id:
            await interaction.response.send_message("Only the active player can pass the card.", ephemeral=True)
            return

        target_id = int(self.values[0])
        recipient = self.engine.resolve_pass_second_chance(self.actor.id, target_id)
        
        self.game_view.remove_item(self)
        self.game_view.action_log = f"❤️ **{self.actor.name}** passed a **Second Chance** shield to **{recipient.name}**!"
        
        await self.game_view.after_action(interaction)


class Flip7GameView(View):
    """Active game view with Hit, Stay, and action selectors."""
    def __init__(self, session: GameSession):
        super().__init__(timeout=None)
        self.session = session
        self.engine = session.engine
        self.message: Optional[discord.Message] = None
        self.action_log: str = "🎮 Round started! Click **Hit** to draw your first card."
        self.turn_timer_task: Optional[asyncio.Task] = None
        self.update_buttons()

    def update_buttons(self):
        is_active = not self.engine.is_round_over()
        curr = self.engine.get_current_player()
        
        cannot_act = (
            not is_active 
            or curr is None 
            or curr.is_bot 
            or curr.pending_action is not None
        )
        self.hit_button.disabled = cannot_act
        
        # Rule Check: Player cannot Stay on initial turn if holding 0 cards in hand
        cannot_stay = cannot_act or (curr is not None and len(curr.hand) == 0)
        self.stay_button.disabled = cannot_stay

    def _clear_selects(self):
        for item in list(self.children):
            if isinstance(item, Select):
                self.remove_item(item)

    def attach_pending_select_if_any(self, player: Player):
        if player.pending_action == "freeze":
            self.add_item(FreezeTargetSelect(self, player))
        elif player.pending_action == "flip_three":
            self.add_item(FlipThreeTargetSelect(self, player))
        elif player.pending_action == "pass_second_chance":
            self.add_item(PassSecondChanceSelect(self, player))

    def create_game_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🃏 Flip 7 — Round {self.engine.round_number}",
            color=discord.Color.blue()
        )

        curr = self.engine.get_current_player()
        if not self.engine.is_round_over() and curr:
            turn_mention = f"🤖 **{curr.name}**" if curr.is_bot else f"<@{curr.id}>"
            embed.description = f"**Current Turn:** {turn_mention}\n\n{self.action_log}"
        else:
            embed.description = f"**Round Ended!**\n\n{self.action_log}"

        for p in self.engine.players.values():
            status_badge = {
                "playing": "🎮 Playing",
                "stayed": "🛑 Stayed",
                "busted": "💥 Busted",
                "frozen": "❄️ Frozen"
            }.get(p.status, p.status)

            cards_str = " ".join(c.format_card() for c in p.hand) if p.hand else "*No cards*"
            shield_badge = " ❤️" if p.has_second_chance else ""
            
            embed.add_field(
                name=f"{p.name}{shield_badge} — {status_badge} (Banked: {p.total_score} pts)",
                value=f"**Round Score:** `{p.get_round_score()} pts`\n**Hand:** {cards_str}",
                inline=False
            )

        embed.set_footer(text=f"Deck: {len(self.engine.deck)} cards | Discard: {len(self.engine.discard_pile)} | Goal: {self.engine.target_score} pts")
        return embed

    async def start_turn_cycle(self):
        self._cancel_timer()
        if self.engine.is_round_over():
            await self.finish_round()
            return

        curr = self.engine.get_current_player()
        if not curr:
            return

        # Check if current human player has remaining actions in their queue
        if not curr.is_bot and curr.pending_action:
            self._clear_selects()
            self.attach_pending_select_if_any(curr)

        self.update_buttons()
        if self.message:
            await self.message.edit(embed=self.create_game_embed(), view=self)

        if curr.is_bot:
            asyncio.create_task(self._process_bot_turn(curr))

    def _cancel_timer(self):
        if self.turn_timer_task and not self.turn_timer_task.done():
            self.turn_timer_task.cancel()
            self.turn_timer_task = None

    async def _process_bot_turn(self, bot_player: Player):
        await asyncio.sleep(1.5)
        if self.engine.is_round_over():
            await self.finish_round()
            return

        # Drain pending actions for bot loop
        while bot_player.pending_action and bot_player.status == "playing":
            await self._resolve_bot_pending_action(bot_player)

        if self.engine.is_round_over():
            await self.finish_round()
            return

        decision = self.engine.get_bot_decision(bot_player)
        if decision == "hit":
            card, result, extra = self.engine.hit(bot_player.id)
            if result == "action_freeze":
                target_id = self.engine.choose_bot_freeze_target(bot_player)
                target_p, _ = self.engine.resolve_freeze(bot_player.id, target_id)
                self.action_log = f"❄️ **{bot_player.name}** drew Freeze and froze **{target_p.name}**!"
            elif result == "action_flip_three":
                target_id = self.engine.choose_bot_flip_three_target(bot_player)
                target_p = self.engine.players[target_id]
                results = self.engine.resolve_flip_three(bot_player.id, target_id)
                cards_str = " ".join(c.format_card() for c, _ in results)
                self.action_log = f"⚡ **{bot_player.name}** forced **{target_p.name}** to Flip 3: {cards_str}"
                
                # If target is a bot with queued pending actions, resolve them now
                while target_p.is_bot and target_p.pending_action and target_p.status == "playing":
                    await self._resolve_bot_pending_action(target_p)
            elif result == "action_second_chance_pass":
                recipients = extra.get("targets", []) if extra else []
                if recipients:
                    rec_p = self.engine.resolve_pass_second_chance(bot_player.id, recipients[0])
                    self.action_log = f"❤️ **{bot_player.name}** passed a **Second Chance** shield to **{rec_p.name}**!"
            elif result == "action_second_chance_kept":
                self.action_log = f"❤️ **{bot_player.name}** drew a **Second Chance** shield!"
            elif result == "saved_by_second_chance":
                self.action_log = f"❤️ **{bot_player.name}** drew duplicate {card.format_card()}, saved by **Second Chance**!"
            elif result == "busted":
                self.action_log = f"💥 **{bot_player.name}** drew {card.format_card()} and **BUSTED**!"
            elif result == "flip7":
                self.action_log = f"🌟 **{bot_player.name}** drew {card.format_card()} and hit **FLIP 7**!"
            else:
                self.action_log = f"🃏 **{bot_player.name}** drew {card.format_card()}."
        else:
            self.engine.stay(bot_player.id)
            self.action_log = f"🛑 **{bot_player.name}** chose to Stay."

        await self.start_turn_cycle()

    async def _resolve_bot_pending_action(self, bot_player: Player):
        if bot_player.pending_action == "freeze":
            target_id = self.engine.choose_bot_freeze_target(bot_player)
            target_p, _ = self.engine.resolve_freeze(bot_player.id, target_id)
            self.action_log += f"\n❄️ **{bot_player.name}** resolved Freeze on **{target_p.name}**!"
        elif bot_player.pending_action == "flip_three":
            target_id = self.engine.choose_bot_flip_three_target(bot_player)
            target_p = self.engine.players[target_id]
            results = self.engine.resolve_flip_three(bot_player.id, target_id)
            cards_str = " ".join(c.format_card() for c, _ in results)
            self.action_log += f"\n⚡ **{bot_player.name}** resolved Flip 3 on **{target_p.name}**: {cards_str}"
        elif bot_player.pending_action == "pass_second_chance":
            eligible = [p for p in self.engine.players.values() if p.id != bot_player.id and p.status == "playing" and not p.has_second_chance]
            if eligible:
                recipient = self.engine.resolve_pass_second_chance(bot_player.id, eligible[0].id)
                self.action_log += f"\n❤️ **{bot_player.name}** passed a Second Chance shield to **{recipient.name}**!"
            else:
                bot_player.pending_action = None

    async def after_action(self, interaction: discord.Interaction):
        self._clear_selects()

        # Check if the active human player has queued actions left to resolve
        curr = self.engine.get_current_player()
        if curr and not curr.is_bot and curr.pending_action:
            self.attach_pending_select_if_any(curr)

        self.update_buttons()
        embed = self.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=self)
        await self.start_turn_cycle()

    @discord.ui.button(label="Hit 🃏", style=discord.ButtonStyle.success, custom_id="btn_hit")
    async def hit_button(self, interaction: discord.Interaction, button: Button):
        curr = self.engine.get_current_player()
        if not curr or interaction.user.id != curr.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if curr.pending_action:
            await interaction.response.send_message("You must resolve your action choice first!", ephemeral=True)
            return

        self._cancel_timer()

        # 1. Process engine state
        card, result, extra = self.engine.hit(interaction.user.id)

        # 2. Update action log and attach dropdowns if action card was drawn
        if result == "action_freeze":
            self.add_item(FreezeTargetSelect(self, curr))
            self.action_log = f"❄️ **{interaction.user.name}** drew Freeze! Pick a player to freeze:"
        elif result == "action_flip_three":
            self.add_item(FlipThreeTargetSelect(self, curr))
            self.action_log = f"⚡ **{interaction.user.name}** drew Flip Three! Pick a player to flip 3 cards:"
        elif result == "action_second_chance_pass":
            targets = extra.get("targets", []) if extra else []
            self.add_item(PassSecondChanceSelect(self, curr, targets))
            self.action_log = f"❤️ **{interaction.user.name}** already has a shield! Choose a player to give it to:"
        elif result == "action_second_chance_kept":
            self.action_log = f"❤️ **{interaction.user.name}** drew a **Second Chance** shield!"
        elif result == "saved_by_second_chance":
            self.action_log = f"❤️ **{interaction.user.name}** drew duplicate {card.format_card()}, saved by **Second Chance**!"
        elif result == "busted":
            self.action_log = f"💥 **{interaction.user.name}** drew {card.format_card()} and **BUSTED**!"
        elif result == "flip7":
            self.action_log = f"🌟 **{interaction.user.name}** drew {card.format_card()} and hit **FLIP 7**!"
        else:
            self.action_log = f"🃏 **{interaction.user.name}** drew {card.format_card()}."

        # 3. Update buttons and edit message ONCE
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_game_embed(), view=self)

        # 4. If no pending action required, start the next turn cycle asynchronously
        if not curr.pending_action:
            asyncio.create_task(self.start_turn_cycle())

    @discord.ui.button(label="Stay 🛑", style=discord.ButtonStyle.secondary, custom_id="btn_stay")
    async def stay_button(self, interaction: discord.Interaction, button: Button):
        curr = self.engine.get_current_player()
        if not curr or interaction.user.id != curr.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        self._cancel_timer()
        self.engine.stay(interaction.user.id)
        self.action_log = f"🛑 **{interaction.user.name}** locked in their hand."
        
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_game_embed(), view=self)
        await self.start_turn_cycle()

    async def finish_round(self):
        self._cancel_timer()
        self._clear_selects()
        round_scores = self.engine.tally_round_scores()
        round_view = Flip7RoundEndView(self.session)
        self.session.current_view = round_view
        embed = round_view.create_summary_embed(round_scores)
        
        if self.message:
            await self.message.edit(embed=embed, view=round_view)
            round_view.message = self.message


class Flip7RoundEndView(View):
    """Displays round recap, leaderboards, and next round / play again buttons."""
    def __init__(self, session: GameSession):
        super().__init__(timeout=180)
        self.session = session
        self.engine = session.engine
        self.message: Optional[discord.Message] = None

        if self.engine.is_game_over():
            self.remove_item(self.next_round_button)
        else:
            self.remove_item(self.play_again_button)
            self.remove_item(self.cancel_button)

    def create_summary_embed(self, round_scores: Dict[int, int]) -> discord.Embed:
        is_match_over = self.engine.is_game_over()
        winner = self.engine.get_winner()

        if is_match_over and winner:
            embed = discord.Embed(
                title=f"🏆 Match Finished! {winner.name} Wins!",
                description=f"🎉 **{winner.name}** reached the goal with **{winner.total_score} points**!",
                color=discord.Color.gold()
            )
        else:
            embed = discord.Embed(
                title=f"🏁 Round {self.engine.round_number} Finished!",
                color=discord.Color.green()
            )

        if self.engine.flip7_achieved_by:
            embed.description = (embed.description or "") + f"\n🌟 **{self.engine.flip7_achieved_by.name} achieved FLIP 7! (+15 Bonus)**"

        round_lines = []
        for p in self.engine.players.values():
            pts = round_scores.get(p.id, 0)
            if pts == 0:
                round_lines.append(f"• **{p.name}**: 💥 0 pts")
            else:
                round_lines.append(f"• **{p.name}**: `+{pts} pts`")

        embed.add_field(name="Round Results", value="\n".join(round_lines), inline=False)

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
        board_lines = []
        for i, p in enumerate(self.engine.get_leaderboard()):
            medal = medals[i] if i < len(medals) else "•"
            board_lines.append(f"{medal} **{p.name}**: `{p.total_score} pts` / {self.engine.target_score} pts")

        embed.add_field(name="Current Standings", value="\n".join(board_lines), inline=False)
        return embed

    @discord.ui.button(label="Next Round ⏭️", style=discord.ButtonStyle.primary, custom_id="btn_next_round")
    async def next_round_button(self, interaction: discord.Interaction, button: Button):
        if self.engine.is_game_over():
            await interaction.response.send_message("The game is already finished! Click 'Play Again' to restart.", ephemeral=True)
            return

        self.engine.start_round()
        game_view = Flip7GameView(self.session)
        self.session.current_view = game_view
        game_view.message = self.message

        game_view.action_log = "🎮 Round started! Click **Hit** to draw your first card."

        await interaction.response.edit_message(embed=game_view.create_game_embed(), view=game_view)
        await game_view.start_turn_cycle()

    @discord.ui.button(label="Play Again 🔄", style=discord.ButtonStyle.success, custom_id="btn_play_again")
    async def play_again_button(self, interaction: discord.Interaction, button: Button):
        for p in self.engine.players.values():
            p.total_score = 0
            p.reset_for_new_round()
        self.engine.round_number = 0
        self.engine.deck = []
        self.engine.discard_pile = []

        self.engine.start_round()
        game_view = Flip7GameView(self.session)
        self.session.current_view = game_view
        game_view.message = self.message

        game_view.action_log = "🔄 New match started! Click **Hit** to draw your first card."

        await interaction.response.edit_message(embed=game_view.create_game_embed(), view=game_view)
        await game_view.start_turn_cycle()

    @discord.ui.button(label="Cancel ❌", style=discord.ButtonStyle.danger, custom_id="btn_end_game_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.session.host.id:
            await interaction.response.send_message("Only the host can close the finished game session.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        winner = self.engine.get_winner()
        winner_text = f" **{winner.name}** won with **{winner.total_score} pts**." if winner else ""
        
        embed = discord.Embed(
            title="🏁 Game Session Closed",
            description=f"The match has concluded.{winner_text} Thanks for playing!",
            color=discord.Color.dark_grey()
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.stop()


class Flip7LobbyView(View):
    """Matchmaking lobby for players and bot opponents to gather before the game starts."""
    def __init__(self, session: GameSession):
        super().__init__(timeout=300)
        self.session = session
        self.engine = session.engine
        self.host = session.host
        self.target_score = session.target_score
        self.message: Optional[discord.Message] = None
        self.bot_index = 0

    def create_lobby_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🃏 Flip 7 — Game Lobby",
            description=(
                f"**Host:** <@{self.host.id}>\n"
                f"**Target Score:** `{self.target_score} pts`\n\n"
                "Gather your friends! Click **Join** below to enter the table.\n"
                "Need more players? Click **Add Bot** to fill seats.\n"
                "When ready (2–8 players), the host can click **Start Game**!"
            ),
            color=discord.Color.purple()
        )

        player_lines = []
        for i, p in enumerate(self.engine.players.values(), start=1):
            if p.id == self.host.id:
                player_lines.append(f"`{i}.` 👑 **{p.name}** *(Host)*")
            elif p.is_bot:
                player_lines.append(f"`{i}.` 🤖 **{p.name}** *(Bot)*")
            else:
                player_lines.append(f"`{i}.` 🎮 **{p.name}**")

        embed.add_field(
            name=f"Players ({len(self.engine.players)}/8)",
            value="\n".join(player_lines) if player_lines else "*Empty*",
            inline=False
        )

        embed.set_footer(text="Flip 7 is a press-your-luck card game. First to reach the target score wins!")
        return embed

    @discord.ui.button(label="Join 🎮", style=discord.ButtonStyle.success, custom_id="btn_lobby_join")
    async def join_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id in self.engine.players:
            await interaction.response.send_message("You are already in the lobby!", ephemeral=True)
            return

        if len(self.engine.players) >= 8:
            await interaction.response.send_message("The lobby is full (max 8 players).", ephemeral=True)
            return

        self.engine.add_player(interaction.user.id, interaction.user.display_name, is_bot=False)
        await interaction.response.edit_message(embed=self.create_lobby_embed(), view=self)

    @discord.ui.button(label="Leave 🚪", style=discord.ButtonStyle.secondary, custom_id="btn_lobby_leave")
    async def leave_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id not in self.engine.players:
            await interaction.response.send_message("You are not in the lobby.", ephemeral=True)
            return

        if interaction.user.id == self.host.id:
            await interaction.response.send_message("Host cannot leave. Click **Cancel** to disband the lobby.", ephemeral=True)
            return

        self.engine.remove_player(interaction.user.id)
        await interaction.response.edit_message(embed=self.create_lobby_embed(), view=self)

    @discord.ui.button(label="Add Bot 🤖", style=discord.ButtonStyle.primary, custom_id="btn_lobby_add_bot")
    async def add_bot_button(self, interaction: discord.Interaction, button: Button):
        if len(self.engine.players) >= 8:
            await interaction.response.send_message("The lobby is full (max 8 players).", ephemeral=True)
            return

        bot_name = BOT_NAMES[self.bot_index % len(BOT_NAMES)]
        self.bot_index += 1
        bot_id = 900000 + self.bot_index

        self.engine.add_player(bot_id, f"Bot {bot_name}", is_bot=True)
        await interaction.response.edit_message(embed=self.create_lobby_embed(), view=self)

    @discord.ui.button(label="Remove Bot 🚫", style=discord.ButtonStyle.secondary, custom_id="btn_lobby_remove_bot")
    async def remove_bot_button(self, interaction: discord.Interaction, button: Button):
        bot_keys = [uid for uid, p in self.engine.players.items() if p.is_bot]
        if not bot_keys:
            await interaction.response.send_message("There are no bots in the lobby to remove.", ephemeral=True)
            return

        self.engine.remove_player(bot_keys[-1])
        await interaction.response.edit_message(embed=self.create_lobby_embed(), view=self)

    @discord.ui.button(label="Start Game ▶️", style=discord.ButtonStyle.success, custom_id="btn_lobby_start")
    async def start_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("Only the host can start the game.", ephemeral=True)
            return

        if len(self.engine.players) < 2:
            await interaction.response.send_message("At least 2 players (friends or bots) are required to start!", ephemeral=True)
            return

        self.engine.start_round()
        game_view = Flip7GameView(self.session)
        self.session.current_view = game_view
        game_view.message = self.message

        game_view.action_log = "🎮 Game started! Click **Hit** to draw your first card."

        await interaction.response.edit_message(embed=game_view.create_game_embed(), view=game_view)
        await game_view.start_turn_cycle()

    @discord.ui.button(label="Cancel ❌", style=discord.ButtonStyle.danger, custom_id="btn_lobby_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.session.host.id:
            await interaction.response.send_message("Only the host can cancel the game.", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="🚫 Lobby Cancelled",
            description=f"The lobby was cancelled by <@{self.host.id}>.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.session.stop()