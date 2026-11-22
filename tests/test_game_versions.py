import pytest

from reason8.game_versions import (
    BALANCE_PATCHES,
    MEASURED_BUILDS,
    STALE_BUILDS,
    UNIT_RENAMES,
    IncompatibleGameVersion,
    TrainedOn,
    balance_options,
    build_number,
    check_game_version,
    current_unit_name,
    ensure_compatible,
    opening_era,
    opening_patches_between,
    playable_units,
    unit_name_changes,
)


def version(build):
    return f"Beyond All Reason test-{build}-abcdef0"


def test_build_number():
    assert build_number("Beyond All Reason test-32018-ad135b9") == 32018
    assert build_number("Beyond All Reason pr-9493-31506-5476673") is None
    assert build_number("Beyond All Reason test-1") is None
    assert build_number(None) is None


def test_patches_are_in_build_and_date_order():
    builds = [patch.first_build for patch in BALANCE_PATCHES]
    dates = [patch.released for patch in BALANCE_PATCHES]
    assert builds == sorted(set(builds))
    assert dates == sorted(dates)


def test_opening_era():
    assert opening_era(28000) is None
    assert opening_era(29240).name == "July 2025 balance patch"
    assert opening_era(29241).name == "Season 3"
    # the shield rework and the February patch do not start an era
    assert opening_era(30235).name == "Season 3"
    assert opening_era(31075).name == "August balance patch"
    assert opening_era(32018).first_build == 31357


def test_opening_patches_between():
    assert [patch.first_build for patch in opening_patches_between(30236, 31075)] == [30755, 31075]
    assert opening_patches_between(31357, 32018) == []


def test_balance_options():
    modoptions = {
        "naval_balance_tweaks": "1",
        "community_balance_patch": "disabled",
        "proposed_unit_reworks": "0",
        "experimentalshields": "unchanged",
        "experimentallegionfaction": "1",
        "tweakunits": "",
        "tweakdefs3": "bG9jYWw=",
        "multiplier_buildpower": "1",
        "multiplier_metalextraction": "2",
        "startmetal": "1000",
    }
    assert balance_options(modoptions) == {
        "experimentallegionfaction": "1",
        "multiplier_metalextraction": "2",
        "naval_balance_tweaks": "1",
        "tweakdefs3": "bG9jYWw=",
    }
    assert balance_options({"community_balance_patch": "enabled"}) == {
        "community_balance_patch": "enabled"
    }


def test_unit_names(monkeypatch):
    definitions = ["", "armmex", "armwin", "armlab"]
    assert playable_units(["armmex", "armlab"], definitions) == ("armmex", "armlab")
    assert playable_units(["legmex", "legmext15"], ["legmex"]) is None
    monkeypatch.setitem(UNIT_RENAMES, "armsolar_old", "armsolar")
    monkeypatch.setitem(UNIT_RENAMES, "armsolar", "armsun")
    assert current_unit_name("armsolar_old") == "armsun"
    assert playable_units(["armsolar_old"], ["armsun"]) == ("armsun",)
    added, removed = unit_name_changes(["", "armsolar", "legmext15"], ["", "armsun", "armnew"])
    assert (added, removed) == (["armnew"], ["legmext15"])


@pytest.fixture
def trained():
    return TrainedOn.from_training_data(
        [version(31400), version(31900), "Beyond All Reason pr-1-2-abcdef0", None],
        ["armmex", "armlab", "legmex"],
    )


def test_trained_on_round_trip(trained):
    assert (trained.first_build, trained.last_build) == (31400, 31900)
    assert TrainedOn.from_json(trained.to_json()) == trained
    with pytest.raises(ValueError):
        TrainedOn.from_training_data([None], ["armmex"])


def test_check_game_version_ok(trained):
    assert check_game_version(trained, version(31650)).level == "ok"
    assert check_game_version(trained, version(31900 + STALE_BUILDS)).level == "ok"
    # Legion is not loaded in this game, so the model's Legion units are not missed
    assert check_game_version(trained, version(31900), ["", "armmex", "armlab"]).level == "ok"


def test_check_game_version_warns(trained):
    assert check_game_version(trained, version(31900 + STALE_BUILDS + 1)).level == "warn"
    assert check_game_version(trained, version(31000)).level == "warn"
    assert check_game_version(trained, "Beyond All Reason pr-9493-31506-5476673").level == "warn"
    older = TrainedOn(30300, 30700, frozenset({"armmex"}))
    result = check_game_version(older, version(30760))
    assert result.level == "warn"
    assert "July balance patch (30755)" in result.reasons[0]


def test_check_game_version_refuses(trained):
    result = check_game_version(trained, version(31900), ["", "armmex", "legmex"])
    assert result.level == "refuse"
    assert "armlab" in result.reasons[0]
    assert check_game_version(trained, version(31900 + MEASURED_BUILDS + 1)).level == "refuse"
    assert check_game_version(trained, version(31400 - MEASURED_BUILDS - 1)).level == "refuse"


def test_ensure_compatible(trained):
    assert ensure_compatible(trained, version(31650)).level == "ok"
    with pytest.warns(UserWarning, match="retrain"):
        ensure_compatible(trained, version(31900 + STALE_BUILDS + 1))
    with pytest.raises(IncompatibleGameVersion, match="armlab"):
        ensure_compatible(trained, version(31900), ["armmex"])
