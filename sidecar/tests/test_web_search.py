"""Search parsing survives the provider's no-JavaScript layouts."""

from uncloud_engine.agent.tools import _parse_bing_rss, _parse_web_search


def test_parses_duckduckgo_lite_results() -> None:
    html = """
      <a class='result-link' href='//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com'>
        Example &amp; title
      </a>
      <td class='result-snippet'>A <b>useful</b> answer.</td>
    """
    result = _parse_web_search(html)
    assert "Example & title" in result
    assert "https://example.com" in result
    assert "A useful answer." in result


def test_refuses_an_empty_or_denial_page() -> None:
    try:
        _parse_web_search("Automated requests are denied")
    except RuntimeError as exc:
        assert "no readable results" in str(exc)
    else:
        raise AssertionError("a provider denial must not be reported as search results")


def test_parses_bing_rss_results() -> None:
    result = _parse_bing_rss("""
      <rss><channel><item>
        <title>Official &amp; useful</title>
        <link>https://example.com/specs</link>
        <description>The current specification.</description>
      </item></channel></rss>
    """)
    assert "Official & useful" in result
    assert "https://example.com/specs" in result
    assert "The current specification." in result
