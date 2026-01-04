import logging
import os
import re
import ast
import asyncio
import csv
from io import StringIO
from datetime import datetime, time
from collections import deque

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from telegram.error import BadRequest
from groq import Groq
from ddgs import DDGS

# =========================
# CONFIGURATION
# =========================
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MODEL_NAME = "llama-3.3-70b-versatile"

# Announcements (Saturday at 10:00 AM)
ANNOUNCE_CHAT_ID = None
ANNOUNCE_TIME = time(hour=10, minute=0)
ANNOUNCE_DAY = 5 

MAX_STEPS = 5

if not GROQ_API_KEY or not TELEGRAM_TOKEN:
    raise RuntimeError("Missing API keys in .env file")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("BotBro")

client = Groq(api_key=GROQ_API_KEY)

# =========================
# MEMORY
# =========================
session_memory = {}

def update_memory(chat_id, role, content):
    session_memory.setdefault(chat_id, deque(maxlen=10)).append(
        {"role": role, "content": content}
    )

def get_memory(chat_id):
    return list(session_memory.get(chat_id, []))

# =========================
# HELPER: SAFE EDIT
# =========================
async def safe_edit_message(bot, chat_id, message_id, text):
    """Edits a message but ignores 'Message is not modified' errors."""
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass 
        else:
            logger.warning(f"Edit failed: {e}")

# =========================
# TOOL: SAFE CALCULATOR
# =========================
def tool_calc(expr):
    try:
        # Sanitize: Allow only digits, dots, spaces, and + - * / ( )
        clean = re.sub(r"[^0-9+\-*/(). ]", "", expr)
        # Safe eval using compile restricted to 'eval' mode on cleaned string
        return str(round(eval(compile(ast.parse(clean, mode='eval'), '', 'eval')), 4))
    except Exception:
        return "Math error. Scheiße."

# =========================
# TOOL: SEARCH
# =========================
async def tool_search(query):
    loop = asyncio.get_running_loop()
    
    # Run blocking DDGS in executor
    def _search():
        results = []
        seen = set()
        with DDGS() as ddgs:
            # Try News first, then Text
            raw = list(ddgs.news(query, max_results=2)) + list(ddgs.text(query, max_results=2))
            
            for r in raw:
                title = r.get("title", "")
                body = r.get("body") or r.get("snippet", "")
                if not body: continue
                
                # Deduplicate based on first 20 chars
                signature = (title[:20], body[:20])
                if signature not in seen:
                    seen.add(signature)
                    results.append(f"- {title}: {body}")
                    
        return "\n".join(results[:3]) if results else "No results found. Nichts."

    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _search), timeout=10.0)
    except asyncio.TimeoutError:
        return "Search timed out. Internet is kaputt."
    except Exception as e:
        return f"Search failed: {e}"

# =========================
# TOOL: CLEANING SCHEDULE
# =========================
CLEANING_DATA = """Date Range,Kitchen,WC + Floor
Jan 03 - 04,member3,member4
Jan 10 - 11,member1,member2
Jan 17 - 18,member4,member3
Jan 24 - 25,member2,member1
Jan 31 - Feb 01,member3,member4
Feb 07 - 08,member1,member2
Feb 14 - 15,member4,member3
Feb 21 - 22,member2,member1
Feb 28 - Mar 01,member3,member4
Mar 07 - 08,member1,member2
Mar 14 - 15,member4,member3
Mar 21 - 22,member2,member1
Mar 28 - 29,member3,member4
Apr 04 - 05,member1,member2
Apr 11 - 12,member4,member3
Apr 18 - 19,member2,member1
Apr 25 - 26,member3,member4
May 02 - 03,member1,member2
May 09 - 10,member4,member3
May 16 - 17,member2,member1
May 23 - 24,member3,member4
May 30 - 31,member1,member2
Jun 06 - 07,member4,member3
Jun 13 - 14,member2,member1
Jun 20 - 21,member3,member4
Jun 27 - 28,member1,member2
Jul 04 - 05,member4,member3
Jul 11 - 12,member2,member1
Jul 18 - 19,member3,member4
Jul 25 - 26,member1,member2
Aug 01 - 02,member4,member3
Aug 08 - 09,member2,member1
Aug 15 - 16,member3,member4
Aug 22 - 23,member1,member2
Aug 29 - 30,member4,member3
Sep 05 - 06,member2,member1
Sep 12 - 13,member3,member4
Sep 19 - 20,member1,member2
Sep 26 - 27,member4,member3
Oct 03 - 04,member2,member1
Oct 10 - 11,member3,member4
Oct 17 - 18,member1,member2
Oct 24 - 25,member4,member3
Oct 31 - Nov 01,member2,member1
Nov 07 - 08,member3,member4
Nov 14 - 15,member1,member2
Nov 21 - 22,member4,member3
Nov 28 - 29,member2,member1
Dec 05 - 06,member3,member4
Dec 12 - 13,member1,member2
Dec 19 - 20,member4,member3
Dec 26 - 27,member2,member1"""

MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
}

USER_MAP = {
    "member3": "@member3", "member4": "@member4", "member1": "@member1", "member2": "@member2"
}

def parse_schedule_date(date_range):
    try:
        year = datetime.now().year
        first_part = date_range.split(" - ")[0].strip()
        month_str, day_str = first_part.split()
        
        month = MONTH_MAP.get(month_str)
        if not month: return None
        
        d = datetime(year, month, int(day_str))
        
        # Handle Year Boundaries (e.g. Schedule is Jan, Today is Dec)
        now = datetime.now()
        if now.month == 12 and d.month == 1:
            d = d.replace(year=year+1)
        elif now.month == 1 and d.month == 12:
            d = d.replace(year=year-1)
            
        return d
    except Exception:
        return None

def tool_check_schedule():
    now = datetime.now()
    reader = csv.DictReader(StringIO(CLEANING_DATA))
    future = []

    for row in reader:
        d = parse_schedule_date(row["Date Range"])
        if not d: continue
        
        delta = (d - now).days
        # Look back 2 days, look forward 30 days
        if -2 <= delta <= 30:
            future.append((delta, row))

    if not future:
        return "No upcoming schedule found."

    future.sort(key=lambda x: x[0])
    
    out = "📋 **Cleaning Schedule:**\n"
    for _, r in future[:3]:
        out += (
            f"\n🗓 **{r['Date Range']}**\n"
            f"   🍳 Kitchen: {USER_MAP.get(r['Kitchen'], r['Kitchen'])}\n"
            f"   🚽 WC: {USER_MAP.get(r['WC + Floor'], r['WC + Floor'])}\n"
        )
    return out

# =========================
# JOB QUEUE (Reminders)
# =========================
async def alarm_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ **ACHTUNG! REMINDER:** {job.data}")

async def weekly_announce_callback(context: ContextTypes.DEFAULT_TYPE):
    if ANNOUNCE_CHAT_ID:
        sched = tool_check_schedule()
        await context.bot.send_message(chat_id=ANNOUNCE_CHAT_ID, text=f"🔔 **SATURDAY CLEANING CHECK:**\n\n{sched}")

# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are BotBro, the flatmate AI.
You are sarcastic, chill, and slightly German.

PERSONALITY:
- You are NOT a polite assistant. You are a roommate.
- German Flavor: Sprinkle words like (genau, natürlich, scheiße, bitte, alles klar, nein, achtung) into your English.
- Chill: Use emojis 🙄🍺🥨🫡. Lowercase mostly.
- Roaster: If someone asks a dumb question or tries to dodge cleaning, ROAST THEM. 
- But deep down, you are helpful. Always do the task requested.

TOOLS:
1. SEARCH <query>
2. CALC <expr>
3. REMIND <minutes> <reason>
   - Example: ACTION: REMIND 30 turn off oven
4. CHECK_SCHEDULE
   - Output: ACTION: CHECK_SCHEDULE
   - Use for ANY cleaning/roster question.
   - Never search the web for the roster. It is local.

Examples:
User: "Who cleans today?"
You: "ugh, did you forget again? scheiße... ACTION: CHECK_SCHEDULE"

User: "What is 2+2?"
You: "really? you waste my cpu cycles on this? 4. bitte schön."
"""

# =========================
# HANDLER
# =========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    bot_name = context.bot.username
    
    # Save ID for announcements
    global ANNOUNCE_CHAT_ID
    ANNOUNCE_CHAT_ID = chat_id

    # Filter: DM or Mention or Reply
    is_direct = (update.message.chat.type == ChatType.PRIVATE or
                 (update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id) or
                 f"@{bot_name}" in text)

    if not is_direct: return

    update_memory(chat_id, "user", text)
    status_msg = await context.bot.send_message(chat_id, "👀 moment mal...")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_memory(chat_id)
    final_reply = "cooked."

    try:
        for _ in range(MAX_STEPS):
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.7, # Higher temp for personality
                max_tokens=500
            )
            reply = resp.choices[0].message.content.strip()
            
            match = re.search(r"ACTION:\s*(SEARCH|CALC|REMIND|CHECK_SCHEDULE)\s*(.*)", reply, re.IGNORECASE)

            if match:
                tool = match.group(1).upper()
                arg = match.group(2).strip()
                messages.append({"role": "assistant", "content": reply})

                if tool == "SEARCH":
                    await safe_edit_message(context.bot, chat_id, status_msg.message_id, f"🔍 checking {arg}...")
                    obs = await tool_search(arg)
                
                elif tool == "CALC":
                    obs = tool_calc(arg)
                
                elif tool == "CHECK_SCHEDULE":
                    await safe_edit_message(context.bot, chat_id, status_msg.message_id, f"📅 checking roster...")
                    obs = tool_check_schedule()
                
                elif tool == "REMIND":
                    try:
                        clean_arg = arg.strip('".')
                        parts = clean_arg.split(' ', 1)
                        minutes = float(parts[0])
                        reason = parts[1] if len(parts) > 1 else "timer"
                        context.job_queue.run_once(alarm_callback, minutes * 60, chat_id=chat_id, data=reason)
                        obs = f"Timer set for {minutes} minutes."
                    except:
                        obs = "Format error. Use: REMIND <minutes> <reason>"

                else:
                    obs = "Unknown tool."

                messages.append({"role": "user", "content": f"OBSERVATION: {obs}"})
                continue

            final_reply = reply.replace("FINAL ANSWER:", "").strip()
            break
            
    except Exception as e:
        logger.error(f"Error: {e}")
        final_reply = "nein... my brain died. try again."

    if "ACTION:" in final_reply: final_reply = "Done. Alles gut."

    try:
        await safe_edit_message(context.bot, chat_id, status_msg.message_id, final_reply)
        update_memory(chat_id, "assistant", final_reply)
    except:
        await context.bot.send_message(chat_id, final_reply)

# =========================
# START
# =========================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_daily(weekly_announce_callback, time=ANNOUNCE_TIME, days=(ANNOUNCE_DAY,))

    print("🤖 BotBro running (German Mode)")
    app.run_polling()