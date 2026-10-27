/* ============================================
   SLIDE PRESENTATION APP
   Escbase Slide Starter
   ============================================ */

// State
let currentSlide = 0;
let totalSlides = 10;
let isReady = true;
let isAnimating = false;
let audioCtx = null;
let bgMusicGain = null;
let bgMusicSource = null;
let customBgmAudio = null;
let isMuted = false;

// Per-slide audio config - benchmark launch vibe
const slideTransitions = [
  "dramatic",
  "boom",
  "rise",
  "sweep",
  "bass",
  "chord",
  "ascending",
  "minimal"
];
const slideReveals = [
  "sparkle",
  "pop",
  "blip",
  "tick",
  "bell",
  "ping",
  "click",
  "sparkle"
];

// Per-slide script text
const slideScripts = [
  "Tại sao giá Vàng tuần này lại chững lại và rơi vào trạng thái trung lập âm sáu phẩy chín điểm?",
  "Hệ thống Market Bias ghi nhận Vàng ở mức âm sáu phẩy chín điểm, phản ánh cuộc chiến kéo co gay cấn giữa sức mạnh đồng đô la Mỹ và dòng tiền nới lỏng thanh khoản toàn cầu.",
  "Lợi suất thực mười năm duy trì ở mức cao hai phẩy bảy mươi tám phần trăm cùng đà tăng bền bỉ của đồng đô la Mỹ đang tạo ra rào cản chi phí cơ hội đắt đỏ, kìm hãm dòng vốn đầu cơ.",
  "Tuy nhiên, sự mở rộng của cung tiền M2 với điểm chuẩn hóa dương một phẩy năm mươi chín kết hợp rủi ro thị trường trái phiếu MOVE trên một trăm lẻ một điểm đang tạo bệ đỡ vững chắc ngăn vàng lao dốc.",
  "Trên thị trường phái sinh, khối lượng quyền chọn gamma ròng dương bốn mươi sáu phẩy bảy triệu đô la đang kẹp chặt giá vàng dao động trong hành lang từ ba trăm bảy mươi đến ba trăm chín mươi tư điểm.",
  "Nghịch lý hiện tại là đà tăng ngắn hạn của đô la Mỹ đang che lấp sự phình to của cung tiền toàn cầu. Khi căng thẳng tín dụng bùng nổ, sự kìm nén này sẽ kích hoạt một pha bùng nổ biến động mới.",
  "Hệ thống dự phóng năm mươi lăm phần trăm xác suất vàng tiếp tục đi ngang giằng co, hai mươi lăm phần trăm áp lực đô la ép thủng hỗ trợ và hai mươi phần trăm dòng tiền trú ẩn bùng nổ vượt kháng cự.",
  "Chiến lược tối ưu lúc này là kiên nhẫn giao dịch theo biên độ và quản trị vốn chặt chẽ. Hãy theo dõi KenvinZone để cập nhật biến động dòng tiền lớn mỗi tuần nhé!"
];
const initialSlideScripts = [...slideScripts];
const initialSlideTransitions = [...slideTransitions];
const initialSlideReveals = [...slideReveals];

const themePresets = {
  'creator-pink-blue': {
    label: 'Creator Pink Blue',
    variables: {
      '--primary': '#ea4c89',
      '--primary-light': '#ff9ac2',
      '--primary-dark': '#8f1d50',
      '--accent': '#4a90e2',
      '--accent-light': '#9bd3ff',
      '--info': '#50c878',
      '--success': '#50c878',
      '--bg-dark': '#07030d'
    }
  },
  'openclaw-neon-green': {
    label: 'OpenClaw Neon Green',
    variables: {
      '--primary': '#00e676',
      '--primary-light': '#b9f6ca',
      '--primary-dark': '#0a7442',
      '--accent': '#ffab40',
      '--accent-light': '#ffd699',
      '--info': '#69f0ae',
      '--success': '#00e676',
      '--bg-dark': '#030807'
    }
  },
  'cyber-purple': {
    label: 'Cyber Purple',
    variables: {
      '--primary': '#8b5cf6',
      '--primary-light': '#c4b5fd',
      '--primary-dark': '#4c1d95',
      '--accent': '#22d3ee',
      '--accent-light': '#a5f3fc',
      '--info': '#38bdf8',
      '--success': '#34d399',
      '--bg-dark': '#080413'
    }
  },
  'minimal-gold': {
    label: 'Minimal Gold',
    variables: {
      '--primary': '#f5c542',
      '--primary-light': '#ffe9a3',
      '--primary-dark': '#926b10',
      '--accent': '#ffffff',
      '--accent-light': '#f4f4f5',
      '--info': '#facc15',
      '--success': '#a3e635',
      '--bg-dark': '#090807'
    }
  },
  'dark-terminal': {
    label: 'Dark Terminal',
    variables: {
      '--primary': '#22c55e',
      '--primary-light': '#86efac',
      '--primary-dark': '#14532d',
      '--accent': '#94a3b8',
      '--accent-light': '#cbd5e1',
      '--info': '#38bdf8',
      '--success': '#22c55e',
      '--bg-dark': '#020617'
    }
  },
  'sunset-fire': {
    label: 'Sunset Fire',
    variables: { '--primary': '#ff5a36', '--primary-light': '#ffb59e', '--primary-dark': '#a62a12', '--accent': '#ffcf3f', '--accent-light': '#ffe6a3', '--info': '#ff8a5b', '--success': '#f59e0b', '--bg-dark': '#0d0503' }
  },
  'ocean-aqua': {
    label: 'Ocean Aqua',
    variables: { '--primary': '#06b6d4', '--primary-light': '#99f6ff', '--primary-dark': '#0e5f73', '--accent': '#3b82f6', '--accent-light': '#bfdbfe', '--info': '#38bdf8', '--success': '#22d3ee', '--bg-dark': '#030a0f' }
  },
  'aurora-mint': {
    label: 'Aurora Mint',
    variables: { '--primary': '#34d399', '--primary-light': '#b6f7dc', '--primary-dark': '#0f6b4a', '--accent': '#a855f7', '--accent-light': '#ddd0fe', '--info': '#22d3ee', '--success': '#34d399', '--bg-dark': '#030a09' }
  },
  'magenta-pop': {
    label: 'Magenta Pop',
    variables: { '--primary': '#ec4899', '--primary-light': '#ffc2e2', '--primary-dark': '#8a1e5a', '--accent': '#a855f7', '--accent-light': '#e9d5ff', '--info': '#f472b6', '--success': '#c084fc', '--bg-dark': '#0c0410' }
  },
  'ice-frost': {
    label: 'Ice Frost',
    variables: { '--primary': '#38bdf8', '--primary-light': '#e0f4ff', '--primary-dark': '#1b6fa8', '--accent': '#818cf8', '--accent-light': '#c7d2fe', '--info': '#60a5fa', '--success': '#22d3ee', '--bg-dark': '#040810' }
  },
  'solar-gold': {
    label: 'Solar Gold',
    variables: { '--primary': '#fbbf24', '--primary-light': '#fff1c2', '--primary-dark': '#92610a', '--accent': '#fb923c', '--accent-light': '#fed7aa', '--info': '#facc15', '--success': '#fbbf24', '--bg-dark': '#0c0803' }
  },
  'candy-pop': {
    label: 'Candy Pop',
    variables: { '--primary': '#f472b6', '--primary-light': '#ffd6ec', '--primary-dark': '#9d2168', '--accent': '#22d3ee', '--accent-light': '#a5f3fc', '--info': '#f9a8d4', '--success': '#5eead4', '--bg-dark': '#0c0410' }
  },
  'crimson-ember': {
    label: 'Crimson Ember',
    variables: { '--primary': '#ef4444', '--primary-light': '#ffc9c9', '--primary-dark': '#8f1f1f', '--accent': '#f59e0b', '--accent-light': '#fde68a', '--info': '#fb7185', '--success': '#f87171', '--bg-dark': '#0d0404' }
  },
  'custom': {
    label: 'Custom',
    variables: {
      '--primary': '#ea4c89',
      '--primary-light': '#ff9ac2',
      '--primary-dark': '#8f1d50',
      '--accent': '#4a90e2',
      '--accent-light': '#9bd3ff',
      '--info': '#50c878',
      '--success': '#50c878',
      '--bg-dark': '#07030d'
    }
  }
};

const previewColorControls = [
  { key: '--primary', type: 'theme', label: 'Primary' },
  { key: '--accent', type: 'theme', label: 'Accent' },
  { key: 'backgroundColor', type: 'visual', label: 'Màu nền' },
  { key: 'gridLight', type: 'visual', label: 'Đèn lưới' },
  { key: 'iconGlow', type: 'visual', label: 'Icon glow' },
  { key: 'iconBacklight', type: 'visual', label: 'Backlight' },
  { key: 'iconLight', type: 'visual', label: 'Ánh icon' }
];

const backgroundFxOptions = {
  scan: 'Scan / Flow / Noise',
  particles: 'Particles',
  rings: 'Rings',
  lorenz: 'Lorenz',
  'matrix-rain': 'Matrix Rain',
  'candlestick': 'Candlestick Pulse',
  'candlestick-diag': 'Candlestick Xéo',
  'candle-mono': 'Candle Mono Gold (TA)',
  'wave-grid': 'Wave Grid',
  'bokeh': 'Bokeh Blur',
  'pulse-radar': 'Pulse Radar',
  'constellation': 'Constellation',
  none: 'Tắt animation'
};

const defaultPreviewSettings = {
  "theme": {
    "preset": "dark-terminal",
    "variables": {
      "--primary": "#22c55e",
      "--primary-light": "#86efac",
      "--primary-dark": "#14532d",
      "--accent": "#94a3b8",
      "--accent-light": "#cbd5e1",
      "--info": "#38bdf8",
      "--success": "#22c55e",
      "--bg-dark": "#020617"
    },
    "customVariables": {
      "--primary": "#f59e0b",
      "--primary-light": "#fbbf24",
      "--primary-dark": "#92400e",
      "--accent": "#38bdf8",
      "--accent-light": "#7dd3fc",
      "--info": "#38bdf8",
      "--success": "#22c55e",
      "--bg-dark": "#090d16"
    }
  },
  "bgm": {
    "mode": "custom",
    "preset": "ambient",
    "volume": 0.22,
    "custom": {
      "name": "Write_You.mp3",
      "path": "preview-assets/bgm/Write_You.mp3",
      "url": "preview-assets/bgm/Write_You.mp3"
    }
  },
  "subtitles": {
    "enabled": false,
    "color": "#f0ff1a",
    "fontSize": 18,
    "bottom": 60,
    "maxLines": 1
  },
  "visuals": {
    "colorMode": "dark",
    "backgroundColor": "#020617",
    "gridEnabled": false,
    "gridLight": "#94a3b8",
    "iconGlow": "#22c55e",
    "iconBacklight": "#94a3b8",
    "iconLight": "#22c55e",
    "backgroundFx": "candle-mono",
    "customValues": {
      "backgroundColor": "#090d16",
      "gridLight": "#f59e0b",
      "iconGlow": "#f59e0b",
      "iconBacklight": "#94a3b8",
      "iconLight": "#f59e0b"
    }
  },
  "slides": {
    "deletedIds": [],
    "scriptLines": [
      "Tại sao giá Vàng tuần này lại chững lại và rơi vào trạng thái trung lập âm sáu phẩy chín điểm?",
      "Hệ thống Market Bias ghi nhận Vàng ở mức âm sáu phẩy chín điểm, phản ánh cuộc chiến kéo co gay cấn giữa sức mạnh đồng đô la Mỹ và dòng tiền nới lỏng thanh khoản toàn cầu.",
      "Lợi suất thực mười năm duy trì ở mức cao hai phẩy bảy mươi tám phần trăm cùng đà tăng bền bỉ của đồng đô la Mỹ đang tạo ra rào cản chi phí cơ hội đắt đỏ, kìm hãm dòng vốn đầu cơ.",
      "Tuy nhiên, sự mở rộng của cung tiền M2 với điểm chuẩn hóa dương một phẩy năm mươi chín kết hợp rủi ro thị trường trái phiếu MOVE trên một trăm lẻ một điểm đang tạo bệ đỡ vững chắc ngăn vàng lao dốc.",
      "Trên thị trường phái sinh, khối lượng quyền chọn gamma ròng dương bốn mươi sáu phẩy bảy triệu đô la đang kẹp chặt giá vàng dao động trong hành lang từ ba trăm bảy mươi đến ba trăm chín mươi tư điểm.",
      "Nghịch lý hiện tại là đà tăng ngắn hạn của đô la Mỹ đang che lấp sự phình to của cung tiền toàn cầu. Khi căng thẳng tín dụng bùng nổ, sự kìm nén này sẽ kích hoạt một pha bùng nổ biến động mới.",
      "Hệ thống dự phóng năm mươi lăm phần trăm xác suất vàng tiếp tục đi ngang giằng co, hai mươi lăm phần trăm áp lực đô la ép thủng hỗ trợ và hai mươi phần trăm dòng tiền trú ẩn bùng nổ vượt kháng cự.",
      "Chiến lược tối ưu lúc này là kiên nhẫn giao dịch theo biên độ và quản trị vốn chặt chẽ. Hãy theo dõi KenvinZone để cập nhật biến động dòng tiền lớn mỗi tuần nhé!"
    ],
    "transitionSounds": [
      "dramatic",
      "boom",
      "rise",
      "sweep",
      "bass",
      "chord",
      "ascending",
      "minimal"
    ],
    "revealSounds": [
      "sparkle",
      "pop",
      "blip",
      "tick",
      "bell",
      "ping",
      "click",
      "sparkle"
    ]
  },
  "score": -7
};

let previewSettings = JSON.parse(JSON.stringify(defaultPreviewSettings));

// DOM Elements
const initialSlides = Array.from(document.querySelectorAll('.slide'));
initialSlides.forEach((slide, index) => {
  if (!slide.dataset.slideId) slide.dataset.slideId = slide.dataset.slide || String(index);
});
const initialSlideIds = initialSlides.map(slide => slide.dataset.slideId);
let slides = [...initialSlides];
totalSlides = slides.length;
const progressFill = document.getElementById('progressFill');
const currentSlideEl = document.getElementById('currentSlide');
const container = document.getElementById('slideContainer');
let themeEditorPanel = null;
let previewSubtitleOverlay = null;
let previewSubtitleLine = null;
let previewSubtitleRaf = null;
let previewSubtitleStartedAt = 0;
let previewSubtitleSlide = 0;
let previewSettingsSaveChain = Promise.resolve();
let scriptAutoSaveTimer = null;

function subtitleCaptionConstraints() {
  return (previewSettings?.subtitles?.maxLines || defaultPreviewSettings.subtitles.maxLines) <= 1
    ? { maxWords: 6, maxChars: 34 }
    : { maxWords: 9, maxChars: 62 };
}

function buildPreviewSubtitleCaptions(text) {
  const words = text.match(/\S+/g) || [];
  const captions = [];
  let current = [];
  let cursor = 0;
  const { maxWords, maxChars } = subtitleCaptionConstraints();
  const flush = () => {
    if (!current.length) return;
    const phraseWords = [...current];
    const phrase = phraseWords.join(' ');
    const duration = Math.max(1.1, phrase.length * 0.065);
    const totalWeight = Math.max(1, phraseWords.reduce((sum, word) => sum + Math.max(1, word.length), 0));
    let wordCursor = cursor;
    const timedWords = phraseWords.map((word, index) => {
      const span = index === phraseWords.length - 1
        ? (cursor + duration) - wordCursor
        : duration * Math.max(1, word.length) / totalWeight;
      const result = { text: word, start: wordCursor, end: wordCursor + span };
      wordCursor += span;
      return result;
    });
    captions.push({ text: phrase, start: cursor, end: cursor + duration, words: timedWords });
    cursor += duration;
    current = [];
  };
  words.forEach((word) => {
    const tentative = [...current, word].join(' ');
    if (current.length && (current.length >= maxWords || tentative.length > maxChars)) {
      flush();
    }
    current.push(word);
  });
  flush();
  return captions;
}

let previewSubtitleCaptions = slideScripts.map(buildPreviewSubtitleCaptions);

function findPreviewActiveWordIndex(words, time) {
  let candidate = -1;
  for (let i = 0; i < words.length; i += 1) {
    const word = words[i];
    if (time >= word.start && time <= word.end + 0.08) return i;
    if (word.start <= time) candidate = i;
    if (word.start > time) break;
  }
  return candidate;
}

function fitPreviewSubtitleLine() {
  if (!previewSubtitleLine) return;
  previewSubtitleLine.style.transform = '';
  previewSubtitleLine.style.transformOrigin = '';
  if ((previewSettings?.subtitles?.maxLines || defaultPreviewSettings.subtitles.maxLines) > 1) return;
  const overlayRect = previewSubtitleOverlay?.getBoundingClientRect();
  const availableWidth = Math.max(0, (overlayRect?.width || previewSubtitleLine.parentElement?.getBoundingClientRect().width || previewSubtitleLine.getBoundingClientRect().width || 0) - 8);
  if (!availableWidth) return;
  const range = document.createRange();
  range.selectNodeContents(previewSubtitleLine);
  const measuredWidth = range.getBoundingClientRect().width || 0;
  if (!availableWidth || !measuredWidth || measuredWidth <= availableWidth) return;
  const scale = Math.min(1, availableWidth / measuredWidth);
  previewSubtitleLine.style.transformOrigin = 'center center';
  previewSubtitleLine.style.transform = `scale(${scale})`;
}

function renderPreviewCaption(caption, time) {
  const words = Array.isArray(caption.words) ? caption.words : [];
  if (!words.length) {
    previewSubtitleLine.textContent = caption.text;
    fitPreviewSubtitleLine();
    return;
  }
  const activeWordIndex = findPreviewActiveWordIndex(words, time);
  previewSubtitleLine.replaceChildren();
  words.forEach((word, index) => {
    const span = document.createElement('span');
    span.className = 'script-subtitle-word';
    if (index < activeWordIndex) {
      span.classList.add('past');
    } else if (index === activeWordIndex) {
      span.classList.add('active');
    }
    span.textContent = word.text;
    previewSubtitleLine.appendChild(span);
  });
  fitPreviewSubtitleLine();
}

function ensurePreviewSubtitleOverlay() {
  if (previewSubtitleOverlay) return;
  previewSubtitleOverlay = document.createElement('div');
  previewSubtitleOverlay.className = 'script-subtitles preview-script-subtitles';
  previewSubtitleLine = document.createElement('div');
  previewSubtitleLine.className = 'script-subtitle-line';
  previewSubtitleOverlay.appendChild(previewSubtitleLine);
  container.appendChild(previewSubtitleOverlay);
}

function renderPreviewSubtitles() {
  if (previewSubtitleOverlay) previewSubtitleOverlay.classList.remove('visible');
  return;
}

function startPreviewSubtitles(slideIdx) {
  if (previewSubtitleOverlay) previewSubtitleOverlay.classList.remove('visible');
  return;
}

function stopPreviewSubtitles() {
  if (previewSubtitleRaf) cancelAnimationFrame(previewSubtitleRaf);
  previewSubtitleRaf = null;
  if (previewSubtitleOverlay) previewSubtitleOverlay.classList.remove('visible');
}

function projectNameFromPath() {
  const match = window.location.pathname.match(/\/slide\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

function settingsStorageKey() {
  return `preview-settings:${projectNameFromPath() || 'local'}`;
}

function scriptStorageKey() {
  return `preview-script:${projectNameFromPath() || 'local'}`;
}

function hasDeletedSlides(settings = previewSettings) {
  return Array.isArray(settings?.slides?.deletedIds) && settings.slides.deletedIds.length > 0;
}

function activeInitialIndexes(deletedIds = previewSettings.slides?.deletedIds || []) {
  const deleted = new Set(deletedIds.map(String));
  return initialSlideIds
    .map((id, index) => deleted.has(id) ? -1 : index)
    .filter(index => index >= 0);
}

function activeInitialIds(deletedIds = previewSettings.slides?.deletedIds || []) {
  const deleted = new Set(deletedIds.map(String));
  return initialSlideIds.filter(id => !deleted.has(id));
}

function linesForActiveSlides(lines, deletedIds = previewSettings.slides?.deletedIds || []) {
  if (!Array.isArray(lines)) return null;
  const cleaned = lines.map(line => String(line || '').trim());
  if (cleaned.length === totalSlides) return cleaned;
  if (cleaned.length !== initialSlideIds.length) return null;
  return activeInitialIndexes(deletedIds).map(index => cleaned[index] || '');
}

function isHexColor(value) {
  return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value);
}

function hexToRgba(hex, alpha) {
  const value = isHexColor(hex) ? hex.slice(1) : 'ffffff';
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function storedCustomVisualSettings(settings = previewSettings) {
  const visuals = settings?.visuals || {};
  const theme = settings?.theme || {};
  const customVars = theme.customVariables && typeof theme.customVariables === 'object'
    ? theme.customVariables
    : (theme.preset === 'custom' && theme.variables && typeof theme.variables === 'object' ? theme.variables : {});
  const stored = visuals.customValues && typeof visuals.customValues === 'object' ? visuals.customValues : null;
  const current = visuals;
  const source = stored || current;
  const fallback = defaultPreviewSettings.visuals;
  return {
    backgroundColor: isHexColor(source.backgroundColor) ? source.backgroundColor : (isHexColor(customVars['--bg-dark']) ? customVars['--bg-dark'] : fallback.backgroundColor),
    gridLight: isHexColor(source.gridLight) ? source.gridLight : (isHexColor(customVars['--accent']) ? customVars['--accent'] : fallback.gridLight),
    iconGlow: isHexColor(source.iconGlow) ? source.iconGlow : (isHexColor(customVars['--primary']) ? customVars['--primary'] : fallback.iconGlow),
    iconBacklight: isHexColor(source.iconBacklight) ? source.iconBacklight : (isHexColor(customVars['--accent']) ? customVars['--accent'] : fallback.iconBacklight),
    iconLight: isHexColor(source.iconLight) ? source.iconLight : (isHexColor(customVars['--success']) ? customVars['--success'] : fallback.iconLight)
  };
}

function normalizeVisualSettings(settings) {
  const input = settings?.visuals || {};
  const themeVariables = settings?.theme?.variables || {};
  const fallback = defaultPreviewSettings.visuals;
  const fx = ['flow', 'noise', 'slide'].includes(input.backgroundFx) ? 'scan' : input.backgroundFx;
  return {
    colorMode: input.colorMode === 'light' ? 'light' : 'dark',
    backgroundColor: isHexColor(input.backgroundColor) ? input.backgroundColor : (isHexColor(themeVariables['--bg-dark']) ? themeVariables['--bg-dark'] : fallback.backgroundColor),
    gridEnabled: typeof input.gridEnabled === 'boolean' ? input.gridEnabled : fallback.gridEnabled,
    gridLight: isHexColor(input.gridLight) ? input.gridLight : (isHexColor(themeVariables['--accent']) ? themeVariables['--accent'] : fallback.gridLight),
    iconGlow: isHexColor(input.iconGlow) ? input.iconGlow : (isHexColor(themeVariables['--primary']) ? themeVariables['--primary'] : fallback.iconGlow),
    iconBacklight: isHexColor(input.iconBacklight) ? input.iconBacklight : (isHexColor(themeVariables['--accent']) ? themeVariables['--accent'] : fallback.iconBacklight),
    iconLight: isHexColor(input.iconLight) ? input.iconLight : (isHexColor(themeVariables['--success']) ? themeVariables['--success'] : fallback.iconLight),
    backgroundFx: fx && backgroundFxOptions[fx] ? fx : fallback.backgroundFx,
    customValues: storedCustomVisualSettings(settings)
  };
}

function storedCustomThemeVariables(settings = previewSettings) {
  const theme = settings?.theme || {};
  const stored = theme.customVariables && typeof theme.customVariables === 'object' ? theme.customVariables : null;
  const fallback = theme.variables && typeof theme.variables === 'object' ? theme.variables : {};
  return {
    ...themePresets.custom.variables,
    ...(stored || fallback)
  };
}

function normalizeThemeSettings(settings) {
  const preset = settings?.theme?.preset && themePresets[settings.theme.preset]
    ? settings.theme.preset
    : defaultPreviewSettings.theme.preset;
  const customVariables = storedCustomThemeVariables(settings);
  return {
    preset,
    variables: {
      ...(preset === 'custom' ? customVariables : themePresets[preset].variables),
      ...(preset === 'custom' ? {} : (settings?.theme?.variables || {}))
    },
    customVariables
  };
}

function normalizeBgmSettings(settings) {
  const input = settings?.bgm || {};
  const custom = input.custom && typeof input.custom === 'object' ? input.custom : {};
  const preset = input.preset && bgmPresets[input.preset] ? input.preset : defaultPreviewSettings.bgm.preset;
  let mode = ['preset', 'custom', 'none'].includes(input.mode) ? input.mode : defaultPreviewSettings.bgm.mode;
  const volume = Math.min(0.3, Math.max(0, Number(input.volume ?? defaultPreviewSettings.bgm.volume) || 0));
  const normalizedCustom = {
    name: String(custom.name || ''),
    path: String(custom.path || ''),
    url: String(custom.url || '')
  };
  if (mode === 'custom' && !normalizedCustom.path && !normalizedCustom.url) mode = 'preset';
  return {
    mode,
    preset,
    volume,
    custom: normalizedCustom
  };
}

function normalizeSubtitleSettings(settings) {
  const input = settings?.subtitles || {};
  const fallback = defaultPreviewSettings.subtitles;
  const fontSize = Math.min(28, Math.max(12, Number(input.fontSize ?? fallback.fontSize) || fallback.fontSize));
  const bottom = Math.min(180, Math.max(40, Number(input.bottom ?? fallback.bottom) || fallback.bottom));
  const maxLines = Math.round(Math.min(3, Math.max(1, Number(input.maxLines ?? fallback.maxLines) || fallback.maxLines)));
  const color = typeof input.color === 'string' && /^#[0-9a-fA-F]{6}$/.test(input.color) ? input.color : fallback.color;
  return {
    enabled: false,
    color,
    fontSize,
    bottom,
    maxLines
  };
}

function normalizeSlideAudioList(value, expectedCount) {
  if (!Array.isArray(value)) return [];
  const cleaned = value.map(item => String(item || '').trim()).filter(Boolean);
  return cleaned.length === expectedCount ? cleaned : [];
}

function normalizeSlideSettings(settings) {
  const input = settings?.slides || {};
  const allowed = new Set(initialSlideIds);
  const deletedIds = [];
  if (Array.isArray(input.deletedIds)) {
    input.deletedIds.forEach((id) => {
      const value = String(id);
      if (allowed.has(value) && !deletedIds.includes(value)) deletedIds.push(value);
    });
  }
  const activeCount = initialSlideIds.length - deletedIds.length;
  const rawScriptLines = Array.isArray(input.scriptLines) ? input.scriptLines : [];
  const scriptLines = rawScriptLines
    .map(line => String(line || '').trim())
    .filter(Boolean);
  const transitionSounds = normalizeSlideAudioList(input.transitionSounds, activeCount);
  const revealSounds = normalizeSlideAudioList(input.revealSounds, activeCount);
  return {
    deletedIds,
    scriptLines: scriptLines.length === activeCount ? scriptLines : [],
    transitionSounds,
    revealSounds
  };
}

function normalizePreviewSettings(settings) {
  const theme = normalizeThemeSettings(settings);
  return {
    ...settings,
    theme,
    visuals: normalizeVisualSettings({ ...settings, theme }),
    bgm: normalizeBgmSettings(settings),
    subtitles: normalizeSubtitleSettings(settings),
    slides: normalizeSlideSettings(settings)
  };
}

function applyThemeSettings(settings = previewSettings) {
  const normalized = normalizePreviewSettings(settings);
  previewSettings = normalized;
  Object.entries(normalized.theme.variables).forEach(([name, value]) => {
    document.documentElement.style.setProperty(name, value);
  });
  const select = document.getElementById('themePresetSelect');
  if (select) select.value = normalized.theme.preset;
  renderThemeSwatches();
}

function updateVisualControls() {
  const controls = document.querySelectorAll('[data-preview-color-key]');
  const vars = previewSettings.theme.variables;
  const visuals = previewSettings.visuals || defaultPreviewSettings.visuals;
  controls.forEach((input) => {
    const key = input.dataset.previewColorKey;
    const type = input.dataset.previewColorType;
    const value = type === 'theme' ? vars[key] : visuals[key];
    if (isHexColor(value)) input.value = value;
  });
  const gridEnabled = document.getElementById('gridEnabled');
  if (gridEnabled) gridEnabled.checked = visuals.gridEnabled !== false;
  const backgroundFxSelect = document.getElementById('backgroundFxSelect');
  if (backgroundFxSelect) backgroundFxSelect.value = visuals.backgroundFx || defaultPreviewSettings.visuals.backgroundFx;
}

function applyBackgroundFx(backgroundFx) {
  const fx = ['flow', 'noise', 'slide'].includes(backgroundFx) ? 'scan' : backgroundFx;
  document.querySelectorAll('.fx-canvas').forEach((canvas) => {
    if (!canvas.dataset.defaultFx) canvas.dataset.defaultFx = canvas.dataset.fx || 'scan';
    if (fx === 'none') {
      canvas.hidden = true;
      return;
    }
    canvas.hidden = false;
    canvas.dataset.fx = backgroundFxOptions[fx] ? fx : defaultPreviewSettings.visuals.backgroundFx;
  });
}

function applyVisualSettings(settings = previewSettings) {
  const normalized = normalizePreviewSettings(settings);
  previewSettings = normalized;
  const visuals = normalized.visuals;
  previewSettings.theme.variables['--bg-dark'] = visuals.backgroundColor;
  document.documentElement.style.setProperty('--bg-dark', visuals.backgroundColor);
  document.documentElement.style.setProperty('--background-glow', hexToRgba(visuals.gridLight, 0.26));
  document.documentElement.style.setProperty('--background-glow-soft', hexToRgba(visuals.gridLight, 0.14));
  document.documentElement.style.setProperty('--grid-light', visuals.gridLight);
  document.documentElement.style.setProperty('--grid-light-soft', hexToRgba(visuals.gridLight, 0.22));
  document.documentElement.style.setProperty('--grid-line', hexToRgba(visuals.gridLight, 0.14));
  document.documentElement.style.setProperty('--grid-line-soft', hexToRgba(visuals.gridLight, 0.08));
  document.documentElement.style.setProperty('--grid-opacity', visuals.gridEnabled ? '1' : '0');
  document.documentElement.style.setProperty('--icon-glow', visuals.iconGlow);
  document.documentElement.style.setProperty('--icon-glow-soft', hexToRgba(visuals.iconGlow, 0.36));
  document.documentElement.style.setProperty('--icon-glow-strong', hexToRgba(visuals.iconGlow, 0.68));
  document.documentElement.style.setProperty('--icon-backlight', visuals.iconBacklight);
  document.documentElement.style.setProperty('--icon-backlight-soft', hexToRgba(visuals.iconBacklight, 0.42));
  document.documentElement.style.setProperty('--icon-light', visuals.iconLight);
  document.documentElement.style.setProperty('--icon-light-soft', hexToRgba(visuals.iconLight, 0.58));
  document.documentElement.style.setProperty('--background-fx-opacity', visuals.backgroundFx === 'none' ? '0' : '0.48');
  applyBackgroundFx(visuals.backgroundFx);
  updateVisualControls();
}

function selectedBgmValue(bgm = previewSettings.bgm) {
  if (bgm.mode === 'none') return 'none';
  if (bgm.mode === 'custom') return 'custom';
  return bgm.preset;
}

function updateBgmControls() {
  const bgm = previewSettings.bgm;
  const value = selectedBgmValue(bgm);
  const selects = [document.getElementById('bgmSelect'), document.getElementById('editorBgmSelect')];
  selects.forEach((select) => {
    if (select) select.value = value;
  });
  const volume = document.getElementById('bgmVolume');
  const volumeValue = document.getElementById('bgmVolumeValue');
  const customName = document.getElementById('bgmCustomName');
  if (volume) volume.value = String(bgm.volume);
  if (volumeValue) volumeValue.textContent = Math.round(bgm.volume * 100) + '%';
  if (customName) {
    customName.textContent = bgm.custom.name || (bgm.mode === 'custom' ? 'Custom BGM' : 'Chưa upload file');
  }
}

function applyBgmSettings(settings = previewSettings) {
  const normalized = normalizePreviewSettings(settings);
  previewSettings = normalized;
  const preset = bgmPresets[normalized.bgm.preset];
  if (preset) {
    for (let i = 0; i < 4; i++) {
      chordProgression[i] = preset.chords[i];
      arpNotes[i] = preset.arps[i];
    }
  }
  updateBgmControls();
  if (bgMusicGain && audioCtx) {
    bgMusicGain.gain.setTargetAtTime(normalized.bgm.volume, audioCtx.currentTime, 0.08);
  }
}

function updateSubtitleControls() {
  const subtitles = previewSettings.subtitles;
  const enabled = document.getElementById('subtitleEnabled');
  const color = document.getElementById('subtitleColor');
  const fontSize = document.getElementById('subtitleFontSize');
  const fontSizeValue = document.getElementById('subtitleFontSizeValue');
  const bottom = document.getElementById('subtitleBottom');
  const bottomValue = document.getElementById('subtitleBottomValue');
  if (enabled) enabled.checked = subtitles.enabled;
  if (color) color.value = subtitles.color;
  if (fontSize) fontSize.value = String(subtitles.fontSize);
  if (fontSizeValue) fontSizeValue.textContent = subtitles.fontSize + 'px';
  if (bottom) bottom.value = String(subtitles.bottom);
  if (bottomValue) bottomValue.textContent = subtitles.bottom + 'px';
}

function applySubtitleSettings(settings = previewSettings) {
  const normalized = normalizePreviewSettings(settings);
  previewSettings = normalized;
  const subtitles = normalized.subtitles;
  document.documentElement.style.setProperty('--subtitle-color', subtitles.color);
  document.documentElement.style.setProperty('--subtitle-font-size', subtitles.fontSize + 'px');
  document.documentElement.style.setProperty('--subtitle-bottom', subtitles.bottom + 'px');
  document.documentElement.style.setProperty('--subtitle-max-lines', subtitles.maxLines);
  document.documentElement.style.setProperty('--subtitle-flex-wrap', subtitles.maxLines <= 1 ? 'nowrap' : 'wrap');
  document.documentElement.style.setProperty('--subtitle-white-space', subtitles.maxLines <= 1 ? 'nowrap' : 'normal');
  previewSubtitleCaptions = slideScripts.map(buildPreviewSubtitleCaptions);
  updateSubtitleControls();
  if (!subtitles.enabled) stopPreviewSubtitles();
}

function updateSlideCounterTotal() {
  const totalSlideEl = document.getElementById('totalSlides');
  if (totalSlideEl) totalSlideEl.textContent = totalSlides;
}

function renumberRuntimeSlides() {
  slides.forEach((slide, index) => {
    slide.dataset.slide = String(index);
  });
}

function playVideosInElement(element) {
  element?.querySelectorAll('video').forEach(video => {
    video.muted = isMuted;
    try { video.currentTime = 0; } catch {}
    video.play().catch(() => {});
  });
}

function pauseVideosInSlide(slide, reset = true) {
  slide?.querySelectorAll('video').forEach(video => {
    video.pause();
    if (reset) {
      try { video.currentTime = 0; } catch {}
    }
  });
}

function setActiveRuntimeSlide(index = currentSlide, options = {}) {
  if (!slides.length) return;
  isAnimating = false;
  currentSlide = Math.min(Math.max(0, index), totalSlides - 1);
  stopPreviewSubtitles();
  slides.forEach((slide, slideIndex) => {
    slide.classList.toggle('active', slideIndex === currentSlide);
    slide.style.transform = '';
    slide.style.opacity = '';
    resetElements(slideIndex);
  });
  const activeSlide = slides[currentSlide];
  const firstEl = activeSlide?.querySelector('.slide-element');
  if (options.revealFirst && firstEl) {
    firstEl.classList.add('visible');
    playVideosInElement(firstEl);
    startPreviewSubtitles(currentSlide);
  }
  updateProgress();
  updateAudioPanel();
}

function updateSlideDeleteControls() {
  const badge = document.getElementById('slideDeleteBadge');
  const deleteButton = document.getElementById('deleteSlideBtn');
  const restoreButton = document.getElementById('restoreSlideBtn');
  const deletedCount = previewSettings.slides?.deletedIds?.length || 0;
  if (badge) badge.textContent = `Slide ${Math.min(currentSlide + 1, totalSlides)} / ${totalSlides}`;
  if (deleteButton) deleteButton.disabled = totalSlides <= 1;
  if (restoreButton) restoreButton.disabled = deletedCount <= 0;
}

function setSlideDeleteStatus(message) {
  setEditorStatus('slideDeleteStatus', message);
}

function applySlideSettings(settings = previewSettings) {
  const normalized = normalizeSlideSettings(settings);
  const deleted = new Set(normalized.deletedIds);
  if (!deleted.size && !normalized.scriptLines.length && slides.length === initialSlides.length) {
    updateSlideCounterTotal();
    updateSlideDeleteControls();
    return;
  }

  initialSlides.forEach((slide) => {
    const shouldDelete = deleted.has(slide.dataset.slideId);
    if (shouldDelete && slide.parentNode) {
      pauseVideosInSlide(slide);
      slide.remove();
    } else if (!shouldDelete && !slide.parentNode) {
      const slideInitialIndex = initialSlides.indexOf(slide);
      const nextLiveSlide = initialSlides
        .slice(slideInitialIndex + 1)
        .find(candidate => !deleted.has(candidate.dataset.slideId) && candidate.parentNode === container);
      container.insertBefore(slide, nextLiveSlide || previewSubtitleOverlay || null);
    }
  });

  slides = initialSlides.filter(slide => !deleted.has(slide.dataset.slideId));
  totalSlides = slides.length;
  renumberRuntimeSlides();
  updateSlideCounterTotal();

  const activeIndexes = activeInitialIndexes(normalized.deletedIds);
  const activeScripts = normalized.scriptLines.length === slides.length
    ? normalized.scriptLines
    : (slideScripts.length === initialSlideIds.length
      ? activeIndexes.map(index => slideScripts[index] || initialSlideScripts[index] || '')
      : (slideScripts.length === slides.length ? slideScripts : activeIndexes.map(index => initialSlideScripts[index] || '')));

  const transitionSource = slideTransitions.length === initialSlideIds.length ? slideTransitions : initialSlideTransitions;
  const revealSource = slideReveals.length === initialSlideIds.length ? slideReveals : initialSlideReveals;
  const activeTransitions = normalized.transitionSounds.length === slides.length
    ? normalized.transitionSounds
    : activeIndexes.map(index => transitionSource[index] || initialSlideTransitions[index] || 'minimal');
  const activeReveals = normalized.revealSounds.length === slides.length
    ? normalized.revealSounds
    : activeIndexes.map(index => revealSource[index] || initialSlideReveals[index] || 'ping');
  slideScripts.splice(0, slideScripts.length, ...activeScripts);
  slideTransitions.splice(0, slideTransitions.length, ...activeTransitions);
  slideReveals.splice(0, slideReveals.length, ...activeReveals);
  syncRuntimeSlideSettings();
  previewSubtitleCaptions = slideScripts.map(buildPreviewSubtitleCaptions);
  currentSlide = Math.min(currentSlide, totalSlides - 1);
  if (currentSlide < 0) currentSlide = 0;
  setActiveRuntimeSlide(currentSlide, { revealFirst: !isReady });
}

function applyPreviewSettings(settings = previewSettings) {
  const normalized = normalizePreviewSettings(settings);
  previewSettings = normalized;
  applyThemeSettings(normalized);
  applyVisualSettings(normalized);
  applyBgmSettings(normalized);
  applySubtitleSettings(normalized);
  applySlideSettings(normalized);
}

function restartBackgroundMusic() {
  const shouldRestart = Boolean(bgMusicGain) && !isMuted;
  stopBackgroundMusic(0.25);
  if (shouldRestart) setTimeout(() => startBackgroundMusic(), 320);
}

function setEditorStatus(targetId, message) {
  const status = document.getElementById(targetId);
  if (!status) return;
  status.textContent = message || '';
  status.hidden = !message;
}

function setThemeStatus(message) {
  setEditorStatus('themeEditorStatus', message);
}

function setBgmStatus(message) {
  setEditorStatus('bgmEditorStatus', message);
}

function setSubtitleStatus(message) {
  setEditorStatus('subtitleEditorStatus', message);
}

function setScriptStatus(message) {
  setEditorStatus('scriptEditorStatus', message);
}

function setSlideAudioStatus(message) {
  setEditorStatus('slideAudioEditorStatus', message);
}

function syncRuntimeSlideSettings() {
  previewSettings.slides = {
    ...(previewSettings.slides || {}),
    scriptLines: [...slideScripts],
    transitionSounds: [...slideTransitions],
    revealSounds: [...slideReveals]
  };
}

async function savePreviewSettings(setStatus = setThemeStatus) {
  syncRuntimeSlideSettings();
  const snapshot = JSON.parse(JSON.stringify(previewSettings));
  window.localStorage.setItem(settingsStorageKey(), JSON.stringify(snapshot));
  const project = projectNameFromPath();
  if (!project || !window.location.protocol.startsWith('http')) {
    setStatus('Đã lưu trên trình duyệt');
    return;
  }
  previewSettingsSaveChain = previewSettingsSaveChain.catch(() => {}).then(async () => {
    const response = await fetch('/api/preview-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, settings: snapshot })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    setStatus('Đã lưu preview-settings.json và app.js');
  });
  return previewSettingsSaveChain;
}

async function loadPreviewSettings() {
  const cached = window.localStorage.getItem(settingsStorageKey());
  if (cached) {
    try {
      previewSettings = normalizePreviewSettings(JSON.parse(cached));
      applyPreviewSettings(previewSettings);
    } catch {}
  }

  const project = projectNameFromPath();
  if (!project || !window.location.protocol.startsWith('http')) {
    applyPreviewSettings(previewSettings);
    return;
  }
  try {
    const response = await fetch(`/api/preview-settings?project=${encodeURIComponent(project)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.settings && Object.keys(data.settings).length) {
      previewSettings = normalizePreviewSettings(data.settings);
      window.localStorage.setItem(settingsStorageKey(), JSON.stringify(previewSettings));
      applyPreviewSettings(previewSettings);
    }
  } catch {
    applyPreviewSettings(previewSettings);
  }
}

function readFileDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('Không đọc được file'));
    reader.readAsDataURL(file);
  });
}

async function uploadCustomBgm(file) {
  setBgmStatus('Đang upload...');
  const project = projectNameFromPath();
  if (!project || !window.location.protocol.startsWith('http')) {
    previewSettings.bgm = {
      ...previewSettings.bgm,
      mode: 'custom',
      custom: {
        name: file.name,
        path: '',
        url: URL.createObjectURL(file)
      }
    };
    applyBgmSettings(previewSettings);
    restartBackgroundMusic();
    setBgmStatus('Dùng tạm trong trình duyệt');
    return;
  }

  try {
    const dataUrl = await readFileDataUrl(file);
    const response = await fetch('/api/preview-bgm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project,
        audio: {
          name: file.name,
          type: file.type,
          data: dataUrl
        }
      })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    const data = await response.json();
    previewSettings.bgm = {
      ...previewSettings.bgm,
      mode: 'custom',
      custom: data.audio
    };
    applyBgmSettings(previewSettings);
    restartBackgroundMusic();
    await savePreviewSettings(setBgmStatus);
  } catch (error) {
    setBgmStatus(error.message || 'Không upload được');
  }
}

function applyProjectScript(lines) {
  const activeLines = linesForActiveSlides(lines);
  if (!activeLines || activeLines.length !== totalSlides) return false;
  slideScripts.splice(0, slideScripts.length, ...activeLines);
  syncRuntimeSlideSettings();
  previewSubtitleCaptions = slideScripts.map(buildPreviewSubtitleCaptions);
  updateScriptPanel();
  updateScriptEditor();
  if (!isReady) startPreviewSubtitles(currentSlide);
  return true;
}

async function loadProjectScript() {
  if (hasDeletedSlides() && Array.isArray(previewSettings.slides?.scriptLines) && previewSettings.slides.scriptLines.length === totalSlides) {
    applyProjectScript(previewSettings.slides.scriptLines);
    window.localStorage.setItem(scriptStorageKey(), JSON.stringify(slideScripts));
    return;
  }

  const cached = window.localStorage.getItem(scriptStorageKey());
  if (cached) {
    try {
      applyProjectScript(JSON.parse(cached));
    } catch {}
  }

  const project = projectNameFromPath();
  if (!project || !window.location.protocol.startsWith('http')) return;
  try {
    const response = await fetch(`/api/slide-script?project=${encodeURIComponent(project)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (applyProjectScript(data.lines)) {
      window.localStorage.setItem(scriptStorageKey(), JSON.stringify(slideScripts));
    }
  } catch {}
}

function updateScriptEditor() {
  const badge = document.getElementById('scriptEditorBadge');
  const text = document.getElementById('scriptEditorText');
  if (!badge || !text) return;
  badge.textContent = `Slide ${currentSlide + 1} / ${totalSlides}`;
  text.value = slideScripts[currentSlide] || '';
}

function syncCurrentSlideScriptFromEditor() {
  const text = document.getElementById('scriptEditorText');
  if (!text) return false;
  const nextText = text.value.trim();
  if (!nextText) {
    setScriptStatus('Script không được trống');
    return false;
  }
  slideScripts[currentSlide] = nextText;
  previewSubtitleCaptions[currentSlide] = buildPreviewSubtitleCaptions(nextText);
  const sText = document.getElementById('scriptText');
  if (sText && !isReady) sText.textContent = nextText;
  if (!isReady) startPreviewSubtitles(currentSlide);
  return true;
}

async function persistProjectScript(statusText = 'Đang tự lưu...', options = {}) {
  const {
    allowCountChange = false,
    syncPreviewSettings = hasDeletedSlides(),
    setStatus = setScriptStatus
  } = options;
  window.localStorage.setItem(scriptStorageKey(), JSON.stringify(slideScripts));
  syncRuntimeSlideSettings();
  const project = projectNameFromPath();
  if (!project || !window.location.protocol.startsWith('http')) {
    if (syncPreviewSettings) await savePreviewSettings(setStatus);
    setStatus('Đã lưu trên trình duyệt');
    return;
  }
  setStatus(statusText);
  const payload = { project, lines: slideScripts };
  if (allowCountChange) payload.allowCountChange = true;
  const response = await fetch('/api/slide-script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  if (syncPreviewSettings) await savePreviewSettings(setStatus);
  setStatus('Đã lưu script-90s.txt, preview-settings.json, app.js và upload-metadata');
}

function queueScriptAutoSave() {
  if (!syncCurrentSlideScriptFromEditor()) return;
  setScriptStatus('Sẽ tự lưu...');
  if (scriptAutoSaveTimer) clearTimeout(scriptAutoSaveTimer);
  scriptAutoSaveTimer = setTimeout(async () => {
    try {
      await persistProjectScript();
    } catch (error) {
      setScriptStatus(error.message || 'Không tự lưu được');
    }
  }, 700);
}

async function saveCurrentSlideScript() {
  if (scriptAutoSaveTimer) clearTimeout(scriptAutoSaveTimer);
  if (!syncCurrentSlideScriptFromEditor()) return;
  const project = projectNameFromPath();
  if (!project || !window.location.protocol.startsWith('http')) {
    window.localStorage.setItem(scriptStorageKey(), JSON.stringify(slideScripts));
    setScriptStatus('Đã tự lưu trên trình duyệt');
    return;
  }
  try {
    await persistProjectScript('Đang lưu...');
  } catch (error) {
    setScriptStatus(error.message || 'Không lưu được');
  }
}

async function deleteCurrentSlide() {
  if (totalSlides <= 1) {
    setSlideDeleteStatus('Không thể xoá slide cuối cùng.');
    return;
  }
  const slide = slides[currentSlide];
  if (!slide) return;
  const slideNumber = currentSlide + 1;
  const confirmed = window.confirm(`Xoá slide ${slideNumber} khỏi preview?\n\nHành động này sẽ cập nhật script-90s.txt, preview-settings và app.js.`);
  if (!confirmed) return;

  if (scriptAutoSaveTimer) clearTimeout(scriptAutoSaveTimer);
  syncCurrentSlideScriptFromEditor();
  const deletedId = slide.dataset.slideId || slide.dataset.slide || String(currentSlide);
  const deletedIds = Array.from(new Set([...(previewSettings.slides?.deletedIds || []), deletedId]));
  const nextScripts = slideScripts.filter((_, index) => index !== currentSlide);
  const nextSlideIndex = Math.min(currentSlide, totalSlides - 2);

  previewSettings.slides = {
    ...(previewSettings.slides || {}),
    deletedIds,
    scriptLines: nextScripts
  };

  isReady = false;
  setSlideDeleteStatus('Đang xoá...');
  applyPreviewSettings(previewSettings);
  setActiveRuntimeSlide(nextSlideIndex, { revealFirst: true });
  window.localStorage.setItem(scriptStorageKey(), JSON.stringify(slideScripts));

  try {
    await persistProjectScript('Đang lưu script-90s.txt...', {
      allowCountChange: true,
      syncPreviewSettings: true,
      setStatus: setSlideDeleteStatus
    });
    setSlideDeleteStatus(`Đã xoá slide ${slideNumber} trong preview.`);
  } catch (error) {
    setSlideDeleteStatus(error.message || 'Đã xoá trong phiên này, nhưng chưa lưu được.');
  }
}

async function restoreDeletedSlide() {
  const deletedIds = [...(previewSettings.slides?.deletedIds || [])];
  if (!deletedIds.length) {
    setSlideDeleteStatus('Chưa có slide nào để khôi phục.');
    return;
  }

  if (scriptAutoSaveTimer) clearTimeout(scriptAutoSaveTimer);
  syncCurrentSlideScriptFromEditor();

  const restoredId = String(deletedIds[deletedIds.length - 1]);
  const currentActiveIds = activeInitialIds(deletedIds);
  const scriptBySlideId = new Map(currentActiveIds.map((id, index) => [id, slideScripts[index] || initialSlideScripts[initialSlideIds.indexOf(id)] || '']));
  const nextDeletedIds = deletedIds.filter(id => id !== restoredId);
  const nextActiveIds = activeInitialIds(nextDeletedIds);
  const nextScripts = nextActiveIds.map((id) => (
    id === restoredId
      ? initialSlideScripts[initialSlideIds.indexOf(id)] || ''
      : scriptBySlideId.get(id) || initialSlideScripts[initialSlideIds.indexOf(id)] || ''
  ));
  const restoredIndex = nextActiveIds.indexOf(restoredId);

  previewSettings.slides = {
    ...(previewSettings.slides || {}),
    deletedIds: nextDeletedIds,
    scriptLines: nextScripts
  };

  isReady = false;
  setSlideDeleteStatus('Đang khôi phục...');
  applyPreviewSettings(previewSettings);
  setActiveRuntimeSlide(restoredIndex >= 0 ? restoredIndex : currentSlide, { revealFirst: true });
  window.localStorage.setItem(scriptStorageKey(), JSON.stringify(slideScripts));

  try {
    await persistProjectScript('Đang lưu script-90s.txt...', {
      allowCountChange: true,
      syncPreviewSettings: true,
      setStatus: setSlideDeleteStatus
    });
    setSlideDeleteStatus(`Đã khôi phục slide ${initialSlideIds.indexOf(restoredId) + 1}.`);
  } catch (error) {
    setSlideDeleteStatus(error.message || 'Đã khôi phục trong phiên này, nhưng chưa lưu được.');
  }
}

function setupThemeEditor() {
  if (themeEditorPanel) return;
  themeEditorPanel = document.createElement('div');
  themeEditorPanel.className = 'theme-editor-panel';
  themeEditorPanel.innerHTML = `
    <div class="theme-editor-title"><i class="fa-solid fa-sliders"></i><span>Preview Editor</span></div>
    <div class="theme-editor-section theme-editor-section-theme">
      <div class="theme-editor-section-title">Tone màu</div>
      <label class="theme-editor-field">
        <span>Preset</span>
        <select id="themePresetSelect">
          ${Object.entries(themePresets).map(([key, preset]) => `<option value="${key}">${preset.label}</option>`).join('')}
        </select>
      </label>
      <div class="theme-editor-swatches" id="themeEditorSwatches"></div>
      <div class="theme-editor-mini-row">
        <label class="theme-editor-check theme-editor-mini-check">
          <input id="gridEnabled" type="checkbox" />
          <span>Lưới</span>
        </label>
        <label class="theme-editor-field theme-editor-mini-select">
          <span>Animation nền</span>
          <select id="backgroundFxSelect">
            ${Object.entries(backgroundFxOptions).map(([key, label]) => `<option value="${key}">${label}</option>`).join('')}
          </select>
        </label>
      </div>
    </div>
    <div class="theme-editor-section theme-editor-section-bgm">
      <div class="theme-editor-section-title">Nhạc nền</div>
      <label class="theme-editor-field">
        <span>BGM</span>
        <select id="editorBgmSelect">
          <option value="ambient">Ambient</option>
          <option value="cinematic">Cinematic</option>
          <option value="lofi">Lo-fi</option>
          <option value="piano">Piano</option>
          <option value="dark">Dark</option>
          <option value="custom">Custom upload</option>
          <option value="none">Tắt</option>
        </select>
      </label>
      <label class="theme-editor-field">
        <span>Volume <b id="bgmVolumeValue">12%</b></span>
        <input id="bgmVolume" type="range" min="0" max="0.3" step="0.01" />
      </label>
      <label class="theme-editor-upload">
        <input id="bgmUpload" type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg" />
        <span><i class="fa-solid fa-upload"></i> Upload BGM</span>
      </label>
      <div class="theme-editor-file" id="bgmCustomName">Chưa upload file</div>
      <div class="theme-editor-status" id="bgmEditorStatus" hidden></div>
    </div>
    <div class="theme-editor-section theme-editor-section-audio">
      <div class="theme-editor-section-title">Âm thanh slide</div>
      <div class="audio-slide-header editor-audio-slide-header">
        <span class="audio-slide-badge" id="editorAudioPanelSlide">Ready</span>
        <div class="audio-slide-nav">
          <button class="audio-nav-btn" type="button" onclick="audioPanelPrev()"><i class="fa-solid fa-chevron-left"></i></button>
          <button class="audio-nav-btn" type="button" onclick="audioPanelNext()"><i class="fa-solid fa-chevron-right"></i></button>
        </div>
      </div>
      <label class="theme-editor-field">
        <span>Chuyển slide</span>
        <select id="editorTransitionSelect" onchange="setSlideTransition(currentSlide, this.value)">
          <option value="gong">Gong</option>
          <option value="rise">Rise</option>
          <option value="bass">Bass</option>
          <option value="chime">Chime</option>
          <option value="sweep">Sweep</option>
          <option value="boom">Boom</option>
          <option value="alarm">Alarm</option>
          <option value="chord">Chord</option>
          <option value="ascending">Ascending</option>
          <option value="retro">Retro</option>
          <option value="minimal">Minimal</option>
          <option value="dramatic">Dramatic</option>
        </select>
      </label>
      <label class="theme-editor-field">
        <span>Hiện element</span>
        <select id="editorRevealSelect" onchange="setSlideReveal(currentSlide, this.value)">
          <option value="ping">Ping</option>
          <option value="pop">Pop</option>
          <option value="chime">Chime</option>
          <option value="click">Click</option>
          <option value="bubble">Bubble</option>
          <option value="woosh">Woosh</option>
          <option value="sparkle">Sparkle</option>
          <option value="drop">Drop</option>
          <option value="tick">Tick</option>
          <option value="bell">Bell</option>
          <option value="blip">Blip</option>
          <option value="snap">Snap</option>
        </select>
      </label>
      <div class="theme-editor-actions">
        <button class="theme-editor-ghost-button" type="button" onclick="testTransition()">Test slide</button>
        <button class="theme-editor-ghost-button" type="button" onclick="testReveal()">Test reveal</button>
      </div>
      <div class="theme-editor-status" id="slideAudioEditorStatus" hidden></div>
    </div>
    <div class="theme-editor-section theme-editor-section-subtitles">
      <div class="theme-editor-section-title">Phụ đề</div>
      <label class="theme-editor-check">
        <input id="subtitleEnabled" type="checkbox" />
        <span>Bật subtitle</span>
      </label>
      <label class="theme-editor-field">
        <span>Màu chữ</span>
        <input id="subtitleColor" type="color" />
      </label>
      <label class="theme-editor-field">
        <span>Cỡ chữ <b id="subtitleFontSizeValue">18px</b></span>
        <input id="subtitleFontSize" type="range" min="12" max="28" step="1" />
      </label>
      <label class="theme-editor-field">
        <span>Vị trí đáy <b id="subtitleBottomValue">152px</b></span>
        <input id="subtitleBottom" type="range" min="40" max="180" step="4" />
      </label>
      <div class="theme-editor-status" id="subtitleEditorStatus" hidden></div>
      <div class="theme-editor-divider"></div>
      <div class="theme-editor-file" id="slideDeleteBadge">Slide 1 / ${totalSlides}</div>
      <div class="theme-editor-slide-actions">
        <button class="theme-editor-danger-button" type="button" id="deleteSlideBtn">
          <i class="fa-solid fa-trash"></i> Xoá slide
        </button>
        <button class="theme-editor-restore-button" type="button" id="restoreSlideBtn">
          <i class="fa-solid fa-rotate-left"></i> Khôi phục
        </button>
      </div>
      <div class="theme-editor-status" id="slideDeleteStatus" hidden></div>
    </div>
    <div class="theme-editor-section theme-editor-section-script">
      <div class="theme-editor-section-title">Script</div>
      <div class="theme-editor-file" id="scriptEditorBadge">Slide 1</div>
      <textarea id="scriptEditorText" class="script-editor-text" rows="8"></textarea>
      <div class="script-editor-hint">Tự lưu sau khi dừng gõ.</div>
      <div class="theme-editor-status" id="scriptEditorStatus" hidden></div>
    </div>
    <div class="theme-editor-status" id="themeEditorStatus" hidden></div>
  `;
  document.body.appendChild(themeEditorPanel);

  const select = document.getElementById('themePresetSelect');
  select.addEventListener('change', async () => {
    const preset = select.value;
    const customVariables = storedCustomThemeVariables(previewSettings);
    const customVisuals = storedCustomVisualSettings(previewSettings);
    const variables = preset === 'custom'
      ? { ...customVariables }
      : { ...themePresets[preset].variables };
    const visualColors = preset === 'custom'
      ? { ...customVisuals }
      : {
        backgroundColor: variables['--bg-dark'] || previewSettings.visuals?.backgroundColor,
        gridLight: variables['--accent'] || previewSettings.visuals?.gridLight,
        iconGlow: variables['--primary'] || previewSettings.visuals?.iconGlow,
        iconBacklight: variables['--accent'] || previewSettings.visuals?.iconBacklight,
        iconLight: variables['--success'] || previewSettings.visuals?.iconLight
      };
    previewSettings.theme = {
      preset,
      variables,
      customVariables
    };
    previewSettings.visuals = {
      ...previewSettings.visuals,
      ...visualColors,
      customValues: customVisuals
    };
    applyPreviewSettings(previewSettings);
    setThemeStatus('Đang lưu...');
    try {
      await savePreviewSettings();
    } catch (error) {
      setThemeStatus(error.message || 'Không lưu được');
    }
  });

  const swatches = document.getElementById('themeEditorSwatches');
  swatches.addEventListener('input', (event) => {
    const input = event.target;
    if (!input.matches('[data-preview-color-key]')) return;
    setPreviewColor(input.dataset.previewColorKey, input.dataset.previewColorType, input.value, input);
  });
  swatches.addEventListener('change', (event) => {
    if (event.target.matches('[data-preview-color-key]')) savePreviewColorSettings();
  });

  const gridEnabled = document.getElementById('gridEnabled');
  gridEnabled.addEventListener('change', () => {
    previewSettings.visuals = {
      ...previewSettings.visuals,
      gridEnabled: gridEnabled.checked
    };
    applyVisualSettings(previewSettings);
    savePreviewColorSettings();
  });

  const backgroundFxSelect = document.getElementById('backgroundFxSelect');
  backgroundFxSelect.addEventListener('change', () => {
    previewSettings.visuals = {
      ...previewSettings.visuals,
      backgroundFx: backgroundFxSelect.value
    };
    applyVisualSettings(previewSettings);
    savePreviewColorSettings();
  });

  const editorBgmSelect = document.getElementById('editorBgmSelect');
  editorBgmSelect.addEventListener('change', () => switchBGM(editorBgmSelect.value));

  const bgmVolume = document.getElementById('bgmVolume');
  bgmVolume.addEventListener('input', () => {
    previewSettings.bgm = {
      ...previewSettings.bgm,
      volume: Number(bgmVolume.value)
    };
    applyBgmSettings(previewSettings);
  });
  bgmVolume.addEventListener('change', async () => {
    setBgmStatus('Đang lưu...');
    try {
      await savePreviewSettings(setBgmStatus);
    } catch (error) {
      setBgmStatus(error.message || 'Không lưu được');
    }
  });

  const bgmUpload = document.getElementById('bgmUpload');
  bgmUpload.addEventListener('change', async () => {
    const file = bgmUpload.files && bgmUpload.files[0];
    if (!file) return;
    await uploadCustomBgm(file);
    bgmUpload.value = '';
  });

  const subtitleEnabled = document.getElementById('subtitleEnabled');
  const subtitleColor = document.getElementById('subtitleColor');
  const subtitleFontSize = document.getElementById('subtitleFontSize');
  const subtitleBottom = document.getElementById('subtitleBottom');
  const saveSubtitleSettings = async () => {
    setSubtitleStatus('Đang lưu...');
    try {
      await savePreviewSettings(setSubtitleStatus);
    } catch (error) {
      setSubtitleStatus(error.message || 'Không lưu được');
    }
  };
  subtitleEnabled.addEventListener('change', () => {
    previewSettings.subtitles = {
      ...previewSettings.subtitles,
      enabled: subtitleEnabled.checked
    };
    applySubtitleSettings(previewSettings);
    saveSubtitleSettings();
  });
  subtitleColor.addEventListener('input', () => {
    previewSettings.subtitles = {
      ...previewSettings.subtitles,
      color: subtitleColor.value
    };
    applySubtitleSettings(previewSettings);
  });
  subtitleColor.addEventListener('change', saveSubtitleSettings);
  subtitleFontSize.addEventListener('input', () => {
    previewSettings.subtitles = {
      ...previewSettings.subtitles,
      fontSize: Number(subtitleFontSize.value)
    };
    applySubtitleSettings(previewSettings);
  });
  subtitleFontSize.addEventListener('change', saveSubtitleSettings);
  subtitleBottom.addEventListener('input', () => {
    previewSettings.subtitles = {
      ...previewSettings.subtitles,
      bottom: Number(subtitleBottom.value)
    };
    applySubtitleSettings(previewSettings);
  });
  subtitleBottom.addEventListener('change', saveSubtitleSettings);

  const scriptEditorText = document.getElementById('scriptEditorText');
  scriptEditorText.addEventListener('input', queueScriptAutoSave);
  const scriptSaveBtn = document.getElementById('scriptSaveBtn');
  if (scriptSaveBtn) scriptSaveBtn.addEventListener('click', saveCurrentSlideScript);
  const deleteSlideBtn = document.getElementById('deleteSlideBtn');
  if (deleteSlideBtn) deleteSlideBtn.addEventListener('click', deleteCurrentSlide);
  const restoreSlideBtn = document.getElementById('restoreSlideBtn');
  if (restoreSlideBtn) restoreSlideBtn.addEventListener('click', restoreDeletedSlide);

  applyPreviewSettings(previewSettings);
  updateScriptEditor();
  updateSlideDeleteControls();
  renderThemeSwatches();
}

function previewControlColor(control, vars, visuals) {
  return control.type === 'theme' ? vars[control.key] : visuals[control.key];
}

function renderThemeSwatches() {
  const wrap = document.getElementById('themeEditorSwatches');
  if (!wrap) return;
  const vars = previewSettings.theme.variables;
  const visuals = previewSettings.visuals || defaultPreviewSettings.visuals;
  wrap.innerHTML = previewColorControls.map((control) => {
    const color = previewControlColor(control, vars, visuals) || '#000000';
    return `<label class="theme-editor-swatch" title="${control.label}" aria-label="${control.label}">
      <input type="color" value="${color}" data-preview-color-key="${control.key}" data-preview-color-type="${control.type}" />
      <span style="background:${color}"></span>
    </label>`;
  }).join('');
}

function setPreviewColor(key, type, value, input) {
  if (!isHexColor(value)) return;
  const customVariables = storedCustomThemeVariables(previewSettings);
  const customVisuals = storedCustomVisualSettings(previewSettings);
  if (type === 'theme') {
    const nextCustomVariables = {
      ...customVariables,
      [key]: value
    };
    const nextCustomVisuals = { ...customVisuals };
    if (key === '--bg-dark') nextCustomVisuals.backgroundColor = value;
    previewSettings.theme = {
      preset: 'custom',
      variables: nextCustomVariables,
      customVariables: nextCustomVariables
    };
    previewSettings.visuals = {
      ...previewSettings.visuals,
      ...(key === '--bg-dark' ? { backgroundColor: value } : {}),
      customValues: nextCustomVisuals
    };
  } else {
    const nextCustomVisuals = {
      ...customVisuals,
      [key]: value
    };
    const nextCustomVariables = key === 'backgroundColor'
      ? { ...customVariables, '--bg-dark': value }
      : customVariables;
    previewSettings.theme = {
      preset: 'custom',
      variables: nextCustomVariables,
      customVariables: nextCustomVariables
    };
    previewSettings.visuals = {
      ...previewSettings.visuals,
      [key]: value,
      customValues: nextCustomVisuals
    };
  }
  previewSettings = normalizePreviewSettings(previewSettings);
  Object.entries(previewSettings.theme.variables).forEach(([name, color]) => {
    document.documentElement.style.setProperty(name, color);
  });
  applyVisualSettings(previewSettings);
  if (input?.nextElementSibling) input.nextElementSibling.style.background = value;
  const presetSelect = document.getElementById('themePresetSelect');
  if (presetSelect) presetSelect.value = previewSettings.theme.preset;
}

async function savePreviewColorSettings() {
  setThemeStatus('Đang lưu...');
  try {
    await savePreviewSettings();
  } catch (error) {
    setThemeStatus(error.message || 'Không lưu được');
  }
}

// ============================================
// AUDIO ENGINE
// ============================================
function initAudio() {
  if (audioCtx) {
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
    return;
  }
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
  } catch (e) {
    console.warn('[audio] Web Audio Context init failed', e);
  }
}

function playTone(type, freqStart, freqEnd, delay, fadeInTime, vol, duration, Q) {
  if (!audioCtx || isMuted) return;
  const t = audioCtx.currentTime + delay;
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  const filter = audioCtx.createBiquadFilter();
  filter.type = 'lowpass';
  filter.frequency.value = 3000;
  if (Q) filter.Q.value = Q;
  osc.type = type;
  osc.frequency.setValueAtTime(freqStart, t);
  if (freqEnd !== freqStart) osc.frequency.exponentialRampToValueAtTime(freqEnd, t + duration);
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(vol, t + fadeInTime);
  gain.gain.exponentialRampToValueAtTime(0.001, t + duration);
  osc.connect(filter); filter.connect(gain); gain.connect(audioCtx.destination);
  osc.start(t); osc.stop(t + duration + 0.05);
}

function playNoiseWhoosh(freqStart, freqEnd, duration) {
  if (!audioCtx || isMuted) return;
  const t = audioCtx.currentTime;
  const noise = createNoiseBuffer(duration + 0.1);
  const src = audioCtx.createBufferSource();
  src.buffer = noise;
  const filter = audioCtx.createBiquadFilter();
  filter.type = 'bandpass';
  filter.frequency.setValueAtTime(freqStart, t);
  filter.frequency.exponentialRampToValueAtTime(freqEnd, t + duration);
  filter.Q.value = 0.8;
  const gain = audioCtx.createGain();
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(0.04, t + 0.04);
  gain.gain.exponentialRampToValueAtTime(0.001, t + duration);
  src.connect(filter); filter.connect(gain); gain.connect(audioCtx.destination);
  src.start(t); src.stop(t + duration + 0.1);
}

function createNoiseBuffer(duration) {
  const sampleRate = audioCtx.sampleRate;
  const length = sampleRate * duration;
  const buffer = audioCtx.createBuffer(1, length, sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < length; i++) data[i] = (Math.random() * 2 - 1) * 0.5;
  return buffer;
}

// ============================================
// 12 TRANSITION SOUNDS
// ============================================
const transitionLib = {
  gong() { playTone('sine', 130, 260, 0, 0.6, 0.09, 0.8); playTone('triangle', 260, 520, 0.08, 0.4, 0.06, 0.6); playNoiseWhoosh(400, 1200, 0.35); },
  rise() { playTone('sine', 220, 440, 0, 0.5, 0.08, 0.6); playTone('triangle', 330, 660, 0.1, 0.35, 0.05, 0.5); },
  bass() { playTone('sine', 65, 55, 0, 0.12, 0.07, 0.7); playTone('triangle', 130, 110, 0.1, 0.08, 0.05, 0.5); playTone('sine', 65, 55, 0.35, 0.10, 0.06, 0.5); },
  chime() { playTone('sine', 880, 1320, 0, 0.6, 0.07, 0.5); playTone('sine', 1100, 880, 0.1, 0.4, 0.04, 0.4); },
  sweep() { playTone('sine', 440, 880, 0, 0.5, 0.07, 0.55); playNoiseWhoosh(600, 3000, 0.3); playTone('triangle', 660, 880, 0.12, 0.3, 0.04, 0.4); },
  boom() { playTone('sine', 80, 60, 0, 0.15, 0.09, 0.8); playTone('sine', 160, 120, 0.05, 0.12, 0.06, 0.6); playNoiseWhoosh(200, 600, 0.4); },
  alarm() { playTone('sawtooth', 370, 185, 0, 0.04, 0.07, 0.25, 2.5); playTone('sawtooth', 370, 185, 0.15, 0.04, 0.07, 0.25, 2.5); playNoiseWhoosh(1500, 3500, 0.2); },
  chord() { playTone('sine', 440, 440, 0, 0.55, 0.06, 0.7); playTone('sine', 554, 554, 0.06, 0.45, 0.05, 0.6); playTone('sine', 660, 660, 0.12, 0.4, 0.04, 0.55); playTone('sine', 880, 880, 0.2, 0.3, 0.03, 0.5); },
  ascending() { playTone('sine', 330, 440, 0, 0.5, 0.06, 0.4); playTone('sine', 440, 554, 0.15, 0.4, 0.05, 0.4); playTone('sine', 554, 660, 0.3, 0.35, 0.04, 0.4); },
  retro() { playTone('square', 262, 131, 0, 0.15, 0.03, 0.15, 2); playTone('square', 393, 262, 0.08, 0.12, 0.03, 0.15, 2); playNoiseWhoosh(2000, 500, 0.1); },
  minimal() { playTone('sine', 523, 784, 0, 0.4, 0.04, 0.3); },
  dramatic() { playTone('sine', 110, 55, 0, 0.15, 0.1, 1.0); playNoiseWhoosh(100, 400, 0.6); playTone('sine', 220, 440, 0.3, 0.5, 0.07, 0.6); }
};

// ============================================
// 12 REVEAL SOUNDS
// ============================================
const revealLib = {
  ping() { playTone('sine', 1000, 1400, 0, 0.03, 0.06, 0.18); },
  pop() { playTone('sine', 800, 1200, 0, 0.02, 0.06, 0.15); playTone('sine', 1200, 600, 0, 0.02, 0.03, 0.12); },
  chime() { playTone('sine', 1200, 1800, 0, 0.02, 0.05, 0.3); playTone('sine', 1500, 2000, 0.06, 0.02, 0.03, 0.25); },
  click() { playTone('triangle', 2000, 800, 0, 0.01, 0.07, 0.06); },
  bubble() { const b = 400 + Math.random() * 400; playTone('sine', b, b * 2, 0, 0.02, 0.05, 0.2); playTone('sine', b * 1.3, b * 2.5, 0.05, 0.02, 0.03, 0.15); },
  woosh() { playNoiseWhoosh(800 + Math.random() * 400, 2000 + Math.random() * 1000, 0.15); },
  sparkle() { playTone('sine', 1500, 2200, 0, 0.02, 0.04, 0.2); playTone('sine', 2000, 2800, 0.04, 0.02, 0.03, 0.18); playTone('sine', 2500, 1800, 0.08, 0.02, 0.02, 0.15); },
  drop() { playTone('sine', 1400, 400, 0, 0.02, 0.06, 0.2); },
  tick() { playTone('triangle', 3000, 1500, 0, 0.01, 0.05, 0.05); },
  bell() { playTone('sine', 880, 1100, 0, 0.02, 0.05, 0.35); playTone('sine', 1100, 880, 0.08, 0.02, 0.03, 0.3); },
  blip() { playTone('square', 600, 900, 0, 0.02, 0.03, 0.08, 3); },
  snap() { playTone('triangle', 4000, 500, 0, 0.01, 0.06, 0.04); playNoiseWhoosh(3000, 1000, 0.05); }
};

// ============================================
// PLAY DISPATCHER
// ============================================
function playSlideSound(slideIndex) {
  if (!audioCtx || isMuted) return;
  const key = slideTransitions[slideIndex] || 'minimal';
  if (transitionLib[key]) transitionLib[key]();
}

function playRevealSound() {
  if (!audioCtx || isMuted) return;
  const key = slideReveals[currentSlide] || 'ping';
  if (revealLib[key]) revealLib[key]();
}

// ============================================
// BACKGROUND MUSIC
// ============================================
let bgChordIndex = 0;
let bgArpInterval = null;
let bgChordInterval = null;

const chordProgression = [
  [130.81, 164.81, 196.00, 246.94],
  [110.00, 130.81, 164.81, 196.00],
  [87.31, 130.81, 164.81, 207.65],
  [98.00, 123.47, 146.83, 174.61],
];

const arpNotes = [
  [523.25, 659.25, 783.99, 987.77],
  [440.00, 523.25, 659.25, 783.99],
  [349.23, 523.25, 659.25, 830.61],
  [392.00, 493.88, 587.33, 698.46],
];

function startBackgroundMusic() {
  if (!audioCtx || isMuted) return;
  if (bgMusicGain) return;
  const bgm = normalizeBgmSettings(previewSettings);
  if (bgm.mode === 'none') return;
  bgMusicGain = audioCtx.createGain();
  bgMusicGain.gain.setValueAtTime(0, audioCtx.currentTime);
  bgMusicGain.gain.linearRampToValueAtTime(bgm.volume, audioCtx.currentTime + 4);
  bgMusicGain.connect(audioCtx.destination);
  if (bgm.mode === 'custom' && startCustomBackgroundMusic(bgm)) return;
  bgChordIndex = 0;
  playChord();
  bgChordInterval = setInterval(() => {
    bgChordIndex = (bgChordIndex + 1) % chordProgression.length;
    playChord();
  }, 8000);
  playArpNote();
  bgArpInterval = setInterval(playArpNote, 2000);
}

function resolveCustomBgmUrls(bgm) {
  const preferred = (bgm && bgm.custom && (bgm.custom.path || bgm.custom.url)) || '';
  const list = [
    preferred,
    'preview-assets/bgm/Write_You.mp3',
    '../gold-macro-bias-template/preview-assets/bgm/Write_You.mp3',
    '../../assets/Write_You.mp3',
    '/assets/Write_You.mp3',
    'preview-assets/bgm/20261026-144800_Write_You.mp3',
    'preview-assets/bgm/20261019-141818_Write_You.mp3'
  ].filter(Boolean);
  return [...new Set(list)];
}

function startCustomBackgroundMusic(bgm) {
  const urls = resolveCustomBgmUrls(bgm);
  if (!urls.length) return false;

  let urlIndex = 0;
  function tryPlayUrl(url) {
    if (!audioCtx || isMuted) return;
    try {
      if (customBgmAudio) {
        try { customBgmAudio.pause(); } catch (_) {}
      }
      customBgmAudio = new Audio(url);
      customBgmAudio.loop = true;
      customBgmAudio.preload = 'auto';
      customBgmAudio.volume = 1;
      if (bgMusicSource) {
        try { bgMusicSource.disconnect(); } catch (_) {}
      }
      bgMusicSource = audioCtx.createMediaElementSource(customBgmAudio);
      bgMusicSource.connect(bgMusicGain);
      customBgmAudio.currentTime = 0;
      const p = customBgmAudio.play();
      if (p) {
        p.catch(() => {
          urlIndex++;
          if (urlIndex < urls.length) {
            tryPlayUrl(urls[urlIndex]);
          } else {
            console.warn('[audio] Custom BGM files not accessible, falling back to ambient synth');
            stopBackgroundMusic(0.1);
            if (!audioCtx || isMuted) return;
            bgMusicGain = audioCtx.createGain();
            bgMusicGain.gain.setValueAtTime(0, audioCtx.currentTime);
            bgMusicGain.gain.linearRampToValueAtTime(bgm.volume || 0.18, audioCtx.currentTime + 3);
            bgMusicGain.connect(audioCtx.destination);
            bgChordIndex = 0;
            playChord();
            bgChordInterval = setInterval(() => {
              bgChordIndex = (bgChordIndex + 1) % chordProgression.length;
              playChord();
            }, 8000);
            playArpNote();
            bgArpInterval = setInterval(playArpNote, 2000);
          }
        });
      }
    } catch (e) {
      urlIndex++;
      if (urlIndex < urls.length) {
        tryPlayUrl(urls[urlIndex]);
      }
    }
  }

  tryPlayUrl(urls[0]);
  return true;
}

function playChord() {
  if (!audioCtx || !bgMusicGain || isMuted) return;
  const chord = chordProgression[bgChordIndex];
  chord.forEach((freq, i) => {
    const osc1 = audioCtx.createOscillator();
    const osc2 = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    const filter = audioCtx.createBiquadFilter();
    osc1.type = 'sine'; osc1.frequency.value = freq;
    osc2.type = 'triangle'; osc2.frequency.value = freq * 1.003;
    filter.type = 'lowpass'; filter.frequency.value = 350 + i * 50; filter.Q.value = 0.5;
    const t = audioCtx.currentTime;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.18, t + 2);
    gain.gain.setValueAtTime(0.18, t + 5);
    gain.gain.linearRampToValueAtTime(0.001, t + 8);
    osc1.connect(gain); osc2.connect(gain); gain.connect(filter); filter.connect(bgMusicGain);
    osc1.start(t + i * 0.15); osc2.start(t + i * 0.15);
    osc1.stop(t + 8.5); osc2.stop(t + 8.5);
  });
}

let arpNoteIndex = 0;
function playArpNote() {
  if (!audioCtx || !bgMusicGain || isMuted) return;
  const notes = arpNotes[bgChordIndex];
  const note = notes[arpNoteIndex % notes.length];
  arpNoteIndex++;
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  const filter = audioCtx.createBiquadFilter();
  const delay = audioCtx.createDelay(1.0);
  const delayGain = audioCtx.createGain();
  osc.type = 'sine'; osc.frequency.value = note;
  filter.type = 'lowpass'; filter.frequency.value = 2000; filter.Q.value = 0.3;
  const t = audioCtx.currentTime;
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(0.12, t + 0.05);
  gain.gain.exponentialRampToValueAtTime(0.03, t + 0.8);
  gain.gain.linearRampToValueAtTime(0.001, t + 2.5);
  delay.delayTime.value = 0.375; delayGain.gain.value = 0.25;
  osc.connect(filter); filter.connect(gain); gain.connect(bgMusicGain);
  gain.connect(delay); delay.connect(delayGain); delayGain.connect(bgMusicGain);
  osc.start(t); osc.stop(t + 3);
}

function stopBackgroundMusic(fadeOut = 1) {
  if (bgChordInterval) { clearInterval(bgChordInterval); bgChordInterval = null; }
  if (bgArpInterval) { clearInterval(bgArpInterval); bgArpInterval = null; }
  if (customBgmAudio) {
    customBgmAudio.pause();
    customBgmAudio.currentTime = 0;
    customBgmAudio = null;
  }
  if (bgMusicSource) {
    try { bgMusicSource.disconnect(); } catch {}
    bgMusicSource = null;
  }
  if (bgMusicGain) {
    const gainNode = bgMusicGain;
    bgMusicGain = null;
    gainNode.gain.cancelScheduledValues(audioCtx.currentTime);
    gainNode.gain.setValueAtTime(gainNode.gain.value, audioCtx.currentTime);
    gainNode.gain.linearRampToValueAtTime(0, audioCtx.currentTime + fadeOut);
    setTimeout(() => {
      try { gainNode.disconnect(); } catch {}
    }, fadeOut * 1000 + 120);
  }
}

function toggleMute() {
  isMuted = !isMuted;
  const muteBtn = document.getElementById('muteBtn');
  if (isMuted) {
    muteBtn.innerHTML = '<i class="fa-solid fa-volume-xmark"></i>';
    stopBackgroundMusic();
  } else {
    muteBtn.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
    initAudio();
    startBackgroundMusic();
  }
}

// ============================================
// SLIDE NAVIGATION
// ============================================
function init() {
  resetToStart();
  if (window.__PREVIEW_SETTINGS__) {
    applyPreviewSettings(window.__PREVIEW_SETTINGS__);
  }
  if (!window.__RENDER_MODE__) {
    setupThemeEditor();
    loadPreviewSettings().then(() => loadProjectScript());
  }
  container.addEventListener('click', handleClick);
  document.addEventListener('keydown', handleKeyboard);
  let touchStartX = 0, touchStartY = 0;
  container.addEventListener('touchstart', (e) => {
    touchStartX = e.touches[0].clientX; touchStartY = e.touches[0].clientY;
  }, { passive: true });
  container.addEventListener('touchend', (e) => {
    const dx = e.changedTouches[0].clientX - touchStartX;
    const dy = e.changedTouches[0].clientY - touchStartY;
    if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 40) {
      if (dx < 0) nextSlide(); else prevSlide();
    }
  }, { passive: true });
  updateAudioPanel();
}

function handleClick(e) {
  initAudio();
  if (!bgMusicGain && !isMuted) startBackgroundMusic();
  if (e.target.closest('.side-controls')) return;
  if (isReady) {
    isReady = false;
    updateProgress();
    updateAudioPanel();
    playSlideSound(0);
    const firstEl = slides[0].querySelector('.slide-element');
    if (firstEl && !firstEl.classList.contains('visible')) {
      firstEl.classList.add('visible');
      playVideosInElement(firstEl);
      createParticleBurst(firstEl);
      triggerShimmer(slides[0].querySelector('.title-shimmer'));
      playRevealSound();
      startPreviewSubtitles(0);
    }
    return;
  }
  const slide = slides[currentSlide];
  const mode = slide.dataset.mode;
  if (mode === 'highlight') {
    const elements = slide.querySelectorAll('.slide-element');
    const hidden = Array.from(elements).filter(el => !el.classList.contains('visible'));
    if (hidden.length > 0) { revealNextElement(); return; }
    const cards = slide.querySelectorAll('.highlightable');
    const highlighted = slide.querySelectorAll('.highlighted');
    if (highlighted.length < cards.length) {
      cards[highlighted.length].classList.add('highlighted');
      playRevealSound(); createParticleBurst(cards[highlighted.length]); return;
    }
    nextSlide(); return;
  }
  if (mode === 'traffic-light') {
    const elements = slide.querySelectorAll('.slide-element');
    const hidden = Array.from(elements).filter(el => !el.classList.contains('visible'));
    if (hidden.length > 0) { revealNextElement(); return; }
    const dots = slide.querySelectorAll('.lightable');
    const lit = slide.querySelectorAll('.lightable[class*="lit-"]');
    if (lit.length < dots.length) {
      const color = dots[lit.length].dataset.lightColor;
      dots[lit.length].classList.add('lit-' + color);
      playRevealSound(); createParticleBurst(dots[lit.length]); return;
    }
    nextSlide(); return;
  }
  const elements = slide.querySelectorAll('.slide-element');
  const hidden = Array.from(elements).filter(el => !el.classList.contains('visible'));
  if (hidden.length > 0) revealNextElement(); else nextSlide();
}

function handleKeyboard(e) {
  const target = e.target;
  if (target?.closest?.('.theme-editor-panel, input, textarea, select, button, [contenteditable="true"]')) {
    return;
  }
  if (e.key === 'ArrowRight' || e.key === ' ') {
    e.preventDefault();
    handleClick({ target: container, closest: () => null });
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault(); prevSlide();
  }
}

function nextSlide() {
  if (isAnimating) return;
  if (currentSlide >= totalSlides - 1) { resetToStart(); return; }
  goToSlide(currentSlide + 1);
}

function prevSlide() {
  if (isAnimating) return;
  if (currentSlide <= 0) { resetToStart(); return; }
  goToSlide(currentSlide - 1);
}

function resetToStart() {
  if (!slides.length) return;
  isAnimating = false;
  isReady = true;
  stopPreviewSubtitles();
  slides.forEach((slide, i) => {
    slide.classList.remove('active');
    slide.style.transform = '';
    slide.style.opacity = '';
    resetElements(i);
  });
  currentSlide = 0;
  slides[0].classList.add('active');
  slides[0].style.transform = '';
  slides[0].style.opacity = '';
  updateProgress();
  updateAudioPanel();
}

function goToSlide(index) {
  if (index < 0 || index >= totalSlides) return;
  if (index === currentSlide || isAnimating) return;
  isAnimating = true;
  initAudio();
  if (!bgMusicGain && !isMuted) startBackgroundMusic();
  playSlideSound(index);
  const direction = index > currentSlide ? 1 : -1;
  const oldSlide = slides[currentSlide];
  const newSlide = slides[index];
  pauseVideosInSlide(oldSlide);
  resetElements(index);
  oldSlide.classList.remove('active');
  oldSlide.style.transform = direction > 0 ? 'translateX(-60px)' : 'translateX(60px)';
  oldSlide.style.opacity = '0';
  newSlide.style.transform = direction > 0 ? 'translateX(60px)' : 'translateX(-60px)';
  newSlide.style.opacity = '0';
  requestAnimationFrame(() => {
    newSlide.classList.add('active');
    newSlide.style.transform = ''; newSlide.style.opacity = '';
    currentSlide = index;
    updateProgress();
    updateAudioPanel();
    setTimeout(() => {
      isAnimating = false;
      oldSlide.style.transform = ''; oldSlide.style.opacity = '';
      const firstEl = newSlide.querySelector('.slide-element');
      if (firstEl && !firstEl.classList.contains('visible')) {
        firstEl.classList.add('visible'); 
        playVideosInElement(firstEl);
        playRevealSound();
        createParticleBurst(firstEl);
        animateCounters(firstEl);
        startPreviewSubtitles(index);
      }
    }, 420);
  });
}

function revealNextElement() {
  const slide = slides[currentSlide];
  const hidden = Array.from(slide.querySelectorAll('.slide-element')).filter(el => !el.classList.contains('visible'));
  if (hidden.length > 0) {
    hidden[0].classList.add('visible'); playRevealSound(); createParticleBurst(hidden[0]);
    playVideosInElement(hidden[0]);
    animateCounters(hidden[0]);
  }
}

function resetElements(slideIndex) {
  const slide = slides[slideIndex];
  if (!slide) return;
  pauseVideosInSlide(slide);
  slide.querySelectorAll('.slide-element').forEach(el => el.classList.remove('visible'));
  slide.querySelectorAll('.highlighted').forEach(el => el.classList.remove('highlighted'));
  slide.querySelectorAll('.lightable').forEach(el => el.classList.remove('lit-red', 'lit-yellow', 'lit-green'));
  // Reset perf counters
  slide.querySelectorAll('[data-count-to]').forEach(el => { el.textContent = '0.0s'; });
}

function triggerShimmer(el) {
  if (!el) return;
  const shimmer = document.createElement('div');
  shimmer.style.cssText = `
    position: absolute; top: 0; left: 0; width: 60%; height: 100%;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.15) 40%, rgba(255,255,255,0.3) 50%, rgba(255,255,255,0.15) 60%, transparent 100%);
    pointer-events: none; z-index: 10;
    transform: translateX(-160%);
    will-change: transform;
  `;
  el.style.position = 'relative';
  el.style.overflow = 'hidden';
  el.appendChild(shimmer);
  void shimmer.offsetWidth;
  shimmer.style.transition = 'transform 2.5s ease-in-out';
  setTimeout(() => { shimmer.style.transform = 'translateX(300%)'; }, 50);
  setTimeout(() => shimmer.remove(), 3000);
}

function createParticleBurst(element) {
  // Wait slightly longer (100ms) to ensure flexbox layouts have fully settled
  setTimeout(() => {
    // Focus the burst specifically on the icon rather than the whole block container
    let targetEl = element.querySelector('.icon-badge, .card-icon, i') || element;
    
    const rect = targetEl.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    if (!rect || !containerRect) return;

    // Detect CSS scale transform on container (used during auto_render recording)
    const scaleX = containerRect.width / container.offsetWidth || 1;
    const scaleY = containerRect.height / container.offsetHeight || 1;

    const cx = (rect.left - containerRect.left + rect.width / 2) / scaleX;
    const cy = (rect.top - containerRect.top + rect.height / 2) / scaleY;
    
    const particleCount = 30; // Increased for a much more vibrant burst
    const colors = [
      '#FF3F8E', '#04C2C9', '#2E5BFF', '#FF9F00', 
      '#00E676', '#D500F9', '#FFEA00', '#FF1744',
      '#00e5ff', '#84ffff', '#1de9b6', '#a7ffeb'
    ];

    for (let i = 0; i < particleCount; i++) {
      const particle = document.createElement('div');
      particle.className = 'particle';
      
      const angle = (Math.PI * 2 * i) / particleCount + (Math.random() * 0.4 - 0.2);
      const distance = 50 + Math.random() * 90;
      const dx = Math.cos(angle) * distance;
      const dy = Math.sin(angle) * distance;
      const size = 3 + Math.random() * 5;
      const color = colors[Math.floor(Math.random() * colors.length)];
      const duration = 0.7 + Math.random() * 0.5;
      
      particle.style.cssText = `
        position: absolute;
        width: ${size}px;
        height: ${size}px;
        border-radius: 50%;
        background: ${color};
        left: ${cx}px;
        top: ${cy}px;
        pointer-events: none;
        z-index: 2000;
        opacity: 1;
        box-shadow: 0 0 15px ${color}, 0 0 5px ${color};
        transition: transform ${duration}s cubic-bezier(0.22, 1, 0.36, 1), opacity ${duration}s ease-out;
      `;
      
      container.appendChild(particle);
      
      // Force reflow để trình duyệt vẽ trạng thái ban đầu (quan trọng cho headless render)
      void particle.offsetWidth;
      
      setTimeout(() => {
        particle.style.transform = `translate(${dx}px, ${dy}px) scale(0)`;
        particle.style.opacity = '0';
      }, 50);
      
      setTimeout(() => particle.remove(), duration * 1000 + 100);
    }
  }, 100);
}

function updateProgress() {
  updateSlideCounterTotal();
  if (isReady) {
    progressFill.style.width = '0%';
    currentSlideEl.textContent = '0';
  } else {
    progressFill.style.width = ((currentSlide + 1) / totalSlides) * 100 + '%';
    currentSlideEl.textContent = currentSlide + 1;
  }
  updateSlideDeleteControls();
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function autoPlay() {
  initAudio(); startBackgroundMusic();
  for (let i = 0; i < totalSlides; i++) {
    if (i > 0) { goToSlide(i); await sleep(800); }
    const els = slides[i].querySelectorAll('.slide-element');
    for (let j = 0; j < els.length; j++) {
      els[j].classList.add('visible'); playRevealSound(); createParticleBurst(els[j]); await sleep(600);
    }
    await sleep(Math.floor(90000 / totalSlides) - els.length * 600);
  }
}

// ============================================
// AUDIO PANEL CONTROLLER
// ============================================
function updateAudioPanel() {
  const badges = [document.getElementById('audioPanelSlide'), document.getElementById('editorAudioPanelSlide')];
  const transitionSelects = [document.getElementById('transitionSelect'), document.getElementById('editorTransitionSelect')];
  const revealSelects = [document.getElementById('revealSelect'), document.getElementById('editorRevealSelect')];
  const badgeText = isReady ? '⏸ Ready' : 'Slide ' + (currentSlide + 1);
  badges.forEach((badge) => {
    if (badge) badge.textContent = badgeText;
  });
  transitionSelects.forEach((select) => {
    if (select) select.value = slideTransitions[currentSlide] || 'minimal';
  });
  revealSelects.forEach((select) => {
    if (select) select.value = slideReveals[currentSlide] || 'ping';
  });
  updateBgmControls();
  updateScriptPanel();
}

function updateScriptPanel() {
  const sBadge = document.getElementById('scriptSlideBadge');
  const sText = document.getElementById('scriptText');
  if (sBadge && sText) {
    if (isReady) {
      sBadge.textContent = '⏸ Ready';
      sText.textContent = 'Bấm vào slide để bắt đầu...';
    } else {
      sBadge.textContent = 'Slide ' + (currentSlide + 1);
      sText.textContent = slideScripts[currentSlide] || '';
    }
  }
  updateScriptEditor();
}

function saveSlideAudioSettings() {
  syncRuntimeSlideSettings();
  setSlideAudioStatus('Đang lưu...');
  savePreviewSettings(setSlideAudioStatus).catch((error) => {
    setSlideAudioStatus(error.message || 'Không lưu được');
  });
}

function setSlideTransition(idx, value) {
  slideTransitions[idx] = value;
  initAudio();
  if (!isMuted) playSlideSound(idx);
  saveSlideAudioSettings();
}

function setSlideReveal(idx, value) {
  slideReveals[idx] = value;
  initAudio();
  if (!isMuted) playRevealSound();
  saveSlideAudioSettings();
}

function audioPanelPrev() { if (currentSlide > 0) goToSlide(currentSlide - 1); }
function audioPanelNext() { if (currentSlide < totalSlides - 1) goToSlide(currentSlide + 1); }

function testTransition() {
  initAudio();
  if (!bgMusicGain && !isMuted) startBackgroundMusic();
  playSlideSound(currentSlide);
}

function testReveal() {
  initAudio();
  if (!bgMusicGain && !isMuted) startBackgroundMusic();
  playRevealSound();
}

// BGM Presets
const bgmPresets = {
  ambient: { chords: [[130.81, 164.81, 196, 246.94], [110, 130.81, 164.81, 196], [87.31, 130.81, 164.81, 207.65], [98, 123.47, 146.83, 174.61]], arps: [[523.25, 659.25, 783.99, 987.77], [440, 523.25, 659.25, 783.99], [349.23, 523.25, 659.25, 830.61], [392, 493.88, 587.33, 698.46]] },
  cinematic: { chords: [[146.83, 174.61, 220, 277.18], [116.54, 146.83, 174.61, 220], [98, 116.54, 146.83, 174.61], [110, 138.59, 164.81, 220]], arps: [[293.66, 349.23, 440, 554.37], [233.08, 293.66, 349.23, 440], [196, 233.08, 293.66, 349.23], [220, 277.18, 329.63, 440]] },
  lofi: { chords: [[130.81, 155.56, 196, 233.08], [110, 138.59, 164.81, 207.65], [87.31, 110, 130.81, 164.81], [98, 123.47, 155.56, 185]], arps: [[523.25, 622.25, 783.99, 932.33], [440, 554.37, 659.25, 783.99], [349.23, 440, 523.25, 659.25], [392, 493.88, 622.25, 739.99]] },
  piano: { chords: [[130.81, 164.81, 196, 261.63], [146.83, 174.61, 220, 293.66], [87.31, 110, 130.81, 174.61], [98, 123.47, 146.83, 196]], arps: [[261.63, 329.63, 392, 523.25], [293.66, 349.23, 440, 587.33], [174.61, 220, 261.63, 349.23], [196, 246.94, 293.66, 392]] },
  dark: { chords: [[65.41, 82.41, 98, 123.47], [73.42, 87.31, 110, 130.81], [55, 69.3, 82.41, 103.83], [61.74, 77.78, 92.5, 116.54]], arps: [[261.63, 311.13, 392, 466.16], [293.66, 349.23, 440, 523.25], [220, 277.18, 329.63, 415.3], [246.94, 311.13, 369.99, 466.16]] }
};

async function switchBGM(preset) {
  const nextBgm = normalizeBgmSettings({
    bgm: {
      ...previewSettings.bgm,
      mode: preset === 'none' ? 'none' : preset === 'custom' ? 'custom' : 'preset',
      preset: bgmPresets[preset] ? preset : previewSettings.bgm.preset
    }
  });
  if (preset === 'custom' && !nextBgm.custom.path && !nextBgm.custom.url) {
    applyBgmSettings({ ...previewSettings, bgm: nextBgm });
    setBgmStatus('Upload file để dùng custom BGM');
    return;
  }
  previewSettings.bgm = nextBgm;
  const p = bgmPresets[nextBgm.preset];
  if (p) {
    for (let i = 0; i < 4; i++) {
      chordProgression[i] = p.chords[i];
      arpNotes[i] = p.arps[i];
    }
  }
  applyBgmSettings(previewSettings);
  stopBackgroundMusic(0.25);
  setTimeout(() => { if (!isMuted) startBackgroundMusic(); }, 320);
  setBgmStatus('Đang lưu...');
  try {
    await savePreviewSettings(setBgmStatus);
  } catch (error) {
    setBgmStatus(error.message || 'Không lưu được');
  }
}

// ============================================
// PERF COUNTER ANIMATION
// ============================================
function animateCounters(element) {
  const counters = element.querySelectorAll('[data-count-to]');
  if (!counters.length) return;
  counters.forEach(el => {
    const target = parseFloat(el.dataset.countTo);
    const duration = 1000; // 1 second
    const startTime = performance.now();
    const prefix = '~';
    function tick(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = (target * eased).toFixed(1);
      el.textContent = prefix + current + 's';
      if (progress < 1) requestAnimationFrame(tick);
    }
    // Delay to sync with bar animation
    setTimeout(() => requestAnimationFrame(tick), 200);
  });
}

// Initialize
document.addEventListener('DOMContentLoaded', init);

// Extra visual effects for image-to-code viral slides
(() => {
  const fxStates = new WeakMap();
  function setupCanvas(canvas){
    const ctx = canvas.getContext('2d');
    const state = {ctx,w:0,h:0,dpr:1,pts:[],x:.1,y:0,z:0,t:0,particles:[]};
    fxStates.set(canvas,state);
    function resize(){
      const rect = canvas.getBoundingClientRect();
      state.dpr = window.devicePixelRatio || 1;
      state.w = canvas.offsetWidth || rect.width; 
      state.h = canvas.offsetHeight || rect.height;
      const scaleX = rect.width / state.w || 1;
      const scaleY = rect.height / state.h || 1;
      canvas.width = Math.max(1, state.w * scaleX * state.dpr);
      canvas.height = Math.max(1, state.h * scaleY * state.dpr);
      ctx.setTransform(scaleX * state.dpr, 0, 0, scaleY * state.dpr, 0, 0);
      state.particles = Array.from({length:42},()=>({x:Math.random()*state.w,y:Math.random()*state.h,vx:(Math.random()-.5)*.35,vy:(Math.random()-.5)*.35,r:1+Math.random()*2,h:180+Math.random()*100}));
    }
    resize(); addEventListener('resize',resize,{passive:true});
    return state;
  }
  function lorenz(s, dt=1){
    const {ctx,w,h}=s,dt_sim=.006,sigma=10,rho=28,beta=8/3;
    const steps = Math.max(1, Math.round(5 * dt));
    for(let k=0;k<steps;k++){const dx=sigma*(s.y-s.x),dy=s.x*(rho-s.z)-s.y,dz=s.x*s.y-beta*s.z;s.x+=dx*dt_sim;s.y+=dy*dt_sim;s.z+=dz*dt_sim;s.pts.push([s.x,s.y,s.z,s.t]);if(s.pts.length>850)s.pts.shift();s.t+=.002}
    const a=performance.now()*.00014;ctx.clearRect(0,0,w,h);ctx.lineWidth=1.25;ctx.lineCap='round';
    function raw(p){const ca=Math.cos(a),sa=Math.sin(a);return[p[0]*ca-p[2]*sa,p[1]-25,p[0]*sa+p[2]*ca]}
    const raws=s.pts.map(raw);let minX=1e9,maxX=-1e9,minY=1e9,maxY=-1e9;raws.forEach(r=>{minX=Math.min(minX,r[0]);maxX=Math.max(maxX,r[0]);minY=Math.min(minY,r[1]);maxY=Math.max(maxY,r[1])});const fit=Math.min(w*.82/(maxX-minX||1),h*.62/(maxY-minY||1)),cx=(minX+maxX)/2,cy=(minY+maxY)/2;
    for(let i=1;i<raws.length;i++){const q=i/raws.length,r0=raws[i-1],r1=raws[i],d0=1+65/(120+r0[2]),d1=1+65/(120+r1[2]);ctx.strokeStyle=`hsla(${185+i*.22},95%,${55+q*24}%,${q*.72})`;ctx.beginPath();ctx.moveTo(w*.5+(r0[0]-cx)*fit*d0,h*.52-(r0[1]-cy)*fit*d0);ctx.lineTo(w*.5+(r1[0]-cx)*fit*d1,h*.52-(r1[1]-cy)*fit*d1);ctx.stroke()}
  }
  function particles(s, mode, dt=1){const {ctx,w,h}=s;ctx.clearRect(0,0,w,h);for(const p of s.particles){p.x+=p.vx*dt;p.y+=p.vy*dt;if(p.x<0||p.x>w)p.vx*=-1;if(p.y<0||p.y>h)p.vy*=-1;ctx.fillStyle=`hsla(${p.h},95%,70%,.65)`;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fill()}ctx.strokeStyle='rgba(34,211,238,.13)';for(let i=0;i<s.particles.length;i++)for(let j=i+1;j<s.particles.length;j++){const a=s.particles[i],b=s.particles[j],dx=a.x-b.x,dy=a.y-b.y,d=Math.hypot(dx,dy);if(d<85){ctx.globalAlpha=(85-d)/420;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.globalAlpha=1}}if(mode==='flow'||mode==='scan'){const y=(performance.now()*.08)%h;ctx.fillStyle='rgba(34,211,238,.10)';ctx.fillRect(0,y,w,2)}}
  function rings(s, dt=1){const {ctx,w,h}=s;ctx.clearRect(0,0,w,h);const t=performance.now()*.001;for(let i=0;i<8;i++){ctx.strokeStyle=`hsla(${190+i*16},95%,65%,${.22-i*.018})`;ctx.lineWidth=1.4;ctx.beginPath();ctx.ellipse(w*.5,h*.43,50+i*25+Math.sin(t+i)*8,22+i*15, t*.25+i,0,Math.PI*2);ctx.stroke()}}
  function noise(s, dt=1){particles(s,'scan', dt);const {ctx,w,h}=s;for(let i=0;i<16;i++){ctx.fillStyle=`rgba(251,113,133,${Math.random()*.05})`;ctx.fillRect(Math.random()*w,Math.random()*h,40+Math.random()*90,1)}}

  // === NEW FX: Matrix Rain ===
  function matrixRain(s, dt=1){
    const {ctx,w,h}=s;
    if(!s.matrixCols){
      const sz=14;s.matrixSz=sz;
      s.matrixCols=Math.ceil(w/sz);
      s.matrixDrops=Array.from({length:s.matrixCols},()=>Math.random()*-50);
    }
    ctx.fillStyle='rgba(0,0,0,0.06)';ctx.fillRect(0,0,w,h);
    const theme=document.body.dataset.theme||'cautious';
    const clr=theme==='bearish'?'255,60,60':theme==='bullish'?'16,185,129':'245,158,11';
    ctx.font=s.matrixSz+'px monospace';
    for(let i=0;i<s.matrixCols;i++){
      const chars='0123456789VNIDXABCFPT.%+-';
      const ch=chars[Math.floor(Math.random()*chars.length)];
      const y=s.matrixDrops[i]*s.matrixSz;
      ctx.fillStyle=`rgba(${clr},${0.5+Math.random()*0.4})`;
      ctx.fillText(ch,i*s.matrixSz,y);
      if(y>h&&Math.random()>0.975)s.matrixDrops[i]=0;
      s.matrixDrops[i]+=0.4*dt;
    }
  }

  // === NEW FX: Candlestick Pulse ===
  function candlestick(s, dt=1){
    const {ctx,w,h}=s;
    if(!s.candles){
      s.candles=Array.from({length:18},()=>{
        const bull=Math.random()>0.45;
        return{x:Math.random()*w,y:h+Math.random()*200,speed:0.3+Math.random()*0.5,
          w:4+Math.random()*8,bodyH:15+Math.random()*35,wickH:8+Math.random()*15,bull,
          alpha:0.08+Math.random()*0.15};
      });
    }
    ctx.clearRect(0,0,w,h);
    const theme=document.body.dataset.theme||'cautious';
    for(const c of s.candles){
      c.y-=c.speed*dt;
      if(c.y<-80){c.y=h+20;c.x=Math.random()*w;c.bull=Math.random()>(theme==='bearish'?0.7:theme==='bullish'?0.25:0.45);}
      const color=c.bull?'34,197,94':'239,68,68';
      ctx.strokeStyle=`rgba(${color},${c.alpha*0.7})`;ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(c.x,c.y-c.wickH);ctx.lineTo(c.x,c.y+c.bodyH+c.wickH);ctx.stroke();
      ctx.fillStyle=`rgba(${color},${c.alpha})`;
      ctx.fillRect(c.x-c.w/2,c.y,c.w,c.bodyH);
    }
  }

  // === NEW FX: Candlestick Xéo (diagonal) ===
  function candlestickDiag(s, dt=1){
    const {ctx,w,h}=s;
    if(!s.dcandles){
      s.dcandles=Array.from({length:20},()=>{const bull=Math.random()>0.45;
        return{x:Math.random()*w*1.3-w*0.3,y:Math.random()*h,speed:0.25+Math.random()*0.5,w:4+Math.random()*8,bodyH:15+Math.random()*35,wickH:8+Math.random()*15,bull,alpha:0.08+Math.random()*0.15};});
    }
    ctx.clearRect(0,0,w,h);
    const theme=document.body.dataset.theme||'cautious';
    for(const c of s.dcandles){
      c.x+=c.speed*1.3*dt; c.y-=c.speed*0.55*dt;
      if(c.x>w+60||c.y<-80){c.x=-60-Math.random()*120;c.y=h*0.3+Math.random()*h*0.8;c.bull=Math.random()>(theme==='bearish'?0.7:theme==='bullish'?0.25:0.45);}
      const color=c.bull?'34,197,94':'239,68,68';
      ctx.strokeStyle=`rgba(${color},${c.alpha*0.7})`;ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(c.x,c.y-c.wickH);ctx.lineTo(c.x,c.y+c.bodyH+c.wickH);ctx.stroke();
      ctx.fillStyle=`rgba(${color},${c.alpha})`;ctx.fillRect(c.x-c.w/2,c.y,c.w,c.bodyH);
    }
  }

  // === NEW FX: Candle Mono Gold (đơn sắc vàng, tối giản) ===
  function candleMono(s, dt=1){
    const x=s.ctx, w=s.w, h=s.h, A=0.12, CW=w/11, GOLD='251,191,36';
    if(!s.cm){ s.cm=[]; let seed=h*0.5;
      for(let i=0;i<13;i++){ seed+=(Math.random()-0.5)*h*0.12; seed=Math.max(h*0.26,Math.min(h*0.74,seed));
        const up=Math.random()>0.5, bh=h*(0.04+Math.random()*0.08), o=up?seed+bh/2:seed-bh/2, c=up?seed-bh/2:seed+bh/2;
        s.cm.push({x:i*CW,o,c,hi:Math.min(o,c)-h*0.03,lo:Math.max(o,c)+h*0.03,up}); } }
    x.clearRect(0,0,w,h);
    x.strokeStyle='rgba('+GOLD+','+(A*0.22)+')'; x.lineWidth=1;
    for(let i=1;i<6;i++){const gx=w*i/6;x.beginPath();x.moveTo(gx,0);x.lineTo(gx,h);x.stroke();}
    for(let i=1;i<11;i++){const gy=h*i/11;x.beginPath();x.moveTo(0,gy);x.lineTo(w,gy);x.stroke();}
    const cs=s.cm;
    for(const c of cs) c.x-=0.9*dt;
    if(cs[0].x<-CW){ const last=cs[cs.length-1]; cs.shift();
      let seed=(last.o+last.c)/2+(Math.random()-0.5)*h*0.12; seed=Math.max(h*0.26,Math.min(h*0.74,seed));
      const up=Math.random()>0.5, bh=h*(0.04+Math.random()*0.08), o=up?seed+bh/2:seed-bh/2, c2=up?seed-bh/2:seed+bh/2;
      cs.push({x:last.x+CW,o,c:c2,hi:Math.min(o,c2)-h*0.03,lo:Math.max(o,c2)+h*0.03,up}); }
    x.beginPath(); cs.forEach((c,i)=>{const y=(c.o+c.c)/2; i?x.lineTo(c.x+CW/2,y):x.moveTo(c.x+CW/2,y);});
    x.strokeStyle='rgba('+GOLD+','+(A*1.5)+')'; x.lineWidth=1.6; x.stroke();
    const line='rgba('+GOLD+','+(A*1.15)+')';
    for(const c of cs){ const bx=c.x+CW*0.5, top=Math.min(c.o,c.c), bh=Math.abs(c.o-c.c)||2, bw=CW*0.56, bl=c.x+CW*0.22, bot=top+bh;
      x.strokeStyle=line; x.lineWidth=1.1; x.beginPath(); x.moveTo(bx,c.hi); x.lineTo(bx,top); x.moveTo(bx,bot); x.lineTo(bx,c.lo); x.stroke();
      if(c.up){ x.strokeStyle=line; x.lineWidth=1.2; x.strokeRect(bl,top,bw,bh); }
      else{ x.fillStyle='rgba('+GOLD+','+(A*0.9)+')'; x.fillRect(bl,top,bw,bh); } }
  }

  // === NEW FX: Wave Grid ===
  function waveGrid(s, dt=1){
    const {ctx,w,h}=s;ctx.clearRect(0,0,w,h);
    const t=performance.now()*0.001;
    const rows=12,cols=16,gapX=w/(cols-1),gapY=h/(rows-1);
    ctx.strokeStyle='rgba(56,189,248,0.1)';ctx.lineWidth=0.8;
    for(let r=0;r<rows;r++){
      ctx.beginPath();
      for(let c=0;c<cols;c++){
        const x=c*gapX;
        const wave=Math.sin(c*0.4+t*1.2+r*0.3)*12+Math.sin(c*0.2-t*0.8)*6;
        const y=r*gapY+wave;
        c===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
    for(let c=0;c<cols;c++){
      ctx.beginPath();
      for(let r=0;r<rows;r++){
        const wave=Math.sin(c*0.4+t*1.2+r*0.3)*12+Math.sin(c*0.2-t*0.8)*6;
        const x=c*gapX;const y=r*gapY+wave;
        r===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
    for(let r=0;r<rows;r++){
      for(let c=0;c<cols;c++){
        const wave=Math.sin(c*0.4+t*1.2+r*0.3)*12+Math.sin(c*0.2-t*0.8)*6;
        const x=c*gapX;const y=r*gapY+wave;
        const bright=0.2+Math.sin(t+c*0.5+r*0.3)*0.15;
        ctx.fillStyle=`rgba(56,189,248,${bright})`;
        ctx.beginPath();ctx.arc(x,y,1.5,0,Math.PI*2);ctx.fill();
      }
    }
  }

  // === NEW FX: Bokeh Blur ===
  function bokeh(s, dt=1){
    const {ctx,w,h}=s;
    if(!s.bokehOrbs){
      s.bokehOrbs=Array.from({length:12},()=>({
        x:Math.random()*w,y:Math.random()*h,
        r:20+Math.random()*45,
        vx:(Math.random()-0.5)*0.15,vy:(Math.random()-0.5)*0.12,
        h:180+Math.random()*60,alpha:0.04+Math.random()*0.06
      }));
    }
    ctx.clearRect(0,0,w,h);
    for(const o of s.bokehOrbs){
      o.x+=o.vx*dt;o.y+=o.vy*dt;
      if(o.x<-o.r)o.x=w+o.r;if(o.x>w+o.r)o.x=-o.r;
      if(o.y<-o.r)o.y=h+o.r;if(o.y>h+o.r)o.y=-o.r;
      const grad=ctx.createRadialGradient(o.x,o.y,0,o.x,o.y,o.r);
      grad.addColorStop(0,`hsla(${o.h},80%,65%,${o.alpha*1.5})`);
      grad.addColorStop(0.5,`hsla(${o.h},80%,65%,${o.alpha*0.5})`);
      grad.addColorStop(1,`hsla(${o.h},80%,65%,0)`);
      ctx.fillStyle=grad;ctx.beginPath();ctx.arc(o.x,o.y,o.r,0,Math.PI*2);ctx.fill();
      ctx.strokeStyle=`hsla(${o.h},80%,65%,${o.alpha*0.8})`;ctx.lineWidth=1;
      ctx.beginPath();ctx.arc(o.x,o.y,o.r,0,Math.PI*2);ctx.stroke();
    }
  }

  // === NEW FX: Pulse Radar ===
  function pulseRadar(s, dt=1){
    const {ctx,w,h}=s;ctx.clearRect(0,0,w,h);
    const t=performance.now()*0.001;
    const cx=w*0.5,cy=h*0.45,maxR=Math.max(w,h)*0.55;
    const theme=document.body.dataset.theme||'cautious';
    const hue=theme==='bearish'?0:theme==='bullish'?160:35;
    for(let i=0;i<5;i++){
      const phase=(t*0.6+i*0.2)%1;
      const r=phase*maxR;
      const alpha=(1-phase)*0.18;
      ctx.strokeStyle=`hsla(${hue},90%,55%,${alpha})`;ctx.lineWidth=1.5;
      ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);ctx.stroke();
    }
    ctx.fillStyle=`hsla(${hue},90%,60%,0.25)`;
    ctx.beginPath();ctx.arc(cx,cy,4,0,Math.PI*2);ctx.fill();
    const sweepAngle=t*1.5;
    ctx.strokeStyle=`hsla(${hue},90%,60%,0.12)`;ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(cx,cy);
    ctx.lineTo(cx+Math.cos(sweepAngle)*maxR,cy+Math.sin(sweepAngle)*maxR);ctx.stroke();
    for(let i=0;i<6;i++){
      const angle=t*0.3+i*1.047;
      const dist=30+i*25+Math.sin(t+i)*10;
      const bx=cx+Math.cos(angle)*dist,by=cy+Math.sin(angle)*dist;
      const blip=0.3+Math.sin(t*2+i)*0.2;
      ctx.fillStyle=`hsla(${hue},90%,65%,${blip})`;
      ctx.beginPath();ctx.arc(bx,by,2,0,Math.PI*2);ctx.fill();
    }
  }

  // === NEW FX: Constellation ===
  function constellation(s, dt=1){
    const {ctx,w,h}=s;ctx.clearRect(0,0,w,h);
    const t=performance.now()*0.001;
    const rows=12,cols=16;
    if(!s.stars){
      s.stars=Array.from({length:24},()=>({
        x:Math.random()*w,y:Math.random()*h,
        r:1+Math.random()*1.5,
        twinkleSpeed:0.5+Math.random()*2,
        twinkleOffset:Math.random()*Math.PI*2,
        vx:(Math.random()-0.5)*0.05,vy:(Math.random()-0.5)*0.04
      }));
    }
    ctx.clearRect(0,0,w,h);
    const tStar=performance.now()*0.001;
    ctx.strokeStyle='rgba(148,163,184,0.06)';ctx.lineWidth=0.6;
    for(let i=0;i<s.stars.length;i++){
      for(let j=i+1;j<s.stars.length;j++){
        const a=s.stars[i],b=s.stars[j];
        const d=Math.hypot(a.x-b.x,a.y-b.y);
        if(d<120){
          ctx.globalAlpha=(120-d)/600;
          ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
          ctx.globalAlpha=1;
        }
      }
    }
    for(const star of s.stars){
      star.x+=star.vx*dt;star.y+=star.vy*dt;
      if(star.x<0||star.x>w)star.vx*=-1;
      if(star.y<0||star.y>h)star.vy*=-1;
      const twinkle=0.3+Math.sin(tStar*star.twinkleSpeed+star.twinkleOffset)*0.35;
      ctx.fillStyle=`rgba(226,232,240,${twinkle})`;
      ctx.beginPath();ctx.arc(star.x,star.y,star.r,0,Math.PI*2);ctx.fill();
      if(twinkle>0.55){
        ctx.fillStyle=`rgba(226,232,240,${twinkle*0.3})`;
        ctx.beginPath();ctx.arc(star.x,star.y,star.r*3,0,Math.PI*2);ctx.fill();
      }
    }
  }

  let lastTime = performance.now();
  function tick(){
    const now = performance.now();
    let dt = (now - lastTime) / 16.666;
    if (dt > 5) dt = 5;
    lastTime = now;
    document.querySelectorAll('.fx-canvas').forEach(c=>{if(c.hidden)return;const s=fxStates.get(c)||setupCanvas(c),fx=c.dataset.fx;if(fx==='lorenz')lorenz(s,dt);else if(fx==='rings')rings(s,dt);else if(fx==='noise')noise(s,dt);else if(fx==='matrix-rain')matrixRain(s,dt);else if(fx==='candlestick')candlestick(s,dt);else if(fx==='candlestick-diag')candlestickDiag(s,dt);else if(fx==='candle-mono')candleMono(s,dt);else if(fx==='wave-grid')waveGrid(s,dt);else if(fx==='bokeh')bokeh(s,dt);else if(fx==='pulse-radar')pulseRadar(s,dt);else if(fx==='constellation')constellation(s,dt);else particles(s,fx,dt)});requestAnimationFrame(tick)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',tick);else tick();
})();
