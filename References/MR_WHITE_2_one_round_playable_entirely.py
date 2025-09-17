import logging
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ForceReply, Message
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler, ConversationHandler, MessageHandler

from config import bot_token

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# States for the conversation
SELECT_PLAYERS, SELECT_ROLES, SELECTING_CARDS, P_HAS_CARD, HANDLE_ELIMINATION, GAME_OVER, ASK_NAME, ADD_NAME, NAME_DEFAULT, SELECT_CARD, END_ROUND, END_GAME = range(12)

# Global variables to store game data
global first_pass
first_pass = True
global available_cards
global standings
standings = []
global num_civilians
global num_undercovers
global num_mr_white
global sequence
global num_players
global chosen_word_pair
chosen_word_pair = {'C': None, 'U': None}
num_players = 0
player_dict = {}
player_order = []
selected_cards = []
words_library = {
    'C': [
        'DOG', 'ICE CREAM', 'MEATBALLS', 'KUNG FU', 'CAMPING', 'COCA COLA',
        'CAR', 'GUITAR', 'SUNRISE', 'RIVER', 'APPLE', 'TEA', 'FORK', 'CHAIR',
        'PIZZA', 'LAPTOP', 'HAT', 'OWL', 'SNOW', 'LAKE', 'OCEAN', 'ROSE',
        'SKATEBOARD', 'SOFA', 'TENNIS', 'COW', 'BOOK', 'BICYCLE', 'PEN',
        'GLASSES', 'BANANA', 'BEACH', 'WINE', 'TRAIN', 'CINEMA', 'SANDALS',
        'FISH', 'WINTER', 'GOLF', 'PARROT', 'VOLLEYBALL', 'TIGER', 'PAINTING',
        'MOUNTAIN', 'JAZZ', 'FOREST', 'ROCK', 'CANDLE', 'KITE', 'CLOCK',
        'CHOCOLATE', 'WHISKEY', 'ELEPHANT', 'NEWSPAPER', 'SPOON', 'RAINBOW',
        'CAMERA', 'SAILBOAT', 'GARDEN', 'CAKE', 'MONKEY', 'SCISSORS', 'POOL',
        'CELLPHONE', 'ZEBRA', 'RUGBY', 'PUMPKIN', 'COMPUTER', 'STOVE'
    ],
    'U': [
        'WOLF', 'YOGHURT', 'CHICKEN NUGGETS', 'KARATE', 'PICNIC', 'FANTA',
        'TRUCK', 'VIOLIN', 'SUNSET', 'STREAM', 'PEAR', 'COFFEE', 'SPOON', 'STOOL',
        'BURGER', 'TABLET', 'CAP', 'EAGLE', 'RAIN', 'POND', 'SEA', 'TULIP',
        'ROLLERBLADES', 'ARMCHAIR', 'BADMINTON', 'BULL', 'MAGAZINE', 'MOTORBIKE',
        'PENCIL', 'SUNGLASSES', 'MANGO', 'LAKE', 'BEER', 'SUBWAY', 'THEATRE',
        'FLIP FLOPS', 'SHARK', 'SUMMER', 'BASEBALL', 'CANARY', 'SOCCER',
        'LEOPARD', 'SKETCH', 'HILL', 'BLUES', 'JUNGLE', 'PEBBLE', 'LANTERN',
        'BALLOON', 'WATCH', 'CANDY', 'RUM', 'RHINO', 'BLOG', 'FORK', 'CLOUD',
        'BINOCULARS', 'YACHT', 'PARK', 'PIE', 'APE', 'RAZOR', 'LAKE',
        'SMARTPHONE', 'HORSE', 'FOOTBALL', 'SQUASH', 'LAPTOP', 'OVEN'
    ]
}

def start(update: Update, context: CallbackContext) -> int:
    print(f'initiated bot, update=  context= ')
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=str(i)) for i in range(3, 11)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("How many players? (3-10)", reply_markup=reply_markup)
    print(f'Asking player amount, update= ')
    return SELECT_PLAYERS

def select_players(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    global num_players
    global player_dict
    global available_cards
    num_players = int(query.data)
    available_cards = list(range(1, num_players + 1))
    print(f"logged amount of players at {num_players}")

    # Create entries for each player in the dictionary
    for i in range(1, num_players + 1):
        player_dict[i] = {'name': '', 'role': '', 'card': 0, 'word': '', 'eliminated': False, 'score': 0}
    context.user_data['current_player'] = 1

    # Move to the roles selection state
    query.message.reply_text("How do you want to distribute the roles?", reply_markup=get_roles_keyboard(num_players))
    print("asking about distribution")

    return SELECT_ROLES

def get_roles_keyboard(num_players):
    if num_players == 3:
        keyboard = [
            [InlineKeyboardButton("2C, 1U, 0W", callback_data="2C1U0W")],
            [InlineKeyboardButton("2C, 0U, 1W", callback_data="2C0U1W")],
        ]
    elif num_players == 4:
        keyboard = [
            [InlineKeyboardButton("3C, 1U, 0W", callback_data="3C1U0W")],
            [InlineKeyboardButton("2C, 1U, 1W", callback_data="2C1U1W")],
        ]
    elif num_players == 5:
        keyboard = [
            [InlineKeyboardButton("3C, 1U, 1W", callback_data="3C1U1W")],
            [InlineKeyboardButton("2C, 2U, 1W", callback_data="2C2U1W")],
        ]
    elif num_players == 6:
        keyboard = [
            [InlineKeyboardButton("3C, 2U, 1W", callback_data="3C2U1W")],
            [InlineKeyboardButton("2C, 2U, 2W", callback_data="2C2U2W")],
        ]
    elif num_players == 7:
        keyboard = [
            [InlineKeyboardButton("4C, 2U, 1W", callback_data="4C2U1W")],
            [InlineKeyboardButton("3C, 2U, 2W", callback_data="3C2U2W")],
        ]
    elif num_players == 8:
        keyboard = [
            [InlineKeyboardButton("5C, 2U, 1W", callback_data="5C2U1W")],
            [InlineKeyboardButton("4C, 2U, 2W", callback_data="4C2U2W")],
        ]
    elif num_players == 9:
        keyboard = [
            [InlineKeyboardButton("5C, 3U, 1W", callback_data="5C3U1W")],
            [InlineKeyboardButton("4C, 3U, 2W", callback_data="4C3U2W")],
        ]
    elif num_players == 10:
        keyboard = [
            [InlineKeyboardButton("5C, 3U, 2W", callback_data="5C3U2W")],
            [InlineKeyboardButton("4C, 4U, 2W", callback_data="4C4U2W")],
        ]
    else:
        # Invalid number of players, return to the start
        query.message.reply_text("Invalid number of players.")
        return SELECT_PLAYERS

    # Implement the rest of the role distributions here based on num_players
    # ...

    return InlineKeyboardMarkup(keyboard)

def select_roles(update: Update, context: CallbackContext) -> int:
    global num_civilians
    global num_players
    global num_undercovers
    global num_mr_white
    global sequence
    query = update.callback_query
    roles = query.data
    print(f"logged roles as {query.data}")
    num_civilians = int(roles[0])
    num_undercovers = int(roles[2])
    num_mr_white = int(roles[4])

    # Assign roles to players randomly
    players = list(range(1, num_players + 1))
    random.shuffle(players)
    for i in range(num_civilians):
        player_dict[players[i]]['role'] = 'C'
    for i in range(num_civilians, num_civilians + num_undercovers):
        player_dict[players[i]]['role'] = 'U'
    for i in range(num_civilians + num_undercovers, num_civilians + num_undercovers + num_mr_white):
        player_dict[players[i]]['role'] = 'W'

    # Convert the player_dict values to a list so we can manipulate the order
    players_list = list(player_dict.values())
    print(f"players list{players_list}")

    # Find the index of the player with role 'W'
    index_w = next((i for i, player in enumerate(players_list) if player['role'] == 'W'), None)
    print(f"index_W{index_w}")
    if index_w == None:
        index_w = next((i for i, player in enumerate(players_list) if player['role'] == 'U'), None)
    if index_w is not None:
        # Determine the number of positions to move down based on the number of players
        max_shift = num_players - 1  # No restrictions other than not being the first one
        print(f"max shift at {num_players} players is {max_shift} positions")
        shift = random.randint(1, max_shift)
        print(f"after random, true shift is {shift}")

        # Rotate the list so that 'W' is shifted down by 'shift' positions
        new_start_index = (index_w + shift) % num_players
        reordered_players = players_list[new_start_index:] + players_list[:new_start_index]

        # Generate a sequence of player names
        sequence = [player['name'] for player in reordered_players]
        print("Player sequence:", sequence)

    # Create player order for elimination
    global player_order
    print(f"player order: {players}")
    player_order = players.copy()
    player_order.remove(players[num_civilians + num_undercovers + num_mr_white - shift])
    print(f"player order.remove: {player_order}")
    player_order.insert(shift, players[num_civilians + num_undercovers + num_mr_white - shift])
    print(f"player_order.insert{player_order}")

    # Move to the selecting cards state
    query.message.reply_text(f"Playing a game with {num_civilians} C, {num_undercovers} U, {num_mr_white} W")
    context.user_data['next_player'] = 1
    print(context.user_data)
    show_card_keyboard(update, context)

    return SELECTING_CARDS

def show_card_keyboard(update: Update, context: CallbackContext):
    print("show_card_keyboard")
    query = update.callback_query
    current_player = context.user_data['next_player']
    context.user_data['current_player'] = current_player
    print(f"a round for our dear player ")
    if query:
        print(f"lol current query data is {query.data}")
    print(f"lol current player_dict is {player_dict}")
    if player_dict[current_player]['name'] == '':
        print("Oh-oh mr noname")
        keyboard = [
            [InlineKeyboardButton(f"Player {current_player}", callback_data="/name_default")],
            [InlineKeyboardButton("Add name", callback_data="/add_name")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.reply_text(f'Player {current_player}, how do you want to be called ?', reply_markup=reply_markup)
        query = update.callback_query
        if query.data == "/name_default":
            print(f"adding default Player name Player{current_player}")
            query.message.reply_text(f'Player {current_player}, keep default name ?', reply_markup=reply_markup)
            player_id = context.user_data['current_player']
            player_name = f"Player {current_player}"
            player_dict[player_id]['name'] = player_name
            show_card_keyboard(update, context)
            return SELECTING_CARDS
            #return NAME_DEFAULT
        elif query.data == "/add_name":
            print(f"adding custom Player name for Player{current_player}")
            query.message.reply_text("Please enter the game you want to use:", reply_markup = ForceReply(selective=True))  
            #add_name(update, context)
            return ADD_NAME
        #return ASK_NAME
    elif first_pass == False:
        return SELECT_CARD
    else:
        print("Great, checking if mr yesname has his cards")
        p_has_card(update, context)
        return P_HAS_CARD

def ask_name(update: Update, _: CallbackContext) -> int:
    print('asking name')
    update.callback_query.message.reply_text("Please enter the name you want to add:", reply_markup = ForceReply(selective=True))
    add_name(update, Message)  
    return ADD_NAME

def name_default(update: Update, context: CallbackContext):
    print("name_default")
    player_id = context.user_data['current_player']
    print(f"Player {player_id} shall henceforth be knowneth as:")
    update.message.text = f"Player {player_id}"
    player_name = update.message.text
    print(player_name)
    #player_dict[current_player]['name'] = f"Player {current_player}"
    player_dict[player_id]['name'] = player_name
    print("returning to see if there is a name now")
    # Proceed to card selection after name input
    show_card_keyboard(update, context)
    return SELECTING_CARDS

def add_name(update: Update, context: CallbackContext):
    print("adding any name other than kevin")
    # Handle name input and store it in the player dictionary
    player_id = context.user_data['current_player']
    print(f"player {player_id} shall henceforth be knowneth as:")
    player_name = update.message.text#.strip()
    print(player_name)
    player_dict[player_id]['name'] = player_name
    print("returning to see if there is a name now")
    # Proceed to card selection after name input
    show_card_keyboard(update, context)
    return SELECTING_CARDS

def p_has_card(update: Update, context: CallbackContext):
    global first_pass
    global available_cards
    print("p_has_card")
    print(f'first_pass = {first_pass}')
    query = update.callback_query
    print("so we are here to see if there is a card and the query states:")
    print(f"and the update")
    current_player = context.user_data['current_player']
    if player_dict[current_player]['card'] != 0:
        print("player has a card and word already")
        context.user_data['next_player'] = current_player + 1
        show_card_keyboard(update, context)
        return SELECTING_CARDS
    elif first_pass == True:
        first_pass = False
        message = update.message
        print(f"and the message is great and loud: {message}")
        print("player doesnt have a card and word")
        print(f"available cards = {available_cards}")
        keyboard = [
              [InlineKeyboardButton(str(card), callback_data=str(card)) for card in available_cards]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if message is not None:
            message.reply_text(f"Player {player_dict[current_player]['name']}, choose your card:", reply_markup=reply_markup)
        else:
            query.message.reply_text(f"Player {player_dict[current_player]['name']}, choose your card:", reply_markup=reply_markup)
        print("returning SELECT_CARD from elif first_pass == True")
        return SELECT_CARD
    print("returning SELECT_CARD from elif p_has_card")
    return SELECT_CARD

def select_card(update: Update, context: CallbackContext) -> int:
    global sequence
    global available_cards
    print("select_card")
    #print(update)
    query = update.callback_query
    card = int(query.data)
    current_player = context.user_data['current_player']
    print(f"{current_player} chose {card}")

    # Store the selected card for the current player
    player_dict[current_player]['card'] = card
    selected_cards.append(card)
    print(selected_cards)
    available_cards.remove(card)
    print (f"available cards= {available_cards}")

    # Inform the player of their role and associated word
    role = player_dict[current_player]['role']
    global chosen_word_pair  # Declare chosen_word_pair as global to modify it

    if role == 'C' or role == 'U':
        if chosen_word_pair['C'] is None:  # If no word has been chosen yet
            # Randomly select a new word pair
            index = random.randint(0, len(words_library['C']) - 1)
            chosen_word_pair['C'] = words_library['C'][index]
            chosen_word_pair['U'] = words_library['U'][index]
        word = chosen_word_pair[role]
    else:
        word = "not, because you're Mr. White"  # Mr. White gets no word
    '''if role == 'C':
        word = random.choice(words_library['C'])
    elif role == 'U':
        word = random.choice(words_library['U'])
    else:
        word = "not, because you're Mr. White"  # Mr. White gets no word'''
    player_dict[current_player]['word'] = word
    query.message.reply_text(f"{player_dict[current_player]['name']}, your word is {word}")
    print(f'current = {current_player}')
    print(context.user_data)
    context.user_data['next_player'] += 1
    print(f'current = {current_player}')
    print(context.user_data)
    global first_pass
    first_pass = True

    # Move to the next player or start elimination if all players have chosen a card
    if len([player for player in player_dict.values() if player['card'] == 0]) == 0:
        print("Gaslight eachother")
         # Display the order in which players describe their word
        # Convert the player_dict values to a list so we can manipulate the order
        players_list = list(player_dict.values())
        print(f"players list{players_list}")

        # Find the index of the player with role 'W'
        index_w = next((i for i, player in enumerate(players_list) if player['role'] == 'W'), None)
        print(f"index_W{index_w}")
        if index_w == None:
            index_w = next((i for i, player in enumerate(players_list) if player['role'] == 'U'), None)
        if index_w is not None:
            # Determine the number of positions to move down based on the number of players
            max_shift = num_players - 1  # No restrictions other than not being the first one
            print(f"max shift at {num_players} players is {max_shift} positions")
            shift = random.randint(1, max_shift)
            print(f"after random, true shift is {shift}")

            # Rotate the list so that 'W' is shifted down by 'shift' positions
            new_start_index = (index_w + shift) % num_players
            reordered_players = players_list[new_start_index:] + players_list[:new_start_index]

            # Generate a sequence of player names
            sequence = [player['name'] for player in reordered_players]
            print("Player sequence:", sequence)
            query.message.reply_text(f"The order of players talking: {sequence}")

        eliminate_player(update, context)
        return HANDLE_ELIMINATION
    else:
        show_card_keyboard(update, context)
        return SELECTING_CARDS

def eliminate_player(update: Update, context: CallbackContext):
    query = update.callback_query

    # Show a keyboard with remaining active players to eliminate
    remaining_players = [player for player in player_dict.values() if not player['eliminated']]
    keyboard = [
        [InlineKeyboardButton(f"{player['name']}", callback_data=str(player['name']))] for player in remaining_players
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.message.reply_text("Select a player to eliminate:", reply_markup=reply_markup)

    return HANDLE_ELIMINATION

def handle_elimination(update: Update, context: CallbackContext): #-> int:
    query = update.callback_query
    player_name = query.data

    # Find the corresponding player_id for the given player_name
    player_id = None
    for id_, player in player_dict.items():
        if player['name'] == player_name:
            player_id = id_
            break

    # Eliminate the selected player
    player_dict[player_id]['eliminated'] = True

    # Communicate elimination 
    if player_dict[player_id]['role'] == 'C':
        query.message.reply_text("A civilian has been eliminated")
    if player_dict[player_id]['role'] == 'U':
        query.message.reply_text("An undercover has been eliminated")
    if player_dict[player_id]['role'] == 'W':
        query.message.reply_text("Mr. White has been eliminated")

    # Check if all infiltrators (undercover or mr white) have been eliminated
    infiltrators_remaining = len([player for player in player_dict.values() if
                                  not player['eliminated'] and player['role'] in ('U', 'W')])
    civilians_remaining = len([player for player in player_dict.values() if
                               not player['eliminated'] and player['role'] == 'C'])
    mr_white_remaining = len([player for player in player_dict.values() if
                              not player['eliminated'] and player['role'] == 'W'])

    if mr_white_remaining == 0 and infiltrators_remaining > 0:
        # Mr. White is eliminated, civilians win
        query.message.reply_text("Mr. White has been eliminated. But infiltrators remain.")
        eliminate_player(update, context)
    elif infiltrators_remaining == 0:
        # All infiltrators are eliminated, civilians win
        query.message.reply_text("All infiltrators have been eliminated. Civilians win this round!")
        for player in player_dict.values():
            if player['role'] == 'C':
                player['score'] += 1
            elif player['role'] == 'U':
                player['score'] += 0
            elif player['role'] == 'W':
                player['score'] += 0
        end_round(update, context)
        return END_ROUND
    elif civilians_remaining == 0:
        query.message.reply_text("All civilians have been eliminated. Infiltrators win this round!")
        for player in player_dict.values():
            if player['role'] == 'C':
                player['score'] += 0
            elif player['role'] == 'U' and not player['eliminated'] == True:
                player['score'] += 2
            elif player['role'] == 'W' and not player['eliminated'] == True:
                player['score'] += 4
        end_round(update, context)
        return END_ROUND
    elif mr_white_remaining == 0 and civilians_remaining == 0 and infiltrators_remaining > 0:
        query.message.reply_text("All civilians have been eliminated. Undercovers win this round!")
        end_round(update, context)
        return END_ROUND
    else:
        # There are remaining infiltrators, continue the elimination
        eliminate_player(update, context)

def end_round(update: Update, context: CallbackContext):
    print("end_round")
    global standings
    query = update.callback_query
    # Calculate and display the standings
    for player_id in player_dict.keys():
        name = player_dict[player_id]['name']
        score = player_dict[player_id]['score']
        standings.append(f"{name}: {score} points")
    print(f"bare standings:\n {standings}")
    # Sort players by score in descending order
    sorted_players = sorted(player_dict.items(), key=lambda x: x[1]['score'], reverse=True)
    sorted_standings = []
    for player_id, player_info in sorted_players:
        name = player_info['name']
        score = player_info['score']
        sorted_standings.append(f"{name}: {score} points")
    print(f"sorted standings :\n {standings}")
    # To print or further manipulate 'standings'
    print(standings)
    query.message.reply_text("\n".join(sorted_standings))

    keyboard = [
        [InlineKeyboardButton("Next Round", callback_data="Yes")],
        [InlineKeyboardButton("End Game", callback_data="No")],
            ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    query.message.reply_text("The round is over. Do you want to continue or end?", reply_markup=reply_markup)
    end_game(update, context)
    return END_GAME

def end_game(update: Update, context: CallbackContext):
    print("end_game")
    # Calculate and display the standings
    global num_civilians
    global num_undercovers
    global num_mr_white
    query = update.callback_query
    if query == "Yes":
        print("yey")
        for players[i], player_info in player_dict.items():
            player_info['role'] = None
            player_info['card'] = 0
            player_info['word'] = None
        # Assign roles to players randomly
        players = list(range(1, num_players + 1))
        random.shuffle(players)
        for i in range(num_civilians):
            player_dict[players[i]]['role'] = 'C'
        for i in range(num_civilians, num_civilians + num_undercovers):
            player_dict[players[i]]['role'] = 'U'
        for i in range(num_civilians + num_undercovers, num_civilians + num_undercovers + num_mr_white):
            player_dict[players[i]]['role'] = 'W'
        return SELECTING_CARDS
    if query == "No":
        print("bye")
        query.message.reply_text("GAME OVER")
        start
        return SELECT_PLAYERS

def main(bot_token):
    # Set up the Telegram Bot token

    updater = Updater(bot_token)
    dp = updater.dispatcher

    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_PLAYERS: [CallbackQueryHandler(select_players)],
            SELECT_ROLES: [CallbackQueryHandler(select_roles)],
            SELECT_CARD: [CallbackQueryHandler(select_card)],
            SELECTING_CARDS: [CallbackQueryHandler(show_card_keyboard)],
            P_HAS_CARD: [CallbackQueryHandler(p_has_card)],
            HANDLE_ELIMINATION: [CallbackQueryHandler(handle_elimination), CallbackQueryHandler(handle_elimination)],
            #GAME_OVER: [MessageHandler(Filters.text & ~Filters.command, end_game)],
            #SELECTING_NAME: [CallbackQueryHandler(handle_name_input)],
            ASK_NAME: [CommandHandler('add_name', ask_name)],
            NAME_DEFAULT: [CommandHandler('name_default', name_default)],
            ADD_NAME: [MessageHandler(Filters.text, add_name)],
            #    CommandHandler('addname', add_name),
            #    MessageHandler(Filters.text & ~Filters.command, handle_name_input),],
            #SELECTING_NAME: [MessageHandler(Filters.text & ~Filters.command, handle_name_input)],
            END_ROUND: [CallbackQueryHandler(end_round)],
            END_GAME: [CallbackQueryHandler(end_game)],
        },
        fallbacks=[CommandHandler('end', end_game)],
        per_message=False,
    )
    dp.add_handler(conv_handler)

    # Start the Bot
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main(bot_token)
