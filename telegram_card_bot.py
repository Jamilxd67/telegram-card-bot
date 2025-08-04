import logging
import os
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import asyncio
import threading

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store user search contexts
user_contexts = {}

def extract_matching_cards(card_numbers, prefix):
    """
    Extracts card numbers from the list that start with the specified prefix.

    Parameters:
    card_numbers (list of str): A list of card numbers as strings.
    prefix (str): The prefix to match at the start of the card numbers.

    Returns:
    list of str: A list containing card numbers that start with the specified prefix.
    """
    return [card for card in card_numbers if card.startswith(prefix)]

def read_card_numbers_from_file(file_path):
    """
    Reads card numbers from a text file. Each line in the file should contain one card number.

    Parameters:
    file_path (str): The path to the text file containing card numbers.

    Returns:
    list of str: A list of card numbers read from the file.
    """
    try:
        with open(file_path, 'r') as file:
            card_numbers = file.read().splitlines()
        return [card.strip() for card in card_numbers if card.strip()]
    except FileNotFoundError:
        return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    welcome_message = f"""🤖 Card Number Extractor Bot

Hello {user.first_name}! Welcome to the bot!

I can help you extract card numbers that start with specific prefixes.

How to use:
1. Use /search <prefix> to start searching
2. Upload your card numbers file when prompted
3. Get matching cards as a downloadable text file

Example:
/search 37918 - Find all cards starting with 37918

Ready to start? Use /search followed by your desired prefix!

👤 Bot Owner: @AHNAF_IS_HERE"""
    
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = """
🔍 *How to use this bot:*

*Workflow:*
1\. Use `/search <prefix>` to start searching
2\. Upload your card numbers file when prompted
3\. Get matching cards as a downloadable text file

*Commands:*
• `/start` - Start the bot and see welcome message
• `/search <prefix>` - Search for card numbers starting with prefix
• `/help` - Show this help message

*Examples:*
• `/search 4532` - Find cards starting with 4532
• `/search 37918` - Find cards starting with 37918

*Supported file formats:*
• `cardnumber|mm|yy|cvv`
• `cardnumber`
• One card per line
• Max file size: 10MB

*Note:* Each search processes your uploaded file and returns results as a downloadable text file\.
    """
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show statistics about the current card database."""
    card_numbers = read_card_numbers_from_file('card_numbers.txt')
    
    if not card_numbers:
        await update.message.reply_text(
            "❌ No card database found. Please upload a file first."
        )
        return
    
    # Analyze prefixes
    prefix_counts = {}
    for card in card_numbers[:5000]:  # Analyze first 5000 for performance
        if len(card) >= 4:
            prefix = card[:4]
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
    
    # Get top 10 prefixes
    top_prefixes = sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    response = f"📊 *Database Statistics*\n\n"
    response += f"• Total cards: `{len(card_numbers):,}`\n"
    response += f"• Unique prefixes: `{len(prefix_counts)}`\n\n"
    
    response += f"🔝 *Top 10 Prefixes:*\n"
    for i, (prefix, count) in enumerate(top_prefixes, 1):
        response += f"`{i:2d}. {prefix}` - {count:,} cards\n"
    
    response += f"\n💡 Use `/search <prefix>` to find specific cards"
    
    await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN_V2)

async def search_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search for cards with the given prefix - asks for file upload first."""
    if not context.args:
        await update.message.reply_text(
            "❌ Please provide a prefix to search for.\n\n"
            "Example: /search 37918"
        )
        return
    
    prefix = context.args[0]
    user_id = update.effective_user.id
    
    # Store the search prefix for this user
    user_contexts[user_id] = {'prefix': prefix, 'waiting_for_file': True}
    
    await update.message.reply_text(
        f"🔍 Searching for cards starting with: {prefix}\n\n"
        f"📤 Please upload your card numbers text file now.\n\n"
        f"Supported formats:\n"
        f"• cardnumber|mm|yy|cvv\n"
        f"• cardnumber\n"
        f"• One card per line\n"
        f"• Max file size: 10MB"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded documents (card numbers file) and process search if user is waiting."""
    document = update.message.document
    user_id = update.effective_user.id
    
    # Send processing message
    processing_msg = await update.message.reply_text("📤 Processing your file...")
    
    if not document.file_name.endswith('.txt'):
        await processing_msg.edit_text(
            "❌ Please upload a .txt file containing card numbers (one per line).\n\n"
            "📋 *Supported formats:*\n"
            "• Plain text files (.txt)\n"
            "• One card number per line\n"
            "• Format: `cardnumber|mm|yy|cvv` or just `cardnumber`"
        )
        return
    
    try:
        # Check file size (Telegram limit is 20MB, but let's be conservative)
        if document.file_size > 10 * 1024 * 1024:  # 10MB limit
            await processing_msg.edit_text(
                "❌ File too large! Please upload a file smaller than 10MB."
            )
            return
        
        # Download the file
        file = await context.bot.get_file(document.file_id)
        temp_file_path = f'temp_cards_{user_id}.txt'
        await file.download_to_drive(temp_file_path)
        
        # Verify the file content
        card_numbers = read_card_numbers_from_file(temp_file_path)
        
        if not card_numbers:
            await processing_msg.edit_text(
                "❌ The uploaded file appears to be empty or contains no valid card numbers.\n\n"
                "Please check your file format."
            )
            return
        
        # Check if user is waiting for file upload after search command
        if user_id in user_contexts and user_contexts[user_id].get('waiting_for_file'):
            prefix = user_contexts[user_id]['prefix']
            
            # Extract matching cards
            matching_cards = extract_matching_cards(card_numbers, prefix)
            
            if not matching_cards:
                await processing_msg.edit_text(
                    f"❌ No cards found starting with prefix: `{prefix}`\n\n"
                    f"📊 Total cards processed: `{len(card_numbers):,}`\n"
                    f"Try a different prefix or check your search term.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                # Clear user context
                del user_contexts[user_id]
                return
            
            # Create results file
            results_filename = f'cards_{prefix}_{len(matching_cards)}_results.txt'
            with open(results_filename, 'w') as f:
                for card in matching_cards:
                    f.write(card + '\n')
            
            # Send results file
            with open(results_filename, 'rb') as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=results_filename,
                    caption=f"🎉 Search Results\n\n"
                           f"🔍 Prefix: {prefix}\n"
                           f"📊 Found: {len(matching_cards):,} cards\n"
                           f"📁 Total processed: {len(card_numbers):,} cards\n\n"
                           f"📥 Download the file above to get all matching cards!"
                )
            
            # Clean up files
            os.remove(results_filename)
            os.remove(temp_file_path)
            
            # Clear user context
            del user_contexts[user_id]
            
            # Delete processing message
            await processing_msg.delete()
            
        else:
            # Regular file upload without search context
            await processing_msg.edit_text(
                f"✅ *File uploaded successfully!*\n\n"
                f"📊 *Statistics:*\n"
                f"• Total cards loaded: `{len(card_numbers):,}`\n"
                f"• File size: `{document.file_size:,} bytes`\n\n"
                f"💡 Use `/search <prefix>` to find specific cards!",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            # Clean up temp file
            os.remove(temp_file_path)
        
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await processing_msg.edit_text(
            "❌ Error processing the file. Please make sure it's a valid text file.\n\n"
            f"Error details: `{str(e)}`"
        )
        # Clear user context on error
        if user_id in user_contexts:
            del user_contexts[user_id]

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages that aren't commands."""
    await update.message.reply_text(
        "🤔 I didn't understand that command.\n\n"
        "Use `/help` to see available commands or `/search <prefix>` to search for cards."
    )

# Flask app for webhook
app = Flask(__name__)

# Get bot token from environment variable (more secure)
BOT_TOKEN = os.getenv('BOT_TOKEN', '7706440354:AAFjos7T0P2yyx9evYYdH3zgO0QAMkqrFoo')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')

# Create the Application
application = Application.builder().token(BOT_TOKEN).build()

# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("search", search_cards))
application.add_handler(CommandHandler("stats", stats_command))
application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

@app.route('/')
def health_check():
    """Health check endpoint for Render"""
    return "🤖 Telegram Card Bot is running!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook from Telegram"""
    try:
        # Get JSON data from request
        json_data = request.get_json(force=True)
        
        # Validate that we have proper Telegram update data
        if not json_data or 'update_id' not in json_data:
            logger.warning("Invalid webhook data received")
            return "OK", 200  # Return OK to avoid Telegram retries
        
        # Create update object from Telegram data
        update = Update.de_json(json_data, application.bot)
        
        # Process the update asynchronously in a thread-safe way
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.process_update(update))
        loop.close()
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return "OK", 200  # Return OK to avoid Telegram retries

async def set_webhook():
    """Set up the webhook with Telegram"""
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/webhook"
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to: {webhook_url}")
    else:
        logger.warning("WEBHOOK_URL not set, webhook not configured")

def run_async_in_thread():
    """Run async operations in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def setup():
        # Initialize the application
        await application.initialize()
        await application.start()
        
        # Set up webhook
        await set_webhook()
        
        logger.info("🤖 Bot initialized and webhook set up!")
    
    loop.run_until_complete(setup())

def main():
    """Start the bot with Flask webhook server"""
    print("🤖 Starting Telegram Card Bot...")
    
    # Start async operations in background thread
    thread = threading.Thread(target=run_async_in_thread)
    thread.daemon = True
    thread.start()
    
    # Get port from environment (Render provides this)
    port = int(os.getenv('PORT', 5000))
    
    print(f"🌐 Starting Flask server on port {port}")
    print("🔗 Webhook endpoint: /webhook")
    print("❤️ Health check: /")
    
    # Start Flask app
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == '__main__':
    main()
