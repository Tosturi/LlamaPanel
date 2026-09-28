"""Standalone, script-free HTML reports with escaped model and dataset content."""

import json
from datetime import datetime, timezone
from html import escape


def text(value):
    return escape(str(value if value is not None else "—"))


def pre(value):
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, ensure_ascii=False)
    return "<pre>" + text(value) + "</pre>"


def write_report(path, run, samples):
    participants = run.get("participants", [])
    metrics = list(run.get("metrics", {}).values())
    with path.open("w", encoding="utf-8") as out:
        out.write(
            """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>"""
            + text(run["name"])
            + """ — LlamaPanel</title>
<style>
:root{color-scheme:light;font:16px/1.6 system-ui,sans-serif;color:#202735;background:#f1f4f8}
body{max-width:1120px;margin:0 auto;padding:40px 24px}h1{margin:0;font-size:32px}h2{margin:0 0 20px;font-size:22px}
section{background:white;border:1px solid #d7dfe9;border-radius:12px;padding:24px;margin:28px 0}
.muted,small{color:#566479}small{display:block}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:14px;border-bottom:1px solid #d7dfe9;vertical-align:top}
.table{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:16px;border-radius:8px;font:13px/1.6 ui-monospace,monospace}
details{border-top:1px solid #d7dfe9;padding:18px 0}summary{cursor:pointer;font-weight:600;overflow-wrap:anywhere}.error{color:#a62424}p{overflow-wrap:anywhere}
@media print{body{background:white;padding:0;font-size:11px}section{break-inside:avoid}pre{white-space:pre-wrap}}
</style><body><header><p class="muted">LlamaPanel · Evaluation report</p><h1>"""
            + text(run["name"])
            + "</h1>"
        )
        created = datetime.fromtimestamp(run["created_at"], timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
        out.write(
            "<p>"
            + text(run["state"])
            + " · "
            + text(created)
            + " · "
            + text(run.get("completed", 0))
            + " / "
            + text(run.get("total", 0))
            + " samples</p>"
        )
        out.write(
            '<p class="muted">Run '
            + text(run["id"])
            + " · Engine: "
            + text(run.get("request", {}).get("engine", "native"))
            + " · App: "
            + text(run.get("app_version"))
            + "</p></header>"
        )
        if run.get("error"):
            out.write('<p class="error">' + text(run["error"]) + "</p>")
        out.write(
            '<section><h2>Results</h2><div class="table"><table><thead><tr><th>Benchmark / metric</th>'
        )
        for p in participants:
            out.write("<th>" + text(p["preset"]) + "</th>")
        out.write("</tr></thead><tbody>")
        for benchmark in dict.fromkeys(m["benchmark"] for m in metrics):
            row = [m for m in metrics if m["benchmark"] == benchmark]
            out.write(
                "<tr><th>"
                + text(row[0]["name"])
                + "<small>"
                + text(row[0].get("harness_metric", row[0]["metric"]))
                + "</small></th>"
            )
            for index, _ in enumerate(participants):
                m = next((m for m in row if m["participant"] == index), None)
                if m is None:
                    out.write("<td>—</td>")
                    continue
                score = m.get("score")
                display = (
                    "—"
                    if score is None
                    else (
                        f"{score * 100:.2f}%"
                        if m["metric"] == "accuracy"
                        else f"{score:.6g}"
                    )
                )
                out.write(
                    "<td>"
                    + text(display)
                    + "<small>"
                    + text(m["scored"])
                    + "/"
                    + text(m["total"])
                    + " scored · "
                    + text(m["errors"])
                    + " errors</small>"
                )
                if m.get("stderr") is not None:
                    out.write(
                        "<small>Standard error: " + text(m["stderr"]) + "</small>"
                    )
                out.write("</td>")
            out.write("</tr>")
        out.write(
            "</tbody></table></div></section><section><h2>Configuration</h2><details><summary>Run settings and provenance</summary>"
        )
        out.write(pre({k: v for k, v in run.items() if k != "metrics"}))
        out.write("</details></section><section><h2>Answers</h2>")
        count = 0
        for sample in samples:
            count += 1
            index = sample["participant"]
            name = (
                participants[index]["preset"]
                if 0 <= index < len(participants)
                else index
            )
            out.write(
                "<details><summary>"
                + text(name)
                + " · "
                + text(sample["benchmark"])
                + " · Sample "
                + text(sample["sample_id"])
                + " · "
                + text(sample.get("status"))
                + " · Score: "
                + text(sample.get("score"))
                + "</summary>"
            )
            if sample.get("error"):
                out.write('<p class="error">' + text(sample["error"]) + "</p>")
            for message in sample.get("messages", []):
                out.write(
                    "<p><strong>"
                    + text(message["role"])
                    + "</strong></p>"
                    + pre(message["content"])
                )
            if not sample.get("messages") and sample.get("output") is not None:
                out.write(pre(sample["output"]))
            if sample.get("expected") is not None:
                out.write("<p>Expected: " + text(sample["expected"]) + "</p>")
            for key in ("judge_output", "harness_metrics"):
                if sample.get(key) is not None:
                    out.write(pre(sample[key]))
            out.write("</details>")
        if not count:
            out.write('<p class="muted">No recorded answers.</p>')
        out.write("</section></body></html>")
