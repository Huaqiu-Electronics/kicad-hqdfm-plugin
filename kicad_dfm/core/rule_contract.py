from dataclasses import dataclass

from kicad_dfm.core.rule_catalog import RULE_CATALOG, normalize_name


REQUIRED_RULE_FIELDS = ("item", "rule", "unit", "kind", "source", "offline_status")


@dataclass(frozen=True)
class RuleContractIssue:
    code: str
    message: str


def validate_rule_contract(
    rule_catalog=RULE_CATALOG,
    implemented_categories=(),
    compat_categories=(),
    summary_items=(),
    native_marker_categories=(),
):
    issues = []
    catalog_categories = tuple(rule_catalog.keys())
    catalog_set = set(catalog_categories)
    implemented_set = set(implemented_categories or ())
    compat_set = set(compat_categories or ())
    summary_set = set(summary_items or ())
    marker_set = set(native_marker_categories or ())

    issues.extend(_validate_rule_entries(rule_catalog))
    issues.extend(_missing("implemented_missing_catalog", implemented_set, catalog_set))
    issues.extend(_missing("catalog_missing_implemented", catalog_set, implemented_set))
    issues.extend(_missing("implemented_missing_compat", implemented_set, compat_set))
    issues.extend(_missing("compat_missing_summary", compat_set, summary_set))
    issues.extend(_missing("marker_missing_catalog", marker_set, catalog_set))
    return tuple(issues)


def assert_valid_rule_contract(**kwargs):
    issues = validate_rule_contract(**kwargs)
    if issues:
        raise AssertionError("\n".join(issue.message for issue in issues))


def rule_key(category, item):
    return "{0}:{1}".format(normalize_name(category), normalize_name(item))


def _validate_rule_entries(rule_catalog):
    issues = []
    for category, entries in (rule_catalog or {}).items():
        seen = set()
        if not entries:
            issues.append(RuleContractIssue("empty_category", "{0}: has no rules".format(category)))
            continue
        for index, rule in enumerate(entries):
            for field in REQUIRED_RULE_FIELDS:
                if field not in rule:
                    issues.append(
                        RuleContractIssue(
                            "missing_rule_field",
                            "{0}[{1}]: missing {2}".format(category, index, field),
                        )
                    )
            key = normalize_name(rule.get("item"))
            if not key:
                issues.append(RuleContractIssue("missing_rule_item", "{0}[{1}]: missing item".format(category, index)))
            elif key in seen:
                issues.append(RuleContractIssue("duplicate_rule_item", "{0}: duplicate item {1}".format(category, rule.get("item"))))
            seen.add(key)
    return issues


def _missing(code, required, available):
    return [
        RuleContractIssue(code, "{0}: {1}".format(code, item))
        for item in sorted(required - available)
    ]
