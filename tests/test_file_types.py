"""Tests for torrent file-type classification and batch planning."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def file_types():
    module_path = (
        Path(__file__).resolve().parent.parent
        / "bot"
        / "helper"
        / "ext_utils"
        / "file_types.py"
    )
    spec = importlib.util.spec_from_file_location("file_types_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Movie.2024.1080p.mkv", "video"),
        ("Show/S01E01.MP4", "video"),
        ("album/track01.flac", "audio"),
        ("cover.JPG", "photo"),
        ("docs/manual.pdf", "document"),
        ("android/app-release.apk", "apps"),
        ("setup.EXE", "apps"),
        ("notes", "other"),
        ("archive.rar", "other"),
        ("file.part1.mkv", "video"),
    ],
)
def test_get_file_type(file_types, name, expected):
    assert file_types.get_file_type(name) == expected


def test_normalize_types_accepts_strings_and_lists(file_types):
    assert file_types.normalize_types("Video, apps") == ["video", "apps"]
    assert file_types.normalize_types(["photo", "unknown", "audio"]) == [
        "audio",
        "photo",
    ]
    assert file_types.normalize_types(None) == []
    # Results follow the canonical group order, not input order.
    assert file_types.normalize_types(["apps", "video"]) == ["video", "apps"]


def test_is_file_type_allowed(file_types):
    assert file_types.is_file_type_allowed("movie.mkv", []) is True
    assert file_types.is_file_type_allowed("movie.mkv", ["video"]) is True
    assert file_types.is_file_type_allowed("movie.mkv", ["document"]) is False
    assert file_types.is_file_type_allowed("unknown.rar", ["video"]) is False


def test_extension_filters(file_types):
    assert file_types.is_extension_allowed("movie.MKV") is True
    assert file_types.is_extension_allowed("movie.mkv", ["mkv", "mp4"]) is True
    assert file_types.is_extension_allowed("movie.avi", ["mkv", "mp4"]) is False
    assert file_types.is_extension_allowed("movie.mkv", [], ["mkv"]) is False
    assert file_types.is_extension_allowed("sample.nfo", [], ["nfo"]) is False
    assert file_types.get_extension("folder/movie.MKV") == "mkv"


def test_plan_batch_by_count(file_types):
    files = [{"size": 1}, {"size": 1}, {"size": 1}]
    assert file_types.plan_batch(files, max_files=2) == files[:2]


def test_plan_batch_by_size(file_types):
    files = [{"size": 4}, {"size": 5}, {"size": 6}]
    assert file_types.plan_batch(files, max_files=5, max_size=8) == files[:1]


def test_plan_batch_keeps_oversized_first_file(file_types):
    files = [{"size": 100}, {"size": 10}]
    assert file_types.plan_batch(files, max_files=3, max_size=8) == files[:1]


def test_plan_batch_empty(file_types):
    assert file_types.plan_batch([], max_files=2) == []


VIDEO_EXTENSIONS = [
    "264", "265", "3g2", "3gp", "3gp2", "3gpp", "3gpp2", "amv", "asf",
    "avc", "avi", "divx", "drc", "dv", "f4v", "flv", "gvi", "gxf", "h264",
    "h265", "hevc", "ivf", "m1v", "m2p", "m2t", "m2ts", "m2v", "m4s",
    "m4v", "mk3d", "mkv", "mov", "mp4", "mp4v", "mpe", "mpeg", "mpeg2",
    "mpeg4", "mpg", "mpv", "mts", "mxf", "mxg", "nsv", "nut", "ogm", "ogv",
    "ogx", "qt", "rm", "rmvb", "roq", "svi", "tod", "ts", "vob", "vro",
    "webm", "wm", "wmv", "wtv", "xvid", "y4m",
]


@pytest.mark.parametrize("extension", VIDEO_EXTENSIONS)
def test_video_extensions_are_classified_as_video(file_types, extension):
    assert extension in file_types.FILE_TYPE_GROUPS["video"]
    assert file_types.get_file_type(f"Some.Show.S01E01.{extension.upper()}") == "video"


def test_file_type_groups_are_disjoint(file_types):
    owner = {}
    for category, extensions in file_types.FILE_TYPE_GROUPS.items():
        for extension in extensions:
            assert extension not in owner, (
                f"{extension} is listed in {owner[extension]} and {category}"
            )
            owner[extension] = category


def test_playlists_and_subtitles_are_not_video(file_types):
    for name in ["playlist.m3u8", "manifest.mpd", "subs.srt", "subs.ass", "subs.vtt"]:
        assert file_types.get_file_type(name) == "other"
