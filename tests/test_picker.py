import json

from evals.picker import label, list_results_files


def write_result(directory, name: str, model: str = "gemma4:31b") -> str:
    path = directory / name
    path.write_text(
        json.dumps(
            {
                "model": model,
                "summary": {"overall": {"cases": 30, "passed_cases": 28}},
            }
        )
    )
    return str(path)


class TestListResultsFiles:
    def test_newest_first(self, tmp_path):
        write_result(tmp_path, "2026-08-14T11:35:13.json")
        newest = write_result(tmp_path, "2026-08-15T16:27:45+00:00.json")
        write_result(tmp_path, "2026-08-15T13:43:48+00:00.json")

        assert list_results_files(str(tmp_path))[0] == newest

    def test_only_json_files(self, tmp_path):
        write_result(tmp_path, "2026-08-15T16:27:45+00:00.json")
        (tmp_path / "2026-08-15T16:27:45+00:00.md").write_text("# report")

        assert len(list_results_files(str(tmp_path))) == 1


class TestLabel:
    def test_shows_filename_model_and_pass_counts(self, tmp_path):
        path = write_result(tmp_path, "2026-08-15T16:27:45+00:00.json")

        text = label(path)

        assert "2026-08-15T16:27:45+00:00.json" in text
        assert "gemma4:31b" in text
        assert "28/30" in text

    def test_falls_back_to_filename_for_unreadable_json(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")

        assert label(str(path)) == "broken.json"
