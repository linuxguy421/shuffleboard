#!/usr/bin/env python3

import tkinter as ttk
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk
from math import log2, ceil
import sys
import re
import random
import os
from collections import OrderedDict
import datetime
import time
import json
import threading

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# --- Version ---
SHUF_VERSION = "1.74B"

# =============================================================================
# --- Flipper Zero IR Module ---
# Sends IR commands to a digital scoreboard via Flipper Zero over USB serial.
# Uses pyserial (pip install pyserial). Fails silently if not connected so the
# app works normally without the Flipper attached.
# =============================================================================

# Flipper Zero USB identifiers (consistent across all platforms)
FLIPPER_VID = 0x0483
FLIPPER_PID = 0x5740

# --- IR Code Map (NEC protocol) ---
# Address and command are plain hex strings (no 0x prefix) taken directly
# from the .ir file's first byte. Flipper CLI does not accept 0x-prefixed args.
# file: "address: 00 00 00 00" -> "00"
# file: "command: 17 00 00 00" -> "17"
IR_CODES = {
    'reset':      ('NEC', '00', '03'),
    'blue_up':    ('NEC', '00', '09'),
    'red_up':     ('NEC', '00', '17'),
    'blue_down':  ('NEC', '00', '19'),
    'red_down':   ('NEC', '00', '50'),
}

# Minimum delay (seconds) between consecutive IR sends to avoid the scoreboard
# dropping rapid-fire commands. 0.15 s is a safe starting point for NEC devices.
IR_SEND_DELAY = 0.15

# --- Internal State ---
_flipper_port = None        # Open serial.Serial instance, or None
_flipper_lock = threading.Lock()  # Serialise writes from multiple threads
_ir_last_sent = 0.0         # Timestamp of last successful IR send

def flipper_connect():
    """
    Scan serial ports for a Flipper Zero by USB VID/PID and open it.
    Returns True if connected, False otherwise.
    Safe to call multiple times — skips if already open.
    """
    global _flipper_port

    if not SERIAL_AVAILABLE:
        log_message("pyserial not installed — Flipper IR disabled. Run: pip install pyserial", "WARN")
        return False

    with _flipper_lock:
        if _flipper_port and _flipper_port.is_open:
            return True  # Already connected

        for port_info in serial.tools.list_ports.comports():
            if port_info.vid == FLIPPER_VID and port_info.pid == FLIPPER_PID:
                try:
                    _flipper_port = serial.Serial(
                        port_info.device,
                        baudrate=230400,
                        timeout=1,
                        write_timeout=1,
                    )
                    log_message(f"Flipper Zero connected on {port_info.device}")
                    return True
                except Exception as e:
                    log_message(f"Flipper found on {port_info.device} but failed to open: {e}", "WARN")
                    return False

    log_message("Flipper Zero not found on any serial port", "WARN")
    return False

def flipper_disconnect():
    """Cleanly close the serial connection."""
    global _flipper_port
    with _flipper_lock:
        if _flipper_port and _flipper_port.is_open:
            _flipper_port.close()
            _flipper_port = None
            log_message("Flipper Zero disconnected")

def _send_ir_blocking(action, repeat=1):
    """
    Internal: sends an IR command `repeat` times with IR_SEND_DELAY between
    each send. Runs in a background thread. Skips if not connected, and if a
    mid-session disconnect is detected it updates the footer UI so the user can
    use the Reconnect button to re-establish the connection.
    """
    global _flipper_port, _ir_last_sent

    if action not in IR_CODES:
        log_message(f"IR action '{action}' not found in IR_CODES map", "WARN")
        return

    protocol, address, command = IR_CODES[action]
    cmd_str = f"ir tx {protocol} {address} {command}\r\n"

    with _flipper_lock:
        if not _flipper_port or not _flipper_port.is_open:
            log_message(f"IR send skipped ({action}) — Flipper not connected", "WARN")
            return

    for i in range(repeat):
        # Enforce minimum gap between any two consecutive IR sends
        now = time.time()
        gap = IR_SEND_DELAY - (now - _ir_last_sent)
        if gap > 0:
            time.sleep(gap)
        try:
            with _flipper_lock:
                _flipper_port.write(cmd_str.encode("ascii"))
            _ir_last_sent = time.time()
            log_message(f"IR sent ({i+1}/{repeat}): {cmd_str.strip()}", "DEBUG")
        except Exception as e:
            log_message(f"IR send failed ({action}): {e} — Flipper disconnected", "WARN")
            with _flipper_lock:
                _flipper_port = None
            # Notify the UI on the main thread so footer shows disconnected state
            _notify_flipper_disconnected()
            break  # Don't retry remaining repeats on a port error

def _notify_flipper_disconnected():
    """
    Called from a background thread when a mid-session IR write failure reveals
    the Flipper has been unplugged. Schedules a UI update on the main thread.
    """
    global main_root
    if main_root:
        try:
            fn = ui_references.get('_set_flipper_ui')
            if fn:
                main_root.after(0, lambda: fn(False))
        except Exception:
            pass

def ir_send(action, repeat=1):
    """
    Public: fire-and-forget IR send. Optional repeat for correction sends.
    Dispatches to a daemon thread so it never blocks the Tkinter UI.
    """
    t = threading.Thread(target=_send_ir_blocking, args=(action, repeat), daemon=True)
    t.start()

def ir_correct(color, current_val, target_val):
    """
    Sends the minimum number of up/down IR commands to reconcile the
    scoreboard with the on-screen counter after a missed signal.
    color: 'red' or 'blue'
    current_val: what the scoreboard currently shows
    target_val:  what it should show
    """
    diff = target_val - current_val
    if diff == 0:
        return
    action = f"{color}_up" if diff > 0 else f"{color}_down"
    ir_send(action, repeat=abs(diff))
    log_message(f"IR correction: {color} {current_val} -> {target_val} ({abs(diff)}x {action})")

# =============================================================================

# --- Theme Configuration ---
THEME = {
    'bg_main': '#263238',       # Dark Blue-Grey
    'bg_card': '#37474F',       # Lighter Blue-Grey for frames
    'bg_canvas': '#455A64',     # Slate for Bracket Background
    'fg_primary': '#ECEFF1',    # White-ish text
    'fg_secondary': '#B0BEC5',  # Light Grey text
    'red_team': '#E53935',      # Vermilion Red
    'blue_team': '#1E88E5',     # Dodger Blue
    'accent_gold': '#FFD700',   # Gold for winners/champs
    'btn_default': '#546E7A',   # Blue-Grey Button
    'btn_confirm': '#43A047',   # Green
    'btn_cancel': '#D32F2F',    # Red
    'btn_yellow': '#FFFF00',    # Yellow
    'font_main': ('Selawik', 10),
    'font_bold': ('Selawik', 10, 'bold'),
    'font_header': ('Selawik', 14, 'bold'),
    'font_title': ('Selawik', 18, 'bold'),
}

# --- Global & Tournament Variables ---
TEAMS = []
TEAM_ROSTERS = {}
TOURNAMENT_RANKINGS = OrderedDict()
ENTRY_FEE_PER_PERSON = 5
MIN_PLAYERS = 6
MAX_PLAYERS = 20
MATCH_HISTORY = []  # Tracks completed matches: {'id': id, 'winner': name, 'loser': name, 'color': color}
schedule_content_frame = None # Reference for refreshing the UI
TOURNAMENT_STATE = {}
REPLAY_FILEPATH = None # Initialized to None, set only on New Game or Resume
REPLAY_MODE = False
REPLAY_VIEW_ONLY = False
SNAPSHOT_VERSION = 1
scoreboard_canvas_ref = None
bracket_canvas = None
status_label = None
match_res_frame = None
current_match_res_buttons = []
team_labels = {'red': None, 'blue': None}
player_labels_ref = {'red': None, 'blue': None}
main_root = None
match_input_frame = None
btn_red = None
btn_blue = None
btn_switch = None
current_match_teams = {'red': None, 'blue': None}
last_assigned_match_id = None
switch_frame_ref = None
full_bracket_root = None
full_bracket_canvas = None
LOG_GAME_TO_FILE = False
LOG_FILE_HANDLE = None
final_control_frame_ref = None
match_details_frame = None
game_routing_label = None
team_info_labels = {'red': None, 'blue': None}
bracket_info_canvas_ref = None
rankings_label_ref = None
bracket_info_frame_ref = None
team_info_frame_ref = None
rankings_display_frame_ref = None
match_timer_id = None
MATCH_DURATIONS = []        # List of completed match durations (seconds)
TOURNAMENT_START_TIME = None

# --- Console Logging Function ---
def log_message(message, level="INFO"):
    """Prints a leveled, timestamped message to the console and log file (if enabled).
    Levels: DEBUG, INFO, WARN, ERROR
    """
    global LOG_GAME_TO_FILE, LOG_FILE_HANDLE
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level:<5}] {message}"

    print(log_line)

    if LOG_GAME_TO_FILE and LOG_FILE_HANDLE:
        LOG_FILE_HANDLE.write(log_line + "\n")
        LOG_FILE_HANDLE.flush()

# --- System Functions ---
def _find_last_snapshot_in_file(path):
    """
    Read the file forward and return the last SNAPSHOT object.
    Safe and simple for normal replay file sizes.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    last_snapshot = None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("type") == "SNAPSHOT":
                    last_snapshot = obj
            except Exception:
                continue

    return last_snapshot

# --- Global References for New UI ---
ui_references = {
    'notebook': None,
    'match_tab_frame': None,
    'red_card_frame': None,
    'blue_card_frame': None,
    'red_name_lbl': None,
    'red_roster_lbl': None,
    'red_stats_lbl': None,
    'blue_name_lbl': None,
    'blue_roster_lbl': None,
    'blue_stats_lbl': None,
    'info_lbl': None,
    'vs_label': None,
    # Win animation state
    '_win_flash_job': None,     # pending after() id for flash loop
    '_win_glow_job': None,      # pending after() id for glow cancel
    '_win_color': None,         # 'red' | 'blue' | None
    '_win_debounce_job': None,  # pending after() id for settle delay
}

def update_footer_log_status():
    """Updates footer to reflect persistent game logging state (from Player Setup)."""
    global ui_references, LOG_GAME_TO_FILE, REPLAY_MODE, REPLAY_VIEW_ONLY

    lbl = ui_references.get('footer_file_status')
    if not lbl:
        return

    if REPLAY_VIEW_ONLY:
        text = "📁 VIEW ONLY"
        color = THEME['fg_secondary']
    elif REPLAY_MODE:
        text = "🔴 REPLAY MODE"
        color = THEME['fg_secondary']
    else:
        if LOG_GAME_TO_FILE:
            text = "🟢 LOG GAME TO FILE: ON"
            color = THEME['accent_gold']
        else:
            text = "⚪ LOG GAME TO FILE: OFF"
            color = THEME['fg_secondary']

    lbl.config(text=text, fg=color)

def add_late_team():
    """
    Adds a late-arriving team by prompting for two player names, then rebuilds
    the bracket for N+1 teams. G1 (currently in progress) is preserved exactly.
    Only available before any match has been completed.
    """
    global TEAMS, TEAM_ROSTERS, TOURNAMENT_STATE, REPLAY_FILEPATH

    # Safety check — should not be reachable, but guard anyway
    if MATCH_HISTORY:
        messagebox.showwarning("Late Entry", "Cannot add a team after matches have been completed.")
        return

    active_id = TOURNAMENT_STATE.get('active_match_id')
    if active_id != 'G1':
        return

    # --- Dialog for new player names ---
    dialog = tk.Toplevel(main_root)
    dialog.title("Late Entry — Add Team")
    dialog.configure(bg=THEME['bg_main'])
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.geometry("360x220")

    tk.Label(dialog, text="Late Team Entry", font=THEME['font_header'],
             bg=THEME['bg_main'], fg=THEME['accent_gold']).pack(pady=(18, 4))
    tk.Label(dialog, text="Enter names for the two new players:",
             font=THEME['font_main'], bg=THEME['bg_main'],
             fg=THEME['fg_secondary']).pack(pady=(0, 12))

    entry_frame = tk.Frame(dialog, bg=THEME['bg_main'])
    entry_frame.pack()

    tk.Label(entry_frame, text="Player 1:", font=THEME['font_main'],
             bg=THEME['bg_main'], fg=THEME['fg_primary'], width=10, anchor='e').grid(row=0, column=0, padx=6, pady=6)
    p1_entry = tk.Entry(entry_frame, bg=THEME['bg_card'], fg=THEME['fg_primary'],
                        insertbackground=THEME['fg_primary'], relief='flat', font=THEME['font_main'], width=22)
    p1_entry.grid(row=0, column=1, padx=6, pady=6)

    tk.Label(entry_frame, text="Player 2:", font=THEME['font_main'],
             bg=THEME['bg_main'], fg=THEME['fg_primary'], width=10, anchor='e').grid(row=1, column=0, padx=6, pady=6)
    p2_entry = tk.Entry(entry_frame, bg=THEME['bg_card'], fg=THEME['fg_primary'],
                        insertbackground=THEME['fg_primary'], relief='flat', font=THEME['font_main'], width=22)
    p2_entry.grid(row=1, column=1, padx=6, pady=6)

    result = [None]

    def _confirm():
        p1 = p1_entry.get().strip()
        p2 = p2_entry.get().strip()
        if not p1 or not p2:
            messagebox.showerror("Missing Names", "Both player names are required.", parent=dialog)
            return
        result[0] = (p1, p2)
        dialog.destroy()

    btn_row = tk.Frame(dialog, bg=THEME['bg_main'])
    btn_row.pack(pady=(14, 0))
    tk.Button(btn_row, text="✓ Add Team", bg=THEME['btn_confirm'], fg='white',
              relief='flat', padx=16, pady=5, font=THEME['font_main'],
              command=_confirm).pack(side='left', padx=8)
    tk.Button(btn_row, text="Cancel", bg=THEME['btn_cancel'], fg='white',
              relief='flat', padx=16, pady=5, font=THEME['font_main'],
              command=dialog.destroy).pack(side='left', padx=8)

    p1_entry.focus_set()
    main_root.wait_window(dialog)

    if result[0] is None:
        return  # Cancelled

    p1_name, p2_name = result[0]

    # --- Snapshot G1 state so we can restore it after rebuilding ---
    g1_snapshot = dict(TOURNAMENT_STATE['G1'])
    g1_snapshot['config'] = dict(TOURNAMENT_STATE['G1']['config'])

    # --- Add the new team ---
    new_team_name = f"Team {len(TEAMS) + 1}"
    TEAMS.append(new_team_name)
    TEAM_ROSTERS[new_team_name] = [p1_name, p2_name]
    log_message(f"Late entry: {new_team_name} ({p1_name} & {p2_name}) added — rebuilding bracket")

    # --- Load new bracket config for N+1 teams ---
    try:
        new_config, _ = load_bracket_config(len(TEAMS), 'D')
    except Exception as e:
        # Rollback
        TEAMS.pop()
        del TEAM_ROSTERS[new_team_name]
        messagebox.showerror("Late Entry Error",
                             f"No bracket config found for {len(TEAMS)} teams.\n{e}")
        return

    # --- Rebuild TOURNAMENT_STATE using existing generator, then restore G1 ---
    # generate_dynamic_bracket handles all seeding correctly for any bracket size
    generate_dynamic_bracket(TEAMS, new_config)

    # Restore G1 live match state (teams, timer, pause etc.) but keep the NEW
    # config routing — the new bracket may route G1's winner/loser differently.
    new_g1_config = TOURNAMENT_STATE['G1']['config']
    TOURNAMENT_STATE['G1'].update({
        'teams':            g1_snapshot['teams'],
        'winner':           g1_snapshot['winner'],
        'winner_color':     g1_snapshot['winner_color'],
        'is_reset':         g1_snapshot['is_reset'],
        'start_time':       g1_snapshot.get('start_time'),
        'timer_paused':     g1_snapshot.get('timer_paused', True),
        'elapsed_at_pause': g1_snapshot.get('elapsed_at_pause', 0),
        '_paused_since':    g1_snapshot.get('_paused_since'),
        '_flash_state':     g1_snapshot.get('_flash_state', False),
        'config':           new_g1_config,
    })
    TOURNAMENT_STATE['active_match_id'] = 'G1'

    # --- Refresh all UI without disturbing the active match ---
    update_schedule_tab()
    update_roster_seeding_vertical()
    update_scoreboard_display()

    if bracket_info_canvas_ref:
        draw_small_bracket_view(bracket_info_canvas_ref, TOURNAMENT_STATE)
    if full_bracket_root and full_bracket_canvas:
        try:
            draw_large_bracket(full_bracket_canvas)
        except Exception:
            pass

    if REPLAY_FILEPATH:
        append_snapshot_to_file(REPLAY_FILEPATH)

    log_message(f"Bracket rebuilt for {len(TEAMS)} teams. G1 preserved and still active.")
    messagebox.showinfo("Late Entry", f"{new_team_name} ({p1_name} & {p2_name}) added!\nBracket updated for {len(TEAMS)} teams.")


WIN_SCORE = 15   # Score needed to trigger a win

# Dim glow colours (darker than the team colour, used for persistent win state)
_WIN_GLOW = {'red': '#5C1A1A', 'blue': '#0D2B4A'}
# Bright flash colour alternates between team colour and the glow
_WIN_FLASH = {'red': THEME['red_team'], 'blue': THEME['blue_team']}

def _cancel_win_animation():
    """Cancel any in-progress flash/glow and restore both cards to normal bg."""
    global ui_references, main_root
    for job_key in ('_win_flash_job', '_win_glow_job', '_win_debounce_job'):
        job = ui_references.get(job_key)
        if job:
            try:
                main_root.after_cancel(job)
            except Exception:
                pass
            ui_references[job_key] = None
    ui_references['_win_color'] = None
    # Restore card backgrounds
    for color in ('red', 'blue'):
        card = ui_references.get(f'{color}_card_frame')
        if card:
            _set_card_bg(card, THEME['bg_card'])

def _set_card_bg(card, bg_color):
    """Recursively set bg on a card frame and all its child widgets."""
    try:
        card.config(bg=bg_color)
        for child in card.winfo_children():
            try:
                child.config(bg=bg_color)
            except Exception:
                pass
            # One level deeper for nested frames (counter frame, etc.)
            try:
                for grandchild in child.winfo_children():
                    try:
                        grandchild.config(bg=bg_color)
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass

def _start_win_animation(winner_color):
    """
    Flash the winning card rapidly for FLASH_DURATION seconds, then
    settle into a persistent dim glow until the next match resets it.
    """
    global ui_references, main_root

    _cancel_win_animation()   # clear any previous animation first
    ui_references['_win_color'] = winner_color

    card = ui_references.get(f'{winner_color}_card_frame')
    if not card:
        return

    FLASH_DURATION  = 3000   # ms total flash period
    FLASH_INTERVAL  = 180    # ms per flash half-cycle
    glow_color      = _WIN_GLOW[winner_color]
    bright_color    = _WIN_FLASH[winner_color]
    flash_end_time  = main_root.tk.call('clock', 'milliseconds') + FLASH_DURATION
    flash_state     = [False]   # mutable so inner func can toggle it

    def _flash_tick():
        now = main_root.tk.call('clock', 'milliseconds')
        if now >= flash_end_time:
            # Flash done — settle into glow
            _set_card_bg(card, glow_color)
            ui_references['_win_flash_job'] = None
            return
        flash_state[0] = not flash_state[0]
        _set_card_bg(card, bright_color if flash_state[0] else glow_color)
        ui_references['_win_flash_job'] = main_root.after(FLASH_INTERVAL, _flash_tick)

    _flash_tick()

WIN_SETTLE_DELAY = 5000  # ms to wait after last button press before checking win

def _evaluate_win():
    """
    The actual win check — runs after the settle delay has elapsed with no
    further button activity.

    Rules:
      - A team wins by reaching WIN_SCORE (15).
      - If both teams are >= WIN_SCORE (e.g. 20-18), the higher score wins.
      - If both scores are exactly equal and >= WIN_SCORE, do nothing and
        wait for one to pull ahead (next button press will reschedule).
    """
    ui_references['_win_debounce_job'] = None

    if ui_references.get('_win_color'):
        return   # already animating

    red_val  = ui_references['red_counter_var'].get()
    blue_val = ui_references['blue_counter_var'].get()

    red_wins  = red_val  >= WIN_SCORE
    blue_wins = blue_val >= WIN_SCORE

    if not red_wins and not blue_wins:
        return   # nobody at 15 yet

    if red_wins and blue_wins:
        if red_val == blue_val:
            # Dead heat — can't determine winner yet, wait for next press
            log_message(f"Scores tied at {red_val}-{blue_val} above WIN_SCORE — waiting for one to pull ahead", "INFO")
            return
        winner = 'red' if red_val > blue_val else 'blue'
    elif red_wins:
        winner = 'red'
    else:
        winner = 'blue'

    log_message(f"Win condition confirmed after settle — {winner} ({red_val} vs {blue_val})", "INFO")
    _start_win_animation(winner)

def _check_win_condition():
    """
    Called after every counter change (up or down). Cancels any pending
    debounce timer and starts a fresh WIN_SETTLE_DELAY countdown. This means
    the win animation only triggers once the score has been untouched for
    5 seconds, avoiding false positives during rapid entry.
    """
    # Cancel previous pending check (score still being entered)
    job = ui_references.get('_win_debounce_job')
    if job:
        try:
            main_root.after_cancel(job)
        except Exception:
            pass

    # Don't schedule a new check if a win is already showing
    if ui_references.get('_win_color'):
        return

    ui_references['_win_debounce_job'] = main_root.after(WIN_SETTLE_DELAY, _evaluate_win)


def _show_correction_dialog(color):
    """
    Opens a small dialog letting the operator enter what the physical scoreboard
    currently shows for the given color. Calculates the delta vs the on-screen
    counter and sends the corrective IR pulses via ir_correct().
    """
    team_color  = THEME['red_team'] if color == 'red' else THEME['blue_team']
    label_color = 'RED' if color == 'red' else 'BLUE'
    current_val = ui_references[f'{color}_counter_var'].get()

    dialog = tk.Toplevel(main_root)
    dialog.title(f"Fix {label_color} Score")
    dialog.configure(bg=THEME['bg_main'])
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.geometry("280x190")

    tk.Label(dialog, text=f"Fix {label_color} Scoreboard",
             font=THEME['font_header'], bg=THEME['bg_main'], fg=team_color).pack(pady=(16, 4))

    tk.Label(dialog, text=f"App shows: {current_val}   |   Scoreboard shows:",
             font=THEME['font_main'], bg=THEME['bg_main'], fg=THEME['fg_secondary']).pack(pady=(0, 8))

    entry_var = tk.StringVar(value=str(current_val))
    entry = tk.Entry(dialog, textvariable=entry_var, font=('Selawik', 18, 'bold'),
                     width=5, justify='center',
                     bg=THEME['bg_card'], fg=team_color,
                     insertbackground=team_color, relief='flat')
    entry.pack()
    entry.select_range(0, 'end')
    entry.focus_set()

    def _confirm(event=None):
        try:
            scoreboard_val = int(entry_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Please enter a whole number.", parent=dialog)
            return
        if scoreboard_val < 0:
            messagebox.showerror("Invalid", "Score cannot be negative.", parent=dialog)
            return
        ir_correct(color, scoreboard_val, current_val)
        dialog.destroy()

    entry.bind("<Return>", _confirm)

    btn_row = tk.Frame(dialog, bg=THEME['bg_main'])
    btn_row.pack(pady=(14, 0))
    tk.Button(btn_row, text="✓ Correct", bg=THEME['btn_confirm'], fg='white',
              relief='flat', padx=14, pady=4, font=THEME['font_main'],
              command=_confirm).pack(side='left', padx=6)
    tk.Button(btn_row, text="Cancel", bg=THEME['btn_cancel'], fg='white',
              relief='flat', padx=14, pady=4, font=THEME['font_main'],
              command=dialog.destroy).pack(side='left', padx=6)


def setup_scoreboard(root, team_red_placeholder, team_blue_placeholder):
    """
    Redesigned Main UI: Uses Tabs to separate concerns and a 'Card' layout for the match.
    """
    global scoreboard_canvas_ref, team_labels, player_labels_ref, status_label
    global match_input_frame, match_res_frame, btn_red, btn_blue, roster_seeding_frame_ref
    global match_details_frame, game_routing_label, team_info_labels, bracket_info_canvas_ref
    global rankings_label_ref, btn_switch, bracket_info_frame_ref, team_info_frame_ref
    global switch_frame_ref, final_control_frame_ref, rankings_display_frame_ref
    global ui_references

    log_message("Scoreboard UI initialized.")

    # --- Styling for Notebook (Dark Theme) ---
    style = ttk.Style()
    style.theme_use('default')
    style.configure("TNotebook", background=THEME['bg_main'], borderwidth=0)
    style.configure("TNotebook.Tab", background=THEME['bg_card'], foreground=THEME['fg_secondary'], padding=[10, 5], font=('Selawik', 10))
    style.map("TNotebook.Tab", background=[("selected", THEME['bg_canvas'])], foreground=[("selected", THEME['fg_primary'])])
    style.configure("TFrame", background=THEME['bg_main'])

    # --- Header Status ---
    status_frame = tk.Frame(root, bg=THEME['bg_card'], padx=10, pady=5)
    status_frame.pack(fill='x', side='top')

    status_label = tk.Label(status_frame, text="Tournament Initialized.", font=('Selawik', 12, 'bold'),
                            bg=THEME['bg_card'], fg=THEME['accent_gold'])
    status_label.pack(side='left')

    # --- Main Notebook (Tabs) ---
    notebook = ttk.Notebook(root)
    notebook.pack(fill='both', expand=True, padx=5, pady=5)
    ui_references['notebook'] = notebook

    # Tab 1: The Arena (Active Match)
    tab_match = tk.Frame(notebook, bg=THEME['bg_main'])
    notebook.add(tab_match, text='   ⚔️ ARENA   ')

    # Tab 2: The Roster (List)
    tab_roster = tk.Frame(notebook, bg=THEME['bg_main'])
    notebook.add(tab_roster, text='   👥 ROSTERS   ')

    # 1. Routing Info (Where does winner go?)
    info_frame = tk.Frame(tab_match, bg=THEME['bg_main'], pady=5)
    info_frame.pack(fill='x')
    game_routing_label = tk.Label(info_frame, text="Winner -> TBD | Loser -> TBD",
                                  font=('Selawik', 9), fg=THEME['fg_secondary'], bg=THEME['bg_main'])
    game_routing_label.pack()
    ui_references['info_lbl'] = game_routing_label

    # + Late Entry button — top right of arena, only visible on first match before any result
    ui_references['late_entry_btn'] = tk.Button(
        info_frame, text="Add Late Entry", font=('Selawik', 8, 'bold'),
        bg=THEME['btn_default'], fg=THEME['accent_gold'],
        relief='flat', padx=6, pady=1, cursor='hand2',
        command=add_late_team
    )
    ui_references['late_entry_btn'].place(relx=1.0, rely=0.5, anchor='e', x=-6)

    # 2. The Interaction Area (Cards)
    match_input_frame = tk.Frame(tab_match, bg=THEME['bg_main'])
    match_input_frame.pack(fill='both', expand=True, padx=5, pady=5)
    ui_references['match_tab_frame'] = match_input_frame # Reference for hiding later

    # -- Red Card --
    red_card = tk.Frame(match_input_frame, bg=THEME['bg_card'], bd=2, relief='flat')
    red_card.place(relx=0.0, rely=0.0, relwidth=0.48, relheight=0.85)
    ui_references['red_card_frame'] = red_card

    # Red Content
    tk.Label(red_card, text="RED TEAM", font=('Selawik', 8, 'bold'), fg=THEME['red_team'], bg=THEME['bg_card']).pack(pady=(10,0))

    ui_references['red_name_lbl'] = tk.Label(red_card, text=team_red_placeholder, font=('Selawik', 14, 'bold'),
                                             fg=THEME['fg_primary'], bg=THEME['bg_card'], wraplength=180)
    ui_references['red_name_lbl'].pack(pady=(5,0))

    ui_references['red_roster_lbl'] = tk.Label(red_card, text="P1 / P2", font=('Selawik', 10, 'bold'),
                                               fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['red_roster_lbl'].pack(pady=(2, 10))

    # -- Red Counter (centered between roster and win button) --
    ui_references['red_counter_var'] = tk.IntVar(value=0)
    red_counter_frame = tk.Frame(red_card, bg=THEME['bg_card'])
    red_counter_frame.pack(expand=True)
    def _red_down():
        ui_references['red_counter_var'].set(max(0, ui_references['red_counter_var'].get() - 1))
        ir_send('red_down')
        _check_win_condition()
    tk.Button(red_counter_frame, text="▼", font=('Selawik', 13, 'bold'),
              bg=THEME['bg_main'], fg=THEME['red_team'], relief='flat', width=3,
              cursor='hand2', command=_red_down,
              ).pack(side='left', padx=6)
    tk.Label(red_counter_frame, textvariable=ui_references['red_counter_var'],
             font=('Selawik', 28, 'bold'), fg=THEME['red_team'], bg=THEME['bg_card'],
             width=3, anchor='center').pack(side='left')
    def _red_up():
        ui_references['red_counter_var'].set(ui_references['red_counter_var'].get() + 1)
        ir_send('red_up')
        _check_win_condition()
    tk.Button(red_counter_frame, text="▲", font=('Selawik', 13, 'bold'),
              bg=THEME['bg_main'], fg=THEME['red_team'], relief='flat', width=3,
              cursor='hand2', command=_red_up,
              ).pack(side='left', padx=6)

    # -- Red Fix Score button --
    def _red_fix():
        _show_correction_dialog('red')
    ui_references['red_fix_btn'] = tk.Button(red_card, text="✎ Fix Score", font=('Selawik', 8),
              bg=THEME['bg_main'], fg=THEME['fg_secondary'], relief='flat',
              cursor='hand2', command=_red_fix)
    ui_references['red_fix_btn'].pack(pady=(0, 4))

    ui_references['red_stats_lbl'] = tk.Label(red_card, text="0-0", font=('Consolas', 9), fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['red_stats_lbl'].pack(side='bottom', pady=5)

    btn_red = tk.Button(red_card, text="🏆 RED WINS", command=lambda: declare_winner('red'),
                        bg=THEME['red_team'], fg='white', font=('Selawik', 11, 'bold'),
                        relief='flat', activebackground='#C62828', cursor='hand2')
    btn_red.pack(side='bottom', fill='x', padx=10, pady=10)

    # -- VS Center --
    vs_frame = tk.Frame(match_input_frame, bg=THEME['bg_main'])
    vs_frame.place(relx=0.48, rely=0.0, relwidth=0.04, relheight=0.85)
    ui_references['vs_label'] = tk.Label(vs_frame, text="VS", font=('Selawik', 10, 'bold'), fg=THEME['fg_secondary'], bg=THEME['bg_main'])
    ui_references['vs_label'].place(relx=0.5, rely=0.4, anchor='center')

    # -- Blue Card --
    blue_card = tk.Frame(match_input_frame, bg=THEME['bg_card'], bd=2, relief='flat')
    blue_card.place(relx=0.52, rely=0.0, relwidth=0.48, relheight=0.85)
    ui_references['blue_card_frame'] = blue_card

    # Blue Content
    tk.Label(blue_card, text="BLUE TEAM", font=('Selawik', 8, 'bold'), fg=THEME['blue_team'], bg=THEME['bg_card']).pack(pady=(10,0))

    ui_references['blue_name_lbl'] = tk.Label(blue_card, text=team_blue_placeholder, font=('Selawik', 14, 'bold'),
                                              fg=THEME['fg_primary'], bg=THEME['bg_card'], wraplength=180)
    ui_references['blue_name_lbl'].pack(pady=(5,0))

    ui_references['blue_roster_lbl'] = tk.Label(blue_card, text="P3 / P4", font=('Selawik', 10),
                                                fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['blue_roster_lbl'].pack(pady=(2, 10))

    # -- Blue Counter (centered between roster and win button) --
    ui_references['blue_counter_var'] = tk.IntVar(value=0)
    blue_counter_frame = tk.Frame(blue_card, bg=THEME['bg_card'])
    blue_counter_frame.pack(expand=True)
    def _blue_down():
        ui_references['blue_counter_var'].set(max(0, ui_references['blue_counter_var'].get() - 1))
        ir_send('blue_down')
        _check_win_condition()
    tk.Button(blue_counter_frame, text="▼", font=('Selawik', 13, 'bold'),
              bg=THEME['bg_main'], fg=THEME['blue_team'], relief='flat', width=3,
              cursor='hand2', command=_blue_down,
              ).pack(side='left', padx=6)
    tk.Label(blue_counter_frame, textvariable=ui_references['blue_counter_var'],
             font=('Selawik', 28, 'bold'), fg=THEME['blue_team'], bg=THEME['bg_card'],
             width=3, anchor='center').pack(side='left')
    def _blue_up():
        ui_references['blue_counter_var'].set(ui_references['blue_counter_var'].get() + 1)
        ir_send('blue_up')
        _check_win_condition()
    tk.Button(blue_counter_frame, text="▲", font=('Selawik', 13, 'bold'),
              bg=THEME['bg_main'], fg=THEME['blue_team'], relief='flat', width=3,
              cursor='hand2', command=_blue_up,
              ).pack(side='left', padx=6)

    # -- Blue Fix Score button --
    def _blue_fix():
        _show_correction_dialog('blue')
    ui_references['blue_fix_btn'] = tk.Button(blue_card, text="✎ Fix Score", font=('Selawik', 8),
              bg=THEME['bg_main'], fg=THEME['fg_secondary'], relief='flat',
              cursor='hand2', command=_blue_fix)
    ui_references['blue_fix_btn'].pack(pady=(0, 4))

    ui_references['blue_stats_lbl'] = tk.Label(blue_card, text="0-0", font=('Consolas', 9), fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['blue_stats_lbl'].pack(side='bottom', pady=5)

    btn_blue = tk.Button(blue_card, text="🏆 BLUE WINS", command=lambda: declare_winner('blue'),
                         bg=THEME['blue_team'], fg='white', font=('Selawik', 11, 'bold'),
                         relief='flat', activebackground='#1565C0', cursor='hand2')
    btn_blue.pack(side='bottom', fill='x', padx=10, pady=10)

    # -- Controls (Bottom of Arena) --
    ctrl_frame = tk.Frame(tab_match, bg=THEME['bg_main'], pady=5)
    ctrl_frame.pack(fill='x', side='bottom')

    switch_frame_ref = ctrl_frame # Use existing ref name for compatibility

    btn_switch = tk.Button(ctrl_frame, text="🔄 Swap Puck Color", command=swap_teams,
                           bg=THEME['btn_default'], fg='white', relief='flat', font=('Selawik', 9))
    btn_switch.pack(side='left', padx=5, fill='x', expand=True)

    tk.Button(ctrl_frame, text="Pop-out Bracket ↗", command=open_full_bracket,
              bg=THEME['btn_default'], fg='white', relief='flat', font=('Selawik', 9)).pack(side='left', padx=5, fill='x', expand=True)

    # --- UPDATED: PERSISTENT FOOTER STATUS BAR ---
    footer_bar = tk.Frame(root, bg=THEME['bg_card'], height=25, bd=1, relief='sunken')
    footer_bar.pack(side='bottom', fill='x')

    # 1. Left Section: Version
    tk.Label(footer_bar, text=f"v{SHUF_VERSION}", font=('Selawik', 8),
             fg=THEME['fg_secondary'], bg=THEME['bg_card'], padx=10).pack(side='left')

    # 2. Left Section: File/Database Status
    ui_references['footer_file_status'] = tk.Label(
    footer_bar,
    text="",
    font=('Selawik', 8, 'bold'),
    fg=THEME['fg_secondary'],
    bg=THEME['bg_card'],
    padx=5
    )
    ui_references['footer_file_status'].pack(side='left')

    update_footer_log_status()

    # 3. Right Section: Timer (Far Right) — click label or button to start/pause
    ui_references['timer_lbl'] = tk.Label(
        footer_bar, text="00:00", font=('Consolas', 10, 'bold'),
        fg=THEME['accent_gold'], bg=THEME['bg_card'], padx=6, cursor='hand2'
    )
    ui_references['timer_lbl'].pack(side='right')
    ui_references['timer_lbl'].bind("<Button-1>", lambda e: toggle_match_timer())

    ui_references['timer_play_btn'] = tk.Button(
        footer_bar, text="▶", font=('Selawik', 8, 'bold'),
        bg=THEME['btn_default'], fg=THEME['accent_gold'],
        relief='flat', padx=4, pady=0, cursor='hand2',
        command=toggle_match_timer
    )
    ui_references['timer_play_btn'].pack(side='right', padx=(0, 2))

    # 4. Center Section: Tournament Progress
    ui_references['footer_progress'] = tk.Label(footer_bar, text="Progress: 0%", font=('Selawik', 9),
                                                fg=THEME['fg_primary'], bg=THEME['bg_card'], padx=20)
    ui_references['footer_progress'].pack(side='right')

    # -- Result Confirmation (Initially Hidden) --
    match_res_frame = tk.Frame(tab_match, bg=THEME['bg_main'], padx=20, pady=40)
    # Note: We don't pack it yet. declare_winner will handle it.

    # -- Final Rankings (Initially Hidden) --
    rankings_display_frame_ref = tk.Frame(root, bg=THEME['bg_card'])
    rankings_label_ref = tk.Label(rankings_display_frame_ref, text="", bg=THEME['bg_card'], fg=THEME['fg_primary'])
    rankings_label_ref.pack()
    final_control_frame_ref = tk.Frame(root, bg=THEME['bg_main'])


    # --- Tab 2: SCHEDULE & HISTORY ---
    schedule_tab = tk.Frame(notebook, bg=THEME['bg_main'])
    notebook.add(schedule_tab, text=" SCHEDULE ")

    # Scrollable container for the schedule
    sched_canvas = tk.Canvas(schedule_tab, bg=THEME['bg_main'], highlightthickness=0)
    sched_scrollbar = ttk.Scrollbar(schedule_tab, orient="vertical", command=sched_canvas.yview)
    global schedule_content_frame
    schedule_content_frame = tk.Frame(sched_canvas, bg=THEME['bg_main'])

    schedule_content_frame.bind(
        "<Configure>",
        lambda e: sched_canvas.configure(scrollregion=sched_canvas.bbox("all"))
    )

    sched_canvas.create_window((0, 0), window=schedule_content_frame, anchor="nw", width=480) # Adjust width as needed
    sched_canvas.configure(yscrollcommand=sched_scrollbar.set)

    sched_canvas.pack(side="left", fill="both", expand=True)
    sched_scrollbar.pack(side="right", fill="y")

    # ==========================
    # TAB 3: ROSTERS
    # ==========================
    # Use the existing roster logic but in a vertical scroll
    roster_scroll = tk.Scrollbar(tab_roster)
    roster_scroll.pack(side='right', fill='y')

    roster_canvas = tk.Canvas(tab_roster, bg=THEME['bg_card'], highlightthickness=0, yscrollcommand=roster_scroll.set)
    roster_canvas.pack(side='left', fill='both', expand=True)
    roster_scroll.config(command=roster_canvas.yview)

    roster_seeding_frame_ref = tk.Frame(roster_canvas, bg=THEME['bg_card'])
    roster_canvas.create_window((0,0), window=roster_seeding_frame_ref, anchor='nw')

    roster_seeding_frame_ref.bind("<Configure>", lambda e: roster_canvas.configure(scrollregion=roster_canvas.bbox("all")))

    # Initialize Data
    update_roster_seeding_vertical() # New helper function for vertical roster
    load_match_data_and_teams()

    # --- Flipper Zero status label + reconnect button in footer ---
    ui_references['flipper_status_lbl'] = tk.Label(
        footer_bar, text="", font=('Selawik', 8),
        bg=THEME['bg_card'], fg=THEME['fg_secondary'], padx=4
    )
    ui_references['flipper_status_lbl'].pack(side='left')

    def _set_flipper_ui(connected):
        """Update Fix Score buttons and footer indicator to reflect connection state."""
        lbl = ui_references.get('flipper_status_lbl')
        btn = ui_references.get('flipper_reconnect_btn')
        for key in ('red_fix_btn', 'blue_fix_btn'):
            fix_btn = ui_references.get(key)
            if fix_btn:
                if connected:
                    fix_btn.pack(pady=(0, 4))
                else:
                    fix_btn.pack_forget()
        if lbl:
            if connected:
                lbl.config(text="🟢 Flipper", fg=THEME['btn_confirm'])
                if btn:
                    btn.pack_forget()
            else:
                lbl.config(text="🔴 Flipper", fg=THEME['btn_cancel'])
                if btn:
                    btn.pack(side='left', padx=(0, 4))
    ui_references['_set_flipper_ui'] = _set_flipper_ui

    def _try_reconnect():
        """One-shot reconnect attempt triggered by the footer button."""
        reconnect_btn = ui_references.get('flipper_reconnect_btn')
        if reconnect_btn:
            reconnect_btn.config(state='disabled', text='...')
        def _do():
            connected = flipper_connect()
            root.after(0, lambda: _finish(connected))
        def _finish(connected):
            _set_flipper_ui(connected)
            if reconnect_btn:
                reconnect_btn.config(state='normal', text='🔌 Reconnect')
            log_message(f"Flipper reconnect attempt — {'success' if connected else 'not found'}", "INFO")
        threading.Thread(target=_do, daemon=True).start()

    ui_references['flipper_reconnect_btn'] = tk.Button(
        footer_bar, text="🔌 Reconnect", font=('Selawik', 8),
        bg=THEME['btn_default'], fg=THEME['fg_primary'],
        relief='flat', padx=6, pady=0, cursor='hand2',
        command=_try_reconnect
    )
    # Don't pack yet — _set_flipper_ui will show/hide it

    def _initial_flipper_check():
        connected = flipper_connect()
        root.after(0, lambda: _set_flipper_ui(connected))
        if not connected:
            log_message("Flipper Zero not detected — Fix Score buttons hidden, reconnect button shown", "INFO")

    threading.Thread(target=_initial_flipper_check, daemon=True).start()

def update_schedule_tab():
    """
    Refreshes the Schedule tab.
    Shows players (rosters) instead of Team IDs for better readability.
    Now shows matches even if only one team is known, using 'TBD' and status icons.
    """
    global schedule_content_frame, MATCH_HISTORY, TOURNAMENT_STATE, TEAM_ROSTERS
    if not schedule_content_frame: return

    # Clear existing widgets
    for widget in schedule_content_frame.winfo_children():
        widget.destroy()

    # Helper function to safely format missing rosters as "TBD"
    def get_roster_text(team):
        if not team:
            return "TBD"
        return " / ".join(TEAM_ROSTERS.get(team, [team, team]))

    # --- SECTION 1: ON DECK (Upcoming) ---
    tk.Label(schedule_content_frame, text="UPCOMING MATCHES", font=THEME['font_bold'],
             fg=THEME['accent_gold'], bg=THEME['bg_main'], pady=10).pack()

    active_id = TOURNAMENT_STATE.get('active_match_id')
    upcoming_count = 0

    # Sort match keys (G1, G2, etc.) to show them in order
    for mid in sorted(TOURNAMENT_STATE.keys(), key=sort_match_keys):
        if mid in ['active_match_id', 'TOURNAMENT_OVER']: continue
        m_data = TOURNAMENT_STATE[mid]

        team1 = m_data['teams'][0]
        team2 = m_data['teams'][1]

        # A match is "Upcoming" if AT LEAST ONE team is known, it hasn't been played, and isn't active
        if (team1 or team2) and m_data['winner'] is None and mid != active_id:
            upcoming_count += 1

            roster_a = get_roster_text(team1)
            roster_b = get_roster_text(team2)

            # Visual indicators based on readiness
            is_ready = bool(team1 and team2)
            icon = "🟢" if is_ready else "⏳"
            status_color = THEME['fg_primary'] if is_ready else THEME['fg_secondary']

            f = tk.Frame(schedule_content_frame, bg=THEME['bg_card'], padx=10, pady=8)
            f.pack(fill='x', padx=20, pady=3)

            # Match ID & Status Icon
            tk.Label(f, text=f"{icon} {mid}:", font=('Selawik', 9, 'bold'),
                     fg=THEME['fg_secondary'], bg=THEME['bg_card']).pack(side='left')

            # Player Names
            tk.Label(f, text=f"{roster_a}   vs   {roster_b}",
                     font=('Selawik', 10, 'bold'), fg=status_color, bg=THEME['bg_card']).pack(side='left', padx=15)

    if upcoming_count == 0:
        tk.Label(schedule_content_frame, text="No matches currently on deck.",
                 font=THEME['font_main'], fg=THEME['fg_secondary'], bg=THEME['bg_main']).pack(pady=10)

    # --- SECTION 2: MATCH HISTORY (Recent Results) ---
    tk.Label(schedule_content_frame, text="MATCH HISTORY", font=THEME['font_bold'],
             fg=THEME['accent_gold'], bg=THEME['bg_main'], pady=20).pack()

    if not MATCH_HISTORY:
        tk.Label(schedule_content_frame, text="No matches completed yet.",
                 font=THEME['font_main'], fg=THEME['fg_secondary'], bg=THEME['bg_main']).pack()
    else:
        # Show history in reverse (newest result at the top)
        for record in reversed(MATCH_HISTORY):
            f = tk.Frame(schedule_content_frame, bg=THEME['bg_main'], pady=3)
            f.pack(fill='x', padx=20)

            # Use the color of the winning team for the text
            color_hex = THEME['red_team'] if record['color'] == 'red' else THEME['blue_team']

            # Fetch rosters for the history record
            win_roster = " & ".join(TEAM_ROSTERS.get(record['winner'], ["?", "?"]))
            loss_roster = " & ".join(TEAM_ROSTERS.get(record['loser'], ["?", "?"]))

            # Format: "G1: Player A / Player B defeated Player C / Player D  (15-8)"
            score_str = ""
            if 'red_score' in record and 'blue_score' in record:
                win_score  = record['red_score']  if record['color'] == 'red'  else record['blue_score']
                loss_score = record['blue_score'] if record['color'] == 'red'  else record['red_score']
                score_str = f"  ({win_score}-{loss_score})"
            history_text = f"{record['id']}: {win_roster} defeated {loss_roster}{score_str}"

            tk.Label(f, text=history_text, font=THEME['font_main'],
                     fg=color_hex, bg=THEME['bg_main']).pack(side='left')

def update_roster_seeding_vertical():
    """Aligned roster table using grid for consistent column layout."""
    global roster_seeding_frame_ref, TEAMS, TEAM_ROSTERS
    global TOURNAMENT_RANKINGS, current_match_teams

    if not roster_seeding_frame_ref:
        return

    for w in roster_seeding_frame_ref.winfo_children():
        w.destroy()

    table = tk.Frame(roster_seeding_frame_ref, bg=THEME['bg_card'])
    table.pack(fill='x', padx=10, pady=10)

    # Configure column weights (keeps alignment consistent)
    table.grid_columnconfigure(0, weight=0)  # Seed
    table.grid_columnconfigure(1, weight=3)  # Team / Players
    table.grid_columnconfigure(2, weight=0)  # W-L
    table.grid_columnconfigure(3, weight=0)  # Win %

    # ---- Header Row ----
    headers = ["Status", "Team / Players", "W-L", "Win%"]
    for col, text in enumerate(headers):
        tk.Label(
            table,
            text=text,
            font=('Selawik', 9, 'bold'),
            bg=THEME['bg_card'],
            fg=THEME['fg_secondary'],
            anchor='w'
        ).grid(row=0, column=col, sticky='w', padx=35, pady=(4, 6))

    # Divider
    tk.Frame(table, bg=THEME['bg_main'], height=2)\
        .grid(row=1, column=0, columnspan=4, sticky='ew', pady=(0, 6))

    # ---- Team Rows ----
    row_index = 2

    for idx, team in enumerate(TEAMS, start=1):
        wins, losses = get_team_record(team)
        total = wins + losses
        win_pct = f"{int((wins / total) * 100)}%" if total > 0 else "--"

        bg_col = THEME['bg_card']
        fg_primary = THEME['fg_primary']
        fg_secondary = THEME['fg_secondary']
        status_color = fg_primary

        status_badge = "    ☐"
        status_color = THEME['btn_confirm']
        if team == TOURNAMENT_RANKINGS.get('1ST'):
            status_badge = "    █"
            status_color = THEME['accent_gold']
        elif team in TOURNAMENT_RANKINGS.values():
            status_badge = "    ✘"
            status_color = THEME['btn_cancel']
        elif team in current_match_teams.values():
            status_badge = "    🗹"
            status_color = THEME['btn_yellow']

        roster = TEAM_ROSTERS.get(team, ['?', '?'])
        team_text = f"{roster[0]} & {roster[1]}"

        # Seed
        tk.Label(
            table, text=status_badge,
            font=('Selawik', 10),
            bg=bg_col, fg=status_color,
            anchor='w'
        ).grid(row=row_index, column=0, sticky='w', padx=35, pady=7)

        # Team / Players
        tk.Label(
            table, text=team_text,
            font=('Selawik', 10, 'bold'),
            bg=bg_col, fg=fg_primary,
            anchor='w'
        ).grid(row=row_index, column=1, sticky='w', padx=35, pady=7)

        # W-L
        tk.Label(
            table, text=f"{wins}-{losses}",
            font=('Consolas', 10),
            bg=bg_col, fg=fg_primary,
            anchor='e'
        ).grid(row=row_index, column=2, sticky='e', padx=35, pady=7)

        # Win %
        tk.Label(
            table, text=win_pct,
            font=('Consolas', 10),
            bg=bg_col, fg=fg_primary,
            anchor='e'
        ).grid(row=row_index, column=3, sticky='e', padx=35, pady=7)

        row_index += 1

def update_timer_display():
    """Updates the match elapsed time every second. Only ticks when timer is running."""
    global match_timer_id, TOURNAMENT_STATE, ui_references, main_root

    if not ui_references.get('timer_lbl') or not main_root:
        return

    match_id = TOURNAMENT_STATE.get('active_match_id')

    if match_id == 'TOURNAMENT_OVER' or not match_id:
        ui_references['timer_lbl'].config(text="--:--")
        return

    match_data = TOURNAMENT_STATE.get(match_id)
    if not match_data:
        return

    # If paused, show current elapsed without advancing
    if match_data.get('timer_paused', True):
        elapsed = int(match_data.get('elapsed_at_pause', 0))
        mins, secs = divmod(elapsed, 60)
        ui_references['timer_lbl'].config(text=f"{mins:02d}:{secs:02d}")

        # Flash red if paused for more than 30 seconds
        paused_at = match_data.get('paused_at') or match_data.get('_paused_since')
        if paused_at is None:
            match_data['_paused_since'] = time.time()
            paused_at = match_data['_paused_since']

        paused_duration = time.time() - paused_at
        if paused_duration >= 30:
            flash_state = match_data.get('_flash_state', False)
            flash_color = '#FF0000' if flash_state else THEME['bg_card']
            ui_references['timer_lbl'].config(fg=flash_color)
            if ui_references.get('timer_play_btn'):
                ui_references['timer_play_btn'].config(fg=flash_color)
            match_data['_flash_state'] = not flash_state
            match_timer_id = main_root.after(1000, update_timer_display)
        else:
            ui_references['timer_lbl'].config(fg=THEME['accent_gold'])
            if ui_references.get('timer_play_btn'):
                ui_references['timer_play_btn'].config(fg=THEME['accent_gold'])
            match_timer_id = main_root.after(1000, update_timer_display)
        return

    if 'start_time' not in match_data or not match_data['start_time']:
        match_data['start_time'] = time.time()

    elapsed = int(time.time() - match_data['start_time'])
    mins, secs = divmod(elapsed, 60)

    ui_references['timer_lbl'].config(text=f"{mins:02d}:{secs:02d}")

    match_timer_id = main_root.after(1000, update_timer_display)

def stop_match_timer():
    global match_timer_id, main_root
    if match_timer_id and main_root:
        try:
            main_root.after_cancel(match_timer_id)
        except:
            pass
        match_timer_id = None

def resume_match_timer():
    """Resumes the timer from where it was paused."""
    global TOURNAMENT_STATE

    match_id = TOURNAMENT_STATE.get('active_match_id')
    if not match_id or match_id == 'TOURNAMENT_OVER':
        return

    match_data = TOURNAMENT_STATE.get(match_id)
    if not match_data:
        return

    elapsed_so_far = match_data.get('elapsed_at_pause', 0)
    match_data['start_time'] = time.time() - elapsed_so_far
    match_data['paused_at'] = None
    match_data['timer_paused'] = False
    match_data['_paused_since'] = None
    match_data['_flash_state'] = False

    ui_references['timer_lbl'].config(fg=THEME['accent_gold'])
    if ui_references.get('timer_play_btn'):
        ui_references['timer_play_btn'].config(text="⏸", fg=THEME['accent_gold'])

    update_timer_display()

def pause_match_timer():
    """Pauses the timer and records elapsed time."""
    global match_timer_id, main_root, TOURNAMENT_STATE

    match_id = TOURNAMENT_STATE.get('active_match_id')
    if match_id and match_id != 'TOURNAMENT_OVER':
        match_data = TOURNAMENT_STATE.get(match_id)
        if match_data and match_data.get('start_time'):
            match_data['elapsed_at_pause'] = int(time.time() - match_data['start_time'])
        match_data['paused_at'] = time.time()
        match_data['timer_paused'] = True

    stop_match_timer()

    if ui_references.get('timer_play_btn'):
        ui_references['timer_play_btn'].config(text="▶")

    update_timer_display()

def toggle_match_timer():
    """Toggles the timer between running and paused."""
    match_id = TOURNAMENT_STATE.get('active_match_id')
    if not match_id or match_id == 'TOURNAMENT_OVER':
        return

    match_data = TOURNAMENT_STATE.get(match_id)
    if not match_data:
        return

    if match_data.get('timer_paused', True):
        resume_match_timer()
    else:
        pause_match_timer()

def finalize_match_duration(match_id):
    global MATCH_DURATIONS, TOURNAMENT_STATE

    match_data = TOURNAMENT_STATE.get(match_id)
    if not match_data or not match_data.get('start_time'):
        return

    # If timer is currently paused use the saved elapsed, otherwise calculate from start_time
    if match_data.get('timer_paused') and match_data.get('elapsed_at_pause') is not None:
        duration = int(match_data['elapsed_at_pause'])
    else:
        duration = int(time.time() - match_data['start_time'])

    match_data['duration'] = duration
    MATCH_DURATIONS.append(duration)

    return duration


def format_seconds(seconds):
    if not seconds:
        return "00:00"
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"

def update_scoreboard_display():
    """Redesigned update logic for the new Card UI."""
    global team_labels, player_labels_ref, TOURNAMENT_STATE, status_label, current_match_teams
    global game_routing_label, team_info_labels, bracket_info_canvas_ref, ui_references

    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')

    if match_id == 'TOURNAMENT_OVER':
        return

    log_message(f"Scoreboard display refreshed for match: {match_id}", "DEBUG")

    team_red = current_match_teams['red']
    team_blue = current_match_teams['blue']

    roster_red = " / ".join(TEAM_ROSTERS.get(team_red, ["P1", "P2"]))
    roster_blue = " / ".join(TEAM_ROSTERS.get(team_blue, ["P3", "P4"]))

    match_data = TOURNAMENT_STATE[match_id]
    match_config = match_data['config']

    # --- Update New UI Elements ---
    if ui_references['red_name_lbl']:
        ui_references['red_name_lbl'].config(text=team_red)
        ui_references['red_roster_lbl'].config(text=roster_red)

        ui_references['blue_name_lbl'].config(text=team_blue)
        ui_references['blue_roster_lbl'].config(text=roster_blue)

        wins_red, losses_red = get_team_record(team_red)
        wins_blue, losses_blue = get_team_record(team_blue)

        ui_references['red_stats_lbl'].config(text=f"Wins: {wins_red} | Loss: {losses_red}")
        ui_references['blue_stats_lbl'].config(text=f"Wins: {wins_blue} | Loss: {losses_blue}")

        w_next = format_destination(match_config.get('W_next'))
        l_next = format_destination(match_config.get('L_next'))

        ui_references['info_lbl'].config(text=f"Match {match_id} • Winner: {w_next} • Loser: {l_next}")

    # Update Status Header
    status_label.config(text=f"ACTIVE MATCH: {match_id}", fg=THEME['accent_gold'])

    # Update Tab 2 (Bracket)
    if bracket_info_canvas_ref:
        draw_small_bracket_view(bracket_info_canvas_ref, TOURNAMENT_STATE)

    # Update Full Bracket if open
    if full_bracket_root and full_bracket_canvas:
        try:
            draw_large_bracket(full_bracket_canvas)
        except Exception as e:
            log_message(f"Failed to update full bracket: {e}", "ERROR")

    # Refresh vertical roster highlights
    update_roster_seeding_vertical()
    update_schedule_tab()

    # --- Late Entry Button visibility ---
    # Show only on G1, no completed matches, AND the N+1 bracket keeps G1 seeding intact
    if ui_references.get('late_entry_btn'):
        show_btn = False
        if match_id == 'G1' and not MATCH_HISTORY:
            try:
                n = len(TEAMS)
                curr_config, _ = load_bracket_config(n, 'D')
                next_config, _ = load_bracket_config(n + 1, 'D')
                curr_g1_slots = sorted(curr_config.get('G1', {}).get('teams', []))
                next_g1_slots = sorted(next_config.get('G1', {}).get('teams', []))
                # Safe only if G1 seeding is identical in both bracket sizes
                show_btn = (curr_g1_slots == next_g1_slots)
            except Exception:
                show_btn = False  # Config missing or unreadable
        if show_btn:
            ui_references['late_entry_btn'].place(relx=1.0, rely=0.5, anchor='e', x=-6)
        else:
            ui_references['late_entry_btn'].place_forget()

    # --- Update Footer Progress ---
    if 'footer_progress' in ui_references:
        # Filter TOURNAMENT_STATE to count actual match keys (like G1, G2, GF)
        total_matches = len([k for k in TOURNAMENT_STATE.keys() if k not in ['active_match_id', 'TOURNAMENT_OVER']])
        completed_matches = len(MATCH_HISTORY)

        if total_matches > 0:
            percent = int((completed_matches / total_matches) * 100)
            ui_references['footer_progress'].config(
                text=f"Match {completed_matches + 1} of {total_matches} ({percent}%)"
            )

def declare_winner(color):
    """Handles UI transition to confirmation screen inside the Tab."""
    global TOURNAMENT_STATE, match_res_frame, current_match_teams
    global ui_references, current_match_res_buttons

    match_id_to_confirm = TOURNAMENT_STATE['active_match_id']
    winner = current_match_teams[color]
    loser = current_match_teams['blue'] if color == 'red' else current_match_teams['red']

    log_message(f"Winner declared — Match {match_id_to_confirm}: {winner} ({color})")

    # Pause timer while confirming — use pause_match_timer so elapsed is saved correctly
    pause_match_timer()

    # Hide the VS Cards, Show the Result Frame
    ui_references['match_tab_frame'].pack_forget()
    match_res_frame.pack(fill='both', expand=True, padx=10, pady=10)

    # Re-create buttons inside match_res_frame
    for widget in match_res_frame.winfo_children():
        widget.destroy()
    current_match_res_buttons.clear()

    # Header
    tk.Label(match_res_frame, text="CONFIRM RESULT", font=('Selawik', 14, 'bold'),
             bg=THEME['bg_main'], fg=THEME['fg_primary']).pack(pady=(0, 20))

    tk.Label(match_res_frame, text=f"{winner} wins Match {match_id_to_confirm}?",
             font=('Selawik', 12), bg=THEME['bg_main'], fg=THEME['fg_secondary']).pack(pady=(0, 20))

    # Big Confirm Button
    confirm_btn = tk.Button(match_res_frame, text=f"✅ YES, {winner} WON",
                            bg=THEME['btn_confirm'], fg='white',
                            font=('Selawik', 12, 'bold'), relief='flat', padx=20, pady=15,
                            command=lambda w=winner, l=loser, c=color, mid=match_id_to_confirm: confirm_match_resolution(w, l, c, mid))
    confirm_btn.pack(pady=10, fill='x')
    current_match_res_buttons.append(confirm_btn)

    # Cancel Button
    go_back_btn = tk.Button(match_res_frame, text="❌ CANCEL / GO BACK",
                            bg=THEME['btn_cancel'], fg='white',
                            font=('Selawik', 10), relief='flat', padx=10, pady=10,
                            command=go_back_to_selection)
    go_back_btn.pack(pady=10, fill='x')
    current_match_res_buttons.append(go_back_btn)

def go_back_to_selection():
    """Reverts the UI from Confirmation to the Arena view."""
    global match_res_frame, ui_references

    log_message("Returned to winner selection (result cancelled)")

    match_res_frame.pack_forget()
    ui_references['match_tab_frame'].pack(fill='both', expand=True, padx=5, pady=5)

    # Resume match timer
    resume_match_timer()

    # Ensure button text is up to date
    update_winner_buttons()

def load_match_data_and_teams():
    """Updated to handle the new notebook structure."""
    global TOURNAMENT_STATE, current_match_teams, last_assigned_match_id
    global rankings_label_ref, final_control_frame_ref, rankings_display_frame_ref
    global ui_references, match_res_frame

    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')
    log_message(f"Loading match: {match_id}")

    # Hide End Game screens if they were open
    if final_control_frame_ref: final_control_frame_ref.pack_forget()
    if rankings_display_frame_ref: rankings_display_frame_ref.pack_forget()

    # Show Notebook
    if ui_references['notebook']:
        ui_references['notebook'].pack(fill='both', expand=True, padx=5, pady=5)

    if match_id == 'TOURNAMENT_OVER':
        ui_references['notebook'].pack_forget() # Hide the game UI

        champion = None
        for data in TOURNAMENT_STATE.values():
            if isinstance(data, dict) and data.get('champion'):
                champion = data['champion']
                break

        if champion:
             display_final_rankings(champion)
        else:
            status_label.config(text=f"TOURNAMENT OVER! No champion declared. (Error State)", fg='dark red')
        return

    # Ensure the Arena view is visible (not the confirm view)
    match_res_frame.pack_forget()
    ui_references['match_tab_frame'].pack(fill='both', expand=True, padx=5, pady=5)

    if match_id != last_assigned_match_id:
        match_data = TOURNAMENT_STATE[match_id]
        team_A = match_data['teams'][0]
        team_B = match_data['teams'][1]

        current_match_teams['red'] = team_A
        current_match_teams['blue'] = team_B
        last_assigned_match_id = match_id

        match_data['timer_paused'] = True
        match_data['elapsed_at_pause'] = 0
        match_data['_paused_since'] = time.time()
        match_data['_flash_state'] = False
        if ui_references.get('timer_play_btn'):
            ui_references['timer_play_btn'].config(text="▶", fg=THEME['accent_gold'])
        ui_references['timer_lbl'].config(fg=THEME['accent_gold'])

        global match_timer_id
        if match_timer_id and main_root:
            main_root.after_cancel(match_timer_id)
        update_timer_display()

    update_scoreboard_display()

def run_replay_mode(path):
    global REPLAY_FILEPATH, REPLAY_MODE, REPLAY_VIEW_ONLY
    global main_root, TEAMS, TEAM_ROSTERS, TOURNAMENT_STATE, TOURNAMENT_RANKINGS

    reset_global_state()
    REPLAY_MODE = True
    REPLAY_VIEW_ONLY = False

    log_message(f"Loading replay file: {path}")

    # Load last snapshot
    try:
        snap = _find_last_snapshot_in_file(path)
    except Exception as e:
        print(f"Replay error: {e}")
        messagebox.showerror("Replay Error", f"Could not load file: {e}")
        return

    if not snap:
        print("Replay file contains no SNAPSHOT entries.")
        sys.exit(1)

    # Validate minimal structure
    required_keys = ("teams", "rosters", "state", "active_match_id")
    for key in required_keys:
        if key not in snap:
            print(f"Snapshot missing required field '{key}'. Cannot continue.")
            sys.exit(1)

    # Load tournament basic data
    TEAMS[:] = snap.get("teams", [])
    TEAM_ROSTERS.clear()
    TEAM_ROSTERS.update(snap.get("rosters", {}))
    TOURNAMENT_RANKINGS.clear()
    TOURNAMENT_RANKINGS.update(snap.get("rankings", {}))
    MATCH_HISTORY.clear()
    MATCH_HISTORY.extend(snap.get("match_history", []))
    MATCH_DURATIONS.clear()
    MATCH_DURATIONS.extend(snap.get("match_durations", []))

    # Restore match-level state including champion
    TOURNAMENT_STATE.clear()
    raw_state = snap.get("state", {})
    for mid, m in raw_state.items():
        config = {}
        raw_cfg = m.get("config", {})

        # restore config tuples
        for ck, cv in raw_cfg.items():
            if isinstance(cv, list) and len(cv) == 2:
                config[ck] = (cv[0], int(cv[1]))
            else:
                config[ck] = cv

        TOURNAMENT_STATE[mid] = {
            "teams": m.get("teams", [None, None]),
            "winner": m.get("winner"),
            "winner_color": m.get("winner_color"),
            "is_reset": m.get("is_reset", False),
            "champion": m.get("champion"),      # ADDED RESTORE
            "is_winnerbracket": m.get("is_winnerbracket", "unknown"),  # ADDED RESTORE
            "start_time": m.get("start_time"),
            "config": config,
        }

    # Restore active match
    active = snap.get("active_match_id")
    TOURNAMENT_STATE["active_match_id"] = active

    # Determine if tournament completed
    is_complete = (
        active == "TOURNAMENT_OVER"
        or "1ST" in TOURNAMENT_RANKINGS
    )

    # -----------------------------
    # VIEW-ONLY MODE FOR FINISHED GAME
    # -----------------------------
    if is_complete:
        REPLAY_VIEW_ONLY = True
        REPLAY_FILEPATH = None

        log_message("Replay loaded — tournament complete, entering view-only mode")

        root = tk.Tk()
        root.title("Moose Lodge Shuffleboard — Replay (VIEW ONLY)")
        root.configure(bg=THEME['bg_main'])
        root.withdraw()

        main_root = root
        open_full_bracket()

        if full_bracket_root:
            full_bracket_root.title("Full Tournament Bracket — Replay (VIEW ONLY)")

        root.mainloop()
        sys.exit(0)

    # -----------------------------
    # CONTINUE MODE (unfinished)
    # -----------------------------
    REPLAY_VIEW_ONLY = False
    REPLAY_FILEPATH = path

    log_message(f"Replay loaded — resuming tournament, appending to: {path}")

    root = tk.Tk()
    root.title("Moose Lodge Shuffleboard — Replay Mode (Continue)")
    root.configure(bg=THEME['bg_main'])
    main_root = root

    am = TOURNAMENT_STATE.get("active_match_id")
    if am and am in TOURNAMENT_STATE:
        tA, tB = TOURNAMENT_STATE[am]["teams"]
    else:
        tA = TEAMS[0] if TEAMS else None
        tB = TEAMS[1] if len(TEAMS) > 1 else None

    setup_scoreboard(root, tA, tB)
    update_roster_seeding_display()
    update_scoreboard_display()

    root.mainloop()
    sys.exit(0)

def on_close(root):
    """Handles clean exit when the window or the console is closed/interrupted."""
    global main_root
    global LOG_FILE_HANDLE

    log_message("Application close requested")
    flipper_disconnect()

    if LOG_FILE_HANDLE:
        try:
            LOG_FILE_HANDLE.close()
            print("[Log Manager] Log file closed on exit.")
        except:
            pass

    try:
        if root:
            # Destroy the main_root (even if hidden) to stop mainloop()
            root.destroy()
        sys.exit(0)
    except:
        sys.exit(0)

def show_title_screen():
    """Displays a title image, Load Game button, and New Game button."""
    import tkinter as tk
    from PIL import Image, ImageTk

    splash = tk.Tk()
    splash.title("Moose Lodge Shuffleboard ")
    splash.geometry("500x550") # Slightly taller for extra button
    splash.configure(bg=THEME['bg_main'])

    try:
        img = Image.open("img/title.png")
        img = img.resize((480, 300), Image.LANCZOS)
        logo = ImageTk.PhotoImage(img)
        tk.Label(splash, image=logo, bg=THEME['bg_main']).pack(pady=20)
    except Exception as e:
        tk.Label(splash, text="Moose Lodge Shuffleboard ", fg=THEME['fg_primary'], bg=THEME['bg_main'], font=("Arial", 20, "bold")).pack(pady=60)
        print(f"[Title Screen] Could not load image: {e}")

    tk.Label(
        splash,
        text="Ms. Ethel's Moose Shuffleboard Tournament",
        fg=THEME['fg_primary'], bg=THEME['bg_main'],
        font=THEME['font_title']
    ).pack(pady=10)

    # --- Button Logic ---

    def start_new_game():
        splash.destroy()
        start_tournament()

    def load_existing_game():
        # Rule 6: Load existing replay file
        filename = filedialog.askopenfilename(
            title="Select Replay File",
            initialdir="replays",
            filetypes=[("JSON Replay", "*.json"), ("All Files", "*.*")]
        )
        if filename:
            splash.destroy()
            run_replay_mode(filename)

    # Load Game Button
    tk.Button(
        splash,
        text="Load Game",
        command=load_existing_game,
        bg=THEME['btn_default'], fg=THEME['fg_primary'],
        font=THEME['font_bold'],
        activebackground=THEME['bg_card'], activeforeground=THEME['fg_primary'],
        relief='flat', padx=20, pady=10,
        height=1
    ).pack(pady=(20, 10), fill="x", padx=50)

    # New Game Button
    tk.Button(
        splash,
        text="Begin New Game",
        command=start_new_game,
        bg=THEME['btn_confirm'], fg='white',
        font=THEME['font_bold'],
        activebackground='#388E3C', activeforeground='white',
        relief='flat', padx=20, pady=10,
        height=1
    ).pack(pady=10, fill="x", padx=50)

    splash.mainloop()

# --- Winnings Calculation (Retained for fallback only) ---

def sort_match_keys(k):
    """Sorts match keys (G1, G2... G7, GF, GGF) numerically, handling non-numeric games safely."""
    if k.startswith('G'):
        try:
            # Handle G1 through G99
            num_part = k.replace('G', '').split('_')[0]
            if num_part.isdigit():
                 return int(num_part)
        except:
             pass

    if k == 'GF':
        # First final match
        return 99

    if k == 'GGF':
        # Grand Finals Reset
        return 100

    return 101

def _parse_json_destination(dest_data):
    """
    Translates JSON destination objects into the internal tuple/string format.
    """
    if not isinstance(dest_data, dict):
        return None

    if 'game' in dest_data and 'slot' in dest_data:
        return (dest_data['game'], int(dest_data['slot']))

    if 'result' in dest_data:
        res = dest_data['result']

        if res == 'ELIMINATED':
            rank = dest_data.get('rank', 'N/A').upper()
            return f"ELIMINATED[{rank}]"

        return res

    return None

def _parse_json_config_content(json_content):
    """
    Parses the JSON dict into the application's internal dictionary structure
    """
    config = {}
    prizes = {}

    # 1. Parse and Fix Prizes
    raw_prizes = json_content.get('prizes', {})

    if '1' in raw_prizes: prizes['1st'] = raw_prizes['1']
    if '2' in raw_prizes: prizes['2nd'] = raw_prizes['2']
    if '3' in raw_prizes: prizes['3rd'] = raw_prizes['3']

    # 2. Parse Games
    games = json_content.get('games', {})

    for match_id, data in games.items():
        match_entry = {
            'teams': data.get('teams', [None, None]),
            'W_next': _parse_json_destination(data.get('winner_advances_to')),
            'L_next': _parse_json_destination(data.get('loser_drops_to')),
            'is_winnerbracket': data.get('is_winnerbracket', 'unknown')
        }
        config[match_id] = match_entry

    return config, prizes

# --- Dynamic Config Loading ---

def load_bracket_config(num_teams, elimination_type='D'):
    """
    Reads the bracket configuration from a local .json file.
    """
    base_filename = f"{num_teams}team{elimination_type}.json"
    search_paths = [base_filename, os.path.join('data', base_filename)]

    log_message(f"Searching for bracket config: {base_filename}", "DEBUG")

    state = {}
    prizes = {}
    json_loaded = False

    for filepath in search_paths:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    content = json.load(f)
                state, prizes = _parse_json_config_content(content)
                log_message(f"Bracket config loaded: {filepath}")
                json_loaded = True
                break
            except Exception as e:
                log_message(f"Failed to read bracket config '{filepath}': {e}", "ERROR")
                raise ValueError(f"Error parsing '{filepath}': {e}")

    if not json_loaded:
        err_msg = f"Configuration file '{base_filename}' not found."
        log_message(f"Bracket config error: {err_msg}", "ERROR")
        raise FileNotFoundError(err_msg)

    # --- PATCH: AUTO-INJECT FINALS LOGIC ---
    WB_FINAL_ID = None
    LB_FINAL_ID = None

    for match_id, match_data in state.items():
        w_next = match_data.get('W_next')
        if w_next == 'CHAMPION':
            WB_FINAL_ID = match_id

    sorted_matches = sorted([k for k in state.keys() if k.startswith('G')], key=sort_match_keys)
    if not WB_FINAL_ID and len(sorted_matches) > 1:
        WB_FINAL_ID = sorted_matches[-2]
    if not LB_FINAL_ID and sorted_matches:
        LB_FINAL_ID = sorted_matches[-1]

    if WB_FINAL_ID in state: state[WB_FINAL_ID]['W_next'] = ('GF', 0)
    if LB_FINAL_ID in state: state[LB_FINAL_ID]['W_next'] = ('GF', 1)

    state['GF'] = {
        'teams': [f'W:{WB_FINAL_ID}', f'W:{LB_FINAL_ID}'],  # Store references instead of None
        'W_next': ('CHAMPION', 0),
        'L_next': ('GGF', 0),
        'is_winnerbracket': 'both'
    }

    state['GGF'] = {
        'teams': [None, None],  # Will be set when GF resolves
        'W_next': ('CHAMPION', 0),
        'L_next': ('CHAMPION', 1),
        'is_winnerbracket': 'both'
    }
    log_message(f"Finals injected — GF linked from {WB_FINAL_ID} & {LB_FINAL_ID}", "DEBUG")
    return state, prizes

def calculate_dynamic_coords(state):
    """
    Calculates X/Y coordinates for all matches, including GF/GGF.
    Adjusts spacing dynamically based on the number of teams to prevent overlaps.
    """
    coords = {}

    # Count total matches to estimate tournament size
    total_matches = sum(1 for v in state.values() if isinstance(v, dict) and 'teams' in v)

    # Dynamic spacing: more matches = more space
    if total_matches <= 6:
        MATCH_WIDTH_U = 12
        MATCH_HEIGHT_U = 6
        X_STEP_U = MATCH_WIDTH_U + 6
        Y_STEP_U = MATCH_HEIGHT_U + 4
    elif total_matches <= 12:
        MATCH_WIDTH_U = 12
        MATCH_HEIGHT_U = 6
        X_STEP_U = MATCH_WIDTH_U + 8
        Y_STEP_U = MATCH_HEIGHT_U + 5
    elif total_matches <= 20:
        MATCH_WIDTH_U = 12
        MATCH_HEIGHT_U = 6
        X_STEP_U = MATCH_WIDTH_U + 10
        Y_STEP_U = MATCH_HEIGHT_U + 6
    else:
        MATCH_WIDTH_U = 12
        MATCH_HEIGHT_U = 6
        X_STEP_U = MATCH_WIDTH_U + 12
        Y_STEP_U = MATCH_HEIGHT_U + 7

    WB_START_Y_U = 10
    LB_START_Y_U = 55
    FINALS_Y_U = 35

    sorted_keys = sorted(
        [k for k in state.keys() if k.startswith('G') or k in ['GF', 'GGF']],
        key=sort_match_keys
    )

    match_props = {}
    max_round = 0

    for mid in sorted_keys:
        props = {'track': 'WB', 'round': 1}

        if mid in ['GF', 'GGF']:
            props['track'] = 'Finals'
        elif mid.startswith('G'):
            try: num = int(mid[1:])
            except: num = 1

            if num <= 2: r = 1
            elif num <= 4: r = 2
            elif num <= 6: r = 3
            else: r = 4

            props['round'] = r
            if r > max_round: max_round = r

            if num in [4, 6, 7]: props['track'] = 'LB'

        match_props[mid] = props

    wb_counts = {}
    lb_counts = {}

    for mid in sorted_keys:
        p = match_props.get(mid)
        if not p: continue

        r = p['round']
        track = p['track']

        if track == 'WB':
            x = 2 + ((r - 1) * X_STEP_U)
            y = WB_START_Y_U + (Y_STEP_U * wb_counts.get(r, 0))
            wb_counts[r] = wb_counts.get(r, 0) + 1
            coords[mid] = (x, y)

        elif track == 'LB':
            x = 2 + ((r - 1) * X_STEP_U)
            y = LB_START_Y_U + (Y_STEP_U * lb_counts.get(r, 0))
            lb_counts[r] = lb_counts.get(r, 0) + 1
            coords[mid] = (x, y)

        elif track == 'Finals':
            finals_x = 2 + (max_round * X_STEP_U) + 5

            if mid == 'GF':
                coords[mid] = (finals_x, FINALS_Y_U)
            elif mid == 'GGF':
                coords[mid] = (finals_x + X_STEP_U, FINALS_Y_U)

    return coords

# --- Dynamic Line Drawing ---
def draw_angled_lines(canvas, state, coords, match_w, match_h, H_SCALE, V_SCALE, H_PAD, V_PAD):
    """
    Draws connecting lines using 45-degree angles ('Classic' style).
    """
    LINE_COLOR = '#BBBBBB'
    LINE_WIDTH = 2
    CHAMFER_SIZE = 15
    MIN_STRAIGHT = 15

    def get_pixel_coords(match_id):
        if match_id not in coords: return None, None
        u_x, u_y = coords[match_id]
        x = u_x * H_SCALE + H_PAD
        y = u_y * V_SCALE + V_PAD
        return x, y

    def box_center_right(match_id):
        x, y = get_pixel_coords(match_id)
        if x is None: return None, None
        return x + match_w, y + match_h / 2

    def box_in_left(match_id):
        x, y = get_pixel_coords(match_id)
        if x is None: return None, None
        return x, y + match_h / 2

    for match_id, match_data in state.items():
        if not isinstance(match_data, dict) or 'config' not in match_data: continue
        if match_id not in coords: continue

        x1, y1 = box_center_right(match_id)
        if x1 is None: continue

        for dest_key in ['W_next', 'L_next']:
            target = match_data['config'].get(dest_key)
            if not isinstance(target, tuple): continue

            next_match_id, slot = target

            if next_match_id in coords:
                x2, y2_center = box_in_left(next_match_id)
                if x2 is None: continue

                y2 = y2_center - (match_h / 4) if slot == 0 else y2_center + (match_h / 4)

                dx = x2 - x1
                dy = abs(y2 - y1)

                if dx <= 0:
                    canvas.create_line(x1, y1, x2, y2, fill=LINE_COLOR, width=LINE_WIDTH)
                    continue

                required_dx = dy + (MIN_STRAIGHT * 1.5)

                if dx > required_dx:
                    turn_point_x = x2 - dy - MIN_STRAIGHT

                    points = [
                        x1, y1,
                        turn_point_x, y1,
                        x2 - MIN_STRAIGHT, y2,
                        x2, y2
                    ]
                    canvas.create_line(points, fill=LINE_COLOR, width=LINE_WIDTH, capstyle='round')

                else:
                    mid_x = x1 + (dx / 2)
                    safe_chamfer = min(CHAMFER_SIZE, dx/2 - 2, dy/2 - 2)
                    if safe_chamfer < 2: safe_chamfer = 0

                    y_sign = 1 if y2 > y1 else -1

                    points = [
                        x1, y1,
                        mid_x - safe_chamfer, y1,
                        mid_x, y1 + (safe_chamfer * y_sign),
                        mid_x, y2 - (safe_chamfer * y_sign),
                        mid_x + safe_chamfer, y2,
                        x2, y2
                    ]
                    canvas.create_line(points, fill=LINE_COLOR, width=LINE_WIDTH, capstyle='round')

def draw_dynamic_lines(canvas, state, coords, match_w, match_h, H_SCALE, V_SCALE, H_PAD, V_PAD):
    """Draws all connection lines based on match configuration (W_next, L_next)."""

    LINE_COLOR = '#90A4AE'
    LINE_WIDTH = 2

    def get_pixel_coords(match_id):
        if match_id not in coords: return None, None
        u_x, u_y = coords[match_id]
        x = u_x * H_SCALE + H_PAD
        y = u_y * V_SCALE + V_PAD
        return x, y

    def box_center(match_id):
        x, y = get_pixel_coords(match_id)
        if x is None: return None, None
        return x + match_w, y + match_h / 2

    def box_in(match_id):
        x, y = get_pixel_coords(match_id)
        if x is None: return None, None
        return x, y + match_h / 2

    for match_id, match_data in state.items():
        if not isinstance(match_data, dict) or 'config' not in match_data: continue

        if match_id not in coords: continue

        x1_out, y1_out = box_center(match_id)
        if x1_out is None: continue

        for dest_key in ['W_next', 'L_next']:
            target = match_data['config'].get(dest_key)
            if not isinstance(target, tuple):
                 continue

            next_match_id, slot = target

            if next_match_id in coords:
                x2_in, y2_in = box_in(next_match_id)
                if x2_in is None: continue

                y2_offset = y2_in - (match_h / 4) if slot == 0 else y2_in + (match_h / 4)

                if x2_in > x1_out:
                    mid_x = x1_out + (x2_in - x1_out) / 2

                    if mid_x < x1_out + 10: mid_x = x1_out + 10
                    if mid_x > x2_in - 10: mid_x = x2_in - 10

                    canvas.create_line(x1_out, y1_out, mid_x, y1_out,
                                       mid_x, y2_offset, x2_in, y2_offset,
                                       fill=LINE_COLOR, width=LINE_WIDTH, smooth=True)
                else:
                     canvas.create_line(x1_out, y1_out, x2_in, y1_out, fill=LINE_COLOR, width=LINE_WIDTH)

def on_full_bracket_close():
    """Resets global variables when the full bracket window is closed, and exits application if in view-only mode."""
    global full_bracket_root, full_bracket_canvas, REPLAY_VIEW_ONLY, main_root

    if REPLAY_VIEW_ONLY:
        # If in view-only mode, closing the bracket window should exit the application.
        log_message("View-only mode — exiting on window close")
        on_close(main_root)
        return

    if full_bracket_root:
        full_bracket_root.destroy()
    full_bracket_root = None
    full_bracket_canvas = None






def draw_connection_lines(canvas, match_coords, h_spacing, match_w, match_h):
    """Draw connection lines between matches (optional visual enhancement)"""
    # This can be enhanced later if needed for visual flow
    pass

def draw_angled_lines_sharp(canvas, state, coords, match_w, match_h, h_scale, v_scale, h_pad, v_pad):
    """Draw connector lines with sharper angles (right-angle style)"""

    for match_id, match_data in state.items():
        if not isinstance(match_data, dict) or 'teams' not in match_data:
            continue

        team_a_ref = match_data['teams'][0]
        team_b_ref = match_data['teams'][1]

        # Team A connector
        if team_a_ref and isinstance(team_a_ref, str) and team_a_ref.startswith('W:'):
            source_id = team_a_ref[2:]
            if source_id in coords and match_id in coords:
                src_x, src_y = coords[source_id]
                src_x = src_x * h_scale + h_pad
                src_y = src_y * v_scale + v_pad

                dst_x, dst_y = coords[match_id]
                dst_x = dst_x * h_scale + h_pad
                dst_y = dst_y * v_scale + v_pad

                # Sharper right-angle lines
                mid_x = src_x + match_w + (dst_x - src_x - match_w) / 2

                canvas.create_line(src_x + match_w, src_y + match_h/4,
                                 mid_x, src_y + match_h/4,
                                 mid_x, dst_y + match_h/4,
                                 dst_x, dst_y + match_h/4,
                                 fill='#90A4AE', width=1)

        # Team B connector
        if team_b_ref and isinstance(team_b_ref, str) and team_b_ref.startswith('W:'):
            source_id = team_b_ref[2:]
            if source_id in coords and match_id in coords:
                src_x, src_y = coords[source_id]
                src_x = src_x * h_scale + h_pad
                src_y = src_y * v_scale + v_pad

                dst_x, dst_y = coords[match_id]
                dst_x = dst_x * h_scale + h_pad
                dst_y = dst_y * v_scale + v_pad

                # Sharper right-angle lines
                mid_x = src_x + match_w + (dst_x - src_x - match_w) / 2

                canvas.create_line(src_x + match_w, src_y + 3*match_h/4,
                                 mid_x, src_y + 3*match_h/4,
                                 mid_x, dst_y + 3*match_h/4,
                                 dst_x, dst_y + 3*match_h/4,
                                 fill='#90A4AE', width=1)

def resolve_team_name(team_ref):
    """Resolve a team reference (W:G7) to actual team name"""
    global TOURNAMENT_STATE

    if not team_ref:
        return None

    # If it's a direct team name, return it
    if not team_ref.startswith('W:'):
        return team_ref

    # Extract match ID from W:MATCH_ID
    source_match_id = team_ref[2:]

    if source_match_id not in TOURNAMENT_STATE:
        return None

    source_match = TOURNAMENT_STATE[source_match_id]

    # Return the winner of that match
    return source_match.get('winner') or source_match.get('champion')








def draw_large_bracket(canvas):
    """
    Vertical bracket layout - only vertical scroll, no horizontal scroll
    Winners on top, Losers on bottom, Finals centered
    """
    global TEAM_ROSTERS, REPLAY_VIEW_ONLY, TOURNAMENT_RANKINGS, TOURNAMENT_STATE

    canvas.delete('all')
    canvas.configure(bg=THEME['bg_canvas'])

    if not TOURNAMENT_STATE:
        return

    # Organize matches
    wb_matches = {}
    lb_matches = {}
    finals_matches = {}

    for match_id, match_data in TOURNAMENT_STATE.items():
        if not isinstance(match_data, dict) or 'teams' not in match_data:
            continue

        bracket_type = match_data.get('is_winnerbracket', 'unknown')

        if bracket_type == 'both':
            finals_matches[match_id] = match_data
        elif bracket_type == 'false':
            lb_matches[match_id] = match_data
        elif bracket_type == 'true':
            wb_matches[match_id] = match_data

    # Compact layout - stack matches vertically in a grid
    MATCH_W = 200
    MATCH_H = 50
    MATCHES_PER_ROW = 4  # How many matches fit horizontally
    COL_WIDTH = 240  # Space each match takes horizontally
    ROW_HEIGHT = 80   # Space each match takes vertically
    SECTION_SPACING = 100  # Space between sections
    SIDE_PAD = 20
    TOP_PAD = 40

    # Calculate dimensions
    wb_rows = (len(wb_matches) + MATCHES_PER_ROW - 1) // MATCHES_PER_ROW if wb_matches else 0
    lb_rows = (len(lb_matches) + MATCHES_PER_ROW - 1) // MATCHES_PER_ROW if lb_matches else 0
    final_rows = (len(finals_matches) + MATCHES_PER_ROW - 1) // MATCHES_PER_ROW if finals_matches else 0

    total_width = (MATCHES_PER_ROW * COL_WIDTH) + (SIDE_PAD * 2)
    total_height = (
        (wb_rows * ROW_HEIGHT if wb_matches else 0) +
        (SECTION_SPACING if wb_matches else 0) +
        (lb_rows * ROW_HEIGHT if lb_matches else 0) +
        (SECTION_SPACING if lb_matches else 0) +
        (final_rows * ROW_HEIGHT if finals_matches else 0) +
        TOP_PAD * 2 + 150
    )

    canvas.config(scrollregion=(0, 0, total_width, total_height))

    match_positions = {}
    y_pos = TOP_PAD

    # Winners Bracket
    if wb_matches:
        canvas.create_text(total_width // 2, y_pos, text="WINNER'S BRACKET",
                          anchor='n', fill='#1976D2',
                          font=('Selawik', 12, 'bold'))
        y_pos += 35

        x_pos = SIDE_PAD
        col_idx = 0

        for match_id in sorted(wb_matches.keys()):
            match_data = wb_matches[match_id]
            match_positions[match_id] = {'x': x_pos, 'y': y_pos, 'w': MATCH_W, 'h': MATCH_H}
            draw_match_box_internal(canvas, match_id, match_data, x_pos, y_pos, MATCH_W, MATCH_H)

            col_idx += 1
            x_pos += COL_WIDTH

            if col_idx >= MATCHES_PER_ROW:
                col_idx = 0
                x_pos = SIDE_PAD
                y_pos += ROW_HEIGHT

        y_pos += SECTION_SPACING

    # Losers Bracket
    if lb_matches:
        canvas.create_text(total_width // 2, y_pos, text="LOSER'S BRACKET",
                          anchor='n', fill='#D32F2F',
                          font=('Selawik', 12, 'bold'))
        y_pos += 35

        x_pos = SIDE_PAD
        col_idx = 0

        for match_id in sorted(lb_matches.keys()):
            match_data = lb_matches[match_id]
            match_positions[match_id] = {'x': x_pos, 'y': y_pos, 'w': MATCH_W, 'h': MATCH_H}
            draw_match_box_internal(canvas, match_id, match_data, x_pos, y_pos, MATCH_W, MATCH_H)

            col_idx += 1
            x_pos += COL_WIDTH

            if col_idx >= MATCHES_PER_ROW:
                col_idx = 0
                x_pos = SIDE_PAD
                y_pos += ROW_HEIGHT

        y_pos += SECTION_SPACING

    # Finals
    if finals_matches:
        canvas.create_text(total_width // 2, y_pos, text="FINALS",
                          anchor='n', fill='#FFB300',
                          font=('Selawik', 12, 'bold'))
        y_pos += 35

        x_pos = SIDE_PAD
        col_idx = 0

        for match_id in sorted(finals_matches.keys()):
            match_data = finals_matches[match_id]
            match_positions[match_id] = {'x': x_pos, 'y': y_pos, 'w': MATCH_W, 'h': MATCH_H}
            draw_match_box_internal(canvas, match_id, match_data, x_pos, y_pos, MATCH_W, MATCH_H)

            col_idx += 1
            x_pos += COL_WIDTH

            if col_idx >= MATCHES_PER_ROW:
                col_idx = 0
                x_pos = SIDE_PAD
                y_pos += ROW_HEIGHT

    # Connection lines
    for source_id, source_info in match_positions.items():
        source_match = TOURNAMENT_STATE.get(source_id, {})
        winner = source_match.get('winner') or source_match.get('champion')

        if not winner:
            continue

        for dest_id, dest_info in match_positions.items():
            dest_match = TOURNAMENT_STATE.get(dest_id, {})
            teams = dest_match.get('teams', [None, None])

            for slot_idx, team_ref in enumerate(teams):
                if isinstance(team_ref, str) and team_ref.startswith('W:'):
                    if team_ref[2:] == source_id:
                        src_x = source_info['x'] + source_info['w']
                        src_y = source_info['y'] + source_info['h'] / 2

                        dest_x = dest_info['x']
                        dest_y = dest_info['y'] + (dest_info['h'] / 4 if slot_idx == 0 else 3 * dest_info['h'] / 4)

                        mid_x = (src_x + dest_x) / 2
                        canvas.create_line(src_x, src_y, mid_x, src_y,
                                         mid_x, dest_y, dest_x, dest_y,
                                         fill='#90A4AE', width=1.5, smooth=True)


def draw_match_box_internal(canvas, match_id, match_data, x, y, w, h):
    """Draw a single match box"""
    global TEAM_ROSTERS, REPLAY_VIEW_ONLY, TOURNAMENT_RANKINGS, TOURNAMENT_STATE

    # Determine colors
    fill_color = 'white'
    outline = '#CCCCCC'
    outline_width = 1.5

    if match_data.get('champion'):
        fill_color = THEME['accent_gold']
        outline = '#B8860B'
        outline_width = 2.5
    elif match_id == TOURNAMENT_STATE.get('active_match_id') and match_data['winner'] is None:
        fill_color = '#FFF9C4'
        outline = '#FBC02D'
        outline_width = 2
    elif match_data.get('winner_color') == 'red':
        fill_color = '#FFCDD2'
        outline = '#E53935'
        outline_width = 2
    elif match_data.get('winner_color') == 'blue':
        fill_color = '#BBDEFB'
        outline = '#1976D2'
        outline_width = 2

    # Draw box
    canvas.create_rectangle(x, y, x + w, y + h,
                           fill=fill_color, outline=outline, width=outline_width,
                           tags=(f'match_{match_id}',))

    # Match ID
    canvas.create_text(x + 5, y + 3, text=f"{match_id}",
                      anchor='nw', fill='#555555',
                      font=('Selawik', 9, 'bold'))

    # Get winner
    winner = match_data.get('winner') or match_data.get('champion')

    if REPLAY_VIEW_ONLY and match_id == 'GF' and not winner:
        winner = TOURNAMENT_RANKINGS.get('1ST')

    # SPECIAL CASE: GGF shows only champion centered
    if match_id == 'GGF':
        if match_data.get('champion'):
            champion = match_data.get('champion')
            roster = TEAM_ROSTERS.get(champion, ['?','?'])
            champion_txt = f"{champion}\n{roster[0]} & {roster[1]}"

            # Center the champion text in the box
            canvas.create_text(x + w/2, y + h/2, text=champion_txt,
                              anchor='center', fill='#1B5E20',
                              font=('Selawik', 9, 'bold'))
            return  # Don't draw teams for GGF

    # SPECIAL CASE: GF undefeated champion — gold box, centered champion text
    if match_id == 'GF' and match_data.get('champion'):
        champion = match_data.get('champion')
        roster = TEAM_ROSTERS.get(champion, ['?', '?'])
        canvas.create_text(x + w/2, y + h/2,
                          text=f"🏆 {champion}\n{roster[0]} & {roster[1]}",
                          anchor='center', fill='#1B5E20',
                          font=('Selawik', 9, 'bold'))
        return

    # Teams
    team_A = match_data['teams'][0]
    team_B = match_data['teams'][1]

    # Team A
    txt_A = "TBD"
    color_A = '#000000'
    weight_A = 'normal'

    if team_A:
        if not team_A.startswith('W:'):
            roster_A = TEAM_ROSTERS.get(team_A, ['?','?'])
            txt_A = f"{team_A}({roster_A[0]}/{roster_A[1]})"
        else:
            txt_A = team_A

        if winner and team_A == winner:
            txt_A += " ✓"
            color_A = '#1B5E20'
            weight_A = 'bold'

    canvas.create_text(x + 6, y + 15, text=txt_A,
                      anchor='nw', fill=color_A,
                      font=('Selawik', 10, weight_A))

    # Divider
    canvas.create_line(x + 3, y + h/2, x + w - 3, y + h/2,
                      fill='#BDBDBD', width=0.5)

    # Team B
    txt_B = "TBD"
    color_B = '#000000'
    weight_B = 'normal'

    if team_B:
        if not team_B.startswith('W:'):
            roster_B = TEAM_ROSTERS.get(team_B, ['?','?'])
            txt_B = f"{team_B}({roster_B[0]}/{roster_B[1]})"
        else:
            txt_B = team_B

        if winner and team_B == winner:
            txt_B += " ✓"
            color_B = '#1B5E20'
            weight_B = 'bold'

    canvas.create_text(x + 6, y + h/2 + 5, text=txt_B,
                      anchor='nw', fill=color_B,
                      font=('Selawik', 10, weight_B))

def open_full_bracket():
    """Opens (or lifts) the large scrollable bracket window with improved styling and click-to-trace functionality."""
    global full_bracket_root, full_bracket_canvas, REPLAY_VIEW_ONLY

    if full_bracket_root is not None:
        try:
            full_bracket_root.lift()
            return
        except:
            full_bracket_root = None

    full_bracket_root = tk.Toplevel(main_root)
    full_bracket_root.title("Tournament Bracket")
    full_bracket_root.geometry("1200x800")
    full_bracket_root.configure(bg=THEME['bg_main'])
    full_bracket_root.protocol("WM_DELETE_WINDOW", on_full_bracket_close)

    # ========================================================================
    # HEADER SECTION
    # ========================================================================

    header = tk.Frame(full_bracket_root, bg=THEME['bg_card'], padx=20, pady=12, relief='raised', borderwidth=1)
    header.pack(fill='x', side='top')

    # Left side: Title
    left_header = tk.Frame(header, bg=THEME['bg_card'])
    left_header.pack(side='left', fill='both', expand=True)

    tk.Label(left_header, text="🏆 Tournament Bracket", font=THEME['font_title'],
             bg=THEME['bg_card'], fg=THEME['fg_primary']).pack(anchor='w')

    tk.Label(left_header, text="Full tournament bracket view", font=('Selawik', 9),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(anchor='w', pady=(3, 0))

    # Right side: Info/Buttons
    right_header = tk.Frame(header, bg=THEME['bg_card'])
    right_header.pack(side='right', padx=(20, 0))

    if REPLAY_VIEW_ONLY:
        # Search bar for player highlighting (also in replay mode)
        search_frame = tk.Frame(right_header, bg=THEME['bg_card'])
        search_frame.pack(side='left', padx=5)

        tk.Label(search_frame, text="Search Player:", font=('Selawik', 9),
                bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(side='left', padx=(0, 5))

        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, width=15,
                               font=('Selawik', 9), relief='flat')
        search_entry.pack(side='left', padx=5)

        def search_player(event=None):
            """Search for player and highlight their matches"""
            player_name = search_var.get().strip()
            dehighlight_traces(full_bracket_canvas)

            if not player_name:
                return

            # Find all teams with this player
            matching_teams = []
            for team_name, roster in TEAM_ROSTERS.items():
                if player_name.lower() in roster[0].lower() or player_name.lower() in roster[1].lower():
                    matching_teams.append(team_name)

            # Highlight all matches with these teams
            for team_name in matching_teams:
                highlight_team_matches(full_bracket_canvas, team_name, '#90EE90')

        search_entry.bind('<Return>', search_player)

        tk.Button(search_frame, text="Search", command=search_player,
                 bg=THEME['btn_confirm'], fg='white', font=('Selawik', 9),
                 relief='flat', padx=10, pady=2).pack(side='left', padx=2)

        # Add clear highlights button
        clear_btn = tk.Button(right_header, text="Clear Highlights",
                             command=lambda: dehighlight_traces(full_bracket_canvas),
                             bg=THEME['btn_cancel'], fg='white', font=THEME['font_main'],
                             relief='flat', padx=15, pady=5)
        clear_btn.pack(side='left', padx=5)

        tk.Label(right_header, text="📁 VIEW ONLY MODE", font=THEME['font_bold'],
                bg=THEME['bg_card'], fg='#FF9800').pack(side='left', padx=10)

        def _replay_export_pdf():
            champ = TOURNAMENT_RANKINGS.get('1ST')
            if not champ:
                messagebox.showwarning("Export", "No champion found — cannot export PDF.")
                return
            export_results_pdf(champ)

        tk.Button(right_header, text="Export PDF", command=_replay_export_pdf,
                 bg=THEME['btn_confirm'], fg='white', font=THEME['font_main'],
                 relief='flat', padx=15, pady=5).pack(side='left', padx=5)

        tk.Button(right_header, text="Exit", command=lambda: on_close(main_root),
                 bg=THEME['btn_cancel'], fg='white', font=THEME['font_main'],
                 relief='flat', padx=15, pady=5).pack(side='left', padx=5)
    else:
        # Search bar for player highlighting
        search_frame = tk.Frame(right_header, bg=THEME['bg_card'])
        search_frame.pack(side='left', padx=5)

        tk.Label(search_frame, text="Search Player:", font=('Selawik', 9),
                bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(side='left', padx=(0, 5))

        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, width=15,
                               font=('Selawik', 9), relief='flat')
        search_entry.pack(side='left', padx=5)

        def search_player(event=None):
            """Search for player and highlight their matches"""
            player_name = search_var.get().strip()
            dehighlight_traces(full_bracket_canvas)

            if not player_name:
                return

            # Find all teams with this player
            matching_teams = []
            for team_name, roster in TEAM_ROSTERS.items():
                if player_name.lower() in roster[0].lower() or player_name.lower() in roster[1].lower():
                    matching_teams.append(team_name)

            # Highlight all matches with these teams
            for team_name in matching_teams:
                highlight_team_matches(full_bracket_canvas, team_name, '#90EE90')

        search_entry.bind('<Return>', search_player)

        tk.Button(search_frame, text="Search", command=search_player,
                 bg=THEME['btn_confirm'], fg='white', font=('Selawik', 9),
                 relief='flat', padx=10, pady=2).pack(side='left', padx=2)

        # Add clear highlights button
        clear_btn = tk.Button(right_header, text="Clear Highlights",
                             bg=THEME['btn_cancel'], fg='white', font=THEME['font_main'],
                             relief='flat', padx=15, pady=5)
        clear_btn.pack(side='left', padx=5)

    # ========================================================================
    # BRACKET CANVAS
    # ========================================================================

    container = tk.Frame(full_bracket_root, bg=THEME['bg_main'])
    container.pack(fill='both', expand=True, padx=10, pady=10)

    v_scroll = tk.Scrollbar(container, orient='vertical')
    h_scroll = tk.Scrollbar(container, orient='horizontal')

    full_bracket_canvas = tk.Canvas(container, bg=THEME['bg_canvas'],
                                   yscrollcommand=v_scroll.set,
                                   xscrollcommand=h_scroll.set,
                                   highlightthickness=0, relief='flat')

    v_scroll.config(command=full_bracket_canvas.yview)
    h_scroll.config(command=full_bracket_canvas.xview)

    full_bracket_canvas.grid(row=0, column=0, sticky='nsew')
    v_scroll.grid(row=0, column=1, sticky='ns')
    h_scroll.grid(row=1, column=0, sticky='ew')

    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)

    # Bind mousewheel for smooth scrolling
    def _on_bracket_mousewheel(event):
        if event.num == 4 or event.delta > 0:
            full_bracket_canvas.yview_scroll(-3, "units")
        elif event.num == 5 or event.delta < 0:
            full_bracket_canvas.yview_scroll(3, "units")

    if sys.platform == 'linux':
        full_bracket_canvas.bind("<Button-4>", _on_bracket_mousewheel)
        full_bracket_canvas.bind("<Button-5>", _on_bracket_mousewheel)
    else:
        full_bracket_canvas.bind("<MouseWheel>", _on_bracket_mousewheel)

    # Bind clear button command now that canvas exists
    if not REPLAY_VIEW_ONLY:
        clear_btn.config(command=lambda: dehighlight_traces(full_bracket_canvas))

    # ========================================================================
    # FOOTER
    # ========================================================================

    footer = tk.Frame(full_bracket_root, bg=THEME['bg_card'], padx=20, pady=8, relief='raised', borderwidth=1)
    footer.pack(fill='x', side='bottom')

    status_text = "Click a match to highlight teams and show player names • Use Clear Highlights button to reset" if not REPLAY_VIEW_ONLY else "Replay View Only - Click matches to trace teams"
    tk.Label(footer, text=status_text, font=('Selawik', 8),
            bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(anchor='w')

    # ========================================================================
    # CLICK HANDLER FOR TRACING TEAMS
    # ========================================================================

    def on_bracket_click(event):
        """Handle clicks on the bracket to trace a team's path"""
        canvas = event.widget
        x, y = canvas.canvasx(event.x), canvas.canvasy(event.y)

        # Find all items at click location
        clicked_items = canvas.find_overlapping(x-10, y-10, x+10, y+10)

        for item in clicked_items:
            tags = canvas.gettags(item)
            # Look for match ID tags (format: match_X, match_G1, etc)
            for tag in tags:
                if tag.startswith('match_'):
                    match_id = tag[6:]  # Remove 'match_' prefix
                    trace_team_path(canvas, match_id)
                    return

    def trace_team_path(canvas, match_id):
        """Highlight the winner's complete path to the clicked match"""
        global TOURNAMENT_STATE

        if match_id not in TOURNAMENT_STATE:
            return

        match_data = TOURNAMENT_STATE[match_id]

        # Clear previous traces
        canvas.delete('trace_highlight')
        canvas.delete('trace_text')

        # Get the winner of this match
        winner = match_data.get('winner') or match_data.get('champion')

        # If no winner, check if it's GF/GGF with W: references
        if not winner and match_id in ['GF', 'GGF']:
            # For GF/GGF, try to resolve the teams to see if they're available
            team_a = match_data.get('teams', [None, None])[0]
            team_b = match_data.get('teams', [None, None])[1]

            resolved_a = resolve_team_name(team_a)
            resolved_b = resolve_team_name(team_b)

            if resolved_a and resolved_b:
                # Both teams are available, but no winner declared yet
                flash_effect(canvas, match_id, '#FFD700')
                return

        # If still no winner, flash and reset
        if not winner:
            flash_effect(canvas, match_id, '#FFD700')
            return

        # Highlight the clicked match in gold
        highlight_match_box(canvas, match_id, '#FFD700', None)

        # Highlight all previous matches the winner played in, with their names
        highlight_team_matches(canvas, winner, '#FFD700')

    def flash_effect(canvas, match_id, color):
        """Flash the match box and then clear"""

        for item_id in canvas.find_all():
            tags = canvas.gettags(item_id)
            if f'match_{match_id}' in tags:
                coords = canvas.coords(item_id)
                if coords and len(coords) >= 4:
                    x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]

                    # Flash 3 times
                    for i in range(3):
                        # Show color
                        canvas.create_rectangle(x1, y1, x2, y2,
                                              fill=color, outline='', tags=('trace_highlight',))
                        canvas.create_rectangle(x1, y1, x2, y2,
                                              fill='', outline='#263238', width=2, tags=('trace_highlight',))
                        canvas.update()
                        canvas.after(200)

                        # Clear
                        canvas.delete('trace_highlight')
                        canvas.update()
                        canvas.after(200)
                break

    def highlight_team_matches(canvas, team_name, color):
        """Highlight all matches this team played in, with their names in each box"""
        global TOURNAMENT_STATE, TEAM_ROSTERS

        if not team_name:
            return

        for match_id, match_data in TOURNAMENT_STATE.items():
            if not isinstance(match_data, dict) or 'teams' not in match_data:
                continue

            team_a = match_data.get('teams', [None, None])[0]
            team_b = match_data.get('teams', [None, None])[1]

            # Check if this team appears in this match
            if team_name in [team_a, team_b]:
                highlight_match_box(canvas, match_id, color, team_name)

    def highlight_match_box(canvas, match_id, color, team_name):
        """Highlight a match box with colored background and team names"""
        global TEAM_ROSTERS

        # For GF/GGF, resolve team references to get actual names
        if match_id in ['GF', 'GGF'] and team_name and team_name.startswith('W:'):
            team_name = resolve_team_name(team_name)

        found = False
        for item_id in canvas.find_all():
            tags = canvas.gettags(item_id)
            if f'match_{match_id}' in tags:
                coords = canvas.coords(item_id)
                if coords and len(coords) >= 4:
                    x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]

                    # Draw colored background
                    canvas.create_rectangle(x1, y1, x2, y2,
                                          fill=color, outline='', tags=('trace_highlight',))

                    # Draw border on top
                    canvas.create_rectangle(x1, y1, x2, y2,
                                          fill='', outline='#263238', width=2, tags=('trace_highlight',))

                    # Add team member names if we have a team name
                    if team_name and team_name in TEAM_ROSTERS:
                        roster = TEAM_ROSTERS.get(team_name, ['?', '?'])

                        # Add player names with larger font to fill the box
                        text_x = (x1 + x2) / 2

                        # Top player name
                        canvas.create_text(text_x, y1 + (y2 - y1) / 4,
                                         text=roster[0],
                                         font=('Selawik', 9, 'bold'),
                                         fill='black', anchor='center',
                                         tags=('trace_text',))

                        # Bottom player name
                        canvas.create_text(text_x, y1 + 3 * (y2 - y1) / 4,
                                         text=roster[1],
                                         font=('Selawik', 9, 'bold'),
                                         fill='black', anchor='center',
                                         tags=('trace_text',))

                    found = True
                break

    def dehighlight_traces(canvas):
        """Clear all trace highlights"""
        canvas.delete('trace_highlight')
        canvas.delete('trace_text')

    # Bind click on canvas background to dehighlight
    full_bracket_canvas.bind("<Button-3>", dehighlight_traces)  # Right-click to dehighlight

    # Bind click event
    full_bracket_canvas.bind("<Button-1>", on_bracket_click)

    draw_large_bracket(full_bracket_canvas)

def find_next_active_match():
    """Iterates through all match keys (in chronological order) to find the next ready-to-play match."""

    sorted_match_keys = sorted(
        [k for k in TOURNAMENT_STATE.keys() if k.startswith('G') or k == 'GF' or k == 'GGF'],
        key=sort_match_keys
    )

    for k in sorted_match_keys:
        data = TOURNAMENT_STATE[k]

        if data['teams'][0] and data['teams'][1] and data['winner'] is None:
            log_message(f"Next active match: {k} ({data['teams'][0]} vs {data['teams'][1]})", "DEBUG")
            return k

    log_message("No further matches found — tournament complete")
    return 'TOURNAMENT_OVER'

def _serialize_config_for_snapshot(config):
    """
    Convert any tuple destinations into lists so it's JSON-serializable.
    e.g. ('G4', 1) -> ['G4', 1]
    Leave strings alone.
    """
    if isinstance(config, dict):
        out = {}
        for k, v in config.items():
            if isinstance(v, tuple):
                out[k] = [v[0], int(v[1])]
            else:
                out[k] = v
        return out
    return config

def serialize_snapshot():
    """
    Produce the minimal tournament snapshot to support replay.
    Now includes champion to preserve finals resolution across view-only mode.
    """
    snapshot = {
        "type": "SNAPSHOT",
        "version": SNAPSHOT_VERSION,
        "timestamp": time.time(),
        "teams": list(TEAMS),
        "rosters": dict(TEAM_ROSTERS),
        "state": {},
        "rankings": dict(TOURNAMENT_RANKINGS),
        "active_match_id": TOURNAMENT_STATE.get("active_match_id"),
        "match_history": list(MATCH_HISTORY),
        "match_durations": list(MATCH_DURATIONS),
    }

    # Only save persistent match fields — ephemeral UI/timer fields are deliberately excluded.
    _MATCH_SAVE_KEYS = ('teams', 'winner', 'winner_color', 'is_reset', 'champion',
                        'is_winnerbracket', 'start_time', 'duration')

    for mid, match_data in TOURNAMENT_STATE.items():
        if isinstance(match_data, dict):
            snapshot["state"][mid] = {
                k: match_data.get(k) for k in _MATCH_SAVE_KEYS
            }
            snapshot["state"][mid]['is_reset'] = match_data.get('is_reset', False)
            snapshot["state"][mid]['is_winnerbracket'] = match_data.get('is_winnerbracket', 'unknown')
            snapshot["state"][mid]['config'] = {
                k: (list(v) if isinstance(v, tuple) else v)
                for k, v in match_data.get('config', {}).items()
            }

    return snapshot

def append_snapshot_to_file(path):
    """
    Append a single ND-JSON snapshot to the replay file.
    No writes occur if no replay file is active.
    """
    if not path:
        return

    try:
        snapshot = serialize_snapshot()
        line = json.dumps(snapshot, separators=(",", ":")) + "\n"

        # Create directory if needed
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass

        log_message(f"Snapshot saved: {path}", "DEBUG")

    except Exception as e:
        log_message(f"Failed to write snapshot to {path}: {e}", "ERROR")

def _find_final_stats_in_file(path):
    """
    Scan the replay file and return the FINAL_STATS record if one exists,
    or None if the tournament was not yet complete when the file was written.
    """
    if not path or not os.path.exists(path):
        return None
    result = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("type") == "FINAL_STATS":
                    result = obj
            except Exception:
                continue
    return result

def _compute_final_stats(champion):
    """
    Compute the full set of final-screen statistics from current globals and
    return them as a plain serialisable dict.  Called both when saving to the
    replay file and when building the PDF from a replay.
    """
    stats = {}

    # ── Standings ────────────────────────────────────────────────────────────
    standings = []
    for key in ('1ST', '2ND', '3RD'):
        team = TOURNAMENT_RANKINGS.get(key)
        if team:
            wins, losses = get_team_record(team)
            standings.append({
                'rank': key,
                'team': team,
                'roster': TEAM_ROSTERS.get(team, []),
                'wins': wins,
                'losses': losses,
            })
    stats['standings'] = standings

    # ── Tournament totals ─────────────────────────────────────────────────────
    total_teams   = len(TEAMS)
    total_players = sum(len(r) for r in TEAM_ROSTERS.values())
    total_matches = len(MATCH_DURATIONS)
    total_time    = sum(MATCH_DURATIONS)
    avg_time      = int(total_time / total_matches) if total_matches else 0
    stats['total_teams']   = total_teams
    stats['total_players'] = total_players
    stats['total_matches'] = total_matches
    stats['total_time_s']  = total_time
    stats['avg_time_s']    = avg_time

    # Longest win streak
    if MATCH_HISTORY:
        best_streak, best_team_s = 0, None
        cur_streak, cur_team = 0, None
        for rec in MATCH_HISTORY:
            if rec['winner'] == cur_team:
                cur_streak += 1
            else:
                cur_team, cur_streak = rec['winner'], 1
            if cur_streak > best_streak:
                best_streak, best_team_s = cur_streak, cur_team
        if best_streak > 1:
            stats['longest_streak'] = {'team': best_team_s, 'count': best_streak}

    # Champion win rate
    champ_wins, champ_losses = get_team_record(champion)
    stats['champion_wins']   = champ_wins
    stats['champion_losses'] = champ_losses

    # WB / LB / Finals split
    wb_ids  = {mid for mid, md in TOURNAMENT_STATE.items()
               if isinstance(md, dict) and md.get('is_winnerbracket') is True}
    lb_ids  = {mid for mid, md in TOURNAMENT_STATE.items()
               if isinstance(md, dict) and md.get('is_winnerbracket') is False}
    fin_ids = {'GF', 'GGF'}
    stats['wb_played']  = sum(1 for r in MATCH_HISTORY if r.get('id') in wb_ids)
    stats['lb_played']  = sum(1 for r in MATCH_HISTORY if r.get('id') in lb_ids)
    stats['fin_played'] = sum(1 for r in MATCH_HISTORY if r.get('id') in fin_ids)

    # ── Match breakdown ───────────────────────────────────────────────────────
    total_h   = len(MATCH_HISTORY)
    red_wins  = sum(1 for x in MATCH_HISTORY if x['color'] == 'red')
    blue_wins = sum(1 for x in MATCH_HISTORY if x['color'] == 'blue')
    stats['red_wins']  = red_wins
    stats['blue_wins'] = blue_wins

    if MATCH_DURATIONS and MATCH_HISTORY:
        paired = list(zip(MATCH_DURATIONS, MATCH_HISTORY))
        long_dur, long_rec = max(paired, key=lambda x: x[0])
        shrt_dur, shrt_rec = min(paired, key=lambda x: x[0])
        stats['longest_match']  = {'duration_s': long_dur,
                                    'winner': long_rec['winner'],
                                    'id': long_rec['id']}
        stats['shortest_match'] = {'duration_s': shrt_dur,
                                    'winner': shrt_rec['winner'],
                                    'id': shrt_rec['id']}

    team_wins_map = {}
    for rec in MATCH_HISTORY:
        team_wins_map[rec['winner']] = team_wins_map.get(rec['winner'], 0) + 1
    if team_wins_map:
        top_team = max(team_wins_map, key=team_wins_map.get)
        stats['most_wins'] = {'team': top_team, 'count': team_wins_map[top_team]}

    # ── Scoring stats ─────────────────────────────────────────────────────────
    scored_recs = [r for r in MATCH_HISTORY if 'red_score' in r and 'blue_score' in r]
    if scored_recs:
        high_rec    = max(scored_recs, key=lambda x: max(x['red_score'], x['blue_score']))
        margins     = [abs(r['red_score'] - r['blue_score']) for r in scored_recs]
        win_scores  = [max(r['red_score'], r['blue_score']) for r in scored_recs]
        loss_scores = [min(r['red_score'], r['blue_score']) for r in scored_recs]
        closest     = min(scored_recs, key=lambda x: abs(x['red_score'] - x['blue_score']))
        blowout     = max(scored_recs, key=lambda x: abs(x['red_score'] - x['blue_score']))

        team_pts = {}
        for rec in scored_recs:
            if rec['color'] == 'red':
                win_pts, loss_pts = rec['red_score'], rec['blue_score']
            else:
                win_pts, loss_pts = rec['blue_score'], rec['red_score']
            team_pts[rec['winner']] = team_pts.get(rec['winner'], 0) + win_pts
            team_pts[rec['loser']]  = team_pts.get(rec['loser'],  0) + loss_pts

        stats['scoring'] = {
            'high_score':    max(high_rec['red_score'], high_rec['blue_score']),
            'high_score_low': min(high_rec['red_score'], high_rec['blue_score']),
            'high_score_winner': high_rec['winner'],
            'high_score_id': high_rec['id'],
            'avg_margin':    round(sum(margins) / len(margins), 2),
            'avg_win':       round(sum(win_scores)  / len(win_scores),  2),
            'avg_loss':      round(sum(loss_scores) / len(loss_scores), 2),
            'closest':  {'id': closest['id'], 'winner': closest['winner'],
                         'win': max(closest['red_score'], closest['blue_score']),
                         'loss': min(closest['red_score'], closest['blue_score'])},
            'blowout':  {'id': blowout['id'], 'winner': blowout['winner'],
                         'win': max(blowout['red_score'], blowout['blue_score']),
                         'loss': min(blowout['red_score'], blowout['blue_score'])},
        }
        if team_pts:
            top_scorer = max(team_pts, key=team_pts.get)
            stats['scoring']['top_scorer'] = {'team': top_scorer,
                                               'pts': team_pts[top_scorer]}

    # ── Misc ──────────────────────────────────────────────────────────────────
    team_matches_map = {}
    for rec in MATCH_HISTORY:
        for t in [rec['winner'], rec['loser']]:
            team_matches_map[t] = team_matches_map.get(t, 0) + 1
    if team_matches_map:
        busiest = max(team_matches_map, key=team_matches_map.get)
        stats['most_active'] = {'team': busiest, 'count': team_matches_map[busiest]}

    lb_runs = {}
    for rec in MATCH_HISTORY:
        lb_runs[rec['winner']] = lb_runs.get(rec['winner'], 0) + 1
    lb_contenders = {t: w for t, w in lb_runs.items()
                     if sum(1 for x in MATCH_HISTORY if x['loser'] == t) > 0}
    if lb_contenders:
        grinder = max(lb_contenders, key=lb_contenders.get)
        grind_losses = sum(1 for x in MATCH_HISTORY if x['loser'] == grinder)
        stats['best_lb_run'] = {'team': grinder,
                                 'wins': lb_contenders[grinder],
                                 'losses': grind_losses}

    all_teams_hist = {r['winner'] for r in MATCH_HISTORY} | {r['loser'] for r in MATCH_HISTORY}
    team_total_m   = {t: sum(1 for x in MATCH_HISTORY if x['winner']==t or x['loser']==t)
                      for t in all_teams_hist}
    eliminated = {t: m for t, m in team_total_m.items() if t != champion}
    if eliminated:
        quickest = min(eliminated, key=eliminated.get)
        stats['quickest_exit'] = {'team': quickest, 'matches': eliminated[quickest]}

    gf_data = TOURNAMENT_STATE.get('GF', {})
    stats['had_gf_reset'] = bool(isinstance(gf_data, dict) and gf_data.get('is_reset', False))

    stats['match_history'] = list(MATCH_HISTORY)

    return stats

def append_final_stats_to_file(path, champion):
    """
    Write a single FINAL_STATS ND-JSON line to the replay file.
    Called once when active_match_id transitions to TOURNAMENT_OVER.
    Safe to call if the file already has a FINAL_STATS line — checks first.
    """
    if not path:
        return
    if _find_final_stats_in_file(path) is not None:
        log_message("FINAL_STATS already present in replay file — skipping", "DEBUG")
        return
    try:
        record = {
            "type":      "FINAL_STATS",
            "version":   SNAPSHOT_VERSION,
            "timestamp": time.time(),
            "champion":  champion,
            "stats":     _compute_final_stats(champion),
        }
        line = json.dumps(record, separators=(",", ":")) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        log_message(f"FINAL_STATS written to replay file: {path}")
    except Exception as e:
        log_message(f"Failed to write FINAL_STATS: {e}", "ERROR")


def handle_match_resolution(winner, loser, winning_color, match_id):
    """
    Propagates the winner/loser of the *specific* completed match (match_id)
    to the next games, with GF/GGF reset logic.
    """
    global current_match_res_buttons, TOURNAMENT_RANKINGS

    log_message(f"Resolving match {match_id}: {winner} ({winning_color}) defeated {loser}")

    if match_id == 'TOURNAMENT_OVER':
         messagebox.showerror("Error", "Attempted to resolve 'TOURNAMENT_OVER' state.")
         TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
         reset_game(update_teams=True)
         log_message("Attempted to resolve TOURNAMENT_OVER state — aborting", "ERROR")
         return

    match_data = TOURNAMENT_STATE.get(match_id)

    if not match_data or 'config' not in match_data:
        log_message(f"Match {match_id} config missing or invalid — cannot resolve", "ERROR")
        messagebox.showerror("Error", f"Match {match_id} configuration data is missing or invalid.")
        TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
        reset_game(update_teams=True)
        return

    match_config = match_data['config']

    if match_data.get('winner') is not None and not match_data.get('is_reset', False):
        log_message(f"Match {match_id} already resolved — skipping", "WARN")
        messagebox.showinfo("Error", f"Match {match_id} already resolved.")
        return

    match_data['winner'] = winner
    match_data['winner_color'] = winning_color

    # 1. Handle Grand Finals Bracket Reset/Championship Win Logic (GF and GGF)
    if match_id == 'GF':
        wb_finalist = match_data['teams'][0]

        # Case 1: LB Winner (winner) defeats WB Winner (loser) in GF -> FORCES RESET
        if winner != wb_finalist and not match_data.get('is_reset', False):
            match_data['is_reset'] = True
            # KEEP the winner and color recorded - don't clear them

            reset_game_id = next((k for k in TOURNAMENT_STATE if k == 'GGF'), 'GGF')

            if reset_game_id in TOURNAMENT_STATE:
                # Use the actual names (winner/loser) since they're already resolved from GF
                TOURNAMENT_STATE[reset_game_id]['teams'] = [winner, loser]
                TOURNAMENT_STATE[reset_game_id]['is_reset'] = True

            w_roster = " & ".join(TEAM_ROSTERS.get(winner, ["P1", "P2"]))
            l_roster = " & ".join(TEAM_ROSTERS.get(loser, ["P3", "P4"]))
            messagebox.showwarning("Final Round!",
                                f"{w_roster} have demoted {l_roster} from undefeated status!")

            TOURNAMENT_STATE['active_match_id'] = 'GGF'
            log_message(f"GF bracket reset — {winner} vs {loser} in GGF")

            reset_game()
            return # EXIT after reset handling

        # Case 2: WB Winner (winner) defeats LB Winner (loser) in GF -> TOURNAMENT OVER
        elif winner == wb_finalist:
            match_data['champion'] = winner
            TOURNAMENT_RANKINGS['1ST'] = winner
            TOURNAMENT_RANKINGS['2ND'] = loser
            TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
            # GGF is not needed — remove it entirely so it never appears in the bracket
            TOURNAMENT_STATE.pop('GGF', None)
            log_message(f"GF complete — Champion: {winner} (1st), Runner-up: {loser} (2nd)")
            if full_bracket_canvas:
                draw_large_bracket(full_bracket_canvas)
            reset_game()
            return

    elif match_id == 'GGF':
        # Case 3: GGF is played -> TOURNAMENT OVER
        match_data['champion'] = winner  # Also set champion on GGF
        TOURNAMENT_STATE[match_id]['champion'] = winner
        TOURNAMENT_RANKINGS['1ST'] = winner
        gfgf_loser = TOURNAMENT_STATE[match_id]['teams'][0] if winner == TOURNAMENT_STATE[match_id]['teams'][1] else TOURNAMENT_STATE[match_id]['teams'][1]
        TOURNAMENT_RANKINGS['2ND'] = gfgf_loser

        TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
        log_message(f"Reset match {match_id} complete — 1st: {winner}, 2nd: {gfgf_loser}. Tournament over.")

        # Redraw the bracket to show GGF champion
        if full_bracket_canvas:
            draw_large_bracket(full_bracket_canvas)

        reset_game()
        return

    # 2. Propagate Winner
    w_target = match_config.get('W_next')
    if isinstance(w_target, tuple):
        next_match_id, slot = w_target
        if next_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[next_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[next_match_id]['teams'][slot] = winner
            log_message(f"  -> Winner {winner} → {next_match_id} [slot {slot}]", "DEBUG")
    elif w_target == 'CHAMPION':
         match_data['champion'] = winner
         TOURNAMENT_RANKINGS['1ST'] = winner
         log_message(f"Champion crowned: {winner} (match {match_id})")

    # 3. Propagate Loser and Assign Elimination Rank (MODIFIED)
    l_target = match_config.get('L_next')

    if isinstance(l_target, tuple):
        loser_match_id, slot = l_target
        if loser_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[loser_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[loser_match_id]['teams'][slot] = loser
            log_message(f"  -> Loser {loser} → {loser_match_id} [slot {slot}]", "DEBUG")
    elif l_target and l_target.startswith('ELIMINATED'):
        rank_match = re.search(r'\[(\w+)\]', l_target)
        if rank_match:
            rank = rank_match.group(1)
            if rank not in TOURNAMENT_RANKINGS:
                TOURNAMENT_RANKINGS[rank] = loser
                log_message(f"  -> {loser} eliminated, ranked {rank}", "DEBUG")

    elif l_target and l_target.endswith('_CONDITIONAL'):
        pass

    # Record to history
    if match_id != 'TOURNAMENT_OVER' and winner and loser:
        MATCH_HISTORY.append({
            'id': match_id,
            'winner': winner,
            'loser': loser,
            'color': winning_color
        })

    # 4. Find the next actively playable match
    TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
    log_message(f"Match {match_id} resolved. Next: {TOURNAMENT_STATE['active_match_id']}")

    reset_game(update_teams=False)

def draw_small_bracket_view(canvas, state):
    """
    Simplified bracket view that now reconstructs GF winner in strict
    view-only mode for visual consistency.
    """
    global REPLAY_VIEW_ONLY, TOURNAMENT_RANKINGS

    canvas.delete('all')
    canvas.configure(bg=THEME['bg_canvas'])

    canvas.update_idletasks()
    W = canvas.winfo_width()
    H = canvas.winfo_height()

    if W < 50:
        W = 400
    if H < 50:
        H = 100

    sorted_match_keys = sorted(
        [k for k in state.keys() if k.startswith('G') or k in ('GF','GGF')],
        key=sort_match_keys
    )

    if not sorted_match_keys:
        return

    # categorize matches
    wb_matches = []
    lb_matches = []
    final_matches = []

    for mid in sorted_match_keys:
        data = state.get(mid)
        if mid in ('GF','GGF'):
            final_matches.append(mid)
            continue

        l_next = data['config'].get('L_next')
        if isinstance(l_next, tuple):
            wb_matches.append(mid)
        elif l_next and 'ELIMINATED' in str(l_next):
            lb_matches.append(mid)
        else:
            wb_matches.append(mid)

    # layout
    num_cols = max(len(wb_matches), len(lb_matches)) + len(final_matches)
    if num_cols < 1:
        num_cols = 1

    padding_x = 10
    available_w = W - (2 * padding_x)
    col_width = available_w / num_cols

    W_box = min(60, col_width - 5)
    H_box = 20

    Y_TOP = H * 0.25
    Y_MID = H * 0.50
    Y_BOT = H * 0.75

    y_top = Y_TOP - H_box/2
    y_mid = Y_MID - H_box/2
    y_bot = Y_BOT - H_box/2

    coords = {}

    # WB
    for i, mid in enumerate(wb_matches):
        cx = padding_x + i * col_width + col_width/2
        coords[mid] = (cx - W_box/2, y_top)

    # LB
    for i, mid in enumerate(lb_matches):
        cx = padding_x + i * col_width + col_width/2
        coords[mid] = (cx - W_box/2, y_bot)

    # Finals
    start_fcol = max(len(wb_matches), len(lb_matches))
    for i, mid in enumerate(final_matches):
        cx = padding_x + (start_fcol + i) * col_width + col_width/2
        coords[mid] = (cx - W_box/2, y_mid)

    active_id = state.get('active_match_id')

    for match_id, (x, y) in coords.items():
        data = state.get(match_id)
        if not isinstance(data, dict):
            continue

        fill_color = 'white'
        outline = '#333333'
        text_color = 'black'

        if data.get('champion'):
            fill_color = THEME['accent_gold']
            text_color = 'black'
        elif match_id == active_id and data.get('winner') is None:
            fill_color = '#FFF9C4'
        elif data.get('is_reset') and data.get('winner') is None:
            fill_color = '#FFCC80'
        elif data.get('winner'):
            wc = data.get('winner_color')
            if wc == 'red':
                fill_color = '#FFCDD2'
            elif wc == 'blue':
                fill_color = '#BBDEFB'
            else:
                fill_color = '#C8E6C9'

        # Determine winner
        winner = data.get('winner') or data.get('champion')

        # -----------------------------
        # GF reconstruction
        # -----------------------------
        if REPLAY_VIEW_ONLY and match_id == 'GF' and not winner:
            winner = TOURNAMENT_RANKINGS.get('1ST')

        canvas.create_rectangle(x, y, x + W_box, y + H_box,
                                fill=fill_color, outline=outline)
        text_id = match_id.replace('G', '')
        canvas.create_text(x + W_box/2, y + H_box/2,
                           text=text_id,
                           font=('Selawik', 7, 'bold'),
                           fill=text_color)

def format_destination(dest):
    """Converts the parsed destination tuple/string into a user-readable string."""
    if dest == 'CHAMPION':
        return "🏆 CHAMPION"
    if isinstance(dest, tuple):
        match_id, slot = dest
        slot_name = "Top Slot (0)" if slot == 0 else "Bottom Slot (1)"
        return f"{match_id} [{slot_name}]"
    if isinstance(dest, str) and dest.endswith('_CONDITIONAL'):
        return f"Grand Finals Reset ({dest.split('_')[0]}R)"
    if dest and str(dest).upper().startswith('ELIMINATED['):
        return f"❌ {dest}"
    return str(dest)

def get_team_record(team_name):
    """Calculates the current wins and losses for a given team from TOURNAMENT_STATE."""
    wins = 0
    losses = 0

    ggf_has_result = isinstance(TOURNAMENT_STATE.get('GGF'), dict) and                      TOURNAMENT_STATE['GGF'].get('winner') is not None

    for match_id, match_data in TOURNAMENT_STATE.items():
        if not isinstance(match_data, dict):
            continue

        # When GGF has been played it is the authoritative result for the finals.
        # Skip GF entirely to avoid double-counting wins/losses for both finalists.
        if match_id == 'GF' and match_data.get('is_reset') and ggf_has_result:
            continue

        winner = match_data.get('winner')

        if winner:
            if team_name == winner:
                wins += 1
            elif team_name in match_data.get('teams', []) and team_name != winner:
                losses += 1

    return wins, losses

def update_winner_buttons():
    """Updates the text on the winner buttons to show the assigned team names."""
    global btn_red, btn_blue, current_match_teams

    team_red = current_match_teams.get('red', 'RED TEAM')
    team_blue = current_match_teams.get('blue', 'BLUE TEAM')

    if btn_red and btn_blue:
        btn_red.config(text=f"WINNERS: {team_red}")
        btn_blue.config(text=f"WINNERS: {team_blue}")
    log_message(f"Winner buttons updated — Red: {team_red}, Blue: {team_blue}", "DEBUG")

def swap_teams():
    """Swaps the Red and Blue teams in the current match UI."""
    global current_match_teams

    log_message(f"Teams swapped — Red: {current_match_teams['red']}, Blue: {current_match_teams['blue']}")

    temp = current_match_teams['red']
    current_match_teams['red'] = current_match_teams['blue']
    current_match_teams['blue'] = temp

    update_scoreboard_display()

def export_results_pdf(champion):
    """
    Exports the tournament final screen stats to a PDF file using ReportLab.
    Mirrors the data logic of display_final_rankings().
    """
    if not REPORTLAB_AVAILABLE:
        messagebox.showerror(
            "Missing Library",
            "ReportLab is not installed.\n\nRun:  pip install reportlab\n\nthen restart the app."
        )
        return

    filepath = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")],
        initialfile=f"tournament_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        title="Save Tournament Results PDF"
    )
    if not filepath:
        return  # User cancelled

    try:
        # ── Colour palette mirroring THEME ──────────────────────────────────
        C_BG        = colors.HexColor('#263238')
        C_CARD      = colors.HexColor('#37474F')
        C_GOLD      = colors.HexColor('#FFD700')
        C_FG        = colors.HexColor('#ECEFF1')
        C_FG2       = colors.HexColor('#B0BEC5')
        C_RED       = colors.HexColor('#E53935')
        C_BLUE      = colors.HexColor('#1E88E5')
        C_WHITE     = colors.white

        # ── Paragraph styles ────────────────────────────────────────────────
        base = ParagraphStyle('base', fontName='Helvetica',
                              fontSize=10, textColor=C_FG,
                              backColor=C_BG, leading=14)
        title_style = ParagraphStyle('title', parent=base,
                                     fontName='Helvetica-Bold',
                                     fontSize=18, textColor=C_GOLD,
                                     alignment=TA_CENTER, spaceAfter=4)
        champ_name  = ParagraphStyle('champName', parent=base,
                                     fontName='Helvetica-Bold',
                                     fontSize=15, textColor=C_FG,
                                     alignment=TA_CENTER)
        champ_sub   = ParagraphStyle('champSub', parent=base,
                                     fontSize=10, textColor=C_FG2,
                                     alignment=TA_CENTER, spaceAfter=8)
        sec_hdr     = ParagraphStyle('secHdr', parent=base,
                                     fontName='Helvetica-Bold',
                                     fontSize=10, textColor=C_GOLD,
                                     spaceBefore=10, spaceAfter=4)
        footer_style= ParagraphStyle('footer', parent=base,
                                     fontSize=8, textColor=C_FG2,
                                     alignment=TA_CENTER)

        # ── Table cell styles ────────────────────────────────────────────────
        LABEL_STYLE = ParagraphStyle('lbl', parent=base,
                                     fontSize=9, textColor=C_FG2)
        VALUE_STYLE = ParagraphStyle('val', parent=base,
                                     fontName='Helvetica-Bold',
                                     fontSize=9, textColor=C_FG)

        def lbl(text):
            return Paragraph(text, LABEL_STYLE)

        def val(text, color=None):
            s = ParagraphStyle('v', parent=VALUE_STYLE,
                               textColor=color or C_FG)
            return Paragraph(text, s)

        def section(text):
            return Paragraph(text, sec_hdr)

        def hr():
            return HRFlowable(width="100%", thickness=1,
                              color=C_GOLD, spaceAfter=6, spaceBefore=2)

        # ── Shared table style ───────────────────────────────────────────────
        def stat_table_style():
            return TableStyle([
                ('BACKGROUND',  (0, 0), (-1, -1), C_CARD),
                ('TEXTCOLOR',   (0, 0), (-1, -1), C_FG),
                ('ROWBACKGROUNDS', (0, 0), (-1, -1), [C_CARD, colors.HexColor('#2E3C43')]),
                ('LEFTPADDING',  (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING',   (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
            ])

        # ── Build story ──────────────────────────────────────────────────────
        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            leftMargin=0.6*inch, rightMargin=0.6*inch,
            topMargin=0.6*inch,  bottomMargin=0.6*inch,
        )

        W = letter[0] - 1.2*inch   # usable width
        COL_W = (W - 0.15*inch) / 2  # two equal columns

        story = []

        # ── Header ───────────────────────────────────────────────────────────
        story.append(Paragraph("TOURNAMENT COMPLETE", title_style))
        story.append(hr())

        # ── Champion block ───────────────────────────────────────────────────
        champ_roster = " / ".join(TEAM_ROSTERS.get(champion, ['?', '?']))
        champ_table = Table(
            [[Paragraph("CHAMPIONS", ParagraphStyle('ct', parent=base,
                         fontName='Helvetica-Bold', fontSize=10,
                         textColor=C_GOLD, alignment=TA_CENTER)),],
             [Paragraph(champ_roster, champ_name)],
            ],
            colWidths=[W]
        )
        champ_table.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, -1), colors.HexColor('#455A64')),
            ('ALIGN',        (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING',   (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
        ]))
        story.append(champ_table)
        story.append(hr())

        # ── Collect all stat rows for left / right columns ────────────────────
        left_rows  = []
        right_rows = []

        # LEFT — Final Standings
        left_rows.append([section("Final Standings"), ""])
        places = [
            ('1st Place', '1ST', C_GOLD),
            ('2nd Place', '2ND', C_FG),
            ('3rd Place', '3RD', C_FG2),
        ]
        for label_text, key, color in places:
            team = TOURNAMENT_RANKINGS.get(key)
            if not team:
                continue
            roster = " / ".join(TEAM_ROSTERS.get(team, ['?', '?']))
            wins, losses = get_team_record(team)
            left_rows.append([lbl(f"{label_text}  (W/L {wins}/{losses})"),
                               val(roster, color)])

        # LEFT — Tournament Stats
        left_rows.append([section("Tournament Stats"), ""])
        total_teams   = len(TEAMS)
        total_players = sum(len(r) for r in TEAM_ROSTERS.values())
        total_matches = len(MATCH_DURATIONS)
        total_time    = sum(MATCH_DURATIONS)
        avg_time      = int(total_time / total_matches) if total_matches else 0

        left_rows.append([lbl("Teams"),           val(str(total_teams))])
        left_rows.append([lbl("Players"),         val(str(total_players))])
        left_rows.append([lbl("Matches played"),  val(str(total_matches))])
        left_rows.append([lbl("Total time"),      val(format_seconds(total_time))])
        left_rows.append([lbl("Avg match time"),  val(format_seconds(avg_time))])

        # Longest win streak (consecutive wins by one team across MATCH_HISTORY order)
        if MATCH_HISTORY:
            best_streak, best_team_s = 0, None
            cur_streak,  cur_team    = 0, None
            for rec in MATCH_HISTORY:
                if rec['winner'] == cur_team:
                    cur_streak += 1
                else:
                    cur_team   = rec['winner']
                    cur_streak = 1
                if cur_streak > best_streak:
                    best_streak, best_team_s = cur_streak, cur_team
            if best_streak > 1 and best_team_s:
                streak_roster = " & ".join(TEAM_ROSTERS.get(best_team_s, ['?', '?']))
                left_rows.append([lbl("Longest win streak"),
                                   val(f"{streak_roster}  ({best_streak})")])

        # Champion win rate
        champ_wins, champ_losses = get_team_record(champion)
        champ_played = champ_wins + champ_losses
        champ_pct = int(champ_wins / champ_played * 100) if champ_played else 0
        left_rows.append([lbl("Champion win rate"),
                           val(f"{champ_wins}W-{champ_losses}L  ({champ_pct}%)", C_GOLD)])

        # WB vs LB match split
        wb_count = sum(1 for r in MATCH_HISTORY
                       if not (r.get('id', '').startswith('G') and
                               any(r.get('id', '') == mid
                                   for mid, md in TOURNAMENT_STATE.items()
                                   if isinstance(md, dict) and not md.get('is_winnerbracket', True))))
        # Simpler: count by match ID prefix patterns — GF/GGF are finals, Gx depends on is_winnerbracket
        wb_ids = {mid for mid, md in TOURNAMENT_STATE.items()
                  if isinstance(md, dict) and md.get('is_winnerbracket') is True}
        lb_ids = {mid for mid, md in TOURNAMENT_STATE.items()
                  if isinstance(md, dict) and md.get('is_winnerbracket') is False}
        fin_ids= {'GF', 'GGF'}
        wb_played  = sum(1 for r in MATCH_HISTORY if r.get('id') in wb_ids)
        lb_played  = sum(1 for r in MATCH_HISTORY if r.get('id') in lb_ids)
        fin_played = sum(1 for r in MATCH_HISTORY if r.get('id') in fin_ids)
        if wb_played or lb_played or fin_played:
            parts = []
            if wb_played:  parts.append(f"{wb_played} WB")
            if lb_played:  parts.append(f"{lb_played} LB")
            if fin_played: parts.append(f"{fin_played} Finals")
            left_rows.append([lbl("Match breakdown"), val("  /  ".join(parts))])

        # RIGHT — Match Breakdown
        right_rows.append([section("Match Breakdown"), ""])
        total_h   = len(MATCH_HISTORY)
        red_wins  = sum(1 for x in MATCH_HISTORY if x['color'] == 'red')
        blue_wins = sum(1 for x in MATCH_HISTORY if x['color'] == 'blue')
        red_pct   = int(red_wins  / total_h * 100) if total_h else 0
        blue_pct  = int(blue_wins / total_h * 100) if total_h else 0
        right_rows.append([lbl("Red side wins"),  val(f"{red_wins} ({red_pct}%)", C_RED)])
        right_rows.append([lbl("Blue side wins"), val(f"{blue_wins} ({blue_pct}%)", C_BLUE)])

        if MATCH_DURATIONS and MATCH_HISTORY:
            paired = list(zip(MATCH_DURATIONS, MATCH_HISTORY))
            long_dur, long_rec = max(paired, key=lambda x: x[0])
            shrt_dur, shrt_rec = min(paired, key=lambda x: x[0])
            lw = " & ".join(TEAM_ROSTERS.get(long_rec['winner'], ['?', '?']))
            sw = " & ".join(TEAM_ROSTERS.get(shrt_rec['winner'], ['?', '?']))
            right_rows.append([lbl("Longest match"),  val(f"{format_seconds(long_dur)}  ({lw})")])
            right_rows.append([lbl("Shortest match"), val(f"{format_seconds(shrt_dur)}  ({sw})")])

        team_wins = {}
        for rec in MATCH_HISTORY:
            team_wins[rec['winner']] = team_wins.get(rec['winner'], 0) + 1
        if team_wins:
            top_team   = max(team_wins, key=team_wins.get)
            top_roster = " & ".join(TEAM_ROSTERS.get(top_team, ['?', '?']))
            right_rows.append([lbl("Most wins"),
                                val(f"{top_roster} ({team_wins[top_team]})", C_GOLD)])

        # RIGHT — Scoring Stats (only when score data present)
        scored_recs = [r for r in MATCH_HISTORY if 'red_score' in r and 'blue_score' in r]
        if scored_recs:
            high_rec   = max(scored_recs, key=lambda x: max(x['red_score'], x['blue_score']))
            high_score = max(high_rec['red_score'], high_rec['blue_score'])
            low_score  = min(high_rec['red_score'], high_rec['blue_score'])
            high_roster = " & ".join(TEAM_ROSTERS.get(high_rec['winner'], ['?', '?']))
            right_rows.append([lbl("High score"),
                                val(f"{high_score}-{low_score}  ({high_rec['id']}, {high_roster})")])

            right_rows.append([section("Scoring Stats"), ""])

            margins    = [abs(r['red_score'] - r['blue_score']) for r in scored_recs]
            win_scores = [max(r['red_score'], r['blue_score']) for r in scored_recs]
            loss_scores= [min(r['red_score'], r['blue_score']) for r in scored_recs]

            avg_margin = sum(margins) / len(margins)
            avg_win    = sum(win_scores)  / len(win_scores)
            avg_loss   = sum(loss_scores) / len(loss_scores)
            right_rows.append([lbl("Avg winning margin"), val(f"{avg_margin:.1f} pts")])
            right_rows.append([lbl("Avg final score"),    val(f"{avg_win:.1f} - {avg_loss:.1f}")])

            closest_rec = min(scored_recs, key=lambda x: abs(x['red_score'] - x['blue_score']))
            c_gap  = abs(closest_rec['red_score'] - closest_rec['blue_score'])
            c_win  = max(closest_rec['red_score'], closest_rec['blue_score'])
            c_loss = min(closest_rec['red_score'], closest_rec['blue_score'])
            c_roster = " & ".join(TEAM_ROSTERS.get(closest_rec['winner'], ['?', '?']))
            right_rows.append([lbl("Closest match"),
                                val(f"{c_win}-{c_loss} (delta {c_gap})  {closest_rec['id']}  {c_roster}")])

            blowout_rec = max(scored_recs, key=lambda x: abs(x['red_score'] - x['blue_score']))
            b_gap  = abs(blowout_rec['red_score'] - blowout_rec['blue_score'])
            b_win  = max(blowout_rec['red_score'], blowout_rec['blue_score'])
            b_loss = min(blowout_rec['red_score'], blowout_rec['blue_score'])
            b_roster = " & ".join(TEAM_ROSTERS.get(blowout_rec['winner'], ['?', '?']))
            right_rows.append([lbl("Most lopsided"),
                                val(f"{b_win}-{b_loss} (delta {b_gap})  {blowout_rec['id']}  {b_roster}")])

            team_pts = {}
            for rec in scored_recs:
                r_score = rec['red_score']
                b_score = rec['blue_score']
                if rec['color'] == 'red':
                    win_team,  win_pts  = rec['winner'], r_score
                    loss_team, loss_pts = rec['loser'],  b_score
                else:
                    win_team,  win_pts  = rec['winner'], b_score
                    loss_team, loss_pts = rec['loser'],  r_score
                team_pts[win_team]  = team_pts.get(win_team,  0) + win_pts
                team_pts[loss_team] = team_pts.get(loss_team, 0) + loss_pts
            if team_pts:
                top_scorer        = max(team_pts, key=team_pts.get)
                top_scorer_roster = " & ".join(TEAM_ROSTERS.get(top_scorer, ['?', '?']))
                right_rows.append([lbl("Most pts scored"),
                                    val(f"{top_scorer_roster} ({team_pts[top_scorer]} pts)", C_GOLD)])

        # Most active
        team_matches = {}
        for rec in MATCH_HISTORY:
            for t in [rec['winner'], rec['loser']]:
                team_matches[t] = team_matches.get(t, 0) + 1
        if team_matches:
            busiest     = max(team_matches, key=team_matches.get)
            busy_roster = " & ".join(TEAM_ROSTERS.get(busiest, ['?', '?']))
            right_rows.append([lbl("Most active"),
                                val(f"{busy_roster} ({team_matches[busiest]})")])

        # Best LB run
        lb_runs = {}
        for rec in MATCH_HISTORY:
            lb_runs[rec['winner']] = lb_runs.get(rec['winner'], 0) + 1
        lb_contenders = {t: w for t, w in lb_runs.items()
                         if sum(1 for x in MATCH_HISTORY if x['loser'] == t) > 0}
        if lb_contenders:
            grinder      = max(lb_contenders, key=lb_contenders.get)
            grind_roster = " & ".join(TEAM_ROSTERS.get(grinder, ['?', '?']))
            grind_losses = sum(1 for x in MATCH_HISTORY if x['loser'] == grinder)
            right_rows.append([lbl("Best LB Run"),
                                val(f"{grind_roster} ({lb_contenders[grinder]}W-{grind_losses}L)")])

        # Quickest exit
        all_teams_in_history = set()
        for rec in MATCH_HISTORY:
            all_teams_in_history.add(rec['winner'])
            all_teams_in_history.add(rec['loser'])
        team_total_matches = {t: sum(1 for x in MATCH_HISTORY
                                     if x['winner'] == t or x['loser'] == t)
                              for t in all_teams_in_history}
        eliminated = {t: m for t, m in team_total_matches.items() if t != champion}
        if eliminated:
            quickest     = min(eliminated, key=eliminated.get)
            quick_roster = " & ".join(TEAM_ROSTERS.get(quickest, ['?', '?']))
            right_rows.append([lbl("Quickest Exit"),
                                val(f"{quick_roster} ({eliminated[quickest]} match{'es' if eliminated[quickest] != 1 else ''})")])

        # GF reset?
        gf_data  = TOURNAMENT_STATE.get('GF', {})
        had_reset = isinstance(gf_data, dict) and gf_data.get('is_reset', False)
        champ_roster_str = " / ".join(TEAM_ROSTERS.get(champion, ['?', '?']))
        right_rows.append([lbl("Undefeated Teams"),
                            val("None" if had_reset else champ_roster_str,
                                C_FG2 if had_reset else C_GOLD)])

        # ── Build individual column tables ───────────────────────────────────
        INNER_L = COL_W * 0.45  # label sub-column
        INNER_V = COL_W * 0.55  # value sub-column

        left_table  = Table(left_rows,  colWidths=[INNER_L, INNER_V])
        right_table = Table(right_rows, colWidths=[INNER_L, INNER_V])
        left_table.setStyle(stat_table_style())
        right_table.setStyle(stat_table_style())

        # ── Combine into a two-column wrapper ────────────────────────────────
        two_col = Table(
            [[left_table, right_table]],
            colWidths=[COL_W, COL_W],
            hAlign='LEFT',
        )
        two_col.setStyle(TableStyle([
            ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING',  (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING',   (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 0),
            ('COLPADDING',   (0, 0), (-1, -1), 6),
        ]))
        story.append(two_col)
        story.append(hr())

        # ── Match History table ──────────────────────────────────────────────
        if MATCH_HISTORY:
            story.append(section("Match History"))
            hdr_style = ParagraphStyle('mhHdr', parent=base,
                                       fontName='Helvetica-Bold',
                                       fontSize=8, textColor=C_GOLD)
            cell_style = ParagraphStyle('mhCell', parent=base,
                                        fontSize=8, textColor=C_FG)

            def mhdr(t): return Paragraph(t, hdr_style)
            def mcell(t, color=None):
                s = ParagraphStyle('mc', parent=cell_style,
                                   textColor=color or C_FG)
                return Paragraph(t, s)

            history_data = [[mhdr("Match"), mhdr("Winner"), mhdr("Loser"),
                              mhdr("Score"), mhdr("Duration")]]
            for rec in MATCH_HISTORY:
                w_roster = " & ".join(TEAM_ROSTERS.get(rec['winner'], ['?', '?']))
                l_roster = " & ".join(TEAM_ROSTERS.get(rec['loser'],  ['?', '?']))
                score_str = ""
                if 'red_score' in rec and 'blue_score' in rec:
                    score_str = f"{rec['red_score']}-{rec['blue_score']}"
                idx = MATCH_HISTORY.index(rec)
                dur_str = format_seconds(MATCH_DURATIONS[idx]) if idx < len(MATCH_DURATIONS) else "-"
                w_color = C_RED if rec.get('color') == 'red' else C_BLUE
                history_data.append([
                    mcell(rec.get('id', '-')),
                    mcell(w_roster, w_color),
                    mcell(l_roster),
                    mcell(score_str),
                    mcell(dur_str),
                ])

            col_w = W / 5
            hist_table = Table(history_data, colWidths=[col_w]*5)
            hist_table.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, 0),  C_CARD),
                ('ROWBACKGROUNDS',(0, 1), (-1, -1), [C_CARD, colors.HexColor('#2E3C43')]),
                ('LINEBELOW',     (0, 0), (-1, 0),  1, C_GOLD),
                ('LEFTPADDING',   (0, 0), (-1, -1), 6),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
                ('TOPPADDING',    (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(hist_table)

        story.append(Spacer(1, 14))

        # ── Footer ───────────────────────────────────────────────────────────
        ts = datetime.datetime.now().strftime("%B %d, %Y  %I:%M %p")
        story.append(Paragraph(
            f"Moose Lodge Shuffleboard  •  Generated {ts}  •  v{SHUF_VERSION}",
            footer_style
        ))

        # ── Page background colour via onPage callback ────────────────────────
        def dark_background(canvas_obj, doc_obj):
            canvas_obj.saveState()
            canvas_obj.setFillColor(C_BG)
            canvas_obj.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
            canvas_obj.restoreState()

        doc.build(story, onFirstPage=dark_background, onLaterPages=dark_background)

        log_message(f"PDF exported: {filepath}")
        messagebox.showinfo("Export Successful",
                            f"Tournament results saved to:\n{filepath}")

    except Exception as e:
        log_message(f"PDF export failed: {e}", "ERROR")
        messagebox.showerror("Export Failed",
                             f"Could not create PDF:\n{e}")


def display_final_rankings(champion):
    """Displays the Tournament Complete screen with standings and statistics."""
    global rankings_display_frame_ref, rankings_label_ref
    global final_control_frame_ref, ui_references

    # ---- Force Footer Progress to 100% ----
    total_matches = len([
        k for k in TOURNAMENT_STATE.keys()
        if k not in ['active_match_id', 'TOURNAMENT_OVER']
    ])
    completed_matches = len(MATCH_HISTORY)
    percent = 100 if total_matches else 0

    if 'footer_progress' in ui_references:
        ui_references['footer_progress'].config(
            text=f"Match {completed_matches} of {total_matches} ({percent}%)"
        )

    # Widen the window to fit the two-column stats layout
    if main_root:
        main_root.geometry("750x620")

    # ---- Reset Frame ----
    for w in rankings_display_frame_ref.winfo_children():
        w.destroy()

    rankings_display_frame_ref.pack(fill='both', expand=True, padx=15, pady=10)

    P = rankings_display_frame_ref  # short alias

    # ==============================
    # HEADER
    # ==============================
    tk.Label(P, text="🏁  TOURNAMENT COMPLETE  🏁",
             font=THEME['font_title'], fg=THEME['accent_gold'],
             bg=THEME['bg_card'], anchor='center'
    ).pack(fill='x', pady=(8, 4))

    tk.Frame(P, bg=THEME['accent_gold'], height=2).pack(fill='x', pady=(0, 10))

    # ==============================
    # CHAMPION
    # ==============================
    champ_roster = " / ".join(TEAM_ROSTERS.get(champion, ['?', '?']))
    champ_frame = tk.Frame(P, bg=THEME['bg_canvas'], padx=10, pady=6)
    champ_frame.pack(fill='x', pady=(0, 8))
    tk.Label(champ_frame, text="🥇 CHAMPIONS",
             font=('Selawik', 10, 'bold'), fg=THEME['accent_gold'],
             bg=THEME['bg_canvas']).pack()
    tk.Label(champ_frame, text=champ_roster,
             font=('Selawik', 16, 'bold'), fg=THEME['fg_primary'],
             bg=THEME['bg_canvas']).pack()

    tk.Frame(P, bg=THEME['accent_gold'], height=2).pack(fill='x', pady=(0, 8))

    # ==============================
    # TWO-COLUMN BODY
    # ==============================
    body = tk.Frame(P, bg=THEME['bg_card'])
    body.pack(fill='both', expand=True)
    body.grid_columnconfigure(0, weight=1)
    body.grid_columnconfigure(1, weight=1)

    # --- helpers ---
    def section_header(parent, text, row):
        tk.Label(parent, text=text, font=('Selawik', 10, 'bold'),
                 fg=THEME['accent_gold'], bg=THEME['bg_card']
        ).grid(row=row, column=0, columnspan=2, sticky='w', pady=(10, 4), padx=8)

    def stat_row(parent, row, label, value, val_color=None):
        val_color = val_color or THEME['fg_primary']
        tk.Label(parent, text=label, font=('Selawik', 9),
                 fg=THEME['fg_secondary'], bg=THEME['bg_card'], anchor='w'
        ).grid(row=row, column=0, sticky='w', padx=(8, 4), pady=2)
        tk.Label(parent, text=value, font=('Selawik', 9, 'bold'),
                 fg=val_color, bg=THEME['bg_card'], anchor='w'
        ).grid(row=row, column=1, sticky='w', padx=(4, 8), pady=2)

    # ---- LEFT COLUMN: Standings + Basic Stats ----
    left = tk.Frame(body, bg=THEME['bg_card'])
    left.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
    left.grid_columnconfigure(0, weight=1)
    left.grid_columnconfigure(1, weight=2)

    section_header(left, "Final Standings", 0)

    places = [
        ('🥇 1st', '1ST', THEME['accent_gold']),
        ('🥈 2nd', '2ND', THEME['fg_primary']),
        ('🥉 3rd', '3RD', THEME['fg_secondary']),
    ]
    r = 1
    for label_text, key, color in places:
        team = TOURNAMENT_RANKINGS.get(key)
        if not team:
            continue
        roster = " / ".join(TEAM_ROSTERS.get(team, ['?', '?']))
        wins, losses = get_team_record(team)
        stat_row(left, r, f"{label_text}  W/L {wins}/{losses}", roster, color)
        r += 1

    section_header(left, "Tournament Stats", r); r += 1

    total_teams   = len(TEAMS)
    total_matches = len(MATCH_DURATIONS)
    total_time    = sum(MATCH_DURATIONS)
    avg_time      = int(total_time / total_matches) if total_matches else 0

    stat_row(left, r, "Teams",         str(total_teams));  r += 1
    stat_row(left, r, "Matches played", str(total_matches)); r += 1
    stat_row(left, r, "Total time",    format_seconds(total_time)); r += 1
    stat_row(left, r, "Avg match time", format_seconds(avg_time)); r += 1

    # ---- RIGHT COLUMN: Match Breakdown ----
    right = tk.Frame(body, bg=THEME['bg_card'])
    right.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
    right.grid_columnconfigure(0, weight=1)
    right.grid_columnconfigure(1, weight=2)

    section_header(right, "Match Breakdown", 0)
    r = 1

    # Red vs Blue
    total_h   = len(MATCH_HISTORY)
    red_wins  = sum(1 for x in MATCH_HISTORY if x['color'] == 'red')
    blue_wins = sum(1 for x in MATCH_HISTORY if x['color'] == 'blue')
    red_pct   = int(red_wins  / total_h * 100) if total_h else 0
    blue_pct  = int(blue_wins / total_h * 100) if total_h else 0
    stat_row(right, r, "🔴 Red side wins",  f"{red_wins} ({red_pct}%)",  THEME['red_team']);  r += 1
    stat_row(right, r, "🔵 Blue side wins", f"{blue_wins} ({blue_pct}%)", THEME['blue_team']); r += 1

    # Longest / shortest
    if MATCH_DURATIONS and MATCH_HISTORY:
        paired = list(zip(MATCH_DURATIONS, MATCH_HISTORY))
        long_dur, long_rec  = max(paired, key=lambda x: x[0])
        shrt_dur, shrt_rec  = min(paired, key=lambda x: x[0])
        lw = " & ".join(TEAM_ROSTERS.get(long_rec['winner'], ['?','?']))
        sw = " & ".join(TEAM_ROSTERS.get(shrt_rec['winner'], ['?','?']))
        stat_row(right, r, "⏱️ Longest match",  f"{format_seconds(long_dur)}  ({lw})"); r += 1
        stat_row(right, r, "⚡ Shortest match", f"{format_seconds(shrt_dur)}  ({sw})"); r += 1

    # Most wins
    team_wins = {}
    for rec in MATCH_HISTORY:
        team_wins[rec['winner']] = team_wins.get(rec['winner'], 0) + 1
    if team_wins:
        top_team   = max(team_wins, key=team_wins.get)
        top_roster = " & ".join(TEAM_ROSTERS.get(top_team, ['?','?']))
        stat_row(right, r, "🏅 Most wins",
                 f"{top_roster} ({team_wins[top_team]})", THEME['accent_gold']); r += 1

    # High score in a single match
    scored_recs = [rec for rec in MATCH_HISTORY if 'red_score' in rec and 'blue_score' in rec]
    if scored_recs:
        high_rec   = max(scored_recs, key=lambda x: max(x['red_score'], x['blue_score']))
        high_score = max(high_rec['red_score'], high_rec['blue_score'])
        low_score  = min(high_rec['red_score'], high_rec['blue_score'])
        high_roster = " & ".join(TEAM_ROSTERS.get(high_rec['winner'], ['?','?']))
        stat_row(right, r, "🎳 High score",
                 f"{high_score}-{low_score}  ({high_rec['id']}, {high_roster})"); r += 1

        # --- Score-based stats (only when score data is available) ---
        section_header(right, "Scoring Stats", r); r += 1

        margins = [abs(rec['red_score'] - rec['blue_score']) for rec in scored_recs]
        win_scores  = [max(rec['red_score'], rec['blue_score']) for rec in scored_recs]
        loss_scores = [min(rec['red_score'], rec['blue_score']) for rec in scored_recs]

        # Average winning margin
        avg_margin = sum(margins) / len(margins)
        stat_row(right, r, "📐 Avg winning margin", f"{avg_margin:.1f} pts"); r += 1

        # Average final score  (winner avg - loser avg)
        avg_win  = sum(win_scores)  / len(win_scores)
        avg_loss = sum(loss_scores) / len(loss_scores)
        stat_row(right, r, "📊 Avg final score", f"{avg_win:.1f} – {avg_loss:.1f}"); r += 1

        # Closest match
        closest_rec = min(scored_recs, key=lambda x: abs(x['red_score'] - x['blue_score']))
        c_gap  = abs(closest_rec['red_score'] - closest_rec['blue_score'])
        c_win  = max(closest_rec['red_score'], closest_rec['blue_score'])
        c_loss = min(closest_rec['red_score'], closest_rec['blue_score'])
        c_roster = " & ".join(TEAM_ROSTERS.get(closest_rec['winner'], ['?','?']))
        stat_row(right, r, "😰 Closest match",
                 f"{c_win}-{c_loss} (Δ{c_gap})  {closest_rec['id']}  {c_roster}"); r += 1

        # Most lopsided win
        blowout_rec = max(scored_recs, key=lambda x: abs(x['red_score'] - x['blue_score']))
        b_gap  = abs(blowout_rec['red_score'] - blowout_rec['blue_score'])
        b_win  = max(blowout_rec['red_score'], blowout_rec['blue_score'])
        b_loss = min(blowout_rec['red_score'], blowout_rec['blue_score'])
        b_roster = " & ".join(TEAM_ROSTERS.get(blowout_rec['winner'], ['?','?']))
        stat_row(right, r, "💥 Most lopsided",
                 f"{b_win}-{b_loss} (Δ{b_gap})  {blowout_rec['id']}  {b_roster}"); r += 1

        # Team with most total points scored
        team_pts = {}
        for rec in scored_recs:
            r_score = rec['red_score']
            b_score = rec['blue_score']
            # Attribute red score to whichever team was on red, blue score to blue team
            red_team  = current_match_teams.get('red')   # fallback — may not reflect history
            # Use winner/loser + color to reconstruct which team scored what
            if rec['color'] == 'red':
                win_team, win_pts  = rec['winner'], r_score
                loss_team, loss_pts = rec['loser'],  b_score
            else:
                win_team, win_pts  = rec['winner'], b_score
                loss_team, loss_pts = rec['loser'],  r_score
            team_pts[win_team]  = team_pts.get(win_team,  0) + win_pts
            team_pts[loss_team] = team_pts.get(loss_team, 0) + loss_pts
        if team_pts:
            top_scorer        = max(team_pts, key=team_pts.get)
            top_scorer_roster = " & ".join(TEAM_ROSTERS.get(top_scorer, ['?','?']))
            stat_row(right, r, "🔥 Most pts scored",
                     f"{top_scorer_roster} ({team_pts[top_scorer]} pts)",
                     THEME['accent_gold']); r += 1

    # Most active
    team_matches = {}
    for rec in MATCH_HISTORY:
        for t in [rec['winner'], rec['loser']]:
            team_matches[t] = team_matches.get(t, 0) + 1
    if team_matches:
        busiest     = max(team_matches, key=team_matches.get)
        busy_roster = " & ".join(TEAM_ROSTERS.get(busiest, ['?','?']))
        stat_row(right, r, "🎯 Most active",
                 f"{busy_roster} ({team_matches[busiest]})"); r += 1

    # --- Deepest loser bracket run ---
    # Team with the most wins who came through the LB (lost at least once)
    lb_runs = {}
    for rec in MATCH_HISTORY:
        lb_runs[rec['winner']] = lb_runs.get(rec['winner'], 0) + 1
    # Only teams that suffered at least one loss
    lb_contenders = {t: w for t, w in lb_runs.items()
                     if sum(1 for x in MATCH_HISTORY if x['loser'] == t) > 0}
    if lb_contenders:
        grinder      = max(lb_contenders, key=lb_contenders.get)
        grind_roster = " & ".join(TEAM_ROSTERS.get(grinder, ['?','?']))
        grind_losses = sum(1 for x in MATCH_HISTORY if x['loser'] == grinder)
        stat_row(right, r, "💪 Best LB Run",
                 f"{grind_roster} ({lb_contenders[grinder]}W-{grind_losses}L)"); r += 1

    # --- Quickest exit ---
    # Team eliminated after playing the fewest total matches
    all_teams_in_history = set()
    for rec in MATCH_HISTORY:
        all_teams_in_history.add(rec['winner'])
        all_teams_in_history.add(rec['loser'])
    team_total_matches = {t: sum(1 for x in MATCH_HISTORY
                                 if x['winner'] == t or x['loser'] == t)
                          for t in all_teams_in_history}
    # Only teams that didn't win the tournament
    eliminated = {t: m for t, m in team_total_matches.items() if t != champion}
    if eliminated:
        quickest     = min(eliminated, key=eliminated.get)
        quick_roster = " & ".join(TEAM_ROSTERS.get(quickest, ['?','?']))
        stat_row(right, r, "🚪 Quickest Exit",
                 f"{quick_roster} ({eliminated[quickest]} match{'es' if eliminated[quickest] != 1 else ''})"); r += 1

    # --- GF bracket reset? ---
    gf_data = TOURNAMENT_STATE.get('GF', {})
    had_reset = isinstance(gf_data, dict) and gf_data.get('is_reset', False)
    stat_row(right, r, "🔄 Undefeated Teams",
             "None" if had_reset else champ_roster,
             THEME['fg_secondary'] if had_reset else THEME['accent_gold']); r += 1

    tk.Frame(P, bg=THEME['accent_gold'], height=2).pack(fill='x', pady=(10, 6))

    # Final controls
    for w in final_control_frame_ref.winfo_children():
        w.destroy()

    btn_row = tk.Frame(final_control_frame_ref, bg=THEME['bg_main'])
    btn_row.pack(pady=6)

    tk.Button(
        btn_row,
        text="📄 Export PDF",
        font=THEME['font_bold'],
        bg=THEME['btn_confirm'],
        fg='white',
        relief='flat',
        padx=18, pady=6,
        cursor='hand2',
        command=lambda: export_results_pdf(champion)
    ).pack(side='left', padx=8)

    final_control_frame_ref.pack(fill='x', pady=(0, 6))

def reset_game(update_teams=True):
    """Resets the game state (only updating teams now)."""
    log_message("Game UI reset", "DEBUG")
    # Cancel any win animation and restore card backgrounds
    _cancel_win_animation()
    # Reset match counters for both teams and send IR reset to scoreboard
    for color in ('red', 'blue'):
        counter_var = ui_references.get(f'{color}_counter_var')
        if counter_var:
            counter_var.set(0)
    ir_send('reset')
    if update_teams:
        load_match_data_and_teams()

def update_roster_seeding_display():
    """Updates the Team Roster & Seeding information box with a horizontal, player-focused view."""
    global roster_seeding_frame_ref, TEAMS, TEAM_ROSTERS

    if not roster_seeding_frame_ref or not TEAMS:
        return

    log_message("Roster display updated", "DEBUG")

    for widget in roster_seeding_frame_ref.winfo_children():
        widget.destroy()

    teams_inner_frame = tk.Frame(roster_seeding_frame_ref, bg=THEME['bg_card'])
    teams_inner_frame.pack(side='top', padx=5, pady=(0, 5))

    for team_name in TEAMS:
        roster = TEAM_ROSTERS.get(team_name, ["N/A", "N/A"])
        players_str = f"{roster[0]} / {roster[1]}"

        team_container = tk.Frame(teams_inner_frame, bg=THEME['bg_main'], bd=0)
        team_container.pack(side=tk.LEFT, padx=5, pady=2)

        tk.Label(team_container, text=f"{team_name}: {players_str}", font=('Consolas', 9),
                 bg=THEME['bg_main'], fg=THEME['fg_secondary']).pack(padx=5, pady=2)

def setup_main_gui(root):
    """Sets up the main windows and calls component initialization."""
    global main_root
    main_root = root
    root.title("Moose Lodge Shuffleboard")
    root.configure(bg=THEME['bg_main'])
    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root))

    # Attempt to connect Flipper Zero for IR scoreboard control (non-blocking)
    threading.Thread(target=flipper_connect, daemon=True).start()

    root.geometry("470x600") # Taller geometry for better breathing room

    g1_teams = TOURNAMENT_STATE.get('G1', {}).get('teams', ["Team Red", "Team Blue"])
    team_A = g1_teams[0] or "Team Red"
    team_B = g1_teams[1] or "Team Blue"

    log_message(f"Main GUI setup — {team_A} vs {team_B}")

    setup_scoreboard(root, team_A, team_B)

def show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes):
    """Displays the player draw, team rosters, and prize pool with improved styling."""

    summary_root = tk.Tk()
    summary_root.title("Tournament Draw & Prize Pool")
    summary_root.geometry("700x850")
    summary_root.configure(bg=THEME['bg_main'])
    summary_root.protocol("WM_DELETE_WINDOW", lambda: on_close(summary_root))

    log_message("Displaying draw summary and prize pool", "DEBUG")

    # ========================================================================
    # HEADER
    # ========================================================================

    header = tk.Frame(summary_root, bg=THEME['bg_card'], padx=25, pady=18)
    header.pack(fill='both', expand=False, padx=0, pady=0)

    tk.Label(header, text="Tournament Summary", font=THEME['font_title'],
             bg=THEME['bg_card'], fg=THEME['fg_primary']).pack(anchor='w')

    tk.Label(header, text="Draw results, team rosters & prize pool", font=('Selawik', 9),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(anchor='w', pady=(5, 0))

    # ========================================================================
    # MAIN SCROLLABLE CONTENT
    # ========================================================================

    # Create scrollable frame
    canvas_frame = tk.Frame(summary_root, bg=THEME['bg_main'])
    canvas_frame.pack(fill='both', expand=True, padx=0, pady=0)

    canvas = tk.Canvas(canvas_frame, bg=THEME['bg_main'], highlightthickness=0)
    scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=THEME['bg_main'], width=680)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=680)
    canvas.configure(yscrollcommand=scrollbar.set, yscrollincrement=5)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    # ========================================================================
    # 1. PLAYER DRAW RESULTS SECTION
    # ========================================================================

    draw_section = tk.Frame(scrollable_frame, bg=THEME['bg_card'], padx=15, pady=12, relief='raised', borderwidth=1)
    draw_section.pack(fill='both', expand=True, padx=0, pady=(0, 12))

    # Section header
    header_row = tk.Frame(draw_section, bg=THEME['bg_card'])
    header_row.pack(fill='x', pady=(0, 10))

    tk.Label(header_row, text="🎲 Player Draw Results", font=THEME['font_bold'],
             bg=THEME['bg_card'], fg='#2196F3').pack(anchor='w')

    tk.Label(header_row, text=f"{len(player_draws)} players drawn", font=('Selawik', 8),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(anchor='w', pady=(3, 0))

    # Draw content
    draw_content = ""
    for draw_num, player_name in player_draws:
        draw_content += f"  #{draw_num:2d}  {player_name}\n"

    draw_text = tk.Text(draw_section, height=8, bg=THEME['bg_main'], fg=THEME['fg_primary'],
                       font=('Consolas', 9), relief='flat', borderwidth=1)
    draw_text.pack(fill='both', expand=True)
    draw_text.insert('1.0', draw_content)
    draw_text.config(state='disabled')

    # ========================================================================
    # 2. TEAM ROSTERS SECTION
    # ========================================================================

    team_section = tk.Frame(scrollable_frame, bg=THEME['bg_card'], padx=15, pady=12, relief='raised', borderwidth=1)
    team_section.pack(fill='both', expand=True, padx=0, pady=(0, 12))

    # Section header
    header_row2 = tk.Frame(team_section, bg=THEME['bg_card'])
    header_row2.pack(fill='x', pady=(0, 10))

    tk.Label(header_row2, text="👥 Team Rosters & Seeding", font=THEME['font_bold'],
             bg=THEME['bg_card'], fg=THEME['accent_gold']).pack(anchor='w')

    tk.Label(header_row2, text=f"{num_teams} teams", font=('Selawik', 8),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(anchor='w', pady=(3, 0))

    # Team content
    team_content = ""
    for i, team_name in enumerate(TEAMS):
        roster = TEAM_ROSTERS.get(team_name, ["N/A", "N/A"])
        team_content += f"  T{i+1}  {roster[0]} & {roster[1]}\n"

    team_text = tk.Text(team_section, height=8, bg=THEME['bg_main'], fg=THEME['fg_primary'],
                       font=('Consolas', 9), relief='flat', borderwidth=1)
    team_text.pack(fill='both', expand=True)
    team_text.insert('1.0', team_content)
    team_text.config(state='disabled')

    # ========================================================================
    # 3. PRIZE POOL SECTION
    # ========================================================================

    prize_section = tk.Frame(scrollable_frame, bg=THEME['bg_card'], padx=15, pady=12, relief='raised', borderwidth=1)
    prize_section.pack(fill='both', expand=True, padx=0, pady=(0, 0))

    # Section header
    header_row3 = tk.Frame(prize_section, bg=THEME['bg_card'])
    header_row3.pack(fill='x', pady=(0, 10))

    tk.Label(header_row3, text="💰 Prize Pool", font=THEME['font_bold'],
             bg=THEME['bg_card'], fg=THEME['accent_gold']).pack(anchor='w')

    # Prize content with better formatting
    per_player_1st = int(prizes.get('1st', 0) / 2)
    per_player_2nd = int(prizes.get('2nd', 0) / 2)

    prize_content = f"  Total Pool: ${total_pool}\n\n"
    prize_content += f"  🥇 1st Place: ${prizes.get('1st', 0):>6} (${per_player_1st}/player)\n"
    prize_content += f"  🥈 2nd Place: ${prizes.get('2nd', 0):>6} (${per_player_2nd}/player)\n"

    if prizes.get('3rd') is not None and prizes.get('3rd') > 0:
        per_player_3rd = int(prizes.get('3rd', 0) / 2)
        prize_content += f"  🥉 3rd Place: ${prizes.get('3rd', 0):>6} (${per_player_3rd}/player)\n"
    else:
        prize_content += f"  🥉 3rd Place: Handshake!\n"

    prize_text = tk.Text(prize_section, height=5, bg=THEME['bg_main'], fg=THEME['fg_primary'],
                        font=('Consolas', 10), relief='flat', borderwidth=1)
    prize_text.pack(fill='both', expand=True)
    prize_text.insert('1.0', prize_content)
    prize_text.config(state='disabled')

    # ========================================================================
    # START BUTTON
    # ========================================================================

    button_frame = tk.Frame(summary_root, bg=THEME['bg_main'], pady=12)
    button_frame.pack(fill='x', padx=0)

    start_button = tk.Button(button_frame, text="✓ Start Tournament",
                            command=summary_root.destroy,
                            bg=THEME['btn_confirm'], fg='white',
                            font=THEME['font_header'], relief='flat',
                            padx=30, pady=8)
    start_button.pack(fill='x', padx=20)

    summary_root.mainloop()

def generate_dynamic_bracket(teams, config=None):
    """
    Loads the bracket structure from the config file, initializes TOURNAMENT_STATE,
    and seeds the starting matches with teams (T1, T2, etc.).
    """
    global TOURNAMENT_STATE
    TOURNAMENT_STATE.clear()

    num_teams = len(teams)
    log_message(f"Generating bracket for {num_teams} teams")

    if config is None:
        try:
            config, _ = load_bracket_config(num_teams, 'D')
        except Exception as e:
            messagebox.showerror("Configuration Error", str(e))
            return

    for match_id, match_config in config.items():
        TOURNAMENT_STATE[match_id] = {
            'config': {
                'W_next': match_config['W_next'],
                'L_next': match_config['L_next'],
                'M_round': match_config.get('M_round', 0),
                'L_round': match_config.get('L_round', 0)
            },
            'teams': [None, None],
            'winner': None,
            'winner_color': None,
            'is_reset': match_id == 'GGF',
            'is_winnerbracket': match_config.get('is_winnerbracket', 'unknown')
        }

    for match_id, match_data in config.items():
        if match_id.startswith('G'):
            for i in range(2):
                if 'teams' not in match_data: continue

                team_slot_id = match_data['teams'][i]

                if not team_slot_id:
                    continue

                match_t_id = re.match(r'T(\d+)', str(team_slot_id))

                if match_t_id:
                    t_num = int(match_t_id.group(1)) - 1
                    if t_num < len(teams):
                        TOURNAMENT_STATE[match_id]['teams'][i] = teams[t_num]
                        log_message(f"  -> Seeded {teams[t_num]} into {match_id} [slot {i}]", "DEBUG")
                    else:
                        TOURNAMENT_STATE[match_id]['teams'][i] = None

    initial_active_match = find_next_active_match()
    TOURNAMENT_STATE['active_match_id'] = initial_active_match
    log_message(f"Bracket ready — first match: {initial_active_match}")

# --- Logging File Management ---
def toggle_log_game(log_var):
    """Toggles file logging based on checkbox state and manages the log file."""
    global LOG_GAME_TO_FILE, LOG_FILE_HANDLE

    LOG_GAME_TO_FILE = log_var.get()

    if LOG_GAME_TO_FILE:
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(log_dir, f"shuffleboard_{timestamp}.log")

        try:
            LOG_FILE_HANDLE = open(filename, 'a', buffering=1)
            log_message(f"File logging enabled: {filename}")
        except Exception as e:
            LOG_GAME_TO_FILE = False
            LOG_FILE_HANDLE = None
            messagebox.showerror("Logging Error", f"Failed to open log file {filename}: {e}")
    else:
        if LOG_FILE_HANDLE:
            LOG_FILE_HANDLE.close()
            LOG_FILE_HANDLE = None
            print("[Log Manager] File logging stopped.")

def get_player_setup_dialog(parent):
    """
    Modern, borderless 'Card' UI for player setup with enhanced features.
    Features:
    - Real-time status banner with progress tracking
    - Team management controls (Add/Remove teams)
    - Column headers for clarity
    - Color-coded rows (green for paid, red for missing)
    - Status indicators (✓ Ready, ⏳ Waiting, ⚠️ Missing)
    - Smart button state management
    - Improved error handling with summary messages
    """
    log_message("Player setup dialog opened", "DEBUG")

    dialog = tk.Toplevel(parent)
    dialog.title("Tournament Setup")
    dialog.geometry("750x950")
    dialog.configure(bg=THEME['bg_main'])
    dialog.grab_set()

    result = None
    is_manual_draw = tk.BooleanVar(value=False)
    log_game_var = tk.BooleanVar(value=LOG_GAME_TO_FILE)
    all_paid_var = tk.BooleanVar(value=False)
    current_player_count = MIN_PLAYERS
    player_entries = []
    status_banner_refs = None
    header_frame_ref = None
    btn_add = None
    btn_remove = None
    lbl_count = None

    def _on_mousewheel(event):
        """Handle mousewheel scrolling"""
        content_height = canvas.bbox("all")[3] if canvas.bbox("all") else 0
        visible_height = canvas.winfo_height()
        if content_height <= visible_height:
            return

        if event.num == 4 or event.delta > 0:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            canvas.yview_scroll(1, "units")

    # ========================================================================
    # HEADER SECTION WITH ACTION BUTTONS
    # ========================================================================

    header = tk.Frame(dialog, bg=THEME['bg_card'], padx=25, pady=12)
    header.pack(fill='x', padx=20, pady=(15, 10))

    # Left side: Title
    left_header = tk.Frame(header, bg=THEME['bg_card'])
    left_header.pack(side='left', fill='both', expand=True)

    tk.Label(left_header, text="Configure Players", font=THEME['font_title'],
             bg=THEME['bg_card'], fg=THEME['fg_primary']).pack(anchor='w')

    tk.Label(left_header, text="Set up your tournament teams", font=('Selawik', 10),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(anchor='w', pady=(5, 0))

    # Right side: Action buttons (will be updated later)
    button_frame = tk.Frame(header, bg=THEME['bg_card'])
    button_frame.pack(side='right', padx=(20, 0))

    # These will be created after confirm function is defined
    continue_btn = None
    cancel_btn = None

    # ========================================================================
    # STATUS BANNER
    # ========================================================================

    def _create_status_banner():
        """Create status banner with real-time progress tracking"""
        nonlocal status_banner_refs

        status_frame = tk.Frame(dialog, bg=THEME['bg_card'], padx=15, pady=8,
                               relief='raised', borderwidth=1)
        status_frame.pack(fill='x', padx=20, pady=(8, 12))

        # Left side: count and info
        left_frame = tk.Frame(status_frame, bg=THEME['bg_card'])
        left_frame.pack(side='left', fill='both', expand=True)

        count_circle = tk.Label(left_frame, text="0", font=('Selawik', 14, 'bold'),
                               bg=THEME['accent_gold'], fg='black', width=3, height=1,
                               padx=5, pady=2, relief='raised', borderwidth=2)
        count_circle.pack(side='left', padx=(5, 15))

        status_text_label = tk.Label(left_frame, text="Total Players: 0 | Paid: 0/0",
                                    font=THEME['font_header'], bg=THEME['bg_card'],
                                    fg=THEME['fg_primary'])
        status_text_label.pack(side='left', fill='x', expand=True)

        # Right side: progress bar
        right_frame = tk.Frame(status_frame, bg=THEME['bg_card'])
        right_frame.pack(side='right', padx=10)

        tk.Label(right_frame, text="Progress", font=THEME['font_main'],
                bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(pady=(0, 3))

        progress_bar = tk.Canvas(right_frame, width=150, height=8, bg=THEME['bg_main'],
                                highlightthickness=1, borderwidth=0,
                                highlightbackground=THEME['fg_secondary'])
        progress_bar.pack()

        def update_status():
            """Update banner with current state"""
            if not player_entries:
                return

            total = len(player_entries)
            paid = sum(1 for _, paid_var, _, _ in player_entries if paid_var.get())

            count_circle.config(text=str(total))

            if paid < total:
                status_text_label.config(
                    text=f"Total Players: {total} | Paid: {paid}/{total}  ⚠️ {total - paid} awaiting"
                )
            else:
                status_text_label.config(
                    text=f"Total Players: {total} | Paid: {paid}/{total}  ✓ All set!"
                )

            progress_bar.delete('all')
            if total > 0:
                progress_width = (paid / total) * 150
                progress_bar.create_rectangle(0, 0, progress_width, 8,
                                            fill=THEME['accent_gold'],
                                            outline=THEME['accent_gold'])

        status_banner_refs = {'update': update_status, 'frame': status_frame}

    # ========================================================================
    # COLUMN HEADERS
    # ========================================================================

    def _create_column_headers():
        """Create column headers above player list"""
        nonlocal header_frame_ref

        header_frame = tk.Frame(input_container, bg=THEME['bg_canvas'], padx=15, pady=4)
        header_frame.pack(fill='x', padx=15, pady=(0, 4))

        tk.Label(header_frame, text="P#", width=4, font=THEME['font_bold'],
                bg=THEME['bg_canvas'], fg=THEME['fg_secondary']).pack(side='left', padx=5)

        if is_manual_draw.get():
            tk.Label(header_frame, text="Draw", width=5, font=THEME['font_bold'],
                    bg=THEME['bg_canvas'], fg=THEME['fg_secondary']).pack(side='left', padx=5)

        tk.Label(header_frame, text="Player Name", font=THEME['font_bold'],
                bg=THEME['bg_canvas'], fg=THEME['fg_secondary']).pack(side='left',
                                                                       expand=True,
                                                                       fill='x', padx=5)

        tk.Label(header_frame, text="Paid", width=8, font=THEME['font_bold'],
                bg=THEME['bg_canvas'], fg=THEME['fg_secondary']).pack(side='right', padx=5)

        tk.Label(header_frame, text="Status", width=10, font=THEME['font_bold'],
                bg=THEME['bg_canvas'], fg=THEME['fg_secondary']).pack(side='right', padx=5)

        header_frame_ref = header_frame

    # ========================================================================
    # VISUALS AND UPDATES
    # ========================================================================

    def update_visuals(event=None):
        """Update visual state of all player entries and button state"""
        # Skip if we're in the middle of rebuilding rows
        if not player_entries:
            return

        from collections import Counter
        current_names = [w[0].get().strip() for w in player_entries]
        counts = Counter(current_names)

        # Get all draw numbers if manual draw is enabled
        draw_numbers = []
        if is_manual_draw.get():
            for widgets in player_entries:
                draw_entry = widgets[2]
                if draw_entry:
                    try:
                        draw_num = int(draw_entry.get().strip())
                        # Only count valid range numbers
                        if 1 <= draw_num <= current_player_count:
                            draw_numbers.append(draw_num)
                    except (ValueError, AttributeError):
                        pass

        draw_counts = Counter(draw_numbers) if draw_numbers else Counter()

        for widgets in player_entries:
            name_entry, paid_var = widgets[0], widgets[1]
            val = name_entry.get().strip()

            if val and counts[val] > 1:
                name_entry.config(bg='#711717', fg='white')
            elif not paid_var.get():
                name_entry.config(bg='#CED119', fg='black')
            else:
                name_entry.config(bg=THEME['bg_main'], fg=THEME['fg_primary'])

        # Update status banner
        if status_banner_refs:
            status_banner_refs['update']()

        # Update continue button state: only enable if all conditions met
        if continue_btn:
            can_continue = True

            if not player_entries:
                can_continue = False
            else:
                for i, widgets in enumerate(player_entries):
                    name_entry, paid_var, draw_entry, status_label = widgets
                    name = name_entry.get().strip()
                    is_paid = paid_var.get()

                    # Check 1: Must have a name
                    if not name:
                        can_continue = False
                        break

                    # Check 2: No default names (Player 1, Player 2, etc)
                    if name.lower().startswith('player '):
                        can_continue = False
                        break

                    # Check 3: Must be marked as paid
                    if not is_paid:
                        can_continue = False
                        break

                    # Check 4: If manual draw enabled, must have valid, unique, and in-range draw number
                    if is_manual_draw.get() and draw_entry:
                        try:
                            draw_num = int(draw_entry.get().strip())

                            # Check if draw number is in valid range
                            if draw_num < 1 or draw_num > current_player_count:
                                can_continue = False
                                break

                            # Check if this draw number is unique
                            if draw_counts[draw_num] > 1:
                                can_continue = False
                                break
                        except (ValueError, AttributeError):
                            can_continue = False
                            break

            try:
                if can_continue:
                    continue_btn.config(state='normal', fg='white')
                else:
                    continue_btn.config(state='disabled', fg='#666666')
            except:
                pass  # Button not created yet, skip

    def toggle_all_paid():
        """Toggle all players as paid/unpaid with visual feedback"""
        state = all_paid_var.get()

        # Set the paid variable for each player
        for widgets in player_entries:
            widgets[1].set(state)

        # Update visuals after all are set
        update_visuals()
        _update_manual_draw_state()

    # ========================================================================
    # ROW CONSTRUCTION (IMPROVED)
    # ========================================================================

    def create_player_row(parent_frame, idx, initial_data=None):
        """Create enhanced player row with status indicators"""
        # Determine initial row background
        if initial_data:
            name = initial_data.get('name', '').strip()
            paid = initial_data.get('paid', False)

            if not name:
                row_bg = '#3d2424'
            elif paid:
                row_bg = '#243d2d'
            else:
                row_bg = THEME['bg_card']
        else:
            row_bg = THEME['bg_card']

        row_frame = tk.Frame(parent_frame, bg=row_bg, pady=7, padx=12)
        row_frame.pack(fill='x', pady=2, padx=15)

        original_bg = row_bg

        # Hover effects
        def on_hover_enter(event):
            current_bg = row_frame.cget('bg')
            hover_bg = '#4a5568' if current_bg == THEME['bg_card'] else current_bg
            row_frame.config(bg=hover_bg)

        def on_hover_leave(event):
            row_frame.config(bg=original_bg)

        row_frame.bind('<Enter>', on_hover_enter)
        row_frame.bind('<Leave>', on_hover_leave)

        # P# Label
        tk.Label(row_frame, text=f"P{idx+1:02}", width=4, font=THEME['font_bold'],
                 bg=row_bg, fg=THEME['fg_secondary']).pack(side='left', padx=5)

        # Draw Entry (conditional)
        draw_entry = None
        if is_manual_draw.get():
            draw_entry = tk.Entry(row_frame, width=5, justify='center',
                                 font=THEME['font_main'], bg=THEME['bg_main'],
                                 fg=THEME['fg_primary'], insertbackground='white',
                                 relief='flat', borderwidth=1)
            draw_entry.pack(side='left', padx=5)
            val = initial_data.get('draw') if initial_data else str(idx + 1)
            draw_entry.insert(0, val)
            # Bind to update status when draw number changes
            draw_entry.bind('<KeyRelease>', lambda e: update_row_status())

        # Name Entry
        name_entry = tk.Entry(row_frame, bg=THEME['bg_main'], fg=THEME['fg_primary'],
                             insertbackground='white', relief='flat',
                             font=THEME['font_main'], borderwidth=1)
        name_entry.pack(side='left', fill='x', expand=True, padx=5, ipady=8)

        name_val = initial_data.get('name') if initial_data else f"Player {idx+1}"
        name_entry.insert(0, name_val)

        # Paid Checkbox
        paid_var = tk.BooleanVar(value=initial_data.get('paid', False) if initial_data else False)

        chk = tk.Checkbutton(row_frame, text="✓ Paid", variable=paid_var,
                            bg=row_bg, fg=THEME['fg_secondary'],
                            selectcolor=row_bg,
                            activebackground=row_bg,
                            activeforeground=THEME['accent_gold'],
                            font=THEME['font_main'],
                            borderwidth=0,
                            highlightthickness=0,
                            padx=5)
        chk.pack(side='right', padx=5)

        # Status Indicator
        status_label = tk.Label(row_frame, text="", font=THEME['font_main'],
                               bg=row_bg, fg=THEME['accent_gold'], width=12)
        status_label.pack(side='right', padx=5)

        # Update Row Status Function
        def update_row_status():
            """Update row appearance based on name and payment status"""
            nonlocal original_bg, row_bg

            name = name_entry.get().strip()
            is_paid = paid_var.get()
            draw_num = None
            draw_valid = True
            draw_duplicate = False
            draw_out_of_range = False

            # Check draw number if manual draw is enabled
            if is_manual_draw.get() and draw_entry:
                try:
                    draw_num = int(draw_entry.get().strip())
                    # Check if draw number is in valid range (1 to current_player_count)
                    if draw_num < 1 or draw_num > current_player_count:
                        draw_out_of_range = True
                    else:
                        # Check if this draw number appears in other rows
                        draw_count = 0
                        for other_widgets in player_entries:
                            other_draw_entry = other_widgets[2]
                            if other_draw_entry:
                                try:
                                    other_draw_num = int(other_draw_entry.get().strip())
                                    if other_draw_num == draw_num:
                                        draw_count += 1
                                except (ValueError, AttributeError):
                                    pass
                        if draw_count > 1:
                            draw_duplicate = True
                except (ValueError, AttributeError):
                    draw_valid = False

            if not name:
                new_bg = '#3d2424'
                status_text = '⚠️ Missing'
                status_color = '#ff6b6b'
            elif not is_paid:
                new_bg = THEME['bg_card']
                status_text = '⏳ Waiting'
                status_color = THEME['accent_gold']
            elif is_manual_draw.get() and not draw_valid:
                # Draw number required but invalid
                new_bg = THEME['bg_card']
                status_text = '⚠️ No Draw#'
                status_color = '#ff6b6b'
            elif is_manual_draw.get() and draw_out_of_range:
                # Draw number is out of range
                new_bg = THEME['bg_card']
                status_text = f'⚠️ 1-{current_player_count}'
                status_color = '#ff6b6b'
            elif is_manual_draw.get() and draw_duplicate:
                # Draw number is a duplicate
                new_bg = THEME['bg_card']
                status_text = '⚠️ Dup Draw#'
                status_color = '#ff6b6b'
            elif is_paid:
                new_bg = '#243d2d'
                status_text = '✓ Ready'
                status_color = '#51cf66'
            else:
                new_bg = THEME['bg_card']
                status_text = '⏳ Waiting'
                status_color = THEME['accent_gold']

            row_bg = new_bg
            original_bg = new_bg
            row_frame.config(bg=new_bg)
            chk.config(bg=new_bg, selectcolor=new_bg, activebackground=new_bg)
            status_label.config(bg=new_bg, text=status_text, fg=status_color)

            update_visuals()
            _update_manual_draw_state()

        # Bind updates
        name_entry.bind('<KeyRelease>', lambda e: update_row_status())
        chk.config(command=update_row_status)

        # Bind scrolling
        for widget in [row_frame, name_entry, chk]:
            if sys.platform == 'linux':
                widget.bind("<Button-4>", _on_mousewheel)
                widget.bind("<Button-5>", _on_mousewheel)
            else:
                widget.bind("<MouseWheel>", _on_mousewheel)

        # Initial status update
        update_row_status()

        return (name_entry, paid_var, draw_entry, status_label)

    def render_inputs():
        """Render/refresh all player input rows"""
        saved_data = []
        for w in player_entries:
            saved_data.append({
                'name': w[0].get(),
                'paid': w[1].get(),
                'draw': w[2].get() if w[2] else ""
            })

        # Clear only the rows, not the headers
        for widget in input_container.winfo_children():
            # Skip the header frame (it's the first child)
            if widget == header_frame_ref:
                continue
            widget.destroy()
        player_entries.clear()

        for i in range(current_player_count):
            existing = saved_data[i] if i < len(saved_data) else None

            # For new rows, inherit the all_paid_var state
            if existing is None and all_paid_var.get():
                existing = {'name': '', 'paid': True, 'draw': ''}

            full_widgets = create_player_row(input_container, i, existing)
            player_entries.append(full_widgets)  # Keep all 4 values (name, paid, draw, status_label)

        update_visuals()  # Call once after all rows are created

    # ========================================================================
    # CREATE STATUS BANNER (call it now)
    # ========================================================================

    _create_status_banner()

    # ========================================================================
    # OPTIONS SECTION
    # ========================================================================

    # ========================================================================
    # MERGED: TOURNAMENT SETTINGS + TEAM MANAGEMENT
    # ========================================================================

    combined_card = tk.Frame(dialog, bg=THEME['bg_card'], padx=15, pady=10,
                             relief='raised', borderwidth=1)
    combined_card.pack(fill='x', padx=20, pady=(10, 12))

    # Left column: Tournament Settings
    settings_col = tk.Frame(combined_card, bg=THEME['bg_card'])
    settings_col.pack(side='left', fill='y', padx=(0, 20))

    tk.Label(settings_col, text="Tournament Settings", font=THEME['font_bold'],
             bg=THEME['bg_card'], fg=THEME['fg_primary']).pack(anchor='w', pady=(0, 6))

    def toggle_manual_draw():
        """Toggle manual draw and recreate headers with/without draw column"""
        if header_frame_ref:
            header_frame_ref.destroy()
        _create_column_headers()
        render_inputs()

    # Manual Draw
    manual_frame = tk.Frame(settings_col, bg=THEME['bg_card'])
    manual_frame.pack(anchor='w', pady=2, fill='x')
    manual_chk = tk.Checkbutton(manual_frame, text="🎲 Manual Draw",
                                variable=is_manual_draw,
                                command=toggle_manual_draw,
                                bg=THEME['bg_card'], fg=THEME['fg_secondary'],
                                selectcolor=THEME['bg_main'],
                                borderwidth=0, highlightthickness=0,
                                font=THEME['font_main'])
    manual_chk.pack(side='left')
    tk.Label(manual_frame, text="(specify draw numbers)", font=('Selawik', 8),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(side='left', padx=8)
    manual_draw_hint = tk.Label(manual_frame, text="", font=('Selawik', 7),
             bg=THEME['bg_card'], fg='#ff6b6b')
    manual_draw_hint.pack(side='left', padx=4)

    def _update_manual_draw_state():
        """Enable manual draw only when all players are paid and have non-default names."""
        if not player_entries:
            manual_chk.config(state='disabled')
            manual_draw_hint.config(text="(add players first)")
            return
        default_pattern = re.compile(r'^Player\s*\d+$', re.IGNORECASE)
        all_paid = all(w[1].get() for w in player_entries)
        all_named = all(
            w[0].get().strip() and not default_pattern.match(w[0].get().strip())
            for w in player_entries
        )
        if all_paid and all_named:
            manual_chk.config(state='normal')
            manual_draw_hint.config(text="")
        else:
            manual_chk.config(state='disabled')
            if not all_paid and not all_named:
                manual_draw_hint.config(text="(needs names & payment)")
            elif not all_paid:
                manual_draw_hint.config(text="(needs all paid)")
            else:
                manual_draw_hint.config(text="(needs real names)")
            # Uncheck if it was on and we're now disabling
            if is_manual_draw.get():
                is_manual_draw.set(False)
                toggle_manual_draw()

    # Log Game
    log_frame = tk.Frame(settings_col, bg=THEME['bg_card'])
    log_frame.pack(anchor='w', pady=2, fill='x')
    log_chk = tk.Checkbutton(log_frame, text="📝 Log Game to File",
                             variable=log_game_var,
                             command=lambda: toggle_log_game(log_game_var),
                             bg=THEME['bg_card'], fg=THEME['fg_secondary'],
                             selectcolor=THEME['bg_main'],
                             borderwidth=0, highlightthickness=0,
                             font=THEME['font_main'])
    log_chk.pack(side='left')
    tk.Label(log_frame, text="(save console logs)", font=('Selawik', 8),
             bg=THEME['bg_card'], fg=THEME['fg_secondary']).pack(side='left', padx=8)

    # All Paid
    all_paid_frame = tk.Frame(settings_col, bg=THEME['bg_card'])
    all_paid_frame.pack(anchor='w', pady=2, fill='x')
    all_paid_chk = tk.Checkbutton(all_paid_frame, text="✅ Mark All as Paid",
                                  variable=all_paid_var,
                                  command=toggle_all_paid,
                                  bg=THEME['bg_card'], fg=THEME['fg_secondary'],
                                  selectcolor=THEME['bg_main'],
                                  borderwidth=0, highlightthickness=0,
                                  font=THEME['font_main'])
    all_paid_chk.pack(side='left')
    all_paid_status = tk.Label(all_paid_frame, text="", font=('Selawik', 8),
                               bg=THEME['bg_card'], fg=THEME['accent_gold'])
    all_paid_status.pack(side='left', padx=8)

    # Vertical divider
    tk.Frame(combined_card, bg=THEME['bg_main'], width=2).pack(side='left', fill='y', padx=(0, 20))

    # Right column: Team Management
    team_col = tk.Frame(combined_card, bg=THEME['bg_card'])
    team_col.pack(side='left', fill='y')

    tk.Label(team_col, text="Team Management", font=THEME['font_bold'],
             bg=THEME['bg_card'], fg=THEME['fg_primary']).pack(anchor='w', pady=(0, 4))

    lbl_count = tk.Label(team_col, text=f"Total Players: {current_player_count}",
                         font=THEME['font_header'], bg=THEME['bg_card'],
                         fg=THEME['fg_primary'])
    lbl_count.pack(anchor='w', pady=(0, 6))

    btn_row = tk.Frame(team_col, bg=THEME['bg_card'])
    btn_row.pack(anchor='w', pady=2)

    def _update_button_states():
        """Enable/disable buttons based on player count"""
        if current_player_count <= MIN_PLAYERS:
            btn_remove.config(state='disabled', fg='#666666')
        else:
            btn_remove.config(state='normal', fg='white')

        if current_player_count >= MAX_PLAYERS:
            btn_add.config(state='disabled', fg='#666666')
            btn_add.config(text="+ Add Team (max)")
        else:
            remaining = MAX_PLAYERS - current_player_count
            btn_add.config(state='normal', fg='white')
            btn_add.config(text=f"+ Add Team ({remaining} slots)")

    def change_count(n):
        nonlocal current_player_count
        if MIN_PLAYERS <= current_player_count + n <= MAX_PLAYERS:
            current_player_count += n
            lbl_count.config(text=f"Total Players: {current_player_count}")
            _update_button_states()
            render_inputs()

    btn_add = tk.Button(btn_row, text=f"+ Add Team ({MAX_PLAYERS - current_player_count} slots)",
                        command=lambda: change_count(2),
                        bg=THEME['btn_default'], fg='white', relief='flat',
                        padx=12, pady=4, font=THEME['font_main'])
    btn_add.pack(side='left', padx=(0, 6))

    btn_remove = tk.Button(btn_row, text="- Remove Team", command=lambda: change_count(-2),
                           bg=THEME['btn_default'], fg='white', relief='flat',
                           padx=12, pady=4, font=THEME['font_main'])
    btn_remove.pack(side='left')

    tk.Label(team_col, text=f"({MIN_PLAYERS}-{MAX_PLAYERS} players total)",
             font=('Selawik', 8), bg=THEME['bg_card'],
             fg=THEME['fg_secondary']).pack(anchor='w', pady=(4, 0))

    # ========================================================================
    # SCROLLABLE PLAYER LIST
    # ========================================================================

    list_card = tk.Frame(dialog, bg=THEME['bg_card'], padx=6, pady=6)
    list_card.pack(fill='both', expand=True, padx=20, pady=(4, 15))

    canvas = tk.Canvas(list_card, bg=THEME['bg_card'], highlightthickness=0, height=220)
    canvas.configure(yscrollincrement=5)
    scrollbar = tk.Scrollbar(list_card, orient="vertical", command=canvas.yview)
    input_container = tk.Frame(canvas, bg=THEME['bg_card'])

    canvas.create_window((0, 0), window=input_container, anchor="nw", width=600)
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    input_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    for widget in [dialog, canvas, input_container]:
        if sys.platform == 'linux':
            widget.bind("<Button-4>", _on_mousewheel)
            widget.bind("<Button-5>", _on_mousewheel)
        else:
            widget.bind("<MouseWheel>", _on_mousewheel)

    # ========================================================================
    # ACTION BUTTONS (at the bottom)
    # ========================================================================

    def confirm():
        """Validate and confirm setup"""
        nonlocal result

        errors = []
        data = []

        for i, widgets in enumerate(player_entries):
            name_entry, paid_var, draw_entry, status_label = widgets
            name = name_entry.get().strip()
            is_paid = paid_var.get()

            if not name:
                errors.append(f"Player {i+1}: Missing name")
            else:
                if not is_paid:
                    errors.append(f"Player {i+1} ({name}): Payment not confirmed")

            draw = None
            if is_manual_draw.get() and draw_entry:
                try:
                    draw = int(draw_entry.get().strip())
                except ValueError:
                    errors.append(f"Player {i+1}: Invalid draw number")

            data.append((draw, name, is_paid))

        if errors:
            error_msg = "Please fix the following issues:\n\n"
            for err in errors:
                error_msg += f"• {err}\n"
            messagebox.showerror("Validation Error", error_msg)
            return

        result = (is_manual_draw.get(), data)
        dialog.destroy()

    # Create buttons in header
    continue_btn = tk.Button(button_frame, text="✓ Continue",
                            font=THEME['font_main'], bg=THEME['btn_confirm'], fg='white',
                            relief='flat', padx=20, pady=5, command=confirm, state='disabled')
    continue_btn.pack(side='left', padx=6)

    tk.Button(button_frame, text="Cancel",
             font=THEME['font_main'], bg=THEME['btn_cancel'], fg='white',
             relief='flat', padx=15, pady=5, command=dialog.destroy).pack(side='left', padx=6)

    # ========================================================================
    # INITIAL RENDER AND STATE SETUP
    # ========================================================================

    # Create headers first (before render_inputs which packs rows)
    _create_column_headers()

    render_inputs()
    _update_button_states()
    _update_manual_draw_state()
    dialog.wait_window()
    return result

def reset_global_state():
    """Clears all tournament globals in one place before starting a new game or replay."""
    global TEAMS, TEAM_ROSTERS, TOURNAMENT_STATE, TOURNAMENT_RANKINGS
    global MATCH_HISTORY, MATCH_DURATIONS, REPLAY_FILEPATH
    global last_assigned_match_id, TOURNAMENT_START_TIME

    TEAMS.clear()
    TEAM_ROSTERS.clear()
    TOURNAMENT_STATE.clear()
    TOURNAMENT_RANKINGS.clear()
    MATCH_HISTORY.clear()
    MATCH_DURATIONS.clear()
    REPLAY_FILEPATH = None
    last_assigned_match_id = None
    TOURNAMENT_START_TIME = None


def start_tournament():
    """
    Prompts for players using the unified dialog, sets up teams,
    generates the bracket, and launches the GUI.
    """
    global REPLAY_FILEPATH, TEAMS, TEAM_ROSTERS

    reset_global_state()
    log_message("Tournament initialization started")

    dialog_root = tk.Tk()
    dialog_root.withdraw()

    # --- 1. Combined Player Setup Step ---
    player_input_result = get_player_setup_dialog(dialog_root)

    if player_input_result is None:
        dialog_root.destroy()
        log_message("Tournament setup cancelled by user", "WARN")
        return

    is_manual_draw, player_data_list = player_input_result
    num_players = len(player_data_list)

    dialog_root.destroy()

    # All players are paid now, enforced by the dialog
    log_message(f"Player setup complete — {num_players} players, manual draw: {is_manual_draw}")

    # --- 2. Process Draw and Team Setup ---
    TEAMS.clear()
    TEAM_ROSTERS.clear()

    if is_manual_draw:
        # Sort by draw number (item 0)
        player_draws = sorted([(d, n) for d, n, p in player_data_list], key=lambda x: x[0])
    else:
        # Extract names only
        player_names = [n for d, n, p in player_data_list]
        draw_numbers = list(range(1, num_players + 1))
        random.shuffle(draw_numbers)

        player_draws = []
        for player_name in player_names:
            draw_num = draw_numbers.pop()
            player_draws.append((draw_num, player_name))

        player_draws.sort(key=lambda x: x[0])
        log_message(f"Auto-draw complete — {num_players} players assigned", "DEBUG")

    num_teams = num_players // 2
    for i in range(num_teams):
        team_name = f'Team {i+1}'
        player1 = player_draws[i*2][1]
        player2 = player_draws[i*2 + 1][1]

        TEAMS.append(team_name)
        TEAM_ROSTERS[team_name] = [player1, player2]
        log_message(f"  -> {team_name}: {player1} & {player2} (draws #{player_draws[i*2][0]}, #{player_draws[i*2+1][0]})", "DEBUG")

    # --- 3. Load Bracket Config and Prizes ---
    try:
        config, prizes_from_file = load_bracket_config(num_teams, 'D')
    except Exception as e:
        messagebox.showerror("Configuration Error", str(e))
        return

    prizes = prizes_from_file
    prizes['1st'] = prizes.get('1st', 0)
    prizes['2nd'] = prizes.get('2nd', 0)
    prizes['3rd'] = prizes.get('3rd', 0)

    total_pool = prizes['1st'] + prizes['2nd'] + prizes['3rd']
    log_message(f"Prize pool loaded — 1st: ${prizes.get('1st',0)}, 2nd: ${prizes.get('2nd',0)}, 3rd: ${prizes.get('3rd',0)} (total: ${total_pool})")

    # --- 4. Show Draw Summary ---
    show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes)

    # --- 5. Generate Bracket ---
    generate_dynamic_bracket(TEAMS, config)

    if not TOURNAMENT_STATE:
        log_message("TOURNAMENT_STATE empty after bracket generation — aborting", "ERROR")
        return

    # --- 6. Create Replay File ---
    os.makedirs("replays", exist_ok=True)
    REPLAY_FILEPATH = f"replays/game_{int(time.time())}.json"
    log_message(f"Replay file created: {REPLAY_FILEPATH}")
    append_snapshot_to_file(REPLAY_FILEPATH)

    # --- 7. Launch Main Game GUI ---
    root = tk.Tk()
    try:
        setup_main_gui(root)
        root.mainloop()
    except KeyboardInterrupt:
        on_close(root)

def confirm_match_resolution(winner, loser, winning_color, match_id):
    """Processes the confirmed match result and updates the tournament state."""
    global match_res_frame, current_match_res_buttons, TOURNAMENT_STATE

    log_message(f"Match {match_id} result confirmed — processing")

    # Capture final scores before reset_game() clears the counters
    red_score  = ui_references['red_counter_var'].get()  if ui_references.get('red_counter_var')  else 0
    blue_score = ui_references['blue_counter_var'].get() if ui_references.get('blue_counter_var') else 0

    duration = finalize_match_duration(match_id)

    handle_match_resolution(winner, loser, winning_color, match_id)

    # Attach scores to the record that handle_match_resolution just appended
    if MATCH_HISTORY and MATCH_HISTORY[-1].get('id') == match_id:
        MATCH_HISTORY[-1]['red_score']  = red_score
        MATCH_HISTORY[-1]['blue_score'] = blue_score

    match_res_frame.pack_forget()
    current_match_res_buttons = []

    append_snapshot_to_file(REPLAY_FILEPATH)

    # If the tournament just ended, append the final stats record once
    if TOURNAMENT_STATE.get('active_match_id') == 'TOURNAMENT_OVER' and REPLAY_FILEPATH:
        champion = TOURNAMENT_RANKINGS.get('1ST')
        if champion:
            append_final_stats_to_file(REPLAY_FILEPATH, champion)

    reset_game()

if __name__ == '__main__':

    log_message("--- Shuffleboard Tournament Manager starting ---")

    if not os.path.exists('data'):
        os.makedirs('data')
        log_message("Created 'data' directory", "DEBUG")

    show_title_screen()

    log_message("--- Shuffleboard Tournament Manager exited ---")
