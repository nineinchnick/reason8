import httpx
import pytest
import synthetic

from reason8.map_metadata import (
    COMMIT,
    MAP_LIST_URL,
    bounding_box,
    decode_option,
    encode_option,
    fetch_map_list,
    load_map_list,
    map_list_path,
    parse_box_sets,
    parse_boxes,
    parse_map_list,
    parse_start_positions,
)


def test_parse_start_positions_reads_layouts_and_roles():
    positions = parse_start_positions(synthetic.START_POSITIONS)
    assert [(layout.team_count, layout.players_per_team) for layout in positions.layouts] == [
        (2, 2),
        (2, 1),
    ]
    layout = positions.layout_for(2, 2)
    assert [[point.id for point in side] for side in layout.sides] == [["P1", "P2"], ["P3", "P4"]]
    first = layout.sides[0][0]
    # the list's y is the engine's z
    assert (first.x, first.z, first.role) == (3000, 7000, "front")
    assert positions.layout_for(2, 8) is None
    assert positions.layout_for(4, 2) is None
    assert parse_start_positions(None) is None
    assert parse_start_positions({"positions": {}, "team": []}) is None


def test_parse_boxes_and_sets():
    sets = parse_box_sets(synthetic.BOX_SETS)
    assert list(sets) == [2]
    assert sets[2][0] == ((0, 100, None), (100, 200, None))
    assert bounding_box(sets[2][0]) == (0, 0.5, 0.5, 1)
    # the map list keys arrangements by an id: the number of boxes is the number of teams
    assert parse_box_sets({"someId": synthetic.BOX_SETS["2"]}) == sets
    curved = {"startboxes": [{"poly": [{"x": 0, "y": 0}, {"x": 50, "y": 20, "strength": 0.5}]}]}
    assert parse_boxes(curved) == (((0, 0, None), (50, 20, 0.5)),)
    assert parse_boxes(None) is None and parse_boxes({}) is None
    assert parse_box_sets(None) == {} and parse_box_sets("") == {}


def test_options_round_trip_and_reject_other_text():
    encoded = encode_option(synthetic.START_POSITIONS)
    assert "=" not in encoded
    assert decode_option(encoded) == synthetic.START_POSITIONS
    for value in (None, "", "0", "not an option", encoded[:-9]):
        assert decode_option(value) is None


def test_parse_map_list():
    maps = parse_map_list(synthetic.MAP_LIST_YAML)
    assert set(maps) == {synthetic.MAP, "Empty Plains 2.0"}
    metadata = maps[synthetic.MAP]
    assert metadata.overlay_default is True
    assert metadata.start_positions.layout_for(2, 2).sides[1][1].role == "air"
    assert metadata.start_boxes == parse_box_sets(synthetic.BOX_SETS)
    empty = maps["Empty Plains 2.0"]
    assert (empty.start_positions, empty.overlay_default, empty.start_boxes) == (None, None, {})
    assert parse_map_list("") == {}


def test_fetch_map_list_downloads_once(tmp_path):
    requests = []

    def server(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text=synthetic.MAP_LIST_YAML)

    path = fetch_map_list(tmp_path, httpx.Client(transport=httpx.MockTransport(server)))
    assert path == map_list_path(tmp_path)
    assert COMMIT[:12] in path.name and COMMIT in MAP_LIST_URL
    assert requests == [MAP_LIST_URL]
    assert synthetic.MAP in load_map_list(path)
    # the cached file is not asked for again
    again = fetch_map_list(tmp_path, httpx.Client(transport=httpx.MockTransport(server)))
    assert again == path and len(requests) == 1
    assert not list(tmp_path.glob("*.part"))


def test_fetch_map_list_leaves_nothing_behind_on_an_error(tmp_path):
    def server(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_map_list(tmp_path, httpx.Client(transport=httpx.MockTransport(server)))
    assert list(tmp_path.iterdir()) == []
    # reading never fetches: without a cached file there is no map list
    assert load_map_list(map_list_path(tmp_path)) == {}
