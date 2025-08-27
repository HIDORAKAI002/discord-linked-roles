# main.py
# This file runs a web server to handle the Discord Linked Roles connection.

import os
import requests
from flask import Flask, request, jsonify, redirect
import discord
from dotenv import load_dotenv
import threading
import asyncio

# --- CONFIGURATION ---
# These variables will be loaded from your hosting service's secrets.
CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')
SERVER_ID = int(os.getenv('DISCORD_SERVER_ID'))

# --- ROLE MAPPING ---
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
# The 'Server Members Intent' must be enabled for your bot in the Developer Portal.
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
bot_loop = None

# --- FLASK WEB SERVER ---
app = Flask(__name__)

@app.route('/callback') # <--- THIS IS THE ONLY LINE THAT HAS CHANGED
def callback():
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

def update_metadata(user_id, access_token):
    """Calculates and pushes the metadata for a user."""
    url = f'https://discord.com/api/v10/users/@me/applications/{CLIENT_ID}/role-connection'

    future = asyncio.run_coroutine_threadsafe(get_user_roles(user_id), bot_loop)
    user_role_ids = future.result()
    
    metadata = {}
    for key, role_id in ROLE_MAPPINGS.items():
        if role_id in user_role_ids:
            metadata[key] = 1
        else:
            metadata[key] = 0

    if metadata.get('manager') == 1:
        metadata['mod'] = 0

    json_data = {
        'platform_name': 'Server Roles',
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

def run_bot():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    client.run(BOT_TOKEN)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    app.run(host='0.0.0.0', port=10000)
