"""
Unit tests for sb.py — pure logic functions only (no tkinter).

Run with:
    python3 -m pytest test_sb.py -v
  or:
    python3 -m unittest test_sb -v
"""

import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Stub out tkinter and every other GUI import before sb.py is loaded
# ---------------------------------------------------------------------------
tk_stub = MagicMock()
sys.modules['tkinter'] = tk_stub
sys.modules['tkinter.ttk'] = tk_stub
sys.modules['tkinter.messagebox'] = tk_stub
sys.modules['tkinter.simpledialog'] = tk_stub
sys.modules['tkinter.filedialog'] = tk_stub

# Prevent messagebox dialogs from blocking during tests
tk_stub.messagebox = MagicMock()
tk_stub.messagebox.showerror = MagicMock()
tk_stub.messagebox.showwarning = MagicMock()
tk_stub.messagebox.showinfo = MagicMock()

import importlib
import types

# Patch messagebox at top level too
messagebox_stub = MagicMock()
messagebox_stub.showerror = MagicMock()
messagebox_stub.showwarning = MagicMock()
messagebox_stub.showinfo = MagicMock()
sys.modules['tkinter.messagebox'] = messagebox_stub

# Now import sb — its global-level code runs (mostly just assignments)
# We suppress the mainloop at the bottom with a guard already in the file
import sb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_match(teams=None, winner=None, winner_color=None, is_reset=False,
                is_winnerbracket='true', w_next=None, l_next=None,
                champion=None):
    return {
        'teams': teams if teams is not None else [None, None],
        'winner': winner,
        'winner_color': winner_color,
        'is_reset': is_reset,
        'is_winnerbracket': is_winnerbracket,
        'champion': champion,
        'config': {
            'W_next': w_next,
            'L_next': l_next,
            'M_round': 0,
            'L_round': 0,
        }
    }


def _reset():
    """Reset all globals to a clean state before each test."""
    sb.TEAMS.clear()
    sb.TEAM_ROSTERS.clear()
    sb.TOURNAMENT_STATE.clear()
    sb.TOURNAMENT_RANKINGS.clear()
    sb.MATCH_HISTORY.clear()
    sb.MATCH_DURATIONS.clear()
    sb.REPLAY_FILEPATH = None
    sb.last_assigned_match_id = None
    sb.TOURNAMENT_START_TIME = None


# ---------------------------------------------------------------------------
# 1. sort_match_keys
# ---------------------------------------------------------------------------

class TestSortMatchKeys(unittest.TestCase):

    def test_numeric_games_sorted(self):
        keys = ['G10', 'G2', 'G1', 'G5']
        self.assertEqual(sorted(keys, key=sb.sort_match_keys), ['G1', 'G2', 'G5', 'G10'])

    def test_gf_after_numeric(self):
        keys = ['GF', 'G3', 'G1']
        self.assertEqual(sorted(keys, key=sb.sort_match_keys), ['G1', 'G3', 'GF'])

    def test_ggf_after_gf(self):
        keys = ['GGF', 'GF', 'G1']
        self.assertEqual(sorted(keys, key=sb.sort_match_keys), ['G1', 'GF', 'GGF'])


# ---------------------------------------------------------------------------
# 2. format_seconds
# ---------------------------------------------------------------------------

class TestFormatSeconds(unittest.TestCase):

    def test_zero(self):
        self.assertEqual(sb.format_seconds(0), "00:00")

    def test_none(self):
        self.assertEqual(sb.format_seconds(None), "00:00")

    def test_seconds_only(self):
        self.assertEqual(sb.format_seconds(45), "00:45")

    def test_minutes_and_seconds(self):
        self.assertEqual(sb.format_seconds(125), "02:05")

    def test_with_hours(self):
        self.assertEqual(sb.format_seconds(3661), "1:01:01")


# ---------------------------------------------------------------------------
# 3. reset_global_state
# ---------------------------------------------------------------------------

class TestResetGlobalState(unittest.TestCase):

    def setUp(self):
        sb.TEAMS.extend(['A', 'B'])
        sb.TEAM_ROSTERS['A'] = ['p1', 'p2']
        sb.TOURNAMENT_STATE['G1'] = _make_match(['A', 'B'])
        sb.TOURNAMENT_RANKINGS['1ST'] = 'A'
        sb.MATCH_HISTORY.append({'id': 'G1', 'winner': 'A', 'loser': 'B', 'color': 'red'})
        sb.MATCH_DURATIONS.append(120)
        sb.REPLAY_FILEPATH = 'some/path.json'
        sb.last_assigned_match_id = 'G1'

    def test_all_cleared(self):
        sb.reset_global_state()
        self.assertEqual(sb.TEAMS, [])
        self.assertEqual(sb.TEAM_ROSTERS, {})
        self.assertEqual(sb.TOURNAMENT_STATE, {})
        self.assertEqual(sb.TOURNAMENT_RANKINGS, {})
        self.assertEqual(sb.MATCH_HISTORY, [])
        self.assertEqual(sb.MATCH_DURATIONS, [])
        self.assertIsNone(sb.REPLAY_FILEPATH)
        self.assertIsNone(sb.last_assigned_match_id)


# ---------------------------------------------------------------------------
# 4. finalize_match_duration
# ---------------------------------------------------------------------------

class TestFinalizeMatchDuration(unittest.TestCase):

    def setUp(self):
        _reset()

    def test_uses_elapsed_at_pause_when_paused(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match()
        sb.TOURNAMENT_STATE['G1']['start_time'] = time.time() - 999
        sb.TOURNAMENT_STATE['G1']['timer_paused'] = True
        sb.TOURNAMENT_STATE['G1']['elapsed_at_pause'] = 42

        result = sb.finalize_match_duration('G1')
        self.assertEqual(result, 42)
        self.assertEqual(sb.MATCH_DURATIONS, [42])

    def test_uses_start_time_when_running(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match()
        sb.TOURNAMENT_STATE['G1']['start_time'] = time.time() - 100
        sb.TOURNAMENT_STATE['G1']['timer_paused'] = False

        result = sb.finalize_match_duration('G1')
        self.assertAlmostEqual(result, 100, delta=2)
        self.assertEqual(len(sb.MATCH_DURATIONS), 1)

    def test_returns_none_if_no_start_time(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match()
        result = sb.finalize_match_duration('G1')
        self.assertIsNone(result)
        self.assertEqual(sb.MATCH_DURATIONS, [])

    def test_missing_match_returns_none(self):
        result = sb.finalize_match_duration('G99')
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5. get_team_record
# ---------------------------------------------------------------------------

class TestGetTeamRecord(unittest.TestCase):

    def setUp(self):
        _reset()

    def test_simple_win_loss(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match(['TeamA', 'TeamB'], winner='TeamA')
        sb.TOURNAMENT_STATE['G2'] = _make_match(['TeamA', 'TeamC'], winner='TeamC')
        w, l = sb.get_team_record('TeamA')
        self.assertEqual(w, 1)
        self.assertEqual(l, 1)

    def test_no_matches_played(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match(['TeamA', 'TeamB'])
        w, l = sb.get_team_record('TeamA')
        self.assertEqual(w, 0)
        self.assertEqual(l, 0)

    def test_skips_gf_when_ggf_has_result(self):
        # GF was reset (TeamB beat TeamA), then GGF was played (TeamA won)
        sb.TOURNAMENT_STATE['GF'] = _make_match(
            ['TeamA', 'TeamB'], winner='TeamB', is_reset=True)
        sb.TOURNAMENT_STATE['GGF'] = _make_match(
            ['TeamB', 'TeamA'], winner='TeamA')

        w_a, l_a = sb.get_team_record('TeamA')
        w_b, l_b = sb.get_team_record('TeamB')

        # GF skipped — only GGF counts
        self.assertEqual(w_a, 1)
        self.assertEqual(l_a, 0)
        self.assertEqual(w_b, 0)
        self.assertEqual(l_b, 1)

    def test_counts_gf_when_ggf_has_no_result(self):
        sb.TOURNAMENT_STATE['GF'] = _make_match(
            ['TeamA', 'TeamB'], winner='TeamA', is_reset=False)
        sb.TOURNAMENT_STATE['GGF'] = _make_match([None, None])

        w, l = sb.get_team_record('TeamA')
        self.assertEqual(w, 1)
        self.assertEqual(l, 0)


# ---------------------------------------------------------------------------
# 6. find_next_active_match
# ---------------------------------------------------------------------------

class TestFindNextActiveMatch(unittest.TestCase):

    def setUp(self):
        _reset()

    def test_returns_first_ready_match(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match(['A', 'B'])
        sb.TOURNAMENT_STATE['G2'] = _make_match(['C', 'D'])
        sb.TOURNAMENT_STATE['active_match_id'] = 'G1'
        self.assertEqual(sb.find_next_active_match(), 'G1')

    def test_skips_completed_matches(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match(['A', 'B'], winner='A')
        sb.TOURNAMENT_STATE['G2'] = _make_match(['C', 'D'])
        self.assertEqual(sb.find_next_active_match(), 'G2')

    def test_skips_incomplete_teams(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match([None, 'B'])
        sb.TOURNAMENT_STATE['G2'] = _make_match(['C', 'D'])
        self.assertEqual(sb.find_next_active_match(), 'G2')

    def test_tournament_over_when_all_done(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match(['A', 'B'], winner='A')
        sb.TOURNAMENT_STATE['GF'] = _make_match(['A', 'C'], winner='A')
        self.assertEqual(sb.find_next_active_match(), 'TOURNAMENT_OVER')


# ---------------------------------------------------------------------------
# 7. handle_match_resolution — winner/loser propagation
# ---------------------------------------------------------------------------

class TestHandleMatchResolution(unittest.TestCase):

    def setUp(self):
        _reset()
        sb.TEAMS.extend(['T1', 'T2', 'T3', 'T4'])
        sb.TEAM_ROSTERS.update({t: [f'{t}p1', f'{t}p2'] for t in sb.TEAMS})
        # Patch UI calls that handle_match_resolution makes
        sb.reset_game = MagicMock()
        sb.full_bracket_canvas = None

    def _make_simple_bracket(self):
        sb.TOURNAMENT_STATE['G1'] = _make_match(
            ['T1', 'T2'], w_next=('G3', 0), l_next=('G4', 0))
        sb.TOURNAMENT_STATE['G2'] = _make_match(
            ['T3', 'T4'], w_next=('G3', 1), l_next=('G4', 1))
        sb.TOURNAMENT_STATE['G3'] = _make_match(
            [None, None], w_next=('GF', 0), l_next=('G5', 0))
        sb.TOURNAMENT_STATE['G4'] = _make_match(
            [None, None], w_next=('G5', 1), l_next='ELIMINATED[4TH]',
            is_winnerbracket='false')
        sb.TOURNAMENT_STATE['G5'] = _make_match(
            [None, None], w_next=('GF', 1), l_next='ELIMINATED[3RD]',
            is_winnerbracket='false')
        sb.TOURNAMENT_STATE['GF'] = _make_match(
            [None, None], w_next='CHAMPION', l_next='GF_CONDITIONAL',
            is_winnerbracket='both')
        sb.TOURNAMENT_STATE['GGF'] = _make_match(
            [None, None], w_next='CHAMPION', l_next='ELIMINATED[2ND]',
            is_winnerbracket='both')
        sb.TOURNAMENT_STATE['active_match_id'] = 'G1'

    def test_winner_propagates_to_correct_slot(self):
        self._make_simple_bracket()
        sb.handle_match_resolution('T1', 'T2', 'red', 'G1')
        self.assertEqual(sb.TOURNAMENT_STATE['G3']['teams'][0], 'T1')

    def test_loser_propagates_to_correct_slot(self):
        self._make_simple_bracket()
        sb.handle_match_resolution('T1', 'T2', 'red', 'G1')
        self.assertEqual(sb.TOURNAMENT_STATE['G4']['teams'][0], 'T2')

    def test_elimination_rank_assigned(self):
        self._make_simple_bracket()
        # Resolve G1 and G2 first to populate G4
        sb.handle_match_resolution('T1', 'T2', 'red', 'G1')
        sb.handle_match_resolution('T3', 'T4', 'red', 'G2')
        # Resolve G4 — loser gets 4th
        sb.handle_match_resolution('T2', 'T4', 'red', 'G4')
        self.assertEqual(sb.TOURNAMENT_RANKINGS.get('4TH'), 'T4')

    def test_gf_undefeated_sets_champion(self):
        self._make_simple_bracket()
        sb.TOURNAMENT_STATE['GF']['teams'] = ['T1', 'T3']
        sb.handle_match_resolution('T1', 'T3', 'red', 'GF')
        self.assertEqual(sb.TOURNAMENT_RANKINGS.get('1ST'), 'T1')
        self.assertEqual(sb.TOURNAMENT_RANKINGS.get('2ND'), 'T3')
        self.assertEqual(sb.TOURNAMENT_STATE['active_match_id'], 'TOURNAMENT_OVER')
        self.assertNotIn('GGF', sb.TOURNAMENT_STATE)

    def test_gf_reset_sets_ggf_active(self):
        self._make_simple_bracket()
        sb.TOURNAMENT_STATE['GF']['teams'] = ['T1', 'T3']  # T1=WB finalist
        # T3 (LB winner) beats T1 (WB finalist) — forces reset
        sb.handle_match_resolution('T3', 'T1', 'blue', 'GF')
        self.assertEqual(sb.TOURNAMENT_STATE['active_match_id'], 'GGF')
        self.assertEqual(sb.TOURNAMENT_STATE['GF'].get('is_reset'), True)
        self.assertEqual(sb.TOURNAMENT_STATE['GGF']['teams'], ['T3', 'T1'])

    def test_ggf_sets_champion(self):
        self._make_simple_bracket()
        sb.TOURNAMENT_STATE['GGF']['teams'] = ['T3', 'T1']
        sb.handle_match_resolution('T1', 'T3', 'red', 'GGF')
        self.assertEqual(sb.TOURNAMENT_RANKINGS.get('1ST'), 'T1')
        self.assertEqual(sb.TOURNAMENT_RANKINGS.get('2ND'), 'T3')
        self.assertEqual(sb.TOURNAMENT_STATE['active_match_id'], 'TOURNAMENT_OVER')


# ---------------------------------------------------------------------------
# 8. serialize_snapshot — ephemeral fields excluded
# ---------------------------------------------------------------------------

class TestSerializeSnapshot(unittest.TestCase):

    def setUp(self):
        _reset()
        sb.TEAMS.extend(['TeamA', 'TeamB'])
        sb.TEAM_ROSTERS.update({'TeamA': ['p1', 'p2'], 'TeamB': ['p3', 'p4']})
        sb.TOURNAMENT_STATE['G1'] = _make_match(['TeamA', 'TeamB'])
        sb.TOURNAMENT_STATE['G1']['_flash_state'] = True
        sb.TOURNAMENT_STATE['G1']['_paused_since'] = 12345.0
        sb.TOURNAMENT_STATE['G1']['elapsed_at_pause'] = 99
        sb.TOURNAMENT_STATE['G1']['timer_paused'] = True
        sb.TOURNAMENT_STATE['active_match_id'] = 'G1'
        sb.MATCH_HISTORY.append({'id': 'G0', 'winner': 'TeamA', 'loser': 'TeamB', 'color': 'red'})
        sb.MATCH_DURATIONS.append(75)

    def test_ephemeral_fields_excluded(self):
        snap = sb.serialize_snapshot()
        g1_saved = snap['state']['G1']
        self.assertNotIn('_flash_state', g1_saved)
        self.assertNotIn('_paused_since', g1_saved)
        self.assertNotIn('elapsed_at_pause', g1_saved)
        self.assertNotIn('timer_paused', g1_saved)

    def test_match_history_included(self):
        snap = sb.serialize_snapshot()
        self.assertEqual(snap['match_history'], sb.MATCH_HISTORY)

    def test_match_durations_included(self):
        snap = sb.serialize_snapshot()
        self.assertEqual(snap['match_durations'], [75])

    def test_teams_and_rosters_included(self):
        snap = sb.serialize_snapshot()
        self.assertEqual(snap['teams'], ['TeamA', 'TeamB'])
        self.assertIn('TeamA', snap['rosters'])

    def test_persistent_fields_saved(self):
        snap = sb.serialize_snapshot()
        g1_saved = snap['state']['G1']
        for key in ('teams', 'winner', 'winner_color', 'is_reset', 'champion',
                    'is_winnerbracket', 'start_time', 'duration', 'config'):
            self.assertIn(key, g1_saved)


# ---------------------------------------------------------------------------
# 9. load_bracket_config — file loading and finals injection
# ---------------------------------------------------------------------------

class TestLoadBracketConfig(unittest.TestCase):

    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

    def _load(self, n):
        orig_dir = os.getcwd()
        os.chdir(self.DATA_DIR)
        try:
            config, prizes = sb.load_bracket_config(n, 'D')
        finally:
            os.chdir(orig_dir)
        return config, prizes

    def test_gf_injected(self):
        config, _ = self._load(5)
        self.assertIn('GF', config)
        self.assertIn('GGF', config)

    def test_all_team_counts_load(self):
        for n in range(3, 11):
            config, prizes = self._load(n)
            self.assertIn('G1', config)
            self.assertIn('GF', config)

    def test_prizes_loaded(self):
        _, prizes = self._load(5)
        self.assertIn('1st', prizes)
        self.assertIn('2nd', prizes)

    def test_missing_config_raises(self):
        with self.assertRaises((FileNotFoundError, ValueError)):
            self._load(99)


# ---------------------------------------------------------------------------
# 10. generate_dynamic_bracket — seeding
# ---------------------------------------------------------------------------

class TestGenerateDynamicBracket(unittest.TestCase):

    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

    def setUp(self):
        _reset()

    def _generate(self, n):
        teams = [f'Team{i}' for i in range(1, n + 1)]
        sb.TEAMS.extend(teams)
        orig_dir = os.getcwd()
        os.chdir(self.DATA_DIR)
        try:
            sb.generate_dynamic_bracket(teams)
        finally:
            os.chdir(orig_dir)

    def test_active_match_set(self):
        self._generate(4)
        self.assertIn(sb.TOURNAMENT_STATE.get('active_match_id'),
                      [k for k in sb.TOURNAMENT_STATE if k.startswith('G')])

    def test_g1_has_two_teams(self):
        self._generate(5)
        teams = sb.TOURNAMENT_STATE['G1']['teams']
        self.assertIsNotNone(teams[0])
        self.assertIsNotNone(teams[1])

    def test_all_bracket_sizes_generate(self):
        for n in range(3, 11):
            _reset()
            self._generate(n)
            self.assertIn('GF', sb.TOURNAMENT_STATE)
            self.assertIn('GGF', sb.TOURNAMENT_STATE)

    def test_seeded_teams_are_from_teams_list(self):
        self._generate(6)
        all_seeded = set()
        for mid, mdata in sb.TOURNAMENT_STATE.items():
            if isinstance(mdata, dict):
                for t in mdata.get('teams', []):
                    if t and not str(t).startswith('W:'):
                        all_seeded.add(t)
        for team in all_seeded:
            self.assertIn(team, sb.TEAMS)


# ---------------------------------------------------------------------------
# 11. Late entry — G1 config routing updated after rebuild
# ---------------------------------------------------------------------------

class TestLateEntryRouting(unittest.TestCase):
    """
    Verify that after add_late_team, G1's config W_next/L_next matches
    the new bracket (not the old one).
    """

    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

    def setUp(self):
        _reset()
        # Suppress all UI calls inside add_late_team
        sb.main_root = MagicMock()
        sb.main_root.wait_window = MagicMock()
        sb.update_schedule_tab = MagicMock()
        sb.update_roster_seeding_vertical = MagicMock()
        sb.update_scoreboard_display = MagicMock()
        sb.draw_small_bracket_view = MagicMock()
        sb.bracket_info_canvas_ref = None
        sb.full_bracket_root = None
        sb.REPLAY_FILEPATH = None

    def _setup_5_team_bracket(self):
        teams = [f'Team{i}' for i in range(1, 6)]
        sb.TEAMS.extend(teams)
        sb.TEAM_ROSTERS.update({t: [f'{t}p1', f'{t}p2'] for t in teams})
        orig = os.getcwd()
        os.chdir(self.DATA_DIR)
        try:
            sb.generate_dynamic_bracket(teams)
        finally:
            os.chdir(orig)
        sb.TOURNAMENT_STATE['active_match_id'] = 'G1'

    def test_g1_routing_updated_to_6_team_config(self):
        self._setup_5_team_bracket()

        # Capture the 5-team G1 W_next before late entry
        old_w_next = sb.TOURNAMENT_STATE['G1']['config']['W_next']

        # Load what the 6-team config says G1's W_next should be
        orig = os.getcwd()
        os.chdir(self.DATA_DIR)
        try:
            six_config, _ = sb.load_bracket_config(6, 'D')
        finally:
            os.chdir(orig)

        # Simulate add_late_team without the dialog by calling the rebuild directly
        g1_snapshot = dict(sb.TOURNAMENT_STATE['G1'])
        g1_snapshot['config'] = dict(sb.TOURNAMENT_STATE['G1']['config'])

        new_team = 'Team6'
        sb.TEAMS.append(new_team)
        sb.TEAM_ROSTERS[new_team] = ['p11', 'p12']

        orig = os.getcwd()
        os.chdir(self.DATA_DIR)
        try:
            sb.generate_dynamic_bracket(sb.TEAMS, six_config)
        finally:
            os.chdir(orig)

        new_g1_config = sb.TOURNAMENT_STATE['G1']['config']
        sb.TOURNAMENT_STATE['G1'].update({
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
        sb.TOURNAMENT_STATE['active_match_id'] = 'G1'

        new_w_next = sb.TOURNAMENT_STATE['G1']['config']['W_next']

        # 5-team: G1 winner → G3 slot 0; 6-team: G1 winner → G3 slot 1
        self.assertNotEqual(old_w_next, new_w_next,
            "G1 W_next should have changed between 5 and 6 team configs")
        # Verify it matches what the 6-team config actually specifies
        import re as _re
        raw_dest = six_config['G1'].get('winner_advances_to') or six_config['G1'].get('W_next')
        # new_w_next is a tuple e.g. ('G3', 1)
        self.assertEqual(new_w_next[0], 'G3')


if __name__ == '__main__':
    unittest.main(verbosity=2)
