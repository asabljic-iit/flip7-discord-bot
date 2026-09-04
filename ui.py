import asyncio
import discord
from discord.ui import LayoutView, Container, TextDisplay, Separator, Button, Select, ActionRow
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
        self.current_view: Optional[LayoutView] = None
        self.message: Optional[discord.Message] = None
        self.is_active: bool = True

    def stop(self):
        self.is_active = False
        if self.current_view and not self.current_view.is_finished():
            self.current_view.stop()


# --- ACTION CARD SELECT DROPDOWNS ---

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
            placeholder="⚡️ Choose who flips 3 cards...",
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
            self.game_view.action_log = f"⚡️ **{self.actor.name}** forced {target_name} to Flip 3: {cards_str} 💥 **BUSTED!**"
        elif target_p.has_flip7_bonus():
            self.game_view.action_log = f"⚡️ **{self.actor.name}** forced {target_name} to Flip 3: {cards_str} 🌟 **FLIP 7!**"
        else:
            self.game_view.action_log = f"⚡️ **{self.actor.name}** forced {target_name} to Flip 3: {cards_str}"

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



class Flip7GameView(LayoutView):
    """Active game view using LayoutView Containers and TextDisplays."""

    def __init__(self, session: GameSession):
        super().__init__(timeout=None)
        self.session = session
        self.engine = session.engine
        self.message: Optional[discord.Message] = None
        self.action_log: str = "🎮 Round started! Click **Hit** to draw your first card."
        self.turn_timer_task: Optional[asyncio.Task] = None
        self.container = Container()
        self.add_item(self.container)

        # Instantiate game controls
        self.hit_btn = Button(label="Hit 🃏", style=discord.ButtonStyle.success, custom_id="btn_hit")
        self.stay_btn = Button(label="Stay 🛑", style=discord.ButtonStyle.secondary, custom_id="btn_stay")

        self.hit_btn.callback = self.hit_button_callback
        self.stay_btn.callback = self.stay_button_callback

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
        self.hit_btn.disabled = cannot_act
        
        cannot_stay = cannot_act or (curr is not None and len(curr.hand) == 0)
        self.stay_btn.disabled = cannot_stay

    def _clear_selects(self):
        for item in list(self.container.children):
            if isinstance(item, ActionRow):
                if any(isinstance(child, Select) for child in item.children):
                    self.container.children.remove(item)

    def attach_pending_select_if_any(self, player: Player):
        select_item = None
        if player.pending_action == "freeze":
            select_item = FreezeTargetSelect(self, player)
        elif player.pending_action == "flip_three":
            select_item = FlipThreeTargetSelect(self, player)
        elif player.pending_action == "pass_second_chance":
            select_item = PassSecondChanceSelect(self, player)

        if select_item:
            self.container.add_item(ActionRow(select_item))

    def build_game_layout(self):
        self.container.clear_items()

        curr = self.engine.get_current_player()
        if not self.engine.is_round_over() and curr:
            turn_mention = f"🤖 **{curr.name}**" if curr.is_bot else f"<@{curr.id}>"
            header_text = f"# 🃏 Flip 7 — Round {self.engine.round_number}\n**Current Turn:** {turn_mention}\n> {self.action_log}"
        else:
            header_text = f"# 🃏 Flip 7 — Round {self.engine.round_number}\n**Round Ended!**\n> {self.action_log}"

        self.container.add_item(TextDisplay(header_text))
        self.container.add_item(Separator())

        for p in self.engine.players.values():
            status_badge = {
                "playing": "🎮 Playing",
                "stayed": "🛑 Stayed",
                "busted": "💥 Busted",
                "frozen": "❄️ Frozen"
            }.get(p.status, p.status)

            shield_badge = " ❤️" if p.has_second_chance else ""

            # Separate hand into number cards and modifier/action cards
            numbers = [c for c in p.hand if c.is_number]
            others = [c for c in p.hand if not c.is_number]

            numbers_str = " ".join(c.format_card() for c in numbers) if numbers else " "
            others_str = " ".join(c.format_card() for c in others) if others else " "

            player_text = (
                f"👤 **{p.name}{shield_badge}  —  {status_badge}**\n"
                f"**Banked Total:** `{p.total_score} pts`  |  **Round Score:** `{p.get_round_score()} pts`\n"
                f"# **Hand:** {numbers_str}\n"
                f"**{others_str}**"
            )
            self.container.add_item(TextDisplay(player_text))
            self.container.add_item(Separator())

        footer_text = f"-# **Deck: {len(self.engine.deck)} cards | Discard: {len(self.engine.discard_pile)} cards | Goal: {self.engine.target_score} pts**"
        self.container.add_item(TextDisplay(footer_text))

        # Re-attach action row controls
        self.container.add_item(ActionRow(self.hit_btn, self.stay_btn))

        # Attach pending action dropdowns inside container if required
        if curr and not curr.is_bot and curr.pending_action:
            self.attach_pending_select_if_any(curr)

    async def start_turn_cycle(self):
        self._cancel_timer()
        if self.engine.is_round_over():
            await self.finish_round()
            return

        curr = self.engine.get_current_player()
        if not curr:
            return

        self.update_buttons()
        self.build_game_layout()

        if self.message:
            await self.message.edit(view=self)

        # If it's a bot's turn, launch a single task loop to process all consecutive bot turns
        if curr.is_bot:
            asyncio.create_task(self._process_bot_turn())

    def _cancel_timer(self):
        if self.turn_timer_task and not self.turn_timer_task.done():
            self.turn_timer_task.cancel()
            self.turn_timer_task = None

    async def _process_bot_turn(self):
        """Iterative loop that processes active bot turns sequentially without recursive tasks."""
        while not self.engine.is_round_over():
            curr = self.engine.get_current_player()
            if not curr or not curr.is_bot or curr.status != "playing":
                break

            await asyncio.sleep(1.2)

            # Resolve any pending actions for this bot
            while curr.pending_action and curr.status == "playing":
                await self._resolve_bot_pending_action(curr)

            if self.engine.is_round_over() or curr.status != "playing":
                break

            # Make hit / stay decision
            decision = self.engine.get_bot_decision(curr)
            if decision == "hit":
                card, result, extra = self.engine.hit(curr.id)
                if result == "action_freeze":
                    target_id = self.engine.choose_bot_freeze_target(curr)
                    target_p, _ = self.engine.resolve_freeze(curr.id, target_id)
                    self.action_log = f"❄️ **{curr.name}** drew Freeze and froze **{target_p.name}**!"
                elif result == "action_flip_three":
                    target_id = self.engine.choose_bot_flip_three_target(curr)
                    target_p = self.engine.players[target_id]
                    results = self.engine.resolve_flip_three(curr.id, target_id)
                    cards_str = " ".join(c.format_card() for c, _ in results)
                    self.action_log = f"⚡️ **{curr.name}** forced **{target_p.name}** to Flip 3: {cards_str}"
                    
                    # If target is a bot with pending actions from Flip 3, resolve them immediately
                    while target_p.is_bot and target_p.pending_action and target_p.status == "playing":
                        await self._resolve_bot_pending_action(target_p)
                elif result == "action_second_chance_pass":
                    recipients = extra.get("targets", []) if extra else []
                    if recipients:
                        rec_p = self.engine.resolve_pass_second_chance(curr.id, recipients[0])
                        self.action_log = f"❤️ **{curr.name}** passed a **Second Chance** shield to **{rec_p.name}**!"
                elif result == "action_second_chance_kept":
                    self.action_log = f"❤️ **{curr.name}** drew a **Second Chance** shield!"
                elif result == "saved_by_second_chance":
                    self.action_log = f"❤️ **{curr.name}** drew duplicate {card.format_card()}, saved by **Second Chance**!"
                elif result == "busted":
                    self.action_log = f"💥 **{curr.name}** drew {card.format_card()} and **BUSTED**!"
                elif result == "flip7":
                    self.action_log = f"🌟 **{curr.name}** drew {card.format_card()} and hit **FLIP 7**!"
                else:
                    self.action_log = f"🃏 **{curr.name}** drew {card.format_card()}."
            else:
                self.engine.stay(curr.id)
                self.action_log = f"🛑 **{curr.name}** chose to Stay."

            # Update layout after each bot action
            self.update_buttons()
            self.build_game_layout()
            if self.message:
                await self.message.edit(view=self)

        # Check if the round ended or hand off control to human player
        if self.engine.is_round_over():
            await self.finish_round()
        else:
            self.update_buttons()
            self.build_game_layout()
            if self.message:
                await self.message.edit(view=self)

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
            self.action_log += f"\n⚡️ **{bot_player.name}** resolved Flip 3 on **{target_p.name}**: {cards_str}"
        elif bot_player.pending_action == "pass_second_chance":
            eligible = [p for p in self.engine.players.values() if p.id != bot_player.id and p.status == "playing" and not p.has_second_chance]
            if eligible:
                recipient = self.engine.resolve_pass_second_chance(bot_player.id, eligible[0].id)
                self.action_log += f"\n❤️ **{bot_player.name}** passed a Second Chance shield to **{recipient.name}**!"
            else:
                bot_player.pending_action = None

    async def after_action(self, interaction: discord.Interaction):
        self._clear_selects()
        self.update_buttons()
        self.build_game_layout()
        await interaction.response.edit_message(view=self)
        await self.start_turn_cycle()

    async def hit_button_callback(self, interaction: discord.Interaction):
        curr = self.engine.get_current_player()
        if not curr or interaction.user.id != curr.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        if curr.pending_action:
            await interaction.response.send_message("You must resolve your action choice first!", ephemeral=True)
            return

        self._cancel_timer()

        card, result, extra = self.engine.hit(interaction.user.id)

        if result == "action_freeze":
            self.action_log = f"❄️ **{interaction.user.name}** drew Freeze! Pick a player to freeze:"
        elif result == "action_flip_three":
            self.action_log = f"⚡️ **{interaction.user.name}** drew Flip Three! Pick a player to flip 3 cards:"
        elif result == "action_second_chance_pass":
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

        self.update_buttons()
        self.build_game_layout()

        # If turn ends or advances, start_turn_cycle will edit the view
        if curr.pending_action:
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()
            await self.start_turn_cycle()

    async def stay_button_callback(self, interaction: discord.Interaction):
        curr = self.engine.get_current_player()
        if not curr or interaction.user.id != curr.id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        self._cancel_timer()
        self.engine.stay(interaction.user.id)
        self.action_log = f"🛑 **{interaction.user.name}** locked in their hand."
        
        self.update_buttons()
        self.build_game_layout()
        await interaction.response.edit_message(view=self)
        await self.start_turn_cycle()

    async def finish_round(self):
        """Called when a round ends. Posts a recap with Next Round controls."""
        self._cancel_timer()
        self._clear_selects()

        if self.message:
            try:
                self.build_game_layout()
                await self.message.edit(view=self)
            except Exception:
                pass

        round_scores = self.engine.tally_round_scores()
        round_view = Flip7RoundEndView(self.session, round_scores)
        self.session.current_view = round_view

        channel = self.message.channel if self.message else None
        if channel:
            try:
                new_msg = await channel.send(view=round_view)
                round_view.message = new_msg
                self.session.message = new_msg
            except discord.Forbidden:
                # Fallback if channel.send fails due to missing permissions:
                # Display the end-of-round recap on the existing view directly
                round_view.build_summary_layout()
                if self.message:
                    await self.message.edit(view=round_view)


class Flip7RoundEndView(LayoutView):
    """Displays round recap and standings using LayoutView Containers."""

    def __init__(self, session: GameSession, round_scores: Dict[int, int]):
        super().__init__(timeout=180)
        self.session = session
        self.engine = session.engine
        self.round_scores = round_scores
        self.message: Optional[discord.Message] = None
        self.container = Container()
        self.add_item(self.container)

        self.btn_next = Button(label="Next Round ⏭️", style=discord.ButtonStyle.primary, custom_id="btn_next_round")
        self.btn_play_again = Button(label="Play Again 🔄", style=discord.ButtonStyle.success, custom_id="btn_play_again")
        self.btn_cancel = Button(label="Cancel ❌", style=discord.ButtonStyle.danger, custom_id="btn_end_game_cancel")

        self.btn_next.callback = self.next_round_button_callback
        self.btn_play_again.callback = self.play_again_button_callback
        self.btn_cancel.callback = self.cancel_button_callback

        self.build_summary_layout()

    def build_summary_layout(self):
        self.container.clear_items()
        is_match_over = self.engine.is_game_over()
        winner = self.engine.get_winner()

        if is_match_over and winner:
            header_text = f"# 🏆 Match Finished! {winner.name} Wins!\n🎉 **{winner.name}** reached the goal with **{winner.total_score} points**!"
        else:
            header_text = f"# 🏁 Round {self.engine.round_number} Finished!\nClick **Next Round ⏭️** below when ready to continue!"

        if self.engine.flip7_achieved_by:
            header_text += f"\n\n🌟 **{self.engine.flip7_achieved_by.name} achieved FLIP 7! (+15 Bonus)**"

        self.container.add_item(TextDisplay(header_text))
        self.container.add_item(Separator())

        round_lines = []
        for p in self.engine.players.values():
            pts = self.round_scores.get(p.id, 0)
            if pts == 0:
                round_lines.append(f"💥 **{p.name}**: `0 pts`")
            else:
                round_lines.append(f"✨ **{p.name}**: `+{pts} pts`")

        self.container.add_item(TextDisplay(f"## 📊 Round Results\n" + "\n".join(round_lines)))
        self.container.add_item(Separator())

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
        board_lines = []
        for i, p in enumerate(self.engine.get_leaderboard()):
            medal = medals[i] if i < len(medals) else "•"
            board_lines.append(f"{medal} **{p.name}**: `{p.total_score} pts` / {self.engine.target_score} pts")

        self.container.add_item(TextDisplay(f"## 🏆 Current Standings\n" + "\n".join(board_lines)))

        if not is_match_over:
            self.container.add_item(ActionRow(self.btn_next))
        else:
            self.container.add_item(ActionRow(self.btn_play_again, self.btn_cancel))

    async def next_round_button_callback(self, interaction: discord.Interaction):
        if self.engine.is_game_over():
            await interaction.response.send_message("The game is already finished! Click 'Play Again' to restart.", ephemeral=True)
            return

        self.engine.start_round()
        game_view = Flip7GameView(self.session)
        self.session.current_view = game_view
        game_view.action_log = f"🎮 Round {self.engine.round_number} started! Click **Hit** to draw your first card."

        game_view.build_game_layout()
        await interaction.response.edit_message(view=game_view)
        
        game_view.message = interaction.message
        self.session.message = interaction.message

        await game_view.start_turn_cycle()

    async def play_again_button_callback(self, interaction: discord.Interaction):
        for p in self.engine.players.values():
            p.total_score = 0
            p.reset_for_new_round()
        self.engine.round_number = 0
        self.engine.deck = []
        self.engine.discard_pile = []

        self.engine.start_round()
        game_view = Flip7GameView(self.session)
        self.session.current_view = game_view
        game_view.action_log = "🔄 New match started! Click **Hit** to draw your first card."

        game_view.build_game_layout()
        await interaction.response.edit_message(view=game_view)

        game_view.message = interaction.message
        self.session.message = interaction.message

        await game_view.start_turn_cycle()

    async def cancel_button_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.host.id:
            await interaction.response.send_message("Only the host can close the finished game session.", ephemeral=True)
            return
        
        await interaction.response.send_message("🏁 The match has concluded. Thanks for playing!")
        self.session.stop()

# --- LAYOUTVIEWS USING COMPONENTS V2 ---

class Flip7LobbyView(LayoutView):
    """Matchmaking lobby for players and bot opponents using LayoutView."""

    def __init__(self, session: GameSession):
        super().__init__(timeout=300)
        self.session = session
        self.engine = session.engine
        self.host = session.host
        self.target_score = session.target_score
        self.message: Optional[discord.Message] = None
        self.bot_index = 0
        self.container = Container()
        self.add_item(self.container)

        # Instantiate buttons explicitly
        self.btn_join = Button(label="Join 🎮", style=discord.ButtonStyle.success, custom_id="btn_lobby_join")
        self.btn_leave = Button(label="Leave 🚪", style=discord.ButtonStyle.secondary, custom_id="btn_lobby_leave")
        self.btn_add_bot = Button(label="Add Bot 🤖", style=discord.ButtonStyle.primary, custom_id="btn_lobby_add_bot")
        self.btn_rem_bot = Button(label="Remove Bot 🚫", style=discord.ButtonStyle.secondary, custom_id="btn_lobby_remove_bot")
        self.btn_start = Button(label="Start Game ▶️", style=discord.ButtonStyle.success, custom_id="btn_lobby_start")
        self.btn_cancel = Button(label="Cancel ❌", style=discord.ButtonStyle.danger, custom_id="btn_lobby_cancel")

        # Map callbacks to class methods
        self.btn_join.callback = self.join_button_callback
        self.btn_leave.callback = self.leave_button_callback
        self.btn_add_bot.callback = self.add_bot_button_callback
        self.btn_rem_bot.callback = self.remove_bot_button_callback
        self.btn_start.callback = self.start_button_callback
        self.btn_cancel.callback = self.cancel_button_callback

        self.build_lobby_layout()

    def build_lobby_layout(self):
        self.container.clear_items()

        header_text = (
            f"# 🃏 Flip 7 — Game Lobby\n"
            f"**Host:** <@{self.host.id}>\n"
            f"**Target Score:** `{self.target_score} pts`\n\n"
            "Gather your friends! Click **Join** below to enter the table.\n"
            "Need more players? Click **Add Bot** to fill seats.\n"
            "When ready (2–8 players), the host can click **Start Game**!"
        )
        self.container.add_item(TextDisplay(header_text))
        self.container.add_item(Separator())

        player_lines = []
        for i, p in enumerate(self.engine.players.values(), start=1):
            if p.id == self.host.id:
                player_lines.append(f"`{i}.` 👑 **{p.name}** *(Host)*")
            elif p.is_bot:
                player_lines.append(f"`{i}.` 🤖 **{p.name}** *(Bot)*")
            else:
                player_lines.append(f"`{i}.` 🎮 **{p.name}**")

        players_content = f"## Players ({len(self.engine.players)}/8)\n" + ("\n".join(player_lines) if player_lines else "*Empty*")
        self.container.add_item(TextDisplay(players_content))
        self.container.add_item(Separator())
        self.container.add_item(TextDisplay("-# **Flip 7 is a press-your-luck card game. First to reach the target score wins!**"))

        # Append interactive ActionRows into the V2 container
        row1 = ActionRow(self.btn_join, self.btn_leave, self.btn_add_bot, self.btn_rem_bot)
        row2 = ActionRow(self.btn_start, self.btn_cancel)
        self.container.add_item(row1)
        self.container.add_item(row2)

    async def join_button_callback(self, interaction: discord.Interaction):
        if interaction.user.id in self.engine.players:
            await interaction.response.send_message("You are already in the lobby!", ephemeral=True)
            return

        if len(self.engine.players) >= 8:
            await interaction.response.send_message("The lobby is full (max 8 players).", ephemeral=True)
            return

        self.engine.add_player(interaction.user.id, interaction.user.display_name, is_bot=False)
        self.build_lobby_layout()
        await interaction.response.edit_message(view=self)

    async def leave_button_callback(self, interaction: discord.Interaction):
        if interaction.user.id not in self.engine.players:
            await interaction.response.send_message("You are not in the lobby.", ephemeral=True)
            return

        if interaction.user.id == self.host.id:
            await interaction.response.send_message("Host cannot leave. Click **Cancel** to disband the lobby.", ephemeral=True)
            return

        self.engine.remove_player(interaction.user.id)
        self.build_lobby_layout()
        await interaction.response.edit_message(view=self)

    async def add_bot_button_callback(self, interaction: discord.Interaction):
        # Ensure only the host can add bots
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("Only the game host can add bots to the lobby.", ephemeral=True)
            return

        if len(self.engine.players) >= 8:
            await interaction.response.send_message("The lobby is full (max 8 players).", ephemeral=True)
            return

        bot_name = BOT_NAMES[self.bot_index % len(BOT_NAMES)]
        self.bot_index += 1
        bot_id = 900000 + self.bot_index

        self.engine.add_player(bot_id, f"Bot {bot_name}", is_bot=True)
        self.build_lobby_layout()
        await interaction.response.edit_message(view=self)

    async def remove_bot_button_callback(self, interaction: discord.Interaction):
        # Ensure only the host can remove bots
        if interaction.user.id != self.host.id:
            await interaction.response.send_message("Only the game host can remove bots from the lobby.", ephemeral=True)
            return

        bot_keys = [uid for uid, p in self.engine.players.items() if p.is_bot]
        if not bot_keys:
            await interaction.response.send_message("There are no bots in the lobby to remove.", ephemeral=True)
            return

        self.engine.remove_player(bot_keys[-1])
        self.build_lobby_layout()
        await interaction.response.edit_message(view=self)

    async def start_button_callback(self, interaction: discord.Interaction):
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
        game_view.build_game_layout()

        await interaction.response.edit_message(view=game_view)
        await game_view.start_turn_cycle()

    async def cancel_button_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.session.host.id:
            await interaction.response.send_message("Only the host can cancel the game.", ephemeral=True)
            return

        self.container.clear_items()
        self.container.add_item(TextDisplay(f"# 🚫 Lobby Cancelled\nThe lobby was cancelled by <@{self.host.id}>."))
        await interaction.response.edit_message(view=self)
        self.session.stop()