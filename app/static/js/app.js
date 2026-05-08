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
        var resp = await fetch('/api/upload', { method: 'POST', body: form });
        var data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Upload failed');
        // Navigate to book detail page
        window.location.href = '/books/' + data.book_id;
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    }
}

// Chapter selection
function toggleAll(checked) {
    document.querySelectorAll('input[name="chapters"]').forEach(function(cb) { cb.checked = checked; });
}

// Voice data
function updateVoices() {
    var lang = document.getElementById('language').value;
    var voiceSelect = document.getElementById('voice');
    var voices = voiceData[lang] || voiceData['en-US'];
    voiceSelect.innerHTML = '';
    voices.forEach(function(v) {
        var opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        voiceSelect.appendChild(opt);
    });
}

// Conversion with inline progress
var _pollTimer = null;

async function startConvert(bookId) {
    var selected = [];
    document.querySelectorAll('input[name="chapters"]:checked').forEach(function(cb) {
        selected.push(parseInt(cb.value));
    });
    if (selected.length === 0) { alert('Please select at least one chapter'); return; }

    var rate = document.getElementById('rate').value;
    var body = {
        selected_chapters: selected,
        voice: document.getElementById('voice').value,
        language: document.getElementById('language').value,
        rate: (rate >= 0 ? '+' : '') + rate + '%',
        output_m4b: document.getElementById('outM4b').checked,
        output_mp3: document.getElementById('outMp3').checked,
    };

    try {
        var resp = await fetch('/api/convert/' + bookId, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        var data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed to start conversion');
        // Show inline progress
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
        if (!resp.ok) return;

        var fill = document.getElementById('progressFill');
        var text = document.getElementById('progressText');
        var chapter = document.getElementById('currentChapter');
        var err = document.getElementById('errorMsg');
        var cancel = document.getElementById('cancelBtn');

        if (!fill) return;

        fill.style.width = data.progress_percent.toFixed(1) + '%';
        text.textContent = data.progress_percent.toFixed(1) + '% (' + data.completed_chapters + '/' + data.total_chapters + ')';
        chapter.textContent = data.current_chapter ? 'Converting: ' + data.current_chapter : '';

        // Highlight converting chapter
        document.querySelectorAll('.chapter-item').forEach(function(el) {
            el.classList.remove('converting');
        });
        if (data.state === 'running' && data.current_chapter) {
            var items = document.querySelectorAll('.chapter-item');
            items.forEach(function(el) {
                var titleEl = el.querySelector('.ch-title');
                if (titleEl && titleEl.textContent.trim() === data.current_chapter) {
                    el.classList.add('converting');
                }
            });
        }

        if (data.state === 'completed') {
            clearInterval(_pollTimer);
            cancel.classList.add('hidden');
            // Reload page to show new conversion in history
            setTimeout(function() { window.location.reload(); }, 500);
        } else if (data.state === 'failed') {
            clearInterval(_pollTimer);
            err.classList.remove('hidden');
            err.textContent = 'Error: ' + data.error_message;
            cancel.classList.add('hidden');
            hideProgress();
        } else if (data.state === 'cancelled') {
            clearInterval(_pollTimer);
            chapter.textContent = 'Conversion cancelled.';
            cancel.classList.add('hidden');
            hideProgress();
        }
    } catch (e) { /* ignore poll errors */ }
}

async function cancelConvert(bookId) {
    await fetch('/api/convert/' + bookId + '/cancel', { method: 'POST' });
}
