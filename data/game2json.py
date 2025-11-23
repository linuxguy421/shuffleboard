#!/usr/bin/env python3

import os
import json
import re

def _parse_legacy_destination(dest_str):
    """
    (Legacy Logic) Parses destination strings from .game files 
    into the internal tuple/string format.
    """
    dest_str = dest_str.strip()
    
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
        
    elim_match = re.search(r'ELIMINATED\s*\((.+?)\)', dest_str, re.IGNORECASE)
    if elim_match:
        rank_part = elim_match.group(1).upper().replace('.', '').strip()
        return f'ELIMINATED[{rank_part}]'
        
    if dest_str.endswith('_CONDITIONAL'):
        return dest_str
        
    return dest_str

def _parse_legacy_file(content):
    """(Legacy Logic) Reads the text content of a .game file."""
    config = {}
    current_match_id = None
    prizes = {} 
    
    is_parsing_prizes = False 
    
    content = re.sub(r'\r', '', content) 
    lines = [line.strip() for line in content.split('\n')]
    
    for line in lines:
        line = line.strip()
        
        # Parse Prizes
        if line.startswith('PRIZES:'):
            is_parsing_prizes = True
            continue
            
        if is_parsing_prizes:
            prize_match = re.match(r'(\d+):\s*(\d+)', line)
            if prize_match:
                rank = prize_match.group(1) 
                amount = int(prize_match.group(2))
                
                # Standardize keys for the JSON output
                # The old app used '2st', but we want clean keys '1', '2', '3' for JSON
                if rank == '1': prizes['1'] = amount
                elif rank == '2': prizes['2'] = amount
                elif rank == '3': prizes['3'] = amount
                continue
            
            if not line or re.match(r'(G\d+|GF|GGF)\s*\(.+\):', line):
                 is_parsing_prizes = False
                 
        if is_parsing_prizes:
            continue
            
        # Parse Matches
        match_header = re.match(r'(G\d+|GF|GGF)\s*\(.+\):', line) 
        if match_header:
            current_match_id = match_header.group(1)
            config[current_match_id] = {'config': {}}
            continue
            
        if not current_match_id:
            continue
            
        if line.startswith('Teams:'):
            teams_str = line.split(':', 1)[1].strip()
            teams = [t.strip().replace('(', '').replace(')', '').split(' ')[0] for t in teams_str.split(',')]
            config[current_match_id]['teams'] = teams
            
        elif line.startswith('Winner_Advances_To:'):
            dest_str = line.split(':', 1)[1].strip()
            config[current_match_id]['config']['W_next'] = _parse_legacy_destination(dest_str)
            
        elif line.startswith('Loser_Drops_To:'):
            dest_str = line.split(':', 1)[1].strip()
            config[current_match_id]['config']['L_next'] = _parse_legacy_destination(dest_str)

    return config, prizes

def convert_internal_to_json_structure(internal_config, internal_prizes, filename):
    """
    Converts the Python internal dictionary format (Tuples) 
    back into the clean JSON format (Objects).
    """
    
    # 1. Format Prizes
    # internal_prizes is already {'1': 50, '2': 30} from our parser above
    json_output = {
        "tournament_name": f"Converted from {filename}",
        "prizes": internal_prizes,
        "games": {}
    }
    
    # 2. Format Games
    for match_id, data in internal_config.items():
        game_obj = {
            "teams": data.get('teams', ["TBD", "TBD"]),
            "winner_advances_to": _convert_dest(data['config'].get('W_next')),
            "loser_drops_to": _convert_dest(data['config'].get('L_next'))
        }
        json_output['games'][match_id] = game_obj
        
    return json_output

def _convert_dest(dest):
    """Helper to turn Python Tuples back into JSON objects."""
    if dest is None:
        return None
        
    # Tuple Case: ('G4', 1) -> {"game": "G4", "slot": 1}
    if isinstance(dest, tuple):
        return {
            "game": dest[0],
            "slot": dest[1]
        }
    
    # String Cases
    if isinstance(dest, str):
        if dest == 'CHAMPION':
            return {"result": "CHAMPION"}
        
        if dest.endswith('_CONDITIONAL'):
            return {"result": "GF_CONDITIONAL"}
            
        # Handle "ELIMINATED[7TH]" -> {"result": "ELIMINATED", "rank": "7th"}
        if dest.startswith('ELIMINATED'):
            rank = dest.replace('ELIMINATED[', '').replace(']', '').lower()
            return {
                "result": "ELIMINATED",
                "rank": rank
            }
            
    return dest

def main():
    # Find all .game files in current directory
    files = [f for f in os.listdir('.') if f.endswith('.game')]
    
    if not files:
        print("No .game files found in this directory.")
        return

    print(f"Found {len(files)} .game files to convert...")

    for filename in files:
        try:
            print(f"Processing {filename}...")
            with open(filename, 'r') as f:
                content = f.read()
            
            # 1. Read .game to Python Dict
            config, prizes = _parse_legacy_file(content)
            
            # 2. Convert Python Dict to JSON Structure
            json_data = convert_internal_to_json_structure(config, prizes, filename)
            
            # 3. Save as .json
            new_filename = filename.replace('.game', '.json')
            with open(new_filename, 'w') as f:
                json.dump(json_data, f, indent=2)
                
            print(f"  -> Created {new_filename}")
            
        except Exception as e:
            print(f"  X Failed to convert {filename}: {e}")

    print("\nConversion complete!")

if __name__ == "__main__":
    main()
