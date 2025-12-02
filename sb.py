#!/usr/bin/env python3

import tkinter as tk
from tkinter import messagebox, simpledialog
from math import log2, ceil
import sys
import re 
import random 
import os 
from collections import OrderedDict
import datetime # ADDED for logging
import json # ADDED for JSON

# --- Console Logging Function ---
def log_message(message):
    """Prints a timestamped message to the console and file (if enabled) for tracking."""
    global LOG_GAME_TO_FILE, LOG_FILE_HANDLE # ADDED for file logging
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    
    print(log_line)

    # ADDED: Write to file if enabled
    if LOG_GAME_TO_FILE and LOG_FILE_HANDLE:
        LOG_FILE_HANDLE.write(log_line + "\n")
        LOG_FILE_HANDLE.flush() # Ensure it's written immediately

# --- Global & Tournament Variables ---
TEAMS = []          
TEAM_ROSTERS = {}   
TOURNAMENT_RANKINGS = OrderedDict() # Stores {'1ST': 'Team X', '2ND': 'Team Y', '3RD': 'Team Z', ...}
ENTRY_FEE_PER_PERSON = 5
MIN_PLAYERS = 6     
MAX_PLAYERS = 20    

# Global state and Canvas item IDs
TOURNAMENT_STATE = {}
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
switch_frame_ref = None # Global reference for the switch button's container frame
full_bracket_root = None
full_bracket_canvas = None
# Global logging control
LOG_GAME_TO_FILE = False 
LOG_FILE_HANDLE = None
final_control_frame_ref = None # Container for the final QUIT button

# Global Variables for Match Details UI
match_details_frame = None
game_routing_label = None
team_info_labels = {'red': None, 'blue': None}
bracket_info_canvas_ref = None 
rankings_label_ref = None
bracket_info_frame_ref = None 
team_info_frame_ref = None 
rankings_display_frame_ref = None # NEW: Frame to hold the final rankings text


# --- System Functions ---

def on_close(root):
    """Handles clean exit when the window or the console is closed/interrupted."""
    global main_root
    global LOG_FILE_HANDLE # ADDED for file logging
    
    log_message("Application close requested.") # ADDED LOGGING
    
    # ADDED: Close log file handle if open
    if LOG_FILE_HANDLE:
        try:
            LOG_FILE_HANDLE.close()
            print("[Log Manager] Log file closed on exit.")
        except:
            pass

    try:
        if root:
            root.quit()
        sys.exit(0)
    except:
        sys.exit(0)

def show_title_screen():
    """Displays a title image and Begin button before tournament setup."""
    import tkinter as tk
    from PIL import Image, ImageTk

    splash = tk.Tk()
    splash.title("Moose Lodge Shuffleboard (large_bracket)")
    splash.geometry("500x500")
    splash.configure(bg="black")

    try:
        img = Image.open("img/title.png")
        img = img.resize((480, 300), Image.LANCZOS)
        logo = ImageTk.PhotoImage(img)
        tk.Label(splash, image=logo, bg="black").pack(pady=20)
    except Exception as e:
        tk.Label(splash, text="Moose Lodge Shuffleboard (large_bracket)", fg="white", bg="black", font=("Arial", 20, "bold")).pack(pady=60)
        print(f"[Title Screen] Could not load image: {e}")

    tk.Label(
        splash,
        text="Ms. Ethels Moose Shuffleboard Tournament",
        fg="white", bg="black",
        font=("Arial", 20)
    ).pack(pady=10)

    def start_game():
        splash.destroy()

    tk.Button(
        splash,
        text="Begin Game Setup",
        command=start_game,
        bg="#4CAF50", fg="white",
        font=("Arial", 14, "bold"),
        height=2
    ).pack(pady=40, fill="x", padx=50)

    splash.mainloop()

# --- Winnings Calculation (Retained for fallback only) ---

def calculate_winnings(num_teams):
    """Calculates prize pool and payouts based on team count, ensuring whole dollars."""
    PAYOUT_SPLIT_3_TEAMS = {'1st': 0.70, '2nd': 0.30, '3rd': 0.00}
    PAYOUT_SPLIT_4_PLUS = {'1st': 0.50, '2nd': 0.30, '3rd': 0.20}
    
    total_pool = num_teams * 2 * ENTRY_FEE_PER_PERSON
    
    if num_teams == 3:	
        payouts = PAYOUT_SPLIT_3_TEAMS
    else:
        payouts = PAYOUT_SPLIT_4_PLUS
        
    prizes = {}
    remaining_pool = total_pool
    
    prizes['1st'] = int(total_pool * payouts['1st'])
    prizes['2nd'] = int(total_pool * payouts['2nd'])
    
    if num_teams >= 4:
        # Calculate 3rd place prize using remaining pool to ensure whole dollar remainder
        prizes['3rd'] = remaining_pool - prizes['1st'] - prizes['2nd']
    else:
        prizes['3rd'] = 0
        
    log_message(f"Calculated prizes (fallback): Total Pool ${total_pool}, Prizes {prizes}") # ADDED LOGGING
    return total_pool, prizes

# --- Bracket Sorting Utility (Retained) ---

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
    
    if k == 'GGF' or k == 'GFF':
        # Grand Finals Reset
        return 100

    return 101

def _parse_json_destination(dest_data):
    """
    Translates JSON destination objects into the internal tuple/string format.
    """
    # Safety check: if it's not a dictionary (e.g. None or old string), return as-is or None
    if not isinstance(dest_data, dict):
        return None

    # Case 1: Standard Game Progression (Game + Slot)
    if 'game' in dest_data and 'slot' in dest_data:
        # Returns tuple: ('G4', 1)
        return (dest_data['game'], int(dest_data['slot']))

    # Case 2: Result Objects (Elimination, Champion, Conditional)
    if 'result' in dest_data:
        res = dest_data['result']
        
        if res == 'ELIMINATED':
            # Extract rank, ensure uppercase, and format: ELIMINATED[7TH]
            rank = dest_data.get('rank', 'N/A').upper()
            return f"ELIMINATED[{rank}]"
            
        # Returns string: 'CHAMPION' or 'GF_CONDITIONAL'
        return res
            
    return None

def _parse_json_config_content(json_content):
    """
    Parses the JSON dict into the application's internal dictionary structure
    and fixes the '2nd' typo.
    """
    config = {}
    prizes = {}
    
    # 1. Parse and Fix Prizes
    raw_prizes = json_content.get('prizes', {})
    
    # Explicit Mapping: JSON Key -> Python Key
    # This also fixes the typo by mapping "2" directly to "2nd"
    if '1' in raw_prizes: prizes['1st'] = raw_prizes['1']
    if '2' in raw_prizes: prizes['2nd'] = raw_prizes['2'] 
    if '3' in raw_prizes: prizes['3rd'] = raw_prizes['3']
    
    # 2. Parse Games
    games = json_content.get('games', {})
    
    for match_id, data in games.items():
        # Build the match entry exactly as sb.py expects it
        match_entry = {
            'teams': data.get('teams', [None, None]),
            # Use the helper function to parse destinations
            'W_next': _parse_json_destination(data.get('winner_advances_to')),
            'L_next': _parse_json_destination(data.get('loser_drops_to'))
        }
        config[match_id] = match_entry
        
    return config, prizes

# --- Dynamic Config Loading (Phase 2: JSON Loader) ---

def load_bracket_config(num_teams, elimination_type='D'):
    """
    Reads the bracket configuration from a local .json file.
    Dynamically constructs filename based on team count (e.g., '7teamD.json').
    """
    # 1. Construct the expected filename dynamically
    # Example: If num_teams=7, this becomes "7teamD.json"
    base_filename = f"{num_teams}team{elimination_type}.json"
    
    # 2. Define search paths (local folder first, then 'data' folder)
    search_paths = [
        base_filename,
        os.path.join('data', base_filename)
    ]
    
    log_message(f"Searching for configuration file: {base_filename}")

    # 3. Iterate through paths to find the file
    for filepath in search_paths:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    # Native JSON loading
                    content = json.load(f)
                
                log_message(f"Successfully loaded JSON configuration from: '{filepath}'")
                
                # Pass the raw JSON dict to our Phase 1 parser
                return _parse_json_config_content(content)
                
            except Exception as e:
                log_message(f"Error reading JSON file '{filepath}': {e}")
                raise ValueError(f"Error parsing '{filepath}': {e}")

    # 4. If loop completes without returning, file was not found
    err_msg = f"Configuration file '{base_filename}' not found. Ensure it exists in the script directory or 'data/'."
    log_message(f"Error: {err_msg}")
    raise FileNotFoundError(err_msg)
    
def calculate_dynamic_coords(state):
    # ... (function body remains unchanged) ...
    coords = {}
    
    # Constants (Normalized Units)
    X_UNITS = 100 
    Y_UNITS = 100 
    MATCH_WIDTH_U = 12 
    MATCH_HEIGHT_U = 6 
    WB_START_Y_U = 10
    LB_START_Y_U = 55
    FINALS_Y_U = 35
    X_STEP_U = MATCH_WIDTH_U + 6 # Distance between columns
    Y_STEP_U = MATCH_HEIGHT_U + 4 # Distance between rows

    # Get all match keys sorted chronologically (G1, G2, G3, ..., GF, GGF)
    sorted_match_keys = sorted(
        [k for k in state.keys() if k.startswith('G') or k == 'GF' or k == 'GGF'], 
        key=sort_match_keys
    )
    
    # 1. Classify Matches and Assign Rounds (X-coordinate logic)
    
    match_properties = {} 
    round_map_by_id = {}
    
    for match_id in sorted_match_keys:
        properties = {'track': 'WB', 'round': 0}
        
        if match_id == 'GF' or match_id == 'GGF':
            properties['track'] = 'Finals'
        elif match_id.startswith('G'):
            try:
                num = int(match_id[1:])
            except ValueError:
                 continue 
            
            # Rough Round Logic based on G# progression in typical DE brackets
            if num in [1, 2]: properties['round'] = 1
            elif num in [3, 4]: properties['round'] = 2
            elif num in [5, 6]: properties['round'] = 3
            elif num == 7: properties['round'] = 4 
            elif num == 8: properties['round'] = 5 
            else: properties['round'] = ceil(num / 2) 

            # Track Logic: If Loser drops to ELIMINATED or if the match ID suggests LB (like G4, G6, G7)
            l_next = state[match_id]['config'].get('L_next')
            if l_next and 'ELIMINATED' in l_next:
                properties['track'] = 'LB'
            # Force G4, G6, G7 (LB) based on standard 5-team config
            if num in [4, 6, 7]: properties['track'] = 'LB'
            if num == 3 and isinstance(l_next, tuple) and l_next[0].startswith('G'): properties['track'] = 'WB' 
            
        match_properties[match_id] = properties
        
    # 2. Assign X-Coordinates (Round based)
    
    round_x_map = {} 
    current_x_u = 2
    
    # Calculate X for WB rounds
    all_rounds = sorted(list(set(p['round'] for p in match_properties.values() if p['round'] > 0)))
    for r in all_rounds:
        round_x_map[r] = current_x_u
        current_x_u += X_STEP_U
        
    # Assign Finals X
    GF_X_U = current_x_u
    GGF_X_U = current_x_u + X_STEP_U

    # 3. Assign Y-Coordinates (Stack based)
    
    wb_y_counts = {r: 0 for r in round_x_map}
    lb_y_counts = {r: 0 for r in round_x_map}
    
    for match_id in sorted_match_keys:
        props = match_properties.get(match_id)
        if not props or props['round'] == 0: continue
            
        r = props['round']
        track = props['track']
        
        if track == 'WB':
            x_u = round_x_map.get(r, 0)
            y_u = WB_START_Y_U + (Y_STEP_U * wb_y_counts.get(r, 0))
            wb_y_counts[r] = wb_y_counts.get(r, 0) + 1
            coords[match_id] = (x_u, y_u)
            
        elif track == 'LB':
            x_u = round_x_map.get(r, 0)
            y_u = LB_START_Y_U + (Y_STEP_U * lb_y_counts.get(r, 0))
            lb_y_counts[r] = lb_y_counts.get(r, 0) + 1
            
            # Adjust X for specific LB matches
            if match_id == 'G4' and 2 in round_x_map:
                 x_u = round_x_map[2]
            elif match_id == 'G6' and 3 in round_x_map:
                 x_u = round_x_map[3]
            elif match_id == 'G7' and 4 in round_x_map: 
                 x_u = round_x_map[4]
            
            coords[match_id] = (x_u, y_u)
            
        elif track == 'Finals':
            if match_id == 'GF':
                coords[match_id] = (GF_X_U, FINALS_Y_U)
            elif match_id == 'GGF':
                coords[match_id] = (GGF_X_U, FINALS_Y_U)

    # log_message(f"Calculated dynamic coordinates for {len(coords)} matches.") # ADDED LOGGING (Too verbose)
    return coords

# --- Dynamic Line Drawing (RETAINED) ---
def draw_angled_lines(canvas, state, coords, match_w, match_h, H_SCALE, V_SCALE, H_PAD, V_PAD):
    """
    Draws connecting lines using 45-degree angles ('Classic' style).
    - Uses a direct diagonal cut if horizontal space permits.
    - Falls back to chamfered (octagonal) routing if space is tight.
    """
    LINE_COLOR = '#BBBBBB' 
    LINE_WIDTH = 2
    CHAMFER_SIZE = 15 # Pixels for the corner cuts
    MIN_STRAIGHT = 15 # Minimum horizontal landing pad before the box

    # Helper: Convert Unit to Pixel
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
        
        # Start Point (Right side of source box)
        x1, y1 = box_center_right(match_id)
        if x1 is None: continue

        # Loop through destinations (Winner and Loser)
        for dest_key in ['W_next', 'L_next']:
            target = match_data['config'].get(dest_key)
            if not isinstance(target, tuple): continue 
                 
            next_match_id, slot = target
            
            if next_match_id in coords:
                x2, y2_center = box_in_left(next_match_id)
                if x2 is None: continue
                
                # Calculate Destination Y based on slot
                # Slot 0 = Top, Slot 1 = Bottom
                y2 = y2_center - (match_h / 4) if slot == 0 else y2_center + (match_h / 4)

                # --- 45-DEGREE LOGIC ---
                
                dx = x2 - x1
                dy = abs(y2 - y1)
                
                # Check 1: Is destination backwards? (Shouldn't happen in standard bracket)
                if dx <= 0:
                    # Fallback to direct line
                    canvas.create_line(x1, y1, x2, y2, fill=LINE_COLOR, width=LINE_WIDTH)
                    continue

                # Check 2: Do we have enough space for a "Perfect Diagonal"?
                # We need enough X to cover the Y drop + the landing pads
                required_dx = dy + (MIN_STRAIGHT * 1.5)
                
                if dx > required_dx:
                    # STYLE A: Direct Converging Diagonal
                    # Path: Horizontal -> 45deg Cut -> Horizontal Stub -> Box
                    
                    turn_point_x = x2 - dy - MIN_STRAIGHT
                    
                    points = [
                        x1, y1,                     # Start
                        turn_point_x, y1,           # Go Horizontal
                        x2 - MIN_STRAIGHT, y2,      # Cut Diagonal
                        x2, y2                      # Landing Stub
                    ]
                    canvas.create_line(points, fill=LINE_COLOR, width=LINE_WIDTH, capstyle='round')

                else:
                    # STYLE B: Chamfered Pipe (Octagonal)
                    # Used when the boxes are too far apart vertically relative to width
                    # Path: Horizontal -> Chamfer -> Vertical -> Chamfer -> Horizontal
                    
                    mid_x = x1 + (dx / 2)
                    
                    # Calculate safe chamfer size (don't exceed half the available space)
                    safe_chamfer = min(CHAMFER_SIZE, dx/2 - 2, dy/2 - 2)
                    if safe_chamfer < 2: safe_chamfer = 0 # Degrade to sharp corner if tiny
                    
                    # Direction of vertical travel
                    y_sign = 1 if y2 > y1 else -1
                    
                    points = [
                        x1, y1,                                      # Start
                        mid_x - safe_chamfer, y1,                    # Horizontal to Chamfer Start
                        mid_x, y1 + (safe_chamfer * y_sign),         # Diagonal to Vertical
                        mid_x, y2 - (safe_chamfer * y_sign),         # Vertical line
                        mid_x + safe_chamfer, y2,                    # Diagonal to Horizontal
                        x2, y2                                       # End
                    ]
                    canvas.create_line(points, fill=LINE_COLOR, width=LINE_WIDTH, capstyle='round')

def draw_dynamic_lines(canvas, state, coords, match_w, match_h, H_SCALE, V_SCALE, H_PAD, V_PAD):
    # ... (function body remains unchanged) ...
    """Draws all connection lines based on match configuration (W_next, L_next)."""
    
    LINE_COLOR = '#888888' 
    LINE_WIDTH = 2
    
    # Helper to convert Unit coordinates to Pixel coordinates and get key points
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
        # Ensure we only process match data (dictionaries)
        if not isinstance(match_data, dict) or 'config' not in match_data: continue

        if match_id not in coords: continue
        
        x1_out, y1_out = box_center(match_id)
        if x1_out is None: continue

        # Iterate over both Winner and Loser destinations
        for dest_key in ['W_next', 'L_next']:
            target = match_data['config'].get(dest_key)
            if not isinstance(target, tuple):
                 continue 
                 
            next_match_id, slot = target
            
            if next_match_id in coords:
                x2_in, y2_in = box_in(next_match_id)
                if x2_in is None: continue
                
                # Vertical offset for the slot (Top=0, Bottom=1)
                y2_offset = y2_in - (match_h / 4) if slot == 0 else y2_in + (match_h / 4)
                
                # Draw the line
                if x2_in > x1_out:
                    # Line moves horizontally and then vertically
                    mid_x = x1_out + (x2_in - x1_out) / 2
                    
                    # If the line travels across a great distance, make the horizontal section longer
                    if mid_x < x1_out + 10: mid_x = x1_out + 10 
                    if mid_x > x2_in - 10: mid_x = x2_in - 10

                    canvas.create_line(x1_out, y1_out, mid_x, y1_out, 
                                       mid_x, y2_offset, x2_in, y2_offset, 
                                       fill=LINE_COLOR, width=LINE_WIDTH, smooth=True)
                else: 
                     # For Finals reset line (GF -> GGF)
                     canvas.create_line(x1_out, y1_out, x2_in, y1_out, fill=LINE_COLOR, width=LINE_WIDTH)
    # log_message("Bracket connection lines drawn.") # ADDED LOGGING (Too verbose)

def on_full_bracket_close():
    """Resets global variables when the full bracket window is closed."""
    global full_bracket_root, full_bracket_canvas
    if full_bracket_root:
        full_bracket_root.destroy()
    full_bracket_root = None
    full_bracket_canvas = None

def draw_large_bracket(canvas):
    """
    Draws the bracket with FIXED scaling and 45-degree styled lines.
    """
    canvas.delete('all')
    
    # 1. Define Fixed Scale (Pixels per Unit)
    H_SCALE_PX = 14  
    V_SCALE_PX = 7  
    
    MATCH_W_U = 12   
    MATCH_H_U = 6    
    
    match_w = MATCH_W_U * H_SCALE_PX
    match_h = MATCH_H_U * V_SCALE_PX
    
    # 2. Get Coordinates
    match_coords = calculate_dynamic_coords(TOURNAMENT_STATE)
    if not match_coords: return

    # 3. Calculate Scroll Region
    max_x_u = 0
    max_y_u = 0
    for (mx, my) in match_coords.values():
        if mx > max_x_u: max_x_u = mx
        if my > max_y_u: max_y_u = my
        
    total_width = (max_x_u + MATCH_W_U + 5) * H_SCALE_PX
    total_height = (max_y_u + MATCH_H_U + 5) * V_SCALE_PX
    
    canvas.config(scrollregion=(0, 0, total_width, total_height))
    
    # 4. Helper for drawing
    H_PAD = 20
    V_PAD = 20
    
    def get_coords(match_id):
        if match_id not in match_coords: return 0, 0
        u_x, u_y = match_coords[match_id]
        x = u_x * H_SCALE_PX + H_PAD
        y = u_y * V_SCALE_PX + V_PAD
        return x, y

    # --- CHANGED: Use the new Angled Line Drawer ---
    draw_angled_lines(canvas, TOURNAMENT_STATE, match_coords, match_w, match_h, H_SCALE_PX, V_SCALE_PX, H_PAD, V_PAD)
    # -----------------------------------------------

    # 6. Draw Boxes (Same as before)
    font_team_size = 10
    font_roster_size = 8
    
    for match_id, match_data in TOURNAMENT_STATE.items():
        if not isinstance(match_data, dict) or 'teams' not in match_data: continue
        if match_id not in match_coords: continue
            
        x, y = get_coords(match_id)

        # Color Logic
        fill_color = 'white'
        if match_data.get('champion'): fill_color = 'gold'
        elif match_id == TOURNAMENT_STATE.get('active_match_id') and match_data['winner'] is None: fill_color = '#FFFFCC'
        elif match_data.get('winner_color') == 'red': fill_color = '#FFCCCC' 
        elif match_data.get('winner_color') == 'blue': fill_color = '#CCE5FF' 

        # Draw Box
        canvas.create_rectangle(x, y, x + match_w, y + match_h, fill=fill_color, outline='black', width=2)
        canvas.create_text(x + 5, y + 5, text=f"{match_id}", anchor='w', fill='#FFFFFF', font=('Arial', 8, 'bold'))

        # Draw Text
        if match_data['winner'] or match_data.get('champion'):
            winner_team = match_data.get('champion') or match_data['winner']
            roster = TEAM_ROSTERS.get(winner_team, ['?', '?'])
            roster_str = f"{roster[0]} / {roster[1]}"
            
            canvas.create_text(x + match_w/2, y + match_h/2 - 5, text=roster_str, font=('Arial', font_team_size, 'bold'))
            canvas.create_text(x + match_w/2, y + match_h/2 + 10, text=winner_team, font=('Arial', font_roster_size))
        else:
            # --- Team A Logic (Display Roster if Team Name is Known) ---
            tA = match_data['teams'][0]
            if tA and not tA.startswith('W:'): 
                # Team name is known. Display roster.
                roster_A = TEAM_ROSTERS.get(tA, ['?','?'])
                txt_A = f"{tA} ({roster_A[0]}/{roster_A[1]})"
            elif tA:
                # Placeholder like 'W:G1' or 'L:G2'. Display the match reference.
                txt_A = tA
            else:
                txt_A = "TBD"
                
            canvas.create_text(x + 5, y + match_h/4 + 5, text=txt_A, anchor='w', font=('Arial', font_roster_size))
            
            canvas.create_line(x, y + match_h/2, x + match_w, y + match_h/2, fill='#CCCCCC')
            
            # --- Team B Logic (Display Roster if Team Name is Known) ---
            tB = match_data['teams'][1]
            if tB and not tB.startswith('W:'):
                # Team name is known. Display roster.
                roster_B = TEAM_ROSTERS.get(tB, ['?','?'])
                txt_B = f"{tB} ({roster_B[0]}/{roster_B[1]})"
            elif tB:
                # Placeholder like 'W:G1' or 'L:G2'. Display the match reference.
                txt_B = tB
            else:
                txt_B = "TBD"
                
            canvas.create_text(x + 5, y + 3*match_h/4, text=txt_B, anchor='w', font=('Arial', font_roster_size))
            
def open_full_bracket():
    """Opens (or lifts) the large scrollable bracket window."""
    global full_bracket_root, full_bracket_canvas
    
    # If open, just bring to front
    if full_bracket_root is not None:
        try:
            full_bracket_root.lift()
            return
        except:
            full_bracket_root = None

    # Create Window
    full_bracket_root = tk.Toplevel(main_root)
    full_bracket_root.title("Full Tournament Bracket")
    full_bracket_root.geometry("1000x700")
    full_bracket_root.protocol("WM_DELETE_WINDOW", on_full_bracket_close)
    
    # Container for scrollbars
    container = tk.Frame(full_bracket_root)
    container.pack(fill='both', expand=True)
    
    # Scrollbars
    v_scroll = tk.Scrollbar(container, orient='vertical')
    h_scroll = tk.Scrollbar(container, orient='horizontal')
    
    # Canvas
    full_bracket_canvas = tk.Canvas(container, bg='#5E5E5E', 
                                    yscrollcommand=v_scroll.set, 
                                    xscrollcommand=h_scroll.set)
    
    v_scroll.config(command=full_bracket_canvas.yview)
    h_scroll.config(command=full_bracket_canvas.xview)
    
    # Grid Layout
    full_bracket_canvas.grid(row=0, column=0, sticky='nsew')
    v_scroll.grid(row=0, column=1, sticky='ns')
    h_scroll.grid(row=1, column=0, sticky='ew')
    
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)
    
    # Initial Draw
    draw_large_bracket(full_bracket_canvas)

def draw_bracket(canvas):
    # ... (function body remains unchanged) ...
    """
    Draws the visual bracket on the Canvas using dynamically calculated proportional 
    coordinates and dynamic line drawing.
    """
    global TEAM_ROSTERS
    canvas.delete('all')
    log_message("Redrawing main bracket.") # ADDED LOGGING
    
    canvas.update_idletasks()
    canvas_width = canvas.winfo_width()
    canvas_height = canvas.winfo_height()
    
    # --- 1. Determine Scale Factors and Dynamic Dimensions ---
    
    X_UNITS = 100 
    Y_UNITS = 100 
    MATCH_WIDTH_U = 12 
    MATCH_HEIGHT_U = 6 
    
    # Use a small padding percentage (2%) to keep elements off the edge
    H_PAD = 0.02 * canvas_width
    V_PAD = 0.02 * canvas_height
    
    effective_width = canvas_width - 2 * H_PAD
    effective_height = canvas_height - 2 * V_PAD
    
    # Scale based on the effective interior size
    H_SCALE = effective_width / X_UNITS
    V_SCALE = effective_height / Y_UNITS

    match_w = MATCH_WIDTH_U * H_SCALE
    match_h = MATCH_HEIGHT_U * V_SCALE
    
    # Define minimum box size to ensure readability
    MIN_MATCH_W, MIN_MATCH_H = 80, 30
    match_w = max(match_w, MIN_MATCH_W)
    match_h = max(match_h, MIN_MATCH_H)
    
    # --- 2. Calculate Dynamic Coordinates ---
    match_coords = calculate_dynamic_coords(TOURNAMENT_STATE)

    # Helper function to convert Unit coordinates to Pixel coordinates
    def get_coords(match_id):
        if match_id not in match_coords: return 0, 0
        u_x, u_y = match_coords[match_id]
        # Add H_PAD and V_PAD to shift from 0,0 to the padded start
        x = u_x * H_SCALE + H_PAD
        y = u_y * V_SCALE + V_PAD
        return x, y
        
    # --- 3. Line Drawing (Now Dynamic) ---
    draw_dynamic_lines(canvas, TOURNAMENT_STATE, match_coords, match_w, match_h, H_SCALE, V_SCALE, H_PAD, V_PAD)

    # --- 4. Draw Match Boxes and Text ---
    
    # Dynamic font sizes (Scaled based on match_h)
    font_id_size = max(5, int(match_h / 8))
    font_team_size = max(8, int(match_h / 5))
    font_roster_size = max(6, int(match_h / 8))
    
    for match_id, match_data in TOURNAMENT_STATE.items():
        # Ensure we only process match data (dictionaries)
        if not isinstance(match_data, dict) or 'teams' not in match_data:
             continue
            
        if not match_id.startswith('G') and match_id != 'GF' and match_id != 'GGF':
            continue
            
        if match_id not in match_coords:
            continue
            
        x, y = get_coords(match_id)

        fill_color = 'white'
        
        if match_id == TOURNAMENT_STATE.get('active_match_id') and match_data['winner'] is None:
            fill_color = 'light yellow'
        elif match_data.get('is_reset') and match_data.get('winner') is None:
             fill_color = 'orange'
        
        # Override fill color if a winner is declared
        if match_data.get('champion'):
             fill_color = 'gold'
        elif match_data.get('winner') is not None and match_data.get('winner_color') == 'red':
             fill_color = '#FFCCCC' 
        elif match_data.get('winner') is not None and match_data.get('winner_color') == 'blue':
             fill_color = '#CCE5FF' 
        
        canvas.create_rectangle(x, y, x + match_w, y + match_h, 
                                fill=fill_color, outline='black', width=2, tags=match_id)
        
        # Match ID
        canvas.create_text(x + 5, y + 5, text=f"{match_id}", anchor='w', fill='gray', font=('Arial', font_id_size))

        # Display winning team and players on two lines
        if match_data['winner'] or match_data.get('champion'):
            winner_team = match_data.get('champion') or match_data['winner']
            color = 'dark red' if match_data.get('champion') else 'dark green'
            
            roster = TEAM_ROSTERS.get(winner_team, ['P1', 'P2'])
            roster_str = f"({roster[0]} / {roster[1]})"
            
            # Team Name (Bold)
            canvas.create_text(x + match_w/2, y + match_h/2 - font_team_size/2, 
                               text=winner_team, fill=color, font=('Arial', font_team_size, 'bold'))
            # Player Names
            canvas.create_text(x + match_w/2, y + match_h/2 + font_roster_size*1.2, 
                               text=roster_str, fill=color, font=('Arial', font_roster_size))

        else:
            # --- Team A (Top slot) ---
            team_A = match_data['teams'][0]
            text_fill_color_A = 'black'
            if team_A:
                roster_A = TEAM_ROSTERS.get(team_A, ['P1', 'P2'])
                p_A_roster_str = f"({roster_A[0]} / {roster_A[1]})"
                text_A = f"{team_A} {p_A_roster_str}"
            else:
                text_A = 'TBD (Waiting for Winner/Loser)'
                text_fill_color_A = 'darkgrey'

            # Position A: Centered vertically in the top half
            canvas.create_text(x + 5, y + match_h/4 + 3, text=text_A, anchor='w', font=('Arial', font_roster_size), fill=text_fill_color_A)

            # Separator Line
            canvas.create_line(x + 5, y + match_h/2, x + match_w - 5, y + match_h/2, fill='#CCCCCC')

            # --- Team B (Bottom slot) ---
            team_B = match_data['teams'][1]
            text_fill_color_B = 'black'
            if team_B:
                roster_B = TEAM_ROSTERS.get(team_B, ['P3', 'P4'])
                p_B_roster_str = f"({roster_B[0]} / {roster_B[1]})"
                text_B = f"{team_B} {p_B_roster_str}"
            else:
                text_B = 'TBD (Waiting for Winner/Loser)'
                text_fill_color_B = 'darkgrey'
            
            # Position B: Centered vertically in the bottom half
            canvas.create_text(x + 5, y + 3*match_h/4 - 3, text=text_B, anchor='w', font=('Arial', font_roster_size), fill=text_fill_color_B)


# --- Utility to find the Next Active Match (RETAINED) ---

def find_next_active_match():
    # ... (function body remains unchanged) ...
    """Iterates through all match keys (in chronological order) to find the next ready-to-play match."""
    
    sorted_match_keys = sorted(
        [k for k in TOURNAMENT_STATE.keys() if k.startswith('G') or k == 'GF' or k == 'GGF'], 
        key=sort_match_keys
    )
    
    for k in sorted_match_keys:
        data = TOURNAMENT_STATE[k]
        
        if data['teams'][0] and data['teams'][1] and data['winner'] is None:
            log_message(f"Found next active match: {k} ({data['teams'][0]} vs {data['teams'][1]})") # ADDED LOGGING
            return k
    
    if sorted_match_keys:
        last_g_id = sorted_match_keys[-1]
        if TOURNAMENT_STATE[last_g_id].get('is_reset', False) and TOURNAMENT_STATE[last_g_id].get('winner') is None:
             log_message(f"Found next active match (Finals Reset): {last_g_id}") # ADDED LOGGING
             return last_g_id
         
    log_message("Tournament is over (or in final state check).") # ADDED LOGGING
    return 'TOURNAMENT_OVER'

# --- Match Setup & Resolution (RETAINED) ---

def handle_match_resolution(winner, loser, winning_color, match_id):
    # ... (function body remains unchanged) ...
    """
    Propagates the winner/loser of the *specific* completed match (match_id) 
    to the next games, with GF/GGF reset logic.
    """
    global current_match_res_buttons, TOURNAMENT_RANKINGS
    
    log_message(f"Resolving match {match_id}: Winner={winner} ({winning_color}), Loser={loser}") # ADDED LOGGING
    
    # Bug fix: Use the passed match_id instead of the active_match_id from global state
    if match_id == 'TOURNAMENT_OVER':
         # This should not happen with the fix, but as a safeguard:
         messagebox.showerror("Error", "Attempted to resolve 'TOURNAMENT_OVER' state.")
         TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
         reset_game(update_teams=True)
         log_message("Error: Attempted to resolve 'TOURNAMENT_OVER'. Resetting game state.") # ADDED LOGGING
         return
         
    match_data = TOURNAMENT_STATE.get(match_id)

    if not match_data or 'config' not in match_data:
        log_message(f"Error: Match {match_id} configuration data is missing or invalid.") # ADDED LOGGING
        messagebox.showerror("Error", f"Match {match_id} configuration data is missing or invalid.")
        # Try to recover by resetting to the next active match
        TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
        reset_game(update_teams=True)
        return
        
    match_config = match_data['config']
    
    if match_data.get('winner') is not None and not match_data.get('is_reset', False):
        log_message(f"Warning: Match {match_id} already resolved.") # ADDED LOGGING
        messagebox.showinfo("Error", f"Match {match_id} already resolved.")
        return
        
    match_data['winner'] = winner
    match_data['winner_color'] = winning_color 

    # 1. Handle Grand Finals Bracket Reset/Championship Win Logic (GF and GGF)
    if match_id == 'GF':
        # WB finalist is teams[0] in GF
        wb_finalist = match_data['teams'][0] 
        
        # Case 1: LB Winner (winner) defeats WB Winner (loser) in GF -> FORCES RESET
        if winner != wb_finalist and not match_data.get('is_reset', False): 
            match_data['is_reset'] = True 
            
            # Find the reset game (GGF)
            reset_game_id = next((k for k in TOURNAMENT_STATE if k == 'GGF' or k == 'GFF'), 'GGF')
            
            if reset_game_id in TOURNAMENT_STATE:
                # Set up GGF with the winner of GF (LB team) and the loser (WB team)
                TOURNAMENT_STATE[reset_game_id]['teams'] = [winner, loser]
                TOURNAMENT_STATE[reset_game_id]['is_reset'] = True
                
                # Clear the winner and winner_color of GF as the tournament is not over yet.
                match_data['winner'] = None 
                match_data['winner_color'] = None 
            
            # MODIFIED: Custom Finals Reset Message
            w_roster = "/".join(TEAM_ROSTERS.get(winner, ["P1", "P2"]))
            l_roster = "/".join(TEAM_ROSTERS.get(loser, ["P3", "P4"]))
            messagebox.showinfo("Final Round!", 
                                f"{w_roster} have defeated the previously undefeated team {l_roster}! So for the marbles...")
            
            TOURNAMENT_STATE['active_match_id'] = reset_game_id
            log_message(f"Match GF resulted in Bracket Reset. Next active match: {reset_game_id} ({winner} vs {loser})") # ADDED LOGGING
            
            # Since the bracket drawing is removed, we only need to call reset_game
            reset_game() 
            return # EXIT after reset handling

        # Case 2: WB Winner (winner) defeats LB Winner (loser) in GF -> TOURNAMENT OVER
        elif winner == wb_finalist:
            match_data['champion'] = winner
            TOURNAMENT_RANKINGS['1ST'] = winner
            TOURNAMENT_RANKINGS['2ND'] = loser
            TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
            log_message(f"Match GF: WB Winner {winner} wins Championship. 1ST={winner}, 2ND={loser}") # ADDED LOGGING
            reset_game() 
            return 

    elif match_id == 'GGF' or match_id == 'GFF':
        # Case 3: GGF is played -> TOURNAMENT OVER
        TOURNAMENT_STATE[match_id]['champion'] = winner
        TOURNAMENT_RANKINGS['1ST'] = winner
        # Loser is the other team in the match
        gfgf_loser = TOURNAMENT_STATE[match_id]['teams'][0] if winner == TOURNAMENT_STATE[match_id]['teams'][1] else TOURNAMENT_STATE[match_id]['teams'][1]
        TOURNAMENT_RANKINGS['2ND'] = gfgf_loser
        
        TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
        log_message(f"Match {match_id} (Reset) completed. 1ST={winner}, 2ND={gfgf_loser}. Tournament is over.") # ADDED LOGGING
        reset_game() 
        return 
        
    # --- Standard Propagation (For all non-final games that did not return above) ---

    # 2. Propagate Winner 
    w_target = match_config.get('W_next')
    if isinstance(w_target, tuple):
        next_match_id, slot = w_target
        if next_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[next_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[next_match_id]['teams'][slot] = winner
            log_message(f"Propagated Winner {winner} to {next_match_id} [Slot {slot}].") # ADDED LOGGING
    elif w_target == 'CHAMPION':
         match_data['champion'] = winner
         TOURNAMENT_RANKINGS['1ST'] = winner
         log_message(f"Match {match_id}: Winner {winner} is CHAMPION.") # ADDED LOGGING
    
    # 3. Propagate Loser and Assign Elimination Rank (MODIFIED)
    l_target = match_config.get('L_next')
    
    if isinstance(l_target, tuple):
        loser_match_id, slot = l_target
        if loser_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[loser_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[loser_match_id]['teams'][slot] = loser
            log_message(f"Propagated Loser {loser} to {loser_match_id} [Slot {slot}].") # ADDED LOGGING
    elif l_target and l_target.startswith('ELIMINATED'):
        # Assign Elimination Rank
        # Rank is extracted from the internal format 'ELIMINATED[RANK]'
        rank_match = re.search(r'\[(\w+)\]', l_target)
        if rank_match:
            rank = rank_match.group(1)
            # Only assign if the rank slot hasn't been filled yet
            if rank not in TOURNAMENT_RANKINGS:
                TOURNAMENT_RANKINGS[rank] = loser
                log_message(f"Assigned rank {rank} to eliminated team {loser}.") # ADDED LOGGING
        
    elif l_target and l_target.endswith('_CONDITIONAL'):
        # This is for GF, which is handled in the reset logic above.
        pass 

    # 4. Find the next actively playable match
    TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
    log_message(f"Standard Match Resolution complete. New active match: {TOURNAMENT_STATE['active_match_id']}") # ADDED LOGGING
    
    reset_game(update_teams=False) 


# --- Draw Small Bracket View (RETAINED) ---

def draw_small_bracket_view(canvas, state):
    """
    Draws a simplified view of the tournament bracket that scales to fit the window.
    MODIFIED: Finished matches now use the winning team's color (Red/Blue) instead of green.
    """
    canvas.delete('all')
    
    canvas.update_idletasks()
    W_canvas = canvas.winfo_width()
    H_canvas = canvas.winfo_height()
    
    if W_canvas < 50: W_canvas = 400
    if H_canvas < 50: H_canvas = 100

    sorted_match_keys = sorted(
        [k for k in state.keys() if k.startswith('G') or k == 'GF' or k == 'GGF'], 
        key=sort_match_keys
    )
    
    if not sorted_match_keys:
        return

    # --- 1. Categorize Matches ---
    wb_matches = []
    lb_matches = []
    final_matches = []

    for match_id in sorted_match_keys:
        match_data = state.get(match_id)
        
        if match_id in ['GF', 'GGF', 'GFF']:
            final_matches.append(match_id)
            continue
            
        l_next = match_data['config'].get('L_next')
        if isinstance(l_next, tuple):
            wb_matches.append(match_id)
        elif l_next and 'ELIMINATED' in str(l_next):
            lb_matches.append(match_id)
        else:
            wb_matches.append(match_id)

    # --- 2. Calculate Layout Metrics ---
    num_cols = max(len(wb_matches), len(lb_matches)) + len(final_matches)
    if num_cols < 1: num_cols = 1
    
    padding_x = 10
    available_w = W_canvas - (2 * padding_x)
    
    col_width = available_w / num_cols
    W_box = min(60, col_width - 5) 
    H_box = 20
    
    Y_TOP = H_canvas * 0.25
    Y_MID = H_canvas * 0.50
    Y_BOT = H_canvas * 0.75
    
    y_top_start = Y_TOP - (H_box / 2)
    y_mid_start = Y_MID - (H_box / 2)
    y_bot_start = Y_BOT - (H_box / 2)

    coords = {}
    
    # --- 3. Assign Coordinates ---
    for i, mid in enumerate(wb_matches):
        center_of_col = padding_x + (i * col_width) + (col_width / 2)
        x = center_of_col - (W_box / 2)
        coords[mid] = (x, y_top_start)
        
    for i, mid in enumerate(lb_matches):
        center_of_col = padding_x + (i * col_width) + (col_width / 2)
        x = center_of_col - (W_box / 2)
        coords[mid] = (x, y_bot_start)

    start_finals_col_idx = max(len(wb_matches), len(lb_matches))
    for i, mid in enumerate(final_matches):
        col_idx = start_finals_col_idx + i
        center_of_col = padding_x + (col_idx * col_width) + (col_width / 2)
        x = center_of_col - (W_box / 2)
        coords[mid] = (x, y_mid_start)

    # --- 4. Draw ---
    active_id = state.get('active_match_id')

    for match_id, (x, y) in coords.items():
        data = state.get(match_id)
        
        fill_color = 'white'
        outline_color = '#333333'
        text_color = 'black'
        
        if not isinstance(data, dict): continue 
            
        # --- COLOR LOGIC START ---
        if data and data.get('champion'):
            fill_color = 'gold'
            text_color = 'white'
        elif match_id == active_id and data and data.get('winner') is None:
            fill_color = 'yellow'
        elif data and data.get('is_reset', False) and data.get('winner') is None:
             fill_color = 'orange'
        elif data and data.get('winner') is not None:
             # CHANGED: Check winner_color instead of defaulting to lightgreen
             w_color = data.get('winner_color')
             if w_color == 'red':
                 fill_color = '#FF5555' # Red Button Color
             elif w_color == 'blue':
                 fill_color = '#55AAFF' # Blue Button Color
             else:
                 fill_color = 'lightgreen' # Fallback
        # --- COLOR LOGIC END ---
        
        canvas.create_rectangle(x, y, x + W_box, y + H_box, fill=fill_color, outline=outline_color)
        
        text_id = match_id.replace('G', '')
        canvas.create_text(x + W_box/2, y + H_box/2, text=text_id, font=('Arial', 7, 'bold'), fill=text_color)
                
# --- Helper Functions (RETAINED) ---

def format_destination(dest):
    # ... (function body remains unchanged) ...
    """Converts the parsed destination tuple/string into a user-readable string."""
    if dest == 'CHAMPION':
        return "🏆 CHAMPION"
    if isinstance(dest, tuple):
        match_id, slot = dest
        slot_name = "Top Slot (0)" if slot == 0 else "Bottom Slot (1)"
        return f"{match_id} [{slot_name}]"
    if isinstance(dest, str) and dest.endswith('_CONDITIONAL'):
        return f"Grand Finals Reset ({dest.split('_')[0]}R)"
    # Check if the destination is the ELIMINATED[n] format
    if dest and str(dest).upper().startswith('ELIMINATED['):
        return f"❌ {dest}"
    return str(dest)

# NEW: Utility to calculate a team's current win/loss record

def get_team_record(team_name):
    """Calculates the current wins and losses for a given team from TOURNAMENT_STATE."""
    wins = 0
    losses = 0
    for match_id, match_data in TOURNAMENT_STATE.items():
        if not isinstance(match_data, dict):
            continue
        
        winner = match_data.get('winner')
        
        # --- PATCH START: Handle GF Reset Case ---
        # If GF triggered a reset, the 'winner' field is cleared to None to reset the UI, 
        # but the game effectively happened. We deduce the winner by checking GGF Slot 0.
        if match_id == 'GF' and match_data.get('is_reset') and winner is None:
            ggf_data = TOURNAMENT_STATE.get('GGF') or TOURNAMENT_STATE.get('GFF')
            if ggf_data and ggf_data.get('teams'):
                 # In handle_match_resolution, the GF winner is explicitly placed in Slot 0 of GGF
                 winner = ggf_data['teams'][0]
        # --- PATCH END ---

        # Standard counting logic
        if winner:
            if team_name == winner:
                wins += 1
            elif team_name in match_data.get('teams', []) and team_name != winner:
                losses += 1
                
    return wins, losses
    
def update_winner_buttons():
    # ... (function body remains unchanged) ...
    """Updates the text on the winner buttons to show the assigned team names."""
    global btn_red, btn_blue, current_match_teams
    
    team_red = current_match_teams.get('red', 'RED TEAM')
    team_blue = current_match_teams.get('blue', 'BLUE TEAM')
    
    if btn_red and btn_blue:
        btn_red.config(text=f"WINNERS: {team_red} (RED)")
        btn_blue.config(text=f"WINNERS: {team_blue} (BLUE)")
    log_message(f"Updated winner buttons: Red={team_red}, Blue={team_blue}") # ADDED LOGGING

# ADDED: Swap function
def swap_teams():
    # ... (function body remains unchanged) ...
    """Swaps the Red and Blue teams in the current match UI."""
    global current_match_teams
    
    log_message(f"Swapping teams: {current_match_teams['red']} <-> {current_match_teams['blue']}") # ADDED LOGGING
    
    # Perform the swap
    temp = current_match_teams['red']
    current_match_teams['red'] = current_match_teams['blue']
    current_match_teams['blue'] = temp
    
    # Update the UI
    update_scoreboard_display()

def go_back_to_selection():
    # ... (function body remains unchanged) ...
    """Hides the confirmation frame and shows the winner selection frame."""
    global match_res_frame, match_input_frame, match_details_frame, current_match_res_buttons, switch_frame_ref
    
    log_message("Going back to winner selection screen.") # ADDED LOGGING
    
    match_res_frame.pack_forget()
    
    for widget in match_res_frame.winfo_children():
        widget.destroy()
    current_match_res_buttons.clear()
    
    # FIX: Add padding to pack call
    if switch_frame_ref: switch_frame_ref.pack(fill='x', padx=10, pady=(0, 5)) # REPACK SWITCH FRAME
    if match_details_frame: match_details_frame.pack(fill='x', padx=10, pady=5)
    match_input_frame.pack(fill='x', pady=5)
    
    team_red = current_match_teams['red']
    team_blue = current_match_teams['blue']
    match_id = TOURNAMENT_STATE['active_match_id']
    status_label.config(text=f"Active Match: {match_id} - {team_red} (RED) vs {team_blue} (BLUE)", fg='black')

def update_scoreboard_display():
    global team_labels, player_labels_ref, TOURNAMENT_STATE, scoreboard_canvas_ref, status_label, current_match_teams
    global game_routing_label, team_info_labels, bracket_info_canvas_ref

    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')
    
    if match_id == 'TOURNAMENT_OVER':
        # Handled by display_final_rankings
        return
        
    log_message(f"Updating scoreboard display for match: {match_id}") # ADDED LOGGING

    team_red = current_match_teams['red']
    team_blue = current_match_teams['blue']
    
    # FIX: Define roster_red and roster_blue *before* they are used in the canvas item config
    # This prevents the UnboundLocalError at startup.
    roster_red = " / ".join(TEAM_ROSTERS.get(team_red, ["P1", "P2"]))
    roster_blue = " / ".join(TEAM_ROSTERS.get(team_blue, ["P3", "P4"]))

    canvas = scoreboard_canvas_ref
    match_data = TOURNAMENT_STATE[match_id]
    match_config = match_data['config']
    
    # --- 1. Update Canvas Text (Team Name & Roster) ---
    
    # MODIFICATION 1: Show "P1 / P2" (roster_red) as the large team name.
    # The old large team name lines are removed.
    canvas.itemconfig(team_labels['red'], text=roster_red)
    canvas.itemconfig(team_labels['blue'], text=roster_blue)
    
    # MODIFICATION 1: Show "Team X" (team_red) as the small player name text.
    # The old small player name lines are removed.
    canvas.itemconfig(player_labels_ref['red'], text=team_red)
    canvas.itemconfig(player_labels_ref['blue'], text=team_blue)
    
    # --- 2. Update Match Details Frame ---
    
    w_next = format_destination(match_config.get('W_next'))
    l_next = format_destination(match_config.get('L_next'))
    
    # MODIFICATION 2: Calculate Wins/Losses
    wins_red, losses_red = get_team_record(team_red)
    wins_blue, losses_blue = get_team_record(team_blue)
    
    # The old team status logic (get_player_status call) is removed here.
    
    routing_text = (
        f"Game ID: {match_id}\n"
        f"Winner Advances To: {w_next}\n"
        f"Loser Drops To: {l_next}"
    )
    game_routing_label.config(text=routing_text)
    
    # MODIFICATION 2: Display Wins/Losses instead of Team Name/Players/Status
    # The old team_info_labels config lines are removed.
    team_info_labels['red'].config(text=f"Wins: {wins_red}\nLosses: {losses_red}")
    team_info_labels['blue'].config(text=f"Wins: {wins_blue}\nLosses: {losses_blue}")
    
    # --- 3. Update Status Label and Buttons ---
    status_label.config(text=f"Active Match: {match_id} - {team_red} (RED) vs {team_blue} (BLUE)", fg='black')
    update_winner_buttons()
    
    # --- 4. Draw Small Bracket View ---
    if bracket_info_canvas_ref:
        draw_small_bracket_view(bracket_info_canvas_ref, TOURNAMENT_STATE)

    # --- NEW: Refresh Big Board if open ---
    if full_bracket_root and full_bracket_canvas:
        try:
            draw_large_bracket(full_bracket_canvas)
        except Exception as e:
            log_message(f"Error updating full bracket: {e}")

def display_final_rankings(champion):
    # ... (function body remains unchanged) ...
    """
    FIXED: Manages packing of match detail frames to ensure the ranking label 
    is visible between the scoreboard and the Quit button.
    """
    global team_labels, player_labels_ref, scoreboard_canvas_ref, match_input_frame, match_details_frame, status_label
    global TOURNAMENT_RANKINGS, main_root, rankings_label_ref, bracket_info_frame_ref, team_info_frame_ref, switch_frame_ref
    global final_control_frame_ref, rankings_display_frame_ref
    
    log_message(f"Displaying final rankings. Champion: {champion}") # ADDED LOGGING
    
    # Clear active match UI elements
    match_input_frame.pack_forget()
    if switch_frame_ref:
        switch_frame_ref.pack_forget() 
    
    # HIDE match-in-progress frames
    if match_details_frame: 
        match_details_frame.pack_forget()
    
    # Ensure the ranking display frame is visible and takes its place
    if rankings_display_frame_ref:
        rankings_display_frame_ref.pack(fill='both', expand=True, padx=10, pady=5)
        
    status_label.config(text=f"TOURNAMENT OVER! Champion: {champion}", font=('Arial', 14, 'bold'), fg='dark green')
    
    # --- 1. Update Scoreboard Canvas for 1ST/2ND Place ---
    
    # Get 1st and 2nd place
    first_place = TOURNAMENT_RANKINGS.get('1ST', 'N/A')
    second_place = TOURNAMENT_RANKINGS.get('2ND', 'N/A')
    
    first_team_num = first_place.split(' ')[1] if 'Team' in first_place else ''
    second_team_num = second_place.split(' ')[1] if 'Team' in second_place else ''
    
    first_roster = " / ".join(TEAM_ROSTERS.get(first_place, ["P1", "P2"]))
    second_roster = " / ".join(TEAM_ROSTERS.get(second_place, ["P3", "P4"]))

    canvas = scoreboard_canvas_ref
    canvas.delete('all')
    
    center_x = canvas.winfo_width() / 2
    name_x_1st, name_x_2nd = center_x - 110, center_x + 110
    
    canvas.create_line(center_x, 5, center_x, 95, fill='#CCCCCC', width=1)
    
    # 1ST PLACE (Left)
    canvas.create_text(name_x_1st, 15, text=f"1ST PLACE (Team {first_team_num})", fill='gold', font=('Arial', 9, 'bold'))
    canvas.create_text(name_x_1st, 40, text=f"{first_roster}", font=('Arial', 16, 'bold'), fill='gold')
    #canvas.create_text(name_x_1st, 70, text=f"${prizes.get('1st', 0)}", font=('Arial', 9), width=200)

    # 2ND PLACE (Right)
    canvas.create_text(name_x_2nd, 15, text=f"2ND PLACE (Team {second_team_num})", fill='#333333', font=('Arial', 9, 'bold'))
    canvas.create_text(name_x_2nd, 40, text=f"{second_roster}", font=('Arial', 16, 'bold'), fill='#333333')
    #canvas.create_text(name_x_2nd, 70, text=f"${prizes.get('2nd', 0)}", font=('Arial', 9), width=200)

    # --- 2. Display Remaining Rankings ---
    
    rankings_text = "--- Remaining Tournament Rankings ---\n\n"
    
    # Get sorted ranks (excluding 1ST and 2ND, then sorting by the rank number/string)
    def rank_sort_key(rank_str):
        # Converts rank string (e.g., '3RD', '5TH') to an integer for sorting
        if rank_str == '1ST' or rank_str == '2ND':
            return 0 # Put them first, though they are excluded later
        # Correctly capture the digits from ordinal strings (e.g., '3RD' -> 3)
        match = re.match(r'(\d+)', rank_str)
        if match:
            return int(match.group(1))
        return float('inf')
        
    sorted_ranks = sorted(TOURNAMENT_RANKINGS.keys(), key=rank_sort_key)
    
    for rank in sorted_ranks:
        if rank not in ['1ST', '2ND']:
            team = TOURNAMENT_RANKINGS[rank]
            team_num = team.split(' ')[1] if 'Team' in team else ''
            roster = " / ".join(TEAM_ROSTERS.get(team, ["TBD", "TBD"]))
            # Show the rank, Team name, and players
            rankings_text += f"{rank} Place: {team} ({roster})\n"
            
    log_message(f"Final Rankings: {dict(TOURNAMENT_RANKINGS)}") # ADDED LOGGING
            
    # Update the rankings label which is now inside its own frame
    if rankings_label_ref:
        rankings_label_ref.config(text=rankings_text, justify=tk.LEFT, fg='black', bg='#F0F0F0', font=('Arial', 10, 'bold'))
    
    # --- 3. Add Quit Button (Ensuring only one is ever created/packed) ---
    
    # Clear any previous content in the final control frame
    for widget in final_control_frame_ref.winfo_children():
        widget.destroy()
        
    final_control_frame_ref.pack(fill='x', pady=10)
    
    quit_btn = tk.Button(final_control_frame_ref, text="QUIT", command=lambda: on_close(main_root), 
                         bg='#D32F2F', fg='white', font=('Arial', 12, 'bold'), height=2)
    quit_btn.pack(padx=10, pady=10, fill='x')

def reset_game(update_teams=True):
    """Resets the game state (only updating teams now)."""
    log_message("Resetting game UI.") # ADDED LOGGING
    if update_teams:
        load_match_data_and_teams()

def update_roster_seeding_display():
    """Updates the Team Roster & Seeding information box."""
    global roster_seeding_frame_ref, TEAMS, TEAM_ROSTERS

    if not roster_seeding_frame_ref or not TEAMS:
        return

    log_message("Updating Team Roster & Seeding display.")

    # Clear existing widgets
    for widget in roster_seeding_frame_ref.winfo_children():
        widget.destroy()

    # Create the roster list string
    roster_text = "Seeding | Team Name | Players\n"
    roster_text += "--------|-----------|---------\n"
    for i, team_name in enumerate(TEAMS):
        roster = TEAM_ROSTERS.get(team_name, ["N/A", "N/A"])
        roster_text += f"T{i+1:<6}| {team_name:<9} | {roster[0]} / {roster[1]}\n"

    tk.Label(roster_seeding_frame_ref, text=roster_text, justify=tk.LEFT, font=('Courier', 10), bg='#EEEEEE').pack(fill='x', padx=5, pady=(0, 5))

def update_roster_seeding_display():
    """Updates the Team Roster & Seeding information box with a horizontal, player-focused view."""
    global roster_seeding_frame_ref, TEAMS, TEAM_ROSTERS

    if not roster_seeding_frame_ref or not TEAMS:
        return

    log_message("Updating Team Roster & Seeding display (horizontal).")

    # Clear existing widgets
    for widget in roster_seeding_frame_ref.winfo_children():
        widget.destroy()

    # Inner frame to hold all team blocks and pack them horizontally (side=tk.LEFT)
    teams_inner_frame = tk.Frame(roster_seeding_frame_ref, bg='#EEEEEE')
    teams_inner_frame.pack(side='top', padx=5, pady=(0, 5))

    for team_name in TEAMS:
        roster = TEAM_ROSTERS.get(team_name, ["N/A", "N/A"])
        players_str = f"{roster[0]} / {roster[1]}"
        
        # Team container frame, packs horizontally
        team_container = tk.Frame(teams_inner_frame, bg='#DDDDDD', bd=1, relief=tk.RIDGE)
        team_container.pack(side=tk.LEFT, padx=5, pady=2) 
        
        # Label combining team name and players, e.g., "Team Alpha: P1 / P2"
        tk.Label(team_container, text=f"{team_name}: {players_str}", font=('Courier', 9), 
                 bg='#DDDDDD', fg='black').pack(padx=5, pady=2)

def setup_scoreboard(root, team_red_placeholder, team_blue_placeholder):
    """Initializes the scoreboard canvas and widgets with the new UI."""
    global scoreboard_canvas_ref, team_labels, player_labels_ref, status_label, match_input_frame, match_res_frame, btn_red, btn_blue, roster_seeding_frame_ref
    global match_details_frame, game_routing_label, team_info_labels, bracket_info_canvas_ref, rankings_label_ref, btn_switch, bracket_info_frame_ref, team_info_frame_ref
    global switch_frame_ref, final_control_frame_ref, rankings_display_frame_ref
    
    log_message("Initializing scoreboard and UI components.") 
    
    header_frame = tk.Frame(root, bg='#333333')
    header_frame.pack(fill='x')
    
    header_label = tk.Label(header_frame, text="Current Match Resolution", font=('Arial', 14, 'bold'), fg='white', bg='#333333', pady=5)
    header_label.pack(fill='x')
    
    status_label = tk.Label(root, text="Tournament Initialized.", font=('Arial', 10, 'bold'), pady=5, bd=1, relief='sunken')
    status_label.pack(fill='x')
    
    # --- Scoreboard Canvas ---
    scoreboard_canvas_ref = tk.Canvas(root, width=450, height=100, bg='white', highlightthickness=0)
    scoreboard_canvas_ref.pack(fill='x', padx=10, pady=5)

    # 1. Outer Frame: Holds the scrollbar and canvas for ROSTER
    roster_outer_frame = tk.Frame(root, padx=10, pady=2, bd=1, relief=tk.GROOVE, bg='#EEEEEE')
    roster_outer_frame.pack(fill='x', padx=10, pady=2) 

    # 2. Scrollbar: For horizontal scrolling (ROSTER ONLY)
    h_scrollbar = tk.Scrollbar(roster_outer_frame, orient=tk.HORIZONTAL)
    h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

    # 3. Canvas: Hosts the content (roster_seeding_frame_ref)
    roster_canvas_ref = tk.Canvas(roster_outer_frame, bg='#666666', height=35, xscrollcommand=h_scrollbar.set, highlightthickness=0)
    roster_canvas_ref.pack(side=tk.TOP, fill=tk.X, expand=True)

    h_scrollbar.config(command=roster_canvas_ref.xview)

    # 4. Inner Frame: This is the frame the rest of the code needs to target
    roster_seeding_frame_ref = tk.Frame(roster_canvas_ref, bg='#EEEEEE')
    roster_canvas_ref.create_window((0, 0), window=roster_seeding_frame_ref, anchor="nw")
    roster_seeding_frame_ref.bind("<Configure>", lambda e: roster_canvas_ref.configure(scrollregion=roster_canvas_ref.bbox("all")))
    
    # Initial content update for the roster/seeding frame
    update_roster_seeding_display()

    # --- Main Scoreboard Text Items ---
    match_details_frame = tk.Frame(root, padx=10, pady=5, bd=1, relief=tk.SUNKEN)
    match_details_frame.pack(fill='x', padx=10, pady=5)
    
    center_x = 225
    name_x_red, name_x_blue = 110, 340 
    
    scoreboard_canvas_ref.create_line(center_x, 5, center_x, 95, fill='#CCCCCC', width=1)
    
    team_labels['red'] = scoreboard_canvas_ref.create_text(name_x_red, 40, text=f"{team_red_placeholder}", font=('Arial', 16, 'bold'), fill='#CC0000')
    player_labels_ref['red'] = scoreboard_canvas_ref.create_text(name_x_red, 70, text="Team X / (P1, P2)", font=('Arial', 9), width=200)

    team_labels['blue'] = scoreboard_canvas_ref.create_text(name_x_blue, 40, text=f"{team_blue_placeholder}", font=('Arial', 16, 'bold'), fill='#0066CC')
    player_labels_ref['blue'] = scoreboard_canvas_ref.create_text(name_x_blue, 70, text="Team Y / (P3, P4)", font=('Arial', 9), width=200)

    # Switch Button Frame
    switch_frame_ref = tk.Frame(root) 
    
    # 1. Switch Button (Left side, takes 50%)
    btn_switch = tk.Button(switch_frame_ref, text="SWITCH RED/BLUE", command=swap_teams, 
                           bg='#EEEEEE', fg='black', font=('Arial', 10), height=1)
    btn_switch.pack(side=tk.LEFT, fill='x', expand=True, padx=(0, 2))
    
    # 2. Full Bracket Button (Right side, takes 50%)
    btn_bracket = tk.Button(switch_frame_ref, text="FULL BRACKET", command=open_full_bracket,
                            bg='#DDDDDD', fg='black', font=('Arial', 10, 'bold'), height=1)
    btn_bracket.pack(side=tk.LEFT, fill='x', expand=True, padx=(2, 0))    
    # Match Details Frame (Contains routing/bracket/team info)
    match_details_frame = tk.Frame(root, padx=10, pady=5)
    
    # ADDED: Store bracket info frame reference
    bracket_info_frame = tk.Frame(match_details_frame, bd=1, relief='sunken')
    bracket_info_frame.pack(fill='x', pady=(0, 5))
    bracket_info_frame_ref = bracket_info_frame 
    
    # --- MODIFIED: Dynamic Fit Mini Bracket (No Scrollbar) ---
    # Increased height to 80 to fit two rows comfortable
    # bind <Configure> to trigger redraw on resize if needed, though currently logic is redraw-on-update
    bracket_info_canvas = tk.Canvas(bracket_info_frame, height=80, bg='white')
    bracket_info_canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    
    # Bind resize event to redraw bracket so it stays fitted
    bracket_info_canvas.bind("<Configure>", lambda event: draw_small_bracket_view(bracket_info_canvas, TOURNAMENT_STATE))

    bracket_info_canvas_ref = bracket_info_canvas 
    # ---------------------------------------------------------
    
    # Rankings Display
    rankings_display_frame_ref = tk.Frame(root, padx=10, pady=5, bd=1, relief='solid', bg='#F0F0F0')
    
    # Routing Label
    game_routing_label = tk.Label(match_details_frame, text="Game ID: G#\nWinner Advances To: TBD\nLoser Drops To: TBD", 
                                  justify=tk.LEFT, font=('Arial', 9), bd=1, relief='solid', padx=5, pady=5, bg='#f0f0f0')
    game_routing_label.pack(fill='x', pady=(0, 5))
    
    # Rankings Label
    rankings_label_ref = tk.Label(rankings_display_frame_ref, 
                                  text="--- Remaining Tournament Rankings ---", 
                                  justify=tk.LEFT, fg='black', bg='#F0F0F0', font=('Arial', 10, 'bold'), padx=5, pady=5)
    rankings_label_ref.pack(fill='both', expand=True)
    
    # Team Info Frame
    team_info_frame = tk.Frame(match_details_frame)
    team_info_frame.pack(fill='x')
    team_info_frame_ref = team_info_frame
    
    team_info_labels['red'] = tk.Label(team_info_frame, text="Team: Team X\nPlayers: P1, P2 (Active)", 
                                       justify=tk.LEFT, font=('Arial', 9), fg='#CC0000')
    team_info_labels['red'].pack(side=tk.LEFT, expand=True, padx=5)
    
    team_info_labels['blue'] = tk.Label(team_info_frame, text="Team: Team Y\nPlayers: P3, P4 (Active)", 
                                        justify=tk.LEFT, font=('Arial', 9), fg='#0066CC')
    team_info_labels['blue'].pack(side=tk.LEFT, expand=True, padx=5)
    
    # Match Input Frame (Winner Buttons)
    match_input_frame = tk.Frame(root, padx=10, pady=5)

    # Match Input Frame (Winner Buttons ONLY)
    match_input_frame = tk.Frame(root, padx=10, pady=5)

    btn_red = tk.Button(match_input_frame, text="RED TEAM WINS", command=lambda: declare_winner('red'), bg='#FF5555', fg='black', font=('Arial', 12, 'bold'), height=2)
    # The winner buttons now expand equally and fill the space
    btn_red.pack(side=tk.LEFT, expand=True, padx=(5, 5), pady=0)
    
    btn_blue = tk.Button(match_input_frame, text="BLUE TEAM WINS", command=lambda: declare_winner('blue'), bg='#55AAFF', fg='black', font=('Arial', 12, 'bold'), height=2)
    # The winner buttons now expand equally and fill the space
    btn_blue.pack(side=tk.LEFT, expand=True, padx=(5, 5), pady=0)

    match_res_frame = tk.Frame(root, bg='#eeeeee', padx=10, pady=10)
    
    final_control_frame_ref = tk.Frame(root)
    
    load_match_data_and_teams()
        
def setup_main_gui(root):
    # ... (function body remains unchanged) ...
    """Sets up the main windows and calls component initialization. MODIFIED for single window."""
    global main_root
    main_root = root
    # MODIFIED: Renamed window title
    root.title("Moose Lodge Shuffleboard (large_bracket)")
    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root)) 
    
    root.geometry("470x500") 

    g1_teams = TOURNAMENT_STATE.get('G1', {}).get('teams', ["Team Red", "Team Blue"])
    team_A = g1_teams[0] or "Team Red"
    team_B = g1_teams[1] or "Team Blue"
    
    log_message(f"Setting up main GUI for teams: {team_A} vs {team_B}") # ADDED LOGGING
    
    # MODIFIED: Scoreboard setup is now for the main root window
    setup_scoreboard(root, team_A, team_B) 

def show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes):
    """Displays the player draw, team rosters, and prize pool before launching the main GUI."""
    summary_root = tk.Tk()
    summary_root.title("Tournament Draw & Prize Pool")
    summary_root.protocol("WM_DELETE_WINDOW", lambda: on_close(summary_root)) 
    
    log_message("Displaying Draw Summary and Prize Pool.") # ADDED LOGGING
    
    # --- Draw Results ---
    draw_frame = tk.Frame(summary_root, padx=10, pady=10, bd=2, relief=tk.GROOVE)
    draw_frame.pack(fill='x', padx=10, pady=5)
    tk.Label(draw_frame, text="*** Player Draw Results ***", font=('Arial', 12, 'bold')).pack(pady=5)
    draw_text = ""
    for draw_num, player_name in player_draws:
        draw_text += f"Draw #{draw_num}: {player_name}\n"
    tk.Label(draw_frame, text=draw_text, justify=tk.LEFT, font=('Courier', 10)).pack()
    
    # --- Team Roster Summary ---
    team_frame = tk.Frame(summary_root, padx=10, pady=10, bd=2, relief=tk.GROOVE)
    team_frame.pack(fill='x', padx=10, pady=5)
    tk.Label(team_frame, text="*** Team Roster & Seeding ***", font=('Arial', 12, 'bold')).pack(pady=5)
    team_text = ""
    for i, team_name in enumerate(TEAMS):
        roster = TEAM_ROSTERS.get(team_name, ["N/A", "N/A"])
        # T1, T2 etc. corresponds to team_name "Team 1", "Team 2" etc.
        team_text += f"Team {i+1} (T{i+1}): {roster[0]} / {roster[1]}\n"
    tk.Label(team_frame, text=team_text, justify=tk.LEFT, font=('Courier', 10)).pack()
    
    # --- Prize Pool Summary (PATCHED FOR FORMAT) ---
    prize_frame = tk.Frame(summary_root, padx=10, pady=10, bd=2, relief=tk.GROOVE)
    prize_frame.pack(fill='x', padx=10, pady=5)
    tk.Label(prize_frame, text="*** Prize Pool Calculation ***", font=('Arial', 12, 'bold')).pack(pady=5)
    
    # Calculate per-player prizes
    per_player_1st = int(prizes.get('1st', 0) / 2)
    per_player_2nd = int(prizes.get('2nd', 0) / 2)
    
    # Display format: Total Pool and then Nth Place Prize: $TOTAL ($PER_PLAYER per player)
    prize_text = f"Total Pool: ${total_pool}\n"
    prize_text += f"1st Place Prize: ${prizes.get('1st', 0)} (${per_player_1st} per player)\n"
    prize_text += f"2nd Place Prize: ${prizes.get('2nd', 0)} (${per_player_2nd} per player)\n"
    
    # Ensure 3rd place is shown if it exists in the prize dictionary, even if 0
    if prizes.get('3rd') is not None:
        per_player_3rd = int(prizes.get('3rd', 0) / 2)
        prize_text += f"3rd Place Prize: ${prizes.get('3rd', 0)} (${per_player_3rd} per player)\n"
        
    tk.Label(prize_frame, text=prize_text, justify=tk.LEFT, font=('Courier', 10)).pack()
    
    # --- Confirmation Button ---
    start_button = tk.Button(summary_root, text="BEGIN TOURNAMENT", 
                             command=summary_root.quit, 
                             bg='#4CAF50', fg='white', font=('Arial', 12, 'bold'), height=2)
    start_button.pack(fill='x', padx=10, pady=10)
    
    summary_root.mainloop() # Blocks execution until button is pressed
    summary_root.destroy()
    log_message("Draw Summary window closed. Proceeding to main GUI.") # ADDED LOGGING
    return

def generate_dynamic_bracket(teams, config=None):
    """
    Loads the bracket structure from the config file, initializes TOURNAMENT_STATE,
    and seeds the starting matches with teams (T1, T2, etc.).
    """
    global TOURNAMENT_STATE
    TOURNAMENT_STATE.clear()

    num_teams = len(teams)
    log_message(f"Generating bracket for {num_teams} teams.") # ADDED LOGGING
    
    if config is None:
        try:
            # Load config and discard the prize data (which is already used)
            config, _ = load_bracket_config(num_teams, 'D') 
        except Exception as e:
            messagebox.showerror("Configuration Error", str(e))
            return
        
    # 1. Initialize TOURNAMENT_STATE based on parsed configuration
    for match_id, match_config in config.items():
        # Store configuration for reference
        TOURNAMENT_STATE[match_id] = {
            'config': {
                'W_next': match_config['W_next'],
                'L_next': match_config['L_next'],
            },
            'teams': [None, None], # Teams are TBD initially
            'winner': None,
            'winner_color': None,
            'is_reset': False
        }
        
    # 2. Seed the starting teams into the correct matches
    for match_id, match_data in config.items():
        if match_id.startswith('G'):
            # The config specifies which teams (T1, T2, T3, etc.) play in the match
            for i in range(2):
                team_slot_id = match_data['teams'][i]
                
                # Check if the slot is a team placeholder (T1, T2, T3, etc.)
                match_t_id = re.match(r'T(\d+)', team_slot_id)
                
                if match_t_id:
                    t_num = int(match_t_id.group(1)) - 1 # T1 is index 0
                    if t_num < len(teams):
                        # Assign the actual team name based on the draw/seeding
                        TOURNAMENT_STATE[match_id]['teams'][i] = teams[t_num]
                        log_message(f"Seeded {teams[t_num]} into {match_id} [Slot {i}].") # ADDED LOGGING
                    else:
                        TOURNAMENT_STATE[match_id]['teams'][i] = None 

    # 3. Set initial active match
    initial_active_match = find_next_active_match()
    TOURNAMENT_STATE['active_match_id'] = initial_active_match
    log_message(f"Bracket generation complete. Initial active match: {initial_active_match}") # ADDED LOGGING

# --- Logging File Management ---
def toggle_log_game(log_var):
    """Toggles file logging based on checkbox state and manages the log file."""
    global LOG_GAME_TO_FILE, LOG_FILE_HANDLE
    
    LOG_GAME_TO_FILE = log_var.get()
    
    if LOG_GAME_TO_FILE:
        # Ensure logs directory exists
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # Format: logs/shuffleboard_$(date +%Y-%m-%d_%H-%M-%S).log
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = os.path.join(log_dir, f"shuffleboard_{timestamp}.log")
        
        try:
            # Open with line buffering (buffering=1) for immediate write
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

def get_multi_line_input(parent, title, prompt, num_required):
    """
    Custom function for individual player input boxes using a Toplevel dialog.
    MODIFIED: Uses a standard tk.Frame instead of a scrollable Canvas,
    and forces layout update after initial draw to fix the bug.
    """
    log_message(f"Opening player input dialog for {num_required} players.") # ADDED LOGGING
    
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    # Increased height to accommodate max players (20) without scrollbar
    dialog.geometry("550x850") 
    dialog.grab_set() 
    
    # result will be a tuple: (is_manual_draw, list_of_player_data)
    result = None 
    is_manual_draw = tk.BooleanVar(value=False)
    log_game_var = tk.BooleanVar(value=LOG_GAME_TO_FILE)
    
    # List to store references to the Entry widgets
    player_entries = [] 

    tk.Label(dialog, text=prompt, pady=5, justify=tk.LEFT).pack(padx=10, anchor='w')
    
    # --- Auto/Manual Draw Control Frame ---
    control_frame = tk.Frame(dialog)
    control_frame.pack(padx=10, pady=5, fill='x')
    
    # Forward declaration for the drawing function
    def toggle_draw_wrapper():
        log_message(f"Toggling draw mode. Manual Draw: {is_manual_draw.get()}") # ADDED LOGGING
        # Redraw the widgets in the simple frame
        draw_input_widgets(is_manual_draw.get(), num_required, input_container, player_entries)

    # Checkbox for Manual Draw
    check_manual = tk.Checkbutton(control_frame, text="Manual Draw (Assign Draw #)", variable=is_manual_draw, 
                                  command=toggle_draw_wrapper)
    check_manual.pack(side='left', padx=(0, 20))
    # ADDED: Log Game Checkbox
    check_log = tk.Checkbutton(control_frame, text="Log Game", variable=log_game_var, command=lambda: toggle_log_game(log_game_var))
    check_log.pack(side='right', padx=(20, 0))    
    # --- Input Container (Simple Frame) ---
    input_container = tk.Frame(dialog)
    # Use fill='both' and expand=True to let it use the available space
    input_container.pack(side='top', fill='both', expand=True, padx=10, pady=5)
    
    # --- Internal function to draw/redraw the widgets ---
    def draw_input_widgets(manual_mode, req, container, entries_list):
        # 1. Clear previous widgets and list
        for widget in container.winfo_children():
            widget.destroy()
        entries_list.clear()

        # Add instructions based on mode
        if manual_mode:
            tk.Label(container, text=f"** Draw Numbers must be unique and between 1 and {req} **", 
                     fg='darkred', font=('Arial', 9, 'bold')).pack(pady=(5, 0), anchor='w', padx=5)
        else:
             tk.Label(container, text=f"** Enter Player Names. Draw numbers will be assigned automatically **", 
                     fg='blue', font=('Arial', 9, 'bold')).pack(pady=(5, 0), anchor='w', padx=5)
            
        # 2. Draw new widgets
        for i in range(req):
            frame = tk.Frame(container)
            frame.pack(fill='x', padx=5, pady=2)
            
            player_num = i + 1
            
            # Common Label
            tk.Label(frame, text=f"Player {player_num} Name:", width=15, anchor='w').pack(side='left')

            if manual_mode:
                # Manual: Draw Entry + Name Entry
                
                # Draw Number Entry (Width 5 for 3-4 digits/chars + padding)
                draw_entry = tk.Entry(frame, width=5, justify='center', font=('Arial', 10, 'bold')) 
                draw_entry.pack(side='left', padx=(0, 5))
                
                tk.Label(frame, text="|").pack(side='left', padx=(0, 5))
                
                # Name Entry (Shorter)
                name_entry = tk.Entry(frame, width=30)
                name_entry.pack(side='left', fill='x', expand=True)
                
                entries_list.append((draw_entry, name_entry))
                
                # Pre-fill example
                draw_entry.insert(0, str(player_num))
                name_entry.insert(0, f"Player {player_num}")
                
            else:
                # Auto: Only Name Entry (Full width)
                name_entry = tk.Entry(frame)
                name_entry.pack(side='left', fill='x', expand=True)
                entries_list.append((name_entry,))
                name_entry.insert(0, f"Player {player_num}")
        
        # Ensure the new widgets are rendered for correct sizing
        container.update_idletasks()

    # --- ON OK Function ---
    def on_ok():
        nonlocal result
        player_data_list = []
        is_manual = is_manual_draw.get()
        num_inputs = len(player_entries)
        
        log_message(f"OK button pressed. Manual Draw: {is_manual}. Validating input.") # ADDED LOGGING
        
        if num_inputs != num_required:
             messagebox.showerror("Internal Error", "Widget count mismatch. Cannot proceed.")
             return
             
        if is_manual:
            assigned_draws = set()
            for i, (draw_entry, name_entry) in enumerate(player_entries):
                raw_draw_num = draw_entry.get().strip()
                player_name = name_entry.get().strip()
                
                if not raw_draw_num or not player_name:
                     messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Both Draw # and Player Name must be filled.")
                     log_message(f"Input Error: Missing data on line {i+1} (Manual Draw).") # ADDED LOGGING
                     return
                     
                try:
                    draw_num = int(raw_draw_num)
                except ValueError:
                    messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Draw number '{raw_draw_num}' is not a valid integer.")
                    log_message(f"Input Error: Invalid draw number '{raw_draw_num}' on line {i+1}.") # ADDED LOGGING
                    return
                
                if draw_num < 1 or draw_num > num_required:
                    messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Draw number {draw_num} is out of range (1-{num_required}).")
                    log_message(f"Input Error: Draw number {draw_num} out of range on line {i+1}.") # ADDED LOGGING
                    return
                if draw_num in assigned_draws:
                    messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Draw number {draw_num} is assigned multiple times.")
                    log_message(f"Input Error: Duplicate draw number {draw_num} on line {i+1}.") # ADDED LOGGING
                    return
                    
                assigned_draws.add(draw_num)
                player_data_list.append((draw_num, player_name))
                
            # Final check for missing draws
            if len(assigned_draws) != num_required:
                missing_draws = [i for i in range(1, num_required + 1) if i not in assigned_draws]
                messagebox.showerror("Input Error", f"Manual Draw Error: The following draw numbers are missing: {', '.join(map(str, missing_draws))}")
                log_message(f"Input Error: Missing draw numbers {missing_draws}.") # ADDED LOGGING
                return

        else: # Auto Draw
            for i, (name_entry,) in enumerate(player_entries):
                player_name = name_entry.get().strip()
                if not player_name:
                    messagebox.showerror("Input Error", f"Auto Draw Error (Line {i+1}): Player Name must be filled.")
                    log_message(f"Input Error: Missing player name on line {i+1} (Auto Draw).") # ADDED LOGGING
                    return
                # Draw_num is None for auto draw
                player_data_list.append((None, player_name)) 
                
        result = (is_manual, player_data_list)
        log_message("Player input successfully validated.") # ADDED LOGGING
        dialog.destroy()

    def on_cancel():
        nonlocal result
        # ADDED: If the user cancels setup, ensure file logging is stopped and handle is closed
        if LOG_GAME_TO_FILE:
             # Force logging off, cleaning up the file handle (passing False)
             toggle_log_game(tk.BooleanVar(value=False))
             
        dialog.destroy()

    # --- Initial draw and Button setup ---
    draw_input_widgets(is_manual_draw.get(), num_required, input_container, player_entries)

    # FIX: Force the dialog to update its layout properties after the initial draw.
    # This prevents the initial incomplete rendering bug.
    dialog.update_idletasks() 
    
    button_frame = tk.Frame(dialog)
    button_frame.pack(fill='x', padx=10, pady=10)
    
    ok_button = tk.Button(button_frame, text="OK", command=on_ok, bg='#4CAF50', fg='white', font=('Arial', 10, 'bold'))
    ok_button.pack(side='left')
    
    cancel_button = tk.Button(button_frame, text="Cancel", command=on_cancel)
    cancel_button.pack(side='right')
    
    dialog.wait_window()
    return result

def start_tournament():
    """Prompts for players, sets up teams, generates the bracket, and launches the GUI. MODIFIED for file-driven prizes and new draw logic."""
    
    log_message("Starting tournament initialization process.") # ADDED LOGGING
    
    # Use a temporary root window for dialogs
    dialog_root = tk.Tk()
    dialog_root.withdraw() # Hide the main window
    
    num_players = None
    while num_players is None:
        try:
            num_players = simpledialog.askinteger("Player Setup", 
                                                f"Enter the total number of players ({MIN_PLAYERS}-{MAX_PLAYERS}):",
                                                minvalue=MIN_PLAYERS, maxvalue=MAX_PLAYERS, parent=dialog_root)
            if num_players is None: 
                dialog_root.destroy()
                log_message("Tournament setup canceled at player count prompt.") # ADDED LOGGING
                return
            if num_players % 2 != 0:
                messagebox.showerror("Error", "The total number of players must be even!")
                num_players = None # Loop again
                log_message(f"Input Error: Player count {num_players} is odd.") # ADDED LOGGING
                continue
            break
        except Exception:
            pass
    log_message(f"Total number of players set to: {num_players}") # ADDED LOGGING

    # --- MODIFIED: Use the new return format from get_multi_line_input ---
    player_input_result = None
    while player_input_result is None:
        player_input_result = get_multi_line_input(dialog_root, "Player Names & Draw Input", 
                                            f"Enter the names and choose the draw method for {num_players} players:",
                                            num_players)
        if player_input_result is None:
            dialog_root.destroy()
            log_message("Tournament setup canceled at player input stage.") # ADDED LOGGING
            return
        
    dialog_root.destroy() # Close the temporary dialog root

    is_manual_draw, player_data_list = player_input_result
    log_message(f"Player data received. Manual Draw: {is_manual_draw}") # ADDED LOGGING

    # --- 1. Process Draw and Team Setup ---
    
    global TEAMS, TEAM_ROSTERS
    TEAMS.clear()
    TEAM_ROSTERS.clear()
    
    if is_manual_draw:
        # Player data is already (draw_num, player_name), just sort by draw number
        player_draws = sorted(player_data_list, key=lambda x: x[0]) 
    else:
        # Player data is (None, player_name), assign random draw numbers
        player_names = [data[1] for data in player_data_list]
        draw_numbers = list(range(1, num_players + 1))
        random.shuffle(draw_numbers)
        
        player_draws = []
        for player_name in player_names:
            draw_num = draw_numbers.pop()
            player_draws.append((draw_num, player_name))
        
        player_draws.sort(key=lambda x: x[0]) 
        log_message(f"Auto-draw complete. {num_players} players drawn.") # ADDED LOGGING
    
    num_teams = num_players // 2
    for i in range(num_teams):
        team_name = f'Team {i+1}'
        player1 = player_draws[i*2][1]
        player2 = player_draws[i*2 + 1][1]
        
        TEAMS.append(team_name)
        TEAM_ROSTERS[team_name] = [player1, player2]
        log_message(f"Created team {team_name}: {player1} / {player2} (Draws #{player_draws[i*2][0]} & #{player_draws[i*2+1][0]})") # ADDED LOGGING
        
    # --- 2. Load Bracket Config and Prizes (Unchanged) ---
    
    try:
        # Load config and get the file prizes
        config, prizes_from_file = load_bracket_config(num_teams, 'D')
    except Exception as e:
        messagebox.showerror("Configuration Error", str(e))
        return

    # Use prizes read from file, calculating the total pool from them
    prizes = prizes_from_file
    
    # Ensure all prize ranks exist, defaulting to 0 if missing from the file
    prizes['1st'] = prizes.get('1st', 0)
    prizes['2nd'] = prizes.get('2nd', 0)
    prizes['3rd'] = prizes.get('3rd', 0)
    
    # Calculate Total Pool by summing the prizes read from the file
    total_pool = prizes['1st'] + prizes['2nd'] + prizes['3rd']
    log_message(f"Loaded prizes: {prizes}. Total Pool: ${total_pool}") # ADDED LOGGING
        
    # --- 3. Show Draw Summary (Unchanged) ---
    show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes)
    
    # --- 4. Generate Bracket and Launch Main Game (Unchanged) ---
    generate_dynamic_bracket(TEAMS, config)
    
    if not TOURNAMENT_STATE:
        log_message("Error: TOURNAMENT_STATE is empty after generation.") # ADDED LOGGING
        return

    root = tk.Tk()
    
    try:
        setup_main_gui(root)
        root.mainloop()
    except KeyboardInterrupt:
        on_close(root)

def declare_winner(color):
    # ... (function body remains unchanged) ...
    """Handles the conclusion of a match by declaring the winner based on button click."""
    global TOURNAMENT_STATE, match_res_frame, match_input_frame, current_match_teams, match_details_frame, switch_frame_ref
    
    # BUG FIX: Capture the ID of the match that *just* finished before showing the confirmation UI.
    match_id_to_confirm = TOURNAMENT_STATE['active_match_id']

    winner = current_match_teams[color]
    loser = current_match_teams['blue'] if color == 'red' else current_match_teams['red']
    
    log_message(f"Winner declared for {match_id_to_confirm}: {winner} ({color}). Waiting for confirmation.") # ADDED LOGGING

    match_input_frame.pack_forget()
    if switch_frame_ref: switch_frame_ref.pack_forget() # HIDE SWITCH BUTTON
    match_details_frame.pack_forget() 

    match_res_frame.pack(fill='x', padx=10, pady=10) 
    
    status_label.config(text=f"MATCH {match_id_to_confirm} ENDED: **{winner}** wins. Please **CONFIRM** or **GO BACK** to re-select winner.", fg='darkred')
    
    global current_match_res_buttons
    for widget in match_res_frame.winfo_children():
        widget.destroy()
    current_match_res_buttons.clear()
    
    # Pass winning color and the specific match ID to the confirm function
    confirm_btn = tk.Button(match_res_frame, text=f"CONFIRM: {winner} won and advance bracket", bg='#4CAF50', fg='white', 
                            font=('Arial', 11, 'bold'),
                            command=lambda w=winner, l=loser, c=color, mid=match_id_to_confirm: confirm_match_resolution(w, l, c, mid))
    confirm_btn.pack(pady=5, fill='x')
    current_match_res_buttons.append(confirm_btn)
    
    go_back_btn = tk.Button(match_res_frame, text="GO BACK: Mistake made in winner selection", bg='#F44336', fg='white', 
                            font=('Arial', 10),
                            command=go_back_to_selection)
    go_back_btn.pack(pady=5, fill='x')
    current_match_res_buttons.append(go_back_btn)

def confirm_match_resolution(winner, loser, winning_color, match_id):
    # ... (function body remains unchanged) ...
    """Processes the confirmed match result and updates the tournament state."""
    global match_res_frame, current_match_res_buttons

    log_message(f"Confirmation received for match {match_id}. Processing result...") # ADDED LOGGING

    # BUG FIX: Call handle_match_resolution with the confirmed match_id
    handle_match_resolution(winner, loser, winning_color, match_id)

    match_res_frame.pack_forget()
    current_match_res_buttons = []

    # Reset game will now load the new active match ID found in handle_match_resolution
    reset_game()
    
def load_match_data_and_teams():
    # ... (function body remains unchanged) ...
    """
    Loads the match data for the current active match, assigns default colors (if new match),
    and triggers the UI update.
    """
    global TOURNAMENT_STATE, match_input_frame, current_match_teams, last_assigned_match_id, match_details_frame
    global bracket_info_frame_ref, team_info_frame_ref, rankings_label_ref, switch_frame_ref, final_control_frame_ref, rankings_display_frame_ref
    
    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')
    log_message(f"Loading match data for new active match: {match_id}") # ADDED LOGGING
    
    # Hide final control frame and ranking frame if they were shown
    if final_control_frame_ref:
        final_control_frame_ref.pack_forget()
    if rankings_display_frame_ref:
        rankings_display_frame_ref.pack_forget()
    
    if match_id == 'TOURNAMENT_OVER':
        # --- Handle Tournament Over UI ---
        champion = None
        for data in TOURNAMENT_STATE.values():
            if isinstance(data, dict) and data.get('champion'):
                champion = data['champion']
                break
        
        if champion:
             display_final_rankings(champion) # New function call
        else:
            status_label.config(text=f"TOURNAMENT OVER! No champion declared. (Error State)", fg='dark red')
            log_message("Error State: TOURNAMENT_OVER with no champion declared.") # ADDED LOGGING
            
        match_input_frame.pack_forget()
        if match_details_frame: match_details_frame.pack_forget()
        if switch_frame_ref: switch_frame_ref.pack_forget()
        return

    # --- Standard Match UI Setup ---
    
    # NEW: Pack switch frame first
    # FIX: Added padding to pack call
    if switch_frame_ref: 
        switch_frame_ref.pack(fill='x', padx=10, pady=(0, 5))

    # Ensure relevant frames are visible again for the next match
    if match_details_frame: 
        match_details_frame.pack(fill='x', padx=10, pady=(5, 0))
        
    match_input_frame.pack(fill='x', pady=(0, 5))


    if match_id != last_assigned_match_id:
        
        match_data = TOURNAMENT_STATE[match_id]
        team_A = match_data['teams'][0] 
        team_B = match_data['teams'][1] 
        
        current_match_teams['red'] = team_A
        current_match_teams['blue'] = team_B
        
        last_assigned_match_id = match_id
        log_message(f"New match {match_id} loaded. Red={team_A}, Blue={team_B}.") # ADDED LOGGING
    
    update_scoreboard_display()


# --- Main Program Entry Point (MODIFIED) ---

if __name__ == '__main__':
    
    log_message("Script starting.") # ADDED LOGGING
    
    # Ensure the 'data' directory exists for configuration files
    if not os.path.exists('data'):
        os.makedirs('data')
        log_message("Created 'data' directory.") # ADDED LOGGING
        
    show_title_screen()
    # start_tournament handles creating and destroying the necessary Tk instances now
    start_tournament()

    log_message("Script finished execution.") # ADDED LOGGING
