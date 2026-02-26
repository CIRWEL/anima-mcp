/* Lumen Shared Utilities */

// ── API Base ──
const API_BASE = window.location.protocol === 'file:' ? 'http://localhost:8768' : window.location.origin;

// ── Utilities ──
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatAge(ts) {
    const secs = (Date.now() / 1000) - ts;
    if (secs < 60) return 'now';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
    return Math.floor(secs / 86400) + 'd ago';
}

function copyId(id, el) {
    navigator.clipboard.writeText(id).then(() => {
        el.classList.add('copied');
        const orig = el.textContent;
        el.textContent = 'copied!';
        setTimeout(() => { el.textContent = orig; el.classList.remove('copied'); }, 1200);
    });
}

async function apiFetch(path) {
    const response = await fetch(`${API_BASE}${path}`);
    return response.json();
}

// ── Lightbox ──
const Lightbox = {
    items: [],
    currentIndex: -1,
    getUrl: null,
    getMeta: null,

    init(items, { getUrl, getMeta } = {}) {
        this.items = items;
        this.getUrl = getUrl || (item => item.url);
        this.getMeta = getMeta || (() => '');

        // Ensure lightbox DOM exists
        if (!document.getElementById('lightbox')) {
            const lb = document.createElement('div');
            lb.id = 'lightbox';
            lb.className = 'lightbox';
            lb.onclick = (e) => this.close(e);
            lb.innerHTML = `
                <span class="lightbox-close" onclick="Lightbox.close(event)">&times;</span>
                <span class="lightbox-nav lightbox-prev" onclick="Lightbox.navigate(event, -1)">&#8249;</span>
                <img id="lightboxImg" src="" alt="Image">
                <span class="lightbox-nav lightbox-next" onclick="Lightbox.navigate(event, 1)">&#8250;</span>
                <div id="lightboxMeta" class="lightbox-meta"></div>
            `;
            document.body.appendChild(lb);
        }
    },

    open(index) {
        if (index < 0 || index >= this.items.length) return;
        this.currentIndex = index;
        const item = this.items[index];

        document.getElementById('lightboxImg').src = this.getUrl(item);
        document.getElementById('lightboxMeta').textContent = this.getMeta(item, index);
        document.getElementById('lightbox').classList.add('show');
        document.body.style.overflow = 'hidden';
    },

    close(event) {
        if (event && event.target.tagName === 'IMG') return;
        if (event && event.target.classList.contains('lightbox-nav')) return;
        document.getElementById('lightbox').classList.remove('show');
        document.body.style.overflow = '';
        this.currentIndex = -1;
    },

    navigate(event, direction) {
        if (event) event.stopPropagation();
        const newIndex = this.currentIndex + direction;
        if (newIndex >= 0 && newIndex < this.items.length) {
            this.open(newIndex);
        }
    }
};

// Global lightbox keyboard handler
document.addEventListener('keydown', (e) => {
    if (Lightbox.currentIndex === -1) return;
    if (e.key === 'Escape') Lightbox.close(e);
    if (e.key === 'ArrowLeft') Lightbox.navigate(e, -1);
    if (e.key === 'ArrowRight') Lightbox.navigate(e, 1);
});

// ── Collapsible Cards ──
function initCollapsibleCards() {
    document.querySelectorAll('.card-header-collapsible').forEach(header => {
        const cardId = header.dataset.cardId;
        const body = header.nextElementSibling;
        if (!body || !body.classList.contains('card-body-collapsible')) return;

        // Restore saved state
        const saved = localStorage.getItem(`lumen-card-${cardId}`);
        if (saved === 'collapsed') {
            header.classList.add('collapsed');
            body.classList.add('collapsed');
        }

        header.addEventListener('click', (e) => {
            // Don't collapse when clicking buttons inside the header
            if (e.target.closest('.refresh-btn') || e.target.closest('a') || e.target.closest('button:not(.card-header-collapsible)')) return;

            const isCollapsed = header.classList.toggle('collapsed');
            body.classList.toggle('collapsed');
            localStorage.setItem(`lumen-card-${cardId}`, isCollapsed ? 'collapsed' : 'expanded');
        });
    });
}

// ── Sparkline Class ──
class Sparkline {
    constructor(canvas, { color = '#00ffff', maxPoints = 30, lineWidth = 1.5 } = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.color = color;
        this.maxPoints = maxPoints;
        this.lineWidth = lineWidth;
        this.data = [];
        // Store CSS (logical) dimensions for HiDPI-correct drawing.
        // The canvas context is pre-scaled by devicePixelRatio, so we draw
        // in CSS pixels, not pixel buffer dimensions.
        this.w = parseInt(canvas.style.width) || canvas.width;
        this.h = parseInt(canvas.style.height) || canvas.height;
    }

    push(value) {
        this.data.push(value);
        if (this.data.length > this.maxPoints) {
            this.data.shift();
        }
        this.draw();
    }

    draw() {
        const { ctx, data, color, lineWidth, w, h } = this;
        ctx.clearRect(0, 0, w, h);

        if (data.length < 2) return;

        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = max - min || 1;

        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.lineJoin = 'round';

        data.forEach((val, i) => {
            const x = (i / (data.length - 1)) * w;
            const y = h - ((val - min) / range) * (h - 4) - 2;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Fill under the line
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.globalAlpha = 0.06;
        ctx.fillStyle = color;
        ctx.fill();
        ctx.globalAlpha = 1;
    }
}

// ── Nav Bar Injection ──
function initNav(activePage) {
    const pages = [
        { id: 'dashboard', label: 'Dashboard', href: '/dashboard' },
        { id: 'architecture', label: 'Architecture', href: '/architecture' },
        { id: 'schema', label: 'Schema', href: '/schema' },
        { id: 'gallery', label: 'Gallery', href: '/gallery-page' },
    ];

    const nav = document.createElement('nav');
    nav.className = 'nav-bar';
    nav.innerHTML = `
        <div class="nav-logo"></div>
        <div class="nav-links">
            ${pages.map(p => `<a href="${p.href}" class="nav-link${p.id === activePage ? ' active' : ''}">${p.label}</a>`).join('')}
        </div>
    `;

    document.body.insertBefore(nav, document.body.firstChild);
}

// ── Value Flash ──
const _prevValues = {};

function flashOnChange(element, newValue) {
    const key = element.id || element.dataset.metric;
    if (!key) return;

    const prev = _prevValues[key];
    _prevValues[key] = newValue;

    if (prev !== undefined && prev !== newValue) {
        element.classList.remove('value-flash');
        // Force reflow to restart animation
        void element.offsetWidth;
        element.classList.add('value-flash');
    }
}
