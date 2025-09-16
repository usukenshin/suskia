import logging
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler, ConversationHandler

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# States for the conversation
SELECTING_PLAYERS, ROLES_SELECTION, SELECTING_CARDS, ELIMINATING, GAME_OVER = range(5)

# Global variables to store game data
num_players = 0
player_dict = {}
player_order = []
words_library = {
    'C': ['DOG'],  # Add more civilian words as needed
    'U': ['WOLF'],  # Add more undercover words as needed
}


def start(update: Update, context: CallbackContext) -> int:
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(3, 11)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("How many players? (3-10)", reply_markup=reply_markup)

    return SELECTING_PLAYERS


def select_players(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    global num_players
    num_players = int(query.data)

    if num_players < 3 or num_players > 10:
        query.message.reply_text("Invalid number of players.")
        return SELECTING_PLAYERS

    # Create entries for each player in the dictionary
    for i in range(1, num_players + 1):
        player_dict[i] = {'name': '', 'role': '', 'word': '', 'eliminated': False, 'score': 0}

    # Move to the roles selection state
    query.message.reply_text("How do you want to distribute the roles?", reply_markup=get_roles_keyboard(num_players))

    return ROLES_SELECTION


def get_roles_keyboard(num_players):
    if num_players == 3:
        keyboard = [
            [InlineKeyboardButton("2 C, 1 U, 0 W", callback_data="2C1U0W")],
            [InlineKeyboardButton("2 C, 0 U, 1 W", callback_data="2C0U1W")],
        ]
    # Implement the rest of the role distributions here based on num_players
    # ...

    return InlineKeyboardMarkup(keyboard)


def select_roles(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    roles = query.data
    num_civilians = int(roles[0])
    num_undercovers = int(roles[2])
    num_mr_white = int(roles[4])

    if num_civilians + num_undercovers + num_mr_white != num_players:
        query.message.reply_text("Invalid role distribution.")
        return ROLES_SELECTION

    # Assign roles to players randomly
    players = list(range(1, num_players + 1))
    random.shuffle(players)
    for i in range(num_civilians):
        player_dict[players[i]]['role'] = 'C'
    for i in range(num_civilians, num_civilians + num_undercovers):
        player_dict[players[i]]['role'] = 'U'
    for i in range(num_civilians + num_undercovers, num_civilians + num_undercovers + num_mr_white):
        player_dict[players[i]]['role'] = 'W'

    # Create player order for elimination
    global player_order
    player_order = players.copy()
    player_order.remove(players[num_civilians + num_undercovers + num_mr_white - 1])
    player_order.insert(1, players[num_civilians + num_undercovers + num_mr_white - 1])

    # Move to the selecting cards state
    query.message.reply_text(f"Playing a game with {num_civilians} C, {num_undercovers} U, {num_mr_white} W")
    context.user_data['current_player'] = 0
    show_card_keyboard(update, context)

    return SELECTING_CARDS


def show_card_keyboard(update: Update, context: CallbackContext):
    context.user_data['current_player'] += 1
    current_player = context.user_data['current_player']

    # Filter out already chosen cards from the keyboard
    available_cards = list(range(1, num_players + 1))
    for player in player_dict.values():
        if player['role'] != '':  # Skip players who have already chosen a card
            available_cards.remove(player['card'])

    keyboard = [
        [InlineKeyboardButton(str(card), callback_data=str(card)) for card in available_cards]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(f"Player {current_player}, choose your card:", reply_markup=reply_markup)


def select_card(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    card = int(query.data)
    current_player = context.user_data['current_player']

    # Store the selected card for the current player
    player_dict[current_player]['card'] = card

    # Move to the next player or start elimination if all players have chosen a card
    if len([player for player in player_dict.values() if player['card'] == 0]) == 0:
        query.message.reply_text(f"The order of players for elimination: {', '.join([str(player_order[i]) for i in range(1, len(player_order))])}.")
        eliminate_player(update, context)
    else:
        show_card_keyboard(update, context)
        return SELECTING_CARDS


def eliminate_player(update: Update, context: CallbackContext):
    # Show a keyboard with remaining active players to eliminate
    remaining_players = [player for player in player_dict.values() if not player['eliminated']]
    keyboard = [
        [InlineKeyboardButton(f"Player {player['id']}", callback_data=str(player['id']))] for player in remaining_players
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Select a player to eliminate:", reply_markup=reply_markup)

    return ELIMINATING


def handle_elimination(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    player_id = int(query.data)

    # Eliminate the selected player
    player_dict[player_id]['eliminated'] = True

    # Check if all infiltrators (undercover or mr white) have been eliminated
    infiltrators_remaining = len([player for player in player_dict.values() if
                                  not player['eliminated'] and player['role'] in ('U', 'W')])
    civilians_remaining = len([player for player in player_dict.values() if
                               not player['eliminated'] and player['role'] == 'C'])
    mr_white_remaining = len([player for player in player_dict.values() if
                              not player['eliminated'] and player['role'] == 'W'])

    if mr_white_remaining == 0:
        # Mr. White is eliminated, civilians win
        query.message.reply_text("Mr. White has been eliminated. Civilians win this round!")
    elif infiltrators_remaining == 0:
        # All infiltrators are eliminated, civilians win
        query.message.reply_text("All infiltrators have been eliminated. Civilians win this round!")
    else:
        # There are remaining infiltrators, continue the elimination
        eliminate_player(update, context)

    return SELECTING_CARDS


def end_game(update: Update, context: CallbackContext) -> int:
    # Calculate and display the standings
    standings = []
    for player in player_dict.values():
        if player['role'] == 'C':
            player['score'] += 1
        elif player['role'] == 'U':
            player['score'] += 2
        elif player['role'] == 'W':
            player['score'] += 4
        standings.append(f"Player {player['id']}: {player['score']} points")

    query.message.reply_text("\n".join(standings))
    query.message.reply_text("The game is over. Do you want to continue or end?")

    return GAME_OVER


def main():
    # Set up the Telegram Bot token
    bot_token = "YOUR_BOT_TOKEN"

    updater = Updater(bot_token)
    dp = updater.dispatcher

    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECTING_PLAYERS: [CallbackQueryHandler(select_players)],
            ROLES_SELECTION: [CallbackQueryHandler(select_roles)],
            SELECTING_CARDS: [CallbackQueryHandler(show_card_keyboard),
                              CallbackQueryHandler(select_card)],
            ELIMINATING: [CallbackQueryHandler(handle_elimination)],
            GAME_OVER: [MessageHandler(Filters.text & ~Filters.command, end_game)],
        },
        fallbacks=[CommandHandler('end', end_game)],
    )
    dp.add_handler(conv_handler)

    # Start the Bot
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
