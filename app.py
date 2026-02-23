"""
WorkBase CRM — Full Stack
Telegram Bot + WhatsApp KB Import + OpenClaw Skill API
"""

from flask import Flask, request, jsonify, send_file, session
import sqlite3, os, json, re, hashlib, hmac
from datetime import datetime, timedelta
from functools import wraps
import urllib.request, urllib.parse

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'crm-secret-change-me-2024')

# ── CONFIG ────────────────────────────────────────────────────────────────────
DB_PATH       = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'crm.db'))
PASSWORD      = os.environ.get('CRM_PASSWORD', 'admin123')
BOT_TOKEN     = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
BOT_API_KEY   = os.environ.get('BOT_API_KEY', 'crm-bot-secret-key-change-me')  # shared secret for /bot/* routes
CRM_URL       = os.environ.get('CRM_URL', 'https://your-app.railway.app')      # your public URL
ALLOWED_USERS = os.environ.get('TELEGRAM_ALLOWED_USERS', '')                   # comma-separated Telegram user IDs

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'todo',
            priority TEXT DEFAULT 'medium',
            assigned_to INTEGER,
            assigned_by TEXT,
            due_date TEXT,
            tags TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            avatar_url TEXT,
            email TEXT
        );
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            author TEXT,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS kb_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            category TEXT DEFAULT 'General',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            remind_at TEXT,
            repeat_type TEXT DEFAULT 'none',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS telegram_sessions (
            chat_id TEXT PRIMARY KEY,
            username TEXT,
            state TEXT DEFAULT 'idle',
            context TEXT DEFAULT '{}',
            last_seen TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS group_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            chat_title TEXT,
            speaker TEXT,
            message TEXT,
            synced_to_kb INTEGER DEFAULT 0,
            timestamp TEXT DEFAULT (datetime('now'))
        );
    ''')
    c.execute('SELECT COUNT(*) FROM team_members')
    if c.fetchone()[0] == 0:
        _seed_data(c)
    conn.commit()
    conn.close()

def _seed_data(c):
    members = [
        ('Alex Rivera', 'Lead',      'https://api.dicebear.com/7.x/adventurer/svg?seed=Alex',   'alex@team.com'),
        ('Sam Chen',    'Manager',   'https://api.dicebear.com/7.x/adventurer/svg?seed=Sam',    'sam@team.com'),
        ('Jordan Lee',  'Editor',    'https://api.dicebear.com/7.x/adventurer/svg?seed=Jordan', 'jordan@team.com'),
        ('Taylor Kim',  'Developer', 'https://api.dicebear.com/7.x/adventurer/svg?seed=Taylor', 'taylor@team.com'),
    ]
    c.executemany('INSERT INTO team_members (name,role,avatar_url,email) VALUES (?,?,?,?)', members)
    now = datetime.now()
    tasks = [
        ('Launch Marketing Campaign',  'Plan and execute Q1 marketing campaign', 'in_progress', 'high',   1, 'Admin', (now+timedelta(days=5)).strftime('%Y-%m-%d'),  'marketing,campaign'),
        ('Update Website Copy',        'Refresh homepage content',               'todo',        'medium', 3, 'Admin', (now+timedelta(days=10)).strftime('%Y-%m-%d'), 'website,content'),
        ('Q1 Financial Review',        'Compile Q1 financial reports',           'todo',        'urgent', 2, 'Admin', (now+timedelta(days=2)).strftime('%Y-%m-%d'),  'finance,review'),
        ('Team Onboarding Docs',       'Create onboarding documentation',        'done',        'low',    3, 'Admin', (now-timedelta(days=3)).strftime('%Y-%m-%d'),  'hr,docs'),
        ('API Integration',            'Integrate payment gateway API',          'in_progress', 'high',   4, 'Admin', (now+timedelta(days=7)).strftime('%Y-%m-%d'),  'dev,api'),
    ]
    c.executemany('INSERT INTO tasks (title,description,status,priority,assigned_to,assigned_by,due_date,tags) VALUES (?,?,?,?,?,?,?,?)', tasks)
    c.executemany('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)', [
        ('Company Style Guide', '## Brand Colors\n- Primary: #e94560\n- Secondary: #1a1a2e', 'Brand'),
        ('Git Workflow',        '1. Feature branch\n2. Changes\n3. PR\n4. Merge',             'Development'),
        ('Meeting Templates',   '## Weekly Sync\n- Done?\n- Blockers?\n- Plan?',              'Processes'),
    ])
    c.execute("INSERT INTO notes (title,content) VALUES (?,?)", ('Welcome Note', '# Welcome to WorkBase CRM!\n\nTelegram bot + WhatsApp KB import + OpenClaw skill — all connected.'))
    c.execute("INSERT INTO activity_log (action,details) VALUES (?,?)", ('System init', 'Database seeded'))

def log_action(c, action, details):
    c.execute('INSERT INTO activity_log (action,details) VALUES (?,?)', (action, details))

# ── AUTH ──────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return dec

def bot_auth_required(f):
    """Validates X-Bot-Key header for bot/skill API routes (no session needed)."""
    @wraps(f)
    def dec(*args, **kwargs):
        key = request.headers.get('X-Bot-Key', '')
        if key != BOT_API_KEY:
            return jsonify({'error': 'Invalid bot key'}), 403
        return f(*args, **kwargs)
    return dec

# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────
def tg_send(chat_id, text, parse_mode='Markdown', reply_markup=None):
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        return
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f'[TG] send error: {e}')

def tg_set_webhook(url):
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        return False
    try:
        payload = json.dumps({'url': url}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/setWebhook',
            data=payload, headers={'Content-Type': 'application/json'})
        res = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return res.get('ok', False)
    except Exception as e:
        print(f'[TG] webhook error: {e}')
        return False

def is_allowed_user(user_id):
    if not ALLOWED_USERS.strip():
        return True  # open to all if not configured
    return str(user_id) in [u.strip() for u in ALLOWED_USERS.split(',')]

def get_tg_session(chat_id):
    conn = get_db()
    row = conn.execute('SELECT * FROM telegram_sessions WHERE chat_id=?', (str(chat_id),)).fetchone()
    conn.close()
    if row:
        s = dict(row)
        s['context'] = json.loads(s['context'] or '{}')
        return s
    return {'chat_id': str(chat_id), 'state': 'idle', 'context': {}}

def save_tg_session(chat_id, state, context=None):
    conn = get_db()
    conn.execute('''
        INSERT INTO telegram_sessions (chat_id, state, context, last_seen)
        VALUES (?,?,?,datetime('now'))
        ON CONFLICT(chat_id) DO UPDATE SET state=excluded.state, context=excluded.context, last_seen=excluded.last_seen
    ''', (str(chat_id), state, json.dumps(context or {})))
    conn.commit()
    conn.close()

# ── TELEGRAM COMMAND ROUTER ───────────────────────────────────────────────────
def handle_telegram_update(update):
    msg  = update.get('message') or update.get('edited_message')
    cb   = update.get('callback_query')

    if cb:
        handle_callback(cb)
        return

    if not msg:
        return

    chat_id   = msg['chat']['id']
    chat_type = msg['chat']['type']  # private / group / supergroup
    user_id   = msg.get('from', {}).get('id', 0)
    username  = msg.get('from', {}).get('username', 'unknown')
    text      = msg.get('text', '').strip()

    # ── Group / supergroup: absorb messages as knowledge ──────────────────────
    if chat_type in ('group', 'supergroup'):
        chat_title = msg['chat'].get('title', 'Group')
        if text and not text.startswith('/'):
            conn = get_db()
            conn.execute(
                'INSERT INTO group_knowledge (chat_id,chat_title,speaker,message) VALUES (?,?,?,?)',
                (str(chat_id), chat_title, username, text))
            conn.commit()
            conn.close()
        # Only respond to /commands in groups
        if not text.startswith('/'):
            return

    # ── Private: check allow-list ─────────────────────────────────────────────
    if chat_type == 'private' and not is_allowed_user(user_id):
        tg_send(chat_id, '⛔ You are not authorised to use this bot.')
        return

    sess = get_tg_session(chat_id)

    # ── Multi-step state machine ──────────────────────────────────────────────
    if sess['state'] != 'idle' and not text.startswith('/'):
        handle_state(chat_id, text, sess)
        return

    # ── Commands ──────────────────────────────────────────────────────────────
    cmd = text.split()[0].lower().split('@')[0] if text.startswith('/') else ''
    rest = text[len(cmd):].strip() if cmd else text

    if cmd == '/start' or cmd == '/help':
        tg_send(chat_id, HELP_TEXT, reply_markup=main_keyboard())

    elif cmd == '/tasks' or text.lower() in ('tasks', 'show tasks', 'list tasks'):
        send_task_summary(chat_id)

    elif cmd == '/todo':
        send_tasks_by_status(chat_id, 'todo')

    elif cmd == '/inprogress':
        send_tasks_by_status(chat_id, 'in_progress')

    elif cmd == '/done':
        send_tasks_by_status(chat_id, 'done')

    elif cmd == '/newtask' or text.lower().startswith('create task') or text.lower().startswith('add task'):
        title = rest or text.replace('create task','').replace('add task','').strip()
        if title and len(title) > 2:
            quick_create_task(chat_id, title, username)
        else:
            tg_send(chat_id, '📝 *New Task*\n\nWhat\'s the task title?')
            save_tg_session(chat_id, 'await_task_title')

    elif cmd == '/note' or text.lower().startswith('add note') or text.lower().startswith('note:'):
        content = rest or re.sub(r'^(add note|note:)', '', text, flags=re.I).strip()
        if content and len(content) > 2:
            quick_create_note(chat_id, content, username)
        else:
            tg_send(chat_id, '📓 *New Note*\n\nWhat\'s the note? (first line = title)')
            save_tg_session(chat_id, 'await_note')

    elif cmd == '/kb' or text.lower().startswith('search kb') or text.lower().startswith('kb:'):
        query = rest or re.sub(r'^(search kb|kb:)', '', text, flags=re.I).strip()
        search_kb(chat_id, query)

    elif cmd == '/addkb':
        tg_send(chat_id, '📚 *Add to Knowledge Base*\n\nSend in format:\n`Title | Content | Category`')
        save_tg_session(chat_id, 'await_kb_entry')

    elif cmd == '/stats' or text.lower() in ('stats', 'status', 'dashboard'):
        send_stats(chat_id)

    elif cmd == '/team' or text.lower() in ('team', 'show team'):
        send_team(chat_id)

    elif cmd == '/overdue' or text.lower() in ('overdue', 'overdue tasks'):
        send_overdue(chat_id)

    elif cmd == '/remind' or text.lower().startswith('remind me'):
        content = rest or re.sub(r'^remind me', '', text, flags=re.I).strip()
        if content:
            quick_create_reminder(chat_id, content, username)
        else:
            tg_send(chat_id, '⏰ *New Reminder*\n\nSend: `remind me [what] at [time]`\nExample: `remind me call John at 3pm`')

    elif cmd == '/syncgroups':
        sync_group_knowledge_to_kb(chat_id)

    elif cmd == '/setwebhook':
        ok = tg_set_webhook(f'{CRM_URL}/telegram/webhook')
        tg_send(chat_id, f'{"✅ Webhook set!" if ok else "❌ Failed. Check BOT_TOKEN and CRM_URL."}')

    else:
        # Natural language fallback — try to understand intent
        handle_natural_language(chat_id, text, username)

def handle_state(chat_id, text, sess):
    state = sess['state']
    ctx   = sess['context']

    if state == 'await_task_title':
        ctx['title'] = text
        tg_send(chat_id, f'✅ Title: *{text}*\n\nPriority? (low/medium/high/urgent) or skip:')
        save_tg_session(chat_id, 'await_task_priority', ctx)

    elif state == 'await_task_priority':
        p = text.lower() if text.lower() in ('low','medium','high','urgent') else 'medium'
        ctx['priority'] = p
        tg_send(chat_id, f'Priority: *{p}*\n\nDue date? (YYYY-MM-DD) or skip:')
        save_tg_session(chat_id, 'await_task_due', ctx)

    elif state == 'await_task_due':
        ctx['due_date'] = text if re.match(r'\d{4}-\d{2}-\d{2}', text) else None
        conn = get_db()
        c    = conn.cursor()
        c.execute('INSERT INTO tasks (title,priority,due_date,assigned_by) VALUES (?,?,?,?)',
                  (ctx['title'], ctx.get('priority','medium'), ctx.get('due_date'), 'Telegram'))
        tid = c.lastrowid
        log_action(c, 'Task created via Telegram', ctx['title'])
        conn.commit(); conn.close()
        tg_send(chat_id, f'✅ Task #{tid} created!\n*{ctx["title"]}*\nPriority: {ctx.get("priority","medium")}'
                + (f'\nDue: {ctx["due_date"]}' if ctx.get('due_date') else ''))
        save_tg_session(chat_id, 'idle')

    elif state == 'await_note':
        lines   = text.split('\n')
        title   = lines[0][:120]
        content = text
        conn = get_db()
        c    = conn.cursor()
        c.execute('INSERT INTO notes (title,content) VALUES (?,?)', (title, content))
        log_action(c, 'Note created via Telegram', title)
        conn.commit(); conn.close()
        tg_send(chat_id, f'📓 Note saved!\n*{title}*')
        save_tg_session(chat_id, 'idle')

    elif state == 'await_kb_entry':
        parts = [p.strip() for p in text.split('|')]
        if len(parts) >= 2:
            title    = parts[0]
            content  = parts[1]
            category = parts[2] if len(parts) > 2 else 'General'
            conn = get_db()
            c    = conn.cursor()
            c.execute('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)', (title, content, category))
            log_action(c, 'KB entry via Telegram', title)
            conn.commit(); conn.close()
            tg_send(chat_id, f'📚 KB entry added!\n*{title}* → _{category}_')
        else:
            tg_send(chat_id, '❌ Format: `Title | Content | Category`')
        save_tg_session(chat_id, 'idle')

    else:
        save_tg_session(chat_id, 'idle')
        tg_send(chat_id, '↩️ Cancelled. /help for commands.')

def handle_callback(cb):
    chat_id = cb['message']['chat']['id']
    data    = cb.get('data', '')

    if data.startswith('status:'):
        _, tid, status = data.split(':')
        conn = get_db()
        c    = conn.cursor()
        c.execute("UPDATE tasks SET status=?,updated_at=datetime('now') WHERE id=?", (status, int(tid)))
        log_action(c, 'Status updated via Telegram', f'Task #{tid} → {status}')
        conn.commit(); conn.close()
        tg_send(chat_id, f'✅ Task #{tid} → *{status}*')

    elif data.startswith('done:'):
        tid = data.split(':')[1]
        conn = get_db()
        c    = conn.cursor()
        c.execute("UPDATE tasks SET status='done',updated_at=datetime('now') WHERE id=?", (int(tid),))
        log_action(c, 'Task done via Telegram', f'Task #{tid}')
        conn.commit(); conn.close()
        tg_send(chat_id, f'✅ Task #{tid} marked *Done*!')

def handle_natural_language(chat_id, text, username):
    t = text.lower()
    if any(w in t for w in ['task', 'todo', 'do']):
        title = re.sub(r'\b(create|add|make|new|task|todo)\b', '', text, flags=re.I).strip(' :-')
        if len(title) > 2:
            quick_create_task(chat_id, title or text, username)
            return
    if any(w in t for w in ['note', 'remember', 'write down']):
        content = re.sub(r'\b(note|remember|write down)\b', '', text, flags=re.I).strip(' :-')
        quick_create_note(chat_id, content or text, username)
        return
    if any(w in t for w in ['remind', 'reminder']):
        quick_create_reminder(chat_id, text, username)
        return
    tg_send(chat_id,
        '🤔 I didn\'t catch that.\n\nTry:\n'
        '• `add task Design new logo`\n'
        '• `note: meeting at 3pm`\n'
        '• `remind me standup at 9am`\n'
        '• /help for all commands',
        reply_markup=main_keyboard())

# ── SEND HELPERS ──────────────────────────────────────────────────────────────
HELP_TEXT = """🦞 *WorkBase CRM Bot*

*Tasks*
/tasks — summary of all tasks
/todo — to-do items
/inprogress — in progress
/done — completed tasks
/newtask — create a new task
/overdue — overdue tasks

*Notes & KB*
/note — quick note
/addkb — add KB entry
/kb [query] — search KB

*Info*
/stats — dashboard stats
/team — team members
/syncgroups — push group chat knowledge to KB
/remind — set a reminder

*Natural language also works:*
`add task Fix login bug`
`note: client called about invoice`
`remind me send report at 5pm`
"""

def main_keyboard():
    return {'keyboard': [
        [{'text': '📋 Tasks'}, {'text': '📊 Stats'}],
        [{'text': '📝 New Note'}, {'text': '📚 Search KB'}],
        [{'text': '👥 Team'}, {'text': '⏰ Overdue'}],
    ], 'resize_keyboard': True}

def send_task_summary(chat_id):
    conn = get_db()
    rows = conn.execute("SELECT status, COUNT(*) as c FROM tasks GROUP BY status").fetchall()
    conn.close()
    counts = {r['status']: r['c'] for r in rows}
    msg = (f"📋 *Task Summary*\n\n"
           f"📌 To Do:       {counts.get('todo', 0)}\n"
           f"🔄 In Progress: {counts.get('in_progress', 0)}\n"
           f"✅ Done:        {counts.get('done', 0)}\n\n"
           f"Use /todo /inprogress /done to view each")
    tg_send(chat_id, msg)

def send_tasks_by_status(chat_id, status):
    conn  = get_db()
    tasks = conn.execute(
        'SELECT t.*, tm.name as assignee FROM tasks t LEFT JOIN team_members tm ON t.assigned_to=tm.id WHERE t.status=? ORDER BY t.priority DESC LIMIT 10',
        (status,)).fetchall()
    conn.close()
    if not tasks:
        tg_send(chat_id, f'No *{status}* tasks.')
        return
    label = {'todo': '📌 To Do', 'in_progress': '🔄 In Progress', 'done': '✅ Done'}.get(status, status)
    lines = [f"*{label}*\n"]
    buttons = []
    for t in tasks:
        pri = {'urgent': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🟢'}.get(t['priority'], '⚪')
        due = f" · {t['due_date']}" if t['due_date'] else ''
        who = f" · {t['assignee']}" if t['assignee'] else ''
        lines.append(f"{pri} #{t['id']} {t['title']}{due}{who}")
        if status != 'done':
            buttons.append([{'text': f"✅ Done #{t['id']}", 'callback_data': f"done:{t['id']}"}])
    tg_send(chat_id, '\n'.join(lines), reply_markup={'inline_keyboard': buttons} if buttons else None)

def send_stats(chat_id):
    conn   = get_db()
    total  = conn.execute('SELECT COUNT(*) as c FROM tasks').fetchone()['c']
    inprog = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='in_progress'").fetchone()['c']
    done   = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='done'").fetchone()['c']
    today  = datetime.now().strftime('%Y-%m-%d')
    wd     = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    odue   = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE due_date < ? AND status!='done'", (today,)).fetchone()['c']
    cweek  = conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='done' AND updated_at >= ?", (wd,)).fetchone()['c']
    notes  = conn.execute('SELECT COUNT(*) as c FROM notes').fetchone()['c']
    kb     = conn.execute('SELECT COUNT(*) as c FROM kb_entries').fetchone()['c']
    conn.close()
    tg_send(chat_id,
        f"📊 *Dashboard*\n\n"
        f"📋 Total Tasks:     {total}\n"
        f"🔄 In Progress:     {inprog}\n"
        f"✅ Done This Week:  {cweek}\n"
        f"⚠️  Overdue:         {odue}\n"
        f"📝 Notes:           {notes}\n"
        f"📚 KB Entries:      {kb}")

def send_team(chat_id):
    conn    = get_db()
    members = conn.execute('SELECT * FROM team_members').fetchall()
    conn.close()
    if not members:
        tg_send(chat_id, 'No team members yet.'); return
    lines = ['👥 *Team*\n']
    for m in members:
        tc = get_db().execute('SELECT COUNT(*) as c FROM tasks WHERE assigned_to=?', (m['id'],)).fetchone()['c']
        lines.append(f"• *{m['name']}* [{m['role']}] — {tc} tasks")
    tg_send(chat_id, '\n'.join(lines))

def send_overdue(chat_id):
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = get_db()
    tasks = conn.execute(
        "SELECT t.*, tm.name as assignee FROM tasks t LEFT JOIN team_members tm ON t.assigned_to=tm.id WHERE t.due_date < ? AND t.status!='done' ORDER BY t.due_date",
        (today,)).fetchall()
    conn.close()
    if not tasks:
        tg_send(chat_id, '🎉 No overdue tasks!'); return
    lines = [f"⚠️ *Overdue Tasks* ({len(tasks)})\n"]
    for t in tasks:
        days = (datetime.now() - datetime.strptime(t['due_date'], '%Y-%m-%d')).days
        lines.append(f"• #{t['id']} {t['title']} — *{days}d overdue*" + (f" ({t['assignee']})" if t['assignee'] else ''))
    tg_send(chat_id, '\n'.join(lines))

def search_kb(chat_id, query):
    conn    = get_db()
    entries = conn.execute(
        "SELECT * FROM kb_entries WHERE title LIKE ? OR content LIKE ? OR category LIKE ? LIMIT 5",
        (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    if not entries:
        tg_send(chat_id, f'🔍 No KB results for `{query}`'); return
    lines = [f"📚 *KB: {query}*\n"]
    for e in entries:
        preview = (e['content'] or '')[:120].replace('\n', ' ')
        lines.append(f"*{e['title']}* [{e['category']}]\n_{preview}_\n")
    tg_send(chat_id, '\n'.join(lines))

def quick_create_task(chat_id, title, username):
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO tasks (title, assigned_by) VALUES (?,?)', (title, f'Telegram:{username}'))
    tid = c.lastrowid
    log_action(c, 'Task created via Telegram', title)
    conn.commit(); conn.close()
    tg_send(chat_id, f'✅ Task #{tid} created!\n*{title}*',
            reply_markup={'inline_keyboard': [
                [{'text': '🔄 In Progress', 'callback_data': f'status:{tid}:in_progress'},
                 {'text': '✅ Done',         'callback_data': f'done:{tid}'}]
            ]})

def quick_create_note(chat_id, text, username):
    lines   = text.split('\n')
    title   = lines[0][:120]
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO notes (title, content) VALUES (?,?)', (title, text))
    log_action(c, 'Note created via Telegram', title)
    conn.commit(); conn.close()
    tg_send(chat_id, f'📓 Note saved!\n*{title}*')

def quick_create_reminder(chat_id, text, username):
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO reminders (title, description) VALUES (?,?)', (text[:200], f'From Telegram: {username}'))
    log_action(c, 'Reminder via Telegram', text[:100])
    conn.commit(); conn.close()
    tg_send(chat_id, f'⏰ Reminder set!\n_{text}_')

def sync_group_knowledge_to_kb(chat_id):
    """Summarise unsynced group messages → KB entries."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM group_knowledge WHERE synced_to_kb=0 ORDER BY timestamp').fetchall()
    if not rows:
        tg_send(chat_id, '📚 No new group messages to sync.')
        conn.close(); return

    # Group by chat
    by_chat = {}
    for r in rows:
        key = r['chat_title'] or r['chat_id']
        by_chat.setdefault(key, []).append(f"[{r['speaker']}]: {r['message']}")

    count = 0
    for chat_title, messages in by_chat.items():
        batch = '\n'.join(messages[:50])  # cap at 50 msgs per sync
        title = f"Group: {chat_title} — {datetime.now().strftime('%Y-%m-%d')}"
        conn.execute('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)',
                     (title, batch, 'Team Conversations'))
        count += len(messages)

    conn.execute('UPDATE group_knowledge SET synced_to_kb=1 WHERE synced_to_kb=0')
    conn.commit(); conn.close()
    tg_send(chat_id, f'✅ Synced {count} group messages → KB\nCategory: *Team Conversations*')

# ── WHATSAPP KB IMPORT ────────────────────────────────────────────────────────
def parse_whatsapp_export(text, category='WhatsApp Import'):
    """
    Parses WhatsApp exported .txt chat format.
    Lines look like:
      [25/02/2024, 10:30:00] John: Hello there
      or
      25/02/2024, 10:30 - John: Hello there
    Returns list of (title, content, category) tuples.
    """
    # Normalise both bracket and dash formats
    pattern = re.compile(
        r'[\["]?(\d{1,2}[\/\.\-]\d{1,2}[\/\.\-]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)["\]]?\s*[-–]\s*([^:]+):\s*(.*)',
        re.IGNORECASE)

    entries   = []
    by_date   = {}
    cur_date  = None
    cur_lines = []

    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            date_str, time_str, speaker, msg = m.groups()
            # normalise date key
            date_key = date_str.replace('.','/').replace('-','/')
            if date_key != cur_date:
                if cur_date and cur_lines:
                    by_date[cur_date] = cur_lines[:]
                cur_date  = date_key
                cur_lines = []
            cur_lines.append(f"[{time_str}] {speaker.strip()}: {msg.strip()}")
        elif cur_lines and line.strip():
            cur_lines[-1] += f' {line.strip()}'  # continuation

    if cur_date and cur_lines:
        by_date[cur_date] = cur_lines

    for date_key, lines in by_date.items():
        title   = f"WhatsApp · {date_key}"
        content = '\n'.join(lines)
        entries.append((title, content, category))

    return entries

# ── FLASK ROUTES ──────────────────────────────────────────────────────────────

# ── Auth ─────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    d = request.json
    if d.get('password') == PASSWORD:
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'error': 'Invalid password'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/check-auth')
def check_auth():
    return jsonify({'authenticated': bool(session.get('logged_in'))})

# ── Tasks ────────────────────────────────────────────────────────
@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    conn  = get_db()
    tasks = conn.execute('''
        SELECT t.*, tm.name as assignee_name, tm.avatar_url as assignee_avatar
        FROM tasks t LEFT JOIN team_members tm ON t.assigned_to = tm.id
        ORDER BY t.created_at DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in tasks])

@app.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    d    = request.json
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO tasks (title,description,status,priority,assigned_to,assigned_by,due_date,tags) VALUES (?,?,?,?,?,?,?,?)',
              (d['title'], d.get('description',''), d.get('status','todo'), d.get('priority','medium'),
               d.get('assigned_to'), d.get('assigned_by','Admin'), d.get('due_date'), d.get('tags','')))
    tid = c.lastrowid
    log_action(c, 'Task created', d['title'])
    conn.commit(); conn.close()
    return jsonify({'id': tid, 'success': True})

@app.route('/api/tasks/<int:tid>', methods=['PUT'])
@login_required
def update_task(tid):
    d      = request.json
    conn   = get_db()
    c      = conn.cursor()
    fields = []
    vals   = []
    for f in ['title','description','status','priority','assigned_to','due_date','tags']:
        if f in d:
            fields.append(f'{f}=?')
            vals.append(d[f])
    fields.append('updated_at=?')
    vals += [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), tid]
    c.execute(f'UPDATE tasks SET {", ".join(fields)} WHERE id=?', vals)
    log_action(c, 'Task updated', f'#{tid}')
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/tasks/<int:tid>', methods=['DELETE'])
@login_required
def delete_task(tid):
    conn = get_db()
    c    = conn.cursor()
    t    = c.execute('SELECT title FROM tasks WHERE id=?', (tid,)).fetchone()
    c.execute('DELETE FROM tasks WHERE id=?', (tid,))
    c.execute('DELETE FROM comments WHERE task_id=?', (tid,))
    if t: log_action(c, 'Task deleted', t['title'])
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/tasks/<int:tid>/comments', methods=['GET'])
@login_required
def get_comments(tid):
    conn = get_db()
    rows = conn.execute('SELECT * FROM comments WHERE task_id=? ORDER BY created_at', (tid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/tasks/<int:tid>/comments', methods=['POST'])
@login_required
def add_comment(tid):
    d    = request.json
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO comments (task_id,author,content) VALUES (?,?,?)',
              (tid, d.get('author','Admin'), d['content']))
    log_action(c, 'Comment added', f'on task #{tid}')
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── Team ─────────────────────────────────────────────────────────
@app.route('/api/team', methods=['GET'])
@login_required
def get_team():
    conn    = get_db()
    members = conn.execute('SELECT * FROM team_members').fetchall()
    result  = []
    for m in members:
        m = dict(m)
        m['task_count'] = conn.execute('SELECT COUNT(*) as c FROM tasks WHERE assigned_to=?', (m['id'],)).fetchone()['c']
        result.append(m)
    conn.close()
    return jsonify(result)

@app.route('/api/team', methods=['POST'])
@login_required
def add_member():
    d      = request.json
    conn   = get_db()
    c      = conn.cursor()
    avatar = d.get('avatar_url') or f"https://api.dicebear.com/7.x/adventurer/svg?seed={d['name'].replace(' ','')}"
    c.execute('INSERT INTO team_members (name,role,avatar_url,email) VALUES (?,?,?,?)',
              (d['name'], d.get('role','Member'), avatar, d.get('email','')))
    mid = c.lastrowid
    log_action(c, 'Team member added', d['name'])
    conn.commit(); conn.close()
    return jsonify({'id': mid, 'success': True})

@app.route('/api/team/<int:mid>', methods=['DELETE'])
@login_required
def delete_member(mid):
    conn = get_db()
    c    = conn.cursor()
    m    = c.execute('SELECT name FROM team_members WHERE id=?', (mid,)).fetchone()
    c.execute('DELETE FROM team_members WHERE id=?', (mid,))
    if m: log_action(c, 'Team member removed', m['name'])
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── Notes ────────────────────────────────────────────────────────
@app.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    conn  = get_db()
    notes = conn.execute('SELECT * FROM notes ORDER BY updated_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in notes])

@app.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    d    = request.json
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO notes (title,content) VALUES (?,?)', (d['title'], d.get('content','')))
    nid = c.lastrowid
    log_action(c, 'Note created', d['title'])
    conn.commit(); conn.close()
    return jsonify({'id': nid, 'success': True})

@app.route('/api/notes/<int:nid>', methods=['PUT'])
@login_required
def update_note(nid):
    d = request.json
    conn = get_db()
    conn.execute('UPDATE notes SET title=?,content=?,updated_at=? WHERE id=?',
                 (d['title'], d['content'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), nid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/notes/<int:nid>', methods=['DELETE'])
@login_required
def delete_note(nid):
    conn = get_db()
    conn.execute('DELETE FROM notes WHERE id=?', (nid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── KB ───────────────────────────────────────────────────────────
@app.route('/api/kb', methods=['GET'])
@login_required
def get_kb():
    conn    = get_db()
    entries = conn.execute('SELECT * FROM kb_entries ORDER BY category,title').fetchall()
    conn.close()
    return jsonify([dict(r) for r in entries])

@app.route('/api/kb', methods=['POST'])
@login_required
def create_kb():
    d    = request.json
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)',
              (d['title'], d.get('content',''), d.get('category','General')))
    kid = c.lastrowid
    log_action(c, 'KB entry created', d['title'])
    conn.commit(); conn.close()
    return jsonify({'id': kid, 'success': True})

@app.route('/api/kb/<int:kid>', methods=['PUT'])
@login_required
def update_kb(kid):
    d = request.json
    conn = get_db()
    conn.execute('UPDATE kb_entries SET title=?,content=?,category=? WHERE id=?',
                 (d['title'], d['content'], d.get('category','General'), kid))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/api/kb/<int:kid>', methods=['DELETE'])
@login_required
def delete_kb(kid):
    conn = get_db()
    conn.execute('DELETE FROM kb_entries WHERE id=?', (kid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── Reminders ────────────────────────────────────────────────────
@app.route('/api/reminders', methods=['GET'])
@login_required
def get_reminders():
    conn      = get_db()
    reminders = conn.execute('SELECT * FROM reminders ORDER BY remind_at').fetchall()
    conn.close()
    return jsonify([dict(r) for r in reminders])

@app.route('/api/reminders', methods=['POST'])
@login_required
def create_reminder():
    d    = request.json
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO reminders (title,description,remind_at,repeat_type) VALUES (?,?,?,?)',
              (d['title'], d.get('description',''), d.get('remind_at'), d.get('repeat_type','none')))
    rid = c.lastrowid
    log_action(c, 'Reminder created', d['title'])
    conn.commit(); conn.close()
    return jsonify({'id': rid, 'success': True})

@app.route('/api/reminders/<int:rid>', methods=['DELETE'])
@login_required
def delete_reminder(rid):
    conn = get_db()
    conn.execute('DELETE FROM reminders WHERE id=?', (rid,))
    conn.commit(); conn.close()
    return jsonify({'success': True})

# ── Activity / Stats ─────────────────────────────────────────────
@app.route('/api/activity')
@login_required
def get_activity():
    conn = get_db()
    lim  = request.args.get('limit', 20)
    logs = conn.execute('SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT ?', (lim,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in logs])

@app.route('/api/stats')
@login_required
def get_stats():
    conn  = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    wd    = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    r = {
        'total':          conn.execute('SELECT COUNT(*) as c FROM tasks').fetchone()['c'],
        'in_progress':    conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='in_progress'").fetchone()['c'],
        'done':           conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='done'").fetchone()['c'],
        'todo':           conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='todo'").fetchone()['c'],
        'completed_week': conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='done' AND updated_at >= ?", (wd,)).fetchone()['c'],
        'overdue':        conn.execute("SELECT COUNT(*) as c FROM tasks WHERE due_date < ? AND status!='done'", (today,)).fetchone()['c'],
    }
    conn.close()
    return jsonify(r)

# ── TELEGRAM WEBHOOK ──────────────────────────────────────────────────────────
@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    try:
        update = request.json
        handle_telegram_update(update)
    except Exception as e:
        print(f'[TG webhook] error: {e}')
    return jsonify({'ok': True})

@app.route('/telegram/setup')
@login_required
def telegram_setup():
    """Call this once from browser after deploy to register the webhook."""
    ok  = tg_set_webhook(f'{CRM_URL}/telegram/webhook')
    return jsonify({'webhook_set': ok, 'url': f'{CRM_URL}/telegram/webhook'})

# ── WHATSAPP IMPORT ───────────────────────────────────────────────────────────
@app.route('/api/import/whatsapp', methods=['POST'])
@login_required
def import_whatsapp():
    """
    POST with JSON: { "text": "<full whatsapp export text>", "category": "optional" }
    OR as multipart/form-data with file field "file".
    """
    category = 'WhatsApp Import'

    if request.content_type and 'multipart' in request.content_type:
        f    = request.files.get('file')
        if not f:
            return jsonify({'error': 'No file uploaded'}), 400
        try:
            text = f.read().decode('utf-8')
        except Exception:
            text = f.read().decode('latin-1')
        category = request.form.get('category', category)
    else:
        d        = request.json or {}
        text     = d.get('text', '')
        category = d.get('category', category)

    if not text.strip():
        return jsonify({'error': 'Empty text'}), 400

    entries = parse_whatsapp_export(text, category)
    if not entries:
        return jsonify({'error': 'No parseable messages found. Make sure this is an exported WhatsApp chat .txt file.'}), 400

    conn  = get_db()
    c     = conn.cursor()
    count = 0
    for title, content, cat in entries:
        c.execute('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)', (title, content, cat))
        count += 1
    log_action(c, 'WhatsApp KB import', f'Imported {count} days of chat as KB entries')
    conn.commit(); conn.close()

    return jsonify({'success': True, 'imported': count, 'category': category})

# ── GROUP KNOWLEDGE ───────────────────────────────────────────────────────────
@app.route('/api/group-knowledge', methods=['GET'])
@login_required
def get_group_knowledge():
    conn = get_db()
    rows = conn.execute('SELECT * FROM group_knowledge ORDER BY timestamp DESC LIMIT 100').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/group-knowledge/sync', methods=['POST'])
@login_required
def manual_sync_groups():
    """Manually trigger group → KB sync from the dashboard."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM group_knowledge WHERE synced_to_kb=0 ORDER BY timestamp').fetchall()
    if not rows:
        conn.close()
        return jsonify({'synced': 0})
    by_chat = {}
    for r in rows:
        key = r['chat_title'] or r['chat_id']
        by_chat.setdefault(key, []).append(f"[{r['speaker']}]: {r['message']}")
    count = 0
    c = conn.cursor()
    for chat_title, messages in by_chat.items():
        batch = '\n'.join(messages[:50])
        title = f"Group: {chat_title} — {datetime.now().strftime('%Y-%m-%d')}"
        c.execute('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)',
                  (title, batch, 'Team Conversations'))
        count += len(messages)
    c.execute('UPDATE group_knowledge SET synced_to_kb=1 WHERE synced_to_kb=0')
    log_action(c, 'Group KB sync', f'Synced {count} messages')
    conn.commit(); conn.close()
    return jsonify({'synced': count})

# ── BOT / OPENCLAW SKILL API ──────────────────────────────────────────────────
# These routes use X-Bot-Key header auth (no session needed) so OpenClaw skill
# can call them directly from your local machine or from the TUI.

@app.route('/bot/tasks', methods=['GET'])
@bot_auth_required
def bot_get_tasks():
    conn  = get_db()
    tasks = conn.execute(
        "SELECT t.id,t.title,t.status,t.priority,t.due_date,tm.name as assignee FROM tasks t LEFT JOIN team_members tm ON t.assigned_to=tm.id ORDER BY t.created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in tasks])

@app.route('/bot/tasks', methods=['POST'])
@bot_auth_required
def bot_create_task():
    d    = request.json or {}
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO tasks (title,description,priority,due_date,assigned_by,tags) VALUES (?,?,?,?,?,?)',
              (d.get('title','Untitled'), d.get('description',''), d.get('priority','medium'),
               d.get('due_date'), d.get('assigned_by','OpenClaw'), d.get('tags','')))
    tid = c.lastrowid
    log_action(c, 'Task created via OpenClaw', d.get('title',''))
    conn.commit(); conn.close()
    return jsonify({'id': tid, 'success': True})

@app.route('/bot/tasks/<int:tid>', methods=['PATCH'])
@bot_auth_required
def bot_update_task(tid):
    d      = request.json or {}
    conn   = get_db()
    c      = conn.cursor()
    fields = []; vals = []
    for f in ['title','status','priority','due_date','tags','description']:
        if f in d:
            fields.append(f'{f}=?'); vals.append(d[f])
    if fields:
        fields.append("updated_at=datetime('now')")
        vals.append(tid)
        c.execute(f'UPDATE tasks SET {", ".join(fields)} WHERE id=?', vals)
        log_action(c, 'Task updated via OpenClaw', f'#{tid}')
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/bot/notes', methods=['POST'])
@bot_auth_required
def bot_create_note():
    d    = request.json or {}
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO notes (title,content) VALUES (?,?)',
              (d.get('title','Untitled'), d.get('content','')))
    nid = c.lastrowid
    log_action(c, 'Note created via OpenClaw', d.get('title',''))
    conn.commit(); conn.close()
    return jsonify({'id': nid, 'success': True})

@app.route('/bot/kb', methods=['GET'])
@bot_auth_required
def bot_search_kb():
    q       = request.args.get('q', '')
    conn    = get_db()
    entries = conn.execute(
        "SELECT id,title,category,substr(content,1,300) as preview FROM kb_entries WHERE title LIKE ? OR content LIKE ? LIMIT 10",
        (f'%{q}%', f'%{q}%')).fetchall()
    conn.close()
    return jsonify([dict(r) for r in entries])

@app.route('/bot/kb', methods=['POST'])
@bot_auth_required
def bot_create_kb():
    d    = request.json or {}
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO kb_entries (title,content,category) VALUES (?,?,?)',
              (d.get('title','Untitled'), d.get('content',''), d.get('category','General')))
    kid = c.lastrowid
    log_action(c, 'KB entry via OpenClaw', d.get('title',''))
    conn.commit(); conn.close()
    return jsonify({'id': kid, 'success': True})

@app.route('/bot/stats', methods=['GET'])
@bot_auth_required
def bot_stats():
    conn  = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    r = {
        'total':       conn.execute('SELECT COUNT(*) as c FROM tasks').fetchone()['c'],
        'in_progress': conn.execute("SELECT COUNT(*) as c FROM tasks WHERE status='in_progress'").fetchone()['c'],
        'overdue':     conn.execute("SELECT COUNT(*) as c FROM tasks WHERE due_date < ? AND status!='done'", (today,)).fetchone()['c'],
        'notes':       conn.execute('SELECT COUNT(*) as c FROM notes').fetchone()['c'],
        'kb_entries':  conn.execute('SELECT COUNT(*) as c FROM kb_entries').fetchone()['c'],
    }
    conn.close()
    return jsonify(r)

@app.route('/bot/reminders', methods=['POST'])
@bot_auth_required
def bot_create_reminder():
    d    = request.json or {}
    conn = get_db()
    c    = conn.cursor()
    c.execute('INSERT INTO reminders (title,description,remind_at,repeat_type) VALUES (?,?,?,?)',
              (d.get('title',''), d.get('description',''), d.get('remind_at'), d.get('repeat_type','none')))
    rid = c.lastrowid
    log_action(c, 'Reminder via OpenClaw', d.get('title',''))
    conn.commit(); conn.close()
    return jsonify({'id': rid, 'success': True})

@app.route('/bot/ping', methods=['GET'])
@bot_auth_required
def bot_ping():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})

# ── FRONTEND ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8090)), debug=False)
