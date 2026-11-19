from autopost.notify import send_telegram, write_step_summary


def test_telegram_skipped_without_secrets():
    calls = []
    assert send_telegram("hi", env={}, post=lambda url, payload: calls.append(url)) is False
    assert calls == []


def test_telegram_posts_message():
    calls = []
    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"}
    assert send_telegram("hi", env=env, post=lambda url, payload: calls.append((url, payload))) is True
    assert calls == [("https://api.telegram.org/bottok/sendMessage", {"chat_id": "42", "text": "hi"})]


def test_telegram_failure_is_swallowed():
    def boom(url, payload):
        raise OSError("network down")

    env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "42"}
    assert send_telegram("hi", env=env, post=boom) is False


def test_step_summary_appends(tmp_path):
    path = tmp_path / "summary.md"
    assert write_step_summary("line1", env={"GITHUB_STEP_SUMMARY": str(path)}) is True
    write_step_summary("line2", env={"GITHUB_STEP_SUMMARY": str(path)})
    assert path.read_text(encoding="utf-8") == "line1\nline2\n"


def test_step_summary_skipped_outside_actions():
    assert write_step_summary("x", env={}) is False
