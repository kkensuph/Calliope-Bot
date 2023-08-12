import asyncio
import datetime
import random
import string
import aiofiles
import discord
import pytz as pytz
import json
from discord.ext import commands
from dotenv import dotenv_values
from collections import OrderedDict
from discord.ext.commands import check

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# Global Variables
env_vars = dotenv_values('.env')
TOKEN = env_vars['TOKEN']
directory = 'stocks_data.json'


@bot.event
async def on_ready():
    print(f"Bot is ready. Connected to {len(bot.guilds)} guilds.")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name='/stocks'))


def openJson(file_path):
    with open(file_path, "r") as file:
        json_data = file.read()
    data_dict = json.loads(json_data, object_pairs_hook=OrderedDict)
    return data_dict


def saveJson(data_dict, file_path):
    with open(file_path, "w") as file:
        json.dump(data_dict, file)


def convert_seconds_to_hours(seconds):
    hours = seconds // 3600  # 1 hour has 3600 seconds
    return f"{hours} HOURS"


async def get_vouch_channel_id():
    env_vars = await asyncio.to_thread(dotenv_values, '.env')
    return int(env_vars['VOUCH_CHANNEL'])


async def get_timer_value():
    env_vars = await asyncio.to_thread(dotenv_values, '.env')
    return int(env_vars['DUE'])


async def get_category_id():
    env_vars = await asyncio.to_thread(dotenv_values, '.env')
    return int(env_vars['CATEGORY'])


async def get_moderator_id():
    env_vars = await asyncio.to_thread(dotenv_values, '.env')
    return int(env_vars['MODERATOR'])


async def generate_reference_code(length=10):
    characters = string.ascii_uppercase + string.digits
    return ''.join(await asyncio.gather(
        *[asyncio.to_thread(random.choice, characters) for _ in range(length)]
    ))


async def replace_env_variable(env_file, variable_name, new_value):
    # Read the contents of the .env file asynchronously
    async with aiofiles.open(env_file, 'r') as file:
        lines = await file.readlines()

    # Find the line that contains the variable
    for i, line in enumerate(lines):
        if line.startswith(variable_name + '='):
            lines[i] = f'{variable_name}={new_value}\n'
            break

    # Write the updated contents back to the .env file asynchronously
    async with aiofiles.open(env_file, 'w') as file:
        await file.writelines(lines)


def has_required_role():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        role = discord.utils.get(ctx.author.roles, id=await get_moderator_id())
        if role is None:
            embed = discord.Embed(
                title="You need permission to use this command",
                description="Sorry, but it seems like you don't have the necessary role to use this command.\n"
                            "If you believe this is a mistake, please contact the Administrator for assistance.",
                color=0xFF0000
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return False
        return True

    return check(predicate)


class BuyNow(discord.ui.View):
    def __init__(self, selected_item, quantity):
        super().__init__()
        self.selected_item = selected_item
        self.quantity = quantity

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary)
    async def confirm_button(self, button, interaction):

        self.disable_all_items()
        self.clear_items()
        await interaction.response.edit_message(view=self)

        if self.quantity <= 0:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Out of Stock",
                    description=f"The selected item `{self.selected_item}` is currently out of stock.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Create a text-channel and send a welcome message
        guild = interaction.guild
        member = interaction.user

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True),
        }

        moderator_roles = [role for role in guild.roles if role.id == await get_moderator_id()]

        for role in moderator_roles:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True)

        ticket_names = f"{member.name}-{self.selected_item}-ticket"

        # Define Category ID
        category = guild.get_channel(await get_category_id())

        channel = await guild.create_text_channel(ticket_names, overwrites=overwrites, category=category)
        embed = discord.Embed(
            title="Welcome to your ticket!",
            description=f"Hey there {member.mention}! We're here to assist you and make your experience as smooth as possible. Just hang on for a moment, and one of our moderators will be with you shortly.\n\nIf you have any questions or concerns, feel free to let us know. We're here to help!\n\nIf you change your mind and want to delete this ticket, you can simply react with the `🗑️` emoji. This will help us keep things organized and ensure a seamless experience for everyone."
                        f"\n\n**Order:** `{self.selected_item}`",
            color=discord.Color.nitro_pink()
        )

        # Handle the confirmation logic here

        await interaction.followup.send(
            embed=discord.Embed(
                title="Ticket Created",
                description=f"You have confirmed to buy `{self.selected_item}`\n"
                            f"Current Stocks: `{self.quantity}`"
                            f"\n\n"
                            f"{channel.mention}",
                color=discord.Color.green()
            ),
            ephemeral=True
        )

        # Ghost ping the user and mods
        moderator_role = discord.utils.get(guild.roles, id=await get_moderator_id())
        ghost_ping = await channel.send(f"{member.mention}, {guild.owner.mention}, {moderator_role.mention}")
        await ghost_ping.delete()

        # Send the embedded message and add the reaction
        message = await channel.send(embed=embed)

        await message.add_reaction("🗑️")

        def check(reaction, user):
            return (
                    str(reaction.emoji) == "🗑️"
                    and (user == member or moderator_role in user.roles)
                    and reaction.message.channel == channel
            )

        try:
            reaction, _ = await bot.wait_for("reaction_add", check=check, timeout=86400)
        except asyncio.TimeoutError:
            pass
        else:
            await channel.delete()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button, interaction):
        # Handle the cancellation logic here
        self.disable_all_items()
        self.clear_items()
        await interaction.response.edit_message(view=self)

        # Create a new interaction to send the cancellation message
        await interaction.followup.send(
            embed=discord.Embed(
                title="Ticket Canceled",
                description="You have canceled the purchase.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )


class DeleteNowConfirmationView(discord.ui.View):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm_button(self, button, interaction):
        if self.name in stocks_data:
            stocks_data.pop(self.name)
            embed = discord.Embed(description=f"The stock item `{self.name}` has been deleted.")

        else:
            embed = discord.Embed(description=f"The stock item '{self.name}' was not found.")
        await interaction.response.edit_message(embed=embed, view=None)

        saveJson(stocks_data, "stocks_data.json")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button, interaction):
        embed = discord.Embed(
            description=f"The cancellation of the deletion for stock item `{self.name}` has been successful.")
        await interaction.response.edit_message(embed=embed, view=None)


class ViewStockButtons(discord.ui.View):
    def __init__(self, data):
        super().__init__()
        self.stocks_data = data

        for name, quantity in self.stocks_data.items():

            if quantity <= 0:
                quantity = 'Out of Stock'

            label = f"{name} ({quantity})"
            button = discord.ui.Button(label=label, custom_id=name, style=discord.ButtonStyle.secondary)
            button.callback = lambda i, b=button: self.on_button_click(i, b)  # Set the callback function
            self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected_item = button.custom_id
        quantity = self.stocks_data[selected_item]

        if quantity <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Out of Stock",
                    description=f"`{selected_item}` is currently out of stock.\n",
                    color=discord.Color.red()
                ), ephemeral=True)
            return
        else:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Confirmation",
                    description=f"Do you want to buy `{selected_item}`?\n"
                                f"If you press confirm, I will create a ticket for you.",
                    color=discord.Color.blue()
                ),
                ephemeral=True,
                view=BuyNow(selected_item, quantity)
            )


# Warranty Classes

class WarrantyModal(discord.ui.Modal):
    def __init__(self, *args, get_modal_variables, selected_item, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.get_modal_variables = get_modal_variables
        self.selected_item = selected_item

        self.add_item(
            discord.ui.InputText(label="Quantity", placeholder='How many items did the user buy?', required=True))
        self.add_item(discord.ui.InputText(label="Link", placeholder='Activation links',
                                           style=discord.InputTextStyle.long, required=False))

    async def callback(self, interaction: discord.Interaction):
        quantity = self.children[0].value
        if not quantity.isdigit():
            error = discord.Embed(
                title="Warranty Error",
                description="Please enter a `number` in the quantity field instead of using `letters`",
                color=0xff0000
            )
            await interaction.response.send_message(embed=error, ephemeral=True)
            return
        link = self.children[1].value
        item = self.selected_item
        await interaction.response.send_message("Got your information!", ephemeral=True)
        await self.get_modal_variables(quantity, link, item)


class ViewWarrantyButtons(discord.ui.View):
    def __init__(self, data, get_modal_variables):
        super().__init__()
        self.stocks_data = data
        self.get_modal_variables = get_modal_variables
        self.selected_quantity = None  # Initialize selected_quantity as None

        for name, quantity in self.stocks_data.items():

            if quantity <= 0:
                quantity = 'Out of Stock'

            label = f"{name} ({quantity})"
            button = discord.ui.Button(label=label, custom_id=name, style=discord.ButtonStyle.secondary)
            button.callback = lambda i, b=button: self.on_button_click(i, b)  # Set the callback function
            self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected_item = button.custom_id
        self.disable_all_items()
        self.clear_items()
        self.selected_quantity = self.stocks_data[selected_item]  # Store the selected quantity

        if self.selected_quantity <= 0:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Out of Stock",
                    description=f"`{selected_item}` is currently out of stock.\n"
                                f"Use `/edit` to edit the quantity of the item.",
                    color=discord.Color.red()
                ), ephemeral=True)
            return
        else:
            await interaction.response.send_modal(
                WarrantyModal(title="Warranty Information", get_modal_variables=self.get_modal_variables,
                              selected_item=selected_item))
            await interaction.followup.edit_message(message_id=interaction.message.id, view=self)


# Stock Edit Quantity Classes

class QuantityModal(discord.ui.Modal):
    def __init__(self, get_modal_variables, name, quantity, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.get_modal_variables = get_modal_variables
        self.name = name
        self.quantity = quantity

        self.add_item(discord.ui.InputText(label="Name", placeholder=name, required=False))
        self.add_item(discord.ui.InputText(label="Quantity", placeholder=quantity, required=False))

    async def callback(self, interaction: discord.Interaction):

        if not self.children[1].value.isdigit() and self.children[1].value != '':
            error = discord.Embed(
                title="Something went wrong",
                description="Please enter a `number` in the quantity field instead of `letters`",
                color=0xff0000
            )
            await interaction.response.send_message(embed=error, ephemeral=True)
            return

        # Assign Variables
        f_quantity = self.quantity
        f_name = self.name

        # If the user didn't change the quantity
        if self.children[1].value == '':
            pass
        else:
            f_quantity = self.children[1].value
            stocks_data[self.name] = int(f_quantity)

        # If the user didn't change the name
        if self.children[0].value == '':
            pass
        else:
            f_name = self.children[0].value
            stocks_data[self.children[0].value] = stocks_data.pop(self.name)

        saveJson(stocks_data, "stocks_data.json")
        await interaction.response.send_message("The item have been successfully edited.", ephemeral=True)
        await self.get_modal_variables(f_quantity, f_name)
        return


class ViewQuantityButtons(discord.ui.View):
    def __init__(self, data, get_modal_variables):
        super().__init__()
        self.stocks_data = data
        self.get_modal_variables = get_modal_variables
        self.selected_quantity = None  # Initialize selected_quantity as None

        for name, quantity in self.stocks_data.items():
            if quantity <= 0:
                quantity = 'Out of Stock'
            label = f"{name} ({quantity})"
            button = discord.ui.Button(label=label, custom_id=name, style=discord.ButtonStyle.secondary)
            button.callback = lambda i, b=button: self.on_button_click(i, b)  # Set the callback function
            self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected_item = button.custom_id
        self.disable_all_items()
        self.clear_items()
        self.selected_quantity = self.stocks_data[selected_item]  # Store the selected quantity

        await interaction.response.send_modal(
            QuantityModal(title="Item Information", get_modal_variables=self.get_modal_variables, name=selected_item,
                          quantity=self.selected_quantity))


# Delete Classes

class ViewDeleteButtons(discord.ui.View):
    def __init__(self, data):
        super().__init__()
        self.stocks_data = data
        self.selected_quantity = None

        for name, quantity in self.stocks_data.items():
            if quantity <= 0:
                quantity = 'Out of Stock'
            label = f"{name} ({quantity})"
            button = discord.ui.Button(label=label, custom_id=name, style=discord.ButtonStyle.secondary)
            button.callback = lambda i, b=button: self.on_button_click(i, b)  # Set the callback function
            self.add_item(button)

    async def on_button_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        selected_item = button.custom_id
        self.selected_quantity = self.stocks_data[selected_item]  # Store the selected quantity
        embed = discord.Embed()
        embed.description = f"Are you sure you want to delete the stock item `{selected_item}`?"
        await interaction.response.send_message(embed=embed, view=DeleteNowConfirmationView(selected_item),
                                                ephemeral=True)
        # await interaction.followup.edit_message(message_id=interaction.message.id, view=self)


# New Classes
class NewModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.add_item(discord.ui.InputText(label="Name", placeholder='Nitro Boost', required=False))
        self.add_item(discord.ui.InputText(label="Quantity", placeholder='50', required=False))

    async def callback(self, interaction: discord.Interaction):
        if not self.children[1].value.isdigit():
            error = discord.Embed(
                title="Something went wrong",
                description="Please enter a `number` in the quantity field instead of `letters`",
                color=0xff0000
            )
            await interaction.response.send_message(embed=error, ephemeral=True)
            return

        name = self.children[0].value
        quantity = int(self.children[1].value)

        embed = discord.Embed(title="Item Added:")
        embed.add_field(name="Name", value=self.children[0].value)
        embed.add_field(name="Quantity", value=self.children[1].value)
        await interaction.response.send_message(embeds=[embed])

        stocks_data[name] = quantity
        saveJson(stocks_data, "stocks_data.json")


stocks_data = openJson(directory)


@bot.slash_command(description="Display a list of items currently in stock.")
async def stocks(ctx: commands.Context):
    if len(stocks_data) <= 0:
        embed = discord.Embed(title="Stock Items", description="There are no items saved on my list.")
        await ctx.respond(embed=embed, ephemeral=True)
        return
    view = ViewStockButtons(stocks_data)
    await ctx.respond(view=view, ephemeral=True)


@bot.slash_command(description="Create a new item from the stock list.")
@has_required_role()
async def new(ctx: commands.Context):
    modal = NewModal(title="New Stock Item")
    await ctx.send_modal(modal)


@bot.slash_command(description="Remove a specific item from the stock list.")
@has_required_role()
async def delete(ctx: commands.Context):
    await ctx.respond(view=ViewDeleteButtons(stocks_data), ephemeral=True)


@bot.slash_command(description="Modify the name and quantity of a specific item in the stock list.")
@has_required_role()
async def edit(ctx: commands.Context):
    async def get_model_variables(quantity, name):
        pass

    await ctx.respond(view=ViewQuantityButtons(stocks_data, get_modal_variables=get_model_variables), ephemeral=True)


@bot.slash_command(description="Send a warranty activation message to a user.")
@has_required_role()
async def warranty(ctx: commands.Context, user: discord.User):
    m_quantity = None
    m_link = None
    m_item = None

    async def get_modal_variables(quantity, link, item):
        nonlocal m_quantity
        nonlocal m_link
        nonlocal m_item
        m_quantity = quantity
        m_link = link
        m_item = item

        async def send_warranty(ctx, user):

            nonlocal m_quantity
            nonlocal m_link

            try:
                reference_code = await generate_reference_code()

                # Get the current date, and await get_timer_value() data
                ph_timezone = pytz.timezone('Asia/Manila')
                current_time_ph = datetime.datetime.now(ph_timezone)
                deadline_ph = current_time_ph + datetime.timedelta(seconds=await get_timer_value())

                # Get the vouch channel
                target_channel = bot.get_channel(await get_vouch_channel_id())

                if m_link == '':
                    message_template = (
                        "**.별 : a message has been received.**\n\n"
                        f"<a:pink_arrow:1116611362861351045> **{m_item}** - **x{quantity}**\n"
                        f"Reference Code: `{await generate_reference_code()}`\n\n"
                        "<a:dot_blow:1139089076578947173> please read <#1100371712509493296> before and after purchasing.\n"
                        f"<a:dot_blow:1139089076578947173> vouch at <#1095348388284862485> within **{convert_seconds_to_hours(await get_timer_value())}** to activate warranty.\n"
                        "<a:dot_blow:1139089076578947173> don't forget to write the right format or else it will be voided.\n"
                        "<a:dot_blow:1139089076578947173> no vouch = no warranty\n\n"
                        "thank you so much for trusting us.\n"
                        "balik po kayo\n\n"
                        "love, calliope <:starguardian:1116890190003314749>"
                    )
                else:
                    m_link = m_link.split()
                    message_template = (
                        "**.별 : a message has been received.**\n\n"
                        f"<a:pink_arrow:1116611362861351045> **{m_item}** - **x{quantity}**\n"
                        f"Reference Code: `{await generate_reference_code()}`\n\n"
                        "<a:dot_blow:1139089076578947173> please read <#1100371712509493296> before and after purchasing.\n"
                        f"<a:dot_blow:1139089076578947173> vouch at <#1095348388284862485> within **{convert_seconds_to_hours(await get_timer_value())}** to activate warranty.\n"
                        "<a:dot_blow:1139089076578947173> don't forget to write the right format or else it will be voided.\n"
                        "<a:dot_blow:1139089076578947173> no vouch = no warranty\n\n"
                        "thank you so much for trusting us.\n"
                        "balik po kayo\n\n"
                        "love, calliope <:starguardian:1116890190003314749>\n\n"
                        "(links)\n\n"
                    )
                    for idx, single_link in enumerate(m_link, start=1):
                        message_template += f"||`{single_link}`||\n"

                pending_embed = discord.Embed(
                    title="Warranty Activation",
                    description=f"The warranty activation has been sent to {user.mention}\n\n"
                                f"**Note:** The warranty will be **AUTOMATICALLY** voided if {user.mention} doesn't vouch in <#{await get_vouch_channel_id()}> within **{convert_seconds_to_hours(await get_timer_value())}** of receiving the warranty activation message.\n\n"
                                f"I will notify you if the user {user.mention} sent an image to the <#{await get_vouch_channel_id()}>.\n\n"
                                f"Reference Code: `{reference_code}`\n"
                                f"Due Date: `{deadline_ph.strftime('%Y-%m-%d %I:%M')} {deadline_ph.strftime('%p').upper()}`\n\n"
                                f"Verifier: {ctx.author.mention}",
                    color=0x00ffff)

                await user.send(message_template)
                await ctx.respond(f'Sending warranty activation message to the user. Let me cook for a minute.',
                                  ephemeral=True)
                pending_msg = await ctx.send(embed=pending_embed)

                try:  # Subtract how much have been bought
                    stocks_data[m_item] = int(stocks_data[m_item]) - int(m_quantity)
                    saveJson(stocks_data, "stocks_data.json")
                except asyncio.TimeoutError:  # If the user didn't enter number
                    error = discord.Embed(
                        title="Something went wrong",
                        description="You encountered a rare bug! Please contact `@kensu`.",
                        color=0xff0000
                    )
                    await ctx.send(embed=error)
                    return

                def image_check(message):
                    return (
                            message.author == user
                            and message.channel == target_channel
                            and any(
                        attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')) for attachment
                        in message.attachments)
                    )

                try:
                    # Wait for the user to send an image message
                    image_message = await bot.wait_for("message", timeout=await get_timer_value(), check=image_check)

                    moderator_role = discord.utils.get(ctx.guild.roles, id=await get_moderator_id())

                    # User sent an image
                    notification_embed = discord.Embed(
                        title="Vouch Notification",
                        description=f"{moderator_role.mention}. The user {user.mention} has sent an image in the vouch channel.\n\n"
                                    f"Before locking the order, please double-check it to ensure the following:\n"
                                    f"- The user mentions {ctx.guild.owner.mention} or the other moderators.\n"
                                    f"- The reference code must be visible from the screenshot.\n\n"
                                    f"Reference code: `{reference_code}`\n\n"
                                    f"Item: `{m_item}`\n"
                                    f"Quantity: `{m_quantity}`\n\n",
                        color=0xffa500
                    )

                    if image_message:
                        image_link = image_message.jump_url
                        notification_embed.description += f"[View Image]({image_link})"

                    # Send the notification and add a lock emoji reaction
                    notification_msg = await ctx.send(embed=notification_embed)

                    await notification_msg.add_reaction("🔒")

                    moderator_id = await get_moderator_id()

                    def check_reaction(reaction, user):
                        role = ctx.guild.get_role(moderator_id)
                        return (
                                reaction.message.id == notification_msg.id
                                and str(reaction.emoji) == "🔒"
                                and role in user.roles
                        )

                    try:
                        # Wait for a moderator to react with the lock emoji
                        reaction, user = await bot.wait_for("reaction_add", check=check_reaction)

                        # Clear all reactions on the message
                        await notification_msg.clear_reactions()

                        # Edit the success_embed to display "Warranty Activated"
                        notification_embed.title = "Warranty Activated"
                        notification_embed.description = (
                            f"The user {user.mention} has successfully vouched.\n\n"
                            f"**Order Information:**\n\n"
                            f"Item: `{m_item}`\n"
                            f"Quantity: `{m_quantity}`\n"
                            f"Reference code: `{reference_code}`\n\n"
                            f"Verified by: {user.mention}\n\n"
                        )

                        if image_message:
                            image_link = image_message.jump_url
                            notification_embed.description += f"[View Image]({image_link})"

                        notification_embed.color = 0x00ff00
                        await notification_msg.edit(embed=notification_embed)

                        # Change the color of the pending embed to green
                        pending_embed.color = 0x00ff00
                        await pending_msg.edit(embed=pending_embed)

                    except asyncio.TimeoutError:
                        # If no moderator reacted
                        pass

                except asyncio.TimeoutError:
                    # User did not send an image
                    fail_embed = discord.Embed(
                        title="Warranty Voided",
                        description=f"The user {user.mention} did not submit a vouch or image within the provided {convert_seconds_to_hours(await get_timer_value())} time.\n"
                                    f"Reference code: `{reference_code}`\n"
                                    f"Verified by: `Automatically Voided`",
                        color=0xff0000
                    )
                    await ctx.send(embed=fail_embed)

                    # Change the color of the pending embed to red
                    pending_embed.color = 0xff0000
                    await pending_msg.edit(embed=pending_embed)
            except discord.errors.Forbidden as e:
                if e.status == 403:
                    await ctx.respond(
                        f"I'm sorry, but I'm unable to send a direct message to {user.mention}. Please inform them to check their privacy settings to enable direct messages.",
                        ephemeral=True)
                else:
                    await ctx.respond(
                        "Please contact the developer for assistance as you seem to have encountered a bug.",
                        ephemeral=True)

        await send_warranty(ctx, user)

    if len(stocks_data) <= 0:
        embed = discord.Embed(title="Stock Items", description="There are no items saved on my list.")
        await ctx.respond(embed=embed, ephemeral=True)
        return
    else:
        await ctx.respond("Select the item that has been bought.",
                          view=ViewWarrantyButtons(stocks_data, get_modal_variables),
                          ephemeral=True)


@bot.slash_command(description="Retrieve and display the current configuration settings of the bot.")
@has_required_role()
async def settings(ctx: commands.Context):
    guild = ctx.guild
    guild_owner = guild.owner if guild else None
    moderator_role = discord.utils.get(ctx.guild.roles, id=await get_moderator_id())
    embed = discord.Embed(
        title="Bot Configuration",
        description="Here is the current configuration of the bot\n",
        color=0x3498db  # Blue color
    )
    embed.add_field(name="⌛ Timer", value=f"`{await get_timer_value() // 3600} hours`", inline=False)
    embed.add_field(name="🧾 Vouch Channel", value=f"`#{ctx.guild.get_channel(await get_vouch_channel_id()).name}`",
                    inline=False)
    embed.add_field(name="🏰 Server Name", value=f"`{guild.name}`" if guild else "`Not in a guild`", inline=False)
    embed.add_field(name="👑 Server Owner", value=f"`@{guild_owner.name}`" if guild_owner else "N/A", inline=False)
    embed.add_field(name="🎟 Ticket Channel", value=f"`#{ctx.guild.get_channel(await get_category_id()).name}`",
                    inline=False)
    embed.add_field(name="🤖 Authorized Role", value=f"`@{moderator_role.name}`",
                    inline=False)
    await ctx.respond(embed=embed)


@bot.slash_command(description="Update the channel where vouches are recorded.")
@has_required_role()
async def channel(ctx: commands.Context, channel: discord.TextChannel):
    embed = discord.Embed(
        title="Vouch Channel Updated",
        description=f"The vouch channel has been set to {channel.mention}.",
        color=0x00ff00  # Green color
    )
    await ctx.respond(embed=embed)

    # Replace the variable on .env file
    await replace_env_variable('.env', 'VOUCH_CHANNEL', channel.id)


@bot.slash_command(description="Modify the roles that have access to use the bot. (Restricted to administrators)")
@has_required_role()
async def moderator(ctx: commands.Context, role: discord.Role):
    embed = discord.Embed(
        title="Moderator Role Updated",
        description=f"The roles that have access to use the bot has been set to {role.mention}.",
        color=0x00ff00  # Green color
    )
    await ctx.respond(embed=embed)

    # Replace the variable on .env file
    await replace_env_variable('.env', 'MODERATOR', role.id)


@bot.slash_command(description="Specify the category where new support tickets will be created.")
@has_required_role()
async def category(ctx: commands.Context, category: discord.CategoryChannel):
    # Replace the variable on .env file
    await replace_env_variable('.env', 'CATEGORY', category.id)

    embed = discord.Embed(
        title="Vouch Channel Updated",
        description=f"The tickets creation has been set to {category.mention}.",
        color=0x00ff00  # Green color
    )
    await ctx.respond(embed=embed)


@bot.slash_command(description="Adjust the duration (in hours) for the Warranty Verification process")
@has_required_role()
async def timer(ctx: commands.Context, hours: int):
    if hours < 0:
        await ctx.respond("Please enter a number.")
        return
    await replace_env_variable('.env', 'DUE', hours * 3600)
    embed = discord.Embed(
        title="Timer Updated",
        description=f"The timer has been set to **{hours}** hour/s.",
        color=0x00ff00  # Green color
    )
    await ctx.respond(embed=embed)


@bot.slash_command(description="Sends an activated warranty message to the specified user.")
@has_required_role()
async def warranty_activated(ctx: commands.Context, user: discord.User, reference_code):
    success_embed = discord.Embed(
        title="Warranty Activated",
        description=f"The user {user.mention} has successfully vouched.\n"
                    f"Reference code: `{reference_code}`\n"
                    f"Verified by: {ctx.author.mention}",
        color=0x00ff00
    )
    await ctx.respond(embed=success_embed)


@bot.slash_command(description="Sends a voided warranty message to the specified user.")
@has_required_role()
async def warranty_voided(ctx: commands.Context, user: discord.User, reference_code):
    fail_embed = discord.Embed(
        title="Warranty Voided",
        description=f"The user {user.mention} did not submit a vouch.\n"
                    f"Reference code: `{reference_code}`\n"
                    f"Verified by: {ctx.author.mention}",
        color=0xff0000
    )
    await ctx.respond(embed=fail_embed)


@bot.slash_command(description="This command will generate a templated message for the payment method you are using.")
@has_required_role()
async def payment1(ctx: commands.Context):
    await ctx.respond(f'Sending payment method message. Let me cook for a sec.', ephemeral=True)
    space = "‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ "
    payment_embed = discord.Embed(
        title=f"{space}Payment Details !{space}",
        description=f"‎ \n"
                    f"{space}별 : **GCASH PAYMENT**{space}\n\n"
                    f"{space}星 : **09057868221 - m.c.**{space}\n\n"
                    f"<a:pink_arrow:1116611362861351045> no receipt, no proc.\n",
        color=0xffc0cb
    )
    await ctx.send(embed=payment_embed)


@bot.slash_command(description="This command will generate a templated message for the payment method you are using.")
@has_required_role()
async def payment2(ctx: commands.Context):
    await ctx.respond(f'Sending payment method message. Let me cook for a sec.', ephemeral=True)
    space = "‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ ‎ "
    payment_embed = discord.Embed(
        title=f"{space}Payment Details !{space}",
        description=f"‎ \n"
                    f"{space}별 : **GCASH PAYMENT**{space}\n\n"
                    f"{space}星 : **09690600063 - MRA**{space}\n\n"
                    f"<a:pink_arrow:1116611362861351045> no receipt, no proc.\n",
        color=0xffc0cb
    )
    await ctx.send(embed=payment_embed)


@bot.slash_command(description="List of available commands.")
@has_required_role()
async def help(ctx):
    embed = discord.Embed(title='Bot Commands', description='List of available commands:', color=discord.Color.blue())

    # Add commands and their functions
    embed.add_field(name='/stock', value='Display a list of items currently in stock.', inline=False)
    embed.add_field(name='/new', value='Create a new item from the stock list.', inline=False)
    embed.add_field(name='/delete', value='Remove a specific item from the stock list.', inline=False)
    embed.add_field(name='/edit', value='Modify the name and quantity of a specific item in the stock list.',
                    inline=False)
    embed.add_field(name='/settings', value='Retrieve and display the current configuration settings of the bot.',
                    inline=False)
    embed.add_field(name='/channel', value='Update the channel where vouches are recorded.', inline=False)
    embed.add_field(name='/moderator',
                    value='Modify the roles that have access to use the bot.',
                    inline=False)
    embed.add_field(name='/category', value='Specify the category where new support tickets will be created.',
                    inline=False)
    embed.add_field(name='/timer',
                    value='Adjust the duration (in hours) for the Warranty Verification process.', inline=False)
    embed.add_field(name='/warranty', value='Send a warranty activation message to a user.', inline=False)
    embed.add_field(name='/warranty_activated',
                    value='Sends an activated warranty message for the specified user.',
                    inline=False)
    embed.add_field(name='/warranty_voided', value='Sends a voided warranty message for the specified user.',
                    inline=False)
    embed.add_field(name='/payment1', value='Generate a templated message for the gcash number 09057868221.',
                    inline=False)
    embed.add_field(name='/payment2', value='Generate a templated message for the gcash number 09690600063.',
                    inline=False)
    await ctx.respond(embed=embed)


# Run the bot
bot.run(TOKEN)
