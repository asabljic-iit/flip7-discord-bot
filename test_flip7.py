import unittest
from game.models import Card, Player, build_flip7_deck
from game.engine import Flip7Engine

class TestFlip7Engine(unittest.TestCase):

    def test_deck_composition(self):
        deck = build_flip7_deck()
        self.assertEqual(len(deck), 94, "Deck must have exactly 94 cards")

        num_cards = [c for c in deck if c.is_number]
        self.assertEqual(len(num_cards), 79, "Must have 79 number cards")
        
        card_0 = [c for c in num_cards if c.value == 0]
        self.assertEqual(len(card_0), 1, "Must have 1 0-card")
        for n in range(1, 13):
            matching = [c for c in num_cards if c.value == n]
            self.assertEqual(len(matching), n, f"Must have {n} copies of card {n}")

        second_chances = [c for c in deck if c.name == "Second Chance"]
        freezes = [c for c in deck if c.name == "Freeze"]
        flip_threes = [c for c in deck if c.name == "Flip Three"]
        self.assertEqual(len(second_chances), 3)
        self.assertEqual(len(freezes), 3)
        self.assertEqual(len(flip_threes), 3)

        modifiers = [c for c in deck if c.is_modifier]
        self.assertEqual(len(modifiers), 6)
        x2_cards = [c for c in modifiers if c.is_multiplier]
        self.assertEqual(len(x2_cards), 1)
        flat_mods = [c for c in modifiers if not c.is_multiplier]
        self.assertEqual(sorted(c.value for c in flat_mods), [2, 4, 6, 8, 10])

    def test_single_hit_per_turn_enforcement(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")

        engine.deck = [Card("5", "number", 5), Card("6", "number", 6)]
        engine.start_round()

        # Bob hits once (drawing 6) and turn automatically advances to Charlie
        card, result, _ = engine.hit(1)
        self.assertEqual(card.value, 6)
        self.assertEqual(engine.get_current_player().id, 2)

    def test_action_card_single_hit_lockout(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")
        engine.add_player(3, "Dave")

        engine.deck = [Card("Freeze", "action")]
        engine.start_round()

        # Bob draws Freeze
        card, result, _ = engine.hit(1)
        self.assertEqual(result, "action_freeze")

        # Bob cannot hit again while freeze action is pending
        with self.assertRaises(ValueError):
            engine.hit(1)

        # Resolving freeze on Charlie freezes Charlie (player 2), so turn advances past Charlie to Dave (player 3)
        engine.resolve_freeze(actor_user_id=1, target_user_id=2)
        self.assertEqual(engine.get_current_player().id, 3)
        self.assertIsNone(engine.players[1].pending_action)

    def test_scoring_mechanics(self):
        player = Player(1, "Alice")
        
        player.hand = [Card("5", "number", 5), Card("7", "number", 7), Card("10", "number", 10)]
        self.assertEqual(player.get_round_score(), 22)

        player.hand.append(Card("+4", "modifier", 4))
        self.assertEqual(player.get_round_score(), 26)

        player.hand.append(Card("x2", "modifier", 0, is_multiplier=True))
        self.assertEqual(player.get_round_score(), 48)

        player.hand.extend([
            Card("0", "number", 0),
            Card("1", "number", 1),
            Card("2", "number", 2),
            Card("3", "number", 3)
        ])
        self.assertTrue(player.has_flip7_bonus())
        self.assertEqual(player.get_round_score(), 75)

        player.status = "busted"
        self.assertEqual(player.get_round_score(), 0)

    def test_scoring_order_of_operations(self):
        player = Player(1, "Alice")
        player.hand = [Card("10", "number", 10), Card("5", "number", 5)]
        player.hand.append(Card("+10", "modifier", 10))
        player.hand.append(Card("x2", "modifier", 0, is_multiplier=True))

        self.assertEqual(player.get_round_score(), 40)

    def test_second_chance_protection(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")
        
        bob = engine.players[1]
        bob.hand = [Card("8", "number", 8)]
        bob.has_second_chance = True
        bob.hand.append(Card("Second Chance", "action"))

        engine.deck = [Card("8", "number", 8)]
        
        card, result, _ = engine.hit(bob.id)
        self.assertEqual(result, "saved_by_second_chance")
        self.assertEqual(bob.status, "playing")
        self.assertFalse(bob.has_second_chance)
        self.assertEqual(len(bob.hand), 1)
        self.assertEqual(bob.hand[0].value, 8)

        engine.deck = [Card("8", "number", 8)]
        card, result, _ = engine.hit(bob.id)
        self.assertEqual(result, "busted")
        self.assertEqual(bob.status, "busted")

    def test_second_chance_draw_ends_turn(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")

        engine.deck = [Card("Second Chance", "action")]
        engine.start_round()

        card, result, _ = engine.hit(1)
        self.assertEqual(result, "action_second_chance_kept")
        self.assertEqual(engine.players[1].status, "playing")
        self.assertEqual(engine.get_current_player().id, 2)

    def test_freeze_resolution(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")
        
        engine.resolve_freeze(actor_user_id=1, target_user_id=2)
        charlie = engine.players[2]
        self.assertEqual(charlie.status, "frozen")

    def test_flip_7_immediate_round_end(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")

        bob = engine.players[1]
        bob.hand = [Card(str(i), "number", i) for i in range(6)]
        
        engine.deck = [Card("6", "number", 6)]
        card, result, _ = engine.hit(bob.id)
        
        self.assertEqual(result, "flip7")
        self.assertTrue(engine.is_round_over())
        self.assertEqual(engine.players[2].status, "stayed")

    def test_flip_three_resolution(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")

        charlie = engine.players[2]
        charlie.hand = [Card("1", "number", 1)]

        engine.deck = [Card("4", "number", 4), Card("3", "number", 3), Card("2", "number", 2)]
        results = engine.resolve_flip_three(actor_user_id=1, target_user_id=2)
        
        self.assertEqual(len(results), 3)
        self.assertEqual(len(charlie.hand), 4)
        self.assertEqual(charlie.status, "playing")

        charlie.hand = [Card("5", "number", 5)]
        engine.deck = [Card("9", "number", 9), Card("5", "number", 5)]
        results = engine.resolve_flip_three(actor_user_id=1, target_user_id=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(charlie.status, "busted")

    def test_flip_three_deferred_action_resolution(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")

        charlie = engine.players[2]
        charlie.hand = [Card("1", "number", 1)]

        # Charlie draws 2, Freeze, 3 -> Freeze should be deferred as pending action
        engine.deck = [Card("3", "number", 3), Card("Freeze", "action"), Card("2", "number", 2)]
        results = engine.resolve_flip_three(actor_user_id=1, target_user_id=2)

        self.assertEqual(len(results), 3)
        self.assertEqual(charlie.status, "playing")
        self.assertEqual(charlie.pending_action, "freeze")

        # Busted test: Charlie draws duplicated 1 and a Freeze -> Freeze should NOT trigger
        charlie.pending_action = None
        charlie.hand = [Card("1", "number", 1)]
        engine.deck = [Card("4", "number", 4), Card("Freeze", "action"), Card("1", "number", 1)]
        results = engine.resolve_flip_three(actor_user_id=1, target_user_id=2)

        self.assertEqual(charlie.status, "busted")
        self.assertIsNone(charlie.pending_action)

    def test_second_chance_pass(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.add_player(2, "Charlie")

        bob = engine.players[1]
        bob.has_second_chance = True
        
        recipient = engine.resolve_pass_second_chance(actor_user_id=1, recipient_user_id=2)
        self.assertEqual(recipient.id, 2)
        self.assertTrue(engine.players[2].has_second_chance)
        self.assertEqual(bob.status, "playing")

    def test_deck_reshuffle_when_empty(self):
        engine = Flip7Engine(target_score=200)
        engine.add_player(1, "Bob")
        engine.deck = []
        engine.discard_pile = [Card("5", "number", 5), Card("6", "number", 6)]

        drawn = engine._draw_card()
        self.assertIn(drawn.value, [5, 6])
        self.assertEqual(len(engine.discard_pile), 0)
        self.assertEqual(len(engine.deck), 1)

    def test_game_session_and_views(self):
        from game.ui import GameSession, Flip7LobbyView, Flip7GameView, Flip7RoundEndView
        from discord.ui import TextDisplay

        class MockUser:
            id = 555
            name = "TestUser"
            display_name = "TestUser"

        # Test GameSession initialization
        session = GameSession(channel_id=123, host=MockUser(), target_score=100)
        self.assertEqual(len(session.engine.players), 1)
        self.assertEqual(session.engine.players[555].name, "TestUser")

        # Test Flip7LobbyView layout items
        lobby = Flip7LobbyView(session)
        lobby_texts = [item.content for item in lobby.container.children if isinstance(item, TextDisplay)]
        self.assertTrue(any("Flip 7 — Game Lobby" in text for text in lobby_texts))

        # Add bot and start round
        session.engine.add_player(999, "Bot Alex", is_bot=True)
        session.engine.start_round()

        # Test Flip7GameView layout items
        game_view = Flip7GameView(session)
        game_view.build_game_layout()
        game_texts = [item.content for item in game_view.container.children if isinstance(item, TextDisplay)]
        self.assertTrue(any("Round 1" in text for text in game_texts))

        # Test Flip7RoundEndView layout items
        scores = session.engine.tally_round_scores()
        round_view = Flip7RoundEndView(session, round_scores=scores)
        summary_texts = [item.content for item in round_view.container.children if isinstance(item, TextDisplay)]
        self.assertTrue(any("Round 1 Finished" in text for text in summary_texts))

        # Stop session
        session.stop()
        self.assertFalse(session.is_active)

if __name__ == "__main__":
    unittest.main()
