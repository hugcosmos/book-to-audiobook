// Upload
function initUpload() {
    var dropZone = document.getElementById('dropZone');
    var fileInput = document.getElementById('fileInput');
    if (!dropZone) return;

    dropZone.addEventListener('click', function() { fileInput.click(); });
    dropZone.addEventListener('dragover', function(e) {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', function() {
        dropZone.classList.remove('dragover');
    });
    dropZone.addEventListener('drop', function(e) {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', function() {
        if (fileInput.files.length) uploadFile(fileInput.files[0]);
    });
}

async function uploadFile(file) {
    var status = document.getElementById('uploadStatus');
    status.classList.remove('hidden');
    status.textContent = 'Uploading and parsing...';

    var form = new FormData();
    form.append('file', file);
    try {
        // Use XMLHttpRequest to bypass the fetch wrapper in base.html
        var resp = await new Promise(function(resolve, reject) {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload');
            xhr.onload = function() {
                resolve({ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, json: function() { return JSON.parse(xhr.responseText); }});
            };
            xhr.onerror = function() { reject(new Error('Network error')); };
            xhr.send(form);
        });
        var data = resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Upload failed');
        window.location.href = '/books/' + data.book_id;
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
}

// Chapter selection
function toggleAll(checked) {
    document.querySelectorAll('input[name="chapters"]').forEach(function(cb) { cb.checked = checked; });
}

// --- TTS Provider / Voice dynamic loading ---

var _providers = [];
var _currentProvider = '';

async function initTTSUI() {
    await loadProviders();
    await loadLanguages();
    await loadVoices();
    await loadDefaultSpeed();
    // Auto-sync speed when returning from settings tab
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) loadDefaultSpeed();
    });
}

async function loadDefaultSpeed() {
    try {
        var resp = await fetch('/api/settings');
        var data = await resp.json();
        var provider = document.getElementById('provider').value;
        var speed = 1.0;
        // Per-provider speed saved from convert page
        if (data.convert_speed && data.convert_speed[provider] != null) {
            speed = data.convert_speed[provider];
        } else if (provider === 'qwen3_mlx' && data.qwen3_mlx && data.qwen3_mlx.speed != null) {
            speed = data.qwen3_mlx.speed;
        } else if (provider === 'supertonic' && data.supertonic && data.supertonic.speed != null) {
            speed = data.supertonic.speed;
        } else if (provider === 'cosyvoice' && data.cosyvoice && data.cosyvoice.speed != null) {
            speed = data.cosyvoice.speed;
        } else if (provider === 'kokoro' && data.kokoro && data.kokoro.speed != null) {
            speed = data.kokoro.speed;
        }
        var el = document.getElementById('speed');
        if (el) {
            el.value = speed;
            var label = document.getElementById('speedLabel');
            if (label) label.textContent = speed + 'x';
        }
    } catch (e) {
        console.error('Failed to load default speed:', e);
    }
}

var _speedSaveTimer = null;
function saveSpeed() {
    if (_speedSaveTimer) clearTimeout(_speedSaveTimer);
    _speedSaveTimer = setTimeout(function() {
        var provider = document.getElementById('provider').value;
        var speed = parseFloat(document.getElementById('speed').value);
        fetch('/api/settings').then(function(r) { return r.json(); }).then(function(data) {
            var speedMap = data.convert_speed || {};
            speedMap[provider] = speed;
            return fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: { convert_speed: speedMap } }),
            });
        }).catch(function(e) {
            console.error('Failed to save speed:', e);
        });
    }, 500);
}

async function loadProviders() {
    try {
        var resp = await fetch('/api/tts/providers');
        _providers = await resp.json();
        var sel = document.getElementById('provider');
        if (!sel) return;
        sel.innerHTML = '';
        _providers.forEach(function(p) {
            var opt = document.createElement('option');
            opt.value = p.name;
            opt.textContent = p.label + (p.configured ? '' : ' (未配置)');
            opt.disabled = !p.configured;
            sel.appendChild(opt);
        });
        // Respect user's configured default provider
        try {
            var defaultResp = await fetch('/api/settings');
            var defaultData = await defaultResp.json();
            var defaultProvider = defaultData.tts_default_provider
                || (defaultData.tts && defaultData.tts.provider);
            if (defaultProvider) {
                sel.value = defaultProvider;
            }
        } catch (e2) {
            console.error('Failed to load default provider:', e2);
        }
        _currentProvider = sel.value;
    } catch (e) {
        console.error('Failed to load providers:', e);
    }
}

async function onProviderChange() {
    _currentProvider = document.getElementById('provider').value;
    await loadLanguages();
    await loadVoices();
    await loadDefaultSpeed();
}

async function loadLanguages() {
    var sel = document.getElementById('language');
    if (!sel || !_currentProvider) return;
    try {
        var resp = await fetch('/api/tts/languages?provider=' + encodeURIComponent(_currentProvider));
        var langs = await resp.json();
        var prevValue = sel.value;
        sel.innerHTML = '';
        langs.forEach(function(l) {
            var opt = document.createElement('option');
            opt.value = l.code;
            opt.textContent = l.name;
            sel.appendChild(opt);
        });
        // Try to keep previous selection if provider supports it
        if (langs.some(function(l) { return l.code === prevValue; })) {
            sel.value = prevValue;
        }
    } catch (e) {
        console.error('Failed to load languages:', e);
    }
}

async function onLanguageChange() {
    await loadVoices();
}

async function loadVoices() {
    var lang = document.getElementById('language').value;
    var sel = document.getElementById('voice');
    if (!sel || !_currentProvider) return;
    try {
        var url = '/api/tts/voices?provider=' + encodeURIComponent(_currentProvider);
        if (lang) url += '&language=' + encodeURIComponent(lang);
        var resp = await fetch(url);
        var voices = await resp.json();
        sel.innerHTML = '';
        if (voices.length === 0) {
            var opt = document.createElement('option');
            opt.value = '';
            opt.textContent = 'No voices available for this language';
            opt.disabled = true;
            opt.selected = true;
            sel.appendChild(opt);
            return;
        }
        voices.forEach(function(v) {
            var opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = v.name + (v.description ? ' - ' + v.description : '');
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load voices:', e);
    }
}

// Conversion with inline progress
var _pollTimer = null;

async function startConvert(bookId, force) {
    var selected = [];
    document.querySelectorAll('input[name="chapters"]:checked').forEach(function(cb) {
        selected.push(parseInt(cb.value));
    });
    if (selected.length === 0) { alert('Please select at least one chapter'); return; }

    var body = {
        selected_chapters: selected,
        provider: document.getElementById('provider').value,
        voice: document.getElementById('voice').value,
        language: document.getElementById('language').value,
        speed: parseFloat(document.getElementById('speed').value),
        output_m4b: document.getElementById('outM4b').checked,
        output_mp3: document.getElementById('outMp3').checked,
    };

    try {
        var url = '/api/convert/' + bookId;
        if (force) url += '?force=1';
        var resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        var data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed to start conversion');
        // Language mismatch warning — ask user before proceeding
        if (data.warning && !force) {
            if (confirm(data.warning)) {
                return startConvert(bookId, true);
            }
            return;
        }
        showProgress();
        startPolling(bookId);
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

function showProgress() {
    var section = document.getElementById('progressSection');
    if (section) section.classList.remove('hidden');
    var btn = document.getElementById('convertBtn');
    if (btn) btn.disabled = true;
}

function hideProgress() {
    var btn = document.getElementById('convertBtn');
    if (btn) btn.disabled = false;
}

function startPolling(bookId) {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(function() { pollStatus(bookId); }, 2000);
    pollStatus(bookId);
}

async function pollStatus(bookId) {
    try {
        var resp = await fetch('/api/convert/' + bookId + '/status');
        var data = await resp.json();
        if (!resp.ok) {
            clearInterval(_pollTimer);
            hideProgress();
            return;
        }

        var fill = document.getElementById('progressFill');
        var text = document.getElementById('progressText');
        var chapter = document.getElementById('currentChapter');
        var err = document.getElementById('errorMsg');
        var cancel = document.getElementById('cancelBtn');

        if (!fill) return;

        if (data.state === 'lost') {
            clearInterval(_pollTimer);
            chapter.textContent = 'Server restarted \u2014 conversion state lost.';
            cancel.classList.add('hidden');
            hideProgress();
            return;
        }

        if (data.state === 'resumable') {
            clearInterval(_pollTimer);
            showProgress();
            var pct = data.progress_percent.toFixed(1) + '%';
            fill.style.width = pct;
            text.textContent = pct + ' \u2014 chapter ' + data.completed_chapters + '/' + data.total_chapters;
            var btns = '<button class="btn btn-sm btn-primary" onclick="resumeConvert(\'' + bookId + '\')" style="margin-left:8px">Resume</button>';
            btns += ' <button class="btn btn-sm btn-danger" onclick="discardTask(\'' + bookId + '\')" style="margin-left:8px">Discard</button>';
            if (data.completed_chapters >= data.total_chapters) {
                chapter.innerHTML = 'All chapters synthesized. Merge interrupted.' + btns;
            } else {
                chapter.innerHTML = 'Conversion interrupted. ' + data.completed_chapters + '/' + data.total_chapters + ' chapters completed.' + btns;
            }
            cancel.classList.add('hidden');
            return;
        }

        fill.style.width = data.progress_percent.toFixed(1) + '%';
        var pctText = data.progress_percent.toFixed(1) + '%';
        if (data.completed_chapters > 0) {
            pctText += ' \u2014 chapter ' + data.completed_chapters + '/' + data.total_chapters;
        }
        text.textContent = pctText;
        chapter.textContent = data.current_chapter ? data.current_chapter : '';

        // Highlight converting chapter (match by title prefix before " (chunk")
        var activeTitle = data.current_chapter ? data.current_chapter.split(' (chunk')[0].split(' (preparing')[0].trim() : '';
        document.querySelectorAll('.chapter-item').forEach(function(el) {
            el.classList.remove('converting');
        });
        if (data.state === 'running' && activeTitle) {
            document.querySelectorAll('.chapter-item').forEach(function(el) {
                var titleEl = el.querySelector('.ch-title');
                if (titleEl && titleEl.textContent.trim() === activeTitle) {
                    el.classList.add('converting');
                }
            });
        }

        if (data.state === 'completed') {
            clearInterval(_pollTimer);
            cancel.classList.add('hidden');
            setTimeout(function() { window.location.reload(); }, 500);
        } else if (data.state === 'failed') {
            clearInterval(_pollTimer);
            err.classList.remove('hidden');
            err.textContent = 'Error: ' + data.error_message;
            cancel.classList.add('hidden');
            hideProgress();
        } else if (data.state === 'cancelled') {
            clearInterval(_pollTimer);
            chapter.innerHTML = 'Conversion cancelled. <button class="btn btn-sm btn-danger" onclick="discardTask(\'' + bookId + '\')" style="margin-left:8px">Discard</button>';
            cancel.classList.add('hidden');
            hideProgress();
        }
    } catch (e) { /* ignore poll errors */ }
}

async function cancelConvert(bookId) {
    await fetch('/api/convert/' + bookId + '/cancel', { method: 'POST' });
}

async function discardTask(bookId) {
    if (!confirm('Discard this task and delete all output files?')) return;
    try {
        var resp = await fetch('/api/convert/' + bookId + '/task', { method: 'DELETE' });
        if (!resp.ok) throw new Error('Discard failed');
        location.reload();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

// Voice preview
var _previewAudio = null;

async function previewVoice() {
    var btn = document.getElementById('previewBtn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = '\u23F3 Loading...';

    // Stop previous preview if playing
    if (_previewAudio) {
        _previewAudio.pause();
        _previewAudio = null;
    }

    try {
        var resp = await fetch('/api/tts/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider: document.getElementById('provider').value,
                voice: document.getElementById('voice').value,
                language: document.getElementById('language').value,
                speed: parseFloat(document.getElementById('speed').value),
            }),
        });
        if (!resp.ok) {
            var msg = 'Preview failed';
            try { var err = await resp.json(); msg = err.detail || msg; } catch(e) {}
            throw new Error(msg);
        }
        var blob = await resp.blob();
        var url = URL.createObjectURL(blob);
        _previewAudio = new Audio(url);
        _previewAudio.onended = function() {
            btn.disabled = false;
            btn.textContent = '\u25B6 Preview Voice';
            URL.revokeObjectURL(url);
        };
        _previewAudio.onerror = function() {
            btn.disabled = false;
            btn.textContent = '\u25B6 Preview Voice';
        };
        _previewAudio.play();
    } catch (e) {
        alert('Preview error: ' + e.message);
        btn.disabled = false;
        btn.textContent = '\u25B6 Preview Voice';
    }
}

// --- Chapter text editor ---

async function openChapterEditor(bookId, chapterIndex) {
    var overlay = document.getElementById('chapterEditorOverlay');
    var textarea = document.getElementById('chapterEditorTextarea');
    var title = document.getElementById('chapterEditorTitle');
    var charCount = document.getElementById('chapterEditorCharCount');
    var saveBtn = document.getElementById('chapterEditorSaveBtn');

    // Find chapter title from DOM
    var item = document.querySelector('.chapter-item[data-index="' + chapterIndex + '"]');
    var chTitle = item ? item.querySelector('.ch-title').textContent.replace('edited', '').trim() : 'Chapter ' + chapterIndex;
    title.textContent = 'Edit: ' + chTitle;
    textarea.value = 'Loading...';
    textarea.disabled = true;
    saveBtn.disabled = true;
    overlay.classList.add('active');

    overlay._bookId = bookId;
    overlay._chapterIndex = chapterIndex;

    try {
        var resp = await fetch('/api/books/' + bookId + '/chapters/' + chapterIndex + '/text');
        if (!resp.ok) throw new Error('Failed to load chapter text');
        var data = await resp.json();
        textarea.value = data.text;
        charCount.textContent = data.text.length + ' chars';
        textarea.disabled = false;
        saveBtn.disabled = false;
    } catch (e) {
        textarea.value = 'Error: ' + e.message;
    }

    textarea.oninput = function() {
        charCount.textContent = textarea.value.length + ' chars';
    };
}

function closeChapterEditor() {
    var overlay = document.getElementById('chapterEditorOverlay');
    overlay.classList.remove('active');
    overlay._bookId = null;
    overlay._chapterIndex = null;
}

async function saveChapterText() {
    var overlay = document.getElementById('chapterEditorOverlay');
    var textarea = document.getElementById('chapterEditorTextarea');
    var saveBtn = document.getElementById('chapterEditorSaveBtn');
    var charCountEl = document.getElementById('chapterEditorCharCount');
    var bookId = overlay._bookId;
    var chapterIndex = overlay._chapterIndex;
    if (!bookId || chapterIndex == null) return;

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
        var resp = await fetch('/api/books/' + bookId + '/chapters/' + chapterIndex + '/text', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: textarea.value }),
        });
        if (!resp.ok) throw new Error('Failed to save');
        var data = await resp.json();

        // Update DOM: char_count and duration
        var item = document.querySelector('.chapter-item[data-index="' + chapterIndex + '"]');
        if (item) {
            var metaEl = item.querySelector('.ch-meta');
            var dur = data.estimated_duration_seconds;
            var durStr = dur / 60 >= 1 ? Math.round(dur / 60) + ' min' : Math.max(1, Math.round(dur)) + 's';
            metaEl.textContent = data.char_count + ' chars \u00b7 ~' + durStr;
            // Add edited badge if not present
            var titleEl = item.querySelector('.ch-title');
            if (!titleEl.querySelector('.ch-edited-badge')) {
                var badge = document.createElement('span');
                badge.className = 'ch-edited-badge';
                badge.textContent = 'edited';
                titleEl.appendChild(document.createTextNode(' '));
                titleEl.appendChild(badge);
            }
        }
        charCountEl.textContent = data.char_count + ' chars';
        saveBtn.textContent = 'Saved!';
        setTimeout(function() { saveBtn.textContent = 'Save'; saveBtn.disabled = false; }, 1000);
    } catch (e) {
        alert('Error: ' + e.message);
        saveBtn.textContent = 'Save';
        saveBtn.disabled = false;
    }
}

// --- Resume interrupted conversion ---

async function resumeConvert(bookId) {
    var chapter = document.getElementById('currentChapter');
    if (chapter) chapter.textContent = 'Resuming conversion...';
    var cancel = document.getElementById('cancelBtn');
    if (cancel) cancel.classList.remove('hidden');
    try {
        var resp = await fetch('/api/convert/' + bookId + '/resume', { method: 'POST' });
        var data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Resume failed');
        startPolling(bookId);
    } catch (e) {
        alert('Resume error: ' + e.message);
    }
}

// --- Check for resumable conversions on page load ---

async function checkResumable() {
    if (typeof bookId === 'undefined') return;
    try {
        var resp = await fetch('/api/convert/' + bookId + '/status');
        var data = await resp.json();
        if (data.state === 'resumable') {
            showProgress();
            var fill = document.getElementById('progressFill');
            var text = document.getElementById('progressText');
            var chapter = document.getElementById('currentChapter');
            var cancel = document.getElementById('cancelBtn');
            var pct = data.progress_percent.toFixed(1) + '%';
            if (fill) fill.style.width = pct;
            if (text) text.textContent = pct + ' \u2014 chapter ' + data.completed_chapters + '/' + data.total_chapters;
            if (chapter) {
                var btns = '<button class="btn btn-sm btn-primary" onclick="resumeConvert(\'' + bookId + '\')" style="margin-left:8px">Resume</button>';
                btns += ' <button class="btn btn-sm btn-danger" onclick="discardTask(\'' + bookId + '\')" style="margin-left:8px">Discard</button>';
                chapter.innerHTML = data.completed_chapters >= data.total_chapters
                    ? 'All chapters synthesized. Merge interrupted.' + btns
                    : 'Conversion interrupted. ' + data.completed_chapters + '/' + data.total_chapters + ' chapters completed.' + btns;
            }
            if (cancel) cancel.classList.add('hidden');
        } else if (data.state === 'running' || data.state === 'pending') {
            // Reconnect to running task — show progress UI and resume polling
            showProgress();
            startPolling(bookId);
        }
    } catch (e) { /* ignore */ }
}
