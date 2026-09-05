# Flip 7 Discord Bot

A Discord app for playing the press-your-luck card game **Flip 7** with your friends!

> **Disclaimer:** This is an unofficial, fan-made application and is not affiliated with, endorsed by, or associated with Flip 7, USAopoly, Inc., or its partners. All game mechanics, names, and card designs belong to their respective copyright holders.

---

## Features

- **Multiplayer Matchmaking Lobby**: Gather 2 to 8 friends in any text channel using interactive buttons (**Join**, **Leave**, **Add Bot**, **Start Game**).
- **AI Bot Opponents**: Add AI bots to fill empty seats or test the game solo. Bots calculate duplicate risk and make smart press-your-luck choices!
- **Authentic 94-Card Deck**:
  - **Number Cards (0–12)**: 1x `0`, 1x `1`, 2x `2`, ..., 12x `12` (79 number cards).
  - **Action Cards**:
    - `[❤️ Second Chance]` (3x): Shields against your next duplicate number bust. Max 1 held; excess copies are passed to active opponents.
    - `[❄️ Freeze]` (3x): Choose a player (opponent or self) to immediately stay and bank their current points.
    - `[⚡️ Flip Three]` (3x): Forces a target player to flip the next 3 cards from the deck in sequence.
  - **Score Modifiers**:
    - Flat Bonuses: `[+2]`, `[+4]`, `[+6]`, `[+8]`, `[+10]`.
    - Multiplier: `[x2]` (doubles the sum of number cards).
- **The Flip 7 Bonus (+15 pts)**: Flipping 7 unique number cards (including `0`) triggers **FLIP 7** (+15 points) and ends the round immediately for all players!
- **Multi-Round Matches**: Bank points across rounds until someone reaches the target score (default 200 points, configurable).
- **AFK Protection**: 45-second turn timer automatically stays inactive players so the game never stalls.
- **Channel Isolation**: Multiple channels and servers can run their own matches simultaneously without cross-talk.

---

## Discord Invite Link

If you want to invite/install the bot to your server, [visit this link](https://discord.com/oauth2/authorize?client_id=1544796864690397184). This bot is hosted by me and may not always be up. For instructions on how to self-host, read below.

## Self-Hosting

### 1. Prerequisites
- Python 3.10+
- A Discord Bot Token from the [Discord Developer Portal](https://discord.com/developers/applications)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/asabljic-iit/flip7-discord-bot.git
cd flip7-discord-bot

# Activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create or update `.env`:
```bash
echo "DISCORD_TOKEN=your_copied_bot_token_here" > .env
```

### 4. Run the Bot
```bash
python3 main.py
```

---

## Slash Commands

| Command | Description |
| :--- | :--- |
| `/flip7 [optional_target_score]` | Starts a game lobby in the current channel (default goal: 200 points). |
| `/flip7_rules` | Displays the complete rulebook, card guide, and scoring formula. |
| `/flip7_stop` | Cancels the active game or lobby in the channel (host or moderator only). |
| `/ping` | Checks bot latency. |

---

## Scoring Rules
1. **Sum Numbers**: Add the face values of your number cards.
2. **Apply Multiplier**: Multiply the number sum by 2 if holding `[x2]`.
3. **Add Modifiers**: Add all flat modifier cards (`+2` to `+10`).
4. **Flip 7 Bonus**: Add `+15` if you have 7 unique number cards in hand.
5. **Bust**: Drawing a duplicate number without a `Second Chance` shield results in **0 points** for the round!

---

## Running Tests
```bash
python -m unittest test_flip7.py -v
```

