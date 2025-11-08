#!/usr/bin/env python3

import tkinter as tk
from tkinter import messagebox, simpledialog
from math import log2, ceil
import sys
import re 
import random 
import os 
from collections import OrderedDict

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
    try:
        if root:
            root.quit()
            root.destroy()
        if main_root:
            main_root.quit()
            main_root.destroy()
    except:
        pass 
    sys.exit(0) 


# --- Winnings Calculation (Retained for fallback only) ---

def calculate_winnings(num_teams):
    """Calculates prize pool and payouts based on team count, ensuring whole dollars."""
    PAYOUT_SPLIT_3_TEAMS = {'1st': 0.70, '2st': 0.30, '3rd': 0.00}
    PAYOUT_SPLIT_4_PLUS = {'1st': 0.50, '2st': 0.30, '3rd': 0.20}
    
    total_pool = num_teams * 2 * ENTRY_FEE_PER_PERSON
    
    if num_teams == 3:
        payouts = PAYOUT_SPLIT_3_TEAMS
    else:
        payouts = PAYOUT_SPLIT_4_PLUS
        
    prizes = {}
    remaining_pool = total_pool
    
    prizes['1st'] = int(total_pool * payouts['1st'])
    prizes['2st'] = int(total_pool * payouts['2st'])
    
    if num_teams >= 4:
        # Calculate 3rd place prize using remaining pool to ensure whole dollar remainder
        prizes['3rd'] = remaining_pool - prizes['1st'] - prizes['2st']
    else:
        prizes['3rd'] = 0
        
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

# --- Bracket Configuration and Parsing Functions (MODIFIED to read PRIZES) ---

def _parse_destination(dest_str):
    """Parses destination strings into the required tuple/string format."""
    dest_str = dest_str.strip()
    
    # Now only looking for G-numbers, GF, and GGF
    match = re.search(r'(G\d+|GF|GGF)\s*\[Slot:\s*(\d+|N/A)\]', dest_str) 
    if match:
        match_id, slot_str = match.groups()
        
        if slot_str.isdigit():
            return (match_id, int(slot_str))
        if match_id.startswith('G') and slot_str == 'N/A':
             return f'{match_id}_CONDITIONAL' 
        return (match_id, 0) 

    if 'CHAMPION' in dest_str:
        return 'CHAMPION'
        
    # FIX: Use regex to correctly look for 'ELIMINATED (nTH)' format in the config files
    elim_match = re.search(r'ELIMINATED\s*\((.+?)\)', dest_str, re.IGNORECASE)
    if elim_match:
        # Extract the rank part (e.g., '5th'), convert to uppercase ('5TH'), and format as ELIMINATED[RANK]
        rank_part = elim_match.group(1).upper().replace('.', '').strip()
        return f'ELIMINATED[{rank_part}]'
        
    if dest_str.endswith('_CONDITIONAL'):
        return dest_str
        
    return dest_str

def _parse_config_file_content(content):
    """Parses the text content of the [N]teamD.game file into a Python dictionary, including PRIZES."""
    config = {}
    current_match_id = None
    prizes = {}  # Dictionary to store prizes
    
    is_parsing_prizes = False # State flag for prize parsing
    
    # Pre-clean the content to handle varying whitespace before processing
    content = re.sub(r'\r', '', content) # Remove carriage returns
    lines = [line.strip() for line in content.split('\n')]
    
    for line in lines:
        line = line.strip()
        
        # 1. Parse PRIZES block
        if line.startswith('PRIZES:'):
            is_parsing_prizes = True
            continue
            
        if is_parsing_prizes:
            # Match line with format '  3: 20' or '3: 20'
            prize_match = re.match(r'(\d+):\s*(\d+)', line)
            if prize_match:
                rank = prize_match.group(1) # '1', '2', '3'
                amount = int(prize_match.group(2))
                
                # Store prizes in the format used by show_draw_summary ('1st', '2st', '3rd')
                if rank == '1':
                    prizes['1st'] = amount
                elif rank == '2':
                    prizes['2st'] = amount
                elif rank == '3':
                    prizes['3rd'] = amount
                continue
            
            # Stop prize parsing if a blank line or a match header is encountered
            if not line or re.match(r'(G\d+|GF|GGF)\s*\(.+\):', line):
                 is_parsing_prizes = False
                 
        if is_parsing_prizes:
            continue
            
        # 2. Parse Match Configuration
        match_header = re.match(r'(G\d+|GF|GGF)\s*\(.+\):', line) 
        if match_header:
            current_match_id = match_header.group(1)
            
            config[current_match_id] = {'config': {}}
            continue
            
        if not current_match_id:
            continue
            
        if line.startswith('Teams:'):
            teams_str = line.split(':', 1)[1].strip()
            # This extracts T1, T2, W-G1, L-G2, etc.
            teams = [t.strip().replace('(', '').replace(')', '').split(' ')[0] for t in teams_str.split(',')]
            config[current_match_id]['teams'] = teams
            
        elif line.startswith('Winner_Advances_To:'):
            dest_str = line.split(':', 1)[1].strip()
            config[current_match_id]['config']['W_next'] = _parse_destination(dest_str)
            
        elif line.startswith('Loser_Drops_To:'):
            dest_str = line.split(':', 1)[1].strip()
            config[current_match_id]['config']['L_next'] = _parse_destination(dest_str)

    final_config = {}
    for match_id, data in config.items():
         if 'teams' in data:
              final_config[match_id] = {
                   'teams': data['teams'],
                   'W_next': data['config'].get('W_next'),
                   'L_next': data['config'].get('L_next')
              }
    # Return the prize dictionary as well
    return final_config, prizes

# --- Dynamic Config Loading (MODIFIED to return prizes) ---
def load_bracket_config(num_teams, elimination_type='D'):
    """
    Reads the bracket configuration from a local .game file.
    Returns: (config_dict, prizes_dict)
    """
    
    if num_teams == 3:
         filename = '3teamD.game'
    elif num_teams == 4:
         filename = '4teamD.game'  
    elif num_teams == 5:
         filename = '5teamD.game'
    elif num_teams == 6:
         filename = '6teamD.game'
    elif num_teams == 10:
         filename = '10teamD.game'
    else:
        # Fallback for other standard sizes that match the naming convention
        if num_teams >= 7 and num_teams <= 16:
            filename = f'{num_teams}team{elimination_type}.game'
        else:
             raise ValueError(f"No configuration file defined or available for {num_teams} teams.")

    filepath = filename 
        
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        return _parse_config_file_content(content) # Returns (config, prizes)
        
    except FileNotFoundError:
        filepath = os.path.join('data', filename) 
        try:
             with open(filepath, 'r') as f:
                 content = f.read()
             return _parse_config_file_content(content) # Returns (config, prizes)
        except FileNotFoundError:
             raise FileNotFoundError(f"Configuration file not found. Please ensure the file '{filename}' is placed in the same folder or a sub-folder named 'data' next to 'sb.py'.")
    except Exception as e:
        raise ValueError(f"Error reading or parsing configuration file '{filepath}': {e}")


# --- Dynamic Coordinate Generation (RETAINED) ---

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

    return coords

# --- Dynamic Line Drawing (RETAINED) ---

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

# --- Draw Bracket Function (RETAINED) ---
    
def draw_bracket(canvas):
    # ... (function body remains unchanged) ...
    """
    Draws the visual bracket on the Canvas using dynamically calculated proportional 
    coordinates and dynamic line drawing.
    """
    global TEAM_ROSTERS
    canvas.delete('all')
    
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
            return k
    
    if sorted_match_keys:
        last_g_id = sorted_match_keys[-1]
        if TOURNAMENT_STATE[last_g_id].get('is_reset', False) and TOURNAMENT_STATE[last_g_id].get('winner') is None:
             return last_g_id
         
    return 'TOURNAMENT_OVER'

# --- Match Setup & Resolution (RETAINED) ---

def handle_match_resolution(winner, loser, winning_color, match_id):
    # ... (function body remains unchanged) ...
    """
    Propagates the winner/loser of the *specific* completed match (match_id) 
    to the next games, with GF/GGF reset logic.
    """
    global current_match_res_buttons, TOURNAMENT_RANKINGS
    
    # Bug fix: Use the passed match_id instead of the active_match_id from global state
    if match_id == 'TOURNAMENT_OVER':
         # This should not happen with the fix, but as a safeguard:
         messagebox.showerror("Error", "Attempted to resolve 'TOURNAMENT_OVER' state.")
         TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
         reset_game(update_teams=True)
         return
         
    match_data = TOURNAMENT_STATE.get(match_id)

    if not match_data or 'config' not in match_data:
        messagebox.showerror("Error", f"Match {match_id} configuration data is missing or invalid.")
        # Try to recover by resetting to the next active match
        TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
        reset_game(update_teams=True)
        return
        
    match_config = match_data['config']
    
    if match_data.get('winner') is not None and not match_data.get('is_reset', False):
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
            
            # Since the bracket drawing is removed, we only need to call reset_game
            reset_game() 
            return # EXIT after reset handling

        # Case 2: WB Winner (winner) defeats LB Winner (loser) in GF -> TOURNAMENT OVER
        elif winner == wb_finalist:
            match_data['champion'] = winner
            TOURNAMENT_RANKINGS['1ST'] = winner
            TOURNAMENT_RANKINGS['2ND'] = loser
            TOURNAMENT_STATE['active_match_id'] = 'TOURNAMENT_OVER'
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
        reset_game() 
        return 
        
    # --- Standard Propagation (For all non-final games that did not return above) ---

    # 2. Propagate Winner 
    w_target = match_config.get('W_next')
    if isinstance(w_target, tuple):
        next_match_id, slot = w_target
        if next_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[next_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[next_match_id]['teams'][slot] = winner
    elif w_target == 'CHAMPION':
         match_data['champion'] = winner
         TOURNAMENT_RANKINGS['1ST'] = winner
    
    # 3. Propagate Loser and Assign Elimination Rank (MODIFIED)
    l_target = match_config.get('L_next')
    
    if isinstance(l_target, tuple):
        loser_match_id, slot = l_target
        if loser_match_id in TOURNAMENT_STATE and TOURNAMENT_STATE[loser_match_id]['teams'][slot] is None:
            TOURNAMENT_STATE[loser_match_id]['teams'][slot] = loser
    elif l_target and l_target.startswith('ELIMINATED'):
        # Assign Elimination Rank
        # Rank is extracted from the internal format 'ELIMINATED[RANK]'
        rank_match = re.search(r'\[(\w+)\]', l_target)
        if rank_match:
            rank = rank_match.group(1)
            # Only assign if the rank slot hasn't been filled yet
            if rank not in TOURNAMENT_RANKINGS:
                TOURNAMENT_RANKINGS[rank] = loser
        
    elif l_target and l_target.endswith('_CONDITIONAL'):
        # This is for GF, which is handled in the reset logic above.
        pass 

    # 4. Find the next actively playable match
    TOURNAMENT_STATE['active_match_id'] = find_next_active_match()
    
    reset_game(update_teams=False) 


# --- Draw Small Bracket View (RETAINED) ---

def draw_small_bracket_view(canvas, state):
    # ... (function body remains unchanged) ...
    """Draws a simplified view of the tournament bracket, highlighting the active match."""
    canvas.delete('all')
    
    canvas.update_idletasks()
    W_canvas = canvas.winfo_width()
    H_canvas = canvas.winfo_height()
    
    # Calculate a simple proportional layout for boxes only
    sorted_match_keys = sorted(
        [k for k in state.keys() if k.startswith('G') or k == 'GF' or k == 'GGF'], 
        key=sort_match_keys
    )
    
    num_matches = len(sorted_match_keys)
    if num_matches == 0:
        return

    # Simplified fixed coordinates for the small view (not dynamic, only visual flow)
    W_box, H_box = 20, 15 
    
    # Create simple, evenly spaced columns and rows
    # Max columns should be dynamic based on the bracket size, let's keep it simple for a small view
    num_cols = min(7, num_matches)
    col_spacing = (W_canvas - 20) / max(1, num_cols - 1)
    
    SX, SY = 5, 5
    
    coords = {}
    current_col = 0
    
    # Heuristic to place GF/GGF in the last column
    final_keys = [k for k in sorted_match_keys if k in ['GF', 'GGF', 'GFF']]
    non_final_keys = [k for k in sorted_match_keys if k not in final_keys]
    
    # Simple columnar layout for non-finals
    for i, match_id in enumerate(non_final_keys):
         # Group matches into columns 
         col_index = i // 2
         coords[match_id] = (SX + col_index * col_spacing, SY + (i % 2) * 2 * H_box)
         current_col = max(current_col, col_index)

    # Place finals in the next column
    final_x = SX + (current_col + 1) * col_spacing
    for i, match_id in enumerate(final_keys):
         coords[match_id] = (final_x + i * col_spacing, SY + H_canvas/2 - H_box)

    active_id = state.get('active_match_id')

    for match_id, (x, y) in coords.items():
        data = state.get(match_id)
        
        fill_color = 'white'
        outline_color = '#333333'
        text_color = 'black'
        
        # Ensure 'data' is a dictionary
        if not isinstance(data, dict):
            continue 
            
        if data and data.get('champion'):
            fill_color = 'gold'
            text_color = 'white'
        elif match_id == active_id and data and data.get('winner') is None:
            fill_color = 'yellow'
        elif data and data.get('is_reset', False) and data.get('winner') is None:
             fill_color = 'orange'
        elif data and data.get('winner') is not None:
             fill_color = 'lightgreen'
        
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

def update_winner_buttons():
    # ... (function body remains unchanged) ...
    """Updates the text on the winner buttons to show the assigned team names."""
    global btn_red, btn_blue, current_match_teams
    
    team_red = current_match_teams.get('red', 'RED TEAM')
    team_blue = current_match_teams.get('blue', 'BLUE TEAM')
    
    if btn_red and btn_blue:
        btn_red.config(text=f"WINNERS: {team_red} (RED)")
        btn_blue.config(text=f"WINNERS: {team_blue} (BLUE)")

# ADDED: Swap function
def swap_teams():
    # ... (function body remains unchanged) ...
    """Swaps the Red and Blue teams in the current match UI."""
    global current_match_teams
    
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
    # ... (function body remains unchanged) ...
    """Updates all visual elements on the scoreboard based on current_match_teams and routing."""
    global team_labels, player_labels_ref, TOURNAMENT_STATE, scoreboard_canvas_ref, status_label, current_match_teams
    global game_routing_label, team_info_labels, bracket_info_canvas_ref

    match_id = TOURNAMENT_STATE.get('active_match_id', 'TOURNAMENT_OVER')
    
    if match_id == 'TOURNAMENT_OVER':
        # Handled by display_final_rankings
        return

    team_red = current_match_teams['red']
    team_blue = current_match_teams['blue']

    canvas = scoreboard_canvas_ref
    match_data = TOURNAMENT_STATE[match_id]
    match_config = match_data['config']
    
    # --- 1. Update Canvas Text (Team Name & Roster) ---
    canvas.itemconfig(team_labels['red'], text=f"{team_red}")
    canvas.itemconfig(team_labels['blue'], text=f"{team_blue}")
    
    roster_red = " / ".join(TEAM_ROSTERS.get(team_red, ["TBD", "TBD"]))
    roster_blue = " / ".join(TEAM_ROSTERS.get(team_blue, ["TBD", "TBD"]))

    # MODIFIED: Update players with team number
    canvas.itemconfig(player_labels_ref['red'], text=f"Team {team_red.split(' ')[1]} / ({roster_red})")
    canvas.itemconfig(player_labels_ref['blue'], text=f"Team {team_blue.split(' ')[1]} / ({roster_blue})")
    
    # --- 2. Update Match Details Frame ---
    
    w_next = format_destination(match_config.get('W_next'))
    l_next = format_destination(match_config.get('L_next'))
    
    def get_player_status(team_name):
        # Find the rank associated with the team
        for rank, team in TOURNAMENT_RANKINGS.items():
            if team == team_name:
                return f"({rank} Place)"
        return "(Active)"
        
    team_red_status = get_player_status(team_red)
    team_blue_status = get_player_status(team_blue)
    
    routing_text = (
        f"Game ID: {match_id}\n"
        f"Winner Advances To: {w_next}\n"
        f"Loser Drops To: {l_next}"
    )
    game_routing_label.config(text=routing_text)
    
    # MODIFIED: Display Team Name and Players with team number and status
    team_info_labels['red'].config(text=f"Team: {team_red}\nPlayers: {roster_red} {team_red_status}")
    team_info_labels['blue'].config(text=f"Team: {team_blue}\nPlayers: {roster_blue} {team_blue_status}")
    
    # --- 3. Update Status Label and Buttons ---
    status_label.config(text=f"Active Match: {match_id} - {team_red} (RED) vs {team_blue} (BLUE)", fg='black')
    update_winner_buttons() 
    
    # --- 4. Draw Small Bracket View ---
    if bracket_info_canvas_ref:
        draw_small_bracket_view(bracket_info_canvas_ref, TOURNAMENT_STATE)

def display_final_rankings(champion):
    # ... (function body remains unchanged) ...
    """
    FIXED: Manages packing of match detail frames to ensure the ranking label 
    is visible between the scoreboard and the Quit button.
    """
    global team_labels, player_labels_ref, scoreboard_canvas_ref, match_input_frame, match_details_frame, status_label
    global TOURNAMENT_RANKINGS, main_root, rankings_label_ref, bracket_info_frame_ref, team_info_frame_ref, switch_frame_ref
    global final_control_frame_ref, rankings_display_frame_ref
    
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
            
    # Update the rankings label which is now inside its own frame
    if rankings_label_ref:
        rankings_label_ref.config(text=rankings_text, justify=tk.LEFT, fg='black', bg='#F0F0F0', font=('Arial', 10, 'bold'))
    
    # --- 3. Add Quit Button (Ensuring only one is ever created/packed) ---
    
    # Clear any previous content in the final control frame
    for widget in final_control_frame_ref.winfo_children():
        widget.destroy()
        
    final_control_frame_ref.pack(fill='x', pady=10)
    
    quit_btn = tk.Button(final_control_frame_ref, text="QUIT SCRIPT", command=lambda: on_close(main_root), 
                         bg='#D32F2F', fg='white', font=('Arial', 12, 'bold'), height=2)
    quit_btn.pack(padx=10, pady=10, fill='x')

def reset_game(update_teams=True):
    """Resets the game state (only updating teams now)."""
    if update_teams:
        load_match_data_and_teams()

def setup_scoreboard(root, team_red_placeholder, team_blue_placeholder):
    # ... (function body remains unchanged) ...
    """Initializes the scoreboard canvas and widgets with the new UI."""
    global scoreboard_canvas_ref, team_labels, player_labels_ref, status_label, match_input_frame, match_res_frame, btn_red, btn_blue
    global match_details_frame, game_routing_label, team_info_labels, bracket_info_canvas_ref, rankings_label_ref, btn_switch, bracket_info_frame_ref, team_info_frame_ref
    global switch_frame_ref, final_control_frame_ref, rankings_display_frame_ref
    
    header_frame = tk.Frame(root, bg='#333333')
    header_frame.pack(fill='x')
    
    header_label = tk.Label(header_frame, text="Current Match Resolution", font=('Arial', 14, 'bold'), fg='white', bg='#333333', pady=5)
    header_label.pack(fill='x')
    
    status_label = tk.Label(root, text="Tournament Initialized.", font=('Arial', 10, 'bold'), pady=5, bd=1, relief='sunken')
    status_label.pack(fill='x')
    
    scoreboard_canvas_ref = tk.Canvas(root, width=450, height=100, bg='white', highlightthickness=0)
    scoreboard_canvas_ref.pack(side='top', pady=10, padx=10, fill='x')
    
    center_x = 225
    name_x_red, name_x_blue = 110, 340 
    
    scoreboard_canvas_ref.create_line(center_x, 5, center_x, 95, fill='#CCCCCC', width=1)
    
    # MODIFIED: Removed 'RED SIDE' and 'BLUE SIDE' from canvas
    team_labels['red'] = scoreboard_canvas_ref.create_text(name_x_red, 40, text=f"{team_red_placeholder}", font=('Arial', 16, 'bold'), fill='#CC0000')
    player_labels_ref['red'] = scoreboard_canvas_ref.create_text(name_x_red, 70, text="Team X / (P1, P2)", font=('Arial', 9), width=200)

    team_labels['blue'] = scoreboard_canvas_ref.create_text(name_x_blue, 40, text=f"{team_blue_placeholder}", font=('Arial', 16, 'bold'), fill='#0066CC')
    player_labels_ref['blue'] = scoreboard_canvas_ref.create_text(name_x_blue, 70, text="Team Y / (P3, P4)", font=('Arial', 9), width=200)

    # NEW: Switch Button Frame (Relocated)
    switch_frame_ref = tk.Frame(root) 
    
    btn_switch = tk.Button(switch_frame_ref, text="SWITCH RED/BLUE", command=swap_teams, bg='#EEEEEE', fg='black', font=('Arial', 10), height=1)
    btn_switch.pack(fill='x')
    
    # Match Details Frame (Contains routing/bracket/team info - to be hidden on TOURNAMENT_OVER)
    match_details_frame = tk.Frame(root, padx=10, pady=5)
    
    # ADDED: Store bracket info frame reference
    bracket_info_frame = tk.Frame(match_details_frame, bd=1, relief='sunken')
    bracket_info_frame.pack(fill='x', pady=(0, 5))
    bracket_info_frame_ref = bracket_info_frame 
    
    bracket_info_canvas = tk.Canvas(bracket_info_frame, height=50, bg='white')
    bracket_info_canvas.pack(fill='x', expand=True, side='left')
    bracket_info_canvas_ref = bracket_info_canvas 
    
    # NEW: Frame to hold the rankings display (hidden during match play)
    rankings_display_frame_ref = tk.Frame(root, padx=10, pady=5, bd=1, relief='solid', bg='#F0F0F0')
    
    # The actual label for rankings/routing info (single instance, repurposed)
    game_routing_label = tk.Label(match_details_frame, text="Game ID: G#\nWinner Advances To: TBD\nLoser Drops To: TBD", 
                                  justify=tk.LEFT, font=('Arial', 9), bd=1, relief='solid', padx=5, pady=5, bg='#f0f0f0')
    game_routing_label.pack(fill='x', pady=(0, 5))
    
    # Create the dedicated ranking label and place it in its frame (to be shown on TOURNAMENT_OVER)
    rankings_label_ref = tk.Label(rankings_display_frame_ref, 
                                  text="--- Remaining Tournament Rankings ---", 
                                  justify=tk.LEFT, fg='black', bg='#F0F0F0', font=('Arial', 10, 'bold'), padx=5, pady=5)
    rankings_label_ref.pack(fill='both', expand=True)
    
    # ADDED: Store team info frame reference
    team_info_frame = tk.Frame(match_details_frame)
    team_info_frame.pack(fill='x')
    team_info_frame_ref = team_info_frame
    
    # MODIFIED: Combined team info box to show name, players, and status
    team_info_labels['red'] = tk.Label(team_info_frame, text="Team: Team X\nPlayers: P1, P2 (Active)", 
                                       justify=tk.LEFT, font=('Arial', 9), fg='#CC0000')
    team_info_labels['red'].pack(side=tk.LEFT, expand=True, padx=5)
    
    team_info_labels['blue'] = tk.Label(team_info_frame, text="Team: Team Y\nPlayers: P3, P4 (Active)", 
                                        justify=tk.LEFT, font=('Arial', 9), fg='#0066CC')
    team_info_labels['blue'].pack(side=tk.LEFT, expand=True, padx=5)
    
    # Match Input Frame (Winner Buttons ONLY)
    match_input_frame = tk.Frame(root, padx=10, pady=5)

    btn_red = tk.Button(match_input_frame, text="RED TEAM WINS", command=lambda: declare_winner('red'), bg='#FF5555', fg='black', font=('Arial', 12, 'bold'), height=2)
    # The winner buttons now expand equally and fill the space
    btn_red.pack(side=tk.LEFT, expand=True, padx=(5, 5), pady=5)
    
    btn_blue = tk.Button(match_input_frame, text="BLUE TEAM WINS", command=lambda: declare_winner('blue'), bg='#55AAFF', fg='black', font=('Arial', 12, 'bold'), height=2)
    # The winner buttons now expand equally and fill the space
    btn_blue.pack(side=tk.LEFT, expand=True, padx=(5, 5), pady=5)

    match_res_frame = tk.Frame(root, bg='#eeeeee', padx=10, pady=10)
    
    # Initialize the persistent final control frame
    final_control_frame_ref = tk.Frame(root)
    
    load_match_data_and_teams() 

def setup_main_gui(root):
    # ... (function body remains unchanged) ...
    """Sets up the main windows and calls component initialization. MODIFIED for single window."""
    global main_root
    main_root = root
    # MODIFIED: Renamed window title
    root.title("Moose Lodge Shuffleboard")
    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root)) 
    
    root.geometry("470x500") 

    g1_teams = TOURNAMENT_STATE.get('G1', {}).get('teams', ["Team Red", "Team Blue"])
    team_A = g1_teams[0] or "Team Red"
    team_B = g1_teams[1] or "Team Blue"
    
    # MODIFIED: Scoreboard setup is now for the main root window
    setup_scoreboard(root, team_A, team_B) 

def show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes):
    """Displays the player draw, team rosters, and prize pool before launching the main GUI."""
    summary_root = tk.Tk()
    summary_root.title("Tournament Draw & Prize Pool")
    summary_root.protocol("WM_DELETE_WINDOW", lambda: on_close(summary_root)) 
    
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
    per_player_2st = int(prizes.get('2st', 0) / 2)
    
    # Display format: Total Pool and then Nth Place Prize: $TOTAL ($PER_PLAYER per player)
    prize_text = f"Total Pool: ${total_pool}\n"
    prize_text += f"1st Place Prize: ${prizes.get('1st', 0)} (${per_player_1st} per player)\n"
    prize_text += f"2nd Place Prize: ${prizes.get('2st', 0)} (${per_player_2st} per player)\n"
    
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
    return

def generate_dynamic_bracket(teams, config=None):
    """
    Loads the bracket structure from the config file, initializes TOURNAMENT_STATE,
    and seeds the starting matches with teams (T1, T2, etc.).
    """
    global TOURNAMENT_STATE
    TOURNAMENT_STATE.clear()

    num_teams = len(teams)
    
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
                    else:
                        TOURNAMENT_STATE[match_id]['teams'][i] = None 

    # 3. Set initial active match
    initial_active_match = find_next_active_match()
    TOURNAMENT_STATE['active_match_id'] = initial_active_match

def get_multi_line_input(parent, title, prompt, num_required):
    """
    Custom function for individual player input boxes using a Toplevel dialog.
    MODIFIED: Uses a standard tk.Frame instead of a scrollable Canvas,
    and forces layout update after initial draw to fix the bug.
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    # Increased height to accommodate max players (20) without scrollbar
    dialog.geometry("550x850") 
    dialog.grab_set() 
    
    # result will be a tuple: (is_manual_draw, list_of_player_data)
    result = None 
    is_manual_draw = tk.BooleanVar(value=False)
    
    # List to store references to the Entry widgets
    player_entries = [] 

    tk.Label(dialog, text=prompt, pady=5, justify=tk.LEFT).pack(padx=10, anchor='w')
    
    # --- Auto/Manual Draw Control Frame ---
    control_frame = tk.Frame(dialog)
    control_frame.pack(padx=10, pady=5, fill='x')
    
    # Forward declaration for the drawing function
    def toggle_draw_wrapper():
        # Redraw the widgets in the simple frame
        draw_input_widgets(is_manual_draw.get(), num_required, input_container, player_entries)

    # Checkbox for Manual Draw
    check_manual = tk.Checkbutton(control_frame, text="Manual Draw (Assign Draw #)", variable=is_manual_draw, 
                                  command=toggle_draw_wrapper)
    check_manual.pack(side='left', padx=(0, 20))
    
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
                     return
                     
                try:
                    draw_num = int(raw_draw_num)
                except ValueError:
                    messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Draw number '{raw_draw_num}' is not a valid integer.")
                    return
                
                if draw_num < 1 or draw_num > num_required:
                    messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Draw number {draw_num} is out of range (1-{num_required}).")
                    return
                if draw_num in assigned_draws:
                    messagebox.showerror("Input Error", f"Manual Draw Error (Line {i+1}): Draw number {draw_num} is assigned multiple times.")
                    return
                    
                assigned_draws.add(draw_num)
                player_data_list.append((draw_num, player_name))
                
            # Final check for missing draws
            if len(assigned_draws) != num_required:
                missing_draws = [i for i in range(1, num_required + 1) if i not in assigned_draws]
                messagebox.showerror("Input Error", f"Manual Draw Error: The following draw numbers are missing: {', '.join(map(str, missing_draws))}")
                return

        else: # Auto Draw
            for i, (name_entry,) in enumerate(player_entries):
                player_name = name_entry.get().strip()
                if not player_name:
                    messagebox.showerror("Input Error", f"Auto Draw Error (Line {i+1}): Player Name must be filled.")
                    return
                # Draw_num is None for auto draw
                player_data_list.append((None, player_name)) 
                
        result = (is_manual, player_data_list)
        dialog.destroy()

    def on_cancel():
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
                return
            if num_players % 2 != 0:
                messagebox.showerror("Error", "The total number of players must be even!")
                num_players = None # Loop again
                continue
            break
        except Exception:
            pass

    # --- MODIFIED: Use the new return format from get_multi_line_input ---
    player_input_result = None
    while player_input_result is None:
        player_input_result = get_multi_line_input(dialog_root, "Player Names & Draw Input", 
                                            f"Enter the names and choose the draw method for {num_players} players:",
                                            num_players)
        if player_input_result is None:
            dialog_root.destroy()
            return
        
    dialog_root.destroy() # Close the temporary dialog root

    is_manual_draw, player_data_list = player_input_result

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
    
    num_teams = num_players // 2
    for i in range(num_teams):
        team_name = f'Team {i+1}'
        player1 = player_draws[i*2][1]
        player2 = player_draws[i*2 + 1][1]
        
        TEAMS.append(team_name)
        TEAM_ROSTERS[team_name] = [player1, player2]
        
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
    prizes['2st'] = prizes.get('2st', 0)
    prizes['3rd'] = prizes.get('3rd', 0)
    
    # Calculate Total Pool by summing the prizes read from the file
    total_pool = prizes['1st'] + prizes['2st'] + prizes['3rd']
        
    # --- 3. Show Draw Summary (Unchanged) ---
    show_draw_summary(player_draws, TEAMS, TEAM_ROSTERS, num_teams, total_pool, prizes)
    
    # --- 4. Generate Bracket and Launch Main Game (Unchanged) ---
    generate_dynamic_bracket(TEAMS, config)
    
    if not TOURNAMENT_STATE:
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
        match_details_frame.pack(fill='x', padx=10, pady=5)
        
    match_input_frame.pack(fill='x', pady=5)


    if match_id != last_assigned_match_id:
        
        match_data = TOURNAMENT_STATE[match_id]
        team_A = match_data['teams'][0] 
        team_B = match_data['teams'][1] 
        
        current_match_teams['red'] = team_A
        current_match_teams['blue'] = team_B
        
        last_assigned_match_id = match_id
    
    update_scoreboard_display()


# --- Main Program Entry Point (MODIFIED) ---

if __name__ == '__main__':
    # Ensure the 'data' directory exists for configuration files
    if not os.path.exists('data'):
        os.makedirs('data')
        
    # start_tournament handles creating and destroying the necessary Tk instances now
    start_tournament()
