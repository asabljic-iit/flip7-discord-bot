from typing import List, Optional

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
            return f"`{self.value}`"
        if self.name == "x2":
            return "`×2`"
        if self.is_modifier:
            return f"`+{self.value}`"
        if self.name == "Second Chance":
            return "`❤️ 2nd Chance`"
        if self.name == "Freeze":
            return "`❄️ Freeze`"
        if self.name == "Flip Three":
            return "`⚡️ Flip 3`"
        return f"`{self.name}`"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "value": self.value,
            "is_multiplier": self.is_multiplier
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(
            name=data["name"],
            category=data["category"],
            value=data["value"],
            is_multiplier=data["is_multiplier"]
        )

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_bot": self.is_bot,
            "hand": [c.to_dict() for c in self.hand],
            "total_score": self.total_score,
            "status": self.status,
            "has_second_chance": self.has_second_chance,
            "pending_actions": self.pending_actions,
            "round_score_cache": self.round_score_cache
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Player":
        p = cls(data["id"], data["name"], is_bot=data["is_bot"])
        p.hand = [Card.from_dict(c) for c in data["hand"]]
        p.total_score = data["total_score"]
        p.status = data["status"]
        p.has_second_chance = data["has_second_chance"]
        p.pending_actions = data.get("pending_actions", [])
        p.round_score_cache = data.get("round_score_cache", 0)
        return p