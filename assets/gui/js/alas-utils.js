/**
 * Alas WebUI Utilities
 * 公告弹窗、截图查看器、自动刷新等前端功能
 * 从 app.py run_js() 运行时注入迁移为静态加载
 */

// ============================================================
// 自动刷新（断连后自动 reload）
// [For develop] Disable by run `reload=0` in console
// ============================================================
(function () {
    window.reload = 1;
    if (window.WebIO && WebIO._state && WebIO._state.CurrentSession) {
        WebIO._state.CurrentSession.on_session_close(function () {
            setTimeout(function () {
                if (window.reload == 1) {
                    location.reload();
                }
            }, 4000);
        });
    }
})();

// ============================================================
// 截图查看器（点击截图放大、缩放、拖拽）
// ============================================================
(function () {
    function sanitizeUrl(url) {
        if (!url) return '';
        var protocol = url.split(':')[0].toLowerCase().trim();
        if (['javascript', 'data', 'vbscript'].indexOf(protocol) !== -1) {
            // Only allow data:image/ for base64 images
            if (url.startsWith('data:image/')) return url;
            return '';
        }
        return url;
    }

    function ensureScreenshotModal() {
        if (document.getElementById('screenshot-modal')) return;
        var modal = document.createElement('div');
        modal.id = 'screenshot-modal';
        Object.assign(modal.style, {
            position: 'fixed',
            left: 0,
            top: 0,
            width: '100vw',
            height: '100vh',
            display: 'none',
            justifyContent: 'center',
            alignItems: 'center',
            background: 'rgba(0,0,0,0.65)',
            zIndex: 99999,
            overflow: 'hidden',
            padding: '20px',
            boxSizing: 'border-box',
            cursor: 'grab'
        });
        var modalImg = document.createElement('img');
        modalImg.id = 'screenshot-modal-img';
        Object.assign(modalImg.style, {
            maxWidth: '100%',
            maxHeight: '90vh',
            objectFit: 'contain',
            boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
            transition: 'transform 0.05s linear',
            transformOrigin: 'center center',
            willChange: 'transform'
        });
        modal.appendChild(modalImg);

        modal.dataset.scale = 1;
        modal.dataset.tx = 0;
        modal.dataset.ty = 0;
        modal.dataset.panning = 0;

        function applyTransform() {
            var s = parseFloat(modal.dataset.scale) || 1;
            var tx = parseFloat(modal.dataset.tx) || 0;
            var ty = parseFloat(modal.dataset.ty) || 0;
            modalImg.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + s + ')';
        }

        modal.addEventListener('wheel', function (e) {
            if (e.ctrlKey) return;
            e.preventDefault();
            var rect = modalImg.getBoundingClientRect();
            var cx = e.clientX - (rect.left + rect.width / 2);
            var cy = e.clientY - (rect.top + rect.height / 2);
            var scale = parseFloat(modal.dataset.scale) || 1;
            var delta = -e.deltaY;
            var factor = delta > 0 ? 1.12 : 0.88;
            var newScale = Math.min(6, Math.max(0.3, scale * factor));

            var tx = parseFloat(modal.dataset.tx) || 0;
            var ty = parseFloat(modal.dataset.ty) || 0;
            modal.dataset.tx = tx - cx * (newScale - scale);
            modal.dataset.ty = ty - cy * (newScale - scale);
            modal.dataset.scale = newScale;
            applyTransform();
        }, { passive: false });

        var start = { x: 0, y: 0 };
        modalImg.addEventListener('mousedown', function (e) {
            e.preventDefault();
            modal.dataset.panning = 1;
            start.x = e.clientX;
            start.y = e.clientY;
            modal.style.cursor = 'grabbing';
        });
        window.addEventListener('mousemove', function (e) {
            if (modal.dataset.panning !== '1') return;
            var dx = e.clientX - start.x;
            var dy = e.clientY - start.y;
            start.x = e.clientX;
            start.y = e.clientY;
            modal.dataset.tx = (parseFloat(modal.dataset.tx) || 0) + dx;
            modal.dataset.ty = (parseFloat(modal.dataset.ty) || 0) + dy;
            applyTransform();
        });
        window.addEventListener('mouseup', function (e) {
            if (modal.dataset.panning === '1') {
                modal.dataset.panning = 0;
                modal.style.cursor = 'grab';
            }
        });

        modalImg.addEventListener('dblclick', function (e) {
            modal.dataset.scale = 1;
            modal.dataset.tx = 0;
            modal.dataset.ty = 0;
            applyTransform();
        });

        modal.addEventListener('click', function (e) {
            if (e.target === modal) modal.style.display = 'none';
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                var m = document.getElementById('screenshot-modal');
                if (m) m.style.display = 'none';
            }
        });

        document.body.appendChild(modal);
    }

    // Ensure modal exists and wire click handler to #screenshot-img
    ensureScreenshotModal();
    function bindScreenshotImg() {
        var img = document.getElementById('screenshot-img');
        if (!img) return;
        img.style.cursor = 'zoom-in';
        img.onclick = function (e) {
            var m = document.getElementById('screenshot-modal');
            var mi = document.getElementById('screenshot-modal-img');
            if (!m || !mi) return;
            var src = img.getAttribute('data-modal-src') || img.src;
            mi.src = sanitizeUrl(src);
            m.dataset.scale = 1;
            m.dataset.tx = 0;
            m.dataset.ty = 0;
            mi.style.transform = '';
            m.style.display = 'flex';
        };
    }
    // Try binding now and also when DOM changes
    bindScreenshotImg();
    var obs = new MutationObserver(function () { bindScreenshotImg(); });
    obs.observe(document.body, { childList: true, subtree: true });
})();

// ============================================================
// 实时截图预览（H264/H265 over fragmented MP4 WebSocket）
// ============================================================
(function () {
    var state = {
        socket: null,
        mediaSource: null,
        sourceBuffer: null,
        queue: [],
        objectUrl: '',
        instance: 'alas',
        codec: localStorage.getItem('alas_live_preview_codec') || 'h264',
        open: false,
        transportId: 0
    };

    function sanitizeText(text) {
        return String(text || '').replace(/[<>&]/g, function (ch) {
            return ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[ch];
        });
    }

    function ensurePanel() {
        var panel = document.getElementById('alas-live-preview');
        if (panel) return panel;

        panel = document.createElement('div');
        panel.id = 'alas-live-preview';
        panel.innerHTML = [
            '<div class="alas-live-preview-head">',
            '<span class="alas-live-preview-title">实时截图</span>',
            '<select class="alas-live-preview-codec" title="编码">',
            '<option value="h264">H264</option>',
            '<option value="h265">H265</option>',
            '</select>',
            '<button class="alas-live-preview-close" type="button" title="关闭">×</button>',
            '</div>',
            '<video class="alas-live-preview-video" muted autoplay playsinline></video>',
            '<div class="alas-live-preview-status">连接中</div>'
        ].join('');

        var style = document.createElement('style');
        style.textContent = [
            '#alas-live-preview{position:fixed;right:18px;bottom:18px;width:min(560px,calc(100vw - 36px));background:#101418;border:1px solid rgba(255,255,255,.14);border-radius:8px;box-shadow:0 12px 36px rgba(0,0,0,.35);z-index:99990;overflow:hidden;display:none;}',
            '.alas-live-preview-head{height:38px;display:flex;align-items:center;gap:8px;padding:0 8px 0 12px;background:#1b222b;color:#f2f5f8;font-size:14px;}',
            '.alas-live-preview-title{font-weight:600;margin-right:auto;}',
            '.alas-live-preview-codec{height:26px;border-radius:4px;border:1px solid rgba(255,255,255,.2);background:#111820;color:#f2f5f8;padding:0 6px;}',
            '.alas-live-preview-close{width:28px;height:28px;border:0;background:transparent;color:#f2f5f8;font-size:24px;line-height:24px;cursor:pointer;}',
            '.alas-live-preview-video{display:block;width:100%;aspect-ratio:16/9;background:#000;object-fit:contain;}',
            '.alas-live-preview-status{position:absolute;left:12px;bottom:10px;max-width:calc(100% - 24px);padding:4px 8px;border-radius:4px;background:rgba(0,0,0,.58);color:#fff;font-size:12px;line-height:1.35;pointer-events:none;}'
        ].join('');
        document.head.appendChild(style);
        document.body.appendChild(panel);

        panel.querySelector('.alas-live-preview-close').onclick = function () {
            window.alasStopLivePreview();
        };
        panel.querySelector('.alas-live-preview-codec').onchange = function (e) {
            state.codec = e.target.value;
            localStorage.setItem('alas_live_preview_codec', state.codec);
            if (state.open) start(state.instance, state.codec);
        };

        return panel;
    }

    function setStatus(text) {
        var panel = ensurePanel();
        var status = panel.querySelector('.alas-live-preview-status');
        status.innerHTML = sanitizeText(text);
        status.style.display = text ? 'block' : 'none';
    }

    function cleanupTransport() {
        state.transportId += 1;
        if (state.socket) {
            state.socket.onclose = null;
            state.socket.onerror = null;
            state.socket.onmessage = null;
            try { state.socket.close(); } catch (e) { }
            state.socket = null;
        }
        if (state.sourceBuffer) {
            state.sourceBuffer.onupdateend = null;
            state.sourceBuffer = null;
        }
        if (state.mediaSource) {
            try {
                if (state.mediaSource.readyState === 'open') state.mediaSource.endOfStream();
            } catch (e) { }
            state.mediaSource = null;
        }
        if (state.objectUrl) {
            URL.revokeObjectURL(state.objectUrl);
            state.objectUrl = '';
        }
        state.queue = [];
    }

    function appendNext(transportId) {
        if (transportId !== state.transportId) return;
        var sb = state.sourceBuffer;
        if (!sb || sb.updating || !state.queue.length) return;
        try {
            sb.appendBuffer(state.queue.shift());
        } catch (e) {
            if (transportId !== state.transportId) return;
            setStatus(e.message || e);
        }
    }

    function attachMedia(socket, codec, mime, transportId) {
        var panel = ensurePanel();
        var video = panel.querySelector('.alas-live-preview-video');
        if (!state.open || transportId !== state.transportId) {
            try { socket.close(); } catch (e) { }
            return;
        }

        state.socket = socket;
        state.mediaSource = new MediaSource();
        state.objectUrl = URL.createObjectURL(state.mediaSource);
        video.src = state.objectUrl;

        state.mediaSource.addEventListener('sourceopen', function () {
            if (!state.open || transportId !== state.transportId || state.socket !== socket) {
                return;
            }
            if (!MediaSource.isTypeSupported(mime)) {
                setStatus(codec.toUpperCase() + ' 当前浏览器不支持');
                cleanupTransport();
                return;
            }
            state.sourceBuffer = state.mediaSource.addSourceBuffer(mime);
            state.sourceBuffer.mode = 'segments';
            state.sourceBuffer.onupdateend = function () {
                appendNext(transportId);
            };
            state.socket.onmessage = function (event) {
                if (!state.open || transportId !== state.transportId || state.socket !== socket) return;
                if (typeof event.data === 'string') {
                    try {
                        var msg = JSON.parse(event.data);
                        if (msg.type === 'error') setStatus(msg.message);
                    } catch (e) { }
                    return;
                }
                state.queue.push(event.data);
                setStatus('');
                appendNext(transportId);
            };
            state.socket.onerror = function () {
                if (transportId === state.transportId) setStatus('实时截图连接错误');
            };
            state.socket.onclose = function () {
                if (state.open && transportId === state.transportId) setStatus('实时截图已断开');
            };
        }, { once: true });
    }

    function getSocketCandidates() {
        var scheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
        var query = '?instance=' + encodeURIComponent(state.instance) +
            '&codec=' + encodeURIComponent(state.codec) + '&fps=5&width=640';
        var candidates = [scheme + location.host + '/ws/live_screenshot' + query];
        var pathParts = location.pathname.split('/').filter(Boolean);
        var firstPart = pathParts.length ? pathParts[0] : '';

        // Alas 远程访问入口通常是 /{sock_name}/...，其中 sock_name 为 8+ 位小写字母数字。
        if (/^[a-z0-9]{8,}$/.test(firstPart)) {
            candidates.unshift(scheme + location.host + '/' + firstPart + '/ws/live_screenshot' + query);
        }

        return candidates;
    }

    function start(instance, codec) {
        var panel = ensurePanel();
        cleanupTransport();
        state.open = true;
        state.instance = instance || 'alas';
        state.codec = codec || state.codec || 'h264';
        panel.style.display = 'block';
        panel.querySelector('.alas-live-preview-codec').value = state.codec;
        setStatus('连接中');
        var transportId = state.transportId;
        var candidates = getSocketCandidates();
        var attempt = 0;

        function connectNext() {
            if (!state.open || transportId !== state.transportId) return;
            if (attempt >= candidates.length) {
                setStatus('实时截图连接失败');
                return;
            }

            var socket = new WebSocket(candidates[attempt++]);
            var ready = false;
            var advanced = false;
            function advance() {
                if (advanced) return;
                advanced = true;
                connectNext();
            }
            socket.binaryType = 'arraybuffer';
            socket.onmessage = function (event) {
                if (transportId !== state.transportId) return;
                if (typeof event.data !== 'string') return;
                var msg;
                try { msg = JSON.parse(event.data); } catch (e) { return; }
                if (msg.type === 'ready') {
                    ready = true;
                    attachMedia(socket, state.codec, msg.mime, transportId);
                } else if (msg.type === 'error') {
                    setStatus(msg.message);
                    socket.close();
                }
            };
            socket.onerror = function () {
                if (!ready) advance();
            };
            socket.onclose = function () {
                if (!state.open || transportId !== state.transportId) return;
                if (!ready && !state.socket) {
                    advance();
                } else if (ready && state.socket === socket) {
                    setStatus('实时截图已断开');
                }
            };
        }

        connectNext();
    }

    window.alasStartLivePreview = function (instance, codec) {
        start(instance, codec);
    };

    window.alasStopLivePreview = function () {
        state.open = false;
        cleanupTransport();
        var panel = ensurePanel();
        panel.style.display = 'none';
    };

    window.alasToggleLivePreview = function (instance) {
        if (state.open) {
            window.alasStopLivePreview();
        } else {
            window.alasStartLivePreview(instance, state.codec);
        }
    };
})();

// ============================================================
// 公告系统
// ============================================================
(function () {
    var STORAGE_KEY = 'alas_shown_announcements';

    window.alasGetShownAnnouncements = function () {
        try {
            var stored = localStorage.getItem(STORAGE_KEY);
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            return [];
        }
    };

    window.alasMarkAnnouncementShown = function (announcementId) {
        try {
            var shown = window.alasGetShownAnnouncements();
            if (shown.indexOf(announcementId) === -1) {
                shown.push(announcementId);
                localStorage.setItem(STORAGE_KEY, JSON.stringify(shown));
            }
        } catch (e) { }
    };

    window.alasHasBeenShown = function (announcementId) {
        var shown = window.alasGetShownAnnouncements();
        return shown.indexOf(announcementId) !== -1;
    };

    window.alasShowAnnouncement = function (title, content, announcementId, url, force) {
        if ((!force && window.alasHasBeenShown(announcementId)) || document.getElementById('alas-announcement-modal')) {
            return;
        }

        // Create modal overlay
        var overlay = document.createElement('div');
        overlay.id = 'alas-announcement-modal';
        overlay.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;background:rgba(0,0,0,0.5);z-index:100000;display:flex;justify-content:center;align-items:center;';

        // Create modal content
        var modal = document.createElement('div');
        var isWeb = !!url;

        if (isWeb) {
            // Web page style: larger, fixed height
            modal.style.cssText = 'background:#fff;border-radius:12px;padding:16px;width:95%;max-width:1200px;height:85vh;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.3);';
        } else {
            // Text style: automatic height, narrower
            modal.style.cssText = 'background:#fff;border-radius:12px;padding:24px;max-width:500px;width:90%;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.3);';
        }

        // Title
        var titleEl = document.createElement('h3');
        titleEl.textContent = title;
        titleEl.style.cssText = 'margin:0 0 12px 0;font-size:1.25rem;color:#333;border-bottom:2px solid #4fc3f7;padding-bottom:8px;flex-shrink:0;';

        modal.appendChild(titleEl);

        // Content (Text or Iframe)
        if (isWeb) {
            var iframe = document.createElement('iframe');
            iframe.src = sanitizeUrl(url);
            iframe.style.cssText = 'flex:1;border:none;width:100%;background:#f5f5f5;border-radius:4px;';
            modal.appendChild(iframe);
        } else {
            var contentEl = document.createElement('div');
            contentEl.textContent = content;
            contentEl.style.cssText = 'font-size:1rem;color:#555;line-height:1.6;margin-bottom:20px;white-space:pre-wrap;';
            modal.appendChild(contentEl);
        }

        // Close button area
        var btnContainer = document.createElement('div');
        btnContainer.style.cssText = 'margin-top:16px;text-align:center;flex-shrink:0;';

        var closeBtn = document.createElement('button');
        closeBtn.textContent = '确认';
        closeBtn.style.cssText = 'background:linear-gradient(90deg,#00b894,#0984e3);color:#fff;border:none;padding:10px 32px;border-radius:6px;cursor:pointer;font-size:1rem;display:inline-block;';
        closeBtn.onmouseover = function () { closeBtn.style.opacity = '0.9'; };
        closeBtn.onmouseout = function () { closeBtn.style.opacity = '1'; };
        closeBtn.onclick = function () {
            window.alasMarkAnnouncementShown(announcementId);
            overlay.remove();
        };

        btnContainer.appendChild(closeBtn);
        modal.appendChild(btnContainer);

        overlay.appendChild(modal);

        // Close on overlay click
        overlay.onclick = function (e) {
            if (e.target === overlay) {
                window.alasMarkAnnouncementShown(announcementId);
                overlay.remove();
            }
        };

        document.body.appendChild(overlay);

        // Apply dark theme if needed
        try {
            var isDark = document.body.classList.contains('pywebio-dark') ||
                document.documentElement.getAttribute('data-theme') === 'dark' ||
                localStorage.getItem('Theme') === 'dark';
            if (isDark) {
                modal.style.background = '#2d3436';
                titleEl.style.color = '#dfe6e9';
                if (!isWeb) {
                    // contentEl only exists in text mode
                    var c = modal.querySelector('div[style*="font-size:1rem"]');
                    if (c) c.style.color = '#b2bec3';
                }
            }
        } catch (e) { }
    };
})();
