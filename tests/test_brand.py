from matriosha.cli.brand.banner import BANNER
from matriosha.cli.brand.theme import MATRIOSHA_THEME, console


def test_banner_non_empty() -> None:
    assert isinstance(BANNER, str)
    assert BANNER.strip()


def test_theme_loadable() -> None:
    c = console()
    assert c is not None
    assert MATRIOSHA_THEME is not None
    # Ensure key semantic styles are present and usable.
    for style_name in ("primary", "accent", "success", "warning", "danger", "muted", "integrity"):
        assert MATRIOSHA_THEME.styles.get(style_name) is not None
