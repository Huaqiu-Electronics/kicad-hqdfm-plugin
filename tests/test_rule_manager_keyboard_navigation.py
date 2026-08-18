import importlib
import sys
import types
import unittest


class RuleManagerKeyboardNavigationTest(unittest.TestCase):
    def setUp(self):
        self.module_names = (
            "wx",
            "wx.dataview",
            "kicad_dfm.manager.ui_rule_manager",
            "kicad_dfm.child_frame.diagram_hint",
            "kicad_dfm.manager.rule_manager_view",
        )
        self.original_modules = {
            name: sys.modules.get(name) for name in self.module_names
        }

        dataview = types.ModuleType("wx.dataview")
        dataview.EVT_DATAVIEW_SELECTION_CHANGED = object()
        dataview.DATAVIEW_CELL_INERT = 0
        dataview.DATAVIEW_COL_RESIZABLE = 0

        wx = types.ModuleType("wx")
        wx.dataview = dataview
        wx.EVT_LEFT_UP = object()
        wx.EVT_LEFT_DCLICK = object()
        wx.EVT_TEXT = object()
        wx.EVT_TEXT_ENTER = object()
        wx.EVT_BUTTON = object()
        wx.ALIGN_CENTER = 0
        wx.ICON_ERROR = 0
        wx.ICON_INFORMATION = 0
        wx.CallAfter = lambda callback: callback()

        ui_module = types.ModuleType("kicad_dfm.manager.ui_rule_manager")
        ui_module.UiRuleManager = object
        diagram_module = types.ModuleType("kicad_dfm.child_frame.diagram_hint")
        diagram_module.diagram_bitmap_for = lambda *args, **kwargs: None

        sys.modules["wx"] = wx
        sys.modules["wx.dataview"] = dataview
        sys.modules["kicad_dfm.manager.ui_rule_manager"] = ui_module
        sys.modules["kicad_dfm.child_frame.diagram_hint"] = diagram_module
        sys.modules.pop("kicad_dfm.manager.rule_manager_view", None)
        self.module = importlib.import_module("kicad_dfm.manager.rule_manager_view")

    def tearDown(self):
        for name, module in self.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_loading_selected_row_does_not_move_focus_to_value_editor(self):
        view = object.__new__(self.module.RuleManagerView)
        view.rule_manager_list = types.SimpleNamespace(
            GetTextValue=lambda row, column: {
                (1, 1): "Category",
                (1, 2): "Rule",
                (1, 3): "0.1,0.2,0.3",
            }[(row, column)]
        )
        view.selected_rule_name = types.SimpleNamespace(
            SetLabel=lambda value: None,
            Wrap=lambda width: None,
        )
        changed_values = []
        view.rule_value_text = types.SimpleNamespace(ChangeValue=changed_values.append)
        updated_rows = []
        view.update_rule_picture = updated_rows.append
        view.focus_rule_editor = lambda: self.fail(
            "changing the selected rule must keep keyboard focus in the rule list"
        )

        view.load_row_into_editor(1)

        self.assertEqual(1, view.selected_row)
        self.assertEqual(["0.1,0.2,0.3"], changed_values)
        self.assertEqual([1], updated_rows)


if __name__ == "__main__":
    unittest.main()
