"""Telegram bot implementation for running an Undercover style party game.

The original project already contained most of the game rules, but the control
flow mixed Telegram specific logic with game state in a way that made the bot
hard to use.  This module restructures the code around the
``python-telegram-bot`` conversation API so every action (player count, role
distribution, card selection and elimination) is driven by a dedicated handler
with clear transitions between the conversation states.
"""

from __future__ import annotations
from config import bot_token

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
)

# Enable logging so it is easier to debug when the bot is running live.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# Conversation states
SELECTING_PLAYERS, ROLES_SELECTION, SELECTING_CARDS, ELIMINATING = range(4)


# Default role distributions for the supported number of players.
ROLE_PRESETS: Dict[int, List[tuple[int, int, int]]] = {
    3: [(2, 1, 0), (2, 0, 1)],
    4: [(3, 1, 0), (2, 1, 1)],
    5: [(3, 2, 0), (3, 1, 1)],
    6: [(4, 1, 1), (3, 2, 1)],
    7: [(4, 2, 1), (5, 1, 1)],
    8: [(5, 2, 1), (4, 3, 1)],
    9: [(6, 2, 1), (5, 3, 1)],
    10: [(6, 3, 1), (5, 3, 2)],
}


ROLE_NAMES = {
    "C": "Civilian",
    "U": "Undercover",
    "W": "Mr. White",
}

ROLE_POINTS = {"C": 1, "U": 2, "W": 4}

WORDS_LIBRARY = {
    "C": ["APPLE", "MOUNTAIN", "SPACESHIP", "GUITAR"],
    "U": ["ORANGE", "HILL", "ROCKET", "VIOLIN"],
    "W": ["Invent your own word!"]
}


@dataclass
class Player:
    """Stores the state for a single player in the session."""

    seat: int
    role: str = ""
    word: str = ""
    eliminated: bool = False
    card: Optional[int] = None
    score: int = 0


@dataclass
class GameSession:
    """In-memory representation of the current match for a chat."""

    num_players: int
    players: Dict[int, Player] = field(init=False)
    pending_seats: List[int] = field(init=False)
    available_cards: List[int] = field(init=False)
    elimination_log: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.players = {seat: Player(seat=seat) for seat in range(1, self.num_players + 1)}
        self.pending_seats = list(self.players.keys())
        self.available_cards = list(self.players.keys())

    # --- helpers for role assignment -------------------------------------------------
    def assign_roles(self, civilians: int, undercovers: int, mr_white: int) -> None:
        seats = list(self.players.keys())
        random.shuffle(seats)

        index = 0
        for _ in range(civilians):
            seat = seats[index]
            index += 1
            player = self.players[seat]
            player.role = "C"
            player.word = random.choice(WORDS_LIBRARY["C"])

        for _ in range(undercovers):
            seat = seats[index]
            index += 1
            player = self.players[seat]
            player.role = "U"
            player.word = random.choice(WORDS_LIBRARY["U"])

        for _ in range(mr_white):
            seat = seats[index]
            index += 1
            player = self.players[seat]
            player.role = "W"
            player.word = random.choice(WORDS_LIBRARY["W"])

        # Reset the card selection order whenever roles are reassigned.
        self.pending_seats = list(self.players.keys())
        self.available_cards = list(self.players.keys())

    # --- helpers for card selection --------------------------------------------------
    def register_card_choice(self, card_value: int) -> Player:
        seat = self.pending_seats.pop(0)
        player = self.players[seat]
        player.card = card_value
        self.available_cards.remove(card_value)
        return player

    def elimination_queue(self) -> List[Player]:
        return sorted(
            self.players.values(),
            key=lambda p: (p.card is None, p.card if p.card is not None else 0, p.seat),
        )

    # --- helpers for elimination -----------------------------------------------------
    def active_players(self) -> List[Player]:
        return [player for player in self.players.values() if not player.eliminated]

    def civilians_remaining(self) -> int:
        return sum(1 for player in self.active_players() if player.role == "C")

    def infiltrators_remaining(self) -> int:
        return sum(1 for player in self.active_players() if player.role in {"U", "W"})

    def eliminate(self, seat: int) -> Player:
        player = self.players[seat]
        player.eliminated = True
        self.elimination_log.append(seat)
        return player

    def outcome(self) -> Optional[str]:
        infiltrators = self.infiltrators_remaining()
        civilians = self.civilians_remaining()
        if infiltrators == 0:
            return "civilians"
        if civilians <= infiltrators:
            return "infiltrators"
        return None


def build_number_keyboard() -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for number in range(3, 11):
        row.append(InlineKeyboardButton(str(number), callback_data=f"players:{number}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def build_roles_keyboard(num_players: int) -> InlineKeyboardMarkup:
    presets = ROLE_PRESETS.get(num_players, [])
    buttons = []
    for civilians, undercovers, mr_white in presets:
        label = f"{civilians} Civ, {undercovers} U, {mr_white} W"
        data = f"roles:{civilians}:{undercovers}:{mr_white}"
        buttons.append([InlineKeyboardButton(label, callback_data=data)])
    return InlineKeyboardMarkup(buttons)


def build_card_keyboard(session: GameSession) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for card in session.available_cards:
        row.append(InlineKeyboardButton(str(card), callback_data=f"card:{card}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def build_elimination_keyboard(session: GameSession) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"Player {seat}", callback_data=f"eliminate:{seat}")]
        for seat in sorted(player.seat for player in session.active_players())
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.chat_data.pop("session", None)
    logger.info("Starting new game in chat %s", update.effective_chat.id if update.effective_chat else "N/A")
    if update.message:
        await update.message.reply_text(
            "How many players are taking part?",
            reply_markup=build_number_keyboard(),
        )
    return SELECTING_PLAYERS


async def select_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return SELECTING_PLAYERS
    await query.answer()

    try:
        num_players = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("Could not determine the number of players. Try again with /start.")
        return ConversationHandler.END

    if num_players not in ROLE_PRESETS:
        await query.edit_message_text("Please choose a number between 3 and 10.")
        return SELECTING_PLAYERS

    session = GameSession(num_players)
    context.chat_data["session"] = session

    await query.edit_message_text(
        f"Game setup for {num_players} players. Choose how to distribute the roles:",
    )
    await query.message.reply_text("Select one of the distributions below:", reply_markup=build_roles_keyboard(num_players))
    return ROLES_SELECTION


async def select_roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ROLES_SELECTION
    await query.answer()

    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    try:
        _, civilians, undercovers, mr_white = query.data.split(":")
        civilians = int(civilians)
        undercovers = int(undercovers)
        mr_white = int(mr_white)
    except (ValueError, IndexError):
        await query.edit_message_text("Invalid role selection. Please pick a preset from the keyboard.")
        return ROLES_SELECTION

    if civilians + undercovers + mr_white != session.num_players:
        await query.edit_message_text("The distribution does not match the number of players.")
        return ROLES_SELECTION

    session.assign_roles(civilians, undercovers, mr_white)

    await query.edit_message_text(
        f"Roles assigned! {civilians} Civilians, {undercovers} Undercover(s) and {mr_white} Mr. White.",
    )

    await query.message.reply_text(
        f"Player {session.pending_seats[0]}, please choose a card to determine the turn order.",
        reply_markup=build_card_keyboard(session),
    )
    return SELECTING_CARDS


async def select_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return SELECTING_CARDS
    await query.answer()

    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    try:
        card_value = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("That card could not be processed. Try again.")
        return SELECTING_CARDS

    if card_value not in session.available_cards:
        await query.answer("Card already taken. Pick another one.", show_alert=True)
        return SELECTING_CARDS

    player = session.register_card_choice(card_value)
    await query.edit_message_text(f"Player {player.seat} chose card {card_value}.")

    if session.pending_seats:
        next_player = session.pending_seats[0]
        await query.message.reply_text(
            f"Player {next_player}, choose your card:",
            reply_markup=build_card_keyboard(session),
        )
        return SELECTING_CARDS

    order = session.elimination_queue()
    order_text = ", ".join(
        f"Player {p.seat} (card {p.card})" if p.card is not None else f"Player {p.seat}"
        for p in order
    )
    await query.message.reply_text(f"Elimination order based on cards: {order_text}")
    await query.message.reply_text(
        "Select a player to eliminate:",
        reply_markup=build_elimination_keyboard(session),
    )
    return ELIMINATING


async def handle_elimination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ELIMINATING
    await query.answer()

    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    try:
        seat = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("Invalid selection. Try again.")
        return ELIMINATING

    player = session.players.get(seat)
    if not player or player.eliminated:
        await query.answer("That player is already out.", show_alert=True)
        return ELIMINATING

    session.eliminate(seat)
    await query.edit_message_text(
        f"Player {seat} has been eliminated and was {ROLE_NAMES.get(player.role, 'Unknown')}!"
    )

    outcome = session.outcome()
    if outcome:
        await announce_winner(query, session, outcome)
        context.chat_data.pop("session", None)
        return ConversationHandler.END

    await query.message.reply_text(
        "Select the next player to eliminate:",
        reply_markup=build_elimination_keyboard(session),
    )
    return ELIMINATING


async def announce_winner(query, session: GameSession, outcome: str) -> None:
    message = query.message
    if outcome == "civilians":
        await message.reply_text("All infiltrators have been eliminated. Civilians win this round!")
    else:
        await message.reply_text("Infiltrators now outnumber civilians. Undercover team wins!")

    scoreboard_lines = []
    for seat in sorted(session.players):
        player = session.players[seat]
        player.score = ROLE_POINTS.get(player.role, 0)
        scoreboard_lines.append(
            f"Player {seat}: {ROLE_NAMES.get(player.role, 'Unknown')} - {player.score} point(s)."
        )

    await message.reply_text("Final roles:\n" + "\n".join(scoreboard_lines))
    await message.reply_text("Game over! Use /start to play again or /end to stop the bot.")


async def cancel_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.chat_data.pop("session", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Game cancelled.")
    elif update.message:
        await update.message.reply_text("Game cancelled.")
    return ConversationHandler.END


def main(bot_token) -> None:

    application = ApplicationBuilder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_PLAYERS: [CallbackQueryHandler(select_players, pattern=r"^players:")],
            ROLES_SELECTION: [CallbackQueryHandler(select_roles, pattern=r"^roles:")],
            SELECTING_CARDS: [CallbackQueryHandler(select_card, pattern=r"^card:")],
            ELIMINATING: [CallbackQueryHandler(handle_elimination, pattern=r"^eliminate:")],
        },
        fallbacks=[CommandHandler("end", cancel_game), CommandHandler("cancel", cancel_game)],
        per_chat=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("end", cancel_game))

    application.run_polling()


if __name__ == "__main__":
    main(bot_token)
