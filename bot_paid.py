import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import sys
import time
import asyncio
import requests
import subprocess
import io

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

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
    embed.set_footer(text="meta bot - WR")

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
    embed.set_footer(text="meta bot - WR")
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
    embed.set_footer(text="meta bot - WR")
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
    import itertools
    seen = set()
    def _yield(v):
        if v not in seen:
            seen.add(v)
            return True
        return False
    # Always check these basic ones
    for v in [name, name.lower(), name.upper(), name.capitalize()]:
        if _yield(v):
            yield v
    # Every possible cap combo
    for combo in itertools.product([0, 1], repeat=len(name)):
        v = "".join(c.upper() if combo[i] else c.lower() for i, c in enumerate(name))
        if _yield(v):
            yield v

def single_check(session, variant):
    url = f"https://horizon.meta.com/profile/{variant}/"
    try:
        r = session.get(url, allow_redirects=False, timeout=10)
        status = r.status_code
        loc = r.headers.get("Location", "").rstrip("/")

        # 200 = profile page exists = TAKEN
        if status == 200:
            return "TAKEN"

        # redirect to exact homepage = username not found = AVAILABLE
        if status in (301, 302, 303, 307, 308):
            if loc in ("https://horizon.meta.com", "https://horizon.meta.com/"):
                return "AVAILABLE"
            # redirect to a login or other page = inconclusive
            if "login" in loc or "auth" in loc:
                return None
            # redirect to another profile = TAKEN
            return "TAKEN"

        # 404 = not found = AVAILABLE
        if status == 404:
            return "AVAILABLE"

    except Exception:
        pass
    return None

def check_username_sync(name):
    name = name.strip().lstrip("@")
    if not name:
        return name, "SKIP"
    session = requests.Session()
    # Check every cap variant — if ANY is taken, the name is taken
    for variant in cap_variants(name):
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
    usernames = []
    for l in raw.decode("utf-8", errors="ignore").splitlines():
        for name in l.split():
            name = name.strip().lstrip("@").strip()
            if name and not name.startswith("#"):
                usernames.append(name)

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
            wait = int(CHECKER_WINDOW - (now - ud["window_start"]))
            mins, secs = divmod(wait, 60)
            await interaction.response.send_message(
                f"Your file has **{len(usernames)}** names but you only have **{remaining_quota}** checks left this window. Resets in **{mins}m {secs}s**.", ephemeral=True
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
    await interaction.response.send_message(
        f"Added to queue — position **#{pos}**. Checking **{len(usernames)}** username(s). Results will be posted here when done.",
        ephemeral=False
    )

    if not checker_queue_running:
        asyncio.create_task(run_checker_queue())



# ============================================
# /username-search  (paid + admin only)
# ============================================

ACCESS_TOKENS = ['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']

@tree.command(name="username-search", description="Search for a Meta/Oculus username using the API")
@app_commands.describe(username="The username to search for")
async def username_search(interaction: discord.Interaction, username: str):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if not (is_paid(interaction.user) or is_admin(interaction.user)):
        await interaction.response.send_message("You don't have **access** to use this.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=False)
    import random as _random, json as _json

    def do_search(uname):
        token = _random.choice(ACCESS_TOKENS)
        url = "https://graph.oculus.com/graphql?forced_locale=en_US"
        headers = {"Authorization": f"OAuth {token}", "Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "doc_id": "8099807633384096",
            "operation_name": "SocialSearchQuery",
            "variables": _json.dumps({"query_data": {"query_string": uname, "search_mode": "ID"}}),
            "forced_locale": "en_US",
        }
        try:
            r = requests.post(url, data=payload, headers=headers, timeout=15)
            data = r.json()
            # Try multiple response paths
            edges = (
                data.get("data", {}).get("search", {}).get("results", {}).get("edges") or
                data.get("data", {}).get("xfb_user_search", {}).get("edges") or
                []
            )
            exact = [e for e in edges if e.get("node", {}).get("search_name", "").lower() == uname.lower()]
            return {"edges": edges, "exact": exact, "raw": str(data)[:300]}
        except Exception as e:
            return {"edges": [], "exact": [], "error": str(e)}

    def fetch_follow_count(token, user_id, follow_type):
        url = "https://graph.oculus.com/graphql"
        headers = {"Authorization": f"OAuth {token}", "Content-Type": "application/x-www-form-urlencoded"}
        doc_id = "5982715498405749" if follow_type == "followers" else "5790509797674020"
        op = "ProfileUserFollowersListQuery" if follow_type == "followers" else "UserProfileFollowsListPagingQuery"
        payload = {"doc_id": doc_id, "operation_name": op, "variables": _json.dumps({"count": 20, "cursor": None, "userId": user_id})}
        try:
            r = requests.post(url, data=payload, headers=headers, timeout=10)
            data = r.json()
            node = data.get("data", {}).get("node", {}) or data.get("data", {}).get("user", {})
            key = "followers" if follow_type == "followers" else "follows"
            return node.get(key, {}).get("count", 0)
        except Exception:
            return 0

    loop = asyncio.get_event_loop()
    token = _random.choice(ACCESS_TOKENS)
    result = await loop.run_in_executor(None, do_search, username)
    exact = result.get("exact", [])
    edges = result.get("edges", [])
    show = exact if exact else edges[:3]

    if not show:
        raw = result.get("raw", "no raw")
        embed = discord.Embed(title="No Results", description="No users found for **" + username + "**\n```" + raw + "```", color=0xFF0000)
        embed.set_footer(text="meta bot - WR")
        await interaction.followup.send(embed=embed)
        return

    if exact:
        user = exact[0]["node"]
        user_id = user.get("user_id", "N/A")
        search_name = user.get("search_name", "N/A")
        friend_status = user.get("friend_status", "unknown").replace("_", " ").title()
        # Try multiple pfp fields
        pfp = (user.get("profile_photo") or {}).get("uri") or               (user.get("pfp_for_right_rail") or {}).get("uri") or               (user.get("avatar_image") or {}).get("uri") or None

        followers = await loop.run_in_executor(None, fetch_follow_count, token, user_id, "followers")
        following = await loop.run_in_executor(None, fetch_follow_count, token, user_id, "following")

        embed = discord.Embed(color=0x0085FF)
        embed.set_author(name=search_name + "  •  @" + username)
        embed.add_field(name="User ID", value="```" + user_id + "```", inline=False)
        embed.add_field(name="Friend Status", value=friend_status, inline=True)
        embed.add_field(name="Followers", value=str(followers), inline=True)
        embed.add_field(name="Following", value=str(following), inline=True)
        if pfp:
            embed.set_thumbnail(url=pfp)
        embed.set_footer(text="meta bot - WR")
    else:
        embed = discord.Embed(title="Similar Users", description="No exact match for **" + username + "**", color=0xFFAA00)
        for i, edge in enumerate(show):
            user = edge.get("node", {})
            name = user.get("search_name", "Unknown")
            uid = user.get("user_id", "Unknown")
            mutual = user.get("mutual_friends", {}).get("count", 0)
            embed.add_field(name=str(i+1) + ". " + name, value="ID: " + uid + "\nMutual Friends: " + str(mutual), inline=True)
        embed.set_footer(text="meta bot - WR")

    await interaction.followup.send(embed=embed)

# ============================================
# /orion-drift-name-display
# ============================================

ORION_DRIFT_ALLOWED_USERS = {1393776676755738715, 161559455253790720}
FONT_PATH = os.path.join(os.path.dirname(__file__), "MagistralBold.ttf")

def generate_name_image(name: str) -> io.BytesIO:
    PADDING_X = 80
    PADDING_Y = 60
    FONT_SIZE = 120

    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    # Measure text size
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), name, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    img_w = text_w + PADDING_X * 2
    img_h = text_h + PADDING_Y * 2

    img = Image.new("RGB", (img_w, img_h), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    x = PADDING_X - bbox[0]
    y = PADDING_Y - bbox[1]
    draw.text((x, y), name, font=font, fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

@tree.command(
    name="orion-drift-name-display",
    description="Preview a name in the Orion Drift font",
)
@app_commands.describe(name="The name to render in the Orion Drift font")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def orion_drift_name_display(interaction: discord.Interaction, name: str):
    if interaction.user.id not in ORION_DRIFT_ALLOWED_USERS:
        await interaction.response.send_message(
            "You don't have **access** to use this command.", ephemeral=True
        )
        return

    await interaction.response.defer()

    loop = asyncio.get_event_loop()
    buf = await loop.run_in_executor(None, generate_name_image, name)

    file = discord.File(buf, filename="orion_drift.png")
    embed = discord.Embed(color=0x000000)
    embed.set_image(url="attachment://orion_drift.png")
    embed.set_footer(text=f"Orion Drift • {name}")

    await interaction.followup.send(embed=embed, file=file)

# ============================================
# RUN
# ============================================

bot.run(BOT_TOKEN)
