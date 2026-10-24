"""mdlite 숨은 테스트 — 링크: 인라인 링크, 참조 링크, 링크 참조 정의, 이미지, 주소 인코딩.

기대값은 CommonMark 0.31.2 참조 구현(commonmark.js 0.31.2)의 출력을 그대로 적은 것이다.
"""

import pytest

from mdlite import render

CASES = [
    pytest.param(
        '[link](/uri "title")\n',
        '<p><a href="/uri" title="title">link</a></p>\n',
        id='link_with_title',
    ),
    pytest.param(
        '[link](/uri)\n',
        '<p><a href="/uri">link</a></p>\n',
        id='link_no_title',
    ),
    pytest.param(
        '[](./target.md)\n',
        '<p><a href="./target.md"></a></p>\n',
        id='link_empty_text',
    ),
    pytest.param(
        '[link]()\n',
        '<p><a href="">link</a></p>\n',
        id='link_empty_dest',
    ),
    pytest.param(
        '[link](<>)\n',
        '<p><a href="">link</a></p>\n',
        id='link_empty_angle_dest',
    ),
    pytest.param(
        '[]()\n',
        '<p><a href=""></a></p>\n',
        id='link_all_empty',
    ),
    pytest.param(
        '[link](/my uri)\n',
        '<p>[link](/my uri)</p>\n',
        id='link_space_in_dest_invalid',
    ),
    pytest.param(
        '[link](</my uri>)\n',
        '<p><a href="/my%20uri">link</a></p>\n',
        id='link_angle_dest_space',
    ),
    pytest.param(
        '[link](foo\nbar)\n',
        '<p>[link](foo\nbar)</p>\n',
        id='link_newline_in_dest_invalid',
    ),
    pytest.param(
        '[a](<b)c>)\n',
        '<p><a href="b)c">a</a></p>\n',
        id='link_angle_dest_paren',
    ),
    pytest.param(
        '[link](\\(foo\\))\n',
        '<p><a href="(foo)">link</a></p>\n',
        id='link_escaped_parens',
    ),
    pytest.param(
        '[link](foo(and(bar)))\n',
        '<p><a href="foo(and(bar))">link</a></p>\n',
        id='link_balanced_parens',
    ),
    pytest.param(
        '[link](foo(and(bar))\n',
        '<p>[link](foo(and(bar))</p>\n',
        id='link_unbalanced_parens',
    ),
    pytest.param(
        '[link](foo\\(and\\(bar\\))\n',
        '<p><a href="foo(and(bar)">link</a></p>\n',
        id='link_escaped_unbalanced',
    ),
    pytest.param(
        '[link](<foo(and(bar)>)\n',
        '<p><a href="foo(and(bar)">link</a></p>\n',
        id='link_angle_unbalanced',
    ),
    pytest.param(
        '[link](foo\\)\\:)\n',
        '<p><a href="foo):">link</a></p>\n',
        id='link_escaped_close_colon',
    ),
    pytest.param(
        '[link](#fragment)\n\n[link](http://example.com#fragment)\n\n[link](http://example.com?foo=3#frag)\n',
        '<p><a href="#fragment">link</a></p>\n<p><a href="http://example.com#fragment">link</a></p>\n<p><a href="http://example.com?foo=3#frag">link</a></p>\n',
        id='link_fragments',
    ),
    pytest.param(
        '[link](foo\\bar)\n',
        '<p><a href="foo%5Cbar">link</a></p>\n',
        id='link_backslash_dest',
    ),
    pytest.param(
        '[link](/url "title")\n[link](/url \'title\')\n[link](/url (title))\n',
        '<p><a href="/url" title="title">link</a>\n<a href="/url" title="title">link</a>\n<a href="/url" title="title">link</a></p>\n',
        id='link_title_quotes_kinds',
    ),
    pytest.param(
        '[link](/url "title \\"q\\"")\n',
        '<p><a href="/url" title="title &quot;q&quot;">link</a></p>\n',
        id='link_title_escaped_quotes',
    ),
    pytest.param(
        '[link](/url "title "and" title")\n',
        '<p>[link](/url &quot;title &quot;and&quot; title&quot;)</p>\n',
        id='link_title_unescaped_quotes_invalid',
    ),
    pytest.param(
        '[link](/url \'title "and" title\')\n',
        '<p><a href="/url" title="title &quot;and&quot; title">link</a></p>\n',
        id='link_title_other_quotes',
    ),
    pytest.param(
        '[link](   /uri\n  "title"  )\n',
        '<p><a href="/uri" title="title">link</a></p>\n',
        id='link_whitespace_around',
    ),
    pytest.param(
        '[link] (/uri)\n',
        '<p>[link] (/uri)</p>\n',
        id='link_space_before_paren',
    ),
    pytest.param(
        '[link [foo [bar]]](/uri)\n',
        '<p><a href="/uri">link [foo [bar]]</a></p>\n',
        id='link_nested_brackets',
    ),
    pytest.param(
        '[link] bar](/uri)\n',
        '<p>[link] bar](/uri)</p>\n',
        id='link_unbalanced_bracket_text',
    ),
    pytest.param(
        '[link [bar](/uri)\n',
        '<p>[link <a href="/uri">bar</a></p>\n',
        id='link_inner_bracket_opener',
    ),
    pytest.param(
        '[link \\[bar](/uri)\n',
        '<p><a href="/uri">link [bar</a></p>\n',
        id='link_escaped_bracket_text',
    ),
    pytest.param(
        '[link *foo **bar** `#`*](/uri)\n',
        '<p><a href="/uri">link <em>foo <strong>bar</strong> <code>#</code></em></a></p>\n',
        id='link_rich_text',
    ),
    pytest.param(
        '[![logo](logo.png)](/home)\n',
        '<p><a href="/home"><img src="logo.png" alt="logo" /></a></p>\n',
        id='link_image_inside',
    ),
    pytest.param(
        '[foo [bar](/uri)](/uri)\n',
        '<p>[foo <a href="/uri">bar</a>](/uri)</p>\n',
        id='link_no_nested_links',
    ),
    pytest.param(
        '[foo *[bar [baz](/uri)](/uri)*](/uri)\n',
        '<p>[foo <em>[bar <a href="/uri">baz</a>](/uri)</em>](/uri)</p>\n',
        id='link_no_nested_deep',
    ),
    pytest.param(
        '![[[foo](uri1)](uri2)](uri3)\n',
        '<p><img src="uri3" alt="[foo](uri2)" /></p>\n',
        id='image_nested_links_alt',
    ),
    pytest.param(
        '*[foo*](/uri)\n',
        '<p>*<a href="/uri">foo*</a></p>\n',
        id='link_bracket_beats_emphasis',
    ),
    pytest.param(
        '[foo *bar](baz*)\n',
        '<p><a href="baz*">foo *bar</a></p>\n',
        id='link_dest_contains_star',
    ),
    pytest.param(
        '*foo [bar* baz]\n',
        '<p><em>foo [bar</em> baz]</p>\n',
        id='link_not_link_emphasis',
    ),
    pytest.param(
        '[foo`](/uri)`\n',
        '<p>[foo<code>](/uri)</code></p>\n',
        id='link_code_span_precedence',
    ),
    pytest.param(
        '[foo<http://example.com/?search=](uri)>\n',
        '<p>[foo<a href="http://example.com/?search=%5D(uri)">http://example.com/?search=](uri)</a></p>\n',
        id='link_autolink_precedence',
    ),
    pytest.param(
        '[a](/b"c")\n',
        '<p><a href="/b%22c%22">a</a></p>\n',
        id='link_dest_quote_no_space',
    ),
    pytest.param(
        '[a](</b c> "t")\n',
        '<p><a href="/b%20c" title="t">a</a></p>\n',
        id='link_angle_dest_title',
    ),
    pytest.param(
        "[x](y 'z' w)\n",
        "<p>[x](y 'z' w)</p>\n",
        id='link_title_then_garbage',
    ),
    pytest.param(
        '[a](/u "x < y & z > w")\n',
        '<p><a href="/u" title="x &lt; y &amp; z &gt; w">a</a></p>\n',
        id='link_title_escaping',
    ),
    pytest.param(
        '[a\nb](/u)\n',
        '<p><a href="/u">a\nb</a></p>\n',
        id='link_text_across_lines',
    ),
    pytest.param(
        '[a](/u\n"t")\n',
        '<p><a href="/u" title="t">a</a></p>\n',
        id='link_title_next_line',
    ),
    pytest.param(
        "![a](/u 'b\nc')\n",
        '<p><img src="/u" alt="a" title="b\nc" /></p>\n',
        id='img_title_with_newline',
    ),
    pytest.param(
        '[foo][bar]\n\n[bar]: /url "title"\n',
        '<p><a href="/url" title="title">foo</a></p>\n',
        id='ref_full',
    ),
    pytest.param(
        '[link [foo [bar]]][ref]\n\n[ref]: /uri\n',
        '<p><a href="/uri">link [foo [bar]]</a></p>\n',
        id='ref_full_nested_brackets',
    ),
    pytest.param(
        '[link \\[bar][ref]\n\n[ref]: /uri\n',
        '<p><a href="/uri">link [bar</a></p>\n',
        id='ref_full_escaped_bracket',
    ),
    pytest.param(
        '[link *foo **bar** `#`*][ref]\n\n[ref]: /uri\n',
        '<p><a href="/uri">link <em>foo <strong>bar</strong> <code>#</code></em></a></p>\n',
        id='ref_full_rich_text',
    ),
    pytest.param(
        '[![logo](logo.png)][home]\n\n[home]: /index\n',
        '<p><a href="/index"><img src="logo.png" alt="logo" /></a></p>\n',
        id='ref_full_image_text',
    ),
    pytest.param(
        '[foo [bar](/uri)][ref]\n\n[ref]: /uri\n',
        '<p>[foo <a href="/uri">bar</a>]<a href="/uri">ref</a></p>\n',
        id='ref_full_no_nested_links',
    ),
    pytest.param(
        '[foo *bar [baz][ref]*][ref]\n\n[ref]: /uri\n',
        '<p>[foo <em>bar <a href="/uri">baz</a></em>]<a href="/uri">ref</a></p>\n',
        id='ref_full_nested_ref',
    ),
    pytest.param(
        '*[foo*][ref]\n\n[ref]: /uri\n',
        '<p>*<a href="/uri">foo*</a></p>\n',
        id='ref_full_bracket_beats_emphasis',
    ),
    pytest.param(
        '[foo *bar][ref]*\n\n[ref]: /uri\n',
        '<p><a href="/uri">foo *bar</a>*</p>\n',
        id='ref_full_emphasis_outside',
    ),
    pytest.param(
        '[foo`][ref]`\n\n[ref]: /uri\n',
        '<p>[foo<code>][ref]</code></p>\n',
        id='ref_full_code_precedence',
    ),
    pytest.param(
        '[foo][BaR]\n\n[bar]: /url "title"\n',
        '<p><a href="/url" title="title">foo</a></p>\n',
        id='ref_case_insensitive',
    ),
    pytest.param(
        '[ẞ]\n\n[SS]: /url\n',
        '<p><a href="/url">ẞ</a></p>\n',
        id='ref_unicode_case_fold',
    ),
    pytest.param(
        '[Foo\n  bar]: /url\n\n[Baz][Foo bar]\n',
        '<p><a href="/url">Baz</a></p>\n',
        id='ref_whitespace_collapse',
    ),
    pytest.param(
        '[foo] [bar]\n\n[bar]: /url "title"\n',
        '<p>[foo] <a href="/url" title="title">bar</a></p>\n',
        id='ref_space_between_labels',
    ),
    pytest.param(
        '[foo]\n[bar]\n\n[bar]: /url "title"\n',
        '<p>[foo]\n<a href="/url" title="title">bar</a></p>\n',
        id='ref_newline_between_labels',
    ),
    pytest.param(
        '[foo]: /url1\n\n[foo]: /url2\n\n[bar][foo]\n',
        '<p><a href="/url1">bar</a></p>\n',
        id='ref_first_definition_wins',
    ),
    pytest.param(
        '[bar][foo\\!]\n\n[foo!]: /url\n',
        '<p>[bar][foo!]</p>\n',
        id='ref_escapes_not_normalized',
    ),
    pytest.param(
        '[foo][ref[]\n\n[ref[]: /uri\n',
        '<p>[foo][ref[]</p>\n<p>[ref[]: /uri</p>\n',
        id='ref_label_with_open_bracket',
    ),
    pytest.param(
        '[foo][ref[bar]]\n\n[ref[bar]]: /uri\n',
        '<p>[foo][ref[bar]]</p>\n<p>[ref[bar]]: /uri</p>\n',
        id='ref_label_nested_brackets',
    ),
    pytest.param(
        '[[[foo]]]\n\n[[[foo]]]: /url\n',
        '<p>[[[foo]]]</p>\n<p>[[[foo]]]: /url</p>\n',
        id='ref_triple_brackets',
    ),
    pytest.param(
        '[foo][ref\\[]\n\n[ref\\[]: /uri\n',
        '<p><a href="/uri">foo</a></p>\n',
        id='ref_label_escaped_bracket',
    ),
    pytest.param(
        '[bar\\\\]: /uri\n\n[bar\\\\]\n',
        '<p><a href="/uri">bar\\</a></p>\n',
        id='ref_label_escaped_backslash',
    ),
    pytest.param(
        '[]\n\n[]: /uri\n',
        '<p>[]</p>\n<p>[]: /uri</p>\n',
        id='ref_empty_label',
    ),
    pytest.param(
        '[\n ]\n\n[\n ]: /uri\n',
        '<p>[\n]</p>\n<p>[\n]: /uri</p>\n',
        id='ref_blank_label',
    ),
    pytest.param(
        '[foo][]\n\n[foo]: /url "title"\n',
        '<p><a href="/url" title="title">foo</a></p>\n',
        id='ref_collapsed',
    ),
    pytest.param(
        '[*foo* bar][]\n\n[*foo* bar]: /url "title"\n',
        '<p><a href="/url" title="title"><em>foo</em> bar</a></p>\n',
        id='ref_collapsed_rich',
    ),
    pytest.param(
        '[Foo][]\n\n[foo]: /url "title"\n',
        '<p><a href="/url" title="title">Foo</a></p>\n',
        id='ref_collapsed_case',
    ),
    pytest.param(
        '[foo] \n[]\n\n[foo]: /url "title"\n',
        '<p><a href="/url" title="title">foo</a>\n[]</p>\n',
        id='ref_collapsed_newline',
    ),
    pytest.param(
        '[foo]\n\n[foo]: /url "title"\n',
        '<p><a href="/url" title="title">foo</a></p>\n',
        id='ref_shortcut',
    ),
    pytest.param(
        '[*foo* bar]\n\n[*foo* bar]: /url "title"\n',
        '<p><a href="/url" title="title"><em>foo</em> bar</a></p>\n',
        id='ref_shortcut_rich',
    ),
    pytest.param(
        '[[*foo* bar]]\n\n[*foo* bar]: /url "title"\n',
        '<p>[<a href="/url" title="title"><em>foo</em> bar</a>]</p>\n',
        id='ref_shortcut_in_brackets',
    ),
    pytest.param(
        '[[bar [foo]\n\n[foo]: /url\n',
        '<p>[[bar <a href="/url">foo</a></p>\n',
        id='ref_shortcut_unclosed_outer',
    ),
    pytest.param(
        '[foo] bar\n\n[foo]: /url\n',
        '<p><a href="/url">foo</a> bar</p>\n',
        id='ref_shortcut_then_text',
    ),
    pytest.param(
        '\\[foo]\n\n[foo]: /url "title"\n',
        '<p>[foo]</p>\n',
        id='ref_shortcut_escaped',
    ),
    pytest.param(
        '[foo*]: /url\n\n*[foo*]\n',
        '<p>*<a href="/url">foo*</a></p>\n',
        id='ref_label_with_star',
    ),
    pytest.param(
        '[foo][bar]\n\n[foo]: /url1\n[bar]: /url2\n',
        '<p><a href="/url2">foo</a></p>\n',
        id='ref_full_beats_shortcut',
    ),
    pytest.param(
        '[foo]()\n\n[foo]: /url1\n',
        '<p><a href="">foo</a></p>\n',
        id='ref_inline_empty_beats_ref',
    ),
    pytest.param(
        '[foo](not a link)\n\n[foo]: /url1\n',
        '<p><a href="/url1">foo</a>(not a link)</p>\n',
        id='ref_inline_fail_falls_back',
    ),
    pytest.param(
        '[foo][bar][baz]\n\n[baz]: /url\n',
        '<p>[foo]<a href="/url">bar</a></p>\n',
        id='ref_three_labels_last',
    ),
    pytest.param(
        '[foo][bar][baz]\n\n[baz]: /url1\n[bar]: /url2\n',
        '<p><a href="/url2">foo</a><a href="/url1">baz</a></p>\n',
        id='ref_three_labels_two_links',
    ),
    pytest.param(
        '[foo][bar][baz]\n\n[baz]: /url1\n[foo]: /url2\n',
        '<p>[foo]<a href="/url1">bar</a></p>\n',
        id='ref_three_labels_first_defined',
    ),
    pytest.param(
        '[foo][bar]\n\n[foo]: /url\n',
        '<p>[foo][bar]</p>\n',
        id='ref_undefined_second_label',
    ),
    pytest.param(
        '[foo]: /url "title"\n\n[foo]\n',
        '<p><a href="/url" title="title">foo</a></p>\n',
        id='def_basic',
    ),
    pytest.param(
        "   [doc]: \n      /manual  \n           'The Manual'  \n\n[doc]\n",
        '<p><a href="/manual" title="The Manual">doc</a></p>\n',
        id='def_multiline_parts',
    ),
    pytest.param(
        "[Ab*cd\\]]:my_(path) 'note (in parens)'\n\n[Ab*cd\\]]\n",
        '<p><a href="my_(path)" title="note (in parens)">Ab*cd]</a></p>\n',
        id='def_label_escapes_parens_title',
    ),
    pytest.param(
        "[Foo bar]:\n<my url>\n'title'\n\n[Foo bar]\n",
        '<p><a href="my%20url" title="title">Foo bar</a></p>\n',
        id='def_angle_dest_next_lines',
    ),
    pytest.param(
        "[foo]: /url '\ntitle\nline1\nline2\n'\n\n[foo]\n",
        '<p><a href="/url" title="\ntitle\nline1\nline2\n">foo</a></p>\n',
        id='def_title_multiline',
    ),
    pytest.param(
        "[foo]: /url 'title\n\nwith blank line'\n\n[foo]\n",
        "<p>[foo]: /url 'title</p>\n<p>with blank line'</p>\n<p>[foo]</p>\n",
        id='def_title_blank_line_invalid',
    ),
    pytest.param(
        '[foo]:\n/url\n\n[foo]\n',
        '<p><a href="/url">foo</a></p>\n',
        id='def_dest_next_line',
    ),
    pytest.param(
        '[foo]:\n\n[foo]\n',
        '<p>[foo]:</p>\n<p>[foo]</p>\n',
        id='def_missing_dest',
    ),
    pytest.param(
        '[foo]: <>\n\n[foo]\n',
        '<p><a href="">foo</a></p>\n',
        id='def_empty_angle_dest',
    ),
    pytest.param(
        '[foo]: /url\\bar\\*baz "foo\\"bar\\baz"\n\n[foo]\n',
        '<p><a href="/url%5Cbar*baz" title="foo&quot;bar\\baz">foo</a></p>\n',
        id='def_escapes_in_dest_title',
    ),
    pytest.param(
        '[foo]\n\n[foo]: url\n',
        '<p><a href="url">foo</a></p>\n',
        id='def_after_use',
    ),
    pytest.param(
        '[foo]\n\n[foo]: first\n[foo]: second\n',
        '<p><a href="first">foo</a></p>\n',
        id='def_duplicate_first_wins',
    ),
    pytest.param(
        '[FOO]: /url\n\n[Foo]\n',
        '<p><a href="/url">Foo</a></p>\n',
        id='def_case_insensitive',
    ),
    pytest.param(
        '[ΔΕΛΤΑ]: /δέλτα\n\n[δελτα]\n',
        '<p><a href="/%CE%B4%CE%AD%CE%BB%CF%84%CE%B1">δελτα</a></p>\n',
        id='def_greek_case_and_encoding',
    ),
    pytest.param(
        '[foo]: /url\n',
        '',
        id='def_only',
    ),
    pytest.param(
        '[\nfoo\n]: /url\nbar\n',
        '<p>bar</p>\n',
        id='def_label_lines_then_text',
    ),
    pytest.param(
        '[foo]: /url "title" ok\n',
        '<p>[foo]: /url &quot;title&quot; ok</p>\n',
        id='def_title_then_text_invalid',
    ),
    pytest.param(
        '[foo]: /url\n"title" ok\n',
        '<p>&quot;title&quot; ok</p>\n',
        id='def_title_next_line_then_text',
    ),
    pytest.param(
        '    [foo]: /url "title"\n\n[foo]\n',
        '<pre><code>[foo]: /url &quot;title&quot;\n</code></pre>\n<p>[foo]</p>\n',
        id='def_indented_code_not_def',
    ),
    pytest.param(
        '```\n[foo]: /url\n```\n\n[foo]\n',
        '<pre><code>[foo]: /url\n</code></pre>\n<p>[foo]</p>\n',
        id='def_in_fence_not_def',
    ),
    pytest.param(
        'Foo\n[bar]: /baz\n\n[bar]\n',
        '<p>Foo\n[bar]: /baz</p>\n<p>[bar]</p>\n',
        id='def_cannot_interrupt_paragraph',
    ),
    pytest.param(
        '# [Foo]\n[foo]: /url\n> bar\n',
        '<h1><a href="/url">Foo</a></h1>\n<blockquote>\n<p>bar</p>\n</blockquote>\n',
        id='def_then_heading_quote',
    ),
    pytest.param(
        '[one]: /1 "first"\n[two]: /2\n  "second"\n[three]: /3\n\n[one],\n[two],\n[three]\n',
        '<p><a href="/1" title="first">one</a>,\n<a href="/2" title="second">two</a>,\n<a href="/3">three</a></p>\n',
        id='def_several_in_a_row',
    ),
    pytest.param(
        '[foo]\n\n> [foo]: /url\n',
        '<p><a href="/url">foo</a></p>\n<blockquote>\n</blockquote>\n',
        id='def_inside_quote_global',
    ),
    pytest.param(
        "[foo]: /url 'title\n\n[foo]\n",
        "<p>[foo]: /url 'title</p>\n<p>[foo]</p>\n",
        id='def_unterminated_title',
    ),
    pytest.param(
        '[a]:/b\n[a]\n',
        '<p><a href="/b">a</a></p>\n',
        id='def_then_paragraph_same_block',
    ),
    pytest.param(
        '![foo](/url "title")\n',
        '<p><img src="/url" alt="foo" title="title" /></p>\n',
        id='img_basic_title',
    ),
    pytest.param(
        '![a *b* c]\n\n[a *b* c]: pic.png "cats & dogs"\n',
        '<p><img src="pic.png" alt="a b c" title="cats &amp; dogs" /></p>\n',
        id='img_alt_plain_text_ref',
    ),
    pytest.param(
        '![foo ![bar](/url)](/url2)\n',
        '<p><img src="/url2" alt="foo bar" /></p>\n',
        id='img_nested_image_alt',
    ),
    pytest.param(
        '![foo [bar](/url)](/url2)\n',
        '<p><img src="/url2" alt="foo bar" /></p>\n',
        id='img_link_in_alt',
    ),
    pytest.param(
        '![foo](train.jpg)\n',
        '<p><img src="train.jpg" alt="foo" /></p>\n',
        id='img_simple',
    ),
    pytest.param(
        'See ![two words](/img/x.png  "cap"   )\n',
        '<p>See <img src="/img/x.png" alt="two words" title="cap" /></p>\n',
        id='img_whitespace_title',
    ),
    pytest.param(
        '![foo](<url>)\n',
        '<p><img src="url" alt="foo" /></p>\n',
        id='img_angle_dest',
    ),
    pytest.param(
        '![](/url)\n',
        '<p><img src="/url" alt="" /></p>\n',
        id='img_empty_alt',
    ),
    pytest.param(
        '![foo][bar]\n\n[bar]: /url\n',
        '<p><img src="/url" alt="foo" /></p>\n',
        id='img_full_ref',
    ),
    pytest.param(
        '![foo][]\n\n[foo]: /url "title"\n',
        '<p><img src="/url" alt="foo" title="title" /></p>\n',
        id='img_collapsed_ref',
    ),
    pytest.param(
        '![*foo* bar]\n\n[*foo* bar]: /url "title"\n',
        '<p><img src="/url" alt="foo bar" title="title" /></p>\n',
        id='img_shortcut_rich',
    ),
    pytest.param(
        '\\![foo]\n\n[foo]: /url "title"\n',
        '<p>!<a href="/url" title="title">foo</a></p>\n',
        id='img_escaped_bang',
    ),
    pytest.param(
        '!\\[foo]\n\n[foo]: /url "title"\n',
        '<p>![foo]</p>\n',
        id='img_escaped_bracket',
    ),
    pytest.param(
        '![a `b` "c"](/u)\n',
        '<p><img src="/u" alt="a b &quot;c&quot;" /></p>\n',
        id='img_alt_code_and_quotes',
    ),
    pytest.param(
        '![x](/a b)\n',
        '<p>![x](/a b)</p>\n',
        id='img_invalid_dest',
    ),
    pytest.param(
        '[a](</ä ö>)\n',
        '<p><a href="/%C3%A4%20%C3%B6">a</a></p>\n',
        id='url_non_ascii_and_space',
    ),
    pytest.param(
        '[a](/a%2Gb%41)\n',
        '<p><a href="/a%252Gb%41">a</a></p>\n',
        id='url_percent_kept_or_encoded',
    ),
    pytest.param(
        '[a](/q?x=1&y=[2])\n',
        '<p><a href="/q?x=1&amp;y=%5B2%5D">a</a></p>\n',
        id='url_ampersand_brackets',
    ),
    pytest.param(
        '[a](/{x}|^`)\n',
        '<p><a href="/%7Bx%7D%7C%5E%60">a</a></p>\n',
        id='url_unsafe_ascii',
    ),
    pytest.param(
        '[a](/%)\n',
        '<p><a href="/%25">a</a></p>\n',
        id='url_lone_percent',
    ),
    pytest.param(
        '![a](/x"y)\n',
        '<p><img src="/x%22y" alt="a" /></p>\n',
        id='url_quote_in_image',
    ),
    pytest.param(
        '[a](/~user/!$&*+,;=:@)\n',
        '<p><a href="/~user/!$&amp;*+,;=:@">a</a></p>\n',
        id='url_safe_chars_kept',
    ),
    pytest.param(
        '<mailto:x@y.z?subject=Hi%20There>\n',
        '<p><a href="mailto:x@y.z?subject=Hi%20There">mailto:x@y.z?subject=Hi%20There</a></p>\n',
        id='url_percent_escape_kept_autolink',
    ),
]


@pytest.mark.parametrize("src, expected", CASES)
def test_links(src, expected):
    assert render(src) == expected
