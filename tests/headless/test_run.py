"""Tests for the parts of `reason8 headless run` that need no engine."""

from reason8.headless import run


def test_with_speed_existing_modoptions():
    script = "[GAME]\n{\n\t[MODOPTIONS]\n\t{\n\t\tdeathmode=neverend;\n\t}\n}\n"
    result = run.with_speed(script, 100)
    assert "MinSpeed=100;" in result and "MaxSpeed=100;" in result
    assert result.index("MinSpeed") < result.index("deathmode")


def test_with_speed_no_modoptions():
    result = run.with_speed("[GAME]\n{\n\tMapName=x;\n}\n", 20)
    assert "[MODOPTIONS]" in result and "MaxSpeed=20;" in result


def test_sim_window(tmp_path):
    log = tmp_path / "infolog.txt"
    log.write_text(
        "[t=00:00:00.500000] starting\n"
        "[t=00:00:10.000000][f=-000001] loading\n"
        "[t=00:00:12.000000][f=0000000] ingame\n"
        "[t=00:00:20.000000][f=0000900] something\n"
        "[t=00:01:12.000000][f=0018000] quit\n"
        "[t=00:01:15.000000][f=0018000] shutdown\n"
    )
    load_seconds, sim_seconds, frames = run.sim_window(log)
    assert load_seconds == 12.0
    assert sim_seconds == 60.0
    assert frames == 18000


def test_widget_config_enables_our_widget():
    config = run.widget_config([run.STATE_WIDGET])
    assert '["Reason8 state export"] = 1' in config
    assert "allowUserWidgets = true" in config
