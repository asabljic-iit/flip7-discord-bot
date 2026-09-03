import random
from typing import List, Dict, Tuple, Optional

class Card:
    def __init__(self, name: str, category: str, value: int = 0, is_multiplier: bool = False):
        self.name = name
        self.category = category  # "number", "action", "modifier"
        self.value = value        # Face value for number, or flat bonus for modifier
        self.is_multiplier = is_multiplier  # True only for "x2"

    @property
    def is_number(self) -> bool:
        return self.category == "number"

    @property
    def is_action(self) -> bool:
        return self.category == "action"

    @property
    def is_modifier(self) -> bool:
        return self.category == "modifier"

    def format_card(self) -> str:
        """Returns clean formatted string with emoji for Discord embeds."""
        if self.is_number:
            return f"`[{self.value}]`"
        if self.name == "x2":
            return "`[✖️ x2]`"
        if self.is_modifier:
            return f"`[➕ +{self.value}]`"
        if self.name == "Second Chance":
            return "`[❤️ 2nd Chance]`"
        if self.name == "Freeze":
            return "`[❄️ Freeze]`"
        if self.name == "Flip Three":
            return "`[⚡ Flip 3]`"
        return f"`[{self.name}]`"

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, other) -> bool:
        if isinstance(other, Card):
            return self.name == other.name and self.category == other.category and self.value == other.value
        if isinstance(other, int) and self.is_number:
            return self.value == other
        if isinstance(other, str):
            return self.name == other
        return False


def build_flip7_deck() -> List[Card]:
    """Generates the official 94-card Flip 7 deck."""
    deck: List[Card] = []

    # 1x 0-card (counts as number for Flip 7 bonus, worth 0 points)
    deck.append(Card("0", "number", value=0))

    # Number cards 1 to 12 (count equals face value)
    for num in range(1, 13):
        for _ in range(num):
            deck.append(Card(str(num), "number", value=num))

    # Action cards (3 copies of each)
    for _ in range(3):
        deck.append(Card("Second Chance", "action"))
        deck.append(Card("Freeze", "action"))
        deck.append(Card("Flip Three", "action"))

    # Flat modifier cards (1 of each: +2, +4, +6, +8, +10)
    for mod in [2, 4, 6, 8, 10]:
        deck.append(Card(f"+{mod}", "modifier", value=mod))

    # Multiplier modifier card (1 copy of x2)
    deck.append(Card("x2", "modifier", value=0, is_multiplier=True))

    return deck


class Player:
    def __init__(self, user_id: int, name: str, is_bot: bool = False):
        self.id = user_id
        self.name = name
        self.is_bot = is_bot
        self.hand: List[Card] = []
        self.total_score: int = 0
        self.status: str = "playing"  # States: "playing", "stayed", "busted", "frozen"
        self.has_second_chance: bool = False
        self.pending_actions: List[str] = []
        self.round_score_cache: int = 0

    @property
    def pending_action(self) -> Optional[str]:
        return self.pending_actions[0] if self.pending_actions else None

    @pending_action.setter
    def pending_action(self, val: Optional[str]):
        if val is None:
            if self.pending_actions:
                self.pending_actions.pop(0)
        else:
            self.pending_actions.append(val)

    @property
    def number_cards(self) -> List[Card]:
        return [c for c in self.hand if c.is_number]

    @property
    def unique_numbers(self) -> List[int]:
        return list(set(c.value for c in self.number_cards))

    @property
    def modifier_cards(self) -> List[Card]:
        return [c for c in self.hand if c.is_modifier]

    @property
    def has_x2(self) -> bool:
        return any(c.is_multiplier for c in self.hand)

    def has_flip7_bonus(self) -> bool:
        """Flip 7 is achieved by collecting 7 unique number cards (0-12)."""
        return len(self.unique_numbers) >= 7

    def get_round_score(self) -> int:
        if self.status == "busted":
            return 0

        num_sum = sum(c.value for c in self.number_cards)
        if self.has_x2:
            num_sum *= 2

        mod_sum = sum(c.value for c in self.modifier_cards if not c.is_multiplier)
        bonus = 15 if self.has_flip7_bonus() else 0

        return num_sum + mod_sum + bonus

    def reset_for_new_round(self):
        self.hand = []
        self.status = "playing"
        self.has_second_chance = False
        self.pending_actions = []
        self.round_score_cache = 0


class Flip7Engine:
    def __init__(self, target_score: int = 200):
        self.players: Dict[int, Player] = {}
        self.player_order: List[int] = []
        self.deck: List[Card] = []
        self.discard_pile: List[Card] = []
        self.current_turn_index: int = 0
        self.target_score: int = target_score
        self.round_number: int = 0
        self.flip7_achieved_by: Optional[Player] = None
        self.last_action_message: str = ""

    def add_player(self, user_id: int, name: str, is_bot: bool = False):
        if user_id not in self.players:
            self.players[user_id] = Player(user_id, name, is_bot=is_bot)
            self.player_order.append(user_id)

    def remove_player(self, user_id: int):
        if user_id in self.players:
            del self.players[user_id]
            if user_id in self.player_order:
                self.player_order.remove(user_id)

    def _draw_card(self) -> Card:
        if not self.deck:
            if self.discard_pile:
                self.deck = self.discard_pile
                self.discard_pile = []
                random.shuffle(self.deck)
            else:
                self.deck = build_flip7_deck()
                random.shuffle(self.deck)
        return self.deck.pop()

    def start_round(self):
        """Resets hands/statuses and prepares the deck for a new round."""
        self.round_number += 1
        self.flip7_achieved_by = None

        total_available = len(self.deck) + len(self.discard_pile)
        if total_available < len(self.player_order) * 4 and total_available >= 90:
            all_cards = self.deck + self.discard_pile
            self.deck = all_cards
            self.discard_pile = []
            random.shuffle(self.deck)
        elif not self.deck and not self.discard_pile:
            self.deck = build_flip7_deck()
            random.shuffle(self.deck)

        for player in self.players.values():
            player.reset_for_new_round()

        if self.round_number > 1 and len(self.player_order) > 1:
            first = self.player_order.pop(0)
            self.player_order.append(first)

        self.current_turn_index = 0
        self._ensure_valid_turn()

    def get_current_player(self) -> Optional[Player]:
        if not self.player_order:
            return None
        return self.players[self.player_order[self.current_turn_index]]

    def hit(self, user_id: int) -> Tuple[Card, str, Optional[Dict]]:
        player = self.players[user_id]
        if player.status != "playing":
            raise ValueError(f"{player.name} cannot hit in status '{player.status}'.")

        if player.pending_action:
            raise ValueError(f"{player.name} must resolve pending action '{player.pending_action}' before hitting again.")

        drawn_card = self._draw_card()

        # --- ACTION CARDS ---
        if drawn_card.name == "Second Chance":
            if not player.has_second_chance:
                player.has_second_chance = True
                player.hand.append(drawn_card)
                self.check_round_over()
                self._advance_turn()
                return drawn_card, "action_second_chance_kept", None
            else:
                eligible_targets = [p for p in self.players.values() if p.id != player.id and p.status == "playing" and not p.has_second_chance]
                if eligible_targets:
                    player.pending_action = "pass_second_chance"
                    return drawn_card, "action_second_chance_pass", {"targets": [p.id for p in eligible_targets]}
                else:
                    self.discard_pile.append(drawn_card)
                    self.check_round_over()
                    self._advance_turn()
                    return drawn_card, "action_second_chance_discarded", None

        if drawn_card.name == "Freeze":
            player.pending_action = "freeze"
            active_targets = [p.id for p in self.players.values() if p.status == "playing"]
            return drawn_card, "action_freeze", {"targets": active_targets}

        if drawn_card.name == "Flip Three":
            player.pending_action = "flip_three"
            active_targets = [p.id for p in self.players.values() if p.status == "playing"]
            return drawn_card, "action_flip_three", {"targets": active_targets}

        # --- MODIFIER CARDS ---
        if drawn_card.is_modifier:
            player.hand.append(drawn_card)
            self.check_round_over()
            self._advance_turn()
            return drawn_card, "safe", None

        # --- NUMBER CARDS ---
        player.hand.append(drawn_card)

        duplicate_count = sum(1 for c in player.hand if c.is_number and c.value == drawn_card.value)
        if duplicate_count > 1:
            if player.has_second_chance:
                player.hand.remove(drawn_card)
                self.discard_pile.append(drawn_card)

                sc_card = next((c for c in player.hand if c.name == "Second Chance"), None)
                if sc_card:
                    player.hand.remove(sc_card)
                    self.discard_pile.append(sc_card)
                player.has_second_chance = False

                self.check_round_over()
                self._advance_turn()
                return drawn_card, "saved_by_second_chance", None
            else:
                player.status = "busted"
                self.discard_pile.extend(player.hand)
                self.check_round_over()
                self._advance_turn()
                return drawn_card, "busted", None

        if player.has_flip7_bonus():
            self.flip7_achieved_by = player
            self.end_round_due_to_flip7()
            return drawn_card, "flip7", None

        self.check_round_over()
        self._advance_turn()
        return drawn_card, "safe", None

    def stay(self, user_id: int):
        player = self.players[user_id]
        if player.status == "playing":
            if player.pending_action:
                raise ValueError(f"{player.name} must resolve pending action '{player.pending_action}' before staying.")
            player.status = "stayed"
            self.check_round_over()
            self._advance_turn()

    def resolve_freeze(self, actor_user_id: int, target_user_id: int) -> Tuple[Player, Card]:
        freeze_card = Card("Freeze", "action")
        self.discard_pile.append(freeze_card)

        actor = self.players.get(actor_user_id)
        if actor:
            actor.pending_action = None

        target_player = self.players.get(target_user_id)
        # Freeze can ONLY target an active player ("playing")
        if not target_player or target_player.status != "playing":
            raise ValueError("Target player is not active.")

        target_player.status = "frozen"

        # If actor froze themselves, end their turn
        if actor_user_id == target_user_id and actor:
            actor.status = "frozen"

        self.check_round_over()
        self._advance_turn()
        return target_player, freeze_card

    def resolve_flip_three(self, actor_user_id: int, target_user_id: int, advance_turn: bool = True) -> List[Tuple[Card, str]]:
        flip3_card = Card("Flip Three", "action")
        self.discard_pile.append(flip3_card)

        actor = self.players.get(actor_user_id)
        if actor:
            actor.pending_action = None

        target_player = self.players.get(target_user_id)
        if not target_player or target_player.status != "playing":
            raise ValueError("Target player is not active.")

        results: List[Tuple[Card, str]] = []
        pending_actions_queue: List[str] = []

        for _ in range(3):
            drawn_card = self._draw_card()

            if drawn_card.name == "Second Chance":
                if not target_player.has_second_chance:
                    target_player.has_second_chance = True
                    target_player.hand.append(drawn_card)
                    results.append((drawn_card, "second_chance_kept"))
                else:
                    eligible_targets = [p for p in self.players.values() if p.id != target_player.id and p.status == "playing" and not p.has_second_chance]
                    if eligible_targets:
                        pending_actions_queue.append("pass_second_chance")
                        results.append((drawn_card, "second_chance_passed_pending"))
                    else:
                        self.discard_pile.append(drawn_card)
                        results.append((drawn_card, "second_chance_discarded"))

            elif drawn_card.name == "Freeze":
                pending_actions_queue.append("freeze")
                results.append((drawn_card, "freeze_drawn"))

            elif drawn_card.name == "Flip Three":
                pending_actions_queue.append("flip_three")
                results.append((drawn_card, "flip_three_drawn"))

            elif drawn_card.is_modifier:
                target_player.hand.append(drawn_card)
                results.append((drawn_card, "modifier"))

            else:
                target_player.hand.append(drawn_card)
                dup_count = sum(1 for c in target_player.hand if c.is_number and c.value == drawn_card.value)

                if dup_count > 1:
                    if target_player.has_second_chance:
                        target_player.hand.remove(drawn_card)
                        self.discard_pile.append(drawn_card)
                        sc_card = next((c for c in target_player.hand if c.name == "Second Chance"), None)
                        if sc_card:
                            target_player.hand.remove(sc_card)
                            self.discard_pile.append(sc_card)
                        target_player.has_second_chance = False
                        results.append((drawn_card, "saved_by_second_chance"))
                    else:
                        target_player.status = "busted"
                        self.discard_pile.extend(target_player.hand)
                        results.append((drawn_card, "busted"))
                        break
                else:
                    if target_player.has_flip7_bonus():
                        self.flip7_achieved_by = target_player
                        results.append((drawn_card, "flip7"))
                        self.end_round_due_to_flip7()
                        break
                    else:
                        results.append((drawn_card, "safe"))

        # Add all queued action cards to target player if they haven't busted
        if target_player.status == "busted":
            for act in pending_actions_queue:
                if act != "pass_second_chance":
                    self.discard_pile.append(Card("Freeze" if act == "freeze" else "Flip Three", "action"))
        else:
            target_player.pending_actions.extend(pending_actions_queue)

        self.check_round_over()
        if advance_turn:
            self._advance_turn()
        return results

    def resolve_pass_second_chance(self, actor_user_id: int, recipient_user_id: int) -> Player:
        sc_card = Card("Second Chance", "action")
        
        actor = self.players.get(actor_user_id)
        if actor:
            actor.pending_action = None

        recipient = self.players.get(recipient_user_id)
        if not recipient or recipient.status != "playing":
            raise ValueError("Recipient is not active.")
        recipient.has_second_chance = True
        recipient.hand.append(sc_card)
        self.check_round_over()
        self._advance_turn()
        return recipient

    def end_round_due_to_flip7(self):
        for p in self.players.values():
            if p.status == "playing":
                p.status = "stayed"

    def _advance_turn(self):
        if self.is_round_over():
            return

        # If current player still has pending actions queued, do NOT advance turn ownership
        curr = self.get_current_player()
        if curr and curr.status == "playing" and curr.pending_actions:
            return

        start_index = self.current_turn_index
        while True:
            self.current_turn_index = (self.current_turn_index + 1) % len(self.player_order)
            next_player = self.get_current_player()
            if next_player and next_player.status == "playing":
                break
            if self.current_turn_index == start_index:
                break

    def _ensure_valid_turn(self):
        if self.is_round_over():
            return
        curr = self.get_current_player()
        if not curr or curr.status != "playing":
            self._advance_turn()

    def is_round_over(self) -> bool:
        return all(p.status in ["stayed", "busted", "frozen"] for p in self.players.values())

    def check_round_over(self) -> bool:
        return self.is_round_over()

    def tally_round_scores(self) -> Dict[int, int]:
        round_scores = {}
        for p in self.players.values():
            r_score = p.get_round_score()
            p.total_score += r_score
            round_scores[p.id] = r_score
            
            # Move all cards to discard pile and clear state
            self.discard_pile.extend(p.hand)
            p.hand = []
            p.has_second_chance = False
            p.pending_actions = []

        return round_scores

    def get_leaderboard(self) -> List[Player]:
        return sorted(self.players.values(), key=lambda p: p.total_score, reverse=True)

    def is_game_over(self) -> bool:
        if not self.is_round_over():
            return False

        qualifiers = [p for p in self.players.values() if p.total_score >= self.target_score]
        if not qualifiers:
            return False

        # Only declare game over if top score is not tied
        leaderboard = self.get_leaderboard()
        top_score = leaderboard[0].total_score
        top_count = sum(1 for p in leaderboard if p.total_score == top_score)
        
        return top_count == 1

    def get_winner(self) -> Optional[Player]:
        if not self.is_game_over():
            return None
        leaderboard = self.get_leaderboard()
        return leaderboard[0] if leaderboard else None

    # --- AI BOT LOGIC ---
    def get_bot_decision(self, bot_player: Player) -> str:
        if bot_player.status != "playing":
            return "stay"

        if bot_player.has_second_chance:
            return "hit"

        unique_count = len(bot_player.unique_numbers)
        if unique_count == 6:
            return "hit" if bot_player.get_round_score() < 50 else "stay"

        known_deck = self.deck if self.deck else (self.deck + self.discard_pile)
        total_cards = len(known_deck)
        if total_cards == 0:
            return "hit"

        current_nums = set(c.value for c in bot_player.number_cards)
        bust_card_count = sum(1 for c in known_deck if c.is_number and c.value in current_nums)
        bust_prob = bust_card_count / total_cards

        current_score = bot_player.get_round_score()

        if current_score < 15:
            return "hit" if bust_prob < 0.35 else "stay"
        elif current_score < 30:
            return "hit" if bust_prob < 0.22 else "stay"
        elif current_score < 50:
            return "hit" if bust_prob < 0.15 else "stay"
        else:
            return "stay"

    def choose_bot_freeze_target(self, bot_player: Player) -> int:
        opponents = [p for p in self.players.values() if p.id != bot_player.id and p.status == "playing"]
        if not opponents:
            return bot_player.id
        opponents.sort(key=lambda p: (p.get_round_score(), p.total_score), reverse=True)
        return opponents[0].id

    def choose_bot_flip_three_target(self, bot_player: Player) -> int:
        opponents = [p for p in self.players.values() if p.id != bot_player.id and p.status == "playing"]
        if not opponents:
            return bot_player.id

        opponents.sort(key=lambda p: len(p.number_cards), reverse=True)
        if len(opponents[0].number_cards) >= 3 and not opponents[0].has_second_chance:
            return opponents[0].id
        elif len(bot_player.number_cards) <= 2:
            return bot_player.id
        return opponents[0].id