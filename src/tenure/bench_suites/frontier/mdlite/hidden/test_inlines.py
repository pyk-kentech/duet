"""mdlite 숨은 테스트 — 인라인: 백슬래시 이스케이프, 코드 스팬, 줄바꿈, 자동 링크.

기대값은 CommonMark 0.31.2 참조 구현(commonmark.js 0.31.2)의 출력을 그대로 적은 것이다.
"""

import pytest

from mdlite import render

CASES = [
    pytest.param(
        '\\!\\"\\#\\$\\%\\&\\\'\\(\\)\\*\\+\\,\\-\\.\\/\\:\\;\\<\\=\\>\\?\\@\\[\\\\\\]\\^\\_\\`\\{\\|\\}\\~\n',
        "<p>!&quot;#$%&amp;'()*+,-./:;&lt;=&gt;?@[\\]^_`{|}~</p>\n",
        id='escape_all_ascii_punct',
    ),
    pytest.param(
        '\\A\\a\\ \\3\\φ\\«\n',
        '<p>\\A\\a\\ \\3\\φ\\«</p>\n',
        id='escape_non_punct_literal',
    ),
    pytest.param(
        '\\*no emphasis*\n\\[no link](/x)\n\\`no code`\n1\\. no list\n\\* no list\n\\# no heading\n\\[ref]: /url "no definition"\n',
        '<p>*no emphasis*\n[no link](/x)\n`no code`\n1. no list\n* no list\n# no heading\n[ref]: /url &quot;no definition&quot;</p>\n',
        id='escape_block_markers',
    ),
    pytest.param(
        '\\\\*emphasis*\n',
        '<p>\\<em>emphasis</em></p>\n',
        id='escape_escaped_backslash',
    ),
    pytest.param(
        'foo\\\nbar\n',
        '<p>foo<br />\nbar</p>\n',
        id='escape_newline_hard_break',
    ),
    pytest.param(
        '`` \\[\\` ``\n',
        '<p><code>\\[\\`</code></p>\n',
        id='escape_not_in_code_span',
    ),
    pytest.param(
        '    \\[\\]\n',
        '<pre><code>\\[\\]\n</code></pre>\n',
        id='escape_not_in_indented_code',
    ),
    pytest.param(
        '~~~\n\\[\\]\n~~~\n',
        '<pre><code>\\[\\]\n</code></pre>\n',
        id='escape_not_in_fence',
    ),
    pytest.param(
        '<http://example.com?find=\\*>\n',
        '<p><a href="http://example.com?find=%5C*">http://example.com?find=\\*</a></p>\n',
        id='escape_not_in_autolink',
    ),
    pytest.param(
        '[foo](/bar\\* "ti\\*tle")\n',
        '<p><a href="/bar*" title="ti*tle">foo</a></p>\n',
        id='escape_in_link_dest_title',
    ),
    pytest.param(
        '``` foo\\+bar\nfoo\n```\n',
        '<pre><code class="language-foo+bar">foo\n</code></pre>\n',
        id='escape_in_info_string',
    ),
    pytest.param(
        'foo\\\n',
        '<p>foo\\</p>\n',
        id='escape_backslash_at_end',
    ),
    pytest.param(
        'a\\\\\nb\n',
        '<p>a\\\nb</p>\n',
        id='escape_double_backslash_newline',
    ),
    pytest.param(
        '\\<br/> not a tag\n',
        '<p>&lt;br/&gt; not a tag</p>\n',
        id='escape_lt_not_tag',
    ),
    pytest.param(
        '`foo`\n',
        '<p><code>foo</code></p>\n',
        id='code_basic',
    ),
    pytest.param(
        '`` foo ` bar ``\n',
        '<p><code>foo ` bar</code></p>\n',
        id='code_double_backticks',
    ),
    pytest.param(
        '` `` `\n',
        '<p><code>``</code></p>\n',
        id='code_strip_one_space',
    ),
    pytest.param(
        '`  ``  `\n',
        '<p><code> `` </code></p>\n',
        id='code_strip_only_one',
    ),
    pytest.param(
        '` a`\n',
        '<p><code> a</code></p>\n',
        id='code_space_one_side',
    ),
    pytest.param(
        '` `\n`  `\n',
        '<p><code> </code>\n<code>  </code></p>\n',
        id='code_only_spaces',
    ),
    pytest.param(
        '``\nfoo\nbar  \nbaz\n``\n',
        '<p><code>foo bar   baz</code></p>\n',
        id='code_newlines_to_spaces',
    ),
    pytest.param(
        '``\nfoo \n``\n',
        '<p><code>foo </code></p>\n',
        id='code_newline_trailing_space',
    ),
    pytest.param(
        '`foo   bar \nbaz`\n',
        '<p><code>foo   bar  baz</code></p>\n',
        id='code_interior_spaces_kept',
    ),
    pytest.param(
        '`foo\\`bar`\n',
        '<p><code>foo\\</code>bar`</p>\n',
        id='code_backslash_literal',
    ),
    pytest.param(
        '``foo`bar``\n',
        '<p><code>foo`bar</code></p>\n',
        id='code_inner_single_backtick',
    ),
    pytest.param(
        '` foo `` bar `\n',
        '<p><code>foo `` bar</code></p>\n',
        id='code_inner_double_backticks',
    ),
    pytest.param(
        '*foo`*`\n',
        '<p>*foo<code>*</code></p>\n',
        id='code_beats_emphasis',
    ),
    pytest.param(
        '[not a `link](/foo`)\n',
        '<p>[not a <code>link](/foo</code>)</p>\n',
        id='code_beats_link',
    ),
    pytest.param(
        '`<http://foo.bar.`baz>`\n',
        '<p><code>&lt;http://foo.bar.</code>baz&gt;`</p>\n',
        id='code_beats_autolink',
    ),
    pytest.param(
        '<http://foo.bar.`baz>`\n',
        '<p><a href="http://foo.bar.%60baz">http://foo.bar.`baz</a>`</p>\n',
        id='autolink_beats_code',
    ),
    pytest.param(
        '```foo``\n',
        '<p>```foo``</p>\n',
        id='code_unmatched_lengths',
    ),
    pytest.param(
        '`foo\n',
        '<p>`foo</p>\n',
        id='code_unclosed',
    ),
    pytest.param(
        '`foo``bar``\n',
        '<p>`foo<code>bar</code></p>\n',
        id='code_unmatched_then_matched',
    ),
    pytest.param(
        '`a & b < c > "d"`\n',
        '<p><code>a &amp; b &lt; c &gt; &quot;d&quot;</code></p>\n',
        id='code_escaping',
    ),
    pytest.param(
        '**a `*` b**\n',
        '<p><strong>a <code>*</code> b</strong></p>\n',
        id='code_inside_strong',
    ),
    pytest.param(
        'foo  \nbaz\n',
        '<p>foo<br />\nbaz</p>\n',
        id='break_two_spaces',
    ),
    pytest.param(
        'foo       \nbaz\n',
        '<p>foo<br />\nbaz</p>\n',
        id='break_many_spaces',
    ),
    pytest.param(
        'foo  \n     bar\n',
        '<p>foo<br />\nbar</p>\n',
        id='break_next_line_spaces_ignored',
    ),
    pytest.param(
        'foo\\\n     bar\n',
        '<p>foo<br />\nbar</p>\n',
        id='break_backslash_next_spaces',
    ),
    pytest.param(
        '*foo  \nbar*\n',
        '<p><em>foo<br />\nbar</em></p>\n',
        id='break_inside_emphasis',
    ),
    pytest.param(
        '`code  \nspan`\n',
        '<p><code>code   span</code></p>\n',
        id='break_not_in_code_span',
    ),
    pytest.param(
        'foo  \n',
        '<p>foo</p>\n',
        id='break_not_at_paragraph_end',
    ),
    pytest.param(
        '### foo\\\n\n### foo  \n',
        '<h3>foo\\</h3>\n<h3>foo</h3>\n',
        id='break_not_at_heading_end',
    ),
    pytest.param(
        'foo \nbaz\n',
        '<p>foo\nbaz</p>\n',
        id='soft_break_one_space',
    ),
    pytest.param(
        'foo\nbaz\n',
        '<p>foo\nbaz</p>\n',
        id='soft_break_plain',
    ),
    pytest.param(
        '> a  \n> b\n',
        '<blockquote>\n<p>a<br />\nb</p>\n</blockquote>\n',
        id='break_in_quote',
    ),
    pytest.param(
        'foo \\\nbar\n',
        '<p>foo <br />\nbar</p>\n',
        id='break_backslash_keeps_space',
    ),
    pytest.param(
        'a *b*\\\n*c*\n',
        '<p>a <em>b</em><br />\n<em>c</em></p>\n',
        id='break_backslash_after_emphasis',
    ),
    pytest.param(
        'x  \n\ny\n',
        '<p>x</p>\n<p>y</p>\n',
        id='break_trailing_spaces_before_blank',
    ),
    pytest.param(
        '<http://foo.bar.baz>\n',
        '<p><a href="http://foo.bar.baz">http://foo.bar.baz</a></p>\n',
        id='autolink_http',
    ),
    pytest.param(
        '<http://foo.bar.baz/test?q=hello&id=22&boolean>\n',
        '<p><a href="http://foo.bar.baz/test?q=hello&amp;id=22&amp;boolean">http://foo.bar.baz/test?q=hello&amp;id=22&amp;boolean</a></p>\n',
        id='autolink_ampersand',
    ),
    pytest.param(
        '<ftp://files.example.net:2121/pub>\n',
        '<p><a href="ftp://files.example.net:2121/pub">ftp://files.example.net:2121/pub</a></p>\n',
        id='autolink_irc_port',
    ),
    pytest.param(
        '<MAILTO:FOO@BAR.BAZ>\n',
        '<p><a href="MAILTO:FOO@BAR.BAZ">MAILTO:FOO@BAR.BAZ</a></p>\n',
        id='autolink_uppercase_scheme',
    ),
    pytest.param(
        '<a+b+c:d>\n\n<made-up-scheme://foo,bar>\n\n<localhost:5001/foo>\n',
        '<p><a href="a+b+c:d">a+b+c:d</a></p>\n<p><a href="made-up-scheme://foo,bar">made-up-scheme://foo,bar</a></p>\n<p><a href="localhost:5001/foo">localhost:5001/foo</a></p>\n',
        id='autolink_odd_schemes',
    ),
    pytest.param(
        '<http://foo.bar/baz bim>\n',
        '<p>&lt;http://foo.bar/baz bim&gt;</p>\n',
        id='autolink_space_invalid',
    ),
    pytest.param(
        '<http://example.com/\\[\\>\n',
        '<p><a href="http://example.com/%5C%5B%5C">http://example.com/\\[\\</a></p>\n',
        id='autolink_backslashes_encoded',
    ),
    pytest.param(
        '<foo@bar.example.com>\n',
        '<p><a href="mailto:foo@bar.example.com">foo@bar.example.com</a></p>\n',
        id='autolink_email',
    ),
    pytest.param(
        '<jo.e+tag@Mail.ex-ample9.org>\n',
        '<p><a href="mailto:jo.e+tag@Mail.ex-ample9.org">jo.e+tag@Mail.ex-ample9.org</a></p>\n',
        id='autolink_email_plus',
    ),
    pytest.param(
        '<foo\\+@bar.example.com>\n',
        '<p>&lt;foo+@bar.example.com&gt;</p>\n',
        id='autolink_email_escape_invalid',
    ),
    pytest.param(
        '<>\n\n< http://foo.bar >\n',
        '<p>&lt;&gt;</p>\n<p>&lt; http://foo.bar &gt;</p>\n',
        id='autolink_empty_and_spaced',
    ),
    pytest.param(
        '<m:abc>\n',
        '<p>&lt;m:abc&gt;</p>\n',
        id='autolink_scheme_too_short',
    ),
    pytest.param(
        '<foo.bar.baz>\n',
        '<p>&lt;foo.bar.baz&gt;</p>\n',
        id='autolink_no_scheme',
    ),
    pytest.param(
        'http://example.com\n\nfoo@bar.example.com\n',
        '<p>http://example.com</p>\n<p>foo@bar.example.com</p>\n',
        id='autolink_bare_text',
    ),
    pytest.param(
        '<https://example.com/ä?q=ü>\n',
        '<p><a href="https://example.com/%C3%A4?q=%C3%BC">https://example.com/ä?q=ü</a></p>\n',
        id='autolink_non_ascii',
    ),
    pytest.param(
        '*<http://a.b/>*\n',
        '<p><em><a href="http://a.b/">http://a.b/</a></em></p>\n',
        id='autolink_in_emphasis',
    ),
]


@pytest.mark.parametrize("src, expected", CASES)
def test_inlines(src, expected):
    assert render(src) == expected
