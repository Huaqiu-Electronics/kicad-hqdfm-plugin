from dataclasses import dataclass


@dataclass
class Location:
    item_id: str = None
    item_type: str = ""
    layer: object = None
    x_nm: int = None
    y_nm: int = None
    bbox_nm: tuple = None


@dataclass
class DfmIssue:
    category: str
    item: str
    severity: str = "ok"
    layer: object = None
    value: str = ""
    rule: str = ""
    message: str = ""
    location: Location = None
    raw: dict = None


@dataclass
class DfmSummary:
    category: str
    display: str = ""
    display_inch: str = ""
    color: str = ""
    issues: tuple = ()


@dataclass
class ExportResult:
    output_dir: str
    zip_path: str = ""
    files: tuple = ()
    plot_plan: tuple = ()
    layer_count: int = 0
    fallback_used: bool = False
    warnings: tuple = ()


@dataclass
class OutputDirResult:
    output_dir: str
    fallback_used: bool = False
    warnings: tuple = ()

    def __str__(self):
        return self.output_dir

    def __fspath__(self):
        return self.output_dir

    def __iter__(self):
        yield self.output_dir
        yield self.fallback_used

    def __eq__(self, other):
        if isinstance(other, OutputDirResult):
            return (
                self.output_dir,
                self.fallback_used,
                self.warnings,
            ) == (
                other.output_dir,
                other.fallback_used,
                other.warnings,
            )
        return self.output_dir == str(other)
