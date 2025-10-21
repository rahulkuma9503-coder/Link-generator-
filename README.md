# Telegram Group Link Bot

A Telegram bot that generates temporary invite links for groups with auto-expiration feature.

## Features

- Generate group invite links with `/link` command
- Customizable expiration time (1-60 minutes) with `/setexpire`
- Automatic link revocation after set time
- Support for topic chats and anonymous admins
- Broadcast functionality for bot owner
- Support for all media types and formatting

## Setup

1. Create a new bot with [BotFather](https://t.me/BotFather) and get the API token
2. Get your Telegram user ID (use @userinfobot)
3. Deploy to Render:
   - Fork this repository
   - Connect your GitHub account to Render
   - Create a new Web Service from your forked repository
   - Add environment variables:
     - `BOT_TOKEN`: Your bot token from BotFather
     - `OWNER_ID`: Your Telegram user ID
   - Deploy

## Commands

- `/start` - Start the bot in private chat
- `/link` - Generate a temporary invite link (group admin only)
- `/setexpire <minutes>` - Set link expiration time (admin only)
- `/broadcast <message>` - Broadcast message to all groups (owner only)

## Local Development

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set environment variables:
   ```bash
   export BOT_TOKEN=your_bot_token
   export OWNER_ID=your_user_id
