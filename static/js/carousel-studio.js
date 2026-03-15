/**
 * Carousel Studio — Complete frontend module for AI Instagram carousel generation.
 *
 * Flow: Prompt → (optional assets) → Generate → Preview → Customize → Export
 *
 * Integrates with backend endpoints:
 *   POST /api/generate-carousel  — full pipeline generation
 *   GET  /api/carousel-templates — list templates + variants
 *   GET  /api/carousel-themes    — list themes
 *   POST /api/user-assets        — upload user asset
 *   GET  /api/user-assets        — list user assets
 *   DELETE /api/user-assets/:id  — delete user asset
 */

// =========================================================================
// State
// =========================================================================
window.CarouselStudio = window.CarouselStudio || {};

const CS = window.CarouselStudio;

CS.state = {
  // Step tracking
  currentStep: 'prompt', // prompt | generating | preview

  // Prompt
  prompt: '',
  autoPlan: true,

  // Template / theme selection (manual mode)
  templates: [],        // from GET /api/carousel-templates
  themes: [],           // from GET /api/carousel-themes
  selectedTemplate: 'minimal_layout',
  selectedVariant: null,
  selectedTheme: null,

  // User assets
  userAssets: [],        // from GET /api/user-assets
  selectedAssets: {},    // {slot_name: asset_id}

  // Asset placement
  placementOverrides: {},  // {slot_name: {anchor, box, slides}}
  assetCommands: [],       // natural-language commands

  // Generation result
  result: null,          // full response from /api/generate-carousel
  slideUrls: [],
  currentSlide: 0,

  // Overrides
  overrides: {},
};


// =========================================================================
// Initialization
// =========================================================================

CS.init = async function() {
  const container = document.getElementById('cstudio-root');
  if (!container) return;

  // Load templates and themes in parallel
  const [tplResp, themeResp] = await Promise.all([
    fetch('/api/carousel-templates').then(r => r.json()).catch(() => ({ templates: [] })),
    fetch('/api/carousel-themes').then(r => r.json()).catch(() => ({ themes: [] })),
  ]);

  CS.state.templates = tplResp.templates || [];
  CS.state.themes = themeResp.themes || [];

  if (CS.state.templates.length > 0) {
    CS.state.selectedTemplate = CS.state.templates[0].template;
    const tpl = CS.state.templates[0];
    CS.state.selectedVariant = tpl.variants && tpl.variants.length ? tpl.variants[0] : null;
  }

  CS.renderPromptStep();
  CS.loadUserAssets();
};


// =========================================================================
// Step: Prompt Input
// =========================================================================

CS.renderPromptStep = function() {
  CS.state.currentStep = 'prompt';
  const body = document.getElementById('cstudio-body');
  if (!body) return;

  // Build template options
  const tplOpts = CS.state.templates.map(t =>
    `<option value="${t.template}" ${t.template === CS.state.selectedTemplate ? 'selected' : ''}>${t.name || t.template}</option>`
  ).join('');

  // Build variant options for selected template
  const selTpl = CS.state.templates.find(t => t.template === CS.state.selectedTemplate);
  const varOpts = (selTpl?.variants || []).map(v =>
    `<option value="${v}" ${v === CS.state.selectedVariant ? 'selected' : ''}>${v}</option>`
  ).join('');

  // Build theme options
  const themeOpts = CS.state.themes.map(t =>
    `<option value="${t.id}" ${t.id === CS.state.selectedTheme ? 'selected' : ''}>${t.name || t.id}</option>`
  ).join('');

  body.className = 'cstudio-body';
  body.innerHTML = `
    <div class="cstudio-prompt-box">
      <h2>Crea un carosello Instagram</h2>
      <p>Descrivi il tuo post e l'AI genererà il design, il contenuto e le immagini.</p>

      <textarea id="cs-prompt" class="cstudio-prompt-input" rows="3"
        placeholder="Es: 5 strategie per aumentare le vendite online del tuo e-commerce"
        oninput="CarouselStudio.state.prompt = this.value">${_esc(CS.state.prompt)}</textarea>

      <div class="cstudio-toggle-row">
        <label class="cstudio-toggle">
          <input type="checkbox" id="cs-autoplan" ${CS.state.autoPlan ? 'checked' : ''}
            onchange="CarouselStudio.state.autoPlan = this.checked; CarouselStudio.toggleManualControls()">
          AI Design Planner (scelta automatica template/tema)
        </label>
      </div>

      <div id="cs-manual-controls" class="cstudio-select-row" style="margin-top:14px; ${CS.state.autoPlan ? 'display:none' : ''}">
        <div class="cstudio-select-group">
          <label>Template</label>
          <select class="cstudio-select" id="cs-template" onchange="CarouselStudio.onTemplateChange(this.value)">
            ${tplOpts}
          </select>
        </div>
        <div class="cstudio-select-group">
          <label>Variante</label>
          <select class="cstudio-select" id="cs-variant" onchange="CarouselStudio.state.selectedVariant = this.value">
            ${varOpts}
          </select>
        </div>
        <div class="cstudio-select-group">
          <label>Tema</label>
          <select class="cstudio-select" id="cs-theme" onchange="CarouselStudio.state.selectedTheme = this.value">
            <option value="">Auto</option>
            ${themeOpts}
          </select>
        </div>
      </div>

      <!-- User assets strip -->
      <div class="cstudio-assets-strip" id="cs-assets-strip">
        <h4>I tuoi asset <span style="font-weight:400;color:var(--text3)">(opzionale)</span></h4>
        <div class="cstudio-assets-row" id="cs-assets-row">
          <div class="cstudio-asset-upload" onclick="CarouselStudio.triggerUpload()">
            <span class="icon">+</span>
            <span>Carica</span>
          </div>
        </div>
        <input type="file" id="cs-file-upload" accept="image/*" style="display:none"
          onchange="CarouselStudio.handleUpload(this)">
      </div>

      <!-- Asset commands -->
      <div id="cs-cmd-section" style="margin-top:12px; ${CS.state.userAssets.length === 0 ? 'display:none' : ''}">
        <input id="cs-cmd-input" class="cstudio-cmd-input"
          placeholder="Es: metti il logo in alto a sinistra, usa il prodotto al centro..."
          onkeydown="if(event.key==='Enter'){event.preventDefault();CarouselStudio.addCommand(this.value);this.value='';}">
        <div class="cstudio-cmd-tags" id="cs-cmd-tags"></div>
      </div>

      <div class="cstudio-prompt-row" style="margin-top:20px;">
        <button class="btn btn-primary" style="padding:12px 32px;font-size:15px;"
          onclick="CarouselStudio.generate()">
          Genera carosello
        </button>
      </div>
    </div>
  `;

  CS.renderAssetsRow();
  CS.renderCommandTags();
  CS.updateStepBar();
};


CS.toggleManualControls = function() {
  const el = document.getElementById('cs-manual-controls');
  if (el) el.style.display = CS.state.autoPlan ? 'none' : 'flex';
};


CS.onTemplateChange = function(templateId) {
  CS.state.selectedTemplate = templateId;
  const tpl = CS.state.templates.find(t => t.template === templateId);
  CS.state.selectedVariant = tpl?.variants?.[0] || null;

  const varSelect = document.getElementById('cs-variant');
  if (varSelect && tpl) {
    varSelect.innerHTML = (tpl.variants || []).map(v =>
      `<option value="${v}">${v}</option>`
    ).join('');
  }
};


// =========================================================================
// User Assets
// =========================================================================

CS.loadUserAssets = async function() {
  try {
    const resp = await fetch('/api/user-assets').then(r => r.json());
    CS.state.userAssets = resp.assets || [];
    CS.renderAssetsRow();
    const cmdSection = document.getElementById('cs-cmd-section');
    if (cmdSection) cmdSection.style.display = CS.state.userAssets.length > 0 ? '' : 'none';
  } catch(e) { console.error('Failed to load user assets', e); }
};


CS.renderAssetsRow = function() {
  const row = document.getElementById('cs-assets-row');
  if (!row) return;

  let html = '';

  // Existing user assets
  CS.state.userAssets.forEach(a => {
    const isSelected = Object.values(CS.state.selectedAssets).includes(a.id);
    html += `
      <div class="cstudio-asset-thumb ${isSelected ? 'selected' : ''}"
           onclick="CarouselStudio.toggleAssetSelection('${a.id}', '${a.type}')"
           title="${_esc(a.filename || a.type)}">
        <img src="${a.url}" alt="${_esc(a.type)}">
        <span class="badge">${a.type}</span>
      </div>`;
  });

  // Upload button
  html += `
    <div class="cstudio-asset-upload" onclick="CarouselStudio.triggerUpload()">
      <span class="icon">+</span>
      <span>Carica</span>
    </div>`;

  row.innerHTML = html;
};


CS.triggerUpload = function() {
  document.getElementById('cs-file-upload')?.click();
};


CS.handleUpload = async function(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];

  // Ask for asset type
  const typeMap = { logo: 'Logo', product: 'Prodotto', photo: 'Foto', texture: 'Texture' };
  const type = await CS.pickAssetType();
  if (!type) return;

  const fd = new FormData();
  fd.append('file', file);
  fd.append('type', type);

  try {
    const resp = await fetch('/api/user-assets', { method: 'POST', body: fd }).then(r => r.json());
    if (resp.error) throw new Error(resp.error);
    CS.state.userAssets.unshift(resp);

    // Auto-select the uploaded asset
    const slotName = { logo: 'logo_asset', product: 'product_asset', photo: 'secondary_asset', texture: 'background_asset' }[type] || 'secondary_asset';
    CS.state.selectedAssets[slotName] = resp.id;

    CS.renderAssetsRow();
    const cmdSection = document.getElementById('cs-cmd-section');
    if (cmdSection) cmdSection.style.display = '';
    if (window.toast) toast('Asset caricato!');
  } catch(e) {
    console.error('Upload failed', e);
    if (window.toast) toast('Errore upload: ' + e.message);
  }

  input.value = '';
};


CS.pickAssetType = function() {
  return new Promise(resolve => {
    const types = [
      { value: 'logo', label: 'Logo' },
      { value: 'product', label: 'Prodotto' },
      { value: 'photo', label: 'Foto' },
      { value: 'texture', label: 'Texture' },
    ];

    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;';
    modal.innerHTML = `
      <div style="background:var(--bg);border-radius:16px;padding:24px;width:320px;box-shadow:0 20px 60px rgba(0,0,0,0.2);">
        <h3 style="margin:0 0 12px;font-size:16px;">Tipo di asset</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          ${types.map(t => `
            <button class="btn btn-secondary" style="padding:12px;font-size:13px;"
              onclick="this.closest('div[style]').dataset.result='${t.value}';this.closest('div[style*=fixed]').remove();">
              ${t.label}
            </button>
          `).join('')}
        </div>
        <button class="btn btn-secondary" style="width:100%;margin-top:8px;font-size:12px;"
          onclick="this.closest('div[style*=fixed]').remove();">Annulla</button>
      </div>`;

    const observer = new MutationObserver(() => {
      if (!document.body.contains(modal)) {
        const inner = modal.querySelector('[data-result]');
        resolve(inner ? inner.dataset.result : null);
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true });

    document.body.appendChild(modal);
    // Close on backdrop click
    modal.addEventListener('click', e => { if (e.target === modal) { modal.remove(); resolve(null); } });
  });
};


CS.toggleAssetSelection = function(assetId, assetType) {
  const slotName = { logo: 'logo_asset', product: 'product_asset', photo: 'secondary_asset', texture: 'background_asset' }[assetType] || 'secondary_asset';

  if (CS.state.selectedAssets[slotName] === assetId) {
    delete CS.state.selectedAssets[slotName];
  } else {
    CS.state.selectedAssets[slotName] = assetId;
  }
  CS.renderAssetsRow();
};


// =========================================================================
// Asset Commands
// =========================================================================

CS.addCommand = function(text) {
  if (!text || !text.trim()) return;
  CS.state.assetCommands.push(text.trim());
  CS.renderCommandTags();
};


CS.removeCommand = function(idx) {
  CS.state.assetCommands.splice(idx, 1);
  CS.renderCommandTags();
};


CS.renderCommandTags = function() {
  const container = document.getElementById('cs-cmd-tags');
  if (!container) return;
  container.innerHTML = CS.state.assetCommands.map((cmd, i) =>
    `<span class="cstudio-cmd-tag">${_esc(cmd)} <span class="remove" onclick="CarouselStudio.removeCommand(${i})">×</span></span>`
  ).join('');
};


// =========================================================================
// Step: Generate
// =========================================================================

CS.generate = async function() {
  const prompt = CS.state.prompt || document.getElementById('cs-prompt')?.value || '';
  if (!prompt.trim()) {
    if (window.toast) toast('Scrivi una descrizione per il carosello');
    return;
  }
  CS.state.prompt = prompt.trim();
  CS.state.currentStep = 'generating';

  const body = document.getElementById('cstudio-body');
  body.className = 'cstudio-body';
  body.innerHTML = `
    <div class="cstudio-loading" id="cs-loading">
      <div class="spinner"></div>
      <div class="step-text" id="cs-loading-text">Preparazione...</div>
      <div class="step-progress"><div class="step-bar" id="cs-loading-bar" style="width:5%"></div></div>
    </div>`;

  CS.updateStepBar();
  CS.animateLoadingSteps();

  // Build request payload
  const payload = { prompt: CS.state.prompt };

  if (CS.state.autoPlan) {
    payload.auto_plan = true;
  } else {
    payload.template = CS.state.selectedTemplate;
    payload.variant = CS.state.selectedVariant;
    if (CS.state.selectedTheme) payload.theme = CS.state.selectedTheme;
  }

  // User asset mapping
  if (Object.keys(CS.state.selectedAssets).length > 0) {
    payload.user_asset_mapping = CS.state.selectedAssets;
  }

  // Placement overrides
  if (Object.keys(CS.state.placementOverrides).length > 0) {
    payload.placement_overrides = CS.state.placementOverrides;
  }

  // Asset commands
  if (CS.state.assetCommands.length > 0) {
    payload.asset_commands = CS.state.assetCommands;
  }

  // Style overrides
  if (Object.keys(CS.state.overrides).length > 0) {
    payload.overrides = CS.state.overrides;
  }

  try {
    const resp = await fetch('/api/generate-carousel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json());

    if (resp.error) throw new Error(resp.error);

    CS.state.result = resp;
    CS.state.slideUrls = resp.slides || [];
    CS.state.currentSlide = 0;

    // Update state from result
    if (resp.template) CS.state.selectedTemplate = resp.template;
    if (resp.variant) CS.state.selectedVariant = resp.variant;
    if (resp.theme) CS.state.selectedTheme = resp.theme;

    CS.renderPreviewStep();
  } catch(e) {
    console.error('Generation failed', e);
    body.innerHTML = `
      <div class="cstudio-loading">
        <div style="font-size:32px;">⚠</div>
        <div class="step-text" style="color:var(--red);">${_esc(e.message)}</div>
        <button class="btn btn-primary" onclick="CarouselStudio.renderPromptStep()" style="margin-top:12px;">Riprova</button>
      </div>`;
  }
};


CS.animateLoadingSteps = function() {
  const steps = [
    { text: 'Analisi del prompt...', pct: 15 },
    { text: 'Selezione design...', pct: 30 },
    { text: 'Generazione contenuti...', pct: 45 },
    { text: 'Creazione immagini...', pct: 60 },
    { text: 'Rendering slide...', pct: 80 },
    { text: 'Upload e finalizzazione...', pct: 95 },
  ];

  let i = 0;
  const interval = setInterval(() => {
    if (CS.state.currentStep !== 'generating' || i >= steps.length) {
      clearInterval(interval);
      return;
    }
    const textEl = document.getElementById('cs-loading-text');
    const barEl = document.getElementById('cs-loading-bar');
    if (textEl) textEl.textContent = steps[i].text;
    if (barEl) barEl.style.width = steps[i].pct + '%';
    i++;
  }, 3000);
};


// =========================================================================
// Step: Preview + Customize
// =========================================================================

CS.renderPreviewStep = function() {
  CS.state.currentStep = 'preview';
  const body = document.getElementById('cstudio-body');
  body.className = 'cstudio-body split';

  // Build theme options for sidebar
  const themeCards = CS.state.themes.map(t => {
    // Generate swatch colors from theme data
    return `
      <div class="cstudio-theme-card ${t.id === CS.state.selectedTheme ? 'active' : ''}"
           onclick="CarouselStudio.changeTheme('${t.id}')">
        <div class="cstudio-theme-name">${_esc(t.name || t.id)}</div>
      </div>`;
  }).join('');

  // Build variant selector
  const selTpl = CS.state.templates.find(t => t.template === CS.state.selectedTemplate);
  const variantBtns = (selTpl?.variants || []).map(v =>
    `<div class="cstudio-ctrl-card ${v === CS.state.selectedVariant ? 'active' : ''}"
         onclick="CarouselStudio.changeVariant('${v}')">${v}</div>`
  ).join('');

  // Build template selector
  const tplBtns = CS.state.templates.map(t =>
    `<div class="cstudio-ctrl-card ${t.template === CS.state.selectedTemplate ? 'active' : ''}"
         onclick="CarouselStudio.changeTemplate('${t.template}')">${t.name || t.template}</div>`
  ).join('');

  // Slide names from result
  const slideNames = ['Cover', 'Text', 'List', 'CTA'];

  body.innerHTML = `
    <!-- Left sidebar: controls -->
    <div class="cstudio-panel sidebar">

      <div class="cstudio-ctrl-section">
        <h4>Template</h4>
        <div class="cstudio-ctrl-grid">${tplBtns}</div>
      </div>

      <div class="cstudio-ctrl-section" id="cs-variant-section" ${!variantBtns ? 'style="display:none"' : ''}>
        <h4>Variante</h4>
        <div class="cstudio-ctrl-grid">${variantBtns}</div>
      </div>

      <div class="cstudio-ctrl-section">
        <h4>Tema</h4>
        <div class="cstudio-theme-grid">${themeCards}</div>
      </div>

      <div class="cstudio-ctrl-section" id="cs-placement-section">
        <h4>Posiziona asset</h4>
        <div id="cs-placement-controls"></div>
        <input class="cstudio-cmd-input" id="cs-inline-cmd"
          placeholder="Es: metti il logo in alto a sinistra..."
          onkeydown="if(event.key==='Enter'){event.preventDefault();CarouselStudio.addInlineCommand(this.value);this.value='';}">
      </div>

      <div class="cstudio-ctrl-section">
        <h4>Azioni</h4>
        <button class="btn btn-secondary" style="width:100%;margin-bottom:6px;font-size:12px;"
          onclick="CarouselStudio.regenerate()">Rigenera carosello</button>
        <button class="btn btn-secondary" style="width:100%;font-size:12px;"
          onclick="CarouselStudio.renderPromptStep()">Modifica prompt</button>
      </div>
    </div>

    <!-- Center: slide preview -->
    <div class="cstudio-preview" id="cs-preview-area">
      <div class="cstudio-preview-slide" id="cs-preview-img">
        ${CS.state.slideUrls.length > 0
          ? `<img src="${CS.state.slideUrls[0]}" alt="Slide 1">`
          : '<div style="padding:40px;color:#666;text-align:center;">Nessuna slide</div>'
        }
      </div>

      <div class="cstudio-slide-nav">
        <button onclick="CarouselStudio.prevSlide()">‹</button>
        <div class="cstudio-slide-dots" id="cs-dots">
          ${CS.state.slideUrls.map((_, i) =>
            `<div class="cstudio-slide-dot ${i === 0 ? 'active' : ''}" onclick="CarouselStudio.goToSlide(${i})"></div>`
          ).join('')}
        </div>
        <span class="cstudio-slide-label" id="cs-slide-label">${slideNames[0] || 'Slide 1'} — 1/${CS.state.slideUrls.length}</span>
        <button onclick="CarouselStudio.nextSlide()">›</button>
      </div>

      <div class="cstudio-thumbstrip" id="cs-thumbstrip">
        ${CS.state.slideUrls.map((url, i) =>
          `<div class="cstudio-thumbstrip-item ${i === 0 ? 'active' : ''}" onclick="CarouselStudio.goToSlide(${i})">
            <img src="${url}" alt="Slide ${i+1}">
          </div>`
        ).join('')}
      </div>
    </div>

    <!-- Right sidebar: export -->
    <div class="cstudio-panel sidebar-right">
      <div class="cstudio-ctrl-section">
        <h4>Esporta</h4>
        <div class="cstudio-export">
          <div class="cstudio-export-btn" onclick="CarouselStudio.downloadAll()">
            <span class="icon">📥</span>
            <div>
              <div>Scarica tutte le slide</div>
              <div class="sub">${CS.state.slideUrls.length} immagini PNG</div>
            </div>
          </div>
          <div class="cstudio-export-btn" onclick="CarouselStudio.downloadCurrent()">
            <span class="icon">🖼</span>
            <div>
              <div>Scarica slide corrente</div>
              <div class="sub">PNG singola</div>
            </div>
          </div>
          <div class="cstudio-export-btn" onclick="CarouselStudio.copyCaption()">
            <span class="icon">📋</span>
            <div>
              <div>Copia didascalia</div>
              <div class="sub">Testo per Instagram</div>
            </div>
          </div>
        </div>
      </div>

      ${CS.state.result?.content ? `
      <div class="cstudio-ctrl-section">
        <h4>Contenuto generato</h4>
        <div style="font-size:12px;color:var(--text2);line-height:1.5;">
          <p style="margin:0 0 6px;"><strong>Titolo:</strong> ${_esc(CS.state.result.content.title || '')}</p>
          <p style="margin:0 0 6px;"><strong>Sottotitolo:</strong> ${_esc(CS.state.result.content.subtitle || '')}</p>
          <p style="margin:0 0 6px;"><strong>CTA:</strong> ${_esc(CS.state.result.content.cta || '')}</p>
        </div>
      </div>` : ''}

      ${CS.state.result?.design_plan ? `
      <div class="cstudio-ctrl-section">
        <h4>Design Plan</h4>
        <div style="font-size:11px;color:var(--text3);line-height:1.5;">
          Template: ${_esc(CS.state.result.template)}<br>
          Variante: ${_esc(CS.state.result.variant)}<br>
          Tema: ${_esc(CS.state.result.theme)}
          ${CS.state.result.design_plan.classification ? `<br>Tipo: ${_esc(CS.state.result.design_plan.classification.post_type)}` : ''}
        </div>
      </div>` : ''}
    </div>`;

  CS.updateStepBar();
  CS.renderPlacementControls();
};


// ── Slide navigation ────────────────────────────────────────────────────

CS.goToSlide = function(idx) {
  if (idx < 0 || idx >= CS.state.slideUrls.length) return;
  CS.state.currentSlide = idx;

  const imgContainer = document.getElementById('cs-preview-img');
  if (imgContainer) imgContainer.innerHTML = `<img src="${CS.state.slideUrls[idx]}" alt="Slide ${idx+1}">`;

  // Update dots
  document.querySelectorAll('#cs-dots .cstudio-slide-dot').forEach((d, i) =>
    d.classList.toggle('active', i === idx));

  // Update thumbstrip
  document.querySelectorAll('#cs-thumbstrip .cstudio-thumbstrip-item').forEach((t, i) =>
    t.classList.toggle('active', i === idx));

  // Update label
  const slideNames = ['Cover', 'Text', 'List', 'CTA'];
  const label = document.getElementById('cs-slide-label');
  if (label) label.textContent = `${slideNames[idx] || 'Slide ' + (idx+1)} — ${idx+1}/${CS.state.slideUrls.length}`;
};


CS.prevSlide = function() {
  CS.goToSlide((CS.state.currentSlide - 1 + CS.state.slideUrls.length) % CS.state.slideUrls.length);
};


CS.nextSlide = function() {
  CS.goToSlide((CS.state.currentSlide + 1) % CS.state.slideUrls.length);
};


// ── Customization: theme/template/variant changes ───────────────────────

CS.changeTheme = function(themeId) {
  CS.state.selectedTheme = themeId;
  // Update active state in UI
  document.querySelectorAll('.cstudio-theme-card').forEach(el =>
    el.classList.toggle('active', el.querySelector('.cstudio-theme-name')?.textContent?.trim() === (CS.state.themes.find(t => t.id === themeId)?.name || themeId))
  );
  CS.regenerate();
};


CS.changeTemplate = function(templateId) {
  CS.state.selectedTemplate = templateId;
  CS.state.autoPlan = false;
  const tpl = CS.state.templates.find(t => t.template === templateId);
  CS.state.selectedVariant = tpl?.variants?.[0] || null;
  CS.regenerate();
};


CS.changeVariant = function(variant) {
  CS.state.selectedVariant = variant;
  CS.state.autoPlan = false;
  CS.regenerate();
};


CS.regenerate = function() {
  CS.generate();
};


// ── Placement controls ──────────────────────────────────────────────────

CS.renderPlacementControls = function() {
  const container = document.getElementById('cs-placement-controls');
  if (!container) return;

  // Show controls for selected user assets
  const anchors = ['top_left', 'top_center', 'top_right', 'center_left', 'center', 'center_right', 'bottom_left', 'bottom_center', 'bottom_right', 'full_bg'];
  const anchorLabels = { top_left: '↖', top_center: '↑', top_right: '↗', center_left: '←', center: '●', center_right: '→', bottom_left: '↙', bottom_center: '↓', bottom_right: '↘', full_bg: '▣' };
  const slides = ['cover', 'text', 'list', 'cta'];

  let html = '';
  for (const [slot, assetId] of Object.entries(CS.state.selectedAssets)) {
    const asset = CS.state.userAssets.find(a => a.id === assetId);
    if (!asset) continue;

    const current = CS.state.placementOverrides[slot] || {};
    const currentAnchor = current.anchor || 'center';

    html += `
      <div class="cstudio-placement-row">
        <img src="${asset.url}" alt="${_esc(asset.type)}">
        <div class="info">
          <div class="name">${_esc(asset.filename || asset.type)}</div>
          <div class="type">${slot.replace('_asset', '')}</div>
        </div>
        <select onchange="CarouselStudio.setAnchor('${slot}', this.value)"
          style="font-size:11px;padding:4px;border:1px solid var(--border);border-radius:6px;">
          ${anchors.map(a => `<option value="${a}" ${a === currentAnchor ? 'selected' : ''}>${a.replace(/_/g, ' ')}</option>`).join('')}
        </select>
      </div>`;
  }

  if (!html) {
    html = '<div style="font-size:12px;color:var(--text3);padding:4px 0;">Seleziona asset dal prompt per posizionarli</div>';
  }

  container.innerHTML = html;
};


CS.setAnchor = function(slot, anchor) {
  if (!CS.state.placementOverrides[slot]) CS.state.placementOverrides[slot] = {};
  CS.state.placementOverrides[slot].anchor = anchor;
};


CS.addInlineCommand = function(text) {
  if (!text || !text.trim()) return;
  CS.state.assetCommands.push(text.trim());
  if (window.toast) toast('Comando aggiunto: ' + text.trim());
};


// =========================================================================
// Export
// =========================================================================

CS.downloadAll = async function() {
  if (!CS.state.slideUrls.length) return;
  if (window.showLoading) showLoading('Scaricando slide...');

  for (let i = 0; i < CS.state.slideUrls.length; i++) {
    try {
      const resp = await fetch(CS.state.slideUrls[i]);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `carousel_slide_${i + 1}.png`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch(e) { console.error('Download failed for slide', i, e); }
  }

  if (window.hideLoading) hideLoading();
  if (window.toast) toast(`${CS.state.slideUrls.length} slide scaricate!`);
};


CS.downloadCurrent = async function() {
  const url = CS.state.slideUrls[CS.state.currentSlide];
  if (!url) return;
  try {
    const resp = await fetch(url);
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `carousel_slide_${CS.state.currentSlide + 1}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
    if (window.toast) toast('Slide scaricata!');
  } catch(e) { console.error('Download failed', e); }
};


CS.copyCaption = function() {
  const content = CS.state.result?.content;
  if (!content) return;

  const caption = [
    content.title,
    '',
    content.subtitle,
    '',
    ...(content.bullets || []).map(b => `• ${b}`),
    '',
    content.cta,
  ].filter(l => l !== undefined).join('\n');

  navigator.clipboard.writeText(caption).then(() => {
    if (window.toast) toast('Didascalia copiata!');
  }).catch(() => {
    // Fallback
    const ta = document.createElement('textarea');
    ta.value = caption;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    if (window.toast) toast('Didascalia copiata!');
  });
};


// =========================================================================
// Step bar
// =========================================================================

CS.updateStepBar = function() {
  const steps = ['prompt', 'generating', 'preview'];
  const labels = ['Descrivi', 'Genera', 'Anteprima'];
  const currentIdx = steps.indexOf(CS.state.currentStep);

  const bar = document.getElementById('cstudio-steps');
  if (!bar) return;

  bar.innerHTML = steps.map((step, i) => {
    let cls = 'cstudio-step';
    if (i === currentIdx) cls += ' active';
    else if (i < currentIdx) cls += ' done';
    return `${i > 0 ? '<span class="cstudio-step-divider"></span>' : ''}
      <span class="${cls}" ${i < currentIdx ? `onclick="CarouselStudio.${i === 0 ? 'renderPromptStep' : 'renderPreviewStep'}()"` : ''}>
        ${i < currentIdx ? '✓' : (i + 1)} ${labels[i]}
      </span>`;
  }).join('');
};


// =========================================================================
// Asset Library (standalone screen in Libreria tab)
// =========================================================================

CS.renderAssetLibrary = async function(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // Load assets
  let assets = [];
  try {
    const resp = await fetch('/api/user-assets?limit=200').then(r => r.json());
    assets = resp.assets || [];
  } catch(e) { console.error('Failed to load asset library', e); }

  const types = ['all', 'logo', 'product', 'photo', 'texture'];

  container.innerHTML = `
    <div class="cstudio-lib-header">
      <div>
        <h2 style="margin:0 0 4px;">Asset Library</h2>
        <p style="margin:0;font-size:13px;color:var(--text2);">${assets.length} asset caricati</p>
      </div>
      <div style="display:flex;gap:8px;">
        <div class="cstudio-lib-filters" id="cs-lib-filters">
          ${types.map(t => `<button class="${t === 'all' ? 'active' : ''}" onclick="CarouselStudio.filterLibrary('${t}', this)">${t === 'all' ? 'Tutti' : t.charAt(0).toUpperCase() + t.slice(1)}</button>`).join('')}
        </div>
        <button class="btn btn-primary btn-small" onclick="document.getElementById('cs-lib-upload').click()">+ Carica asset</button>
        <input type="file" id="cs-lib-upload" accept="image/*" style="display:none"
          onchange="CarouselStudio.handleLibraryUpload(this, '${containerId}')">
      </div>
    </div>
    <div class="cstudio-lib-grid" id="cs-lib-grid">
      ${assets.length === 0 ? '<div class="cstudio-lib-empty">Nessun asset caricato. Carica il tuo logo, foto prodotto o texture per usarli nei caroselli.</div>' : ''}
      ${assets.map(a => `
        <div class="cstudio-lib-card" data-type="${a.type}">
          <img class="thumb" src="${a.url}" alt="${_esc(a.filename || a.type)}">
          <div class="meta">
            <div class="name">${_esc(a.filename || 'Asset')}</div>
            <span class="type-badge">${a.type}</span>
            <button class="btn btn-sm" style="float:right;font-size:10px;padding:2px 8px;color:var(--red);border:1px solid var(--red);border-radius:6px;background:transparent;cursor:pointer;"
              onclick="event.stopPropagation();CarouselStudio.deleteAsset('${a.id}','${containerId}')">×</button>
          </div>
        </div>`
      ).join('')}
    </div>`;
};


CS.filterLibrary = function(type, btn) {
  document.querySelectorAll('#cs-lib-filters button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  document.querySelectorAll('#cs-lib-grid .cstudio-lib-card').forEach(card => {
    card.style.display = (type === 'all' || card.dataset.type === type) ? '' : 'none';
  });
};


CS.deleteAsset = async function(assetId, containerId) {
  if (!confirm('Eliminare questo asset?')) return;
  try {
    await fetch(`/api/user-assets/${assetId}`, { method: 'DELETE' });
    CS.renderAssetLibrary(containerId);
    if (window.toast) toast('Asset eliminato');
  } catch(e) { console.error('Delete failed', e); }
};


CS.handleLibraryUpload = async function(input, containerId) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  const type = await CS.pickAssetType();
  if (!type) return;

  const fd = new FormData();
  fd.append('file', file);
  fd.append('type', type);

  try {
    const resp = await fetch('/api/user-assets', { method: 'POST', body: fd }).then(r => r.json());
    if (resp.error) throw new Error(resp.error);
    CS.renderAssetLibrary(containerId);
    if (window.toast) toast('Asset caricato!');
  } catch(e) {
    console.error('Upload failed', e);
    if (window.toast) toast('Errore: ' + e.message);
  }
  input.value = '';
};


// =========================================================================
// Utility
// =========================================================================

function _esc(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
