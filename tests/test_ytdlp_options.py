"""Tests for YT-DLP option handling."""

from types import SimpleNamespace

from bot.helper.mirror_leech_utils.download_utils.yt_dlp_download import (
    YoutubeDLHelper,
)


def test_download_ranges_callback_keeps_its_value():
    helper = YoutubeDLHelper(SimpleNamespace())
    ranges = [{"start_time": 0, "end_time": 10}]

    helper._set_options({"download_ranges": ranges, "format": "best"})

    assert helper.opts["download_ranges"](None, None) == ranges
