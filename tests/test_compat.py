from token_governor.compat import is_streaming_request


def test_streaming_request_detection() -> None:
    assert is_streaming_request({"stream": True})
    assert not is_streaming_request({"stream": False})
    assert not is_streaming_request({})
