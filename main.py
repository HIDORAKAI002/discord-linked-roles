# server.py
# This file runs a web server to handle the Discord Linked Roles connection.

import os
import requests
from flask import Flask, request, jsonify, redirect
import discord
from dotenv import load_dotenv
import threading
import asyncio

# Load environment variables from a .env file for local testing
load_dotenv()

# --- CONFIGURATION ---
# These variables will be loaded from your hosting service's secrets or a .env file.
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')  # e.g., 'https://your-app-name.onrender.com/linked-roles'
SERVER_ID = int(os.getenv('DISCORD_SERVER_ID'))    # The ID of the server where the roles exist

# --- ROLE MAPPING ---
# This is the most important part to configure.
# You MUST replace the numbers on the right with the actual Role IDs from YOUR Discord server.
# To get a Role ID, right-click the role in Server Settings -> Roles and click "Copy Role ID".
# Make sure Developer Mode is enabled in your Discord settings.
#
# The key (e.g., 'mod') MUST EXACTLY MATCH the "Field Name / Key" you set up in the
# Linked Roles metadata section of your Discord Developer Portal.
ROLE_MAPPINGS = {
    'founder': 1400496639680057407,
    'manager': 1400496639680057406,
    'developer': 1400496639675990026,
    'mod': 1400496639675990033,      # moderation team
    'event_host': 1400496639675990028,  # event team
}

# --- DISCORD BOT SETUP ---
# We need a bot to connect to your server and check which roles a user has.
# The 'Server Members Intent' must be enabled for your bot in the Developer Portal.
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)

# This will hold the bot's event loop
bot_loop = None

# --- FLASK WEB SERVER ---
app = Flask(__name__)

# This is the main endpoint that Discord redirects the user to.
@app.route('/linked-roles')
def linked_roles():
    # 1. Get the authorization code from Discord's redirect.
    code = request.args.get('code')
    if not code:
        return "Error: No authorization code provided.", 400

    # 2. Exchange the code for an access token.
    token_url = 'https://discord.com/api/v10/oauth2/token'
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        token_response = requests.post(token_url, data=data, headers=headers)
        token_response.raise_for_status()
        access_token = token_response.json()['access_token']
    except requests.exceptions.RequestException as e:
        print(f"Error exchanging code for token: {e}")
        return "Error communicating with Discord API.", 500

    # 3. Get the user's Discord ID.
    user_info_url = 'https://discord.com/api/v10/users/@me'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        user_response = requests.get(user_info_url, headers=headers)
        user_response.raise_for_status()
        user_id = user_response.json()['id']
    except requests.exceptions.RequestException as e:
        print(f"Error getting user info: {e}")
        return "Error getting user info from Discord.", 500

    # 4. Update the user's metadata based on their roles in your server.
    update_metadata(user_id, access_token)

    # 5. Redirect the user back to their Discord client.
    return redirect('https://discord.com/channels/@me')

# This function uses the bot to look up a user in your server.
async def get_user_roles(user_id):
    """Uses the bot to get a user's roles from the specified server."""
    try:
        guild = client.get_guild(SERVER_ID)
        if not guild:
            print(f"Error: Bot is not in server with ID {SERVER_ID}")
            return []
        
        member = await guild.fetch_member(user_id)
        if not member:
            print(f"Error: Could not find member with ID {user_id} in the server.")
            return []
            
        # Return a list of the user's role IDs
        return [role.id for role in member.roles]
    except discord.errors.NotFound:
        print(f"Error: Member with ID {user_id} not found in guild {SERVER_ID}.")
        return []
    except discord.errors.Forbidden:
        print(f"Error: Bot does not have permissions to fetch member {user_id}.")
        return []
    except Exception as e:
        print(f"An unexpected error occurred in get_user_roles: {e}")
        return []

# This function builds and sends the metadata to Discord.
def update_metadata(user_id, access_token):
    """Calculates and pushes the metadata for a user."""
    url = f'https://discord.com/api/v10/users/@me/applications/{CLIENT_ID}/role-connection'

    # Get the user's current roles from our server using the bot
    future = asyncio.run_coroutine_threadsafe(get_user_roles(user_id), bot_loop)
    user_role_ids = future.result()
    
    # Create the metadata payload based on the user's roles
    metadata = {}
    for key, role_id in ROLE_MAPPINGS.items():
        if role_id in user_role_ids:
            metadata[key] = 1 # 1 means true
        else:
            metadata[key] = 0 # 0 means false

    # As requested: if a user has the 'manager' role, they should NOT get the 'mod' linked role.
    # This assumes 'manager' is a higher-tier role than 'mod'.
    if metadata.get('manager') == 1:
        metadata['mod'] = 0

    # Send the metadata to Discord
    json_data = {
        'platform_name': 'Server Roles', # You can change this name
        'metadata': metadata
    }
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.put(url, json=json_data, headers=headers)
        response.raise_for_status()
        print(f"Successfully updated metadata for user {user_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error updating metadata for user {user_id}: {e}")
        print(f"Response Body: {response.text}")

# --- MAIN EXECUTION ---
# This part runs both the web server and the Discord bot at the same time.
def run_bot():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    client.run(BOT_TOKEN)

if __name__ == "__main__":
    # Start the Discord bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Start the Flask web server
    # Note: For a real hosting service, you would use a production server like Gunicorn,
    # not the built-in Flask development server.
    app.run(host='0.0.0.0', port=10000)
