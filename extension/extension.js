// limitlens — AI CLI usage limits in the GNOME top bar.
// Inspired by the macOS menu bar app CodexBar.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const READ_INTERVAL_SEC = 5;      // re-read stats.json (a few KB)
const COLLECT_INTERVAL_SEC = 120; // re-run the collector
const OPEN_COLLECT_MIN_SEC = 30;  // throttle for the collect on menu open

function fullProviderName(provider) {
    if (!provider) return 'AI Provider';
    const lower = provider.toLowerCase();
    if (lower.includes('claude')) return 'Claude';
    if (lower.includes('antigravity')) return 'Antigravity';
    return provider;
}

function providerGlyph(name) {
    if (!name) return '🤖';
    const lower = name.toLowerCase();
    if (lower.includes('claude')) return '✦';
    if (lower.includes('antigravity')) return '✨';
    return '🤖';
}

function createProviderIconWidget(extPath, provider) {
    if (extPath && provider) {
        const lower = provider.toLowerCase();
        let iconName = null;
        if (lower.includes('claude')) iconName = 'claude.svg';
        else if (lower.includes('antigravity')) iconName = 'antigravity.svg';

        if (iconName) {
            const iconPath = GLib.build_filenamev([extPath, 'icons', iconName]);
            if (GLib.file_test(iconPath, GLib.FileTest.EXISTS)) {
                const file = Gio.File.new_for_path(iconPath);
                const gicon = new Gio.FileIcon({ file });
                return new St.Icon({
                    gicon,
                    icon_size: 18,
                    style_class: 'limitlens-card-icon',
                    y_align: Clutter.ActorAlign.CENTER,
                });
            }
        }
    }
    
    return new St.Label({
        text: providerGlyph(provider),
        y_align: Clutter.ActorAlign.CENTER,
        style_class: 'limitlens-card-icon-fallback',
    });
}

const DATA_DIR = GLib.build_filenamev([GLib.get_user_data_dir(), 'limitlens']);
const STATS_FILE = GLib.build_filenamev([DATA_DIR, 'stats.json']);
const LIB_DIR = GLib.build_filenamev([DATA_DIR, 'lib']);
const PYTHON = GLib.find_program_in_path('python3') ||
               GLib.find_program_in_path('python') ||
               '/usr/bin/python3';

const PIE_GLYPHS = ['○', '◔', '◑', '◕', '●'];

function pieGlyph(percent) {
    const index = Math.min(PIE_GLYPHS.length - 1,
        Math.max(0, Math.round((percent / 100) * (PIE_GLYPHS.length - 1))));
    return PIE_GLYPHS[index];
}

function fmtReset(secondsLeft) {
    if (secondsLeft === null || secondsLeft === undefined)
        return '';
    secondsLeft = Math.round(secondsLeft);
    if (secondsLeft <= 0)
        return 'now';
    const days = Math.floor(secondsLeft / 86400);
    const hours = Math.floor((secondsLeft % 86400) / 3600);
    const minutes = Math.floor((secondsLeft % 3600) / 60);
    if (days)
        return hours ? `${days}d ${hours}h` : `${days}d`;
    if (hours)
        return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
    return `${Math.max(minutes, 1)}m`;
}

function fmtExactReset(epochSec) {
    if (!epochSec)
        return '';
    const date = new Date(epochSec * 1000);
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    if (isToday)
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const diffDays = (epochSec - Date.now() / 1000) / 86400;
    if (diffDays < 6)
        return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
    return date.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function severityClass(severity) {
    if (severity === 'critical')
        return 'limitlens-critical';
    if (severity === 'warning')
        return 'limitlens-warning';
    return 'limitlens-normal';
}

const LimitLensIndicator = GObject.registerClass(
class LimitLensIndicator extends PanelMenu.Button {
    _init(extPath) {
        super._init(0.5, 'LimitLens');
        this._extPath = extPath;

        this._label = new St.Label({
            text: '…',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'limitlens-label limitlens-normal',
        });
        this.add_child(this._label);

        this._signature = '';
        this._rows = [];
        this._collecting = false;
        this._lastCollect = 0;
        this._lastMtime = 0;

        this._limitSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._limitSection);

        this._warningItem = new PopupMenu.PopupMenuItem('', {
            reactive: false,
            can_focus: false,
        });
        this._warningItem.label.style_class = 'limitlens-dim';
        this._warningItem.visible = false;
        this.menu.addMenuItem(this._warningItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const refresh = new PopupMenu.PopupMenuItem('Refresh');
        refresh.connect('activate', () => this._collect(true));
        this.menu.addMenuItem(refresh);

        this.menu.connect('open-state-changed', (_menu, open) => {
            if (!open)
                return;
            this._read(true);
            const now = GLib.get_monotonic_time() / 1e6;
            if (now - this._lastCollect > OPEN_COLLECT_MIN_SEC)
                this._collect(false);
        });

        try {
            GLib.mkdir_with_parents(DATA_DIR, 0o755);
            const statsFile = Gio.File.new_for_path(STATS_FILE);
            this._fileMonitor = statsFile.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._fileMonitorSignal = this._fileMonitor.connect('changed', () => this._read(true));
        } catch (e) {
            console.warn(`limitlens: file monitor: ${e.message}`);
        }

        this._collectTimeout = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, COLLECT_INTERVAL_SEC, () => {
                this._collect(false);
                return GLib.SOURCE_CONTINUE;
            });

        this._read();
        this._collect(false);
    }

    // ----- collector -----

    _collect(force) {
        if (this._collecting)
            return;
        this._collecting = true;
        this._lastCollect = GLib.get_monotonic_time() / 1e6;

        const argv = [PYTHON, '-m', 'limitlens', '--once'];
        if (force)
            argv.push('--force');

        try {
            const launcher = new Gio.SubprocessLauncher({
                flags: Gio.SubprocessFlags.STDOUT_SILENCE |
                       Gio.SubprocessFlags.STDERR_PIPE,
            });
            launcher.set_cwd(LIB_DIR);
            const env = GLib.get_environ();
            env.push(`PYTHONPATH=${LIB_DIR}`);
            launcher.set_environ(env);
            const proc = launcher.spawnv(argv);
            proc.communicate_utf8_async(null, null, (source, res) => {
                this._collecting = false;
                try {
                    const [, , stderr] = source.communicate_utf8_finish(res);
                    if (!source.get_successful() && stderr)
                        console.warn(`limitlens: collector: ${stderr.trim()}`);
                } catch (e) {
                    console.warn(`limitlens: collector: ${e.message}`);
                }
                this._read();
            });
        } catch (e) {
            this._collecting = false;
            console.warn(`limitlens: could not run collector: ${e.message}`);
        }
    }

    // ----- rendering -----

    _read(force = false) {
        let stats = null;
        try {
            const info = Gio.File.new_for_path(STATS_FILE)
                .query_info('time::modified', Gio.FileQueryInfoFlags.NONE, null);
            const mtime = info.get_attribute_uint64('time::modified');
            if (!force && mtime === this._lastMtime && !this.menu.isOpen)
                return;
            this._lastMtime = mtime;

            const [ok, bytes] = GLib.file_get_contents(STATS_FILE);
            if (ok)
                stats = JSON.parse(new TextDecoder().decode(bytes));
        } catch {
            // not collected yet
        }
        if (!stats)
            return;

        this._stats = stats;
        this._updatePanel(stats);
        if (this.menu.isOpen || !this._signature)
            this._updateMenu(stats);
    }

    _updatePanel(stats) {
        const panel = stats.panel;
        if (!panel) {
            this._label.text = '—';
            this._label.style_class = 'limitlens-label limitlens-normal';
            return;
        }
        const stale = panel.stale ? '*' : '';
        this._label.text =
            `${pieGlyph(panel.percent)} ${Math.round(panel.percent)}%${stale}`;
        this._label.style_class =
            `limitlens-label ${severityClass(panel.severity)}`;
    }

    _signatureFor(stats) {
        return (stats.limits || [])
            .map(l => `${l.provider}/${l.label}`).join(',');
    }

    _updateMenu(stats) {
        const signature = this._signatureFor(stats);
        if (signature !== this._signature) {
            this._rebuild(stats);
            this._signature = signature;
        }
        this._refresh(stats);
    }

    _rebuild(stats) {
        this._limitSection.removeAll();
        this._rows = [];

        const limits = stats.limits || [];
        if (!limits.length) {
            const empty = new PopupMenu.PopupMenuItem('No limits available', {
                reactive: false,
                can_focus: false,
            });
            empty.label.style_class = 'limitlens-dim';
            this._limitSection.addMenuItem(empty);
            return;
        }

        let provider = null;
        for (const limit of limits) {
            if (limit.provider !== provider) {
                provider = limit.provider;
                
                const headerItem = new PopupMenu.PopupBaseMenuItem({
                    reactive: false,
                    can_focus: false,
                });
                const headerBox = new St.BoxLayout({
                    x_expand: true,
                    style_class: 'limitlens-card-header',
                });

                const iconWidget = createProviderIconWidget(this._extPath, limit.provider);
                headerBox.add_child(iconWidget);

                const titleLabel = new St.Label({
                    text: fullProviderName(limit.provider),
                    y_align: Clutter.ActorAlign.CENTER,
                    x_expand: true,
                    style_class: 'limitlens-card-title',
                });
                headerBox.add_child(titleLabel);

                if (limit.plan) {
                    const badge = new St.Label({
                        text: limit.plan,
                        y_align: Clutter.ActorAlign.CENTER,
                        style_class: 'limitlens-plan-badge',
                    });
                    headerBox.add_child(badge);
                }

                headerItem.add_child(headerBox);
                this._limitSection.addMenuItem(headerItem);
            }
            const row = this._makeRow(limit.label);
            row.key = `${limit.provider}/${limit.label}`;
            this._rows.push(row);
        }
    }

function formatRowLabel(label) {
    if (!label) return '';
    return label
        .replace(/ and /gi, ' & ')
        .replace(/\bWeekly\b/gi, 'W');
}

    _makeRow(label) {
        const item = new PopupMenu.PopupBaseMenuItem({
            reactive: false,
            can_focus: false,
        });
        const box = new St.BoxLayout({x_expand: true, style_class: 'limitlens-row'});

        const left = new St.Label({
            text: formatRowLabel(label),
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'limitlens-row-label',
        });
        box.add_child(left);

        // Segmented Bar Chart Outer Box (10 Columns + Percent Tag)
        const barBox = new St.BoxLayout({
            style_class: 'limitlens-barchart-box',
            y_align: Clutter.ActorAlign.CENTER,
        });

        const segContainer = new St.BoxLayout({
            style_class: 'limitlens-seg-container',
            y_align: Clutter.ActorAlign.CENTER,
        });

        const segBars = [];
        for (let i = 0; i < 10; i++) {
            const seg = new St.Widget({
                style_class: 'limitlens-seg-bar',
            });
            segContainer.add_child(seg);
            segBars.push(seg);
        }
        barBox.add_child(segContainer);

        const percentTag = new St.Label({
            text: '0%',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'limitlens-percent-tag',
        });
        barBox.add_child(percentTag);

        box.add_child(barBox);

        const right = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.END,
            x_expand: true,
            style_class: 'limitlens-row-value',
        });
        box.add_child(right);

        item.add_child(box);
        this._limitSection.addMenuItem(item);
        return {item, left, segBars, percentTag, right};
    }

    _refresh(stats) {
        const now = Date.now() / 1000;
        const limits = new Map(
            (stats.limits || []).map(l => [`${l.provider}/${l.label}`, l]));

        for (const row of this._rows) {
            const limit = limits.get(row.key);
            if (!limit)
                continue;

            const percent = Math.min(Math.max(limit.percent, 0), 100);
            const activeCount = Math.round((percent / 100) * 10);
            const sev = limit.severity || 'normal';

            for (let i = 0; i < 10; i++) {
                if (i < activeCount) {
                    row.segBars[i].style_class = `limitlens-seg-bar active-${sev}`;
                } else {
                    row.segBars[i].style_class = 'limitlens-seg-bar';
                }
            }

            row.percentTag.text = `${Math.round(percent)}%`;
            row.percentTag.style_class = `limitlens-percent-tag ${severityClass(limit.severity)}`;

            let reset = '';
            if (limit.resets_at) {
                const remaining = fmtReset(limit.resets_at - now);
                const exact = fmtExactReset(limit.resets_at);
                reset = remaining ? `in ${remaining}` : exact;
            }
            row.right.text = reset;
        }

        const warnings = stats.warnings || [];
        this._warningItem.visible = warnings.length > 0;
        if (warnings.length)
            this._warningItem.label.text = warnings.join('  ·  ');
    }

    destroy() {
        if (this._fileMonitor) {
            if (this._fileMonitorSignal)
                this._fileMonitor.disconnect(this._fileMonitorSignal);
            this._fileMonitor.cancel();
            this._fileMonitor = null;
        }
        if (this._collectTimeout) {
            GLib.source_remove(this._collectTimeout);
            this._collectTimeout = null;
        }
        super.destroy();
    }
});

export default class LimitLensExtension extends Extension {
    enable() {
        this._indicator = new LimitLensIndicator(this.path);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
