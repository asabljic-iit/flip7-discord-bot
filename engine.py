import random
from typing import List, Dict, Tuple, Optional
from models import Card, Player, build_flip7_deck

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
        if not target_player or target_player.status != "playing":
            raise ValueError("Target player is not active.")

        target_player.status = "frozen"

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
        pending_actions_queue: List[Tuple[Card, str]] = []

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
                        pending_actions_queue.append((drawn_card, "pass_second_chance"))
                        results.append((drawn_card, "second_chance_passed_pending"))
                    else:
                        self.discard_pile.append(drawn_card)
                        results.append((drawn_card, "second_chance_discarded"))

            elif drawn_card.name == "Freeze":
                pending_actions_queue.append((drawn_card, "freeze"))
                results.append((drawn_card, "freeze_drawn"))

            elif drawn_card.name == "Flip Three":
                pending_actions_queue.append((drawn_card, "flip_three"))
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

        if target_player.status == "busted":
            for card_obj, _ in pending_actions_queue:
                self.discard_pile.append(card_obj)
        else:
            for _, act_type in pending_actions_queue:
                target_player.pending_actions.append(act_type)

        self.check_round_over()
        if advance_turn:
            self._advance_turn()
        return results

    def resolve_pass_second_chance(self, actor_user_id: int, recipient_user_id: int, card: Optional[Card] = None) -> Player:
        actor = self.players.get(actor_user_id)
        if actor:
            actor.pending_action = None

        recipient = self.players.get(recipient_user_id)
        if not recipient or recipient.status != "playing":
            raise ValueError("Recipient is not active.")

        sc_card = card if card else Card("Second Chance", "action")

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

        leaderboard = self.get_leaderboard()
        top_score = leaderboard[0].total_score
        top_count = sum(1 for p in leaderboard if p.total_score == top_score)
        
        return top_count == 1

    def get_winner(self) -> Optional[Player]:
        if not self.is_game_over():
            return None
        leaderboard = self.get_leaderboard()
        return leaderboard[0] if leaderboard else None

    def to_dict(self) -> dict:
        return {
            "players": {str(k): v.to_dict() for k, v in self.players.items()},
            "player_order": self.player_order,
            "deck": [c.to_dict() for c in self.deck],
            "discard_pile": [c.to_dict() for c in self.discard_pile],
            "current_turn_index": self.current_turn_index,
            "target_score": self.target_score,
            "round_number": self.round_number,
            "flip7_achieved_by_id": self.flip7_achieved_by.id if self.flip7_achieved_by else None
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Flip7Engine":
        engine = cls(target_score=data["target_score"])
        engine.players = {int(k): Player.from_dict(v) for k, v in data["players"].items()}
        engine.player_order = data["player_order"]
        engine.deck = [Card.from_dict(c) for c in data["deck"]]
        engine.discard_pile = [Card.from_dict(c) for c in data["discard_pile"]]
        engine.current_turn_index = data["current_turn_index"]
        engine.round_number = data["round_number"]
        
        flip7_id = data.get("flip7_achieved_by_id")
        if flip7_id and flip7_id in engine.players:
            engine.flip7_achieved_by = engine.players[flip7_id]
            
        return engine

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