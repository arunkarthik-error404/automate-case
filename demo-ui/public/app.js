/* ═══════════════════════════════════════════════════════════════
   Case Search Reports — App Logic
   ═══════════════════════════════════════════════════════════════ */

const API_BASE = '';

// ─── DOM References ─────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const btnPerson = $('#btnPerson');
const btnEntity = $('#btnEntity');
const btnAsset = $('#btnAsset');
const btnDebtor = $('#btnDebtor');
const nameSelect = $('#nameSelect');
const populateBtn = $('#populateBtn');
const emptyState = $('#emptyState');
const loadingState = $('#loadingState');
const resultsContainer = $('#resultsContainer');
const resultsHeader = $('#resultsHeader');
const categoryFilters = $('#categoryFilters');
const resultsGrid = $('#resultsGrid');
const selectionInfo = $('#selectionInfo');
const infoName = $('#infoName');
const infoType = $('#infoType');
const infoCount = $('#infoCount');
const nameSection = $('#nameSection');
const namePicker = $('#namePicker');
const pickerTitle = $('#pickerTitle');
const pickerDesc = $('#pickerDesc');
const nameCardGrid = $('#nameCardGrid');
const backBtn = $('#backBtn');
const backBtnLabel = $('#backBtnLabel');

// Modal
const pdfModal = $('#pdfModal');
const modalBackdrop = $('#modalBackdrop');
const modalClose = $('#modalClose');
const modalTitle = $('#modalTitle');
const modalIframe = $('#modalIframe');

// ─── State ──────────────────────────────────────────────────────
let currentType = 'person';
let currentData = null;
let selectedName = null;
// Cached name lists for the card pickers, keyed by type
const nameCache = { person: null, entity: null };

// Types that are browsed as clickable cards instead of a sidebar dropdown
const CARD_TYPES = {
  person: {
    title: 'Select a Person',
    desc: 'Click a person below to explore their litigation documents.',
    back: 'All Persons'
  },
  entity: {
    title: 'Select an Entity',
    desc: 'Click an entity below to explore its ROC, Litigation, and Debtor search documents.',
    back: 'All Entities'
  }
};
const isCardType = (type) => Object.prototype.hasOwnProperty.call(CARD_TYPES, type);

// ─── Initialize ─────────────────────────────────────────────────
async function init() {
  bindEvents();
  await loadStats();
  switchType('person');
}

// ─── Load header stats ──────────────────────────────────────────
async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/api/stats`);
    const data = await res.json();
    $('#statPersons').textContent = data.totalPersons;
    $('#statEntities').textContent = data.totalEntities;
    $('#statDocs').textContent = data.totalDocuments;
  } catch (e) {
    console.error('Failed to load stats:', e);
  }
}

// ─── Load names for a card picker ───────────────────────────────
async function loadNames(type) {
  if (nameCache[type]) return nameCache[type];
  try {
    const res = await fetch(`${API_BASE}/api/names?type=${type}`);
    const data = await res.json();
    nameCache[type] = data.names || [];
  } catch (e) {
    console.error('Failed to load names:', e);
    nameCache[type] = [];
  }
  return nameCache[type];
}

// ─── Bind events ────────────────────────────────────────────────
function bindEvents() {
  // Type toggle
  btnPerson.addEventListener('click', () => switchType('person'));
  btnEntity.addEventListener('click', () => switchType('entity'));
  btnAsset.addEventListener('click', () => switchType('asset'));
  btnDebtor.addEventListener('click', () => switchType('debtor'));

  // Name select
  nameSelect.addEventListener('change', () => {
    populateBtn.disabled = !nameSelect.value;
  });

  // Populate button
  populateBtn.addEventListener('click', handlePopulate);

  // Back to the card grid
  backBtn.addEventListener('click', () => showCardPicker(currentType));

  // Modal close
  modalClose.addEventListener('click', closeModal);
  modalBackdrop.addEventListener('click', closeModal);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
}

// ─── Switch type ────────────────────────────────────────────────
function switchType(type) {
  currentType = type;

  // Update toggle buttons
  btnPerson.classList.toggle('active', type === 'person');
  btnEntity.classList.toggle('active', type === 'entity');
  btnAsset.classList.toggle('active', type === 'asset');
  btnDebtor.classList.toggle('active', type === 'debtor');

  // Persons and entities are picked from cards in the main area,
  // not from the sidebar dropdown
  const usesCards = isCardType(type);
  nameSection.style.display = usesCards ? 'none' : '';
  populateBtn.style.display = usesCards ? 'none' : '';
  if (!usesCards) namePicker.style.display = 'none';

  if (usesCards) {
    selectedName = null;
    selectionInfo.style.display = 'none';
    showCardPicker(type);
  } else if (type === 'asset' || type === 'debtor') {
    nameSelect.innerHTML = type === 'asset'
      ? '<option value="global">— Global Asset Report —</option>'
      : '<option value="global">— Global Debtor Reports —</option>';
    nameSelect.disabled = true;
    populateBtn.disabled = false;
    handlePopulate();
  } else {
    nameSelect.disabled = false;
    populateBtn.disabled = true;
  }
}

// ─── Card picker (persons / entities) ───────────────────────────
async function showCardPicker(type) {
  const config = CARD_TYPES[type];
  if (!config) return;

  emptyState.style.display = 'none';
  resultsContainer.style.display = 'none';
  selectionInfo.style.display = 'none';
  namePicker.style.display = 'block';
  pickerTitle.textContent = config.title;
  pickerDesc.textContent = config.desc;

  if (!nameCache[type]) {
    nameCardGrid.innerHTML = '';
    loadingState.style.display = 'flex';
    await loadNames(type);
    loadingState.style.display = 'none';
    // Guard against a slow fetch resolving after the user switched tabs
    if (currentType !== type) return;
  }

  renderNameCards(type);
}

function renderNameCards(type) {
  nameCardGrid.innerHTML = '';

  (nameCache[type] || []).forEach((name, i) => {
    const card = document.createElement('button');
    card.className = `name-card ${type}`;
    card.style.animationDelay = `${Math.min(i * 0.05, 0.5)}s`;
    card.innerHTML = `
      <span class="name-card-avatar">${escHtml(nameInitials(name))}</span>
      <span class="name-card-title" title="${escAttr(name)}">${escHtml(name)}</span>
      <span class="name-card-cta">
        View documents
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="12" x2="19" y2="12"/>
          <polyline points="12 5 19 12 12 19"/>
        </svg>
      </span>
    `;
    card.addEventListener('click', () => selectCard(name));
    nameCardGrid.appendChild(card);
  });
}

function selectCard(name) {
  selectedName = name;
  namePicker.style.display = 'none';
  handlePopulate();
}

function nameInitials(name) {
  return name
    .replace(/[^A-Za-z0-9\s]/g, ' ')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('');
}

// ─── Handle Populate ────────────────────────────────────────────
async function handlePopulate() {
  const name = isCardType(currentType) ? selectedName : nameSelect.value;
  if (isCardType(currentType) && !name) return;

  // Show loading
  emptyState.style.display = 'none';
  namePicker.style.display = 'none';
  resultsContainer.style.display = 'none';
  loadingState.style.display = 'flex';

  try {
    let url = `${API_BASE}/api/search?type=${currentType}`;
    if (isCardType(currentType)) {
      url += `&name=${encodeURIComponent(name)}`;
    }
    const res = await fetch(url);
    const data = await res.json();
    currentData = data;

    // Small delay for effect
    await new Promise(r => setTimeout(r, 400));

    renderResults(data);
  } catch (e) {
    console.error('Failed to fetch data:', e);
    loadingState.style.display = 'none';
    if (isCardType(currentType)) namePicker.style.display = 'block';
    else emptyState.style.display = 'flex';
  }
}

// ─── Render results ─────────────────────────────────────────────
function renderResults(data) {
  loadingState.style.display = 'none';
  resultsContainer.style.display = 'block';

  // Header
  let badgeClass = 'badge-person';
  let badgeIcon = '👤';
  if (data.type === 'entity') { badgeClass = 'badge-entity'; badgeIcon = '🏢'; }
  else if (data.type === 'asset') { badgeClass = 'badge-asset'; badgeIcon = '🏡'; }
  else if (data.type === 'debtor') { badgeClass = 'badge-debtor'; badgeIcon = '📋'; }

  resultsHeader.innerHTML = `
    <h2 class="results-name">
      ${escHtml(data.name)}
      <span class="results-type-badge ${badgeClass}">${badgeIcon} ${data.type}</span>
    </h2>
  `;

  // Count total PDFs
  let totalPdfs = 0;
  const categories = Object.keys(data.categories);
  categories.forEach(cat => {
    Object.values(data.categories[cat]).forEach(pdfs => {
      totalPdfs += pdfs.length;
    });
  });

  // Update selection info
  selectionInfo.style.display = 'block';
  infoName.textContent = data.name;
  infoType.textContent = data.type.toUpperCase();
  infoCount.textContent = `${totalPdfs} documents found`;

  // Persons and entities use collapsible dropdown sections instead of filter chips
  const usesCards = isCardType(data.type);
  backBtn.style.display = usesCards ? 'inline-flex' : 'none';
  categoryFilters.style.display = usesCards ? 'none' : 'flex';

  if (usesCards) {
    backBtnLabel.textContent = CARD_TYPES[data.type].back;
    renderCategoryDropdowns(data.categories);
    return;
  }

  // Category filter chips
  categoryFilters.innerHTML = '';
  const allBtn = createFilterBtn('All', 'all', true);
  categoryFilters.appendChild(allBtn);
  categories.forEach(cat => {
    const btn = createFilterBtn(formatCategoryName(cat), cat, false);
    categoryFilters.appendChild(btn);
  });

  // Render category sections
  renderCategorySections(data.categories, 'all');
}

// ─── Render category dropdowns (persons / entities) ─────────────
// "All", "ROC Search" and "Litigation Search" become collapsible
// dropdowns; each holds its own collapsible sub-sections.
function renderCategoryDropdowns(categories) {
  resultsGrid.innerHTML = '';

  const allSubs = {};
  Object.entries(categories).forEach(([catKey, subCategories]) => {
    Object.entries(subCategories).forEach(([subName, pdfs]) => {
      allSubs[`${formatCategoryName(catKey)} — ${subName}`] = pdfs;
    });
  });

  const groups = [{ key: 'all', label: 'All', subs: allSubs }];
  Object.entries(categories).forEach(([catKey, subCategories]) => {
    groups.push({ key: catKey, label: formatCategoryName(catKey), subs: subCategories });
  });

  groups.forEach(group => resultsGrid.appendChild(createDropdownSection(group)));
}

function createDropdownSection({ key, label, subs }) {
  const subEntries = Object.entries(subs);
  const fileCount = subEntries.reduce((n, [, pdfs]) => n + pdfs.length, 0);

  const section = document.createElement('div');
  section.className = 'dropdown-section';

  const header = document.createElement('button');
  header.className = 'dropdown-header collapsed';
  header.innerHTML = `
    <span class="category-dot ${key}"></span>
    <span class="dropdown-title">${escHtml(label)}</span>
    <span class="category-count">${subEntries.length} sections · ${fileCount} files</span>
    <span class="dropdown-chevron">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
    </span>
  `;

  const body = document.createElement('div');
  body.className = 'dropdown-body collapsed';

  header.addEventListener('click', () => {
    header.classList.toggle('collapsed');
    body.classList.toggle('collapsed');
  });

  if (!subEntries.length) {
    body.innerHTML = '<p class="dropdown-empty">No documents available.</p>';
  }

  subEntries.forEach(([subName, pdfs]) => {
    body.appendChild(createSubDropdown(subName, pdfs));
  });

  section.appendChild(header);
  section.appendChild(body);
  return section;
}

function createSubDropdown(subName, pdfs) {
  const wrap = document.createElement('div');
  wrap.className = 'sub-dropdown';

  const header = document.createElement('button');
  header.className = 'sub-dropdown-header collapsed';
  header.innerHTML = `
    <span class="sub-dropdown-chevron">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6 9 12 15 18 9"/>
      </svg>
    </span>
    <span class="sub-dropdown-title">${escHtml(subName)}</span>
    <span class="sub-category-count">${pdfs.length} files</span>
  `;

  const body = document.createElement('div');
  body.className = 'sub-dropdown-body collapsed';

  let loaded = false;
  header.addEventListener('click', () => {
    // Build the PDF previews only the first time this section is opened
    if (!loaded) {
      const grid = document.createElement('div');
      grid.className = 'pdf-grid';
      pdfs.forEach(pdf => grid.appendChild(createPdfCard(pdf)));
      body.appendChild(grid);
      loaded = true;
    }
    header.classList.toggle('collapsed');
    body.classList.toggle('collapsed');
  });

  wrap.appendChild(header);
  wrap.appendChild(body);
  return wrap;
}

// ─── Create filter button ───────────────────────────────────────
function createFilterBtn(label, value, active) {
  const btn = document.createElement('button');
  btn.className = `cat-filter-btn${active ? ' active' : ''}`;
  btn.textContent = label;
  btn.dataset.category = value;
  btn.addEventListener('click', () => {
    $$('.cat-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderCategorySections(currentData.categories, value);
  });
  return btn;
}

// ─── Render category sections ───────────────────────────────────
function renderCategorySections(categories, filter) {
  resultsGrid.innerHTML = '';

  Object.entries(categories).forEach(([catKey, subCategories]) => {
    if (filter !== 'all' && filter !== catKey) return;

    const catColor = getCategoryColor(catKey);
    let catPdfCount = 0;
    Object.values(subCategories).forEach(pdfs => catPdfCount += pdfs.length);

    const section = document.createElement('div');
    section.className = 'category-section';
    
    // Category header
    const header = document.createElement('div');
    header.className = 'category-header';
    header.innerHTML = `
      <span class="category-dot ${catKey}"></span>
      <span class="category-title">${formatCategoryName(catKey)}</span>
      <span class="category-count">${catPdfCount} files</span>
      <span class="category-chevron">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </span>
    `;

    // Category body
    const body = document.createElement('div');
    body.className = 'category-body';

    // Toggle collapse
    header.addEventListener('click', () => {
      header.classList.toggle('collapsed');
      body.classList.toggle('collapsed');
    });

    // Sub-categories
    Object.entries(subCategories).forEach(([subName, pdfs]) => {
      const subDiv = document.createElement('div');
      subDiv.className = 'sub-category';

      subDiv.innerHTML = `
        <div class="sub-category-title">
          ${escHtml(subName)}
          <span class="sub-category-count">${pdfs.length} files</span>
        </div>
      `;

      // PDF grid
      const grid = document.createElement('div');
      grid.className = 'pdf-grid';

      pdfs.forEach(pdf => {
        const card = createPdfCard(pdf);
        grid.appendChild(card);
      });

      subDiv.appendChild(grid);
      body.appendChild(subDiv);
    });

    section.appendChild(header);
    section.appendChild(body);
    resultsGrid.appendChild(section);
  });
}

// ─── Create PDF card ────────────────────────────────────────────
function createPdfCard(pdf) {
  const card = document.createElement('div');
  card.className = 'pdf-card';

  const sizeStr = formatFileSize(pdf.size);
  const displayName = pdf.name.replace(/\.pdf$/i, '');

  card.innerHTML = `
    <iframe class="pdf-preview" src="${pdf.url}#toolbar=0&navpanes=0&scrollbar=0&view=FitH" title="${escAttr(pdf.name)}"></iframe>
    <div class="pdf-card-info">
      <div class="pdf-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
      </div>
      <span class="pdf-name" title="${escAttr(pdf.name)}">${escHtml(displayName)}</span>
      <span class="pdf-size">${sizeStr}</span>
      <span class="pdf-expand-icon">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="15 3 21 3 21 9"/>
          <polyline points="9 21 3 21 3 15"/>
          <line x1="21" y1="3" x2="14" y2="10"/>
          <line x1="3" y1="21" x2="10" y2="14"/>
        </svg>
      </span>
    </div>
  `;

  card.addEventListener('click', () => openModal(pdf));
  return card;
}

// ─── Modal ──────────────────────────────────────────────────────
function openModal(pdf) {
  modalTitle.textContent = pdf.name;
  modalIframe.src = pdf.url;
  pdfModal.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  pdfModal.classList.remove('open');
  modalIframe.src = '';
  document.body.style.overflow = '';
}

// ─── Helpers ────────────────────────────────────────────────────
function formatCategoryName(key) {
  const names = {
    roc: 'ROC Search',
    litigation: 'Litigation Search',
    asset: 'Asset Details',
    debtor: 'Debtor Search',
    cersai: 'CERSAI / Debtor Search'
  };
  return names[key] || key.charAt(0).toUpperCase() + key.slice(1);
}

function getCategoryColor(key) {
  const colors = {
    roc: 'var(--cat-roc)',
    litigation: 'var(--cat-litigation)',
    asset: 'var(--cat-asset)',
    debtor: 'var(--cat-debtor)',
    cersai: 'var(--cat-cersai)'
  };
  return colors[key] || 'var(--accent-blue)';
}

function formatFileSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(0) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escAttr(str) {
  return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ─── AI Chatbot UI Handler ──────────────────────────────────────
// Messaging only — opening and closing the docked panel is owned by initAiDock()
function initAiChatbot() {
  const inputForm = document.getElementById('chatInputForm');
  const chatInput = document.getElementById('chatInput');
  const messagesContainer = document.getElementById('chatMessages');
  const sendBtn = document.getElementById('chatSendBtn');
  const resetBtn = document.getElementById('chatResetBtn');
  const chipBtns = document.querySelectorAll('.chip-btn');

  if (!inputForm || !messagesContainer) return;

  chipBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const prompt = btn.getAttribute('data-prompt');
      if (prompt) {
        chatInput.value = prompt;
        sendChatMessage(prompt);
      }
    });
  });

  if (resetBtn) resetBtn.addEventListener('click', resetConversation);

  inputForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const prompt = chatInput.value.trim();
    if (prompt) {
      sendChatMessage(prompt);
    }
  });

  // Identifies this tab so the server keeps its conversation history separate.
  function getChatSessionId() {
    let id = sessionStorage.getItem('chatSessionId');
    if (!id) {
      id = 'chat-' + Math.random().toString(36).slice(2) + '-' + Date.now().toString(36);
      sessionStorage.setItem('chatSessionId', id);
    }
    return id;
  }

  let sending = false;

  function setSending(state) {
    sending = state;
    if (sendBtn) sendBtn.disabled = state;
    if (chatInput) chatInput.disabled = state;
  }

  async function sendChatMessage(promptText) {
    if (sending) return;
    appendMessage(promptText, 'user');
    chatInput.value = '';
    setSending(true);

    const loadingId = appendMessage('', 'bot', true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText, sessionId: getChatSessionId() })
      });
      const data = await res.json();
      removeMessage(loadingId);

      if (data.answer) {
        appendMessage(data.answer, 'bot');
      } else {
        const msg = data.details ? `${data.error}\nDetails: ${data.details}` : (data.error || 'Unable to retrieve answer.');
        appendMessage(msg, 'bot');
      }
    } catch (err) {
      removeMessage(loadingId);
      appendMessage('Error communicating with AI server: ' + err.message, 'bot');
    } finally {
      setSending(false);
      chatInput.focus();
    }
  }

  // Clears this tab's server-side history and returns to the starter prompts
  async function resetConversation() {
    try {
      await fetch('/api/chat/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId: getChatSessionId() })
      });
    } catch (err) {
      console.error('Could not reset the conversation:', err);
    }
    messagesContainer.querySelectorAll('.chat-msg').forEach(el => el.remove());
    messagesContainer.classList.remove('has-messages');
    chatInput.focus();
  }

  async function openPdfByName(filename) {
    try {
      const res = await fetch(`/api/pdf-url?filename=${encodeURIComponent(filename)}`);
      const data = await res.json();
      if (data.url) {
        openModal({ name: data.filename || filename, url: data.url });
      } else {
        alert(`PDF file "${filename}" could not be located on server.`);
      }
    } catch (err) {
      console.error('Error opening PDF:', err);
    }
  }

  messagesContainer.addEventListener('click', (e) => {
    const btn = e.target.closest('.pdf-open-btn');
    if (btn) {
      const filename = btn.getAttribute('data-filename');
      if (filename) {
        openPdfByName(filename);
      }
    }
  });

  function formatChatMarkdown(text) {
    if (!text) return '';

    // Escape HTML first
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Convert Headers (### Header or ## Header)
    html = html.replace(/^### (.*$)/gim, '<h4 class="chat-section-header">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 class="chat-section-header">$1</h3>');
    html = html.replace(/^# (.*$)/gim, '<h2 class="chat-section-header">$1</h2>');

    // Convert bold text **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Convert Source File tags into interactive clickable buttons
    html = html.replace(/(?:📄\s*)?(?:<strong>Source File(?:s)?:<\/strong>|Source File(?:s)?:)\s*`?([a-zA-Z0-9_\-\.\s\(\)]+\.pdf)`?/gi, 
      '<button type="button" class="source-file-badge pdf-open-btn" data-filename="$1" title="Click to view PDF in modal">📄 $1 <span class="view-hint">🔍 View PDF</span></button>');
    html = html.replace(/`([a-zA-Z0-9_\-\.\s\(\)]+\.pdf)`/gi, 
      '<button type="button" class="source-file-badge pdf-open-btn" data-filename="$1" title="Click to view PDF in modal">📄 $1 <span class="view-hint">🔍 View PDF</span></button>');

    // Inline code `code`
    html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

    // Convert lists and line breaks
    const lines = html.split('\n');
    let inList = false;
    let resultLines = [];

    for (let line of lines) {
      let trimmed = line.trim();
      if (/^[\*\-]\s+/.test(trimmed)) {
        if (!inList) {
          inList = true;
          resultLines.push('<ul class="chat-list">');
        }
        let content = trimmed.replace(/^[\*\-]\s+/, '');
        resultLines.push(`<li>${content}</li>`);
      } else if (/^\d+\.\s+/.test(trimmed)) {
        if (!inList) {
          inList = true;
          resultLines.push('<ol class="chat-list">');
        }
        let content = trimmed.replace(/^\d+\.\s+/, '');
        resultLines.push(`<li>${content}</li>`);
      } else {
        if (inList) {
          inList = false;
          resultLines.push('</ul>');
        }
        if (trimmed.length > 0) {
          resultLines.push(`<p class="chat-para">${trimmed}</p>`);
        }
      }
    }
    if (inList) {
      resultLines.push('</ul>');
    }

    return resultLines.join('');
  }

  function appendMessage(text, sender, isLoading = false) {
    const msgId = 'msg-' + Date.now() + '-' + Math.random().toString(36).substr(2, 4);
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-msg ${sender}-msg`;
    msgDiv.id = msgId;

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    
    if (isLoading) {
      bubble.innerHTML = '<span class="typing-indicator" role="status" aria-label="Assistant is thinking"><span></span><span></span><span></span></span>';
    } else if (sender === 'bot') {
      bubble.innerHTML = formatChatMarkdown(text);
    } else {
      bubble.textContent = text;
    }

    msgDiv.appendChild(bubble);
    messagesContainer.appendChild(msgDiv);
    // Swaps the starter prompts out for the conversation
    messagesContainer.classList.add('has-messages');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msgId;
  }

  function removeMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }
}

// ─── Assistant dock: open / close / focus ───────────────────────
function initAiDock() {
  const dock = $('#aiDock');
  const scrim = $('#dockScrim');
  const trigger = $('#assistantTrigger');
  const closeBtn = $('#dockCloseBtn');
  const chatInput = $('#chatInput');
  if (!dock || !trigger) return;

  const isOpen = () => document.body.classList.contains('dock-open');

  function openDock() {
    document.body.classList.add('dock-open');
    dock.setAttribute('aria-hidden', 'false');
    trigger.setAttribute('aria-expanded', 'true');
    sessionStorage.setItem('assistantDockOpen', '1');
    if (chatInput) chatInput.focus();
  }

  function closeDock() {
    document.body.classList.remove('dock-open');
    dock.setAttribute('aria-hidden', 'true');
    trigger.setAttribute('aria-expanded', 'false');
    sessionStorage.setItem('assistantDockOpen', '0');
    trigger.focus();
  }

  trigger.addEventListener('click', () => (isOpen() ? closeDock() : openDock()));
  if (closeBtn) closeBtn.addEventListener('click', closeDock);
  if (scrim) scrim.addEventListener('click', closeDock);

  // Escape closes the panel, but never while the PDF modal is on top of it
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !isOpen()) return;
    const modal = $('#pdfModal');
    if (modal && modal.classList.contains('open')) return;
    closeDock();
  });

  if (sessionStorage.getItem('assistantDockOpen') === '1') openDock();
}

// ─── Boot ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  init();
  initAiChatbot();
  initAiDock();
});

