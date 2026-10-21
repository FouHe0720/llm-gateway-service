"""Actual browser screenshots; install optional screenshots dependency first."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".venv/playwright-browsers"))
libs = ROOT / ".venv/browser-libs/usr/lib/x86_64-linux-gnu"
if libs.exists():
    os.environ["LD_LIBRARY_PATH"] = str(libs) + ":" + os.environ.get("LD_LIBRARY_PATH", "")

fonts = ROOT / ".venv/browser-libs/usr/share/fonts/opentype/noto"
if fonts.exists():
    config = ROOT / ".venv/browser-fonts.conf"
    config.write_text(
        f"<fontconfig><dir>{fonts}</dir>"
        f"<cachedir>{ROOT / '.venv/font-cache'}</cachedir></fontconfig>"
    )
    os.environ["FONTCONFIG_FILE"] = str(config)


def main():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1120}, device_scale_factor=1)
        page.context.set_offline(True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((ROOT / "benchmarks/reports/index.html").as_uri())
        page.wait_for_selector(".card")
        assert page.locator(".card").count() == 6
        output = ROOT / "docs/images"
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / "benchmark-overview.png"))
        for experiment in ("B", "C", "D", "E"):
            page.select_option("#experiment", experiment)
            page.screenshot(path=str(output / f"benchmark-{experiment.lower()}.png"))
        assert not errors, errors
        print("Browser render and screenshots passed; zero JavaScript errors")
        browser.close()


if __name__ == "__main__":
    main()
