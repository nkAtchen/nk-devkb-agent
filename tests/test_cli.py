from nk_devkb_agent.cli import main


def test_cli_init_ingest_search_and_ask(tmp_path, capsys):
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\nThe summary command reads stored chunks.", encoding="utf-8")

    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["ingest", "file", str(doc), "--root", str(tmp_path)]) == 0
    assert main(["search", "summary", "--root", str(tmp_path)]) == 0
    assert main(["ask", "What does the summary command read?", "--root", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "notes.md" in out
    assert "reflection" in out.lower()


def test_cli_schedule_commands(tmp_path, capsys):
    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["schedule", "set", "--daily-at", "12:00", "--timezone", "local", "--root", str(tmp_path)]) == 0
    assert main(["schedule", "list", "--root", str(tmp_path)]) == 0
    assert main(["schedule", "run-now", "--root", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "0 12 * * *" in out
    assert "refreshed" in out


def test_cli_summarize_file_matches_architecture_command_shape(tmp_path, capsys):
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\nSummaries read stored chunks.", encoding="utf-8")

    assert main(["init", "--root", str(tmp_path)]) == 0
    assert main(["ingest", "file", str(doc), "--root", str(tmp_path)]) == 0
    assert main(["summarize", "file", "notes.md", "--root", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "Summary for notes.md" in out
    assert "Summaries read stored chunks" in out
