from pathlib import Path

from ui.dashboard import DASHBOARD_CSS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_cloud_theme_is_tracked_as_a_light_coordinated_palette():
    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(
        encoding="utf-8"
    )

    assert 'base = "light"' in config
    assert 'primaryColor = "#167d83"' in config
    assert 'backgroundColor = "#f4f7f8"' in config
    assert 'secondaryBackgroundColor = "#ffffff"' in config
    assert 'textColor = "#1c2933"' in config


def test_dashboard_css_uses_shared_palette_variables_without_legacy_dark_theme():
    assert "--koc-primary: #167d83" in DASHBOARD_CSS
    assert "--koc-surface: #ffffff" in DASHBOARD_CSS
    assert "#0a1420" not in DASHBOARD_CSS
    assert "#112334" not in DASHBOARD_CSS
