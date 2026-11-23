from oden.formatting import defang_markdown, format_sender_display, one_line, sanitize_msg_data


def test_defang_markdown_kills_html_and_remote_embeds():
    out = defang_markdown('hej <img src="https://x/p.png"> ![a](https://x/b.png) ![r][1] <iframe src=x></iframe>')
    assert "<img" not in out and "<iframe" not in out and "</iframe" not in out
    assert "![a]" not in out and "![r]" not in out
    # Normal text, comparisons and vault-local embeds survive
    assert (
        defang_markdown("avstånd <500 m, ![[karta]] [länk](https://x)")
        == "avstånd <500 m, ![[karta]] [länk](https://x)"
    )


def test_one_line_cannot_break_out_of_heading_or_wikilink():
    assert one_line("Grupp]]\n![b](https://x)\n# [[x|y") == "Grupp)) !(b)(https://x) # ((x/y"
    assert "\n" not in format_sender_display("Eve\n<img src=x>", "+46701234567")


def test_sanitize_msg_data_copies_and_defangs():
    raw = {
        "envelope": {
            "sourceName": "Eve\nx",
            "dataMessage": {
                "message": "<script>x</script>",
                "quote": {"text": "![a](http://x)"},
                "groupV2": {"id": "abc", "name": "G]]\n<b>"},
            },
        }
    }
    clean = sanitize_msg_data(raw)
    dm = clean["envelope"]["dataMessage"]
    assert dm["message"] == "&lt;script>x&lt;/script>"
    assert dm["quote"]["text"] == "!\\[a](http://x)"
    assert dm["groupV2"] == {"id": "abc", "name": "G)) &lt;b>"}
    assert clean["envelope"]["sourceName"] == "Eve x"
    assert raw["envelope"]["dataMessage"]["message"] == "<script>x</script>"  # original untouched
