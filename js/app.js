(() => {
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const colorOk = c => /^#[0-9a-f]{3,8}$/i.test(c || '') ? c : '#0084ff';
const imgOk = u => typeof u === 'string' && u.startsWith('data:image/');

let npw = null, ws, me = null, servers = [], dms = [], srv = null, sd = null, cur = null, msgs = [];
let replyTo = null, mode = 'login', pending = null, typing = {}, unread = new Set(), lastTyping = 0, typingTimer;
let reactMsgId = null;

const send = o => ws && ws.readyState === 1 && ws.send(JSON.stringify(o));
function typingMsg(f) { if (cur) send(cur.kind === 'ch' ? {type: 'typing', channel_id: cur.id, is_typing: f} : {type: 'dm_typing', dm_id: cur.id, is_typing: f}); }
const parseTs = s => new Date(String(s).replace(' ', 'T') + 'Z');
const dayKey = s => parseTs(s).toDateString();
const dayLabel = s => { const d = parseTs(s), t = new Date(), y = new Date(); y.setDate(t.getDate() - 1); return d.toDateString() === t.toDateString() ? 'Today' : d.toDateString() === y.toDateString() ? 'Yesterday' : d.toLocaleDateString([], {day: 'numeric', month: 'short', year: 'numeric'}); };
const fmt = s => esc(s).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');

function emptyHtml() {
  if (!cur) return `
    <div class="empty">
      <div class="big" style="font-size:42px">&#128172;</div>
      <h2 style="font-size:20px;font-weight:700">Welcome${me ? ', ' + esc(me.username) : ''}</h2>
      <p style="font-size:13.5px;max-width:280px;line-height:1.4">${srv ? 'Select a channel on the left to start chatting.' : 'Pick a room from the bar or start a direct message.'}</p>
      <button class="primary" data-a="opennav" style="font-size:13px;padding:8px 16px">Browse Channels</button>
    </div>`;
  if (!msgs.length) return `
    <div class="empty">
      <div class="big" style="font-size:36px">&#128075;</div>
      <p style="font-size:14px;color:var(--tx);font-weight:600;margin:0">No messages here yet</p>
      <p style="font-size:12.5px;color:var(--mut);margin:0">Be the first to say hello!</p>
    </div>`;
  return '';
}

const wide = () => matchMedia('(min-width:900px)').matches;
const THEMES = [
  '#050b16',
  'linear-gradient(135deg,#0d2246,#060c18)',
  'linear-gradient(135deg,#1e1b4b,#0f172a)',
  'linear-gradient(135deg,#311025,#090d16)',
  'linear-gradient(135deg,#064e3b,#022c22)',
  'linear-gradient(135deg,#ecdad9 0%,#f6eeeb 45%,#dedae9 100%)'
];

const WALLPAPER_PRESETS = [
  { id: 'none', name: 'Default', bg: '' },
  { id: 'nebula', name: 'Cosmic', bg: 'linear-gradient(135deg,#0f172a 0%,#1e1b4b 50%,#311025 100%)' },
  { id: 'rose', name: 'Pastel Rose', bg: 'linear-gradient(135deg,#ecdad9 0%,#f6eeeb 50%,#dedae9 100%)' },
  { id: 'slate', name: 'Obsidian', bg: 'linear-gradient(135deg,#18181b 0%,#27272a 100%)' },
  { id: 'aurora', name: 'Aurora', bg: 'linear-gradient(135deg,#064e3b 0%,#022c22 50%,#042f2e 100%)' },
  { id: 'sunset', name: 'Sunset', bg: 'linear-gradient(135deg,#450a0a 0%,#2e1065 100%)' }
];

const applyTheme = () => {
  const t = localStorage.getItem('lan_bg') || THEMES[5];
  document.body.style.setProperty('--bgimg', t);
};

const toast = t => {
  const d = document.createElement('div');
  d.className = 'toast';
  d.textContent = t;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 2800);
};

const av = (u, cls = '') => imgOk(u.avatar_url)
  ? `<div class="av ${cls}"><img src="${esc(u.avatar_url)}" alt=""></div>`
  : `<div class="av ${cls}" style="background:${colorOk(u.avatar_color)}">${esc((u.username || '?')[0].toUpperCase())}</div>`;

const ts = s => { const d = new Date(String(s).replace(' ', 'T') + 'Z'); return isNaN(d) ? '' : d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); };
const canAdmin = () => sd && ['owner', 'admin'].includes(sd.my_role);
const canMod = () => sd && ['owner', 'admin', 'mod'].includes(sd.my_role);

let actx;
const beep = () => {
  if (localStorage.getItem('lan_ping') === '0') return;
  try {
    actx = actx || new AudioContext();
    const o = actx.createOscillator(), g = actx.createGain();
    o.connect(g); g.connect(actx.destination);
    o.frequency.value = 880; g.gain.value = .05;
    o.start(); o.stop(actx.currentTime + .1);
  } catch (e) {}
};

// ---------- image helper ----------
const toData = (file, max, q = .8) => new Promise((res, rej) => {
  const r = new FileReader();
  r.onerror = rej;
  r.onload = () => {
    const im = new Image();
    im.onerror = rej;
    im.onload = () => {
      const k = Math.min(1, max / Math.max(im.width, im.height));
      const c = document.createElement('canvas');
      c.width = Math.round(im.width * k);
      c.height = Math.round(im.height * k);
      c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
      res(c.toDataURL('image/jpeg', q));
    };
    im.src = r.result;
  };
  r.readAsDataURL(file);
});

// ---------- URL invite code helper ----------
function getUrlInviteCode() {
  const h = location.hash || '';
  const m = h.match(/invite=([a-zA-Z0-9_-]+)/) || h.match(/^#([a-zA-Z0-9_-]{6,16})$/);
  if (m) return m[1];
  const p = new URLSearchParams(location.search);
  return p.get('invite') || '';
}

function checkUrlInvite() {
  const code = getUrlInviteCode();
  if (!code) return;
  if (!me) {
    setMode('register');
    $('a-invite').value = code;
    $('auth-error').innerHTML = `<div class="auth-invite-banner">🔒 You've been invited! Register or log in to enter.</div>`;
  } else {
    send({type: 'inspect_invite', code});
  }
}

// ---------- modal ----------
function modal(title, fields, ok, cb, extra = '') {
  const o = $('overlay');
  o.innerHTML = `<div class="modal"><h3>${esc(title)}</h3>${extra}${fields.map(f => {
    const v = f.value ?? '', l = f.label ? `<label style="font-size:12px;color:var(--mut);font-weight:600">${esc(f.label)}</label>` : '';
    if (f.type === 'textarea') return `${l}<textarea id="f-${f.id}" rows="3" maxlength="200">${esc(v)}</textarea>`;
    if (f.type === 'select') return `${l}<select id="f-${f.id}" style="padding:10px;background:var(--p2);color:var(--tx);border-radius:12px;border:1px solid var(--line)">${f.options.map(x => `<option value="${esc(x.v)}" ${x.v === v ? 'selected' : ''}>${esc(x.t)}</option>`).join('')}</select>`;
    return `${l}<input id="f-${f.id}" type="${f.type || 'text'}" value="${esc(v)}" ${f.type === 'file' ? 'accept="image/*"' : ''}>`;
  }).join('')}<div class="row">${ok ? '<button class="primary" id="m-ok">' + esc(ok) + '</button>' : ''}<button id="m-x">Close</button></div></div>`;
  o.hidden = false;
  const close = () => { o.hidden = true; o.innerHTML = ''; };
  o.onclick = e => { if (e.target === o) close(); };
  $('m-x').onclick = close;
  if (ok) $('m-ok').onclick = async () => {
    const v = {};
    for (const f of fields) {
      const el = $('f-' + f.id);
      v[f.id] = f.type === 'file' ? el.files[0] : el.value;
    }
    if (await cb(v) !== false) close();
  };
  const first = o.querySelector('input,textarea,select');
  first && first.focus();
}

// ---------- invite share modal ----------
function showInviteShareModal(server, invite, isNew = false) {
  const fullLink = `${location.protocol}//${location.host}${location.pathname}#invite=${invite.code}`;
  modal(isNew ? '🎉 Private Room Ready' : 'Invite to ' + server.name, [], '', null, `
    <div class="invite-card">
      <p style="margin:0;font-size:13.5px;color:var(--tx);line-height:1.4">
        Share this private invite link with friends. Anyone with this link can join <b>${esc(server.name)}</b> directly:
      </p>
      <div class="invite-box" style="width:100%">
        <input id="inv-link-input" readonly value="${esc(fullLink)}">
        <button class="primary" id="btn-copy-inv">Copy Link</button>
      </div>
      <div style="font-size:12px;color:var(--mut);display:flex;justify-content:space-between;width:100%;margin-top:2px">
        <span>Invite Code: <b style="color:var(--tx)">${esc(invite.code)}</b></span>
        <span>${invite.max_uses ? invite.max_uses + ' uses max' : 'Unlimited uses'} &bull; 7 days</span>
      </div>
    </div>
  `);
  $('btn-copy-inv').onclick = () => {
    const fallbackCopy = () => {
      const el = $('inv-link-input');
      el.select();
      document.execCommand('copy');
      $('btn-copy-inv').textContent = '✓ Copied!';
      toast('Invite link copied!');
      setTimeout(() => { if ($('btn-copy-inv')) $('btn-copy-inv').textContent = 'Copy Link'; }, 2500);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(fullLink).then(() => {
        $('btn-copy-inv').textContent = '✓ Copied!';
        toast('Invite link copied to clipboard!');
        setTimeout(() => { if ($('btn-copy-inv')) $('btn-copy-inv').textContent = 'Copy Link'; }, 2500);
      }).catch(fallbackCopy);
    } else {
      fallbackCopy();
    }
  };
}

// ---------- interactive wallpaper modal ----------
function openWallpaperModal() {
  if (!srv || !sd) return;
  const isAdm = canAdmin();
  const personalKey = 'lan_bg_srv_' + srv;
  const currentPersonal = localStorage.getItem(personalKey) || '';
  const currentGroup = sd.server.background_url || '';
  let activeScope = currentPersonal ? 'personal' : (isAdm ? 'group' : 'personal');
  let selectedVal = currentPersonal || currentGroup || '';

  const o = $('overlay');
  o.innerHTML = `
    <div class="modal">
      <h3>🎨 Room Wallpaper</h3>
      <div class="segmented">
        <button type="button" class="${activeScope === 'personal' ? 'active' : ''}" id="scope-personal">👤 For Me Only</button>
        <button type="button" class="${activeScope === 'group' ? 'active' : ''}" id="scope-group" ${isAdm ? '' : 'disabled title="Requires Admin or Owner role"'}>👥 For Everyone ${isAdm ? '' : '(Admin)'}</button>
      </div>
      <p id="scope-hint" style="font-size:12px;color:var(--mut);margin:2px 0 8px">
        ${activeScope === 'personal' ? 'Applies only on your device. Overrides group wallpaper.' : 'Changes the shared wallpaper for all members in this room (Admin).'}
      </p>

      <label style="font-size:12px;color:var(--mut);font-weight:700">PRESETS</label>
      <div class="bg-presets">
        ${WALLPAPER_PRESETS.map(p => `
          <div class="bg-preset" data-bg="${esc(p.bg)}" style="background:${p.bg || 'rgba(0,0,0,.08)'};color:${p.bg ? '#fff' : 'var(--tx)'}">
            ${esc(p.name)}
          </div>
        `).join('')}
      </div>

      <label style="font-size:12px;color:var(--mut);font-weight:700;margin-top:6px">OR UPLOAD CUSTOM IMAGE</label>
      <input type="file" id="bg-file-input" accept="image/*" style="font-size:13px">

      <div class="row" style="margin-top:12px">
        <button class="primary" id="btn-save-bg">Apply</button>
        <button id="btn-reset-bg" style="background:none;border:1px solid var(--line)">Reset</button>
        <button id="btn-close-bg">Close</button>
      </div>
    </div>
  `;
  o.hidden = false;

  const updateScopeUI = () => {
    $('scope-personal').classList.toggle('active', activeScope === 'personal');
    $('scope-group').classList.toggle('active', activeScope === 'group');
    $('scope-hint').textContent = activeScope === 'personal'
      ? 'Applies only on your device. Overrides group wallpaper.'
      : 'Changes the shared wallpaper for all members in this room (Admin).';
  };

  $('scope-personal').onclick = () => { activeScope = 'personal'; updateScopeUI(); };
  $('scope-group').onclick = () => { if (isAdm) { activeScope = 'group'; updateScopeUI(); } };

  o.querySelectorAll('.bg-preset').forEach(el => {
    el.onclick = () => {
      selectedVal = el.dataset.bg;
      o.querySelectorAll('.bg-preset').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
    };
  });

  $('bg-file-input').onchange = async e => {
    const f = e.target.files[0];
    if (f) {
      try {
        selectedVal = await toData(f, 1920, .82);
        toast('Image loaded for wallpaper');
      } catch (err) {
        toast('Failed to load image');
      }
    }
  };

  $('btn-save-bg').onclick = () => {
    if (activeScope === 'personal') {
      if (selectedVal) {
        localStorage.setItem(personalKey, selectedVal);
        toast('Personal wallpaper saved!');
      } else {
        localStorage.removeItem(personalKey);
        toast('Personal wallpaper cleared');
      }
      renderHeader();
    } else if (activeScope === 'group') {
      if (!isAdm) return;
      send({
        type: 'update_server',
        server_id: srv,
        background_url: selectedVal || 'reset'
      });
      toast('Updating room wallpaper for all members...');
    }
    o.hidden = true;
  };

  $('btn-reset-bg').onclick = () => {
    if (activeScope === 'personal') {
      localStorage.removeItem(personalKey);
      toast('Personal wallpaper reset to group default');
      renderHeader();
      o.hidden = true;
    } else if (activeScope === 'group') {
      if (!isAdm) return;
      send({
        type: 'update_server',
        server_id: srv,
        background_url: 'reset'
      });
      toast('Group wallpaper reset');
      o.hidden = true;
    }
  };

  $('btn-close-bg').onclick = () => { o.hidden = true; };
  o.onclick = e => { if (e.target === o) o.hidden = true; };
}

// ---------- interactive member card ----------
function showMemberProfile(u) {
  const isSelf = u.id === me.id;
  const owner = sd && sd.my_role === 'owner';
  const canManage = canAdmin() && !isSelf && u.role !== 'owner';
  const roleClass = 'role-' + (u.role || 'member');

  const o = $('overlay');
  o.innerHTML = `
    <div class="modal">
      <div class="profile-card">
        ${av(u)}
        <h3>${esc(u.username)}</h3>
        <div class="role-badge ${roleClass}">
          ${u.role === 'owner' ? '👑 Owner' : u.role === 'admin' ? '🛡️ Admin' : u.role === 'mod' ? '⚔️ Moderator' : 'Member'}
        </div>
        <div class="profile-status">${u.online ? '<span style="color:var(--green)">● Online</span>' : '<span style="color:var(--mut)">○ Offline</span>'}${u.custom_status ? ' &bull; ' + esc(u.custom_status) : ''}</div>
        ${u.bio ? `<div class="profile-bio">${esc(u.bio)}</div>` : ''}

        <div class="profile-actions">
          ${isSelf ? '' : '<button class="primary" id="card-dm-btn">💬 Send Message</button>'}
          ${canManage ? '<button id="card-manage-btn" style="background:rgba(0,0,0,.05)">⚙️ Manage</button>' : ''}
          <button id="card-close-btn" style="background:none;border:1px solid var(--line)">Close</button>
        </div>
      </div>
    </div>
  `;
  o.hidden = false;

  if ($('card-dm-btn')) {
    $('card-dm-btn').onclick = () => {
      o.hidden = true;
      openDm(u.id);
    };
  }
  if ($('card-manage-btn')) {
    $('card-manage-btn').onclick = () => {
      o.hidden = true;
      modal(u.username, owner ? [{id: 'role', label: 'Role', type: 'select', options: ['member', 'mod', 'admin'].map(r => ({v: r, t: r}))}] : [], owner ? 'Set role' : '', v => send({type: 'set_member_role', server_id: srv, user_id: u.id, role: v.role}),
        '<button id="m-kick" style="background:var(--red);color:#fff">Remove from Room</button>');
      if (owner && $('f-role')) $('f-role').value = u.role;
      const k = $('m-kick');
      if (k) k.onclick = () => { if (confirm('Remove ' + u.username + ' from this room?')) { send({type: 'kick_member', server_id: srv, user_id: u.id}); $('overlay').click(); } };
    };
  }
  $('card-close-btn').onclick = () => { o.hidden = true; };
  o.onclick = e => { if (e.target === o) o.hidden = true; };
}

// ---------- connection ----------
function getWsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  // If running over tunnel / domain or port 8000, connect on the same port via /ws proxy
  if (!location.port || location.port === '80' || location.port === '443' || location.port === '8000') {
    return `${proto}://${location.host}/ws`;
  }
  return `${proto}://${location.hostname}:8001`;
}

function connect() {
  ws = new WebSocket(getWsUrl());
  ws.onopen = () => {
    $('status').textContent = '';
    if (pending) { send({type: pending.mode, ...pending.c}); }
  };
  ws.onmessage = e => {
    try { handle(JSON.parse(e.data)); } catch (x) { console.error(x); }
  };
  ws.onclose = () => {
    $('status').textContent = 'Reconnecting…';
    setTimeout(connect, 1500);
  };
}

function login(m, c) {
  pending = {mode: m, c};
  if (ws.readyState === 1) send({type: m, ...c});
}

// ---------- state actions ----------
function selectServer(id) {
  srv = id; sd = null; cur = null; msgs = [];
  send({type: 'get_server_details', server_id: id});
  renderAll();
}

function openChannel(id) {
  typing = {}; cur = {kind: 'ch', id}; msgs = []; replyTo = null;
  unread.delete('c' + id);
  send({type: 'join_channel', channel_id: id});
  renderAll();
  closeNav();
}

function goHome() {
  srv = null; sd = null; cur = null; msgs = [];
  renderAll();
}

function openDm(uid) {
  if (uid !== me.id) {
    send({type: 'open_dm', recipient_id: uid});
  }
}

const closeNav = () => document.body.classList.remove('nav');

// ---------- websocket event dispatcher ----------
function handle(m) {
  switch (m.type) {
    case 'auth_success':
      me = m.user; servers = m.servers; dms = m.dms;
      localStorage.setItem('lan_creds', JSON.stringify(pending.c));
      pending = {mode: 'login', c: pending.c};
      $('auth').hidden = true; $('app').hidden = false;
      if (srv && servers.some(s => s.id === srv)) {
        const c = cur;
        selectServer(srv);
        if (c && c.kind === 'ch') { cur = c; send({type: 'join_channel', channel_id: c.id}); }
      } else if (!srv && servers.length && !cur) {
        selectServer(servers[0].id);
      }
      renderAll();
      checkUrlInvite();
      break;

    case 'auth_error':
      localStorage.removeItem('lan_creds');
      pending = null;
      $('auth').hidden = false;
      $('app').hidden = true;
      $('auth-error').textContent = m.message;
      break;

    case 'initial_data':
      servers = m.servers; dms = m.dms;
      renderAll();
      break;

    case 'server_details':
      if (m.server.id !== srv) break;
      sd = m;
      if (!cur) {
        const t = m.channels.find(c => c.channel_type !== 'voice');
        t ? openChannel(t.id) : renderAll();
      } else {
        renderAll();
      }
      break;

    case 'channel_history':
      if (cur && cur.kind === 'ch' && m.channel.id === cur.id) {
        msgs = m.messages;
        if (sd) sd.members = m.members;
        renderAll();
        scrollEnd(true);
      }
      break;

    case 'new_message': {
      const mine = m.message.user_id === me.id;
      if (cur && cur.kind === 'ch' && cur.id === m.channel_id) {
        const near = nearEnd();
        msgs.push(m.message);
        renderMsgs();
        scrollEnd(near || mine);
        if (!mine && document.hidden) beep();
      } else if (!mine) {
        unread.add('c' + m.channel_id);
        beep();
        renderSide();
      }
      break;
    }

    case 'message_deleted':
      if (cur && cur.id === m.channel_id) {
        msgs = msgs.filter(x => x.id !== m.message_id);
        renderMsgs();
      }
      break;

    case 'reactions_updated':
      if (cur && cur.kind === 'ch' && cur.id === m.channel_id) {
        const x = msgs.find(y => y.id === m.message_id);
        if (x) { x.reactions = m.reactions; renderMsgs(); }
      }
      break;

    case 'user_typing':
      if (cur && cur.kind === 'ch' && cur.id === m.channel_id) {
        clearTimeout(typing[m.username]);
        if (m.is_typing) typing[m.username] = setTimeout(() => { delete typing[m.username]; renderTyping(); }, 4000);
        else delete typing[m.username];
        renderTyping();
      }
      break;

    case 'server_created':
      servers.push(m.server);
      selectServer(m.server.id);
      if (m.invite) {
        showInviteShareModal(m.server, m.invite, true);
      }
      break;

    case 'server_updated':
      servers = servers.map(s => s.id === m.server.id ? {...s, ...m.server} : s);
      if (sd && sd.server.id === m.server.id) sd.server = {...sd.server, ...m.server};
      renderRail();
      renderSide();
      renderHeader();
      break;

    case 'server_left':
      servers = servers.filter(s => s.id !== m.server_id);
      if (srv === m.server_id) goHome();
      else renderAll();
      break;

    case 'member_left':
      if (sd && srv === m.server_id) {
        sd.members = sd.members.filter(x => x.id !== m.user_id);
        renderMembers();
      }
      break;

    case 'category_created':
      if (sd && srv === m.category.server_id) {
        sd.categories.push(m.category);
        renderSide();
      }
      break;

    case 'channel_created':
      if (sd && srv === m.channel.server_id) {
        sd.channels.push(m.channel);
        renderSide();
      }
      break;

    case 'channel_updated':
      if (sd && srv === m.channel.server_id) {
        sd.channels = sd.channels.map(c => c.id === m.channel.id ? m.channel : c);
        renderAll();
      }
      break;

    case 'channel_deleted':
      if (sd && srv === m.server_id) {
        sd.channels = sd.channels.filter(c => c.id !== m.channel_id);
        if (cur && cur.id === m.channel_id) {
          cur = null;
          const t = sd.channels[0];
          t ? openChannel(t.id) : renderAll();
        } else {
          renderSide();
        }
      }
      break;

    case 'dm_history':
      if (!dms.some(d => d.dm_id === m.dm_id)) dms.push({dm_id: m.dm_id, recipient_id: m.recipient.id, ...m.recipient});
      typing = {}; srv = null; sd = null;
      cur = {kind: 'dm', id: m.dm_id, user: m.recipient};
      msgs = m.messages;
      replyTo = null;
      unread.delete('d' + m.dm_id);
      renderAll();
      scrollEnd(true);
      closeNav();
      break;

    case 'new_dm_message': {
      const mine = m.message.user_id === me.id;
      if (!dms.some(d => d.dm_id === m.dm_id)) send({type: 'get_initial_data'});
      if (cur && cur.kind === 'dm' && cur.id === m.dm_id) {
        const near = nearEnd();
        msgs.push(m.message);
        renderMsgs();
        scrollEnd(near || mine);
        if (!mine && document.hidden) beep();
      } else if (!mine) {
        unread.add('d' + m.dm_id);
        beep();
        renderSide();
      }
      break;
    }

    case 'server_invite_created':
      showInviteShareModal(sd ? sd.server : {name: 'Room'}, m.invite);
      break;

    case 'invite_info':
      if (!m.valid) {
        toast(m.message || 'Invalid invite link');
        history.replaceState(null, '', location.pathname);
        break;
      }
      const inv = m.invite;
      modal(inv.server_is_public ? 'Community Invite' : '🔒 Private Room Invitation', [], '', null, `
        <div class="invite-card">
          <div class="logo av" style="background:#231c26;color:#fff">${esc(inv.server_name[0])}</div>
          <h2>${esc(inv.server_name)}</h2>
          <div class="room-tag ${inv.server_is_public ? '' : 'private'}">${inv.server_is_public ? '🌐 Public Community' : '🔒 Hidden Private Room'}</div>
          <p style="font-size:12.5px;color:var(--mut);margin:4px 0">Invited by <b>${esc(inv.inviter_name)}</b> &bull; ${inv.member_count} member${inv.member_count > 1 ? 's' : ''}</p>
          ${inv.server_description ? `<div class="profile-bio">${esc(inv.server_description)}</div>` : ''}
          <div class="row" style="width:100%;margin-top:10px">
            <button class="primary" id="btn-accept-inv">${m.is_member ? 'Open Room' : 'Join Room'}</button>
            <button id="btn-cancel-inv">Dismiss</button>
          </div>
        </div>
      `);
      $('btn-accept-inv').onclick = () => {
        $('overlay').hidden = true;
        history.replaceState(null, '', location.pathname);
        if (m.is_member) {
          selectServer(inv.server_id);
        } else {
          send({type: 'redeem_server_invite', code: inv.code});
        }
      };
      $('btn-cancel-inv').onclick = () => {
        $('overlay').hidden = true;
        history.replaceState(null, '', location.pathname);
      };
      break;

    case 'invite_redeemed':
      toast(m.message);
      send({type: 'get_initial_data'});
      if (m.server) {
        if (!servers.some(s => s.id === m.server.id)) servers.push(m.server);
        selectServer(m.server.id);
      }
      break;

    case 'user_profile':
      showMemberProfile(m.user);
      break;

    case 'profile_updated':
      me = m.user;
      if (srv) send({type: 'get_server_details', server_id: srv});
      renderAll();
      break;

    case 'dm_reactions_updated':
      if (cur && cur.kind === 'dm' && cur.id === m.dm_id) {
        const x = msgs.find(y => y.id === m.message_id);
        if (x) { x.reactions = m.reactions; renderMsgs(); }
      }
      break;

    case 'dm_message_deleted':
      if (cur && cur.kind === 'dm' && cur.id === m.dm_id) {
        msgs = msgs.filter(x => x.id !== m.message_id);
        renderMsgs();
      }
      break;

    case 'dm_user_typing':
      if (cur && cur.kind === 'dm' && cur.id === m.dm_id) {
        clearTimeout(typing[m.username]);
        if (m.is_typing) typing[m.username] = setTimeout(() => { delete typing[m.username]; renderTyping(); }, 4000);
        else delete typing[m.username];
        renderTyping();
      }
      break;

    case 'member_updated':
      if (sd && srv === m.server_id) {
        const x = sd.members.find(y => y.id === m.user_id);
        if (x) x.role = m.role;
        if (m.user_id === me.id) sd.my_role = m.role;
        renderAll();
      }
      break;

    case 'password_changed':
      toast('Password changed');
      if (npw && pending) {
        pending.c.password = npw;
        localStorage.setItem('lan_creds', JSON.stringify(pending.c));
      }
      break;

    case 'account_deleted':
      localStorage.removeItem('lan_creds');
      location.reload();
      break;

    case 'presence':
      if (sd) {
        const x = sd.members.find(y => y.id === m.user_id);
        if (x) {
          x.online = m.online;
          renderMembers();
          renderHeader();
        }
      }
      break;

    case 'error':
      toast(m.message);
      break;
  }
}

// ---------- rendering ----------
function renderAll() {
  renderRail();
  renderSide();
  renderHeader();
  renderMsgs();
  renderMembers();
  renderReply();
}

function renderRail() {
  $('rail').innerHTML = `<div class="ri ${!srv ? 'on' : ''}" data-a="home" title="Direct messages">&#9993;</div>` +
    servers.map(s => {
      const isPrivate = s.is_public === 0 || s.is_public === false;
      return `<div class="ri ${srv === s.id ? 'on' : ''}" data-a="srv" data-id="${s.id}" title="${esc(s.name)}${isPrivate ? ' (Private Room)' : ''}">
        ${imgOk(s.icon_url) ? `<img src="${esc(s.icon_url)}" alt="">` : esc(s.name[0].toUpperCase())}
        ${isPrivate ? '<span class="lock-badge">🔒</span>' : ''}
      </div>`;
    }).join('') +
    `<div class="ri" data-a="newsrv" title="Create Room / Group">+</div><div class="ri" data-a="join" title="Enter invite link or code">&#127915;</div>`;
}

function renderSide() {
  const head = $('side-head'), list = $('side-list');
  $('me-bar').innerHTML = me ? `${av(me, 'sm')}<b data-a="profile" style="cursor:pointer">${esc(me.username)}</b><button class="icon" data-a="settings" title="Account settings">&#9881;</button><button class="icon" data-a="logout" title="Logout">&#9099;</button>` : '';

  if (srv && sd) {
    const owner = sd.my_role === 'owner';
    const isPrivate = sd.server.is_public === 0 || sd.server.is_public === false;
    head.innerHTML = `<span>${isPrivate ? '<span title="Private Room">🔒</span> ' : ''}${esc(sd.server.name)}</span>` +
      `<button class="icon" data-a="invite" title="Share invite link">&#127915;</button>` +
      `<button class="icon" data-a="newch" title="New channel">&#43;</button>` +
      (canAdmin() ? `<button class="icon" data-a="srvset" title="Server settings">&#9881;</button>` : '') +
      (owner ? '' : `<button class="icon" data-a="leave" title="Leave room">&#9167;</button>`);

    const chRow = c => `<div class="item ${cur && cur.kind === 'ch' && cur.id === c.id ? 'on' : ''}" data-a="ch" data-id="${c.id}"># ${esc(c.name)}${unread.has('c' + c.id) ? ' <b style="color:var(--acc)">&bull;</b>' : ''}${canAdmin() ? `<button class="x icon" data-a="chmenu" data-id="${c.id}" title="Channel options">&#8942;</button>` : ''}</div>`;
    const cats = sd.categories.map(k => `<div class="cat">${esc(k.name)}</div>` + sd.channels.filter(c => c.category_id === k.id).map(chRow).join('')).join('');
    const loose = sd.channels.filter(c => !sd.categories.some(k => k.id === c.category_id)).map(chRow).join('');
    list.innerHTML = cats + loose;
  } else if (!srv) {
    head.innerHTML = '<span>Direct Messages</span>';
    list.innerHTML = dms.length ? dms.map(d => `<div class="item ${cur && cur.kind === 'dm' && cur.id === d.dm_id ? 'on' : ''}" data-a="dm" data-id="${d.recipient_id}">${av(d, 'sm')}${esc(d.username)}${unread.has('d' + d.dm_id) ? ' <b style="color:var(--acc)">&bull;</b>' : ''}</div>`).join('')
      : '<div class="cat">No conversations yet. Open a room and click a member to chat.</div>';
  } else {
    head.innerHTML = '<span>Loading…</span>';
    list.innerHTML = '';
  }
}

function renderHeader() {
  let t = 'LAN Chat', meta = '', ic = '#', bg = '', isPrivate = false;

  if (cur && cur.kind === 'ch' && sd) {
    const c = sd.channels.find(x => x.id === cur.id);
    if (c) {
      t = c.name;
      isPrivate = sd.server.is_public === 0 || sd.server.is_public === false;
      meta = c.topic || (sd.members.filter(x => x.online).length + ' online \u00b7 ' + sd.members.length + ' members');

      // Wallpaper resolution hierarchy: Personal -> Channel -> Server -> Default
      const personalBg = localStorage.getItem('lan_bg_srv_' + srv);
      if (personalBg) {
        bg = personalBg.startsWith('data:') ? `linear-gradient(rgba(6,12,24,.68),rgba(6,12,24,.68)),url(${personalBg})` : personalBg;
      } else if (imgOk(c.background_url)) {
        bg = `linear-gradient(rgba(6,12,24,.68),rgba(6,12,24,.68)),url(${c.background_url})`;
      } else if (imgOk(sd.server.background_url)) {
        bg = `linear-gradient(rgba(6,12,24,.68),rgba(6,12,24,.68)),url(${sd.server.background_url})`;
      } else if (sd.server.background_url && sd.server.background_url.includes('gradient')) {
        bg = sd.server.background_url;
      }
    }
  } else if (cur && cur.kind === 'dm') {
    t = cur.user.username; meta = 'Direct message'; ic = t[0].toUpperCase();
  } else if (srv && sd) {
    t = sd.server.name; meta = 'Pick a channel'; ic = t[0].toUpperCase();
    isPrivate = sd.server.is_public === 0 || sd.server.is_public === false;
  }

  $('title').innerHTML = `${isPrivate ? '<span title="Private Room">🔒</span> ' : ''}${esc(t)}`;
  $('meta').textContent = meta;
  $('header-icon').textContent = ic;
  $('msgs').style.backgroundImage = bg;

  // Toggle wallpaper and members button visibility
  const bgBtn = $('bg-btn');
  if (bgBtn) {
    bgBtn.style.display = srv ? '' : 'none';
    const hasPersonal = !!localStorage.getItem('lan_bg_srv_' + srv);
    bgBtn.title = hasPersonal ? 'Wallpaper (Personal active)' : 'Room Wallpaper';
    bgBtn.style.color = hasPersonal ? 'var(--acc)' : '';
  }

  $('members-btn').style.display = srv ? '' : 'none';
  $('msg').disabled = $('send').disabled = $('img-btn').disabled = $('emoji-btn').disabled = !cur;
  $('msg').placeholder = cur ? 'Type a message\u2026' : 'Select a chat to start';
}

const nearEnd = () => { const m = $('msgs'); return m.scrollHeight - m.scrollTop - m.clientHeight < 120; };
const scrollEnd = f => { if (f) { const m = $('msgs'); m.scrollTop = m.scrollHeight; } };

function renderMsgs() {
  const isCh = cur && cur.kind === 'ch';
  $('msgs').innerHTML = emptyHtml() || msgs.map((m, i) => {
    const u = {username: m.username, avatar_color: m.avatar_color, avatar_url: m.avatar_url, id: m.user_id};
    let q = '';
    if (m.reply_to_id) {
      const r = msgs.find(x => x.id === m.reply_to_id);
      q = `<div class="q">&#8617; ${r ? esc(r.username) + ': ' + (r.message_type === 'image' ? '[photo]' : esc(r.content.slice(0, 80))) : 'original message'}</div>`;
    }
    const body = m.message_type === 'image' && imgOk(m.content) ? `<img class="pic" data-a="pic" src="${esc(m.content)}" alt="photo">` : `<div class="c">${fmt(m.content)}</div>`;
    const grp = {};
    (m.reactions || []).forEach(r => { (grp[r.emoji] = grp[r.emoji] || []).push(r); });
    const rx = Object.keys(grp).length ? `<div class="rx">${Object.entries(grp).map(([e, a]) => `<span class="${a.some(r => r.user_id === me.id) ? 'me' : ''}" data-a="rx" data-id="${m.id}" data-e="${esc(e)}" title="${esc(a.map(r => r.username).join(', '))}">${esc(e)} ${a.length}</span>`).join('')}</div>` : '';
    const acts = `<div class="acts">
      <button data-a="reply" data-id="${m.id}" title="Reply">&#8617;</button>
      ${['\u{1F44D}', '\u2764\uFE0F', '\u{1F602}'].map(e => `<button data-a="react" data-id="${m.id}" data-e="${e}">${e}</button>`).join('')}
      <button data-a="morereact" data-id="${m.id}" title="More emojis">&#43;</button>
      ${m.user_id === me.id || (isCh && canMod()) ? `<button data-a="del" data-id="${m.id}" title="Delete">&#128465;</button>` : ''}
    </div>`;
    const p = msgs[i - 1], newDay = !p || dayKey(p.created_at) !== dayKey(m.created_at);
    const cont = !newDay && p.user_id === m.user_id && !m.reply_to_id && (parseTs(m.created_at) - parseTs(p.created_at)) < 300000;
    return (newDay ? `<div class="day"><span>${dayLabel(m.created_at)}</span></div>` : '') +
      `<div class="m ${m.user_id === me.id ? 'mine' : ''} ${cont ? 'cont' : ''}">
        ${cont ? '<div class="av ph"></div>' : `<div style="cursor:pointer" data-a="userprofile" data-id="${m.user_id}">${av(u)}</div>`}
        <div class="b">
          ${cont ? '' : `<div class="n" data-a="userprofile" data-id="${m.user_id}" style="cursor:pointer">${esc(m.username)}</div>`}
          ${q}${body}${rx}<span class="t">${ts(m.created_at)}</span>
        </div>
        ${acts}
      </div>`;
  }).join('');
  $('down').hidden = nearEnd();
}

function renderMembers() {
  const el = $('members');
  if (!srv || !sd) { el.hidden = true; return; }
  el.hidden = !(el.dataset.user === 'open');
  el.innerHTML = '<div class="cat">Members \u2014 ' + sd.members.filter(x => x.online).length + '/' + sd.members.length + ' online</div>' + [...sd.members].sort((a, b) => (b.online ? 1 : 0) - (a.online ? 1 : 0)).map(u =>
    `<div class="item ${u.online ? '' : 'off'}" data-a="userprofile" data-id="${u.id}">
      <div class="pw">${av(u, 'sm')}${u.online ? '<i class="dot"></i>' : ''}</div>
      <span>${esc(u.username)}</span>
      ${u.role !== 'member' ? `<small style="margin-left:auto;font-size:11px;opacity:.75">${esc(u.role)}</small>` : ''}
      ${u.id !== me.id && u.role !== 'owner' && canAdmin() ? `<button class="x icon" data-a="mmenu" data-id="${u.id}" title="Manage">&#8942;</button>` : ''}
    </div>`).join('');
}

function renderTyping() {
  const n = Object.keys(typing);
  $('typing').textContent = n.length ? n.join(', ') + (n.length > 1 ? ' are' : ' is') + ' typing…' : '';
}

function renderReply() {
  $('reply-bar').hidden = !replyTo;
  if (replyTo) $('reply-text').textContent = 'Replying to ' + replyTo.username + ': ' + (replyTo.message_type === 'image' ? '[photo]' : replyTo.content.slice(0, 60));
}

// ---------- click handling ----------
document.addEventListener('click', e => {
  const t = e.target.closest('[data-a]');
  if (!t) {
    const mm = e.target.closest('.m');
    if (mm) {
      const was = mm.classList.contains('sel');
      document.querySelectorAll('.m.sel').forEach(x => x.classList.remove('sel'));
      if (!was) mm.classList.add('sel');
    }
    if (!e.target.closest('#emoji-picker,#emoji-btn,[data-a="morereact"]')) {
      $('emoji-picker').hidden = true;
      reactMsgId = null;
    }
    return;
  }
  const a = t.dataset.a, id = +t.dataset.id;
  switch (a) {
    case 'home': goHome(); break;
    case 'srv': selectServer(id); break;
    case 'ch': openChannel(id); break;
    case 'dm': openDm(id); break;
    case 'userprofile': {
      if (sd) {
        const u = sd.members.find(x => x.id === id);
        if (u) { showMemberProfile(u); break; }
      }
      send({type: 'get_user_profile', user_id: id, server_id: srv});
      break;
    }
    case 'newsrv':
      modal('Create Room / Group', [
        {id: 'name', label: 'Room Name'},
        {id: 'desc', label: 'Description (optional)'},
        {id: 'privacy', label: 'Room Privacy', type: 'select', options: [
          {v: 'private', t: '🔒 Hidden Room (Invite-only, hidden from non-members)'},
          {v: 'public', t: '🌐 Public Community (Auto-joined by all members)'}
        ]}
      ], 'Create Room', v => {
        if (!v.name.trim()) return false;
        send({
          type: 'create_server',
          name: v.name.trim(),
          description: v.desc,
          is_public: v.privacy === 'public'
        });
      });
      break;
    case 'join':
      modal('Join Room', [{id: 'code', label: 'Invite Link or Code'}], 'Join', v => {
        let val = v.code.trim();
        if (!val) return false;
        const m = val.match(/invite=([a-zA-Z0-9_-]+)/) || val.match(/#([a-zA-Z0-9_-]{6,16})/);
        if (m) val = m[1];
        send({type: 'redeem_server_invite', code: val});
      });
      break;
    case 'invite':
      modal('Create Invite Link', [
        {id: 'max', label: 'Max uses (0 = unlimited)', type: 'number', value: 0},
        {id: 'hrs', label: 'Expires in hours (e.g. 168 = 7 days)', type: 'number', value: 168}
      ], 'Generate Link', v => {
        send({type: 'create_server_invite', server_id: srv, max_uses: +v.max || 0, expires_in_hours: +v.hrs || 168});
      });
      break;
    case 'newch':
      modal('New channel', [
        {id: 'name', label: 'Name'},
        {id: 'topic', label: 'Topic (optional)'},
        {id: 'cat', label: 'Category', type: 'select', options: [{v: '', t: '(none)'}, ...sd.categories.map(k => ({v: k.id, t: k.name}))]}
      ], 'Create', v => {
        if (!v.name.trim()) return false;
        send({type: 'create_channel', server_id: srv, name: v.name.trim(), topic: v.topic, category_id: v.cat ? +v.cat : null});
      });
      break;
    case 'chmenu': {
      const c = sd.channels.find(x => x.id === id);
      modal('#' + c.name, [
        {id: 'name', label: 'Rename', value: c.name},
        {id: 'topic', label: 'Topic', value: c.topic || ''},
        {id: 'bg', label: 'Channel Wallpaper (optional)', type: 'file'}
      ], 'Save', async v => {
        const o = {type: 'update_channel', channel_id: id, name: v.name.trim() || c.name, topic: v.topic};
        if (v.bg) o.background_url = await toData(v.bg, 1920, .82);
        send(o);
      }, `<button id="m-reset">Reset channel wallpaper</button><button id="m-del" style="background:var(--red);color:#fff">Delete channel</button>`);
      $('m-reset').onclick = () => { send({type: 'update_channel', channel_id: id, background_url: 'reset'}); $('overlay').click(); };
      $('m-del').onclick = () => { if (confirm('Delete #' + c.name + ' and its messages?')) { send({type: 'delete_channel', channel_id: id}); $('overlay').click(); } };
      break;
    }
    case 'leave':
      if (confirm('Leave this room?')) send({type: 'leave_server', server_id: srv});
      break;
    case 'profile':
      modal('Profile', [
        {id: 'status', label: 'Status', value: me.custom_status || ''},
        {id: 'bio', label: 'Bio', type: 'textarea', value: me.bio || ''},
        {id: 'color', label: 'Avatar color', type: 'color', value: colorOk(me.avatar_color).slice(0, 7)},
        {id: 'file', label: 'Avatar photo', type: 'file'}
      ], 'Save', async v => {
        const o = {type: 'update_profile', bio: v.bio, avatar_color: v.color, custom_status: v.status};
        if (v.file) o.avatar_url = await toData(v.file, 256, .85);
        send(o);
      });
      break;
    case 'srvset': {
      const sv = sd.server;
      const isPriv = sv.is_public === 0 || sv.is_public === false;
      modal('Room Settings', [
        {id: 'name', label: 'Room Name', value: sv.name},
        {id: 'desc', label: 'Description', value: sv.description || ''},
        {id: 'privacy', label: 'Privacy', type: 'select', options: [
          {v: 'private', t: '🔒 Hidden Room (Invite-only)'},
          {v: 'public', t: '🌐 Public Community'}
        ], value: isPriv ? 'private' : 'public'},
        {id: 'icon', label: 'Icon', type: 'file'}
      ], 'Save', async v => {
        const o = {
          type: 'update_server',
          server_id: srv,
          name: v.name.trim() || sv.name,
          description: v.desc,
          is_public: v.privacy === 'public'
        };
        if (v.icon) o.icon_url = await toData(v.icon, 128, .85);
        send(o);
      }, sd.my_role === 'owner' ? '<button id="m-delsrv" style="background:var(--red);color:#fff">Delete Room</button>' : '');
      const b = $('m-delsrv');
      if (b) b.onclick = () => { if (confirm('Permanently delete this room and all its messages?')) { send({type: 'delete_server', server_id: srv}); $('overlay').click(); } };
      break;
    }
    case 'mmenu': {
      const u = sd.members.find(x => x.id === id);
      if (u) showMemberProfile(u);
      break;
    }
    case 'settings':
      modal('Account', [
        {id: 'old', label: 'Current password', type: 'password'},
        {id: 'neu', label: 'New password (4+ chars)', type: 'password'}
      ], 'Change password', v => {
        if (v.neu.length < 4) { toast('Password too short'); return false; }
        npw = v.neu;
        send({type: 'change_password', old_password: v.old, new_password: v.neu});
      }, `<label style="font-size:12px;color:var(--mut);font-weight:600">Theme</label><div class="sw">${THEMES.map(b => `<i data-a="theme" data-bg="${esc(b)}" style="background:${esc(b)}"></i>`).join('')}</div><label style="display:flex;gap:8px;align-items:center;margin-top:6px"><input type="checkbox" data-a="ping" ${localStorage.getItem('lan_ping') === '0' ? '' : 'checked'}> Sound notifications</label><button id="m-delacc" style="background:var(--red);color:#fff;margin-top:4px">Delete my account</button>`);
      $('m-delacc').onclick = () => {
        const p = prompt('Enter your password to permanently delete your account (rooms you own are deleted too):');
        if (p) send({type: 'delete_account', password: p});
      };
      break;
    case 'theme':
      localStorage.setItem('lan_bg', t.dataset.bg);
      applyTheme();
      break;
    case 'ping':
      localStorage.setItem('lan_ping', t.checked ? '1' : '0');
      break;
    case 'opennav':
      document.body.classList.add('nav');
      break;
    case 'logout':
      localStorage.removeItem('lan_creds');
      location.reload();
      break;
    case 'reply':
      replyTo = msgs.find(x => x.id === id);
      renderReply();
      $('msg').focus();
      break;
    case 'react': case 'rx': {
      const m = msgs.find(x => x.id === id), em = t.dataset.e;
      const has = (m.reactions || []).some(r => r.emoji === em && r.user_id === me.id);
      const dm = cur.kind === 'dm';
      send({type: (dm ? 'dm_' : '') + (has ? 'remove_reaction' : 'add_reaction'), message_id: id, dm_id: dm ? cur.id : undefined, emoji: em});
      break;
    }
    case 'morereact': {
      reactMsgId = id;
      const picker = $('emoji-picker');
      picker.hidden = !picker.hidden;
      break;
    }
    case 'del':
      if (confirm('Delete this message?')) {
        send(cur.kind === 'dm' ? {type: 'dm_delete_message', dm_id: cur.id, message_id: id} : {type: 'delete_message', message_id: id});
      }
      break;
    case 'pic':
      $('viewer-img').src = t.src;
      $('viewer').hidden = false;
      break;
  }
});

$('msgs').addEventListener('scroll', () => { $('down').hidden = nearEnd(); });
$('down').onclick = () => { scrollEnd(true); $('down').hidden = true; };
$('viewer').onclick = () => { $('viewer').hidden = true; };
$('menu-btn').onclick = () => document.body.classList.toggle('nav');
$('bg-btn').onclick = openWallpaperModal;
$('members-btn').onclick = () => {
  const el = $('members');
  const isOpen = el.dataset.user === 'open';
  el.dataset.user = isOpen ? 'closed' : 'open';
  el.hidden = isOpen;
};
$('backdrop').onclick = () => {
  closeNav();
  $('members').hidden = true;
  $('members').dataset.user = 'closed';
};
$('reply-x').onclick = () => { replyTo = null; renderReply(); };

// ---------- sending ----------
function sendMsg(content, type = 'text') {
  if (!cur) return;
  if (cur.kind === 'ch') send({type: 'send_message', channel_id: cur.id, content, message_type: type, reply_to_id: replyTo ? replyTo.id : null});
  else send({type: 'send_dm_message', dm_id: cur.id, content, message_type: type, reply_to_id: replyTo ? replyTo.id : null});
  replyTo = null; renderReply();
  typingMsg(false);
}

const doSend = () => {
  const v = $('msg').value.trim();
  if (!v) return;
  sendMsg(v);
  $('msg').value = '';
};

$('send').onclick = doSend;
$('msg').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); } });
$('msg').addEventListener('input', () => {
  if (!cur) return;
  const now = Date.now();
  if (now - lastTyping > 2000) { lastTyping = now; typingMsg(true); }
  clearTimeout(typingTimer);
  typingTimer = setTimeout(() => typingMsg(false), 3000);
});

$('img-btn').onclick = () => $('file').click();
$('file').onchange = async e => {
  const f = e.target.files[0];
  e.target.value = '';
  if (!f) return;
  try {
    sendMsg(await toData(f, 1280, .8), 'image');
  } catch (x) {
    toast('Could not read image');
  }
};

window.addEventListener('paste', async e => {
  const f = [...(e.clipboardData?.files || [])].find(x => x.type.startsWith('image/'));
  if (f && cur) {
    try {
      sendMsg(await toData(f, 1280, .8), 'image');
    } catch (x) {}
  }
});

// ---------- auth UI ----------
function setMode(m) {
  mode = m;
  $('tab-login').classList.toggle('active', m === 'login');
  $('tab-register').classList.toggle('active', m === 'register');
  $('a-invite').style.display = m === 'register' ? '' : 'none';
  $('a-submit').textContent = m === 'login' ? 'Login' : 'Register';
  $('auth-error').textContent = '';
}

$('tab-login').onclick = () => setMode('login');
$('tab-register').onclick = () => setMode('register');

function submitAuth() {
  const c = {username: $('a-user').value.trim(), password: $('a-pass').value};
  if (mode === 'register') c.invite = $('a-invite').value.trim();
  if (!c.username || !c.password) {
    $('auth-error').textContent = 'Enter username and password';
    return;
  }
  login(mode, c);
}

$('a-submit').onclick = submitAuth;
['a-user', 'a-pass', 'a-invite'].forEach(i => $(i).addEventListener('keydown', e => { if (e.key === 'Enter') submitAuth(); }));

// ---------- emoji / drop / swipe ----------
const EMO = '😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😍 🥰 😘 😋 😎 🤩 🥳 😏 😒 😞 😔 😢 😭 😤 😡 🤯 😱 😨 🤗 🤔 🙄 😴 🤮 👍 👎 👏 🙌 🙏 💪 👀 🔥 ✨ 💯 ❤️ 🧡 💛 💚 💙 💜 🖤 💔 🎉 🎮 🎧 📷 🍕 🍔 ☕ 🚀 ⚡ 🌈 ⭐'.split(' ');
$('emoji-picker').innerHTML = EMO.map(e => `<button type="button">${e}</button>`).join('');
$('emoji-picker').onclick = e => {
  const b = e.target.closest('button');
  if (b) {
    const em = b.textContent;
    if (reactMsgId) {
      const dm = cur && cur.kind === 'dm';
      send({type: (dm ? 'dm_' : '') + 'add_reaction', message_id: reactMsgId, dm_id: dm ? cur.id : undefined, emoji: em});
      $('emoji-picker').hidden = true;
      reactMsgId = null;
    } else {
      const i = $('msg');
      i.value += em;
      if (wide()) i.focus();
    }
  }
};

$('emoji-btn').onclick = () => {
  reactMsgId = null;
  $('emoji-picker').hidden = !$('emoji-picker').hidden;
};

let dragN = 0;
addEventListener('dragenter', e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) { dragN++; $('drop').hidden = false; } });
addEventListener('dragleave', () => { if (--dragN <= 0) { dragN = 0; $('drop').hidden = true; } });
addEventListener('dragover', e => e.preventDefault());
addEventListener('drop', async e => {
  e.preventDefault(); dragN = 0; $('drop').hidden = true;
  const f = [...(e.dataTransfer?.files || [])].find(x => x.type.startsWith('image/'));
  if (f && cur) {
    try {
      sendMsg(await toData(f, 1280, .8), 'image');
    } catch (x) {
      toast('Could not read image');
    }
  }
});

let tx = null;
addEventListener('touchstart', e => { tx = e.touches[0]; }, {passive: true});
addEventListener('touchend', e => {
  if (!tx || wide()) return;
  const t = e.changedTouches[0], dx = t.clientX - tx.clientX, dy = Math.abs(t.clientY - tx.clientY);
  if (dy < 50 && dx > 70 && tx.clientX < 28) document.body.classList.add('nav');
  else if (dy < 50 && dx < -70 && document.body.classList.contains('nav')) closeNav();
  tx = null;
}, {passive: true});

window.addEventListener('hashchange', checkUrlInvite);

applyTheme();

// ---------- boot ----------
connect();
checkUrlInvite();
try {
  const c = JSON.parse(localStorage.getItem('lan_creds') || 'null');
  if (c) login('login', {username: c.username, password: c.password});
} catch (e) {}
})();
