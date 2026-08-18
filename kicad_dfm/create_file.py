import logging
from kicad_dfm.kicad.swig import SwigBackend
from kicad_dfm.services import export

class CreateFile:
    def __init__(self, _board):
        self.board = _board
        self.backend = SwigBackend(_board)
        self.logger = logging.getLogger(__name__)

    def export_gerber(self, gerber_dir, layer_count=None):
        """Generating Gerber files"""
        return export.export_gerber(self.backend, gerber_dir, layer_count)

    def export_drl(self, gerber_dir):
        """Generate Drill files."""
        export.export_drill(self.backend, gerber_dir)
        self.logger.info("Finished generating Drill files")
