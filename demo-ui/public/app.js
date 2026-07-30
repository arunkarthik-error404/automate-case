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

// Modal
const pdfModal = $('#pdfModal');
const modalBackdrop = $('#modalBackdrop');
const modalClose = $('#modalClose');
const modalTitle = $('#modalTitle');
const modalIframe = $('#modalIframe');

// ─── State ──────────────────────────────────────────────────────
let currentType = 'person';
let currentData = null;

// ─── Initialize ─────────────────────────────────────────────────
async function init() {
  await loadStats();
  await loadNames('person');
  bindEvents();
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

// ─── Load names dropdown ────────────────────────────────────────
async function loadNames(type) {
  try {
    const res = await fetch(`${API_BASE}/api/names?type=${type}`);
    const data = await res.json();
    
    nameSelect.innerHTML = '<option value="">— Choose a name —</option>';
    data.names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      nameSelect.appendChild(opt);
    });
  } catch (e) {
    console.error('Failed to load names:', e);
  }
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

  if (type === 'asset' || type === 'debtor') {
    nameSelect.innerHTML = type === 'asset'
      ? '<option value="global">— Global Asset Report —</option>'
      : '<option value="global">— Global Debtor Reports —</option>';
    nameSelect.disabled = true;
    populateBtn.disabled = false;
    handlePopulate();
  } else {
    nameSelect.disabled = false;
    populateBtn.disabled = true;
    loadNames(type);
  }
}

// ─── Handle Populate ────────────────────────────────────────────
async function handlePopulate() {
  if (currentType === 'person' || currentType === 'entity') {
    const name = nameSelect.value;
    if (!name) return;
  }

  // Show loading
  emptyState.style.display = 'none';
  resultsContainer.style.display = 'none';
  loadingState.style.display = 'flex';

  try {
    let url = `${API_BASE}/api/search?type=${currentType}`;
    if (currentType === 'person' || currentType === 'entity') {
      url += `&name=${encodeURIComponent(nameSelect.value)}`;
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
    emptyState.style.display = 'flex';
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
    debtor: 'Debtor Search Details',
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
function initAiChatbot() {
  const toggleBtn = document.getElementById('aiChatToggle');
  const chatWindow = document.getElementById('aiChatWindow');
  const closeBtn = document.getElementById('chatCloseBtn');
  const inputForm = document.getElementById('chatInputForm');
  const chatInput = document.getElementById('chatInput');
  const messagesContainer = document.getElementById('chatMessages');
  const chipBtns = document.querySelectorAll('.chip-btn');

  if (!toggleBtn || !chatWindow) return;

  toggleBtn.addEventListener('click', () => {
    const isVisible = chatWindow.style.display !== 'none';
    chatWindow.style.display = isVisible ? 'none' : 'flex';
    if (!isVisible) chatInput.focus();
  });

  closeBtn.addEventListener('click', () => {
    chatWindow.style.display = 'none';
  });

  chipBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const prompt = btn.getAttribute('data-prompt');
      if (prompt) {
        chatInput.value = prompt;
        sendChatMessage(prompt);
      }
    });
  });

  inputForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const prompt = chatInput.value.trim();
    if (prompt) {
      sendChatMessage(prompt);
    }
  });

  async function sendChatMessage(promptText) {
    appendMessage(promptText, 'user');
    chatInput.value = '';

    const loadingId = appendMessage('Searching...', 'bot', true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText })
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
    }
  }

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

    // Convert Source File tags (📄 **Source File:** `file.pdf` or `file.pdf`)
    html = html.replace(/(?:📄\s*)?(?:<strong>Source File(?:s)?:<\/strong>|Source File(?:s)?:)\s*`?([a-zA-Z0-9_\-\.\s\(\)]+\.pdf)`?/gi, 
      '<span class="source-file-badge">📄 $1</span>');
    html = html.replace(/`([a-zA-Z0-9_\-\.\s\(\)]+\.pdf)`/gi, 
      '<span class="source-file-badge">📄 $1</span>');

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
      bubble.innerHTML = '<span class="loading-pulse"><span class="loading-dots">Searching</span><span class="dot-anim">...</span></span>';
      bubble.style.opacity = '0.85';
    } else if (sender === 'bot') {
      bubble.innerHTML = formatChatMarkdown(text);
    } else {
      bubble.textContent = text;
    }

    msgDiv.appendChild(bubble);
    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msgId;
  }

  function removeMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }
}

// ─── Boot ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  init();
  initAiChatbot();
});

