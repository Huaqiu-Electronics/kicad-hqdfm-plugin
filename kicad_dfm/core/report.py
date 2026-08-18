import csv
import html
import json
import os


def export_json(data, path):
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    return path


def export_csv(summary, path):
    _ensure_parent(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(["item", "display", "color"])
        for item, value in summary.items():
            if isinstance(value, dict):
                writer.writerow([item, value.get("display", ""), value.get("color", "")])
            else:
                writer.writerow([item, value, ""])
    return path


def export_html(summary, path, title="HQ DFM Report"):
    _ensure_parent(path)
    rows = []
    for item, value in summary.items():
        if isinstance(value, dict):
            display = value.get("display", "")
            color = value.get("color", "")
        else:
            display = value
            color = ""
        rows.append(
            "<tr><td>{0}</td><td>{1}</td><td>{2}</td></tr>".format(
                html.escape(str(item)), html.escape(str(display)), html.escape(str(color))
            )
        )
    content = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>{0}</title></head>
<body>
<h1>{0}</h1>
<table border="1" cellspacing="0" cellpadding="6">
<thead><tr><th>Item</th><th>Display</th><th>Color</th></tr></thead>
<tbody>
{1}
</tbody>
</table>
</body>
</html>
""".format(
        html.escape(title), "\n".join(rows)
    )
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(content)
    return path


def _ensure_parent(path):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
