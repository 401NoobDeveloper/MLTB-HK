from web.pin import make_pin, pincode_enabled


def test_pin_uses_first_four_digits_when_available():
    assert make_pin("9e4160870d5be7c2") == "9416"


def test_pin_falls_back_for_hex_only_gid():
    pin = make_pin("abcdefabcdefabcd")
    assert len(pin) == 4
    assert pin.isdigit()


def test_pin_pads_short_digit_prefix():
    pin = make_pin("abc12def")
    assert len(pin) == 4
    assert pin.isdigit()
    assert pin.startswith("12")


def test_pin_is_never_empty():
    pin = make_pin("")
    assert len(pin) == 4
    assert pin.isdigit()


def test_pincode_false_string_is_disabled():
    assert pincode_enabled("false") is False
    assert pincode_enabled("0") is False
    assert pincode_enabled("") is False


def test_pincode_true_values_are_enabled():
    assert pincode_enabled("true") is True
    assert pincode_enabled("1") is True
    assert pincode_enabled(True) is True
