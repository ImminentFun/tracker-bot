import discord
from discord.ext import commands
from discord import EventStatus
from discord.ui import Button, View

import time
import datetime

import asyncio

import gspread
from google.oauth2.service_account import Credentials

import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up intents
intents = discord.Intents.default()
intents.guild_scheduled_events = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="đ", intents=intents)


SERVICE_ACCOUNT_FILE = "BotCreds.json"
SPREADSHEET_ID = "1Q8x4Qa9_8k7RpjqVnojw-BDeOeTEq1gnhYmrQdvqIr4"

MaxLine = 30 #default = 30
MinTime = 15 #default = 15
WaitForCoHost = 60 #default = 60

is_timer_running = False
members_in_vc = {}

# Get IDS/Bot info from environment variables
USE_TEST_MODE = False  # Change this to False for production/pushing to main branch

if USE_TEST_MODE:
    guild_id = int(os.getenv("TEST_GUILD_ID"))
    ReportChannelID = int(os.getenv("TEST_REPORT_CHANNEL_ID"))
    TrackedVoiceChannelID = int(os.getenv("TEST_TRACKED_VOICE_CHANNEL_ID"))
    BotToken = os.getenv("TEST_BOT_TOKEN")
else:
    guild_id = int(os.getenv("MAIN_GUILD_ID"))
    ReportChannelID = int(os.getenv("MAIN_REPORT_CHANNEL_ID"))
    TrackedVoiceChannelID = int(os.getenv("MAIN_TRACKED_VOICE_CHANNEL_ID"))
    BotToken = os.getenv("MAIN_BOT_TOKEN")

# Validate that all required environment variables are set
if not all([guild_id, ReportChannelID, TrackedVoiceChannelID, BotToken]):
    raise ValueError("Missing required environment variables. Please check your .env file.")

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Import")

gamenight_message = None


start_time = None
end_time = None
cohost = None

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

    guild = bot.get_guild(guild_id)
    if guild:
        print(f"Connected to the correct guild: {guild.name} ({guild.id})")
    else:
        print("The bot is not connected to the expected guild")

@bot.event
async def on_scheduled_event_update(before, after):
    global is_timer_running, members_in_vc, start_time, end_time, cohost, gamenight_overview_message

    if after.guild.id != guild_id:
        return

    if before.status != after.status:
        guild = bot.get_guild(guild_id)
        if not guild:
            print(f"Unable to find the guild with ID {guild_id}")
            return
        
        channel = guild.get_channel(ReportChannelID)
        if not channel:
            print(f"Unable to find the channel with ID {ReportChannelID}")
            return
        
        GamenightVoiceChannel = guild.get_channel(TrackedVoiceChannelID)
        if not GamenightVoiceChannel:
            print(f"Unable to find the channel with ID {TrackedVoiceChannelID}")
            return

        host = after.creator if after.creator else None

        # Create embed1 here to avoid UnboundLocalError
        embed1 = discord.Embed()
        view = discord.ui.View(timeout=None)
        
        new_gamenight_info = None

        rounded_hours = 0
        unrounded_hours = 0
        rounded_minutes = 0
        unrounded_minutes = 0

        # Define buttons upfront
        join_button = discord.ui.Button(label="Join as CoHost", style=discord.ButtonStyle.primary)
        remove_button = discord.ui.Button(label="Remove CoHost", style=discord.ButtonStyle.danger)

        async def join_button_callback(interaction):
            if interaction.user.id == host.id:
                await interaction.response.send_message("You cannot assign yourself as the CoHost because you are the host!", ephemeral=True, delete_after=5)
                return

            global cohost
            cohost = interaction.user  # Assign the new cohost
            await interaction.response.send_message(f"CoHost assigned: {cohost.mention}", ephemeral=True, delete_after=5)

            if is_timer_running == True:
                new_gamenight_info = f"""
                Gamenight Overview:
                Name: {after.name}
                Host: {host.display_name}
                CoHost: {cohost.display_name}
                Duration: <a:Green:1335416471521857566> Pending
                Date: {start_time.strftime('%Y-%m-%d')}
                """
            else:
                new_gamenight_info = f"""
                Gamenight Overview:
                Name: {after.name}
                Host: {host.display_name}
                CoHost: {cohost.display_name}
                Duration: {rounded_hours}h {rounded_minutes}m
                Date: {start_time.strftime('%Y-%m-%d')}
                """

            embed1.description = new_gamenight_info
            embed1.set_image(url=after.cover_image.url if after.cover_image else None)

            # Rebuild the view to include buttons
            view = discord.ui.View(timeout=None)
            view.add_item(join_button)
            view.add_item(remove_button)
            await interaction.message.edit(embeds=[embed1], view=view)

        async def remove_button_callback(interaction):
            global cohost
            if cohost:
                await interaction.response.send_message(f"CoHost removed: {cohost.mention}", ephemeral=True, delete_after=5)
                cohost = None  # Remove cohost
            else:
                await interaction.response.send_message("No CoHost to remove!", ephemeral=True, delete_after=5)

            if is_timer_running == True:
                new_gamenight_info = f"""
                Gamenight Overview:
                Name: {after.name}
                Host: {host.display_name}
                Duration: <a:Green:1335416471521857566> Pending
                Date: {start_time.strftime('%Y-%m-%d')}
                """
            else:
                new_gamenight_info = f"""
                Gamenight Overview:
                Name: {after.name}
                Host: {host.display_name}
                Duration: {rounded_hours}h {rounded_minutes}m
                Date: {start_time.strftime('%Y-%m-%d')}
                """
                
            embed1.description = new_gamenight_info
            embed1.set_image(url=after.cover_image.url if after.cover_image else None)

            # Rebuild the view to include buttons
            view = discord.ui.View(timeout=None)
            view.add_item(join_button)
            view.add_item(remove_button)
            await interaction.message.edit(embeds=[embed1], view=view)

        # Assign callback functions to buttons
        join_button.callback = join_button_callback
        remove_button.callback = remove_button_callback

        # --- EVENT STARTED ---
        if after.status == EventStatus.active:

            # Unlock Gamenight Channel for @everyone
            overwrite = GamenightVoiceChannel.overwrites_for(guild.default_role)
            overwrite.connect = True 
            await GamenightVoiceChannel.set_permissions(guild.default_role, overwrite=overwrite)


            start_time = datetime.datetime.now()
            is_timer_running = True
            members_in_vc = {}

            # Track members in the voice channel
            for member in guild.members:
                if member.voice and member.voice.channel and member.voice.channel.id == TrackedVoiceChannelID:
                    members_in_vc[member.id] = [{
                        "start_time": discord.utils.utcnow().timestamp(),
                        "total_time": 0,
                    }]
            
            # Post "Gamenight Overview" at event start (without participants yet)
            GamenightInfoTable = f"""
            Gamenight Overview:
            Name: {after.name}
            Host: {host.display_name}
            Duration: <a:Green:1335416471521857566> Pending
            Date: {start_time.strftime('%Y-%m-%d')}
            """

            embed1.description = GamenightInfoTable

            if after.cover_image:
                embed1.set_image(url=after.cover_image.url)

            # Add buttons to the view
            view.add_item(join_button)
            view.add_item(remove_button)

            # Send the Gamenight Overview and store message ID for later deletion
            gamenight_overview_message = await channel.send(embeds=[embed1], view=view)

        # --- EVENT ENDED ---
        elif after.status == EventStatus.completed:
            # Lock Gamenight Channel for @everyone
            overwrite = GamenightVoiceChannel.overwrites_for(guild.default_role)
            overwrite.connect = False 
            await GamenightVoiceChannel.set_permissions(guild.default_role, overwrite=overwrite)


            end_time = datetime.datetime.now()
            is_timer_running = False
            results_list = []

            # Update gamenight overview with the duration and participants
            for member_id, sessions in members_in_vc.items():
                member = await fetch_member(guild, member_id)
                total_time = sum(session["total_time"] for session in sessions)

                if member and member.voice and member.voice.channel and member.voice.channel.id == TrackedVoiceChannelID:
                    last_session = sessions[-1]
                    total_time += discord.utils.utcnow().timestamp() - last_session["start_time"]

                total_minutes = int(total_time // 60)  # Store exact minutes for sheets
                if total_minutes < MinTime:
                    continue  

                unrounded_hours, unrounded_remainder = divmod(int(total_time), 3600)
                unrounded_minutes, _ = divmod(unrounded_remainder, 60)

                rounded_hours = unrounded_hours
                rounded_minutes = unrounded_minutes

                if unrounded_minutes < MinTime:
                    rounded_minutes = 0
                elif MinTime <= unrounded_minutes < 45:
                    rounded_minutes = 30
                elif 45 <= unrounded_minutes <= 60:
                    rounded_minutes = 0
                    rounded_hours += 1
                    unrounded_hours += 1

                results_list.append({
                    "name": member.name if member else member.display_name if member else "Unknown Member", 
                    "display_name": member.display_name if member else "Unknown Member",
                    "actual_name": member.name if member else "Unknown Member",
                    "mention": member.mention if member else f"<@{member_id}>",
                    "id": member_id,
                    "time": f"{rounded_hours}h {rounded_minutes}m",
                    "unrounded_time": f"{unrounded_hours}h {unrounded_minutes}m",
                    "unrounded_minutes": total_minutes,
                })

            # Sort participants by name for the report
            results_list = sorted(results_list, key=lambda x: x["display_name"].lower())

            # Construct participant overview message
            participants_info = "\n".join([f"### {entry['display_name']} (ID: {entry['id']}): {entry['time']}" for entry in results_list])
            embed = discord.Embed(
                title="Participants Overview",
                description=participants_info,
                color=discord.Color.blue()
            )

            event_duration_seconds = (end_time - start_time).total_seconds()

            unrounded_hours, unrounded_remainder = divmod(int(event_duration_seconds), 3600)
            unrounded_minutes, _ = divmod(unrounded_remainder, 60)

            rounded_hours = unrounded_hours
            rounded_minutes = unrounded_minutes

            if unrounded_minutes < MinTime:
                rounded_minutes = 0
            elif MinTime <= unrounded_minutes < 45:
                rounded_minutes = 30
            elif 45 <= unrounded_minutes <= 60:
                rounded_minutes = 0
                rounded_hours += 1
                unrounded_hours += 1

            # Update the gamenight overview with duration and participants
            new_gamenight_info = f"""
            Gamenight Overview:
            Name: {after.name}
            Host: {host.display_name}
            CoHost: {cohost.display_name if cohost else 'None'}
            Duration: {rounded_hours}h {rounded_minutes}m
            Date: {start_time.strftime('%Y-%m-%d')}
            """
            embed1.description = new_gamenight_info
            embed1.set_image(url=after.cover_image.url if after.cover_image else None)
            embed1.set_thumbnail(url="https://cdn.discordapp.com/attachments/1292176893738614856/1335751326558060605/EventFinished.png?ex=67a14edd&is=679ffd5d&hm=165deeed8a3900265ff24c13b475d4ab4abc43c18c67be83a8e64093a1fbdd82&")

            # Rebuild the view to include buttons
            view = discord.ui.View(timeout=None)
            view.add_item(join_button)
            view.add_item(remove_button)

            await gamenight_overview_message.edit(embeds=[embed1], view=view)
            await channel.send(embed=embed)

            await asyncio.sleep(WaitForCoHost)

            save_results_to_google_sheets(after, host, f"{unrounded_hours}h {unrounded_hours}m", end_time.strftime('%Y-%m-%d'), results_list, cohost)


def save_results_to_google_sheets(event, host, duration_str, end_date, results_list, cohost=None):
    duration_parts = duration_str.split('h')
    gamenight_hours = int(duration_parts[0].strip()) if duration_parts[0].strip() else 0
    gamenight_minutes = int(duration_parts[1].replace('m', '').strip()) if len(duration_parts) > 1 else 0
    total_gamenight_minutes = gamenight_hours * 60 + gamenight_minutes  # Convert to total minutes

    rows_for_gsheets = []

    for entry in results_list:
        participant_role = "Participant"
        if entry['id'] == host.id:
            participant_role = "Host"
        elif cohost and entry['id'] == cohost.id:
            participant_role = "CoHost"

        # Use unrounded time values for Google Sheets
        total_minutes = entry["unrounded_minutes"]

        row = [end_date, event.name, str(event.id), total_gamenight_minutes, participant_role, entry["display_name"], str(entry["id"]), total_minutes]
        rows_for_gsheets.append(row)

    if rows_for_gsheets:
        rows_for_gsheets.sort(key=lambda x: x[5].lower())  # Sort by participant name (index 5)
        sheet.append_rows(rows_for_gsheets, value_input_option="RAW")
        print("Data successfully saved to Google Sheets (Import sheet).")
    else:
        print("No participant data to save.")


async def fetch_member(guild, member_id):
    member = guild.get_member(member_id)  # Try fetching from cache
    if not member:  
        try:
            member = await guild.fetch_member(member_id)  # Force fetch from API
        except discord.NotFound:
            return None  # Member not found
    return member

@bot.event
async def on_voice_state_update(member, before, after):
    global is_timer_running, members_in_vc

    if not is_timer_running:
        return
    
    if member.guild.id != guild_id:
        return

    member_id = member.id

    if after.channel and after.channel.id == TrackedVoiceChannelID and (not before.channel or before.channel.id != TrackedVoiceChannelID):
        if member_id not in members_in_vc:
            members_in_vc[member_id] = [{
                "start_time": time.time(),
                "total_time": 0,
            }]
        else:
            members_in_vc[member_id].append({
                "start_time": time.time(),
                "total_time": 0,
            })

        print(f"{member.name} joined the target VC.")

    if before.channel and before.channel.id == TrackedVoiceChannelID and (not after.channel or after.channel.id != TrackedVoiceChannelID):
        if member_id in members_in_vc:
            current_session = members_in_vc[member_id][-1]
            current_session["total_time"] += time.time() - current_session["start_time"]

            print(f"{member.name} left the target VC. Total time: {current_session['total_time']} seconds.")

bot.run(BotToken)