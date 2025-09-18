"""Telegram bot implementation for running an Undercover style party game.

The original reference bots bundled inside the project relied on the now
deprecated ``Updater`` API from the ``python-telegram-bot`` library.  This
module rebuilds the experience on top of the modern asynchronous
``Application`` interface (v20+) while keeping the full game logic from the
legacy implementation: configurable player names, role distribution, card
selection, word assignment and round based scoring.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import bot_token

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update

from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import Forbidden, TelegramError

# Enable logging so it is easier to debug when the bot is running live.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
(
    SELECTING_PLAYERS,
    NAMING_PLAYERS,
    ROLE_SELECTION,
    CARD_SELECTION,
    ELIMINATION,
    ROUND_END,
) = range(6)

# Default role distributions for the supported number of players.
ROLE_PRESETS: Dict[int, List[tuple[int, int, int]]] = {
    3: [(2, 1, 0), (2, 0, 1)],
    4: [(3, 1, 0), (2, 1, 1)],
    5: [(3, 1, 1), (2, 2, 1)],
    6: [(3, 2, 1), (2, 2, 2)],
    7: [(4, 2, 1), (3, 2, 2)],
    8: [(5, 2, 1), (4, 2, 2)],
    9: [(5, 3, 1), (4, 3, 2)],
    10: [(5, 3, 2), (4, 4, 2)],
}

ROLE_NAMES = {"C": "Civilian", "U": "Undercover", "W": "Mr. White"}
ROLE_POINTS = {"C": 1, "U": 2, "W": 4}

WORDS_LIBRARY = {
    "C": [
        "DOG",
        "ICE CREAM",
        "MEATBALLS",
        "KUNG FU",
        "CAMPING",
        "COCA COLA",
        "CAR",
        "GUITAR",
        "SUNRISE",
        "RIVER",
        "APPLE",
        "TEA",
        "FORK",
        "CHAIR",
        "PIZZA",
        "LAPTOP",
        "HAT",
        "OWL",
        "SNOW",
        "LAKE",
        "OCEAN",
        "ROSE",
        "SKATEBOARD",
        "SOFA",
        "TENNIS",
        "COW",
        "BOOK",
        "BICYCLE",
        "PEN",
        "GLASSES",
        "BANANA",
        "BEACH",
        "WINE",
        "TRAIN",
        "CINEMA",
        "SANDALS",
        "FISH",
        "WINTER",
        "GOLF",
        "PARROT",
        "VOLLEYBALL",
        "TIGER",
        "PAINTING",
        "MOUNTAIN",
        "JAZZ",
        "FOREST",
        "ROCK",
        "CANDLE",
        "KITE",
        "CLOCK",
        "CHOCOLATE",
        "WHISKEY",
        "ELEPHANT",
        "NEWSPAPER",
        "SPOON",
        "RAINBOW",
        "CAMERA",
        "SAILBOAT",
        "GARDEN",
        "CAKE",
        "MONKEY",
        "SCISSORS",
        "POOL",
        "CELLPHONE",
        "ZEBRA",
        "RUGBY",
        "PUMPKIN",
        "COMPUTER",
        "STOVE",
    ],
    "U": [
        "WOLF",
        "YOGHURT",
        "CHICKEN NUGGETS",
        "KARATE",
        "PICNIC",
        "FANTA",
        "TRUCK",
        "VIOLIN",
        "SUNSET",
        "STREAM",
        "PEAR",
        "COFFEE",
        "SPOON",
        "STOOL",
        "BURGER",
        "TABLET",
        "CAP",
        "EAGLE",
        "RAIN",
        "POND",
        "SEA",
        "TULIP",
        "ROLLERBLADES",
        "ARMCHAIR",
        "BADMINTON",
        "BULL",
        "MAGAZINE",
        "MOTORBIKE",
        "PENCIL",
        "SUNGLASSES",
        "MANGO",
        "LAKE",
        "BEER",
        "SUBWAY",
        "THEATRE",
        "FLIP FLOPS",
        "SHARK",
        "SUMMER",
        "BASEBALL",
        "CANARY",
        "SOCCER",
        "LEOPARD",
        "SKETCH",
        "HILL",
        "BLUES",
        "JUNGLE",
        "PEBBLE",
        "LANTERN",
        "BALLOON",
        "WATCH",
        "CANDY",
        "RUM",
        "RHINO",
        "BLOG",
        "FORK",
        "CLOUD",
        "BINOCULARS",
        "YACHT",
        "PARK",
        "PIE",
        "APE",
        "RAZOR",
        "LAKE",
        "SMARTPHONE",
        "HORSE",
        "FOOTBALL",
        "SQUASH",
        "LAPTOP",
        "OVEN",
    ],
}

WORD_PAIRS = list(zip(WORDS_LIBRARY["C"], WORDS_LIBRARY["U"]))


@dataclass
class Player:
    """Stores the state for a single player in the session."""

    seat: int
    name: str = ""
    role: str = ""
    word: str = ""
    eliminated: bool = False
    card: Optional[int] = None
    score: int = 0
    telegram_id: Optional[int] = None


@dataclass
class GameSession:
    """In-memory representation of the current match for a chat."""

    num_players: int
    players: Dict[int, Player] = field(init=False)
    pending_seats: List[int] = field(init=False)
    available_cards: List[int] = field(init=False)
    elimination_log: List[int] = field(default_factory=list)
    role_distribution: Optional[tuple[int, int, int]] = None
    word_pair: Optional[tuple[str, str]] = None
    name_order: List[int] = field(init=False)
    next_name_index: int = 0
    name_prompt_message_id: Optional[int] = None

    def __post_init__(self) -> None:
        self.players = {
            seat: Player(seat=seat, name=f"Player {seat}")
            for seat in range(1, self.num_players + 1)
        }
        self.pending_seats = list(self.players.keys())
        self.available_cards = list(self.players.keys())
        self.name_order = list(self.players.keys())

    # --- helpers for role assignment -------------------------------------------------
    def assign_roles(self, civilians: int, undercovers: int, mr_white: int) -> None:
        self.role_distribution = (civilians, undercovers, mr_white)
        self.elimination_log.clear()
        self.pending_seats = list(self.players.keys())
        self.available_cards = list(self.players.keys())

        for player in self.players.values():
            player.role = ""
            player.word = ""
            player.eliminated = False
            player.card = None

        seats = list(self.players.keys())
        random.shuffle(seats)
        index = 0

        if WORD_PAIRS:
            self.word_pair = random.choice(WORD_PAIRS)
        else:
            self.word_pair = ("", "")
        civilian_word, undercover_word = self.word_pair

        for _ in range(civilians):
            seat = seats[index]
            index += 1
            player = self.players[seat]
            player.role = "C"
            player.word = civilian_word

        for _ in range(undercovers):
            seat = seats[index]
            index += 1
            player = self.players[seat]
            player.role = "U"
            player.word = undercover_word

        for _ in range(mr_white):
            seat = seats[index]
            index += 1
            player = self.players[seat]
            player.role = "W"
            player.word = ""

    # --- helpers for card selection --------------------------------------------------
    def register_card_choice(self, card_value: int, user_id: int) -> Player:
        seat = self.pending_seats.pop(0)
        player = self.players[seat]
        player.card = card_value
        self.available_cards.remove(card_value)
        player.telegram_id = user_id
        return player

    def revert_card_choice(self, player: Player, previous_user: Optional[int]) -> None:
        """Restore the last pending seat and card if a reveal could not be delivered."""

        self.pending_seats.insert(0, player.seat)
        if player.card is not None:
            self.available_cards.append(player.card)
            self.available_cards.sort()
        player.card = None
        player.telegram_id = previous_user

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
        if civilians == 0 or civilians <= infiltrators:
            return "infiltrators"
        return None

    # --- helpers for naming ----------------------------------------------------------
    def current_name_seat(self) -> Optional[int]:
        if self.next_name_index < len(self.name_order):
            return self.name_order[self.next_name_index]
        return None

    def set_current_player_name(self, name: str) -> Optional[Player]:
        seat = self.current_name_seat()
        if seat is None:
            return None
        player = self.players[seat]
        player.name = name
        self.next_name_index += 1
        return player

    def skip_current_player_name(self) -> Optional[Player]:
        seat = self.current_name_seat()
        if seat is None:
            return None
        player = self.players[seat]
        self.next_name_index += 1
        return player

    # --- helpers for scoring ---------------------------------------------------------
    def apply_scores(self, outcome: str) -> None:
        if outcome == "civilians":
            for player in self.players.values():
                if player.role == "C":
                    player.score += ROLE_POINTS["C"]
        else:
            for player in self.players.values():
                if player.role == "U" and not player.eliminated:
                    player.score += ROLE_POINTS["U"]
                elif player.role == "W" and not player.eliminated:
                    player.score += ROLE_POINTS["W"]

    def standings(self) -> List[Player]:
        return sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.seat),
        )

    def scoreboard_lines(self) -> List[str]:
        return [f"{player.name}: {player.score} point(s)" for player in self.standings()]

    def reset_for_next_round(self) -> None:
        if not self.role_distribution:
            raise ValueError("Role distribution not set for this session")
        civilians, undercovers, mr_white = self.role_distribution
        self.assign_roles(civilians, undercovers, mr_white)


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
        [InlineKeyboardButton(player.name, callback_data=f"eliminate:{player.seat}")]
        for player in sorted(session.active_players(), key=lambda p: p.seat)
    ]
    return InlineKeyboardMarkup(buttons)


async def prompt_next_name(message: Message, session: GameSession) -> int:
    seat = session.current_name_seat()
    if seat is None:
        session.name_prompt_message_id = None
        await message.reply_text(
            "All names registered! Choose the role distribution for this round:",
        )
        await message.reply_text(
            "Select one of the distributions below:",
            reply_markup=build_roles_keyboard(session.num_players),
        )
        return ROLE_SELECTION

    player = session.players[seat]
    prompt = await message.reply_text(
        f"Reply to this message with the name for Player {seat} (current: {player.name}). Use /skip to keep it.",
        reply_markup=ForceReply(
            selective=False,
            input_field_placeholder=f"Player {seat} name",
        ),
    )
    session.name_prompt_message_id = prompt.message_id
    return NAMING_PLAYERS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.chat_data.pop("session", None)
    logger.info(
        "Starting new game in chat %s",
        update.effective_chat.id if update.effective_chat else "N/A",
    )
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
        f"Game setup for {num_players} players. Let's set everyone's name.",
    )
    return await prompt_next_name(query.message, session)


async def capture_player_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await update.message.reply_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    chat = update.effective_chat
    if chat and chat.type in {"group", "supergroup"}:
        prompt_id = session.name_prompt_message_id
        if not prompt_id:
            await update.message.reply_text(
                "Please wait for the next naming prompt before sending a name.",
            )
            return NAMING_PLAYERS

        reply = update.message.reply_to_message
        if not reply or reply.message_id != prompt_id:
            await update.message.reply_text(
                "Reply to the bot's latest prompt to register the next player's name.",
            )
            return NAMING_PLAYERS

    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Please send a non-empty name or use /skip to keep the default.")
        return NAMING_PLAYERS

    player = session.set_current_player_name(name)
    if player:
        await update.message.reply_text(f"Seat {player.seat} will play as {player.name}.")
    return await prompt_next_name(update.message, session)


async def skip_player_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await update.message.reply_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    player = session.skip_current_player_name()
    if player:
        await update.message.reply_text(f"Keeping default name {player.name} for seat {player.seat}.")
    return await prompt_next_name(update.message, session)


async def select_roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ROLE_SELECTION
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
        return ROLE_SELECTION

    if civilians + undercovers + mr_white != session.num_players:
        await query.edit_message_text("The distribution does not match the number of players.")
        return ROLE_SELECTION

    session.assign_roles(civilians, undercovers, mr_white)

    await query.edit_message_text(
        f"Roles assigned! {civilians} Civilians, {undercovers} Undercover(s) and {mr_white} Mr. White.",
    )

    next_seat = session.pending_seats[0]
    next_player = session.players[next_seat]
    await query.message.reply_text(
        f"{next_player.name}, please choose a card to determine the order.",
        reply_markup=build_card_keyboard(session),
    )
    return CARD_SELECTION


async def select_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return CARD_SELECTION
    await query.answer()

    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    if not session.pending_seats:
        await query.answer("All cards have already been drawn.", show_alert=True)
        return CARD_SELECTION

    try:
        card_value = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("That card could not be processed. Try again.")
        return CARD_SELECTION

    if card_value not in session.available_cards:
        await query.answer("Card already taken. Pick another one.", show_alert=True)
        return CARD_SELECTION

    seat = session.pending_seats[0]
    player = session.players[seat]

    user_id = query.from_user.id
    if player.telegram_id and player.telegram_id != user_id:
        await query.answer(
            f"It's {player.name}'s turn to draw. Ask them to pick their card.",
            show_alert=True,
        )
        return CARD_SELECTION

    previous_user = player.telegram_id
    player = session.register_card_choice(card_value, user_id)

    proposed_name = player.name
    if player.name.startswith("Player "):
        proposed_name = query.from_user.full_name or player.name

    if player.role == "W":
        dm_lines = [
            f"Hi {query.from_user.first_name or proposed_name}!",
            "You are Mr. White this round.",
            "You received no secret word—listen carefully and improvise!",
        ]
    else:
        dm_lines = [
            f"Hi {query.from_user.first_name or proposed_name}!",
            f"Your secret word is: {player.word}",
            "Keep it to yourself and describe it carefully during the discussion.",
        ]

    try:
        await context.bot.send_message(chat_id=user_id, text="\n".join(dm_lines))
    except Forbidden:
        session.revert_card_choice(player, previous_user)
        await query.answer(
            "I couldn't send you the word. Start a private chat with me and tap the card again.",
            show_alert=True,
        )
        return CARD_SELECTION
    except TelegramError as exc:
        session.revert_card_choice(player, previous_user)
        logger.exception("Failed to send secret word to user %s", user_id, exc_info=exc)
        await query.answer(
            "Something went wrong while sending your word. Please try again.",
            show_alert=True,
        )
        return CARD_SELECTION

    player.name = proposed_name

    await query.edit_message_text(
        f"{player.name} drew card {card_value}. Check your private messages!",
    )

    if session.pending_seats:
        next_seat = session.pending_seats[0]
        next_player = session.players[next_seat]
        await query.message.reply_text(
            f"{next_player.name}, choose your card:",
            reply_markup=build_card_keyboard(session),
        )
        return CARD_SELECTION

    order_text = ", ".join(
        f"{session.players[seat].name} (card {session.players[seat].card})"
        for seat in sorted(session.players.keys(), key=lambda s: session.players[s].card or 0)
    )
    await query.message.reply_text(f"Speaking order based on cards: {order_text}")
    await query.message.reply_text(
        "Select a player to eliminate:",
        reply_markup=build_elimination_keyboard(session),
    )
    return ELIMINATION


async def handle_elimination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ELIMINATION
    await query.answer()

    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    try:
        seat = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.edit_message_text("Invalid selection. Try again.")
        return ELIMINATION

    player = session.players.get(seat)
    if not player or player.eliminated:
        await query.answer("That player is already out.", show_alert=True)
        return ELIMINATION

    session.eliminate(seat)
    await query.edit_message_text(
        f"{player.name} has been eliminated and was {ROLE_NAMES.get(player.role, 'Unknown')}!",
    )

    outcome = session.outcome()
    if outcome:
        return await finalize_round(query, session, outcome)

    await query.message.reply_text(
        "Select the next player to eliminate:",
        reply_markup=build_elimination_keyboard(session),
    )
    return ELIMINATION


async def finalize_round(query, session: GameSession, outcome: str) -> int:
    if outcome == "civilians":
        await query.message.reply_text("All infiltrators have been eliminated. Civilians win this round!")
    else:
        await query.message.reply_text("Infiltrators now outnumber civilians. Undercover team wins!")

    session.apply_scores(outcome)
    scoreboard = session.scoreboard_lines()
    await query.message.reply_text("Current standings:\n" + "\n".join(scoreboard))

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Next round", callback_data="round:continue")],
            [InlineKeyboardButton("End game", callback_data="round:end")],
        ]
    )
    await query.message.reply_text(
        "Do you want to play another round with the same players?",
        reply_markup=keyboard,
    )
    return ROUND_END


async def handle_round_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ROUND_END
    await query.answer()

    session: Optional[GameSession] = context.chat_data.get("session")
    if not session:
        await query.edit_message_text("Game session not found. Start a new game with /start.")
        return ConversationHandler.END

    _, action = query.data.split(":", 1)
    if action == "continue":
        session.reset_for_next_round()
        await query.edit_message_text("Starting the next round!")
        if session.role_distribution:
            civ, und, white = session.role_distribution
            await query.message.reply_text(
                f"Roles reassigned! {civ} Civilians, {und} Undercover(s), {white} Mr. White.",
            )
        next_seat = session.pending_seats[0]
        next_player = session.players[next_seat]
        await query.message.reply_text(
            f"{next_player.name}, please choose a card to determine the order.",
            reply_markup=build_card_keyboard(session),
        )
        return CARD_SELECTION

    await query.edit_message_text("Game over! Thanks for playing.")
    scoreboard = session.scoreboard_lines()
    if scoreboard:
        await query.message.reply_text("Final standings:\n" + "\n".join(scoreboard))
    context.chat_data.pop("session", None)
    await query.message.reply_text("Use /start to begin a new game at any time.")
    return ConversationHandler.END


async def cancel_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = context.chat_data.pop("session", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Game cancelled.")
    elif update.message:
        await update.message.reply_text("Game cancelled.")

    if session:
        scoreboard = session.scoreboard_lines()
        if scoreboard and update.effective_message:
            await update.effective_message.reply_text(
                "Standings before cancellation:\n" + "\n".join(scoreboard)
            )
    return ConversationHandler.END


def main(bot_token: str) -> None:
    application = ApplicationBuilder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_PLAYERS: [CallbackQueryHandler(select_players, pattern=r"^players:")],
            NAMING_PLAYERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, capture_player_name),
                CommandHandler("skip", skip_player_name),
            ],
            ROLE_SELECTION: [CallbackQueryHandler(select_roles, pattern=r"^roles:")],
            CARD_SELECTION: [CallbackQueryHandler(select_card, pattern=r"^card:")],
            ELIMINATION: [CallbackQueryHandler(handle_elimination, pattern=r"^eliminate:")],
            ROUND_END: [CallbackQueryHandler(handle_round_end, pattern=r"^round:")],
        },
        fallbacks=[CommandHandler("end", cancel_game), CommandHandler("cancel", cancel_game)],
        per_chat=True,
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("end", cancel_game))

    application.run_polling()


if __name__ == "__main__":
    main(bot_token)
