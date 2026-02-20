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

# --- Version ---
SHUF_VERSION = "1.47"

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
    'font_main': ('Segoe UI', 10),
    'font_bold': ('Segoe UI', 10, 'bold'),
    'font_header': ('Segoe UI', 14, 'bold'),
    'font_title': ('Segoe UI', 18, 'bold'),
}

# --- Console Logging Function ---
def log_message(message):
    """Prints a timestamped message to the console and file (if enabled) for tracking."""
    global LOG_GAME_TO_FILE, LOG_FILE_HANDLE 
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    
    print(log_line)

    if LOG_GAME_TO_FILE and LOG_FILE_HANDLE:
        LOG_FILE_HANDLE.write(log_line + "\n")
        LOG_FILE_HANDLE.flush() 

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
    'vs_label': None
}

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

    log_message("Initializing modernized scoreboard UI.")

    # --- Styling for Notebook (Dark Theme) ---
    style = ttk.Style()
    style.theme_use('default')
    style.configure("TNotebook", background=THEME['bg_main'], borderwidth=0)
    style.configure("TNotebook.Tab", background=THEME['bg_card'], foreground=THEME['fg_secondary'], padding=[10, 5], font=('Segoe UI', 10))
    style.map("TNotebook.Tab", background=[("selected", THEME['bg_canvas'])], foreground=[("selected", THEME['fg_primary'])])
    style.configure("TFrame", background=THEME['bg_main'])

    # --- Header Status ---
    status_frame = tk.Frame(root, bg=THEME['bg_card'], padx=10, pady=5)
    status_frame.pack(fill='x', side='top')
    
    status_label = tk.Label(status_frame, text="Tournament Initialized.", font=('Segoe UI', 12, 'bold'),
                            bg=THEME['bg_card'], fg=THEME['accent_gold'])
    status_label.pack(side='left')

    # --- Main Notebook (Tabs) ---
    notebook = ttk.Notebook(root)
    notebook.pack(fill='both', expand=True, padx=5, pady=5)
    ui_references['notebook'] = notebook

    # Tab 1: The Arena (Active Match)
    tab_match = tk.Frame(notebook, bg=THEME['bg_main'])
    notebook.add(tab_match, text='   ⚔️ ARENA   ')
    
    # Tab 3: The Roster (List)
    tab_roster = tk.Frame(notebook, bg=THEME['bg_main'])
    notebook.add(tab_roster, text='   👥 ROSTERS   ')

    # ==========================
    # TAB 1: ARENA LAYOUT
    # ==========================
    
    # 1. Routing Info (Where does winner go?)
    info_frame = tk.Frame(tab_match, bg=THEME['bg_main'], pady=5)
    info_frame.pack(fill='x')
    game_routing_label = tk.Label(info_frame, text="Winner -> TBD | Loser -> TBD", 
                                  font=('Segoe UI', 9), fg=THEME['fg_secondary'], bg=THEME['bg_main'])
    game_routing_label.pack()
    ui_references['info_lbl'] = game_routing_label

    # 2. The Interaction Area (Cards)
    match_input_frame = tk.Frame(tab_match, bg=THEME['bg_main'])
    match_input_frame.pack(fill='both', expand=True, padx=5, pady=5)
    ui_references['match_tab_frame'] = match_input_frame # Reference for hiding later

    # -- Red Card --
    red_card = tk.Frame(match_input_frame, bg=THEME['bg_card'], bd=2, relief='flat')
    red_card.place(relx=0.0, rely=0.0, relwidth=0.48, relheight=0.85)
    ui_references['red_card_frame'] = red_card

    # Red Content
    tk.Label(red_card, text="RED TEAM", font=('Segoe UI', 8, 'bold'), fg=THEME['red_team'], bg=THEME['bg_card']).pack(pady=(10,0))
    
    ui_references['red_name_lbl'] = tk.Label(red_card, text=team_red_placeholder, font=('Segoe UI', 14, 'bold'), 
                                             fg=THEME['fg_primary'], bg=THEME['bg_card'], wraplength=180)
    ui_references['red_name_lbl'].pack(pady=(5,0))
    
    ui_references['red_roster_lbl'] = tk.Label(red_card, text="P1 / P2", font=('Segoe UI', 10), 
                                               fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['red_roster_lbl'].pack(pady=(2,10))
    
    ui_references['red_stats_lbl'] = tk.Label(red_card, text="0-0", font=('Consolas', 9), fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['red_stats_lbl'].pack(side='bottom', pady=5)
    
    btn_red = tk.Button(red_card, text="🏆 RED WINS", command=lambda: declare_winner('red'),
                        bg=THEME['red_team'], fg='white', font=('Segoe UI', 11, 'bold'),
                        relief='flat', activebackground='#C62828', cursor='hand2')
    btn_red.pack(side='bottom', fill='x', padx=10, pady=10)

    # -- VS Center --
    vs_frame = tk.Frame(match_input_frame, bg=THEME['bg_main'])
    vs_frame.place(relx=0.48, rely=0.0, relwidth=0.04, relheight=0.85)
    ui_references['vs_label'] = tk.Label(vs_frame, text="VS", font=('Segoe UI', 12, 'bold'), fg=THEME['fg_secondary'], bg=THEME['bg_main'])
    ui_references['vs_label'].place(relx=0.5, rely=0.4, anchor='center')

    # -- Blue Card --
    blue_card = tk.Frame(match_input_frame, bg=THEME['bg_card'], bd=2, relief='flat')
    blue_card.place(relx=0.52, rely=0.0, relwidth=0.48, relheight=0.85)
    ui_references['blue_card_frame'] = blue_card

    # Blue Content
    tk.Label(blue_card, text="BLUE TEAM", font=('Segoe UI', 8, 'bold'), fg=THEME['blue_team'], bg=THEME['bg_card']).pack(pady=(10,0))
    
    ui_references['blue_name_lbl'] = tk.Label(blue_card, text=team_blue_placeholder, font=('Segoe UI', 14, 'bold'), 
                                              fg=THEME['fg_primary'], bg=THEME['bg_card'], wraplength=180)
    ui_references['blue_name_lbl'].pack(pady=(5,0))
    
    ui_references['blue_roster_lbl'] = tk.Label(blue_card, text="P3 / P4", font=('Segoe UI', 10), 
                                                fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['blue_roster_lbl'].pack(pady=(2,10))
    
    ui_references['blue_stats_lbl'] = tk.Label(blue_card, text="0-0", font=('Consolas', 9), fg=THEME['fg_secondary'], bg=THEME['bg_card'])
    ui_references['blue_stats_lbl'].pack(side='bottom', pady=5)

    btn_blue = tk.Button(blue_card, text="🏆 BLUE WINS", command=lambda: declare_winner('blue'),
                         bg=THEME['blue_team'], fg='white', font=('Segoe UI', 11, 'bold'),
                         relief='flat', activebackground='#1565C0', cursor='hand2')
    btn_blue.pack(side='bottom', fill='x', padx=10, pady=10)

    # -- Controls (Bottom of Arena) --
    ctrl_frame = tk.Frame(tab_match, bg=THEME['bg_main'], pady=5)
    ctrl_frame.pack(fill='x', side='bottom')
    
    switch_frame_ref = ctrl_frame # Use existing ref name for compatibility
    
    btn_switch = tk.Button(ctrl_frame, text="🔄 Swap Puck Color", command=swap_teams,
                           bg=THEME['btn_default'], fg='white', relief='flat', font=('Segoe UI', 9))
    btn_switch.pack(side='left', padx=5, fill='x', expand=True)
    
    tk.Button(ctrl_frame, text="Pop-out Bracket ↗", command=open_full_bracket,
              bg=THEME['btn_default'], fg='white', relief='flat', font=('Segoe UI', 9)).pack(side='left', padx=5, fill='x', expand=True)

    # --- UPDATED: PERSISTENT FOOTER STATUS BAR ---
    footer_bar = tk.Frame(root, bg=THEME['bg_card'], height=25, bd=1, relief='sunken')
    footer_bar.pack(side='bottom', fill='x')

    # 1. Left Section: Version
    tk.Label(footer_bar, text=f"v{SHUF_VERSION}", font=('Segoe UI', 8), 
             fg=THEME['fg_secondary'], bg=THEME['bg_card'], padx=10).pack(side='left')

    # 2. Left Section: File/Database Status
    status_text = "🔴 REPLAY MODE" if REPLAY_MODE else "🟢 RECORDING LIVE"
    if REPLAY_VIEW_ONLY: status_text = "📁 VIEW ONLY"
    
    ui_references['footer_file_status'] = tk.Label(footer_bar, text=status_text, font=('Segoe UI', 8, 'bold'), 
                                                   fg=THEME['fg_secondary'], bg=THEME['bg_card'], padx=5)
    ui_references['footer_file_status'].pack(side='left')

    # 3. Right Section: Timer (Far Right)
    ui_references['timer_lbl'] = tk.Label(footer_bar, text="00:00", font=('Consolas', 10, 'bold'), 
                                           fg=THEME['accent_gold'], bg=THEME['bg_card'], padx=10)
    ui_references['timer_lbl'].pack(side='right')

    # 4. Center Section: Tournament Progress
    ui_references['footer_progress'] = tk.Label(footer_bar, text="Progress: 0%", font=('Segoe UI', 9), 
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
            tk.Label(f, text=f"{icon} {mid}:", font=('Segoe UI', 9, 'bold'), 
                     fg=THEME['fg_secondary'], bg=THEME['bg_card']).pack(side='left')
            
            # Player Names
            tk.Label(f, text=f"{roster_a}   vs   {roster_b}", 
                     font=('Segoe UI', 10, 'bold'), fg=status_color, bg=THEME['bg_card']).pack(side='left', padx=15)

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
            win_roster = " / ".join(TEAM_ROSTERS.get(record['winner'], ["?", "?"]))
            loss_roster = " / ".join(TEAM_ROSTERS.get(record['loser'], ["?", "?"]))
            
            # Format: "G1: Player A / Player B def. Player C / Player D"
            history_text = f"{record['id']}: {win_roster} def. {loss_roster}"
            
            tk.Label(f, text=history_text, font=THEME['font_main'], 
                     fg=color_hex, bg=THEME['bg_main']).pack(side='left')

def update_roster_seeding_vertical():
    """Updates roster tab with vertical list."""
    global roster_seeding_frame_ref, TEAMS, TEAM_ROSTERS
    if not roster_seeding_frame_ref: return
    
    for w in roster_seeding_frame_ref.winfo_children(): w.destroy()
    
    for i, team in enumerate(TEAMS):
        bg_col = THEME['bg_card']
        fg_col = THEME['fg_primary']
        
        # Highlight if active
        if team in current_match_teams.values():
            fg_col = THEME['accent_gold']
            
        row = tk.Frame(roster_seeding_frame_ref, bg=bg_col, pady=5)
        row.pack(fill='x', padx=10, pady=2)
        
        roster = TEAM_ROSTERS.get(team, ['?','?'])
        
        tk.Label(row, text=f"{team}", font=('Segoe UI', 10, 'bold'), width=15, anchor='w', bg=bg_col, fg=fg_col).pack(side='left')
        tk.Label(row, text=f"{roster[0]} / {roster[1]}", font=('Segoe UI', 10), anchor='w', bg=bg_col, fg=THEME['fg_secondary']).pack(side='left')

def update_timer_display():
    """Updates the match elapsed time every second."""
    global match_timer_id, TOURNAMENT_STATE, ui_references, main_root
    
    if not ui_references.get('timer_lbl') or not main_root:
        return
        
    match_id = TOURNAMENT_STATE.get('active_match_id')
    
    # Stop timer if the tournament is over or no active match
    if match_id == 'TOURNAMENT_OVER' or not match_id:
        ui_references['timer_lbl'].config(text="--:--")
        return

    match_data = TOURNAMENT_STATE.get(match_id)
    if not match_data:
        return

    # Initialize start time if this is the first tick for this match
    if 'start_time' not in match_data or not match_data['start_time']:
        match_data['start_time'] = time.time()

    # Calculate elapsed time
    elapsed = int(time.time() - match_data['start_time'])
    mins, secs = divmod(elapsed, 60)
    
    # Update the label
    ui_references['timer_lbl'].config(text=f"{mins:02d}:{secs:02d}")
    
    # Schedule the next tick in 1000ms (1 second)
    match_timer_id = main_root.after(1000, update_timer_display)

def update_scoreboard_display():
    """Redesigned update logic for the new Card UI."""
    global team_labels, player_labels_ref, TOURNAMENT_STATE, status_label, current_match_teams
    global game_routing_label, team_info_labels, bracket_info_canvas_ref, ui_references

    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')
    
    if match_id == 'TOURNAMENT_OVER':
        return
        
    log_message(f"Updating scoreboard display for match: {match_id}") 

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
            log_message(f"Error updating full bracket: {e}")
            
    # Refresh vertical roster highlights
    update_roster_seeding_vertical()
    update_schedule_tab()

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
    
    log_message(f"Winner declared for {match_id_to_confirm}: {winner} ({color}).") 

    # Hide the VS Cards, Show the Result Frame
    ui_references['match_tab_frame'].pack_forget()
    match_res_frame.pack(fill='both', expand=True, padx=10, pady=10)
    
    # Re-create buttons inside match_res_frame
    for widget in match_res_frame.winfo_children():
        widget.destroy()
    current_match_res_buttons.clear()
    
    # Header
    tk.Label(match_res_frame, text="CONFIRM RESULT", font=('Segoe UI', 14, 'bold'), 
             bg=THEME['bg_main'], fg=THEME['fg_primary']).pack(pady=(0, 20))
             
    tk.Label(match_res_frame, text=f"{winner} wins Match {match_id_to_confirm}?", 
             font=('Segoe UI', 12), bg=THEME['bg_main'], fg=THEME['fg_secondary']).pack(pady=(0, 20))
    
    # Big Confirm Button
    confirm_btn = tk.Button(match_res_frame, text=f"✅ YES, {winner} WON", 
                            bg=THEME['btn_confirm'], fg='white', 
                            font=('Segoe UI', 12, 'bold'), relief='flat', padx=20, pady=15,
                            command=lambda w=winner, l=loser, c=color, mid=match_id_to_confirm: confirm_match_resolution(w, l, c, mid))
    confirm_btn.pack(pady=10, fill='x')
    current_match_res_buttons.append(confirm_btn)
    
    # Cancel Button
    go_back_btn = tk.Button(match_res_frame, text="❌ CANCEL / GO BACK", 
                            bg=THEME['btn_cancel'], fg='white', 
                            font=('Segoe UI', 10), relief='flat', padx=10, pady=10,
                            command=go_back_to_selection)
    go_back_btn.pack(pady=10, fill='x')
    current_match_res_buttons.append(go_back_btn)

def go_back_to_selection():
    """Reverts the UI from Confirmation to the Arena view."""
    global match_res_frame, ui_references
    
    log_message("Going back to winner selection screen.") 
    
    match_res_frame.pack_forget()
    ui_references['match_tab_frame'].pack(fill='both', expand=True, padx=5, pady=5)
    
    # Ensure button text is up to date
    update_winner_buttons()

def load_match_data_and_teams():
    """Updated to handle the new notebook structure."""
    global TOURNAMENT_STATE, current_match_teams, last_assigned_match_id
    global rankings_label_ref, final_control_frame_ref, rankings_display_frame_ref
    global ui_references, match_res_frame
    
    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')
    log_message(f"Loading match data for new active match: {match_id}") 
    
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
    
        global match_timer_id
        if match_timer_id and main_root:
            main_root.after_cancel(match_timer_id) # Cancel any old loops
        update_timer_display() # Kick off the new timer loop
    
    update_scoreboard_display()

def run_replay_mode(path):
    global REPLAY_FILEPATH, REPLAY_MODE, REPLAY_VIEW_ONLY
    global main_root, TEAMS, TEAM_ROSTERS, TOURNAMENT_STATE, TOURNAMENT_RANKINGS

    REPLAY_MODE = True
    REPLAY_VIEW_ONLY = False

    log_message(f"Attempting to load replay from: {path}")

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

        log_message("Replay loaded: Tournament Finished. Entering View-Only Mode.")

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

    log_message(f"Replay loaded: Resuming tournament. Appending to {path}")

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
    
    log_message("Application close requested.") 
    
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
            'L_next': _parse_json_destination(data.get('loser_drops_to'))
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
    
    log_message(f"Searching for configuration file: {base_filename}")
    
    state = {}
    prizes = {}
    json_loaded = False

    for filepath in search_paths:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    content = json.load(f)
                state, prizes = _parse_json_config_content(content)
                log_message(f"Successfully loaded JSON from: '{filepath}'")
                json_loaded = True
                break
            except Exception as e:
                log_message(f"Error reading JSON file '{filepath}': {e}")
                raise ValueError(f"Error parsing '{filepath}': {e}")

    if not json_loaded:
        err_msg = f"Configuration file '{base_filename}' not found."
        log_message(f"Error: {err_msg}")
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
        'teams': [None, None],
        'W_next': ('CHAMPION', 0), 
        'L_next': ('GGF', 0) 
    }

    state['GGF'] = {
        'teams': [None, None],
        'W_next': ('CHAMPION', 0),
        'L_next': ('CHAMPION', 1)
    }
    
    log_message(f"Injected Finals: GF linked from {WB_FINAL_ID} & {LB_FINAL_ID}")
    return state, prizes
        
def calculate_dynamic_coords(state):
    """
    Calculates X/Y coordinates for all matches, including GF/GGF.
    """
    coords = {}
    
    MATCH_WIDTH_U = 12 
    MATCH_HEIGHT_U = 6 
    
    WB_START_Y_U = 10
    LB_START_Y_U = 55
    FINALS_Y_U = 35 
    
    X_STEP_U = MATCH_WIDTH_U + 6 
    Y_STEP_U = MATCH_HEIGHT_U + 4 

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
        log_message("View-Only mode detected. Exiting application on window close.")
        on_close(main_root)
        return

    if full_bracket_root:
        full_bracket_root.destroy()
    full_bracket_root = None
    full_bracket_canvas = None

def draw_large_bracket(canvas):
    """
    Draws the large full bracket and adds GF-winner reconstruction
    in strict view-only mode.
    """
    global TEAM_ROSTERS, REPLAY_VIEW_ONLY, TOURNAMENT_RANKINGS

    canvas.delete('all')
    canvas.configure(bg=THEME['bg_canvas'])

    H_SCALE_PX = 14
    V_SCALE_PX = 7

    MATCH_W_U = 12
    MATCH_H_U = 6

    match_w = MATCH_W_U * H_SCALE_PX
    match_h = MATCH_H_U * V_SCALE_PX

    # Calculate coords
    match_coords = calculate_dynamic_coords(TOURNAMENT_STATE)
    if not match_coords:
        return

    max_x_u = 0
    max_y_u = 0
    for (mx, my) in match_coords.values():
        max_x_u = max(max_x_u, mx)
        max_y_u = max(max_y_u, my)

    total_width = (max_x_u + MATCH_W_U + 5) * H_SCALE_PX
    total_height = (max_y_u + MATCH_H_U + 5) * V_SCALE_PX
    canvas.config(scrollregion=(0, 0, total_width, total_height))

    H_PAD = 20
    V_PAD = 20

    def get_coords(match_id):
        if match_id not in match_coords:
            return 0, 0
        u_x, u_y = match_coords[match_id]
        return u_x * H_SCALE_PX + H_PAD, u_y * V_SCALE_PX + V_PAD

    # Draw lines
    draw_angled_lines(canvas, TOURNAMENT_STATE, match_coords,
                      match_w, match_h, H_SCALE_PX, V_SCALE_PX, H_PAD, V_PAD)

    font_roster_size = 8

    for match_id, match_data in TOURNAMENT_STATE.items():
        if not isinstance(match_data, dict) or 'teams' not in match_data:
            continue
        if match_id not in match_coords:
            continue

        x, y = get_coords(match_id)

        # Determine background
        fill_color = 'white'
        outline = '#263238'
        if match_data.get('champion'):
            fill_color = THEME['accent_gold']
        elif match_id == TOURNAMENT_STATE.get('active_match_id') and match_data['winner'] is None:
            fill_color = '#FFF9C4' # Light Yellow
        elif match_data.get('winner_color') == 'red':
            fill_color = '#FFCDD2' # Light Red
        elif match_data.get('winner_color') == 'blue':
            fill_color = '#BBDEFB' # Light Blue

        canvas.create_rectangle(x, y, x + match_w, y + match_h,
                                fill=fill_color, outline=outline, width=2)
        canvas.create_text(x + 5, y + 5, text=f"{match_id}",
                           anchor='w', fill='#000000',
                           font=('Segoe UI', 8, 'bold'))

        # Determine winner or champion
        winner = match_data.get('winner') or match_data.get('champion')

        # -----------------------------
        # GF Reconstruction (strict view-only)
        # -----------------------------
        if REPLAY_VIEW_ONLY and match_id == 'GF' and not winner:
            # Reconstruct from rankings if available
            winner = TOURNAMENT_RANKINGS.get('1ST')

        # Render teams
        team_A = match_data['teams'][0]
        team_B = match_data['teams'][1]

        # Team A
        txt_A = "TBD"
        font_A = ('Segoe UI', font_roster_size)
        if team_A:
            if not team_A.startswith('W:'):
                roster_A = TEAM_ROSTERS.get(team_A, ['?','?'])
                txt_A = f"{team_A} ({roster_A[0]}/{roster_A[1]})"
            else:
                txt_A = team_A

            if winner and team_A == winner:
                txt_A += " \u2713"
                font_A = ('Segoe UI', font_roster_size, 'bold')

        canvas.create_text(x + 5, y + match_h/4 + 5,
                           text=txt_A, anchor='w', font=font_A)

        canvas.create_line(x, y + match_h/2,
                           x + match_w, y + match_h/2,
                           fill='#B0BEC5')

        # Team B
        txt_B = "TBD"
        font_B = ('Segoe UI', font_roster_size)
        if team_B:
            if not team_B.startswith('W:'):
                roster_B = TEAM_ROSTERS.get(team_B, ['?','?'])
                txt_B = f"{team_B} ({roster_B[0]}/{roster_B[1]})"
            else:
                txt_B = team_B

            if winner and team_B == winner:
                txt_B += " \u2713"
                font_B = ('Segoe UI', font_roster_size, 'bold')

        canvas.create_text(x + 5, y + 3*match_h/4,
                           text=txt_B, anchor='w', font=font_B)
        
def open_full_bracket():
    """Opens (or lifts) the large scrollable bracket window, adding an exit button in View Only mode."""
    global full_bracket_root, full_bracket_canvas, REPLAY_VIEW_ONLY
    
    if full_bracket_root is not None:
        try:
            full_bracket_root.lift()
            return
        except:
            full_bracket_root = None

    full_bracket_root = tk.Toplevel(main_root)
    full_bracket_root.title("Moose Lodge Shuffleboard Bracket")
    full_bracket_root.geometry("1000x700")
    full_bracket_root.configure(bg=THEME['bg_main'])
    # This protocol is now the central exit point for the window
    full_bracket_root.protocol("WM_DELETE_WINDOW", on_full_bracket_close)
    
    container = tk.Frame(full_bracket_root, bg=THEME['bg_main'])
    container.pack(fill='both', expand=True)

    if REPLAY_VIEW_ONLY:
        # Add an explicit exit button when in view-only mode
        exit_frame = tk.Frame(container, bg=THEME['bg_card'])
        exit_frame.pack(fill='x', pady=(0, 5))
        
        exit_btn = tk.Button(exit_frame, text="EXIT APPLICATION (View Only)", 
                             command=lambda: on_close(main_root),
                             bg=THEME['btn_cancel'], fg='white', font=THEME['font_bold'], height=2,
                             relief='flat', padx=10, pady=5)
        exit_btn.pack(padx=10, pady=5, fill='x')
        
        # Place the canvas in a sub-container to separate it from the exit button
        bracket_canvas_container = tk.Frame(container, bg=THEME['bg_main'])
        bracket_canvas_container.pack(fill='both', expand=True, padx=5, pady=5)
    else:
        bracket_canvas_container = container
    
    v_scroll = tk.Scrollbar(bracket_canvas_container, orient='vertical')
    h_scroll = tk.Scrollbar(bracket_canvas_container, orient='horizontal')
    
    full_bracket_canvas = tk.Canvas(bracket_canvas_container, bg=THEME['bg_canvas'], 
                                    yscrollcommand=v_scroll.set, 
                                    xscrollcommand=h_scroll.set,
                                    highlightthickness=0)
    
    v_scroll.config(command=full_bracket_canvas.yview)
    h_scroll.config(command=full_bracket_canvas.xview)
    
    full_bracket_canvas.grid(row=0, column=0, sticky='nsew')
    v_scroll.grid(row=0, column=1, sticky='ns')
    h_scroll.grid(row=1, column=0, sticky='ew')
    
    bracket_canvas_container.grid_rowconfigure(0, weight=1)
    bracket_canvas_container.grid_columnconfigure(0, weight=1)
    
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
            log_message(f"Found next active match: {k} ({data['teams'][0]} vs {data['teams'][1]})") 
            return k
    
    if sorted_match_keys:
        last_g_id = sorted_match_keys[-1]
        if TOURNAMENT_STATE[last_g_id].get('is_reset', False) and TOURNAMENT_STATE[last_g_id].get('winner') is None:
             log_message(f"Found next active match (Finals Reset): {last_g_id}") 
             return last_g_id
         
    log_message("Tournament is over (or in final state check).") 
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
    }

    # Serialize match-level state including champion.
    for mid, match_data in TOURNAMENT_STATE.items():
        if isinstance(match_data, dict):
            snapshot["state"][mid] = {
                "teams": match_data.get("teams"),
                "winner": match_data.get("winner"),
                "winner_color": match_data.get("winner_color"),
                "is_reset": match_data.get("is_reset", False),
                "champion": match_data.get("champion"),  # ADDED
                "start_time": match_data.get("start_time"),
                "config": {
                    k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in match_data.get("config", {}).items()
                },
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

        log_message(f"[Replay] Snapshot appended to {path}")

    except Exception as e:
        log_message(f"[Replay] Error writing snapshot: {e}")

def handle_match_resolution(winner, loser, winning_color, match_id):
    """
    Propagates the winner/loser of the *specific* completed match (match_id) 
    to the next games, with GF/GGF reset logic.
    """
    global current_match_res_buttons, TOURNAMENT_RANKINGS
    
    log_message(f"Resolving match {match_id}: Winner={winner} ({winning_color}), Loser={loser}") 
    
    if match_id == 'TOURNAMENT_OVER':
         messagebox.showerror("Error", "Attempted to resolve 'TOURNAMENT_OVER' state.")
         TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
         reset_game(update_teams=True)
         log_message("Error: Attempted to resolve 'TOURNAMENT_OVER'. Resetting game state.") 
         return
         
    match_data = TOURNAMENT_STATE.get(match_id)

    if not match_data or 'config' not in match_data:
        log_message(f"Error: Match {match_id} configuration data is missing or invalid.") 
        messagebox.showerror("Error", f"Match {match_id} configuration data is missing or invalid.")
        TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
        reset_game(update_teams=True)
        return
        
    match_config = match_data['config']
    
    if match_data.get('winner') is not None and not match_data.get('is_reset', False):
        log_message(f"Warning: Match {match_id} already resolved.") 
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
            
            reset_game_id = next((k for k in TOURNAMENT_STATE if k == 'GGF'), 'GGF')
            
            if reset_game_id in TOURNAMENT_STATE:
                TOURNAMENT_STATE[reset_game_id]['teams'] = [winner, loser]
                TOURNAMENT_STATE[reset_game_id]['is_reset'] = True
                
                match_data['winner'] = None 
                match_data['winner_color'] = None 
            
            w_roster = "/".join(TEAM_ROSTERS.get(winner, ["P1", "P2"]))
            l_roster = "/".join(TEAM_ROSTERS.get(loser, ["P3", "P4"]))
            messagebox.showinfo("Final Round!", 
                                f"{w_roster} have defeated the previously undefeated team {l_roster}! So for the marbles...")
            
            TOURNAMENT_STATE['active_match_id'] = reset_game_id
            log_message(f"Match GF resulted in Bracket Reset. Next active match: {reset_game_id} ({winner} vs {loser})") 

            
            
            reset_game() 
            return # EXIT after reset handling

        # Case 2: WB Winner (winner) defeats LB Winner (loser) in GF -> TOURNAMENT OVER
        elif winner == wb_finalist:
            match_data['champion'] = winner
            TOURNAMENT_RANKINGS['1ST'] = winner
            TOURNAMENT_RANKINGS['2ND'] = loser
            TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
            log_message(f"Match GF: WB Winner {winner} wins Championship. 1ST={winner}, 2ND={loser}") 
            reset_game() 
            return 

    elif match_id == 'GGF':
        # Case 3: GGF is played -> TOURNAMENT OVER
        TOURNAMENT_STATE[match_id]['champion'] = winner
        TOURNAMENT_RANKINGS['1ST'] = winner
        gfgf_loser = TOURNAMENT_STATE[match_id]['teams'][0] if winner == TOURNAMENT_STATE[match_id]['teams'][1] else TOURNAMENT_STATE[match_id]['teams'][1]
        TOURNAMENT_RANKINGS['2ND'] = gfgf_loser
        
        TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
        log_message(f"Match {match_id} (Reset) completed. 1ST={winner}, 2ND={gfgf_loser}. Tournament is over.") 
        
        reset_game() 
        return 
        
    # --- Standard Propagation (For all non-final games that did not return above) ---

    # 2. Propagate Winner 
    w_target = match_config.get('W_next')
    if isinstance(w_target, tuple):
        next_match_id, slot = w_target
        if next_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[next_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[next_match_id]['teams'][slot] = winner
            log_message(f"Propagated Winner {winner} to {next_match_id} [Slot {slot}].") 
    elif w_target == 'CHAMPION':
         match_data['champion'] = winner
         TOURNAMENT_RANKINGS['1ST'] = winner
         log_message(f"Match {match_id}: Winner {winner} is CHAMPION.") 
    
    # 3. Propagate Loser and Assign Elimination Rank (MODIFIED)
    l_target = match_config.get('L_next')
    
    if isinstance(l_target, tuple):
        loser_match_id, slot = l_target
        if loser_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[loser_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[loser_match_id]['teams'][slot] = loser
            log_message(f"Propagated Loser {loser} to {loser_match_id} [Slot {slot}].") 
    elif l_target and l_target.startswith('ELIMINATED'):
        rank_match = re.search(r'\[(\w+)\]', l_target)
        if rank_match:
            rank = rank_match.group(1)
            if rank not in TOURNAMENT_RANKINGS:
                TOURNAMENT_RANKINGS[rank] = loser
                log_message(f"Assigned rank {rank} to eliminated team {loser}.") 
        
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
    log_message(f"Standard Match Resolution complete. New active match: {TOURNAMENT_STATE['active_match_id']}") 
    
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
                           font=('Segoe UI', 7, 'bold'),
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
    for match_id, match_data in TOURNAMENT_STATE.items():
        if not isinstance(match_data, dict):
            continue
        
        winner = match_data.get('winner')
        
        if match_id == 'GF' and match_data.get('is_reset') and winner is None:
            ggf_data = TOURNAMENT_STATE.get('GGF')
            if ggf_data and ggf_data.get('teams'):
                 winner = ggf_data['teams'][0]

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
    log_message(f"Updated winner buttons: Red={team_red}, Blue={team_blue}") 

def swap_teams():
    """Swaps the Red and Blue teams in the current match UI."""
    global current_match_teams
    
    log_message(f"Swapping teams: {current_match_teams['red']} <-> {current_match_teams['blue']}") 
    
    temp = current_match_teams['red']
    current_match_teams['red'] = current_match_teams['blue']
    current_match_teams['blue'] = temp
    
    update_scoreboard_display()

def display_final_rankings(champion):
    """
    Displays the final rankings and a centered EXIT button using the correct root reference.
    """
    # Use 'main_root' instead of 'root'
    global rankings_display_frame_ref, rankings_label_ref, status_label
    global ui_references, final_control_frame_ref, TEAM_ROSTERS, TEAMS, main_root

    log_message(f"Displaying final rankings. Champion: {champion}")

    # 1. Update Header
    if status_label:
        status_label.config(text="🏆 TOURNAMENT COMPLETE 🏆", fg=THEME['accent_gold'])

    # 2. Hide the main game interface
    if ui_references.get('notebook'):
        ui_references['notebook'].pack_forget()

    # 3. Show the Rankings Frame
    rankings_display_frame_ref.pack(fill='both', expand=True, padx=20, pady=20)
    
    # 4. Format the Champion and Standings text
    champ_roster = " / ".join(TEAM_ROSTERS.get(champion, ["?",  "?"]))
    final_text = f"CONGRATULATIONS\n\n🏆 {champ_roster} 🏆\n\nFINAL STANDINGS:\n"
    
    sorted_teams = sorted(TEAMS, key=lambda t: get_team_record(t)[0], reverse=True)
    for i, team in enumerate(sorted_teams, 1):
        w, l = get_team_record(team)
        team_roster = " / ".join(TEAM_ROSTERS.get(team, ["?", "?"]))
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"{i}. "
        final_text += f"\n{medal}{team_roster} ({w}W - {l}L)"

    # 5. Update the text label
    rankings_label_ref.config(
        text=final_text, 
        justify='center', 
        font=('Segoe UI', 12, 'bold'),
        fg=THEME['fg_primary'],
        bg=THEME['bg_card'],
        pady=20
    )

    # 6. Setup the EXIT Button
    final_control_frame_ref.pack(fill='x', side='bottom', pady=30)
    
    # Clear out any old buttons
    for child in final_control_frame_ref.winfo_children():
        child.destroy()
        
    # Create the large Exit button using main_root.destroy
    exit_button = tk.Button(
        final_control_frame_ref, 
        text="EXIT TOURNAMENT", 
        command=main_root.destroy,  # Using the correct global variable
        bg=THEME['btn_cancel'], 
        fg='white',
        font=('Segoe UI', 12, 'bold'), 
        relief='flat', 
        padx=60, 
        pady=20,
        cursor='hand2'
    )
    exit_button.pack(expand=True)
    
def reset_game(update_teams=True):
    """Resets the game state (only updating teams now)."""
    log_message("Resetting game UI.") 
    if update_teams:
        load_match_data_and_teams()

def update_roster_seeding_display():
    """Updates the Team Roster & Seeding information box with a horizontal, player-focused view."""
    global roster_seeding_frame_ref, TEAMS, TEAM_ROSTERS

    if not roster_seeding_frame_ref or not TEAMS:
        return

    log_message("Updating Team Roster & Seeding display (horizontal).")

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
    
    root.geometry("470x600") # Taller geometry for better breathing room

    g1_teams = TOURNAMENT_STATE.get('G1', {}).get('teams', ["Team Red", "Team Blue"])
    team_A = g1_teams[0] or "Team Red"
    team_B = g1_teams[1] or "Team Blue"
    
    log_message(f"Setting up main GUI for teams: {team_A} vs {team_B}") 
    
    setup_scoreboard(root, team_A, team_B) 

def show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes):
    """Displays the player draw, team rosters, and prize pool before launching the main GUI."""
    
    # --- Theme Constants ---
    BG_MAIN = "#121212"
    BG_CARD = "#1E1E1E"
    FG_TEXT = "#FFFFFF"
    FG_ACCENT = "#4CAF50" # Green for headers

    summary_root = tk.Tk()
    summary_root.title("Tournament Draw & Prize Pool")
    summary_root.geometry("550x750")
    summary_root.configure(bg=BG_MAIN)
    summary_root.protocol("WM_DELETE_WINDOW", lambda: on_close(summary_root)) 
    
    log_message("Displaying Draw Summary and Prize Pool.") 
    
    # Header
    tk.Label(summary_root, text="TOURNAMENT READY", font=('Segoe UI', 18, 'bold'), 
             bg=BG_MAIN, fg=FG_ACCENT).pack(pady=(20, 10))

    # 1. Draw Results
    draw_frame = tk.Frame(summary_root, padx=15, pady=10, bg=BG_CARD)
    draw_frame.pack(fill='both', expand=True, padx=20, pady=5)
    
    tk.Label(draw_frame, text="Player Draw Results", font=('Segoe UI', 11, 'bold'), 
             bg=BG_CARD, fg="#2196F3", anchor='w').pack(fill='x')
    
    draw_scroll = tk.Scrollbar(draw_frame)
    draw_scroll.pack(side='right', fill='y')
    
    draw_text_widget = tk.Text(draw_frame, height=6, bg="#2D2D2D", fg="white", 
                               font=('Consolas', 9), relief='flat', yscrollcommand=draw_scroll.set)
    draw_text_widget.pack(fill='both', expand=True, pady=5)
    draw_scroll.config(command=draw_text_widget.yview)

    draw_content = ""
    for draw_num, player_name in player_draws:
        draw_content += f"Draw #{draw_num}: {player_name}\n"
    
    draw_text_widget.insert('1.0', draw_content)
    draw_text_widget.config(state='disabled')

    # 2. Team Rosters
    team_frame = tk.Frame(summary_root, padx=15, pady=10, bg=BG_CARD)
    team_frame.pack(fill='both', expand=True, padx=20, pady=5)
    
    tk.Label(team_frame, text="Team Rosters & Seeding", font=('Segoe UI', 11, 'bold'),
             bg=BG_CARD, fg="#FFC107", anchor='w').pack(fill='x')
    
    team_text_widget = tk.Text(team_frame, height=6, bg="#2D2D2D", fg="white", 
                               font=('Consolas', 9), relief='flat')
    team_text_widget.pack(fill='both', expand=True, pady=5)
    
    team_content = ""
    for i, team_name in enumerate(TEAMS):
        roster = TEAM_ROSTERS.get(team_name, ["N/A", "N/A"])
        team_content += f"Team {i+1} (T{i+1}): {roster[0]} / {roster[1]}\n"
    
    team_text_widget.insert('1.0', team_content)
    team_text_widget.config(state='disabled')
    
    # 3. Prize Pool
    prize_frame = tk.Frame(summary_root, padx=15, pady=10, bg=BG_CARD)
    prize_frame.pack(fill='x', padx=20, pady=5)
    
    tk.Label(prize_frame, text="Prize Pool Calculation", font=('Segoe UI', 11, 'bold'),
             bg=BG_CARD, fg="#E91E63", anchor='w').pack(fill='x')
    
    per_player_1st = int(prizes.get('1st', 0) / 2)
    per_player_2nd = int(prizes.get('2nd', 0) / 2)
    
    prize_text = f"Total Pool: ${total_pool}\n\n"
    prize_text += f"1st Place: ${prizes.get('1st', 0)} (${per_player_1st} / player)\n"
    prize_text += f"2nd Place: ${prizes.get('2nd', 0)} (${per_player_2nd} / player)\n"
    
    if prizes.get('3rd') is not None and prizes.get('3rd') > 0:
        per_player_3rd = int(prizes.get('3rd', 0) / 2)
        prize_text += f"3rd Place: ${prizes.get('3rd', 0)} (${per_player_3rd} / player)\n"
        
    tk.Label(prize_frame, text=prize_text, justify=tk.LEFT, font=('Consolas', 10),
             bg=BG_CARD, fg="white").pack(anchor='w', pady=5)
    
    start_button = tk.Button(summary_root, text="BEGIN TOURNAMENT", 
                             command=summary_root.quit, 
                             bg=THEME['btn_confirm'], fg='white', font=('Segoe UI', 12, 'bold'), height=2,
                             relief='flat', padx=20)
    start_button.pack(fill='x', padx=20, pady=20)
    
    summary_root.mainloop() 
    summary_root.destroy()
    log_message("Draw Summary window closed. Proceeding to main GUI.") 
    return

def generate_dynamic_bracket(teams, config=None):
    """
    Loads the bracket structure from the config file, initializes TOURNAMENT_STATE,
    and seeds the starting matches with teams (T1, T2, etc.).
    """
    global TOURNAMENT_STATE
    TOURNAMENT_STATE.clear()

    num_teams = len(teams)
    log_message(f"Generating bracket for {num_teams} teams.") 
    
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
            'is_reset': match_id == 'GGF' 
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
                        log_message(f"Seeded {teams[t_num]} into {match_id} [Slot {i}].") 
                    else:
                        TOURNAMENT_STATE[match_id]['teams'][i] = None 

    initial_active_match = find_next_active_match()
    TOURNAMENT_STATE['active_match_id'] = initial_active_match
    log_message(f"Bracket generation complete. Initial active match: {initial_active_match}")

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
            log_message(f"Starting file logging to: {filename}")
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
    Combined dialog for selecting player count and entering names/draw numbers.
    Maintains player data (Names, Paid status, Draws) when toggling modes.
    """
    log_message("Opening unified player setup dialog.") 
    
    # --- Theme Constants for this Dialog ---
    BG_MAIN = "#121212"
    BG_CARD = "#1E1E1E" 
    FG_TEXT = "#E0E0E0"
    FG_SUB = "#B0B0B0"
    ENTRY_BG = "#2D2D2D"
    ENTRY_FG = "#FFFFFF"
    BTN_BG = "#333333"
    BTN_FG = "#FFFFFF"
    
    dialog = tk.Toplevel(parent)
    dialog.title("Tournament Setup - Player Entry")
    dialog.geometry("650x850") 
    dialog.configure(bg=BG_MAIN)
    dialog.grab_set() 
    
    result = None 
    is_manual_draw = tk.BooleanVar(value=False)
    log_game_var = tk.BooleanVar(value=LOG_GAME_TO_FILE)
    
    # Internal state
    current_player_count = MIN_PLAYERS 
    player_entries = [] # List of tuples: (name_entry, paid_var, draw_entry_or_None)

    # --- Data Persistence Helpers ---
    def save_current_data():
        """Scrapes text and state from current widgets to prevent loss on re-render."""
        data = []
        for widgets in player_entries:
            # (name_entry, paid_var, draw_entry)
            name = widgets[0].get().strip()
            paid = widgets[1].get()
            draw = ""
            if len(widgets) > 2 and widgets[2]:
                draw = widgets[2].get().strip()
            data.append({'name': name, 'paid': paid, 'draw': draw})
        return data

    def update_visuals(event=None):
        """Red (Duplicate) > Orange (Not Paid) > White (OK)."""
        current_names = [w[0].get().strip() for w in player_entries]
        from collections import Counter
        counts = Counter(current_names)
        has_duplicates = False
        
        for widgets in player_entries:
            name_entry, paid_var = widgets[0], widgets[1]
            val = name_entry.get().strip()
            
            if val and counts[val] > 1:
                name_entry.config(bg='#C62828', fg='white') # Dark Red
                has_duplicates = True
            elif not paid_var.get():
                name_entry.config(bg='#EF6C00', fg='white') # Dark Orange
            else:
                name_entry.config(bg=ENTRY_BG, fg=ENTRY_FG)
        return has_duplicates

    # --- Dynamic Rendering Logic ---
    def create_player_row(parent_frame, player_index, initial_data=None):
        """Creates a row, populating with existing data if provided."""
        row_frame = tk.Frame(parent_frame, bg=BG_CARD, pady=2)
        row_frame.pack(fill='x', pady=3, padx=5)
        
        p_num = player_index + 1
        tk.Label(row_frame, text=f"P{p_num:02}:", width=4, anchor='w', 
                 bg=BG_CARD, fg=FG_SUB, font=('Segoe UI', 10, 'bold')).pack(side='left', padx=5)

        draw_entry = None
        if is_manual_draw.get():
            draw_entry = tk.Entry(row_frame, width=5, justify='center', 
                                  bg=ENTRY_BG, fg=ENTRY_FG, insertbackground='white', relief='flat')
            draw_entry.pack(side='left', padx=(0,5))
            # Restore draw or default to index
            val = initial_data.get('draw') if initial_data else str(p_num)
            draw_entry.insert(0, val if val else str(p_num))
            tk.Label(row_frame, text="|", bg=BG_CARD, fg=FG_SUB).pack(side='left', padx=(0,5))

        name_entry = tk.Entry(row_frame, bg=ENTRY_BG, fg=ENTRY_FG, insertbackground='white', relief='flat', font=('Segoe UI', 10))
        name_entry.pack(side='left', fill='x', expand=True, padx=(0, 5), ipady=3)
        # Restore name or default to "Player X"
        name_val = initial_data.get('name') if initial_data else f"Player {p_num}"
        name_entry.insert(0, name_val)
        name_entry.bind('<KeyRelease>', update_visuals)

        paid_var = tk.BooleanVar(value=initial_data.get('paid', False) if initial_data else False)
        chk = tk.Checkbutton(row_frame, text="Paid", variable=paid_var, 
                             bg=BG_CARD, fg=FG_TEXT, selectcolor=BG_MAIN, 
                             activebackground=BG_CARD, activeforeground=FG_TEXT,
                             command=update_visuals)
        chk.pack(side='right', padx=(5, 10))

        return (name_entry, paid_var, draw_entry)

    def render_inputs(container):
        """Saves current state, wipes UI, and rebuilds."""
        saved_data = save_current_data()
        
        for widget in container.winfo_children():
            widget.destroy()
        player_entries.clear()

        instr = "Draw # unique" if is_manual_draw.get() else "Auto-Draw"
        tk.Label(container, text=f"** {instr} | Orange=Unpaid | Red=Duplicate **", 
                 fg=FG_SUB, bg=BG_CARD, font=('Segoe UI', 9)).pack(pady=(10, 5), anchor='w', padx=10)

        for i in range(current_player_count):
            existing = saved_data[i] if i < len(saved_data) else None
            widgets = create_player_row(container, i, existing)
            player_entries.append(widgets)
        
        container.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        update_visuals()

    # --- Controls ---
    header_frame = tk.Frame(dialog, bg=BG_MAIN, pady=10)
    header_frame.pack(fill='x')
    tk.Label(header_frame, text="Configure Players", font=("Segoe UI", 16, "bold"), 
             bg=BG_MAIN, fg=THEME['blue_team']).pack(side='top', pady=(0, 10))

    controls_frame = tk.Frame(header_frame, bg=BG_MAIN)
    controls_frame.pack(fill='x', padx=20)

    tk.Checkbutton(controls_frame, text="Manual Draw (Assign Draw #)", 
                  variable=is_manual_draw, command=lambda: render_inputs(input_container),
                  bg=BG_MAIN, fg=FG_TEXT, selectcolor=BG_CARD, activebackground=BG_MAIN, activeforeground=FG_TEXT).pack(side='left')
    
    tk.Checkbutton(controls_frame, text="Log Game to File", 
                  variable=log_game_var, command=lambda: toggle_log_game(log_game_var),
                  bg=BG_MAIN, fg=FG_TEXT, selectcolor=BG_CARD, activebackground=BG_MAIN, activeforeground=FG_TEXT).pack(side='right')

    # --- Scrollable Area ---
    canvas_frame = tk.Frame(dialog, bd=0, bg=BG_CARD)
    canvas_frame.pack(fill='both', expand=True, padx=20, pady=10)
    
    v_scrollbar = tk.Scrollbar(canvas_frame)
    v_scrollbar.pack(side='right', fill='y')
    
    canvas = tk.Canvas(canvas_frame, yscrollcommand=v_scrollbar.set, bg=BG_CARD, highlightthickness=0)
    canvas.pack(side='left', fill='both', expand=True)
    
    v_scrollbar.config(command=canvas.yview)
    
    input_container = tk.Frame(canvas, bg=BG_CARD)
    canvas.create_window((0, 0), window=input_container, anchor="nw")
    input_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

    # --- Team Mgmt ---
    mgmt_frame = tk.Frame(dialog, bg=BG_MAIN, pady=15)
    mgmt_frame.pack(fill='x')
    
    lbl_count = tk.Label(mgmt_frame, text=f"Total Players: {current_player_count}", 
                         font=("Segoe UI", 12, "bold"), bg=BG_MAIN, fg=FG_TEXT)
    lbl_count.pack(pady=(0, 10))

    def update_count(delta):
        nonlocal current_player_count
        new_count = current_player_count + delta
        if MIN_PLAYERS <= new_count <= MAX_PLAYERS:
            current_player_count = new_count
            render_inputs(input_container)
            lbl_count.config(text=f"Total Players: {current_player_count}")
        else:
            messagebox.showwarning("Limit", f"Player count must be between {MIN_PLAYERS} and {MAX_PLAYERS}.")

    btn_frame = tk.Frame(mgmt_frame, bg=BG_MAIN)
    btn_frame.pack()
    
    tk.Button(btn_frame, text="+ Add Team", command=lambda: update_count(2), 
              bg=BTN_BG, fg=BTN_FG, relief='flat', padx=15, pady=5).pack(side='left', padx=10)
    
    tk.Button(btn_frame, text="- Remove Team", command=lambda: update_count(-2), 
              bg=BTN_BG, fg=BTN_FG, relief='flat', padx=15, pady=5).pack(side='left', padx=10)

    # --- Footer ---
    action_frame = tk.Frame(dialog, pady=20, bg=BG_MAIN)
    action_frame.pack(fill='x', side='bottom')

    def on_ok():
        nonlocal result
        player_data_list = []
        unpaid_players = []
        if update_visuals():
            messagebox.showerror("Input Error", "Duplicate player names detected.")
            return

        assigned_draws = set()
        for i, (name_entry, paid_var, draw_entry) in enumerate(player_entries):
            p_name = name_entry.get().strip()
            if not p_name:
                messagebox.showerror("Error", f"Player {i+1} name is empty.")
                return
            if not paid_var.get(): unpaid_players.append(p_name)

            d_num = None
            if is_manual_draw.get():
                try:
                    d_num = int(draw_entry.get().strip())
                    if d_num < 1 or d_num > current_player_count or d_num in assigned_draws:
                        raise ValueError
                    assigned_draws.add(d_num)
                except ValueError:
                    messagebox.showerror("Error", f"Invalid/Duplicate draw for {p_name}.")
                    return
            player_data_list.append((d_num, p_name, paid_var.get()))

        if unpaid_players:
            messagebox.showerror("Payment Required", f"Unpaid players:\n" + "\n".join(unpaid_players[:10]))
            return

        result = (is_manual_draw.get(), player_data_list)
        dialog.destroy()

    tk.Button(action_frame, text="START TOURNAMENT", command=on_ok, 
              bg=THEME['btn_confirm'], fg='white', font=('Segoe UI', 11, 'bold'), 
              relief='flat', padx=30, pady=8).pack(side='right', padx=20)
              
    tk.Button(action_frame, text="Cancel", command=dialog.destroy,
              bg=THEME['btn_cancel'], fg='white', font=('Segoe UI', 10), 
              relief='flat', padx=15, pady=8).pack(side='right', padx=10)

    render_inputs(input_container)
    dialog.wait_window()
    return result

def start_tournament():
    """
    Prompts for players using the unified dialog, sets up teams, 
    generates the bracket, and launches the GUI.
    """
    global REPLAY_FILEPATH, TEAMS, TEAM_ROSTERS

    log_message("Starting tournament initialization process.") 
    
    dialog_root = tk.Tk()
    dialog_root.withdraw() 
    
    # --- 1. Combined Player Setup Step ---
    player_input_result = get_player_setup_dialog(dialog_root)
    
    if player_input_result is None:
        dialog_root.destroy()
        log_message("Tournament setup canceled.") 
        return
        
    is_manual_draw, player_data_list = player_input_result
    num_players = len(player_data_list)
    
    dialog_root.destroy() 
    
    # All players are paid now, enforced by the dialog
    log_message(f"Player data received. Total: {num_players}. Manual Draw: {is_manual_draw}. All players paid.") 

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
        log_message(f"Auto-draw complete. {num_players} players drawn.") 
    
    num_teams = num_players // 2
    for i in range(num_teams):
        team_name = f'Team {i+1}'
        player1 = player_draws[i*2][1]
        player2 = player_draws[i*2 + 1][1]
        
        TEAMS.append(team_name)
        TEAM_ROSTERS[team_name] = [player1, player2]
        log_message(f"Created team {team_name}: {player1} / {player2} (Draws #{player_draws[i*2][0]} & #{player_draws[i*2+1][0]})") 
        
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
    log_message(f"Loaded prizes: {prizes}. Total Pool: ${total_pool}") 
        
    # --- 4. Show Draw Summary ---
    show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes)
    
    # --- 5. Generate Bracket ---
    generate_dynamic_bracket(TEAMS, config)
    
    if not TOURNAMENT_STATE:
        log_message("Error: TOURNAMENT_STATE is empty after generation.") 
        return

    # --- 6. Create Replay File ---
    os.makedirs("replays", exist_ok=True)
    REPLAY_FILEPATH = f"replays/game_{int(time.time())}.json"
    log_message(f"Created new replay file at: {REPLAY_FILEPATH}")
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
    global match_res_frame, current_match_res_buttons

    log_message(f"Confirmation received for match {match_id}. Processing result...") 

    handle_match_resolution(winner, loser, winning_color, match_id)

    match_res_frame.pack_forget()
    current_match_res_buttons = []

    append_snapshot_to_file(REPLAY_FILEPATH)

    reset_game()
    
if __name__ == '__main__':
    
    log_message("Script starting.") 
    
    if not os.path.exists('data'):
        os.makedirs('data')
        log_message("Created 'data' directory.") 
    
    # Rule 1 & 2: Clean main block. No automatic replay file creation here.
    # Rule 12: Replay creation logic moved inside start_tournament (new game flow).
    
    show_title_screen()

    log_message("Script finished execution.")
