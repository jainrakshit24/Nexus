"""AC4: three numbers, separately labelled; only `saved` may say estimated."""

from nexus import tokens


def test_counts_are_real_token_counts():
    assert tokens.count("") == 0
    assert tokens.count("hello world") > 0
    assert tokens.count("a" * 400) > tokens.count("a" * 40)


def test_three_numbers_are_reported_separately():
    lines = tokens.Accounting(task="t", actual=100, baseline=900).lines()
    joined = "\n".join(lines)
    assert "actual" in joined and "baseline" in joined and "saved" in joined
    assert len([line for line in lines if "tokens" in line]) == 3


def test_only_saved_is_labelled_estimated():
    lines = tokens.Accounting(task="t", actual=100, baseline=900).lines()
    by_name = {line.split()[0]: line for line in lines}
    assert "estimated" in by_name["saved"]
    assert "estimated" not in by_name["actual"]
    assert "estimated" not in by_name["baseline"]
    assert "measured" in by_name["actual"] and "measured" in by_name["baseline"]


def test_the_tokenizer_is_named_in_the_output():
    assert tokens.TOKENIZER_NAME in "\n".join(
        tokens.Accounting(task="t", actual=1, baseline=2).lines())


def test_saved_never_goes_negative():
    assert tokens.Accounting(task="t", actual=900, baseline=100).saved_estimated == 0


def test_log_and_totals_roundtrip(tmp_path):
    tokens.record(tmp_path, tokens.Accounting(task="a", actual=100, baseline=1000))
    tokens.record(tmp_path, tokens.Accounting(task="b", actual=200, baseline=800))
    t = tokens.totals(tmp_path)
    assert (t["packs"], t["actual_measured"], t["baseline_measured"]) == (2, 300, 1800)
    assert t["saved_estimated"] == 1500


def test_corrupt_log_lines_are_skipped_not_fatal(tmp_path):
    tokens.record(tmp_path, tokens.Accounting(task="a", actual=1, baseline=2))
    tokens.log_path(tmp_path).open("a").write("not json\n")
    assert tokens.totals(tmp_path)["packs"] == 1


def test_missing_host_usage_says_unavailable_and_never_guesses(tmp_path):
    u = tokens.platform_usage(tmp_path / "nowhere")
    assert u["available"] is False
    assert "reason" in u
    assert "input_tokens" not in u
