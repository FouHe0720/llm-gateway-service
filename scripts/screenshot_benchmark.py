"""Check the offline report in Chromium and capture its desktop/mobile views."""

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
        external_requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                external_requests.append(request.url)
                if request.url.startswith(("http://", "https://"))
                else None
            ),
        )
        page.goto((ROOT / "benchmarks/reports/index.html").as_uri())
        page.wait_for_selector(".card")
        assert page.locator(".card").count() == 6
        output = ROOT / "docs/images"
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / "benchmark-overview.png"))
        for experiment in ("B", "C", "D", "E"):
            page.locator(f"#tab-{experiment}").click()
            page.screenshot(path=str(output / f"benchmark-{experiment.lower()}.png"))
        page.locator("#gpu-panel").screenshot(path=str(output / "benchmark-gpu.png"))

        # Check every filter combination, including experiments with no real samples.
        for experiment in "ABCDE":
            page.locator(f"#tab-{experiment}").click()
            for phase in ("warm", "cold", "all"):
                page.select_option("#phase", phase)
                for mode in ("all", "simulated", "real"):
                    page.select_option("#mode", mode)
                    expected = page.evaluate(
                        """() => summaries.filter(r => r.experiment === experiment
                            && r.phase === byId('phase').value
                            && (byId('mode').value === 'all'
                                || r.mode === byId('mode').value)).length"""
                    )
                    assert page.locator("#rows tr").count() == expected
                    assert page.locator("#rows-empty").is_visible() == (expected == 0)
                    assert not page.locator(".barvalue").filter(has_text="NaN").count()

        # Tabs also work with a keyboard; the small layout must not overflow the page.
        page.locator("#tab-A").click()
        page.locator("#tab-A").focus()
        page.keyboard.press("End")
        assert page.locator("#tab-E").get_attribute("aria-selected") == "true"
        page.keyboard.press("Home")
        assert page.locator("#tab-A").get_attribute("aria-selected") == "true"
        page.set_viewport_size({"width": 390, "height": 844})
        for experiment in "ABCDE":
            page.locator(f"#tab-{experiment}").click()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                f"Mobile page overflow in experiment {experiment}"
            )
        page.locator("#tab-A").click()
        page.locator("#overview").scroll_into_view_if_needed()
        page.screenshot(path=str(output / "benchmark-mobile.png"), full_page=True)

        # A fresh checkout without measurements must keep its numbers untested.
        empty = browser.new_page()
        empty.on("pageerror", lambda error: errors.append(str(error)))
        empty.set_content(
            (ROOT / "benchmarks/report_template.html")
            .read_text()
            .replace("__DATA__", '{"runs":[]}')
        )
        assert empty.locator(".card .value").all_text_contents() == ["未测试"] * 6
        assert empty.locator("#rows-empty").is_visible()
        assert "未测试" in empty.locator("#gpu").inner_text()
        assert not errors, errors
        assert not external_requests, external_requests
        print(
            "Browser checks passed: 45 filter combinations, keyboard tabs, "
            "390px layout, empty data, offline rendering; screenshots saved."
        )
        browser.close()


if __name__ == "__main__":
    main()
