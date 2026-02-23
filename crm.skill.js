/**
 * WorkBase CRM Skill for OpenClaw
 * 
 * Install: drop this file in your OpenClaw skills/ folder,
 * then say "load CRM skill" or restart OpenClaw.
 * 
 * Set environment variables in your OpenClaw config:
 *   CRM_URL     = https://your-app.railway.app
 *   CRM_BOT_KEY = crm-bot-secret-key-change-me   (must match BOT_API_KEY in app.py)
 */

const CRM_URL     = process.env.CRM_URL     || 'https://your-app.railway.app';
const CRM_BOT_KEY = process.env.CRM_BOT_KEY || 'crm-bot-secret-key-change-me';

const headers = {
  'Content-Type':  'application/json',
  'X-Bot-Key':     CRM_BOT_KEY,
};

async function crmFetch(path, opts = {}) {
  const url = `${CRM_URL}${path}`;
  const res  = await fetch(url, { headers, ...opts });
  return res.json();
}

// ── SKILL DEFINITION ──────────────────────────────────────────────────────────
export default {
  name:        'WorkBase CRM',
  description: 'Manage your CRM board: tasks, notes, KB, reminders, stats.',
  version:     '1.0.0',

  // ── Tool declarations (OpenClaw uses these to decide when to call the skill)
  tools: [
    {
      name:        'crm_get_tasks',
      description: 'List your CRM tasks. Optionally filter by status (todo|in_progress|done).',
      parameters:  {
        type:       'object',
        properties: {
          status: { type: 'string', enum: ['todo', 'in_progress', 'done', 'all'], default: 'all' }
        }
      },
      async execute({ status = 'all' }) {
        const tasks = await crmFetch('/bot/tasks');
        const filtered = status === 'all' ? tasks : tasks.filter(t => t.status === status);
        if (!filtered.length) return `No ${status === 'all' ? '' : status + ' '}tasks found.`;
        return filtered.map(t =>
          `#${t.id} [${t.priority.toUpperCase()}] ${t.title} — ${t.status}` +
          (t.due_date ? ` (due ${t.due_date})` : '') +
          (t.assignee  ? ` → ${t.assignee}`   : '')
        ).join('\n');
      }
    },

    {
      name:        'crm_create_task',
      description: 'Create a new task in the CRM board.',
      parameters:  {
        type:       'object',
        required:   ['title'],
        properties: {
          title:       { type: 'string',  description: 'Task title' },
          description: { type: 'string',  description: 'Optional details' },
          priority:    { type: 'string',  enum: ['low','medium','high','urgent'], default: 'medium' },
          due_date:    { type: 'string',  description: 'YYYY-MM-DD format' },
          tags:        { type: 'string',  description: 'Comma-separated tags' },
        }
      },
      async execute(params) {
        const res = await crmFetch('/bot/tasks', {
          method: 'POST',
          body:   JSON.stringify({ ...params, assigned_by: 'OpenClaw' })
        });
        return res.success ? `✅ Task #${res.id} created: ${params.title}` : `❌ Failed: ${JSON.stringify(res)}`;
      }
    },

    {
      name:        'crm_update_task',
      description: 'Update a task status, priority, or other field.',
      parameters:  {
        type:       'object',
        required:   ['id'],
        properties: {
          id:       { type: 'number', description: 'Task ID' },
          status:   { type: 'string', enum: ['todo','in_progress','done'] },
          priority: { type: 'string', enum: ['low','medium','high','urgent'] },
          due_date: { type: 'string' },
          title:    { type: 'string' },
        }
      },
      async execute({ id, ...fields }) {
        const res = await crmFetch(`/bot/tasks/${id}`, {
          method: 'PATCH',
          body:   JSON.stringify(fields)
        });
        return res.success ? `✅ Task #${id} updated.` : `❌ Failed.`;
      }
    },

    {
      name:        'crm_get_stats',
      description: 'Get dashboard stats: total tasks, in progress, overdue, notes, KB entries.',
      parameters:  { type: 'object', properties: {} },
      async execute() {
        const s = await crmFetch('/bot/stats');
        return (
          `📊 CRM Stats:\n` +
          `• Total tasks:   ${s.total}\n` +
          `• In progress:   ${s.in_progress}\n` +
          `• Overdue:       ${s.overdue}\n` +
          `• Notes:         ${s.notes}\n` +
          `• KB entries:    ${s.kb_entries}`
        );
      }
    },

    {
      name:        'crm_search_kb',
      description: 'Search the Knowledge Base. Use this to find company info, processes, team docs.',
      parameters:  {
        type:       'object',
        required:   ['query'],
        properties: {
          query: { type: 'string', description: 'Search query' }
        }
      },
      async execute({ query }) {
        const results = await crmFetch(`/bot/kb?q=${encodeURIComponent(query)}`);
        if (!results.length) return `No KB results for "${query}".`;
        return results.map(e =>
          `📚 **${e.title}** [${e.category}]\n${e.preview}`
        ).join('\n\n');
      }
    },

    {
      name:        'crm_add_kb',
      description: 'Add a new entry to the Knowledge Base.',
      parameters:  {
        type:       'object',
        required:   ['title', 'content'],
        properties: {
          title:    { type: 'string' },
          content:  { type: 'string' },
          category: { type: 'string', default: 'General' },
        }
      },
      async execute(params) {
        const res = await crmFetch('/bot/kb', {
          method: 'POST',
          body:   JSON.stringify(params)
        });
        return res.success ? `✅ KB entry #${res.id} added: ${params.title}` : `❌ Failed.`;
      }
    },

    {
      name:        'crm_create_note',
      description: 'Save a quick note to the CRM.',
      parameters:  {
        type:       'object',
        required:   ['title'],
        properties: {
          title:   { type: 'string' },
          content: { type: 'string', default: '' },
        }
      },
      async execute(params) {
        const res = await crmFetch('/bot/notes', {
          method: 'POST',
          body:   JSON.stringify(params)
        });
        return res.success ? `✅ Note #${res.id} saved: ${params.title}` : `❌ Failed.`;
      }
    },

    {
      name:        'crm_create_reminder',
      description: 'Create a reminder in the CRM.',
      parameters:  {
        type:       'object',
        required:   ['title'],
        properties: {
          title:       { type: 'string' },
          description: { type: 'string' },
          remind_at:   { type: 'string', description: 'ISO datetime: 2024-03-15T09:00:00' },
          repeat_type: { type: 'string', enum: ['none','daily','weekly','monthly'], default: 'none' },
        }
      },
      async execute(params) {
        const res = await crmFetch('/bot/reminders', {
          method: 'POST',
          body:   JSON.stringify(params)
        });
        return res.success ? `✅ Reminder #${res.id} set: ${params.title}` : `❌ Failed.`;
      }
    },

    {
      name:        'crm_ping',
      description: 'Check if the CRM server is online.',
      parameters:  { type: 'object', properties: {} },
      async execute() {
        try {
          const r = await crmFetch('/bot/ping');
          return `✅ CRM online. Server time: ${r.time}`;
        } catch {
          return `❌ CRM is unreachable at ${CRM_URL}`;
        }
      }
    },
  ],

  // ── Onboarding message shown when skill loads ──────────────────────────────
  onLoad() {
    return `🦞 WorkBase CRM skill loaded!\n\nYou can now:\n• "Show my tasks"\n• "Create task: Fix login bug, high priority"\n• "Search KB for onboarding"\n• "Add note: Client meeting notes..."\n• "CRM stats"\n\nCRM URL: ${CRM_URL}`;
  }
};
