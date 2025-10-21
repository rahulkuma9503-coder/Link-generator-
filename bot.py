import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)
from datetime import datetime, timedelta
import asyncio
from aiohttp import web

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = int(os.environ.get('OWNER_ID', 0))
PORT = int(os.environ.get('PORT', 5000))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')
SUPPORT_GROUP = os.environ.get('SUPPORT_GROUP', '')
UPDATE_CHANNEL = os.environ.get('UPDATE_CHANNEL', '')

class TelegramBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.group_links = {}
        self.stats = {
            'links_generated': 0,
            'broadcasts_sent': 0,
            'groups_served': set()
        }
        self.setup_handlers()
        self.setup_server()

    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("link", self.generate_link))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast))
        self.application.add_handler(CommandHandler("setexpire", self.set_expire_time))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        self.application.add_handler(MessageHandler(filters.ALL, self.handle_message))

    def setup_server(self):
        # Create a simple web server to keep the app alive on Render
        async def handle(request):
            return web.Response(text="Bot is running!")

        self.app = web.Application()
        self.app.router.add_get('/', handle)
        self.app.router.add_get('/health', handle)
        
        # Create a runner for the web server
        self.runner = web.AppRunner(self.app)

    async def start_server(self):
        # Start the web server
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', PORT)
        await self.site.start()
        logger.info(f"Web server started on port {PORT}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            # Get bot info for the add to group link
            bot_info = await self.application.bot.get_me()
            bot_username = bot_info.username
            
            # Create keyboard with buttons
            keyboard = []
            
            # Add "Add to Group" button
            keyboard.append([InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{bot_username}?startgroup=true")])
            
            if UPDATE_CHANNEL:
                keyboard.append([InlineKeyboardButton("📢 Update Channel", url=f"https://t.me/{UPDATE_CHANNEL}")])
            
            if SUPPORT_GROUP:
                keyboard.append([InlineKeyboardButton("💬 Support Group", url=f"https://t.me/{SUPPORT_GROUP}")])
                
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            welcome_text = (
                "Hello! I'm a bot that generates temporary invite links for groups.\n\n"
                "Add me to a group and use /link to generate an invite link that automatically expires after 5-10 minutes!\n\n"
                "Group admins can use /setexpire to configure the expiration time."
            )
            
            await update.message.reply_text(welcome_text, reply_markup=reply_markup)

    async def generate_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Only work in groups
        if update.effective_chat.type == "private":
            await update.message.reply_text("This command only works in groups!")
            return
            
        # Try to delete the user's /link command message
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete user message: {e}")
            # Continue execution even if message deletion fails
            
        chat = update.effective_chat
        message_thread_id = update.effective_message.message_thread_id
        expire_time = context.chat_data.get('expire_time', 300)  # Default 5 minutes
        
        try:
            # Check if bot has permission to create invite links
            bot_member = await chat.get_member(context.bot.id)
            if not bot_member.can_invite_users:
                response = await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=message_thread_id,
                    text="I need permission to create invite links! Please make me an admin with 'Invite Users' permission.",
                    disable_web_page_preview=True
                )
                return
                
            invite_link = await chat.create_invite_link(
                name=f"AutoGenerated_{datetime.now().timestamp()}",
                creates_join_request=False,
                expire_date=datetime.now() + timedelta(seconds=expire_time),
                member_limit=1
            )
            
            # Store message ID for later deletion
            self.group_links[chat.id] = {
                'link': invite_link.invite_link,
                'expire_time': datetime.now() + timedelta(seconds=expire_time),
                'message_id': None,
                'thread_id': message_thread_id
            }
            
            # Update stats
            self.stats['links_generated'] += 1
            self.stats['groups_served'].add(chat.id)
            
            keyboard = [
                [InlineKeyboardButton("Revoke Now", callback_data=f"revoke_{chat.id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text=f"Group invite link generated!\n"
                     f"Link: {invite_link.invite_link}\n"
                     f"Expires in {expire_time//60} minutes",
                reply_markup=reply_markup,
                disable_web_page_preview=True  # Disable link preview
            )
            
            # Store message ID for later deletion
            self.group_links[chat.id]['message_id'] = message.message_id
            
            # Schedule automatic revocation
            asyncio.create_task(self.revoke_link_after_delay(chat.id, expire_time))
            
        except Exception as e:
            logger.error(f"Error generating invite link: {e}")
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text="Error generating invite link. Please make sure I'm an admin with 'Invite Users' permission.",
                disable_web_page_preview=True
            )

    async def revoke_link_after_delay(self, chat_id, delay_seconds):
        await asyncio.sleep(delay_seconds)
        if chat_id in self.group_links:
            try:
                # Delete the message with the link
                await self.application.bot.delete_message(
                    chat_id=chat_id,
                    message_id=self.group_links[chat_id]['message_id']
                )
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
                # If deletion fails, edit the message to show link expired
                try:
                    await self.application.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=self.group_links[chat_id]['message_id'],
                        text="Invite link has expired!",
                        reply_markup=None
                    )
                except:
                    pass  # Message might be deleted or not editable
            finally:
                # Remove from storage
                if chat_id in self.group_links:
                    del self.group_links[chat_id]

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Handle group messages and topic messages
        if update.effective_chat.type != "private":
            # Check if bot was added to group
            if update.message and update.message.new_chat_members:
                for member in update.message.new_chat_members:
                    if member.id == context.bot.id:
                        await self.send_welcome_message(update, context)

    async def send_welcome_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        message_thread_id = update.effective_message.message_thread_id
        
        # Create keyboard with buttons
        keyboard = []
        
        if UPDATE_CHANNEL:
            keyboard.append([InlineKeyboardButton("📢 Update Channel", url=f"https://t.me/{UPDATE_CHANNEL}")])
        
        if SUPPORT_GROUP:
            keyboard.append([InlineKeyboardButton("💬 Support Group", url=f"https://t.me/{SUPPORT_GROUP}")])
            
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        welcome_text = (
            "Thanks for adding me to this group!\n\n"
            "I can generate temporary invite links with auto-expiration.\n\n"
            "Commands:\n"
            "/link - Generate a temporary invite link\n"
            "/setexpire <minutes> - Set link expiration time (admin only)\n\n"
            "To generate a link, just type /link in the group chat!"
        )
        
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=message_thread_id,
            text=welcome_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith('revoke_'):
            chat_id = int(query.data.split('_')[1])
            if chat_id in self.group_links:
                try:
                    # Delete the message with the link
                    await self.application.bot.delete_message(
                        chat_id=chat_id,
                        message_id=self.group_links[chat_id]['message_id']
                    )
                except Exception as e:
                    logger.error(f"Error deleting message: {e}")
                    # If deletion fails, edit the message
                    try:
                        await query.edit_message_text(
                            text="Invite link revoked!",
                            reply_markup=None
                        )
                    except:
                        # If editing fails, send a new message
                        try:
                            message_thread_id = query.message.message_thread_id
                            await self.application.bot.send_message(
                                chat_id=chat_id,
                                message_thread_id=message_thread_id,
                                text="Invite link revoked!",
                                disable_web_page_preview=True
                            )
                        except:
                            pass
                finally:
                    # Remove from storage
                    if chat_id in self.group_links:
                        del self.group_links[chat_id]

    async def set_expire_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        message_thread_id = update.effective_message.message_thread_id
        
        # Check if user is admin
        try:
            user = await chat.get_member(update.effective_user.id)
            if user.status not in ['administrator', 'creator']:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=message_thread_id,
                    text="You need to be an admin to use this command!",
                    disable_web_page_preview=True
                )
                return
        except:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text="Error checking admin status.",
                disable_web_page_preview=True
            )
            return
        
        if len(context.args) == 0:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text="Usage: /setexpire <minutes>",
                disable_web_page_preview=True
            )
            return
        
        try:
            minutes = int(context.args[0])
            if minutes < 1 or minutes > 60:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=message_thread_id,
                    text="Please enter a value between 1-60 minutes",
                    disable_web_page_preview=True
                )
                return
            
            context.chat_data['expire_time'] = minutes * 60
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text=f"Expire time set to {minutes} minutes",
                disable_web_page_preview=True
            )
            
        except ValueError:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text="Please enter a valid number",
                disable_web_page_preview=True
            )

    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        message_thread_id = update.effective_message.message_thread_id
        
        if update.effective_user.id != OWNER_ID:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text="You are not authorized to use this command!",
                disable_web_page_preview=True
            )
            return
        
        # Check if it's a reply to a message
        if not update.message.reply_to_message:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message_thread_id,
                text="Please reply to a message with /broadcast to broadcast it.",
                disable_web_page_preview=True
            )
            return
        
        # Get the replied message
        replied_message = update.message.reply_to_message
        
        # Track broadcast progress
        success_count = 0
        fail_count = 0
        
        # Send broadcast to all groups where the bot has generated links
        for chat_id in self.group_links.keys():
            try:
                # Forward the replied message
                await replied_message.forward(chat_id=chat_id)
                success_count += 1
            except Exception as e:
                logger.error(f"Broadcast error for {chat_id}: {e}")
                fail_count += 1
        
        # Update stats
        self.stats['broadcasts_sent'] += 1
        
        # Send broadcast report to owner
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"Broadcast completed!\n\nSuccess: {success_count}\nFailed: {fail_count}",
            disable_web_page_preview=True
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("You are not authorized to use this command!")
            return
        
        # Calculate stats
        active_groups = len(self.group_links)
        total_groups_served = len(self.stats['groups_served'])
        links_generated = self.stats['links_generated']
        broadcasts_sent = self.stats['broadcasts_sent']
        
        stats_text = (
            "📊 Bot Statistics\n\n"
            f"• Active Groups: {active_groups}\n"
            f"• Total Groups Served: {total_groups_served}\n"
            f"• Links Generated: {links_generated}\n"
            f"• Broadcasts Sent: {broadcasts_sent}\n\n"
            f"• Uptime: {self.get_uptime()}"
        )
        
        await update.message.reply_text(stats_text, disable_web_page_preview=True)

    def get_uptime(self):
        # Calculate uptime (this is a simple implementation)
        # You might want to track start time for more accurate uptime
        return "Since last restart"

    async def run(self):
        # Start the web server
        await self.start_server()
        
        # Start the bot
        if WEBHOOK_URL:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path=BOT_TOKEN,
                webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
            )
        else:
            # Use polling for local development
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
        
        logger.info("Bot started successfully")
        
        # Keep the application running
        await asyncio.Event().wait()

    async def shutdown(self):
        # Shutdown the bot
        if self.application.updater:
            await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        
        # Shutdown the web server
        await self.runner.cleanup()

if __name__ == "__main__":
    bot = TelegramBot()
    
    try:
        # Run the bot and web server
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {e}")
    finally:
        asyncio.run(bot.shutdown())
