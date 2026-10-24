"""mdlite 숨은 테스트 — 여러 규칙이 섞인 문서.

기대값은 CommonMark 0.31.2 참조 구현(commonmark.js 0.31.2)의 출력을 그대로 적은 것이다.
"""

import pytest

from mdlite import render

CASES = [
    pytest.param(
        '# Project\n\nA *small* tool for `x`.\n\n## Install\n\n```sh\npip install x\n```\n\n- fast\n- **safe**\n- see [docs][d]\n\n[d]: https://example.com/docs "Docs"\n',
        '<h1>Project</h1>\n<p>A <em>small</em> tool for <code>x</code>.</p>\n<h2>Install</h2>\n<pre><code class="language-sh">pip install x\n</code></pre>\n<ul>\n<li>fast</li>\n<li><strong>safe</strong></li>\n<li>see <a href="https://example.com/docs" title="Docs">docs</a></li>\n</ul>\n',
        id='doc_readme',
    ),
    pytest.param(
        '> Note:\n> 1. first\n>    second line\n> 2. `two`\n>\n>        code here\n\nAfter.\n',
        '<blockquote>\n<p>Note:</p>\n<ol>\n<li>\n<p>first\nsecond line</p>\n</li>\n<li>\n<p><code>two</code></p>\n<pre><code>code here\n</code></pre>\n</li>\n</ol>\n</blockquote>\n<p>After.</p>\n',
        id='doc_quote_list_code',
    ),
    pytest.param(
        '1. one\n\n   - a\n   - b\n2. two\n   ```\n   x < y\n   ```\n3. three\n',
        '<ol>\n<li>\n<p>one</p>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n</li>\n<li>\n<p>two</p>\n<pre><code>x &lt; y\n</code></pre>\n</li>\n<li>\n<p>three</p>\n</li>\n</ol>\n',
        id='doc_nested_loose_tight',
    ),
    pytest.param(
        'Use **bold _and_ italic**, `code`, [link](/a "t"), ![img](/i.png) and <me@x.org>.\nNew line\\\nhard break.\n',
        '<p>Use <strong>bold <em>and</em> italic</strong>, <code>code</code>, <a href="/a" title="t">link</a>, <img src="/i.png" alt="img" /> and <a href="mailto:me@x.org">me@x.org</a>.\nNew line<br />\nhard break.</p>\n',
        id='doc_mixed_inline',
    ),
    pytest.param(
        'Title\n=====\n\nIntro text\n***\n### Sub ###\n\n    code\n\n___\n',
        '<h1>Title</h1>\n<p>Intro text</p>\n<hr />\n<h3>Sub</h3>\n<pre><code>code\n</code></pre>\n<hr />\n',
        id='doc_headings_breaks',
    ),
    pytest.param(
        '> - a\n> continued\nlazy\n\n- b\n  > q\nlazy2\n',
        '<blockquote>\n<ul>\n<li>a\ncontinued\nlazy</li>\n</ul>\n</blockquote>\n<ul>\n<li>b\n<blockquote>\n<p>q\nlazy2</p>\n</blockquote>\n</li>\n</ul>\n',
        id='doc_lazy_everything',
    ),
]


@pytest.mark.parametrize("src, expected", CASES)
def test_documents(src, expected):
    assert render(src) == expected
