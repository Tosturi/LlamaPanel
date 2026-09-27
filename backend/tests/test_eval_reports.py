import json
import pytest
from app.evals.library import document


def seed(client, state="completed"):
    svc = client.app.state.evaluations
    id = "a" * 32
    run = dict(
        id=id,
        name="<script>alert(1)</script>",
        state=state,
        created_at=0,
        completed=151,
        total=151,
        participants=[{"preset": "A&B"}],
        benchmarks=[],
        request={"engine": "native"},
        metrics={
            "0:b": dict(
                participant=0,
                benchmark="b",
                name="Example",
                metric="accuracy",
                scored=151,
                total=151,
                errors=0,
                score=1,
            )
        },
    )
    document(svc._dir(id) / "run.json", "run").save(run)
    rows = [
        dict(
            participant=0,
            benchmark="b",
            sample_id=str(i),
            phase="generation",
            score=1,
            messages=[{"role": "assistant", "content": "<img src=x onerror=alert(1)>"}],
            expected="answer",
        )
        for i in range(151)
    ]
    rows.append({**rows[0], "phase": "judging", "judge_output": "final judge decision"})
    (svc._dir(id) / "samples.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    return svc, id, run


def test_html_export_all_answers_latest_judge_and_escaped_content(client):
    svc, id, _ = seed(client)
    response = client.get(f"/api/evaluations/runs/{id}/report")
    assert response.status_code == 200
    assert "attachment;" in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "<script>" not in html and "<img " not in html
    assert "&lt;script&gt;" in html and "&lt;img " in html and "A&amp;B" in html
    assert "Sample 150" in html and html.count(" · Sample ") == 151
    assert "final judge decision" in html and "100.00%" in html
    assert svc.get(id)["state"] == "completed"


def test_delete_removes_only_run_and_clears_cached_selection(client):
    svc, id, run = seed(client)
    svc.run = run
    library = svc.library.directory
    library.mkdir(parents=True, exist_ok=True)
    retained = library / "keep.txt"
    retained.write_text("dataset")
    (svc._dir(id) / "harness").mkdir()
    (svc._dir(id) / "harness" / "responses.sqlite").write_text("cache")
    assert client.delete(f"/api/evaluations/runs/{id}").status_code == 200
    assert not svc._dir(id).exists() and svc.run is None
    assert retained.read_text() == "dataset"
    assert client.get(f"/api/evaluations/runs/{id}").status_code == 404
    assert client.get("/api/evaluations/runs").json() == []


@pytest.mark.parametrize("state", ["running", "paused", "preparing"])
def test_active_run_cannot_be_deleted_or_exported(client, state):
    svc, id, _ = seed(client, state)
    assert client.delete(f"/api/evaluations/runs/{id}").status_code == 409
    assert client.get(f"/api/evaluations/runs/{id}/report").status_code == 409
    assert svc._dir(id).exists()


def test_missing_report_or_delete_returns_404(client):
    id = "b" * 32
    assert client.get(f"/api/evaluations/runs/{id}/report").status_code == 404
    assert client.delete(f"/api/evaluations/runs/{id}").status_code == 404
