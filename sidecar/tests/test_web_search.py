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


def test_rejects_unrelated_provider_results():
    import pytest

    from uncloud_engine.agent.tools import _relevant_search_results
    with pytest.raises(RuntimeError, match='unrelated'):
        _relevant_search_results('latest iPhone 18 Pro specs',
                                 '1. Windows help\nhttps://microsoft.com/help\nFix Windows')


def test_keeps_relevant_sources_and_discards_noise():
    from uncloud_engine.agent.tools import _relevant_search_results
    result = _relevant_search_results('latest iPhone specs',
        '1. Windows help\nhttps://microsoft.com/help\n\n'
        '2. iPhone specifications\nhttps://apple.com/iphone/')
    assert 'apple.com' in result and 'Windows' not in result


def test_search_retries_topic_when_providers_return_unrelated_results(monkeypatch):
    import asyncio

    import httpx

    from uncloud_engine.agent import tools
    calls = []
    def respond(request):
        calls.append(str(request.url))
        if request.url.params.get('q') == 'iphone 18 pro':
            return httpx.Response(200, text='<rss><channel><item><title>iPhone 18 Pro</title>'
                '<link>https://apple.com/iphone/</link><description>Specifications</description>'
                '</item></channel></rss>')
        return httpx.Response(200, text='<rss><channel><item><title>Windows Help</title>'
            '<link>https://microsoft.com/help</link></item></channel></rss>')
    client = httpx.AsyncClient
    monkeypatch.setattr(tools.httpx, 'AsyncClient',
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(tools._search_snippets('latest iPhone 18 Pro specs'))
    assert 'apple.com/iphone' in result
    assert len(calls) == 3


def test_search_reads_pages_and_reports_blocked_sources(monkeypatch):
    import asyncio

    from uncloud_engine.agent import tools
    async def snippets(query):
        return ("1. Gardening\nhttps://example.org/soil\nSoil guide\n\n"
                "2. Plants\nhttps://example.org/plants\nPlant guide")
    async def read(url):
        if url.endswith('plants'):
            raise RuntimeError('blocked')
        return 'Water deeply. Loamy soil drains well.'
    monkeypatch.setattr(tools, '_search_snippets', snippets)
    monkeypatch.setattr(tools, '_web_read', read)
    result = asyncio.run(tools._web_search('gardening soil'))
    assert 'Loamy soil' in result
    assert 'Search snippet only; could not read page' in result
    assert 'https://example.org/soil' in result


def test_excerpts_include_relevant_content_beyond_header():
    from uncloud_engine.agent.tools import _page_excerpts
    page = 'Navigation ' * 900 + '\nBattery capacity is 5000 mAh. Charging takes 40 minutes.'
    assert '5000 mAh' in _page_excerpts('battery capacity charging', page)


def test_shared_name_alone_does_not_make_a_source_relevant():
    import pytest

    from uncloud_engine.agent.tools import _relevant_search_results
    with pytest.raises(RuntimeError, match='unrelated'):
        _relevant_search_results('James Webb telescope instruments',
                                '1. James Bible\nhttps://example.org/james\nJames chapter one')
