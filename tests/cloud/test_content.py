from reason8.cloud import content


def test_the_content_archive_goes_to_the_bucket_and_back(bucket, tmp_path):
    data_dir = tmp_path / "bar"
    (data_dir / "engine" / "recoil_1").mkdir(parents=True)
    (data_dir / "engine" / "recoil_1" / "spring-headless").write_text("engine")
    (data_dir / "maps").mkdir()
    (data_dir / "maps" / "some.sd7").write_text("map")
    (data_dir / "headless_setup.json").write_text("{}")
    (data_dir / "demos").mkdir()
    (data_dir / "demos" / "private.sdfz").write_text("a replay")

    pushed = content.push(bucket, data_dir)
    assert pushed["parts"] == ["engine", "maps", "headless_setup.json"]

    restored = tmp_path / "work" / "bar"
    assert content.restore(bucket, restored)
    assert (restored / "engine" / "recoil_1" / "spring-headless").read_text() == "engine"
    assert (restored / "maps" / "some.sd7").read_text() == "map"
    assert not (restored / "demos").exists()  # only what the setup fetches is packed
    assert not content.restore(bucket, restored)  # content is there: left alone


def test_no_archive_leaves_the_worker_to_fetch(bucket, tmp_path):
    assert not content.restore(bucket, tmp_path / "bar")
