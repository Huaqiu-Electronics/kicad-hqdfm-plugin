import unittest

from kicad_dfm.services.locate import LocatePlan
from kicad_dfm.services.native_drc import NativeDrcMarkerExporter


class FakeItem:
    def __init__(self, item_id="", layer_name="F.Cu", position=(1000, 2000)):
        self.item_id = item_id
        self.layer_name = layer_name
        self.position = position


class FakeBackend:
    def __init__(self):
        self.added = []
        self.deleted = []

    def add_board_item(self, item):
        self.added.append(item)

    def delete_board_item(self, item):
        self.deleted.append(item)

    def item_id(self, item):
        return item.item_id

    def item_position(self, item):
        return item.position

    def item_bbox(self, item):
        return None

    def item_layer_name(self, item):
        return item.layer_name


class NativeDrcMarkerExporterTest(unittest.TestCase):
    def test_export_creates_session_owned_markers_from_plan_items(self):
        backend = FakeBackend()
        calls = []

        def marker_factory(payload):
            calls.append(payload)
            if payload.startswith("track_width|"):
                return {"payload": payload}
            return None

        exporter = NativeDrcMarkerExporter(
            board=object(),
            backend=backend,
            marker_factory=marker_factory,
            marker_keys=("generic_warning", "track_width"),
        )

        item = FakeItem(item_id="item-uuid", layer_name="B.Cu")
        result = exporter.export(LocatePlan(items=[item]))

        self.assertEqual(1, len(result.markers))
        self.assertEqual([], result.skipped)
        self.assertEqual(result.markers, backend.added)
        self.assertIn("generic_warning|1000|2000|item-uuid|B.Cu", calls)
        self.assertEqual("track_width|1000|2000|item-uuid|B.Cu", result.markers[0]["payload"])

        exporter.clear()

        self.assertEqual(result.markers, backend.deleted)
        self.assertEqual([], exporter.markers)

    def test_export_skips_items_without_uuid_or_factory(self):
        backend = FakeBackend()
        exporter = NativeDrcMarkerExporter(
            board=object(),
            backend=backend,
            marker_factory=None,
        )
        exporter._default_marker_factory = lambda: None
        item = FakeItem(item_id="item-uuid")

        result = exporter.export(LocatePlan(items=[item]))

        self.assertEqual([], result.markers)
        self.assertEqual([item], result.skipped)
        self.assertEqual([], backend.added)

        exporter = NativeDrcMarkerExporter(
            board=object(),
            backend=backend,
            marker_factory=lambda payload: {"payload": payload},
        )
        item_without_uuid = FakeItem(item_id="")

        result = exporter.export(LocatePlan(items=[item_without_uuid]))

        self.assertEqual([], result.markers)
        self.assertEqual([item_without_uuid], result.skipped)
        self.assertEqual([], backend.added)

    def test_export_prefers_category_marker_key_mapping(self):
        backend = FakeBackend()
        calls = []

        def marker_factory(payload):
            calls.append(payload)
            if payload.startswith("annular_width|"):
                return {"payload": payload}
            return None

        exporter = NativeDrcMarkerExporter(
            board=object(),
            backend=backend,
            marker_factory=marker_factory,
        )

        result = exporter.export(
            LocatePlan(items=[FakeItem(item_id="pad-uuid")]),
            category="RingHole",
        )

        self.assertEqual(1, len(result.markers))
        self.assertEqual("annular_width|1000|2000|pad-uuid|F.Cu", result.markers[0]["payload"])
        self.assertEqual("annular_width|1000|2000|pad-uuid|F.Cu", calls[0])

    def test_export_uses_default_key_order_without_category(self):
        backend = FakeBackend()
        calls = []

        def marker_factory(payload):
            calls.append(payload)
            return {"payload": payload}

        exporter = NativeDrcMarkerExporter(
            board=object(),
            backend=backend,
            marker_factory=marker_factory,
        )

        result = exporter.export(LocatePlan(items=[FakeItem(item_id="track-uuid")]))

        self.assertEqual(1, len(result.markers))
        self.assertEqual("generic_warning|1000|2000|track-uuid|F.Cu", result.markers[0]["payload"])
        self.assertEqual("generic_warning|1000|2000|track-uuid|F.Cu", calls[0])


if __name__ == "__main__":
    unittest.main()
