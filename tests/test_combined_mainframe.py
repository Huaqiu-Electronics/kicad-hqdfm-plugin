import copy
import sys
import types
import unittest
from unittest import mock

from kicad_dfm.core.progress import AnalysisCancelled
from kicad_dfm.services.analysis_results import AnalysisStageResult
from kicad_dfm.services.analysis_results import COMBINED
from kicad_dfm.services.analysis_results import GERBER_ENRICHED
from kicad_dfm.services.analysis_results import GERBER_STRICT
from kicad_dfm.services.analysis_results import KICAD_NATIVE
from kicad_dfm.services.analysis_results import build_analysis_contract
from kicad_dfm.services.export_checks import CATEGORY as GERBER_EXPORT_CATEGORY
from kicad_dfm.services.offline_analysis import COMPAT_CATEGORIES


class CombinedMainframeTest(unittest.TestCase):
    def setUp(self):
        self.original_modules = {
            name: sys.modules.get(name)
            for name in (
                "wx",
                "wx.xrc",
                "wx.dataview",
                "pcbnew",
                "kicad_dfm.child_frame.dfm_child_frame",
                "kicad_dfm.dfm_maindialog.dfm_maindialog_view",
                "kicad_dfm.manager.rule_manager_view",
                "kicad_dfm.hole_childframe.hole_childframe_view",
            )
        }
        fake_dataview = types.SimpleNamespace(
            DataViewCtrl=object,
            DataViewColumn=object,
            DataViewIndexListModel=object,
            DATAVIEW_CELL_ACTIVATABLE=1,
        )

        class Dialog:
            instances = []

            def __init__(self, *args, **kwargs):
                self.args = args
                self.show_count = 0
                Dialog.instances.append(self)

            def ShowModal(self):
                self.show_count += 1

        class Frame:
            def Show(self, show=True):
                self.base_show_count = getattr(self, "base_show_count", 0) + 1
                return bool(show)

        self.Dialog = Dialog
        sys.modules["wx"] = types.SimpleNamespace(
            Frame=Frame,
            Panel=object,
            TopLevelWindow=object,
            DEFAULT_FRAME_STYLE=0,
            MAXIMIZE_BOX=0,
            TAB_TRAVERSAL=0,
            EVT_BUTTON=object(),
            EVT_CLOSE=object(),
            ICON_INFORMATION=0,
            OK=1,
            MessageDialog=Dialog,
            MessageBox=lambda *args, **kwargs: None,
            dataview=fake_dataview,
        )
        sys.modules["wx.xrc"] = types.SimpleNamespace()
        sys.modules["wx.dataview"] = fake_dataview
        sys.modules["pcbnew"] = types.SimpleNamespace(
            PCB_SHAPE=object,
            UpdateUserInterface=lambda: None,
            Refresh=lambda: None,
            GetUserUnits=lambda: 0,
        )
        sys.modules["kicad_dfm.child_frame.dfm_child_frame"] = types.SimpleNamespace(
            DfmChildFrame=object
        )
        sys.modules["kicad_dfm.dfm_maindialog.dfm_maindialog_view"] = types.SimpleNamespace(
            DfmMaindailogView=object
        )
        sys.modules["kicad_dfm.manager.rule_manager_view"] = types.SimpleNamespace(
            RuleManagerView=object
        )
        sys.modules["kicad_dfm.hole_childframe.hole_childframe_view"] = types.SimpleNamespace(
            HoleChildFrameView=object
        )
        sys.modules.pop("kicad_dfm.dfm_mainframe", None)

    def tearDown(self):
        sys.modules.pop("kicad_dfm.dfm_mainframe", None)
        for name, module in self.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_summary_column_widths_are_saved_for_the_next_window(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.settings = {"rule_profile": "standard"}
        frame.dfm_maindialog = types.SimpleNamespace(
            summary_column_widths=lambda: [245, 180, 85]
        )

        with mock.patch.object(mainframe_module, "save_settings") as save:
            frame.persist_summary_column_widths()

        self.assertEqual([245, 180, 85], frame.settings["summary_column_widths"])
        save.assert_called_once_with(frame.settings)

    def test_gerber_file_issues_open_one_conditional_dialog(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        issue = types.SimpleNamespace(
            severity="error",
            item="Missing Drill File",
            message="board-PTH.drl is missing.",
        )
        summary = {
            GERBER_EXPORT_CATEGORY: types.SimpleNamespace(issues=(issue,))
        }
        frame = object.__new__(DfmMainframe)

        with mock.patch.object(mainframe_module, "_", side_effect=lambda value: value):
            self.assertFalse(frame.show_gerber_export_issues({}))
            self.assertEqual([], self.Dialog.instances)

            self.assertTrue(frame.show_gerber_export_issues(summary))

        self.assertEqual(1, len(self.Dialog.instances))
        dialog = self.Dialog.instances[0]
        self.assertEqual("Gerber File Integrity", dialog.args[2])
        self.assertIn("Missing Drill File", dialog.args[1])
        self.assertEqual(1, dialog.show_count)

    def test_combined_entry_has_one_lifecycle_and_one_success_dialog(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        category = "Hole Size"
        native_map = {
            category: {
                "display": 0.2,
                "color": "red",
                "check": [{"result": [{"id": "uuid-1", "item": "Smallest Drill Size", "color": "red"}]}],
            }
        }
        gerber_map = {
            category: {
                "display": 0.19999,
                "color": "red",
                "check": [{"result": [{"id": "uuid-1", "item": "Smallest Drill Size", "color": "red"}]}],
            }
        }
        strict_contract = build_analysis_contract(GERBER_STRICT, gerber_map)
        native_stage = AnalysisStageResult(KICAD_NATIVE, native_map)
        gerber_stage = AnalysisStageResult(
            GERBER_ENRICHED,
            gerber_map,
            input_paths=("F_Cu.gbr",),
            source_views={
                GERBER_STRICT: {
                    "analysis_result": gerber_map,
                    "contract": strict_contract,
                }
            },
        )
        call_order = []
        workflow = types.SimpleNamespace(
            parsing_count=0,
            done_count=0,
        )
        workflow.parsing = lambda: setattr(
            workflow, "parsing_count", workflow.parsing_count + 1
        )
        workflow.done = lambda: setattr(workflow, "done_count", workflow.done_count + 1)

        frame = object.__new__(DfmMainframe)
        frame.workflow = workflow
        frame.current_rules = lambda: {"Hole Size": ()}
        def analyze_native(_rules, progress):
            call_order.append(KICAD_NATIVE)
            progress(1, 1, "Native complete")
            return native_stage

        def analyze_gerber(_rules, progress, analysis_progress):
            call_order.append(GERBER_ENRICHED)
            progress(1, 1, "Gerber export complete")
            analysis_progress(1, 1, "Gerber analysis complete")
            return gerber_stage

        frame._analyze_native_stage = analyze_native
        frame._analyze_gerber_stage = analyze_gerber
        progress_updates = []
        frame.update_analysis_progress = lambda *args: progress_updates.append(args) or True
        frame.dfm_analysis = types.SimpleNamespace(dfm_issues=(), dfm_summary={})
        saved_modes = []
        frame.save_analysis_snapshot = lambda mode, *args, **kwargs: saved_modes.append(mode)
        frame.add_all_item = lambda **kwargs: None
        frame.sync_native_drc_markers = lambda: (0, 0)

        frame.run_combined_analysis()

        self.assertEqual([KICAD_NATIVE, GERBER_ENRICHED], call_order)
        self.assertEqual(1, workflow.parsing_count)
        self.assertEqual(1, workflow.done_count)
        self.assertEqual([KICAD_NATIVE, COMBINED], saved_modes)
        percentages = [current for current, _total, _item in progress_updates]
        self.assertEqual(sorted(percentages), percentages)
        self.assertEqual(100, percentages[-1])
        self.assertEqual(COMBINED, frame.analysis_contract["mode"])
        self.assertEqual(
            {KICAD_NATIVE, GERBER_STRICT, GERBER_ENRICHED},
            set(frame.source_views),
        )
        self.assertEqual(1, len(self.Dialog.instances))
        self.assertEqual(1, self.Dialog.instances[0].show_count)

    def test_initial_data_view_defers_saved_analysis_restore(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.board = types.SimpleNamespace(
            GetVisibleLayers=lambda: "layers",
            GetVisibleElements=lambda: "elements",
        )
        frame.dfm_maindialog = types.SimpleNamespace(init_data_view=mock.Mock())
        frame.schedule_saved_analysis_load = mock.Mock()
        frame.load_saved_analysis = mock.Mock(
            side_effect=AssertionError("cache restore ran synchronously")
        )
        summary = {"Signal Integrity": {"display": "", "color": ""}}

        with mock.patch.object(mainframe_module, "default_summary_map", return_value=summary):
            frame.init_data_view()

        self.assertEqual("layers", frame.gal_set)
        self.assertEqual("elements", frame.ele_gal_set)
        frame.dfm_maindialog.init_data_view.assert_called_once_with(summary)
        frame.schedule_saved_analysis_load.assert_not_called()
        frame.load_saved_analysis.assert_not_called()

    def test_normal_signal_result_clears_stale_abnormal_headline(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        signal = {
            "display": "正常",
            "color": "red",
            "violation_count": 0,
            "check": [{"result": []}],
        }
        frame = object.__new__(DfmMainframe)
        frame.analysis_result = {"Signal Integrity": signal}
        frame.json_analysis_map = {
            "Signal Integrity": {"display": "异常", "color": "red"}
        }
        frame.item_result = "no errors detected"

        with mock.patch.object(mainframe_module, "_", side_effect=lambda value: value):
            frame.apply_signal_integrity_summary()

        self.assertEqual(
            {"display": "no errors detected", "color": ""},
            frame.json_analysis_map["Signal Integrity"],
        )
        self.assertFalse(
            frame.has_detail_result(
                frame.analysis_result,
                "Signal Integrity",
            )
        )

    def test_signal_summary_and_detail_share_visible_violation_semantics(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        for color in ("red", "gold"):
            with self.subTest(color=color):
                signal = {
                    "display": "",
                    "color": color,
                    "violation_count": 1,
                    "check": [
                        {
                            "result": [
                                {
                                    "item": "Dangling Tracks",
                                    "color": color,
                                    "layer": ["F.Cu"],
                                }
                            ]
                        }
                    ],
                }
                frame = object.__new__(DfmMainframe)
                frame.analysis_result = {"Signal Integrity": signal}
                frame.json_analysis_map = {
                    "Signal Integrity": {"display": "", "color": ""}
                }
                frame.item_result = "no errors detected"

                with mock.patch.object(
                    mainframe_module,
                    "_",
                    side_effect=lambda value: value,
                ):
                    frame.apply_signal_integrity_summary()

                self.assertEqual(
                    {"display": "Error(s) detected", "color": color},
                    frame.json_analysis_map["Signal Integrity"],
                )
                self.assertTrue(
                    frame.has_detail_result(
                        frame.analysis_result,
                        "Signal Integrity",
                    )
                )

    def test_legacy_signal_result_without_count_uses_row_severity(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        signal = {
            "display": "legacy",
            "color": "black",
            "check": [{"result": [{"severity": "warning"}]}],
        }
        frame = object.__new__(DfmMainframe)

        self.assertEqual("gold", frame.result_violation_color(signal))
        self.assertTrue(
            frame.has_detail_result(
                {"Signal Integrity": signal},
                "Signal Integrity",
            )
        )

    def test_first_show_queues_cache_restore_after_show_returns(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._startup_cache_restore_scheduled = False
        frame.board = object()
        frame.dfm_maindialog = object()
        frame.schedule_saved_analysis_load = mock.Mock()
        queued = []

        with mock.patch.object(
            mainframe_module.wx,
            "CallAfter",
            side_effect=lambda callback, *args: queued.append((callback, args)),
            create=True,
        ):
            self.assertTrue(frame.Show())
            self.assertEqual(1, frame.base_show_count)
            frame.schedule_saved_analysis_load.assert_not_called()
            self.assertEqual(1, len(queued))

            callback, args = queued.pop()
            callback(*args)
            frame.schedule_saved_analysis_load.assert_called_once_with()

            frame.Show()
            self.assertEqual([], queued)

    def test_stale_background_cache_result_is_not_applied(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._saved_analysis_load_generation = 2
        frame._closing = False
        frame.apply_saved_analysis = mock.Mock()
        request = {"generation": 1}

        applied = frame._finish_saved_analysis_load(
            request,
            {"analysis_result": {"stale": True}},
        )

        self.assertFalse(applied)
        frame.apply_saved_analysis.assert_not_called()

    def test_dirty_board_rejects_background_cache_result(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._saved_analysis_load_generation = 1
        frame._closing = False
        frame.workflow = types.SimpleNamespace(running=False)
        frame.analysis_result = {}
        frame.board = types.SimpleNamespace(IsModified=lambda: True)
        frame.IsBeingDeleted = lambda: False

        self.assertFalse(
            frame._saved_analysis_request_is_current({"generation": 1})
        )

    def test_destroying_frame_rejects_queued_cache_callback(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._saved_analysis_load_generation = 1
        frame._closing = False
        frame.IsBeingDeleted = lambda: True

        self.assertFalse(
            frame._saved_analysis_request_is_current({"generation": 1})
        )

    def test_background_restore_requests_latest_valid_bounded_cache(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._finish_saved_analysis_load = mock.Mock()
        request = {
            "board_path": "board.kicad_pcb",
            "profile_id": "standard",
            "language": "English",
            "rules": {"Signal Integrity": ()},
        }

        with (
            mock.patch.object(
                mainframe_module,
                "load_analysis_cache",
                return_value=None,
            ) as loader,
            mock.patch.object(
                mainframe_module.wx,
                "CallAfter",
                side_effect=lambda callback, *args: callback(*args),
                create=True,
            ),
        ):
            frame._load_saved_analysis_worker(request)

        loader.assert_called_once_with(
            "board.kicad_pcb",
            "standard",
            "English",
            rules={"Signal Integrity": ()},
            max_payload_bytes=mainframe_module.STARTUP_CACHE_MAX_BYTES,
        )
        frame._finish_saved_analysis_load.assert_called_once_with(
            request,
            None,
            None,
        )

    def test_begin_analysis_invalidates_background_cache_result(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._saved_analysis_load_generation = 3
        frame._analysis_cancel_requested = True
        frame.set_run_enabled = mock.Mock()
        frame.dfm_maindialog = types.SimpleNamespace(begin_check_progress=mock.Mock())

        frame.begin_analysis_progress()

        self.assertEqual(4, frame._saved_analysis_load_generation)
        self.assertFalse(frame._analysis_cancel_requested)
        frame.set_run_enabled.assert_called_once_with(False)
        frame.dfm_maindialog.begin_check_progress.assert_called_once_with()

    def test_online_sparse_results_complete_compat_before_legacy_ui(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        hole_result = {"display": 0.2, "color": "red", "check": []}
        stage = AnalysisStageResult(
            GERBER_ENRICHED,
            {"Hole Size": hole_result},
            kicad_result={"Hole Size": hole_result},
            input_paths=("board-PTH.drl",),
        )
        workflow = types.SimpleNamespace(parsing_count=0, done_count=0)
        workflow.parsing = lambda: setattr(
            workflow, "parsing_count", workflow.parsing_count + 1
        )
        workflow.done = lambda: setattr(
            workflow, "done_count", workflow.done_count + 1
        )
        frame = object.__new__(DfmMainframe)
        frame._analysis_cancel_requested = False
        frame.workflow = workflow
        frame.current_rules = lambda: {"Hole Size": ()}
        def analyze_gerber(_rules, progress, analysis_progress):
            progress(0, 2, "Saving board")
            progress(2, 2, "Exporting fabrication files")
            analysis_progress(0, 100, "Scanning exported geometry")
            analysis_progress(100, 100, "Finalizing results")
            return stage

        frame._analyze_gerber_stage = analyze_gerber
        progress_updates = []
        frame.update_analysis_progress = lambda *args: progress_updates.append(args) or True
        frame.update_export_analysis_progress = lambda *_args: True
        frame.dfm_analysis = types.SimpleNamespace(dfm_issues=(), dfm_summary={})
        ui_calls = []

        def add_all_item(**kwargs):
            ui_calls.append(kwargs)
            for category in COMPAT_CATEGORIES:
                frame.analysis_result[category]
            for category in ("Smallest Trace Width", "Pad size", "RingHole"):
                frame.kicad_result[category]

        frame.add_all_item = add_all_item
        frame.sync_native_drc_markers = lambda: (0, 0)
        saved = []
        frame.save_analysis_snapshot = lambda *args, **kwargs: saved.append(args)

        frame.run_online_analysis()

        self.assertEqual(set(COMPAT_CATEGORIES), set(frame.analysis_result))
        self.assertEqual(set(COMPAT_CATEGORIES), set(frame.kicad_result))
        self.assertEqual(1, len(ui_calls))
        self.assertEqual(1, len(saved))
        self.assertEqual(set(COMPAT_CATEGORIES), set(saved[0][1]))
        self.assertEqual(set(COMPAT_CATEGORIES), set(saved[0][2]))
        percentages = [current for current, _total, _item in progress_updates]
        self.assertEqual(sorted(percentages), percentages)
        self.assertEqual(100, percentages[-1])
        self.assertEqual(1, workflow.done_count)
        self.assertEqual(1, len(self.Dialog.instances))

    def test_rule_profile_change_replaces_combined_state_with_native_stage(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        native_map = {category: "" for category in COMPAT_CATEGORIES}
        native_map["Hole Size"] = {
            "display": 0.25,
            "color": "gold",
            "check": [],
        }
        native_contract = build_analysis_contract(
            KICAD_NATIVE,
            native_map,
            categories=COMPAT_CATEGORIES,
        )
        native_stage = AnalysisStageResult(
            KICAD_NATIVE,
            native_map,
            kicad_result=native_map,
            summary={"Hole Size": object()},
            contract=native_contract,
        )
        event = types.SimpleNamespace(skipped=False)
        event.Skip = lambda: setattr(event, "skipped", True)
        frame = object.__new__(DfmMainframe)
        frame.settings = {"rule_profile": "standard"}
        frame.rule_profile_ids = ["standard", "precision"]
        frame.selected_rule_profile_index = lambda: 1
        frame.analysis_result = {"Hole Size": {"display": 0.2}}
        frame.analysis_contract = {"mode": COMBINED}
        frame.source_views = {COMBINED: {"stale": True}}
        frame.analysis_cache_input_paths = ("stale-F_Cu.gbr",)
        frame.dfm_analysis = types.SimpleNamespace(
            dfm_issues=("stale-gerber-issue",),
            dfm_summary={GERBER_EXPORT_CATEGORY: object()},
        )
        frame.json_analysis_map = {}
        frame._analyze_native_stage = lambda _rules, _progress=None: native_stage
        ui_calls = []
        frame.add_all_item = lambda **kwargs: ui_calls.append(kwargs)
        marker_calls = []
        frame.sync_native_drc_markers = lambda: marker_calls.append(True)

        with mock.patch.object(mainframe_module, "save_settings"):
            frame.on_rule_profile_changed(event)

        self.assertEqual("precision", frame.settings["rule_profile"])
        self.assertEqual(KICAD_NATIVE, frame.analysis_contract["mode"])
        self.assertEqual({KICAD_NATIVE}, set(frame.source_views))
        self.assertEqual((), frame.analysis_cache_input_paths)
        self.assertNotIn(GERBER_EXPORT_CATEGORY, frame.dfm_analysis.dfm_summary)
        self.assertNotIn(GERBER_EXPORT_CATEGORY, frame.json_analysis_map)
        self.assertEqual([{"use_existing_kicad_result": True}], ui_calls)
        self.assertEqual([True], marker_calls)
        self.assertTrue(event.skipped)

    def test_online_stop_after_ui_commit_prevents_cache_and_success(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        stage = AnalysisStageResult(
            GERBER_ENRICHED,
            {category: "" for category in COMPAT_CATEGORIES},
            input_paths=("F_Cu.gbr",),
        )
        workflow = types.SimpleNamespace(parsing_count=0, done_count=0)
        workflow.parsing = lambda: setattr(
            workflow, "parsing_count", workflow.parsing_count + 1
        )
        workflow.done = lambda: setattr(
            workflow, "done_count", workflow.done_count + 1
        )
        frame = object.__new__(DfmMainframe)
        frame._analysis_cancel_requested = False
        frame.workflow = workflow
        frame.current_rules = lambda: {}
        frame._analyze_gerber_stage = lambda *_args: stage
        frame.update_analysis_progress = lambda *_args: True
        frame.update_export_analysis_progress = lambda *_args: True
        frame.dfm_analysis = types.SimpleNamespace(dfm_issues=(), dfm_summary={})
        frame.add_all_item = lambda **_kwargs: setattr(
            frame, "_analysis_cancel_requested", True
        )
        marker_calls = []
        frame.sync_native_drc_markers = lambda: marker_calls.append(True)
        saved = []
        frame.save_analysis_snapshot = lambda *args, **kwargs: saved.append(args)

        with self.assertRaises(AnalysisCancelled):
            frame.run_online_analysis()

        self.assertEqual([], saved)
        self.assertEqual([], marker_calls)
        self.assertEqual(0, workflow.done_count)
        self.assertEqual([], self.Dialog.instances)

    def test_gerber_enrichment_heartbeat_honors_stop_before_mapping(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame._analysis_cancel_requested = False
        frame.board = types.SimpleNamespace(GetFileName=lambda: "board.kicad_pcb")
        frame.backend = types.SimpleNamespace(board_thickness_mm=lambda: 1.6)
        frame.language = "English"
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)
        frame.output_gerber_dir = lambda: "HQDMF"
        mapped = []
        frame.map_gerber_native_result_rows = lambda *_args, **_kwargs: mapped.append(True)
        export_result = types.SimpleNamespace(files=(), zip_path="")
        enrichment_updates = []

        def enrichment_progress(completed, total, item):
            enrichment_updates.append((completed, total, item))
            return item != "Enriching Gerber results"

        with (
            mock.patch.object(mainframe_module.pcbnew, "SaveBoard", create=True),
            mock.patch.object(mainframe_module.os.path, "exists", return_value=False),
            mock.patch.object(
                mainframe_module,
                "export_fabrication_package",
                return_value=export_result,
            ),
            mock.patch.object(
                mainframe_module,
                "analyze_export_with_results",
                return_value=((), {}, {"Hole Size": ""}, {}),
            ),
        ):
            with self.assertRaises(AnalysisCancelled):
                frame._analyze_gerber_stage(
                    {},
                    progress_callback=lambda *_args: True,
                    analysis_progress_callback=enrichment_progress,
                )

        self.assertEqual([], mapped)
        self.assertEqual("Enriching Gerber results", enrichment_updates[-1][2])

    def test_sparse_gerber_stage_completes_compat_contract_and_results(self):
        import kicad_dfm.dfm_mainframe as mainframe_module
        from kicad_dfm.dfm_mainframe import DfmMainframe

        hole_result = {"display": 0.2, "color": "red", "check": []}
        frame = object.__new__(DfmMainframe)
        frame._analysis_cancel_requested = False
        frame.board = types.SimpleNamespace(GetFileName=lambda: "board.kicad_pcb")
        frame.backend = types.SimpleNamespace(board_thickness_mm=lambda: 1.6)
        frame.language = "English"
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)
        frame.output_gerber_dir = lambda: "HQDMF"
        frame.map_gerber_native_result_rows = lambda *_args, **_kwargs: None
        export_result = types.SimpleNamespace(
            files=("board-PTH.drl",),
            zip_path="board.zip",
        )
        analysis_updates = []

        def analyze_export(*_args, progress_callback=None, **_kwargs):
            progress_callback(0, 4, "Scanning exported geometry")
            progress_callback(4, 4, "Checking solder mask")
            return (), {}, {"Hole Size": hole_result}, {}

        with (
            mock.patch.object(mainframe_module.pcbnew, "SaveBoard", create=True),
            mock.patch.object(mainframe_module.os.path, "exists", return_value=False),
            mock.patch.object(
                mainframe_module,
                "export_fabrication_package",
                return_value=export_result,
            ),
            mock.patch.object(
                mainframe_module,
                "analyze_export_with_results",
                side_effect=analyze_export,
            ),
        ):
            stage = frame._analyze_gerber_stage(
                {},
                progress_callback=lambda *_args: True,
                analysis_progress_callback=lambda *args: analysis_updates.append(args) or True,
            )

        self.assertEqual(set(COMPAT_CATEGORIES), set(stage.analysis_result))
        self.assertEqual(set(COMPAT_CATEGORIES), set(stage.kicad_result))
        self.assertEqual(
            set(COMPAT_CATEGORIES),
            set(stage.contract["categories"]),
        )
        self.assertEqual(
            set(COMPAT_CATEGORIES),
            set(stage.source_views[GERBER_STRICT]["analysis_result"]),
        )
        self.assertEqual(("board-PTH.drl", "board.zip"), stage.input_paths)
        percentages = [current for current, _total, _item in analysis_updates]
        self.assertEqual(sorted(percentages), percentages)
        self.assertEqual(100, percentages[-1])

    def test_combined_stop_before_merge_prevents_cache_and_success(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        native_stage = AnalysisStageResult(
            KICAD_NATIVE,
            {category: "" for category in COMPAT_CATEGORIES},
        )
        gerber_stage = AnalysisStageResult(
            GERBER_ENRICHED,
            {category: "" for category in COMPAT_CATEGORIES},
        )
        workflow = types.SimpleNamespace(parsing=lambda: None, done_count=0)
        workflow.done = lambda: setattr(
            workflow, "done_count", workflow.done_count + 1
        )
        frame = object.__new__(DfmMainframe)
        frame._analysis_cancel_requested = False
        frame.workflow = workflow
        frame.current_rules = lambda: {}
        frame.update_analysis_progress = lambda *_args: True
        frame._analyze_native_stage = lambda *_args: native_stage

        def cancel_after_gerber(*_args):
            frame._analysis_cancel_requested = True
            return gerber_stage

        frame._analyze_gerber_stage = cancel_after_gerber
        frame.dfm_analysis = types.SimpleNamespace(dfm_issues=(), dfm_summary={})
        frame.add_all_item = lambda **_kwargs: None
        frame.sync_native_drc_markers = lambda: None
        saved = []
        frame.save_analysis_snapshot = lambda *args, **kwargs: saved.append(args)

        with self.assertRaises(AnalysisCancelled):
            frame.run_combined_analysis()

        self.assertEqual([], saved)
        self.assertEqual(0, workflow.done_count)
        self.assertEqual([], self.Dialog.instances)

    def test_gerber_uuid_enrichment_preserves_measurement_provenance(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        track = types.SimpleNamespace(
            item_id="track-uuid",
            start=(1000000, 1000000),
            end=(9000000, 1000000),
            layer="F.Cu",
        )

        class Backend:
            def iter_tracks(self):
                return iter((track,))

            def iter_vias(self):
                return iter(())

            def iter_footprints(self):
                return iter(())

            def iter_pads(self, _footprint):
                return iter(())

            def iter_drawings(self):
                return iter(())

            def item_id(self, item):
                return item.item_id

            def item_layer_name(self, item):
                return item.layer

            def item_width(self, _item):
                return 100000

            def item_bbox(self, item):
                return (900000, 900000, 9100000, 1100000)

            def item_position(self, item):
                return (5000000, 1000000)

            def track_segment(self, item):
                return item.start, item.end

        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = Backend()
        frame.logger = types.SimpleNamespace(debug=lambda *args, **kwargs: None)
        result = {
            "check": [
                {
                    "result": [
                        {
                            "id": "board-CuTop.gbr",
                            "source": "gerber",
                            "item_type": "gerber",
                            "layer": ["F.Cu"],
                            "value": "0.100000",
                            "message": "strict Gerber width",
                            "geometry_basis": "gerber_derived",
                            "raw": {
                                "segment": ((1.0, 1.0), (9.0, 1.0)),
                                "measurement_basis": "gerber",
                            },
                        }
                    ]
                }
            ]
        }

        frame.map_gerber_native_result_rows(result)

        row = result["check"][0]["result"][0]
        self.assertEqual("track-uuid", row["id"])
        self.assertEqual("0.100000", row["value"])
        self.assertEqual("strict Gerber width", row["message"])
        self.assertEqual("gerber_derived", row["geometry_basis"])
        self.assertEqual("gerber", row["raw"]["measurement_basis"])
        self.assertEqual("kicad_hit_test", row["raw"]["location_basis"])

    def test_enrichment_suppresses_only_zero_clearance_local_net_tie_contact(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        class Item:
            def __init__(self, item_id, net_name, kind="pad"):
                self.item_id = item_id
                self.net_name = net_name
                self.kind = kind

        items = {
            item.item_id: item
            for item in (
                Item("nt-a", "A"),
                Item("nt-b", "B"),
                Item("gap-a", "C"),
                Item("gap-b", "D"),
            )
        }
        clearances = {
            frozenset(("nt-a", "nt-b")): 0,
            frozenset(("gap-a", "gap-b")): 50000,
        }

        class Backend:
            def net_tie_pad_groups(self):
                return (
                    (("nt-a", "A"), ("nt-b", "B")),
                    (("gap-a", "C"), ("gap-b", "D")),
                )

            def resolve_item(self, item_id):
                return items.get(item_id)

            def item_net_name(self, item):
                return item.net_name

            def item_clearance_nm(self, left, right, _maximum):
                return clearances[frozenset((left.item_id, right.item_id))]

            def is_pad(self, item):
                return item.kind == "pad"

            def is_track(self, item):
                return item.kind == "track"

        def spacing_row(left_id, right_id, value):
            return {
                "id": left_id,
                "related_id": right_id,
                "source": "gerber",
                "item": "Pad-to-Pad Spacing",
                "rule_key": "smallesttracespacing:padtopadspacing",
                "layer": ["F.Cu"],
                "value": value,
                "color": "red",
                "raw": {"related": {}},
            }

        stable_key = "smallesttracespacing:padtopadspacing"
        strict = {
            "display": 0.0,
            "color": "red",
            "checked_count": 2,
            "available_count": 2,
            "violation_count": 2,
            "suppressed_count": 0,
            "displayed_count": 2,
            "visible_count": 2,
            "execution_status": "completed",
            "item_summaries": {
                stable_key: {
                    "rule_key": stable_key,
                    "item": "Pad-to-Pad Spacing",
                    "checked_count": 2,
                    "available_count": 2,
                    "violation_count": 2,
                    "suppressed_count": 0,
                    "displayed_count": 2,
                    "visible_count": 2,
                    "execution_status": "completed",
                    "color": "red",
                    "display": 0.0,
                }
            },
            "check": [
                {"result": [spacing_row("nt-a", "nt-b", "0.000000")]},
                {"result": [spacing_row("gap-a", "gap-b", "0.050000")]},
            ],
        }
        enriched = copy.deepcopy(strict)
        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = Backend()
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)

        frame.map_gerber_native_result_rows(enriched)

        self.assertEqual(2, len(strict["check"]))
        rows = [row for check in enriched["check"] for row in check["result"]]
        self.assertEqual([("gap-a", "gap-b")], [(row["id"], row["related_id"]) for row in rows])
        self.assertEqual(0.05, enriched["display"])
        self.assertEqual("red", enriched["color"])
        self.assertEqual(2, enriched["checked_count"])
        self.assertEqual(2, enriched["available_count"])
        self.assertEqual(1, enriched["violation_count"])
        self.assertEqual(1, enriched["displayed_count"])
        self.assertEqual(1, enriched["visible_count"])
        self.assertEqual(1, enriched["suppressed_count"])
        self.assertEqual(
            {"local_net_tie_contact": 1},
            enriched["suppression_reasons"],
        )
        summary = enriched["item_summaries"][stable_key]
        self.assertEqual(2, summary["checked_count"])
        self.assertEqual(1, summary["violation_count"])
        self.assertEqual(1, summary["displayed_count"])
        self.assertEqual(1, summary["suppressed_count"])
        self.assertEqual(0.05, summary["display"])

    def test_smd_spacing_uses_declared_and_local_attachment_net_tie_scope(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        class Item:
            def __init__(self, item_id, net_name, layer="F.Cu"):
                self.item_id = item_id
                self.net_name = net_name
                self.layer = layer

        member_a = Item("member-a", "A")
        member_b = Item("member-b", "B")
        attached_a = Item("attached-a", "A")
        far_a = Item("far-a", "A")
        cross_layer_a = Item("cross-layer-a", "A", "B.Cu")
        items = {
            item.item_id: item
            for item in (member_a, member_b, attached_a, far_a, cross_layer_a)
        }
        clearances = {
            frozenset(("member-a", "member-b")): 30000,
            frozenset(("attached-a", "member-a")): 8680,
            frozenset(("attached-a", "member-b")): 37969,
            frozenset(("far-a", "member-a")): 12000,
            frozenset(("far-a", "member-b")): 30000,
            frozenset(("cross-layer-a", "member-a")): 0,
            frozenset(("cross-layer-a", "member-b")): 30000,
        }

        class Backend:
            def net_tie_pad_groups(self):
                return ((("member-a", "A"), ("member-b", "B")),)

            def resolve_item(self, item_id):
                return items.get(item_id)

            def item_id(self, item):
                return item.item_id

            def item_net_name(self, item):
                return item.net_name

            def item_clearance_nm(self, left, right, _maximum):
                return clearances[frozenset((left.item_id, right.item_id))]

            def item_local_clearance_nm(self, item):
                return 10000 if item.item_id == "member-a" else 0

            def pad_copper_layer_ids(self, item):
                return (item.layer,)

            def is_pad(self, _item):
                return True

            def is_track(self, _item):
                return False

        frame = object.__new__(DfmMainframe)
        frame.backend = Backend()
        groups = frame._gerber_net_tie_groups_by_pad_id()

        self.assertTrue(
            frame._is_local_net_tie_item_contact(
                member_a,
                member_b,
                groups,
                clearance_nm=30000,
                allow_positive_pad_gap=True,
            )
        )
        self.assertTrue(
            frame._is_local_net_tie_item_contact(
                attached_a,
                member_b,
                groups,
                clearance_nm=37969,
                allow_positive_pad_gap=True,
            )
        )
        self.assertFalse(
            frame._is_local_net_tie_item_contact(
                far_a,
                member_b,
                groups,
                clearance_nm=30000,
                allow_positive_pad_gap=True,
            )
        )
        self.assertFalse(
            frame._is_local_net_tie_item_contact(
                cross_layer_a,
                member_b,
                groups,
                clearance_nm=30000,
                allow_positive_pad_gap=True,
            )
        )
        self.assertFalse(
            frame._is_local_net_tie_item_contact(
                member_a,
                member_b,
                groups,
                clearance_nm=30000,
                allow_positive_pad_gap=False,
            )
        )

    def test_enrichment_keeps_non_authoritative_net_tie_relations(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        class Item:
            def __init__(self, item_id, net_name, kind="pad"):
                self.item_id = item_id
                self.net_name = net_name
                self.kind = kind

        declared_a = Item("nt-a", "A")
        declared_b = Item("nt-b", "B")
        positive_a = Item("positive-a", "A")
        positive_b = Item("positive-b", "B")
        same_a = Item("same-a", "A")
        same_b = Item("same-b", "A")
        remote_a = Item("remote-a", "A")
        remote_b = Item("remote-b", "B")
        items = {
            item.item_id: item
            for item in (
                declared_a,
                declared_b,
                positive_a,
                positive_b,
                same_a,
                same_b,
                remote_a,
                remote_b,
            )
        }

        class Backend:
            def net_tie_pad_groups(self):
                return ((('nt-a', 'A'), ('nt-b', 'B')),)

            def resolve_item(self, item_id):
                return items.get(item_id)

            def item_net_name(self, item):
                return item.net_name

            def item_clearance_nm(self, left, right, _maximum):
                if {left.item_id, right.item_id} == {"nt-a", "nt-b"}:
                    return 50000
                return 0

            def is_pad(self, item):
                return item.kind == "pad"

            def is_track(self, item):
                return item.kind == "track"

        def result_for(left_id, right_id):
            return {
                "display": 0.0,
                "color": "red",
                "execution_status": "completed",
                "check": [{
                    "result": [{
                        "id": left_id,
                        "related_id": right_id,
                        "source": "gerber",
                        "item": "SMD Pad Spacing",
                        "rule_key": "smdspacing:smdpadspacing",
                        "layer": ["F.Cu"],
                        "value": "0.000000",
                        "color": "red",
                        "raw": {"related": {}},
                    }]
                }],
            }

        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = Backend()
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)

        for name, pair, expected_count in (
            ("positive_declared_smd_gap", ("nt-a", "nt-b"), 0),
            ("same_net", ("same-a", "same-b"), 1),
            ("same_nets_elsewhere", ("remote-a", "remote-b"), 1),
            ("unresolved_mapping", ("missing-a", "missing-b"), 1),
        ):
            with self.subTest(name=name):
                result = result_for(*pair)
                frame.map_gerber_native_result_rows(result)
                rows = [row for check in result["check"] for row in check["result"]]
                self.assertEqual(expected_count, len(rows))

    def test_enrichment_suppresses_track_contact_at_declared_net_tie_pad(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        anchor = types.SimpleNamespace(item_id="anchor-a", net_name="A", kind="pad")
        pad = types.SimpleNamespace(item_id="tie-pad-b", net_name="B", kind="pad")
        track = types.SimpleNamespace(item_id="track-a", net_name="A", kind="track")
        items = {item.item_id: item for item in (anchor, pad, track)}

        class Backend:
            def net_tie_pad_groups(self):
                return ((('anchor-a', 'A'), ('tie-pad-b', 'B')),)

            def resolve_item(self, item_id):
                return items.get(item_id)

            def item_net_name(self, item):
                return item.net_name

            def item_clearance_nm(self, _left, _right, _maximum):
                return 0

            def is_pad(self, item):
                return item.kind == "pad"

            def is_track(self, item):
                return item.kind == "track"

        result = {
            "display": 0.0,
            "color": "red",
            "checked_count": 1,
            "violation_count": 1,
            "displayed_count": 1,
            "execution_status": "completed",
            "check": [{
                "result": [{
                    "id": "track-a",
                    "related_id": "tie-pad-b",
                    "source": "gerber",
                    "item": "Trace-to-Pad Spacing",
                    "rule_key": "smallesttracespacing:tracetopadspacing",
                    "layer": ["F.Cu"],
                    "value": "0.000000",
                    "color": "red",
                    "raw": {"related": {}},
                }]
            }],
        }
        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = Backend()
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)

        frame.map_gerber_native_result_rows(result)

        self.assertEqual([], result["check"])
        self.assertEqual("正常", result["display"])
        self.assertEqual("black", result["color"])
        self.assertEqual(0, result["violation_count"])
        self.assertEqual(1, result["suppressed_count"])
        summary = result["item_summaries"][
            "smallesttracespacing:tracetopadspacing"
        ]
        self.assertEqual(1, summary["checked_count"])
        self.assertEqual(0, summary["displayed_count"])
        self.assertEqual(1, summary["suppressed_count"])

    def test_enrichment_uses_gerber_value_to_resolve_ambiguous_net_tie_pads(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        anchor_a = types.SimpleNamespace(item_id="anchor-a", net_name="A", kind="pad")
        member_a = types.SimpleNamespace(item_id="ordinary-a", net_name="A", kind="pad")
        member_b = types.SimpleNamespace(item_id="member-b", net_name="B", kind="pad")
        decoy_b = types.SimpleNamespace(item_id="decoy-b", net_name="B", kind="pad")

        def mapping(status, item=None):
            return types.SimpleNamespace(
                status=status,
                item=item,
                item_id=getattr(item, "item_id", ""),
                confidence=1.0,
                reason="test",
            )

        class Mapper:
            def map_pair(self, _row):
                return mapping("matched", member_a), mapping("ambiguous")

            def map_pair_candidates(self, _row):
                return (
                    (mapping("matched", member_a),),
                    (mapping("matched", member_b), mapping("matched", decoy_b)),
                )

            def apply_mapping(self, row):
                row["id"] = member_a.item_id
                row.setdefault("raw", {})["uuid_mapping"] = {
                    "status": "matched",
                    "id": member_a.item_id,
                    "related": {
                        "status": "ambiguous",
                        "reason": "multiple_candidates",
                    },
                }
                return mapping("matched", member_a)

        class Backend:
            def net_tie_pad_groups(self):
                return ((("anchor-a", "A"), ("member-b", "B")),)

            def item_id(self, item):
                return item.item_id

            def item_net_name(self, item):
                return item.net_name

            def item_clearance_nm(self, left, right, _maximum):
                if {left.item_id, right.item_id} == {"ordinary-a", "anchor-a"}:
                    return 8680
                if {left.item_id, right.item_id} == {"ordinary-a", "member-b"}:
                    return 37969
                return 200000

            def item_local_clearance_nm(self, item):
                return 10000 if item.item_id == "anchor-a" else 0

            def is_pad(self, item):
                return item.kind == "pad"

            def is_track(self, item):
                return item.kind == "track"

            def resolve_item(self, item_id):
                return {
                    "anchor-a": anchor_a,
                    "ordinary-a": member_a,
                    "member-b": member_b,
                    "decoy-b": decoy_b,
                }.get(item_id)

        row = {
            "id": "F_Cu.gbr",
            "related_id": "F_Cu.gbr",
            "source": "gerber",
            "item": "SMD Pad Spacing",
            "rule_key": "smdspacing:smdpadspacing",
            "layer": ["F.Cu"],
            "value": "0.037969",
            "color": "red",
            "raw": {"primary": {}, "related": {}},
        }
        result = {
            "display": 0.0,
            "color": "red",
            "checked_count": 1,
            "violation_count": 1,
            "displayed_count": 1,
            "execution_status": "completed",
            "check": [{"result": [row]}],
        }
        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = Backend()
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)

        with mock.patch(
            "kicad_dfm.dfm_mainframe.GerberResultObjectMapper",
            return_value=Mapper(),
        ):
            frame.map_gerber_native_result_rows(result)

        self.assertEqual([], result["check"])
        self.assertEqual(1, result["suppressed_count"])
        resolution = row["raw"]["net_tie_candidate_resolution"]
        self.assertEqual(2, resolution["candidate_pair_count"])
        self.assertEqual(1, resolution["closest_pair_count"])
        self.assertTrue(resolution["all_closest_local_contacts"])

    def test_enrichment_keeps_tied_ambiguous_native_pair(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        member_a = types.SimpleNamespace(item_id="member-a", net_name="A", kind="pad")
        member_b = types.SimpleNamespace(item_id="member-b", net_name="B", kind="pad")
        decoy_b = types.SimpleNamespace(item_id="decoy-b", net_name="B", kind="pad")

        def mapping(status, item=None):
            return types.SimpleNamespace(
                status=status,
                item=item,
                item_id=getattr(item, "item_id", ""),
                confidence=1.0,
                reason="test",
            )

        class Mapper:
            def map_pair(self, _row):
                return mapping("matched", member_a), mapping("ambiguous")

            def map_pair_candidates(self, _row):
                return (
                    (mapping("matched", member_a),),
                    (mapping("matched", member_b), mapping("matched", decoy_b)),
                )

            def apply_mapping(self, row):
                row["id"] = member_a.item_id
                row.setdefault("raw", {})["uuid_mapping"] = {
                    "status": "matched",
                    "id": member_a.item_id,
                    "related": {"status": "ambiguous"},
                }
                return mapping("matched", member_a)

        class Backend:
            def net_tie_pad_groups(self):
                return ((("member-a", "A"), ("member-b", "B")),)

            def item_id(self, item):
                return item.item_id

            def item_net_name(self, item):
                return item.net_name

            def item_clearance_nm(self, _left, _right, _maximum):
                return 0

            def is_pad(self, item):
                return item.kind == "pad"

            def is_track(self, item):
                return False

            def resolve_item(self, item_id):
                return {"member-a": member_a}.get(item_id)

        row = {
            "id": "F_Cu.gbr",
            "related_id": "F_Cu.gbr",
            "source": "gerber",
            "item": "SMD Pad Spacing",
            "rule_key": "smallesttracespacing:smdpadspacing",
            "layer": ["F.Cu"],
            "value": "0.000000",
            "color": "red",
            "raw": {"primary": {}, "related": {}},
        }
        result = {
            "display": 0.0,
            "color": "red",
            "execution_status": "completed",
            "check": [{"result": [row]}],
        }
        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = Backend()
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)

        with mock.patch(
            "kicad_dfm.dfm_mainframe.GerberResultObjectMapper",
            return_value=Mapper(),
        ):
            frame.map_gerber_native_result_rows(result)

        self.assertEqual([row], result["check"][0]["result"])
        resolution = row["raw"]["net_tie_candidate_resolution"]
        self.assertEqual(2, resolution["closest_pair_count"])
        self.assertFalse(resolution["all_closest_local_contacts"])

    def test_board_edge_enrichment_maps_then_physically_aggregates_rows(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        def mapping(status, item_id="", confidence=1.0, reason="test"):
            return types.SimpleNamespace(
                status=status,
                item_id=item_id,
                confidence=confidence,
                reason=reason,
                item=None,
            )

        class Mapper:
            def apply_mapping(self, row):
                raw = row.setdefault("raw", {})
                primary = raw.get("primary") or {}
                token = primary.get("token")
                if token in ("zone-a", "zone-b"):
                    row["id"] = "zone-uuid"
                    raw["uuid_mapping"] = {
                        "status": "matched",
                        "id": "zone-uuid",
                        "confidence": 1.0,
                        "reason": "zone_filled_bbox",
                    }
                    return mapping("matched", "zone-uuid")
                raw["uuid_mapping"] = {
                    "status": "ambiguous",
                    "confidence": 1.0,
                    "reason": "multiple_candidates",
                }
                return mapping("ambiguous")

            def map_row(self, row):
                if (row.get("raw") or {}).get("token") == "pth-outer-x2":
                    return mapping("matched", "pth-uuid", reason="x2_component_pad")
                return mapping("ambiguous")

        def zone_row(token, value):
            return {
                "id": "F_Cu.gbr",
                "source": "gerber",
                "item_type": "gerber",
                "item": "Copper-to-Board Edge",
                "rule_key": "coppertoboardedge:coppertoboardedge",
                "layer": ["F.Cu"],
                "value": value,
                "color": "gold",
                "raw": {
                    "primary": {
                        "token": token,
                        "kind": "region",
                        "net": "GND",
                        "bbox": (1.0, 1.0, 2.0, 2.0),
                    }
                },
            }

        pth_primary = {
            "token": "pth-inner",
            "kind": "segment",
            "through_hole": True,
            "net": "CHASSIS",
            "aperture_function": "ComponentPad",
            "bbox": (5.0, 1.0, 5.2, 3.0),
            "segment": ((5.1, 1.1), (5.1, 2.9)),
            "width": 0.9,
        }
        pth = {
            "id": "In1_Cu.gbr",
            "source": "gerber",
            "item_type": "gerber",
            "item": "Copper-to-Board Edge",
            "rule_key": "coppertoboardedge:coppertoboardedge",
            "layer": ["F.Cu", "In1.Cu"],
            "value": "0.250000",
            "color": "gold",
            "raw": {
                "primary": pth_primary,
                "physical_measurement_count": 2,
                "per_layer_measurements": [
                    {
                        "layer": ["F.Cu"],
                        "primary": dict(pth_primary, token="pth-outer-x2"),
                    },
                    {"layer": ["In1.Cu"], "primary": dict(pth_primary)},
                ],
            },
        }
        result = {
            "display": 0.24,
            "color": "gold",
            "checked_count": 4,
            "available_count": 4,
            "violation_count": 3,
            "displayed_count": 3,
            "execution_status": "completed",
            "check": [
                {"result": [zone_row("zone-a", "0.250000")]},
                {"result": [zone_row("zone-b", "0.240000")]},
                {"result": [pth]},
            ],
        }
        frame = object.__new__(DfmMainframe)
        frame.board = object()
        frame.backend = types.SimpleNamespace()
        frame.logger = types.SimpleNamespace(debug=lambda *_args, **_kwargs: None)

        with mock.patch(
            "kicad_dfm.dfm_mainframe.GerberResultObjectMapper",
            return_value=Mapper(),
        ):
            frame.map_gerber_native_result_rows(
                result,
                category="Copper-to-Board Edge",
            )

        rows = [row for check in result["check"] for row in check["result"]]
        self.assertEqual(2, len(rows))
        self.assertEqual({"zone-uuid", "pth-uuid"}, {row["id"] for row in rows})
        self.assertEqual(4, result["checked_count"])
        self.assertEqual(2, result["displayed_count"])
        zone = next(row for row in rows if row["id"] == "zone-uuid")
        pth_row = next(row for row in rows if row["id"] == "pth-uuid")
        self.assertEqual("0.240000", zone["value"])
        self.assertEqual(2, zone["raw"]["physical_measurement_count"])
        self.assertEqual(2, pth_row["raw"]["physical_measurement_count"])
        self.assertEqual(
            "per_layer_export_identity",
            pth_row["raw"]["uuid_mapping"]["reason"],
        )

    def test_ui_exposes_quick_and_comprehensive_analysis_entries(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        class Button:
            def __init__(self):
                self.label = ""
                self.visible = True

            def SetLabel(self, label):
                self.label = label

            def Hide(self):
                self.visible = False

            def Show(self):
                self.visible = True

        run_button = Button()
        gerber_button = Button()
        dialog = types.SimpleNamespace(
            dfm_run_button=run_button,
            gerber_dfm_button=gerber_button,
            layout_count=0,
        )
        dialog.Layout = lambda: setattr(dialog, "layout_count", dialog.layout_count + 1)
        frame = object.__new__(DfmMainframe)
        frame.dfm_maindialog = dialog

        frame.configure_analysis_entry_buttons()

        self.assertEqual("Quick DFM Check", run_button.label)
        self.assertTrue(run_button.visible)
        self.assertEqual("Full DFM Check", gerber_button.label)
        self.assertTrue(gerber_button.visible)
        self.assertEqual(1, dialog.layout_count)

    def test_quick_entry_runs_native_analysis_only(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.workflow = types.SimpleNamespace(start_analysis=lambda: True)
        frame.logger = types.SimpleNamespace(info=lambda *_args, **_kwargs: None)
        lifecycle = []
        frame.begin_analysis_progress = lambda: lifecycle.append("begin")
        frame.end_analysis_progress = lambda: lifecycle.append("end")
        frame.run_offline_analysis = lambda: lifecycle.append("native")
        frame.run_combined_analysis = lambda: self.fail("combined analysis was selected")

        frame.on_select_native_dfm(None)

        self.assertEqual(["begin", "native", "end"], lifecycle)

    def test_comprehensive_entry_runs_combined_analysis_only(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        frame = object.__new__(DfmMainframe)
        frame.workflow = types.SimpleNamespace(start_analysis=lambda: True)
        frame.logger = types.SimpleNamespace(info=lambda *_args, **_kwargs: None)
        lifecycle = []
        frame.begin_analysis_progress = lambda: lifecycle.append("begin")
        frame.end_analysis_progress = lambda: lifecycle.append("end")
        frame.run_combined_analysis = lambda: lifecycle.append("combined")
        frame.run_offline_analysis = lambda: self.fail("native analysis was selected")

        frame.on_select_combined_dfm(None)

        self.assertEqual(["begin", "combined", "end"], lifecycle)

    def test_quick_analysis_finishes_ui_cache_and_progress_before_success(self):
        from kicad_dfm.dfm_mainframe import DfmMainframe

        stage = AnalysisStageResult(
            KICAD_NATIVE,
            {"Hole Size": {"display": 0.2, "color": "red", "check": []}},
        )
        lifecycle = []
        workflow = types.SimpleNamespace()
        workflow.parsing = lambda: lifecycle.append("parsing")
        workflow.done = lambda: lifecycle.append("done")

        frame = object.__new__(DfmMainframe)
        frame._analysis_cancel_requested = False
        frame.workflow = workflow
        frame.current_rules = lambda: {"Hole Size": ()}
        progress_updates = []
        frame.update_analysis_progress = lambda *args: progress_updates.append(args) or True

        def analyze_native(_rules, progress):
            lifecycle.append("analyze")
            progress(1, 1, "Finalizing results")
            return stage

        frame._analyze_native_stage = analyze_native
        frame.apply_native_stage_result = lambda _stage: lifecycle.append("apply")
        frame.add_all_item = lambda **_kwargs: lifecycle.append("ui")
        frame.sync_native_drc_markers = lambda: lifecycle.append("markers")
        frame.save_analysis_snapshot = lambda *_args, **_kwargs: lifecycle.append("cache")

        frame.run_offline_analysis()

        self.assertEqual(
            ["parsing", "analyze", "apply", "ui", "markers", "cache", "done"],
            lifecycle,
        )
        percentages = [current for current, _total, _item in progress_updates]
        self.assertEqual(sorted(percentages), percentages)
        self.assertEqual(100, percentages[-1])
        self.assertEqual("Quick DFM check completed.", self.Dialog.instances[-1].args[1])


if __name__ == "__main__":
    unittest.main()
