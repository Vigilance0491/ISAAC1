from isaac1.rut241 import RUT241_CHECKS, build_parser


def test_rut241_checks_cover_required_field_signals():
    names = {name for name, _command in RUT241_CHECKS}

    assert "sim_inserted" in names
    assert "pin_state" in names
    assert "operator" in names
    assert "signal" in names
    assert "internet_ping" in names


def test_rut241_check_parser_defaults_to_lan_address():
    parser = build_parser()
    args = parser.parse_args(["rut241-check"])

    assert args.host == "192.168.1.1"
    assert args.user == "root"


def test_control_ui_parser_defaults_to_local_bind():
    parser = build_parser()
    args = parser.parse_args(["control-ui"])

    assert args.bind == "127.0.0.1"
    assert args.port == 8765
    assert args.token_env == "ISAAC1_CONTROL_TOKEN"
