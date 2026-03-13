import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import time
import asyncio
import requests

# ============================================
# CONFIG
# ============================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CLIENT_ID = "1481838867437977792"
ACCOUNTS_FREE_FILE = "accounts_free.txt"
ACCOUNTS_PAID_FILE = "accounts_paid.txt"
USED_FILE = "used_accounts.txt"
COOLDOWNS_FREE_FILE = "cooldowns_free.json"
COOLDOWNS_PAID_FILE = "cooldowns_paid.json"

ADMIN_ROLE_ID   = 1480274903914647644
PAID_ROLE_ID    = 1481841458502701217
FREE_ROLE_ID    = 1480276864357499011

COOLDOWN_SECONDS = 600  # 10 minutes
MAX_PER_WINDOW   = 2

# ============================================
# HELPERS
# ============================================

def has_role(user, role_id):
    return any(r.id == role_id for r in user.roles)

def is_admin(user):
    return has_role(user, ADMIN_ROLE_ID)

def is_paid(user):
    return has_role(user, PAID_ROLE_ID)

def is_free(user):
    return has_role(user, FREE_ROLE_ID)

# ============================================
# GUERRILLA MAIL INBOX CHECKER
# ============================================

def guerrilla_inbox(email_address):
    try:
        session = requests.Session()
        session.proxies = {'http': None, 'https': None}
        session.trust_env = False
        r = session.get('https://api.guerrillamail.com/ajax.php',
                        params={'f': 'get_email_address'}, timeout=10)
        sid = r.json().get('sid_token')
        local = email_address.split('@')[0]
        session.get('https://api.guerrillamail.com/ajax.php',
                    params={'f': 'set_email_user', 'email_user': local, 'sid_token': sid}, timeout=10)
        r2 = session.get('https://api.guerrillamail.com/ajax.php',
                         params={'f': 'check_email', 'sid_token': sid, 'seq': 0}, timeout=10)
        return r2.json().get('list', [])
    except Exception:
        return []

# ============================================
# ACCOUNT MANAGEMENT
# ============================================

def load_cooldowns(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r') as f:
        return json.load(f)

def save_cooldowns(data, filename):
    with open(filename, 'w') as f:
        json.dump(data, f)

def load_accounts(filename):
    if not os.path.exists(filename):
        return []
    with open(filename, 'r') as f:
        return [line.strip() for line in f if ':' in line.strip()]

def save_accounts(accounts, filename):
    with open(filename, 'w') as f:
        for acc in accounts:
            f.write(acc + '\n')

def mark_used(account_line, user_id):
    with open(USED_FILE, 'a') as f:
        f.write(f"{account_line} | used_by:{user_id} | time:{int(time.time())}\n")

def get_user_account(user_id):
    if not os.path.exists(USED_FILE):
        return None
    with open(USED_FILE, 'r') as f:
        lines = f.readlines()
    for line in reversed(lines):
        if f"used_by:{user_id}" in line:
            return line.split(' | ')[0].strip()
    return None

async def give_account(interaction, tier_label):
    """Shared logic for both /gen and /gen-paid"""
    await interaction.response.defer(ephemeral=True)

    user = interaction.user
    user_id = str(user.id)
    admin = is_admin(user)
    filename = ACCOUNTS_PAID_FILE if tier_label == "paid" else ACCOUNTS_FREE_FILE
    cooldowns_file = COOLDOWNS_PAID_FILE if tier_label == "paid" else COOLDOWNS_FREE_FILE

    cooldowns = load_cooldowns(cooldowns_file)
    now = time.time()
    raw = cooldowns.get(user_id, None)

    if raw is None or not isinstance(raw, dict):
        user_data = {"count": 0, "window_start": now}
    else:
        user_data = raw

    if now - user_data["window_start"] >= COOLDOWN_SECONDS:
        user_data = {"count": 0, "window_start": now}

    if not admin and user_data["count"] >= MAX_PER_WINDOW:
        remaining = COOLDOWN_SECONDS - (now - user_data["window_start"])
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        await interaction.followup.send(
            f"You've used your **{MAX_PER_WINDOW} free accounts**. Try again in **{mins}m {secs}s**.", ephemeral=True
        )
        return

    accounts = load_accounts(filename)
    if not accounts:
        await interaction.followup.send("No accounts **in stock** right now. Check back later.", ephemeral=True)
        return

    account = accounts.pop(0)
    save_accounts(accounts, filename)
    mark_used(account, user_id)

    user_data["count"] += 1
    cooldowns[user_id] = user_data
    save_cooldowns(cooldowns, cooldowns_file)

    email, password = account.split(':', 1)

    instructions = (
        "• Go to **secure.oculus.com** or the Meta Quest app\n"
        "• Login with the credentials provided by the bot\n"
        "• If it asks for a code do **/inbox** to get code, change email/pass if u want\n"
        "• Upload the picture of the old guy for selfie verification"
        if tier_label == "free" else
        "• Go to **secure.oculus.com** or the Meta Quest app\n"
        "• Login with the credentials provided by the bot\n"
        "• If it asks for a code do **/inbox** to get code, change email/pass if u want"
    )
    embed = discord.Embed(title="Meta / Oculus Account", color=0xFFFFFF)
    embed.add_field(name="**Email**", value=f"`{email}`", inline=False)
    embed.add_field(name="**Password**", value=f"`{password}`", inline=False)
    embed.add_field(name="**Instructions**", value=instructions, inline=False)
    embed.set_footer(text="WR Gen")

    try:
        await user.send(embed=embed)
        if tier_label == "free":
            await user.send("https://media.discordapp.net/attachments/1480766903243767910/1481851689672773642/senior-caucasian-man-happy-selfie.png?ex=69b4d16e&is=69b37fee&hm=715f9ff6bdc1eded660b90bbb5d2b6288be451b42095a12b1d42d82a54b14fb6&=&format=webp&quality=lossless")
        await interaction.followup.send("Account sent to your **DMs**.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            f"Account (enable DMs next time):\n```{email}:{password}```", ephemeral=True
        )

# ============================================
# BOT SETUP
# ============================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    await tree.sync()
    print(f"[BOT] Logged in as {bot.user}")
    print(f"[BOT] Slash commands synced")

# ============================================
# /gen  (free role)
# ============================================

@tree.command(name="gen", description="Generate a Meta/Oculus account")
async def gen_free(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not (is_free(interaction.user) or is_paid(interaction.user) or is_admin(interaction.user)):
        await interaction.response.send_message("You don't have **access** to use this.", ephemeral=True)
        return
    await give_account(interaction, "free")

# ============================================
# /gen-paid  (paid role)
# ============================================

@tree.command(name="gen-paid", description="Generate a Meta/Oculus account (paid)")
async def gen_paid(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not (is_paid(interaction.user) or is_admin(interaction.user)):
        await interaction.response.send_message("You don't have **access** to use this.", ephemeral=True)
        return
    await give_account(interaction, "paid")

# ============================================
# /stock  (free role)
# ============================================

@tree.command(name="stock", description="Check how many accounts are available")
async def stock_free(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not (is_free(interaction.user) or is_paid(interaction.user) or is_admin(interaction.user)):
        await interaction.response.send_message("You don't have **access** to use this.", ephemeral=True)
        return
    free_count = len(load_accounts(ACCOUNTS_FREE_FILE))
    paid_count = len(load_accounts(ACCOUNTS_PAID_FILE))
    embed = discord.Embed(title="Account Stock", color=0xFFFFFF)
    embed.add_field(name="Free Stock", value=f"**{free_count}** account(s)", inline=True)
    embed.add_field(name="Paid Stock", value=f"**{paid_count}** account(s)", inline=True)
    embed.set_footer(text="WR Gen")
    await interaction.response.send_message(embed=embed)

# ============================================
# /inbox  (free + paid + admin)
# ============================================

@tree.command(name="inbox", description="Check a guerrillamail inbox for a verification code")
@app_commands.describe(email="The guerrillamail address to check (leave blank to use your last generated account)")
async def inbox(interaction: discord.Interaction, email: str = None):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not (is_free(interaction.user) or is_paid(interaction.user) or is_admin(interaction.user)):
        await interaction.response.send_message("You don't have **access** to use this.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    user_id = str(interaction.user.id)

    if not email:
        account = get_user_account(user_id)
        if not account:
            await interaction.followup.send("You haven't generated an account yet. Use **/gen** first, or provide an email.", ephemeral=True)
            return
        email = account.split(':')[0]

    guerrilla_domains = [
        'guerrillamail.com', 'guerrillamail.net', 'guerrillamail.org',
        'guerrillamail.biz', 'guerrillamail.de', 'grr.la', 'spam4.me',
        'guerrillamailblock.com', 'sharklasers.com'
    ]

    domain = email.split('@')[-1]
    if domain not in guerrilla_domains:
        await interaction.followup.send(f"Inbox check only works for **GuerrillaMail** addresses.\nYour email: `{email}`", ephemeral=True)
        return

    emails = await asyncio.get_event_loop().run_in_executor(None, guerrilla_inbox, email)

    if not emails:
        await interaction.followup.send(f"No emails found in `{email}`", ephemeral=True)
        return

    import re

    def find_code(text):
        m = re.search(r'\b(\d{6})\b', text or '')
        return m.group(1) if m else None

    code_found = None
    meta_emails = []

    for msg in emails:
        sender = msg.get('mail_from', '')
        if 'meta.com' not in sender and 'oculus.com' not in sender:
            continue
        meta_emails.append(msg)
        subject = msg.get('mail_subject', '') or ''
        excerpt = msg.get('mail_excerpt', '') or ''
        code_found = code_found or find_code(subject) or find_code(excerpt)
        if not code_found:
            try:
                msg_id = msg.get('mail_id') or msg.get('id', '')
                if msg_id:
                    sid_r = requests.get('https://api.guerrillamail.com/ajax.php',
                                         params={'f': 'get_email_address'}, timeout=10)
                    sid = sid_r.json().get('sid_token')
                    local = email.split('@')[0]
                    requests.get('https://api.guerrillamail.com/ajax.php',
                                 params={'f': 'set_email_user', 'email_user': local, 'sid_token': sid}, timeout=10)
                    full_r = requests.get('https://api.guerrillamail.com/ajax.php',
                                          params={'f': 'fetch_email', 'email_id': msg_id, 'sid_token': sid}, timeout=10)
                    full_body = full_r.json().get('mail_body', '') or ''
                    code_found = find_code(re.sub(r'<[^>]+>', ' ', full_body))
            except Exception:
                pass

    if not meta_emails:
        await interaction.followup.send(f"No Meta emails found yet in `{email}`. Try again in a moment.", ephemeral=True)
        return

    embed = discord.Embed(title=f"Inbox — {email}", color=0xFFFFFF)
    if code_found:
        embed.add_field(name="Verification Code", value=f"**`{code_found}`**", inline=False)
    else:
        embed.add_field(name="Verification Code", value="Not found yet — try again in a moment.", inline=False)
    for msg in meta_emails[:3]:
        subject = msg.get('mail_subject', 'No subject')
        embed.add_field(name=subject, value=f"**From:** {msg.get('mail_from', '')}", inline=False)
    embed.set_footer(text="WR Gen")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ============================================
# /addaccounts  (admin only)
# ============================================

@tree.command(name="addaccounts", description="[Admin] Add accounts to stock")
@app_commands.describe(tier="free or paid", accounts="email:password lines")
async def addaccounts(interaction: discord.Interaction, tier: str, accounts: str):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not is_admin(interaction.user):
        await interaction.response.send_message("You don't have **permission** to use this.", ephemeral=True)
        return

    tier = tier.lower().strip()
    if tier not in ("free", "paid"):
        await interaction.response.send_message("Tier must be **free** or **paid**.", ephemeral=True)
        return

    filename = ACCOUNTS_PAID_FILE if tier == "paid" else ACCOUNTS_FREE_FILE
    lines = [l.strip() for l in accounts.split('\n') if ':' in l.strip()]
    if not lines:
        await interaction.response.send_message("No valid accounts found. Format: email:password", ephemeral=True)
        return

    with open(filename, 'a') as f:
        for line in lines:
            f.write(line + '\n')

    await interaction.response.send_message(f"Added **{len(lines)}** account(s) to **{tier}** stock.", ephemeral=True)


# ============================================
# CHECKER QUEUE SYSTEM
# ============================================

import io
import collections

CHECKER_MAX_FREE     = 200   # max names per 10 min window for free users
CHECKER_WINDOW       = 600   # 10 minutes
checker_queue        = asyncio.Queue()
checker_usage        = {}    # user_id -> {"count": int, "window_start": float}
checker_queue_running = False

def cap_variants(name):
    seen = set()
    seen.add(name)
    yield name
    for v in {name.lower(), name.upper(), name.capitalize()}:
        if v not in seen:
            seen.add(v)
            yield v

def single_check(session, variant):
    url = f"https://horizon.meta.com/profile/{variant}/"
    try:
        r = session.get(url, allow_redirects=False, timeout=10)
        loc = r.headers.get("Location", "")
        if r.status_code == 200:
            return "TAKEN"
        if r.status_code in (301, 302):
            if loc == "https://horizon.meta.com/":
                return "AVAILABLE"
            return "TAKEN"
    except Exception:
        pass
    return None

def check_username_sync(name):
    name = name.strip().lstrip("@")
    if not name:
        return name, "SKIP"
    session = requests.Session()
    result = single_check(session, name)
    if result == "TAKEN":
        return name, "TAKEN"
    if result == "AVAILABLE":
        for variant in cap_variants(name):
            if variant == name:
                continue
            r = single_check(session, variant)
            if r == "TAKEN":
                return name, "TAKEN"
        return name, "AVAILABLE"
    for variant in cap_variants(name):
        if variant == name:
            continue
        r = single_check(session, variant)
        if r == "TAKEN":
            return name, "TAKEN"
    return name, "AVAILABLE"

async def run_checker_queue():
    global checker_queue_running
    checker_queue_running = True
    while not checker_queue.empty():
        interaction, usernames, channel = await checker_queue.get()
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, lambda u=usernames: list(map(check_username_sync, u)))

            available = [name for name, status in results if status == "AVAILABLE"]
            taken     = [name for name, status in results if status == "TAKEN"]

            available_file = discord.File(io.BytesIO("\n".join(available).encode() if available else b"None"), filename="available.txt")
            taken_file     = discord.File(io.BytesIO("\n".join(taken).encode() if taken else b"None"),     filename="taken.txt")

            embed = discord.Embed(title="Username Checker Results", color=0xFFFFFF)
            embed.add_field(name="✅ Available", value=f"**{len(available)}**", inline=True)
            embed.add_field(name="🔒 Taken",     value=f"**{len(taken)}**",     inline=True)
            embed.add_field(name="Total",        value=f"**{len(usernames)}**", inline=True)
            embed.set_footer(text=f"WR Gen • requested by {interaction.user.display_name}")

            await channel.send(f"{interaction.user.mention} your check is done!", embed=embed, files=[available_file, taken_file])
        except Exception as e:
            try:
                await channel.send(f"{interaction.user.mention} checker error: {e}")
            except Exception:
                pass
        checker_queue.task_done()
    checker_queue_running = False

# ============================================
# /checker  (free + paid + admin)
# ============================================

@tree.command(name="checker", description="Check a list of usernames for availability on Meta/Horizon")
@app_commands.describe(file="A .txt file with one username per line")
async def checker(interaction: discord.Interaction, file: discord.Attachment):
    global checker_queue_running
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not (is_free(interaction.user) or is_paid(interaction.user) or is_admin(interaction.user)):
        await interaction.response.send_message("You don't have **access** to use this.", ephemeral=True)
        return
    if not file.filename.endswith(".txt"):
        await interaction.response.send_message("Please upload a **.txt** file.", ephemeral=True)
        return

    raw = await file.read()
    usernames = [l.strip().lstrip("@") for l in raw.decode("utf-8", errors="ignore").splitlines() if l.strip()]

    if not usernames:
        await interaction.response.send_message("No usernames found in the file.", ephemeral=True)
        return

    # Free users: enforce 200 name / 10 min limit
    admin = is_admin(interaction.user)
    paid  = is_paid(interaction.user)
    if not admin and not paid:
        user_id = str(interaction.user.id)
        now     = time.time()
        ud      = checker_usage.get(user_id, {"count": 0, "window_start": now})
        if now - ud["window_start"] >= CHECKER_WINDOW:
            ud = {"count": 0, "window_start": now}
        remaining_quota = CHECKER_MAX_FREE - ud["count"]
        if remaining_quota <= 0:
            wait = int(CHECKER_WINDOW - (now - ud["window_start"]))
            mins, secs = divmod(wait, 60)
            await interaction.response.send_message(
                f"You've hit your **{CHECKER_MAX_FREE} username** limit for this window. Try again in **{mins}m {secs}s**.", ephemeral=True
            )
            return
        if len(usernames) > remaining_quota:
            await interaction.response.send_message(
                f"Your file has **{len(usernames)}** names but you only have **{remaining_quota}** checks left this window. Trim your list and try again.", ephemeral=True
            )
            return
        ud["count"] += len(usernames)
        checker_usage[user_id] = ud
    else:
        # paid/admin: still cap at 2000 to avoid abuse
        if len(usernames) > 2000:
            await interaction.response.send_message("Max **2000 usernames** per check.", ephemeral=True)
            return

    pos = checker_queue.qsize() + 1
    await checker_queue.put((interaction, usernames, interaction.channel))

    instructions = (
        "**How to use /checker:**\n"
        "• Create a `.txt` file with one username per line\n"
        "• Upload it using `/checker` and attach the file\n"
        "• The bot checks each name on **horizon.meta.com**\n"
        "• It also checks capitalization variants (e.g. `name`, `Name`, `NAME`)\n"
        "• Names 6 chars or less get every possible cap combo checked\n"
        "• Results are posted publicly with `available.txt` and `taken.txt`\n"
        f"• Free users: max **{CHECKER_MAX_FREE} usernames** per 10 minutes\n"
    )
    await interaction.response.send_message(
        f"{instructions}\nAdded to queue — position **#{pos}**. Checking **{len(usernames)}** username(s). Results will be posted here when done.",
        ephemeral=False
    )

    if not checker_queue_running:
        asyncio.create_task(run_checker_queue())


# ============================================
# RUN
# ============================================

bot.run(BOT_TOKEN)
