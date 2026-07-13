from agent_network.input_analysis import analyze_input


def test_input_size_classification_and_token_estimate() -> None:
    small = analyze_input("a" * 7_999)
    medium = analyze_input("中" * 8_000)
    long = analyze_input(("中文报告\n" * 5_001).rstrip())

    assert small.input_size_class == "small"
    assert medium.input_size_class == "medium"
    assert long.input_size_class == "long"
    assert long.input_lines == 5_001
    assert long.estimated_input_tokens > 0
