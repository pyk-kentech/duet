"""mdlite 숨은 테스트 — 블록: 문단, ATX·setext 제목, 구분선, 들여쓴·펜스 코드 블록.

기대값은 CommonMark 0.31.2 참조 구현(commonmark.js 0.31.2)의 출력을 그대로 적은 것이다.
"""

import pytest

from mdlite import render

CASES = [
    pytest.param(
        '',
        '',
        id='empty_input',
    ),
    pytest.param(
        '\n\n   \n',
        '',
        id='only_blank_lines',
    ),
    pytest.param(
        'hello world',
        '<p>hello world</p>\n',
        id='single_paragraph_no_newline',
    ),
    pytest.param(
        'aaa\n\nbbb\n',
        '<p>aaa</p>\n<p>bbb</p>\n',
        id='two_paragraphs',
    ),
    pytest.param(
        'aaa\n\n\n\nbbb\n',
        '<p>aaa</p>\n<p>bbb</p>\n',
        id='many_blank_lines_between',
    ),
    pytest.param(
        '  aaa\n bbb\n',
        '<p>aaa\nbbb</p>\n',
        id='leading_spaces_stripped',
    ),
    pytest.param(
        'aaa\n             bbb\n                                       ccc\n',
        '<p>aaa\nbbb\nccc</p>\n',
        id='deep_continuation_lines',
    ),
    pytest.param(
        '   aaa\nbbb\n',
        '<p>aaa\nbbb</p>\n',
        id='first_line_three_spaces',
    ),
    pytest.param(
        '    aaa\nbbb\n',
        '<pre><code>aaa\n</code></pre>\n<p>bbb</p>\n',
        id='first_line_four_spaces_is_code',
    ),
    pytest.param(
        'Tom & Jerry say "1 < 2" and 3 > 2\n',
        '<p>Tom &amp; Jerry say &quot;1 &lt; 2&quot; and 3 &gt; 2</p>\n',
        id='html_escape_text',
    ),
    pytest.param(
        '5 * 3 = 15 and 2 _ 4\n',
        '<p>5 * 3 = 15 and 2 _ 4</p>\n',
        id='lone_delimiters_literal',
    ),
    pytest.param(
        '# foo\n## foo\n### foo\n#### foo\n##### foo\n###### foo\n',
        '<h1>foo</h1>\n<h2>foo</h2>\n<h3>foo</h3>\n<h4>foo</h4>\n<h5>foo</h5>\n<h6>foo</h6>\n',
        id='atx_levels',
    ),
    pytest.param(
        '####### foo\n',
        '<p>####### foo</p>\n',
        id='atx_seven_hashes',
    ),
    pytest.param(
        '#5 bolt\n\n#hashtag\n',
        '<p>#5 bolt</p>\n<p>#hashtag</p>\n',
        id='atx_needs_space',
    ),
    pytest.param(
        '\\## foo\n',
        '<p>## foo</p>\n',
        id='atx_escaped_hash',
    ),
    pytest.param(
        '# foo *bar* \\*baz\\*\n',
        '<h1>foo <em>bar</em> *baz*</h1>\n',
        id='atx_inline_content',
    ),
    pytest.param(
        '#                  foo                     \n',
        '<h1>foo</h1>\n',
        id='atx_surrounding_spaces',
    ),
    pytest.param(
        ' ### foo\n  ## foo\n   # foo\n',
        '<h3>foo</h3>\n<h2>foo</h2>\n<h1>foo</h1>\n',
        id='atx_indent_up_to_three',
    ),
    pytest.param(
        '    # foo\n',
        '<pre><code># foo\n</code></pre>\n',
        id='atx_indent_four_is_code',
    ),
    pytest.param(
        'foo\n    # bar\n',
        '<p>foo\n# bar</p>\n',
        id='atx_indented_continuation',
    ),
    pytest.param(
        '## foo ##\n  ###   bar    ###\n',
        '<h2>foo</h2>\n<h3>bar</h3>\n',
        id='atx_closing_sequence',
    ),
    pytest.param(
        '# foo ##################################\n##### foo ##\n',
        '<h1>foo</h1>\n<h5>foo</h5>\n',
        id='atx_closing_any_length',
    ),
    pytest.param(
        '### foo ###     \n',
        '<h3>foo</h3>\n',
        id='atx_closing_trailing_spaces',
    ),
    pytest.param(
        '### foo ### b\n',
        '<h3>foo ### b</h3>\n',
        id='atx_hashes_then_text',
    ),
    pytest.param(
        '# foo#\n',
        '<h1>foo#</h1>\n',
        id='atx_hash_no_space_kept',
    ),
    pytest.param(
        '### foo \\###\n## foo #\\##\n# foo \\#\n',
        '<h3>foo ###</h3>\n<h2>foo ###</h2>\n<h1>foo #</h1>\n',
        id='atx_escaped_closing',
    ),
    pytest.param(
        '# a # b #\n',
        '<h1>a # b</h1>\n',
        id='atx_inner_hash_kept',
    ),
    pytest.param(
        '****\n## foo\n****\n',
        '<hr />\n<h2>foo</h2>\n<hr />\n',
        id='atx_between_breaks',
    ),
    pytest.param(
        'Foo bar\n# baz\nBar foo\n',
        '<p>Foo bar</p>\n<h1>baz</h1>\n<p>Bar foo</p>\n',
        id='atx_interrupts_paragraph',
    ),
    pytest.param(
        '## \n#\n### ###\n',
        '<h2></h2>\n<h1></h1>\n<h3></h3>\n',
        id='atx_empty',
    ),
    pytest.param(
        'Big *one*\n=========\n\nSmall *one*\n---------\n',
        '<h1>Big <em>one</em></h1>\n<h2>Small <em>one</em></h2>\n',
        id='setext_basic',
    ),
    pytest.param(
        'Big *one\ntwo*\n====\n',
        '<h1>Big <em>one\ntwo</em></h1>\n',
        id='setext_multiline',
    ),
    pytest.param(
        'Foo  \nbar\n===\n',
        '<h1>Foo<br />\nbar</h1>\n',
        id='setext_hard_break_inside',
    ),
    pytest.param(
        'Foo\n-------------------------\n\nFoo\n=\n',
        '<h2>Foo</h2>\n<h1>Foo</h1>\n',
        id='setext_underline_lengths',
    ),
    pytest.param(
        'Foo\n-\n',
        '<h2>Foo</h2>\n',
        id='setext_single_dash',
    ),
    pytest.param(
        '   Foo\n---\n\n  Foo\n-----\n\n  Foo\n  ===\n',
        '<h2>Foo</h2>\n<h2>Foo</h2>\n<h1>Foo</h1>\n',
        id='setext_indents',
    ),
    pytest.param(
        '    Foo\n    ---\n\n    Foo\n---\n',
        '<pre><code>Foo\n---\n\nFoo\n</code></pre>\n<hr />\n',
        id='setext_code_indent',
    ),
    pytest.param(
        'Foo\n   ----      \n',
        '<h2>Foo</h2>\n',
        id='setext_underline_indent',
    ),
    pytest.param(
        'Foo\n    ---\n',
        '<p>Foo\n---</p>\n',
        id='setext_underline_four_spaces',
    ),
    pytest.param(
        'Foo\n= =\n\nFoo\n--- -\n',
        '<p>Foo\n= =</p>\n<p>Foo</p>\n<hr />\n',
        id='setext_underline_internal_space',
    ),
    pytest.param(
        'Foo  \n-----\n',
        '<h2>Foo</h2>\n',
        id='setext_trailing_spaces_content',
    ),
    pytest.param(
        'Foo\\\n----\n',
        '<h2>Foo\\</h2>\n',
        id='setext_trailing_backslash',
    ),
    pytest.param(
        '> foo\nbar\n===\n',
        '<blockquote>\n<p>foo\nbar\n===</p>\n</blockquote>\n',
        id='setext_not_lazy_in_quote',
    ),
    pytest.param(
        '> Foo\n---\n',
        '<blockquote>\n<p>Foo</p>\n</blockquote>\n<hr />\n',
        id='setext_after_quote_is_hr',
    ),
    pytest.param(
        '- Foo\n---\n',
        '<ul>\n<li>Foo</li>\n</ul>\n<hr />\n',
        id='setext_after_list_is_hr',
    ),
    pytest.param(
        'Foo\nBar\n---\n',
        '<h2>Foo\nBar</h2>\n',
        id='setext_two_line_h2',
    ),
    pytest.param(
        '---\nFoo\n---\nBar\n---\nBaz\n',
        '<hr />\n<h2>Foo</h2>\n<h2>Bar</h2>\n<p>Baz</p>\n',
        id='setext_sequence',
    ),
    pytest.param(
        '\n====\n',
        '<p>====</p>\n',
        id='setext_empty_paragraph',
    ),
    pytest.param(
        '\\> foo\n------\n',
        '<h2>&gt; foo</h2>\n',
        id='setext_escaped_gt',
    ),
    pytest.param(
        'Foo\n\nbar\n---\nbaz\n',
        '<p>Foo</p>\n<h2>bar</h2>\n<p>baz</p>\n',
        id='setext_only_last_paragraph',
    ),
    pytest.param(
        'Foo\nbar\n\\---\nbaz\n',
        '<p>Foo\nbar\n---\nbaz</p>\n',
        id='setext_escaped_underline',
    ),
    pytest.param(
        '- Foo\n  ---\n  bar\n',
        '<ul>\n<li>\n<h2>Foo</h2>\nbar</li>\n</ul>\n',
        id='setext_in_list_item',
    ),
    pytest.param(
        '***\n---\n___\n',
        '<hr />\n<hr />\n<hr />\n',
        id='hr_three_kinds',
    ),
    pytest.param(
        '+++\n\n===\n',
        '<p>+++</p>\n<p>===</p>\n',
        id='hr_wrong_chars',
    ),
    pytest.param(
        '--\n**\n__\n',
        '<p>--\n**\n__</p>\n',
        id='hr_too_few',
    ),
    pytest.param(
        ' ***\n  ***\n   ***\n',
        '<hr />\n<hr />\n<hr />\n',
        id='hr_indent',
    ),
    pytest.param(
        '    ***\n',
        '<pre><code>***\n</code></pre>\n',
        id='hr_indent_four',
    ),
    pytest.param(
        ' - - -\n **  * ** * ** * **\n-     -      -      -\n- - - -    \n',
        '<hr />\n<hr />\n<hr />\n<hr />\n',
        id='hr_spaces_between',
    ),
    pytest.param(
        '_ _ _ _ a\n\na------\n\n---a---\n',
        '<p>_ _ _ _ a</p>\n<p>a------</p>\n<p>---a---</p>\n',
        id='hr_other_chars_not_allowed',
    ),
    pytest.param(
        ' *-*\n',
        '<p><em>-</em></p>\n',
        id='hr_not_mixed',
    ),
    pytest.param(
        '- foo\n***\n- bar\n',
        '<ul>\n<li>foo</li>\n</ul>\n<hr />\n<ul>\n<li>bar</li>\n</ul>\n',
        id='hr_between_lists',
    ),
    pytest.param(
        'Foo\n***\nbar\n',
        '<p>Foo</p>\n<hr />\n<p>bar</p>\n',
        id='hr_interrupts_paragraph',
    ),
    pytest.param(
        '* Foo\n* * *\n* Bar\n',
        '<ul>\n<li>Foo</li>\n</ul>\n<hr />\n<ul>\n<li>Bar</li>\n</ul>\n',
        id='hr_beats_list_item',
    ),
    pytest.param(
        '- Foo\n- * * *\n',
        '<ul>\n<li>Foo</li>\n<li>\n<hr />\n</li>\n</ul>\n',
        id='hr_inside_list_item',
    ),
    pytest.param(
        'Foo\nbar\n* * *\nbaz\n',
        '<p>Foo\nbar</p>\n<hr />\n<p>baz</p>\n',
        id='hr_dashes_after_paragraph_spaced',
    ),
    pytest.param(
        '    a simple\n      indented code block\n',
        '<pre><code>a simple\n  indented code block\n</code></pre>\n',
        id='icode_basic',
    ),
    pytest.param(
        '    <a/>\n    *hi*\n\n    - one\n',
        '<pre><code>&lt;a/&gt;\n*hi*\n\n- one\n</code></pre>\n',
        id='icode_content_escaped',
    ),
    pytest.param(
        '    chunk1\n\n    chunk2\n  \n \n \n    chunk3\n',
        '<pre><code>chunk1\n\nchunk2\n\n\n\nchunk3\n</code></pre>\n',
        id='icode_blank_chunks',
    ),
    pytest.param(
        '    chunk1\n      \n      chunk2\n',
        '<pre><code>chunk1\n  \n  chunk2\n</code></pre>\n',
        id='icode_blank_line_spaces_kept',
    ),
    pytest.param(
        'Foo\n    bar\n',
        '<p>Foo\nbar</p>\n',
        id='icode_cannot_interrupt',
    ),
    pytest.param(
        '    foo\nbar\n',
        '<pre><code>foo\n</code></pre>\n<p>bar</p>\n',
        id='icode_then_paragraph',
    ),
    pytest.param(
        '# Heading\n    foo\nHeading\n------\n    foo\n----\n',
        '<h1>Heading</h1>\n<pre><code>foo\n</code></pre>\n<h2>Heading</h2>\n<pre><code>foo\n</code></pre>\n<hr />\n',
        id='icode_between_headings',
    ),
    pytest.param(
        '        foo\n    bar\n',
        '<pre><code>    foo\nbar\n</code></pre>\n',
        id='icode_extra_indent',
    ),
    pytest.param(
        '\n    \n    foo\n    \n\n',
        '<pre><code>foo\n</code></pre>\n',
        id='icode_surrounding_blank',
    ),
    pytest.param(
        '    foo  \n',
        '<pre><code>foo  \n</code></pre>\n',
        id='icode_trailing_spaces',
    ),
    pytest.param(
        '```\n<\n >\n```\n',
        '<pre><code>&lt;\n &gt;\n</code></pre>\n',
        id='fence_backticks',
    ),
    pytest.param(
        '~~~\n<\n >\n~~~\n',
        '<pre><code>&lt;\n &gt;\n</code></pre>\n',
        id='fence_tildes',
    ),
    pytest.param(
        '``\nfoo\n``\n',
        '<p><code>foo</code></p>\n',
        id='fence_two_backticks_is_span',
    ),
    pytest.param(
        '```\naaa\n~~~\n```\n',
        '<pre><code>aaa\n~~~\n</code></pre>\n',
        id='fence_close_same_char',
    ),
    pytest.param(
        '~~~\naaa\n```\n~~~\n',
        '<pre><code>aaa\n```\n</code></pre>\n',
        id='fence_close_same_char_tilde',
    ),
    pytest.param(
        '````\naaa\n```\n``````\n',
        '<pre><code>aaa\n```\n</code></pre>\n',
        id='fence_close_at_least_as_long',
    ),
    pytest.param(
        '~~~~\naaa\n~~~\n~~~~\n',
        '<pre><code>aaa\n~~~\n</code></pre>\n',
        id='fence_close_tilde_longer',
    ),
    pytest.param(
        '```\n',
        '<pre><code></code></pre>\n',
        id='fence_unclosed_empty',
    ),
    pytest.param(
        '`````\n\n```\naaa\n',
        '<pre><code>\n```\naaa\n</code></pre>\n',
        id='fence_unclosed_runs_to_end',
    ),
    pytest.param(
        '> ```\n> aaa\n\nbbb\n',
        '<blockquote>\n<pre><code>aaa\n</code></pre>\n</blockquote>\n<p>bbb</p>\n',
        id='fence_unclosed_in_quote',
    ),
    pytest.param(
        '```\n\n  \n```\n',
        '<pre><code>\n  \n</code></pre>\n',
        id='fence_blank_content',
    ),
    pytest.param(
        '```\n```\n',
        '<pre><code></code></pre>\n',
        id='fence_empty',
    ),
    pytest.param(
        ' ```\n aaa\naaa\n```\n',
        '<pre><code>aaa\naaa\n</code></pre>\n',
        id='fence_indent_one',
    ),
    pytest.param(
        '  ```\naaa\n  aaa\naaa\n  ```\n',
        '<pre><code>aaa\naaa\naaa\n</code></pre>\n',
        id='fence_indent_two',
    ),
    pytest.param(
        '   ```\n   aaa\n    aaa\n  aaa\n   ```\n',
        '<pre><code>aaa\n aaa\naaa\n</code></pre>\n',
        id='fence_indent_three',
    ),
    pytest.param(
        '    ```\n    aaa\n    ```\n',
        '<pre><code>```\naaa\n```\n</code></pre>\n',
        id='fence_indent_four_is_code',
    ),
    pytest.param(
        '```\naaa\n  ```\n',
        '<pre><code>aaa\n</code></pre>\n',
        id='fence_closing_indented',
    ),
    pytest.param(
        '   ```\naaa\n  ```\n',
        '<pre><code>aaa\n</code></pre>\n',
        id='fence_closing_indent_independent',
    ),
    pytest.param(
        '```\naaa\n    ```\n',
        '<pre><code>aaa\n    ```\n</code></pre>\n',
        id='fence_closing_four_spaces_not_close',
    ),
    pytest.param(
        '``` ```\naaa\n',
        '<p><code> </code>\naaa</p>\n',
        id='fence_backtick_info_with_backtick',
    ),
    pytest.param(
        '~~~~~~\naaa\n~~~ ~~\n',
        '<pre><code>aaa\n~~~ ~~\n</code></pre>\n',
        id='fence_closing_no_internal_space',
    ),
    pytest.param(
        'foo\n```\nbar\n```\nbaz\n',
        '<p>foo</p>\n<pre><code>bar\n</code></pre>\n<p>baz</p>\n',
        id='fence_interrupts_paragraph',
    ),
    pytest.param(
        'foo\n---\n~~~\nbar\n~~~\n# baz\n',
        '<h2>foo</h2>\n<pre><code>bar\n</code></pre>\n<h1>baz</h1>\n',
        id='fence_between_headings',
    ),
    pytest.param(
        '```ruby\ndef foo(x)\n  return 3\nend\n```\n',
        '<pre><code class="language-ruby">def foo(x)\n  return 3\nend\n</code></pre>\n',
        id='fence_info_class',
    ),
    pytest.param(
        '~~~~    ruby startline=3 $%@#$\ndef foo(x)\n  return 3\nend\n~~~~~~~\n',
        '<pre><code class="language-ruby">def foo(x)\n  return 3\nend\n</code></pre>\n',
        id='fence_info_first_word',
    ),
    pytest.param(
        '````;\n````\n',
        '<pre><code class="language-;"></code></pre>\n',
        id='fence_info_punctuation',
    ),
    pytest.param(
        '``` aa ```\nfoo\n',
        '<p><code>aa</code>\nfoo</p>\n',
        id='fence_info_backticks_span',
    ),
    pytest.param(
        '~~~ aa ``` ~~~\nfoo\n~~~\n',
        '<pre><code class="language-aa">foo\n</code></pre>\n',
        id='fence_tilde_info_backticks',
    ),
    pytest.param(
        '```\n``` aaa\n```\n',
        '<pre><code>``` aaa\n</code></pre>\n',
        id='fence_closing_no_info',
    ),
    pytest.param(
        '```a\\*b"c\nx\n```\n',
        '<pre><code class="language-a*b&quot;c">x\n</code></pre>\n',
        id='fence_info_escapes',
    ),
]


@pytest.mark.parametrize("src, expected", CASES)
def test_blocks(src, expected):
    assert render(src) == expected
