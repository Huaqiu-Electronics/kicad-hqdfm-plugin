import argparse
import os
import subprocess
import sys
import textwrap


CHECK_SCRIPT = r"""
import builtins
import sys

sys.path.insert(0, r"{repo}")
builtins._ = lambda value: value

import pcbnew
import wx
import wx.dataview as dv

from kicad_dfm import config
from kicad_dfm.child_frame.dfm_child_frame import DfmChildFrame
from kicad_dfm.core.rule_profiles import rules_for_profile
from kicad_dfm.core.settings import DEFAULT_SETTINGS
import kicad_dfm.dfm_mainframe as mainframe_module
from kicad_dfm.dfm_mainframe import DfmMainframe
from kicad_dfm.kicad.board_loader import load_board_noninteractive
from kicad_dfm.manager.rule_manager_view import RuleManagerView
from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis
from kicad_dfm.settings.kicad_setting import KiCadSetting
from kicad_dfm.ui.main_frame import HQ_DFM_EN_URL, select_language_control


def first_board_item_id(board):
    candidates = []
    if hasattr(board, "GetTracks"):
        candidates.extend(list(board.GetTracks()))
    if hasattr(board, "GetFootprints"):
        for footprint in board.GetFootprints():
            if hasattr(footprint, "Pads"):
                candidates.extend(list(footprint.Pads()))
    for item in candidates:
        uuid = getattr(item, "m_Uuid", None)
        if uuid is not None and hasattr(uuid, "AsString"):
            value = uuid.AsString()
            if value:
                return value
        if hasattr(item, "GetUuid"):
            uuid = item.GetUuid()
            if hasattr(uuid, "AsString"):
                value = uuid.AsString()
                if value:
                    return value
    return ""


def synthetic_marker_result(item_id):
    return {{
        "Smallest Trace Width": {{
            "check": [
                {{
                    "result": [
                        {{
                            "item": "Trace Width",
                            "id": item_id,
                            "source": "kicad",
                            "geometry_basis": "exact_kicad",
                        }}
                    ]
                }}
            ]
        }}
    }}


app = wx.App(False)
board = load_board_noninteractive(r"{board}")
pcbnew.GetBoard = lambda: board
KiCadSetting.read_lang_setting = staticmethod(lambda: "English")
restored_ui_settings = DEFAULT_SETTINGS.copy()
restored_ui_settings["summary_column_widths"] = [250, 230, 90]
saved_ui_settings = []
mainframe_module.load_ui_settings = lambda: restored_ui_settings.copy()
mainframe_module.save_settings = lambda settings: saved_ui_settings.append(dict(settings))
rules = rules_for_profile("standard")
economy_rules = rules_for_profile("economy")
precision_rules = rules_for_profile("precision")

main_window = DfmMainframe(None)
if len(main_window.dfm_maindialog.rule_profile_buttons) < 3:
    raise AssertionError("Main window did not create rule profile radio buttons")
profile_labels = [
    button.GetLabel() for button in main_window.dfm_maindialog.rule_profile_buttons
]
if profile_labels != ["Basic", "Standard", "Advanced"]:
    raise AssertionError("Main window profile labels are not compact: {{0}}".format(profile_labels))
if main_window.dfm_maindialog.gerber_dfm_button.GetLabel() != "Full DFM Check":
    raise AssertionError("Full DFM button label is not compact")
for button in (
    main_window.dfm_maindialog.dfm_run_button,
    main_window.dfm_maindialog.gerber_dfm_button,
    main_window.dfm_maindialog.rule_manager_button,
    main_window.dfm_maindialog.reset_visible_layers_button,
):
    if button.GetBestSize().width > button.GetSize().width:
        raise AssertionError(
            "Main action label is wider than its button: {{0}}".format(
                button.GetLabel()
            )
        )
if (
    main_window.dfm_maindialog.rule_profile_sizer.GetMinSize().width
    > main_window.dfm_maindialog.rule_profile_panel.GetSize().width
):
    raise AssertionError("Rule profile labels overflow their panel")
if main_window.dfm_maindialog.dfm_hint_link.GetURL() != HQ_DFM_EN_URL:
    raise AssertionError("English main window DFM hint has the wrong URL")
if main_window.dfm_maindialog.dfm_hint_link.GetLabel() != "Huaqiu DFM":
    raise AssertionError("Main window Huaqiu DFM hint has the wrong link label")
if not main_window.dfm_maindialog.dfm_hint_panel.IsShown():
    raise AssertionError("Main window Huaqiu DFM hint is hidden")
if hasattr(main_window.dfm_maindialog, "gerber_export_button"):
    raise AssertionError("Main window still exposes a fixed Gerber Export row action")
if "Gerber Export" in main_window.json_analysis_map:
    raise AssertionError("Main window still contains a fixed Gerber Export summary row")
if len(main_window.dfm_maindialog.check_buttons) != len(main_window.json_analysis_map):
    raise AssertionError("Main summary rows and action targets are misaligned")
summary_view = main_window.dfm_maindialog.mainframe_data_view
if summary_view.GetWindowStyleFlag() & dv.DV_NO_HEADER:
    raise AssertionError("Main summary column headers are hidden")
if summary_view.GetColumnCount() != 3:
    raise AssertionError("Main summary does not contain three columns")
summary_columns = [summary_view.GetColumn(index) for index in range(3)]
if [column.GetTitle() for column in summary_columns] != ["Rule", "Value", "Check"]:
    raise AssertionError("Main summary column titles are incorrect")
if not all(column.IsResizeable() for column in summary_columns):
    raise AssertionError("Main summary columns are not user-resizable")
expected_widths = [main_window.dfm_maindialog.FromDIP(width) for width in [250, 230, 90]]
actual_widths = [column.GetWidth() for column in summary_columns]
if actual_widths != expected_widths:
    raise AssertionError(
        "Saved summary column widths were not restored: {{0}} != {{1}}".format(
            actual_widths, expected_widths
        )
    )
resized_width = summary_columns[0].GetWidth() + 40
summary_columns[0].SetWidth(resized_width)
main_window.dfm_maindialog.refresh_dpi_layout()
if summary_columns[0].GetWidth() != resized_width:
    raise AssertionError("DPI refresh reset a user-adjusted summary column width")
main_window.persist_summary_column_widths()
expected_saved_widths = [
    main_window.dfm_maindialog.ToDIP(column.GetWidth())
    for column in summary_columns
]
if saved_ui_settings[-1]["summary_column_widths"] != expected_saved_widths:
    raise AssertionError("Adjusted summary column widths were not saved")
expected_button_size = main_window.dfm_maindialog.FromDIP(wx.Size(100, 30))
for button in main_window.dfm_maindialog.check_buttons:
    if button.GetMinSize() != expected_button_size:
        raise AssertionError(
            "DFM check button did not use current-monitor DIP size: {{0}} != {{1}}".format(
                button.GetMinSize(),
                expected_button_size,
            )
        )
if not hasattr(main_window.dfm_maindialog, "reset_visible_layers_button"):
    raise AssertionError("Main window has no reset visible layers button")
main_action_buttons = main_window.dfm_maindialog.main_action_buttons
if len({{button.GetPosition().y for button in main_action_buttons}}) != 1:
    raise AssertionError("Main action buttons are not arranged in one row")
if main_window.dfm_maindialog.reset_visible_layers_button.GetLabel() != "Reset Layers":
    raise AssertionError("Reset layers label is not compact")
if main_window.dfm_maindialog.inject_drc_markers_button.IsShown():
    raise AssertionError("Inject DRC Markers button is still visible")
if main_window.dfm_maindialog.clear_drc_markers_button.IsShown():
    raise AssertionError("Clear DRC Markers button is still visible")
action_renderer = main_window.dfm_maindialog._action_renderer
narrow_button_rect = action_renderer._button_rect(
    wx.Rect(0, 0, main_window.dfm_maindialog.FromDIP(90), 35)
)
wide_button_rect = action_renderer._button_rect(
    wx.Rect(0, 0, main_window.dfm_maindialog.FromDIP(140), 35)
)
if wide_button_rect.x <= narrow_button_rect.x:
    raise AssertionError("Check button does not follow action-column resizing")
if wide_button_rect.width != narrow_button_rect.width:
    raise AssertionError("Check button width changes with an oversized action column")
if hasattr(main_window.dfm_maindialog, "inject_native_drc_markers_button"):
    raise AssertionError("Main window still exposes native DRC marker inject button")
if hasattr(main_window.dfm_maindialog, "clear_native_drc_markers_button"):
    raise AssertionError("Main window still exposes native DRC marker clear button")
hidden_layers = board.GetVisibleLayers()
hidden_layers.RemoveLayer(pcbnew.F_Cu)
board.SetVisibleLayers(hidden_layers)
main_window.show_all_visible_layers()
visible_layers = board.GetVisibleLayers()
visible_layer_ids = set(visible_layers.Seq())
expected_layer_ids = set(pcbnew.LSET.AllLayersMask().Seq())
if not expected_layer_ids.issubset(visible_layer_ids):
    raise AssertionError("Reset visible layers did not make every layer visible")
main_window.Destroy()

rule_window = RuleManagerView(None, "standard", rules, 1, config.Language_english)
width, height = rule_window.GetMinSize()
if width < 760 or height < 560:
    raise AssertionError("Rule Manager minimum size is too small")
if rule_window.rule_manager_list.GetItemCount() <= 0:
    raise AssertionError("Rule Manager has no rows")
rule_window.select_row(0)
if not rule_window.rule_picture.GetBitmap().IsOk():
    raise AssertionError("Rule editor did not load a localized hint image")
rule_window.rule_value_text.SetValue("0.111,0.222,999")
if not rule_window.apply_rule_editor():
    raise AssertionError("Rule editor did not accept a valid value")
if rule_window.rule_manager_list.GetTextValue(0, 3) != "0.111,0.222,999":
    raise AssertionError("Rule editor did not update the selected row")
print("rule-manager-ok")
rule_window.Destroy()

result = OfflineDfmAnalysis(
    board,
    select_language_control("English", config),
    rules=rules,
    include_passed_details=True,
).analyze()
economy_result = OfflineDfmAnalysis(
    board,
    select_language_control("English", config),
    rules=economy_rules,
    include_passed_details=True,
).analyze()
precision_result = OfflineDfmAnalysis(
    board,
    select_language_control("English", config),
    rules=precision_rules,
    include_passed_details=True,
).analyze()
economy_rule = economy_result.kicad_result["Smallest Trace Width"]["check"][0]["result"][0]["rule"]
precision_rule = precision_result.kicad_result["Smallest Trace Width"]["check"][0]["result"][0]["rule"]
if economy_rule == precision_rule:
    raise AssertionError("Rule profile switching did not change the active rule")
item_id = first_board_item_id(board)
if not item_id:
    raise AssertionError("No board item UUID available for native DRC marker verification")
can_native_marker = main_window.supports_native_drc_marker_auto_sync()
main_window.analysis_result = {{}}
main_window.kicad_result = synthetic_marker_result(item_id)
exported, skipped = main_window.sync_native_drc_markers()
if can_native_marker:
    if exported <= 0:
        raise AssertionError("Native DRC marker auto sync exported no markers; skipped={{0}}".format(skipped))
else:
    if exported != 0 or skipped != 0:
        raise AssertionError("Native DRC marker auto sync should be disabled on this KiCad version")
cleared = main_window.clear_native_drc_markers()
if cleared != exported:
    raise AssertionError("Native DRC marker clear count mismatch: {{0}} != {{1}}".format(cleared, exported))
detail_window = DfmChildFrame(
    None,
    "Smallest Trace Width",
    result.kicad_result,
    "Smallest Trace Width",
    [],
    1,
    board,
    True,
)
print("detail-window-ok")
detail_window.Destroy()
app.Destroy()
"""


def main():
    parser = argparse.ArgumentParser(description="Verify core wx windows can be constructed.")
    parser.add_argument("--kicad-python", default=r"D:\KiCad\10.0\bin\python.exe")
    parser.add_argument(
        "--board",
        default=r"D:\KiCad\6.0\share\kicad\demos\video\video.kicad_pcb",
    )
    parser.add_argument("--repo", default=os.getcwd())
    args = parser.parse_args()

    script = CHECK_SCRIPT.format(
        repo=os.path.abspath(args.repo).replace("\\", "\\\\"),
        board=os.path.abspath(args.board).replace("\\", "\\\\"),
    )
    result = subprocess.run(
        [args.kicad_python, "-c", textwrap.dedent(script)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    sys.stdout.write(result.stdout)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
