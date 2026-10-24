"""mdlite 숨은 테스트 — 컨테이너: 인용, 목록 항목과 목록(들여쓰기·중첩·촘촘함/느슨함), 게으른 이어짐.

기대값은 CommonMark 0.31.2 참조 구현(commonmark.js 0.31.2)의 출력을 그대로 적은 것이다.
"""

import pytest

from mdlite import render

CASES = [
    pytest.param(
        '> # Title\n> line one\n> line two\n',
        '<blockquote>\n<h1>Title</h1>\n<p>line one\nline two</p>\n</blockquote>\n',
        id='bq_basic',
    ),
    pytest.param(
        '># Title\n>line one\n> line two\n',
        '<blockquote>\n<h1>Title</h1>\n<p>line one\nline two</p>\n</blockquote>\n',
        id='bq_no_space',
    ),
    pytest.param(
        '   > # Title\n   > line one\n > line two\n',
        '<blockquote>\n<h1>Title</h1>\n<p>line one\nline two</p>\n</blockquote>\n',
        id='bq_indented_markers',
    ),
    pytest.param(
        '    > # Foo\n    > bar\n',
        '<pre><code>&gt; # Foo\n&gt; bar\n</code></pre>\n',
        id='bq_four_spaces_is_code',
    ),
    pytest.param(
        '> # Foo\n> bar\nbaz\n',
        '<blockquote>\n<h1>Foo</h1>\n<p>bar\nbaz</p>\n</blockquote>\n',
        id='bq_lazy_last_line',
    ),
    pytest.param(
        '> bar\nbaz\n> foo\n',
        '<blockquote>\n<p>bar\nbaz\nfoo</p>\n</blockquote>\n',
        id='bq_lazy_middle',
    ),
    pytest.param(
        '> foo\n---\n',
        '<blockquote>\n<p>foo</p>\n</blockquote>\n<hr />\n',
        id='bq_hr_not_lazy',
    ),
    pytest.param(
        '> - foo\n- bar\n',
        '<blockquote>\n<ul>\n<li>foo</li>\n</ul>\n</blockquote>\n<ul>\n<li>bar</li>\n</ul>\n',
        id='bq_list_not_lazy',
    ),
    pytest.param(
        '>     foo\n    bar\n',
        '<blockquote>\n<pre><code>foo\n</code></pre>\n</blockquote>\n<pre><code>bar\n</code></pre>\n',
        id='bq_code_not_lazy',
    ),
    pytest.param(
        '> ```\nfoo\n```\n',
        '<blockquote>\n<pre><code></code></pre>\n</blockquote>\n<p>foo</p>\n<pre><code></code></pre>\n',
        id='bq_fence_not_lazy',
    ),
    pytest.param(
        '> foo\n    - bar\n',
        '<blockquote>\n<p>foo\n- bar</p>\n</blockquote>\n',
        id='bq_lazy_indented_text',
    ),
    pytest.param(
        '>\n',
        '<blockquote>\n</blockquote>\n',
        id='bq_empty',
    ),
    pytest.param(
        '>\n>  \n> \n',
        '<blockquote>\n</blockquote>\n',
        id='bq_empty_lines',
    ),
    pytest.param(
        '>\n> foo\n>  \n',
        '<blockquote>\n<p>foo</p>\n</blockquote>\n',
        id='bq_blank_edges',
    ),
    pytest.param(
        '> foo\n\n> bar\n',
        '<blockquote>\n<p>foo</p>\n</blockquote>\n<blockquote>\n<p>bar</p>\n</blockquote>\n',
        id='bq_blank_separates',
    ),
    pytest.param(
        '> foo\n> bar\n',
        '<blockquote>\n<p>foo\nbar</p>\n</blockquote>\n',
        id='bq_two_lines_one_para',
    ),
    pytest.param(
        '> foo\n>\n> bar\n',
        '<blockquote>\n<p>foo</p>\n<p>bar</p>\n</blockquote>\n',
        id='bq_two_paragraphs',
    ),
    pytest.param(
        'foo\n> bar\n',
        '<p>foo</p>\n<blockquote>\n<p>bar</p>\n</blockquote>\n',
        id='bq_interrupts_paragraph',
    ),
    pytest.param(
        '> aaa\n***\n> bbb\n',
        '<blockquote>\n<p>aaa</p>\n</blockquote>\n<hr />\n<blockquote>\n<p>bbb</p>\n</blockquote>\n',
        id='bq_around_hr',
    ),
    pytest.param(
        '> bar\n\nbaz\n',
        '<blockquote>\n<p>bar</p>\n</blockquote>\n<p>baz</p>\n',
        id='bq_blank_then_text',
    ),
    pytest.param(
        '> bar\n>\nbaz\n',
        '<blockquote>\n<p>bar</p>\n</blockquote>\n<p>baz</p>\n',
        id='bq_empty_line_then_text',
    ),
    pytest.param(
        '> > > foo\nbar\n',
        '<blockquote>\n<blockquote>\n<blockquote>\n<p>foo\nbar</p>\n</blockquote>\n</blockquote>\n</blockquote>\n',
        id='bq_nested_lazy',
    ),
    pytest.param(
        '>>> foo\n> bar\n>>baz\n',
        '<blockquote>\n<blockquote>\n<blockquote>\n<p>foo\nbar\nbaz</p>\n</blockquote>\n</blockquote>\n</blockquote>\n',
        id='bq_nested_mixed_markers',
    ),
    pytest.param(
        '>     code\n\n>    not code\n',
        '<blockquote>\n<pre><code>code\n</code></pre>\n</blockquote>\n<blockquote>\n<p>not code</p>\n</blockquote>\n',
        id='bq_code_needs_five_spaces',
    ),
    pytest.param(
        '> a\n# b\n',
        '<blockquote>\n<p>a</p>\n</blockquote>\n<h1>b</h1>\n',
        id='bq_heading_not_lazy',
    ),
    pytest.param(
        '> - a\nb\n',
        '<blockquote>\n<ul>\n<li>a\nb</li>\n</ul>\n</blockquote>\n',
        id='bq_list_item_lazy',
    ),
    pytest.param(
        '1.  First para\n    second line.\n\n        some code\n\n    > a quote.\n',
        '<ol>\n<li>\n<p>First para\nsecond line.</p>\n<pre><code>some code\n</code></pre>\n<blockquote>\n<p>a quote.</p>\n</blockquote>\n</li>\n</ol>\n',
        id='li_paragraph_code_quote',
    ),
    pytest.param(
        '- uno\n\n dos\n',
        '<ul>\n<li>uno</li>\n</ul>\n<p>dos</p>\n',
        id='li_not_enough_indent',
    ),
    pytest.param(
        '- uno\n\n  dos\n',
        '<ul>\n<li>\n<p>uno</p>\n<p>dos</p>\n</li>\n</ul>\n',
        id='li_enough_indent',
    ),
    pytest.param(
        ' -    uno\n\n     dos\n',
        '<ul>\n<li>uno</li>\n</ul>\n<pre><code> dos\n</code></pre>\n',
        id='li_content_column_from_marker',
    ),
    pytest.param(
        ' -    uno\n\n      dos\n',
        '<ul>\n<li>\n<p>uno</p>\n<p>dos</p>\n</li>\n</ul>\n',
        id='li_content_column_reached',
    ),
    pytest.param(
        '   > > 1.  uno\n>>\n>>     dos\n',
        '<blockquote>\n<blockquote>\n<ol>\n<li>\n<p>uno</p>\n<p>dos</p>\n</li>\n</ol>\n</blockquote>\n</blockquote>\n',
        id='li_inside_nested_quotes',
    ),
    pytest.param(
        '>>- uno\n>>\n  >  > dos\n',
        '<blockquote>\n<blockquote>\n<ul>\n<li>uno</li>\n</ul>\n<p>dos</p>\n</blockquote>\n</blockquote>\n',
        id='li_quote_then_outside',
    ),
    pytest.param(
        '-one\n\n2.two\n',
        '<p>-one</p>\n<p>2.two</p>\n',
        id='li_marker_needs_space',
    ),
    pytest.param(
        '- foo\n\n\n  bar\n',
        '<ul>\n<li>\n<p>foo</p>\n<p>bar</p>\n</li>\n</ul>\n',
        id='li_multiple_blank_lines_inside',
    ),
    pytest.param(
        '1.  item\n\n    ```\n    code\n    ```\n\n    more\n\n    > quoted\n',
        '<ol>\n<li>\n<p>item</p>\n<pre><code>code\n</code></pre>\n<p>more</p>\n<blockquote>\n<p>quoted</p>\n</blockquote>\n</li>\n</ol>\n',
        id='li_complex_content',
    ),
    pytest.param(
        '123456789. ok\n',
        '<ol start="123456789">\n<li>ok</li>\n</ol>\n',
        id='li_nine_digits',
    ),
    pytest.param(
        '1234567890. not ok\n',
        '<p>1234567890. not ok</p>\n',
        id='li_ten_digits',
    ),
    pytest.param(
        '0. ok\n',
        '<ol start="0">\n<li>ok</li>\n</ol>\n',
        id='li_start_zero',
    ),
    pytest.param(
        '003. ok\n',
        '<ol start="3">\n<li>ok</li>\n</ol>\n',
        id='li_leading_zeros',
    ),
    pytest.param(
        '-1. not ok\n',
        '<p>-1. not ok</p>\n',
        id='li_negative_number',
    ),
    pytest.param(
        '- foo\n\n      bar\n',
        '<ul>\n<li>\n<p>foo</p>\n<pre><code>bar\n</code></pre>\n</li>\n</ul>\n',
        id='li_indented_code_inside',
    ),
    pytest.param(
        '  10.  foo\n\n           bar\n',
        '<ol start="10">\n<li>\n<p>foo</p>\n<pre><code>bar\n</code></pre>\n</li>\n</ol>\n',
        id='li_wide_marker_code',
    ),
    pytest.param(
        '1.     indented code\n\n   paragraph\n\n       more code\n',
        '<ol>\n<li>\n<pre><code>indented code\n</code></pre>\n<p>paragraph</p>\n<pre><code>more code\n</code></pre>\n</li>\n</ol>\n',
        id='li_starts_with_code',
    ),
    pytest.param(
        '1.      indented code\n\n   paragraph\n\n       more code\n',
        '<ol>\n<li>\n<pre><code> indented code\n</code></pre>\n<p>paragraph</p>\n<pre><code>more code\n</code></pre>\n</li>\n</ol>\n',
        id='li_starts_with_code_extra_space',
    ),
    pytest.param(
        '-    foo\n\n  bar\n',
        '<ul>\n<li>foo</li>\n</ul>\n<p>bar</p>\n',
        id='li_five_spaces_after_marker',
    ),
    pytest.param(
        '-    a\n\n    b\n',
        '<ul>\n<li>a</li>\n</ul>\n<pre><code>b\n</code></pre>\n',
        id='li_four_spaces_after_marker',
    ),
    pytest.param(
        '-  foo\n\n   bar\n',
        '<ul>\n<li>\n<p>foo</p>\n<p>bar</p>\n</li>\n</ul>\n',
        id='li_three_spaces_after_marker',
    ),
    pytest.param(
        '-\n  foo\n-\n  ```\n  bar\n  ```\n-\n      baz\n',
        '<ul>\n<li>foo</li>\n<li>\n<pre><code>bar\n</code></pre>\n</li>\n<li>\n<pre><code>baz\n</code></pre>\n</li>\n</ul>\n',
        id='li_begins_blank',
    ),
    pytest.param(
        '-   \n  foo\n',
        '<ul>\n<li>foo</li>\n</ul>\n',
        id='li_begins_blank_with_spaces',
    ),
    pytest.param(
        '-\n\n  foo\n',
        '<ul>\n<li></li>\n</ul>\n<p>foo</p>\n',
        id='li_at_most_one_blank_start',
    ),
    pytest.param(
        '- foo\n-\n- bar\n',
        '<ul>\n<li>foo</li>\n<li></li>\n<li>bar</li>\n</ul>\n',
        id='li_empty_middle',
    ),
    pytest.param(
        '- foo\n-   \n- bar\n',
        '<ul>\n<li>foo</li>\n<li></li>\n<li>bar</li>\n</ul>\n',
        id='li_empty_middle_spaces',
    ),
    pytest.param(
        '1. foo\n2.\n3. bar\n',
        '<ol>\n<li>foo</li>\n<li></li>\n<li>bar</li>\n</ol>\n',
        id='li_empty_ordered',
    ),
    pytest.param(
        '*\n',
        '<ul>\n<li></li>\n</ul>\n',
        id='li_only_marker',
    ),
    pytest.param(
        'foo\n*\n\nfoo\n1.\n',
        '<p>foo\n*</p>\n<p>foo\n1.</p>\n',
        id='li_empty_cannot_interrupt',
    ),
    pytest.param(
        ' 1.  Step one\n     goes here.\n\n  1.  Step two\n      goes here.\n',
        '<ol>\n<li>\n<p>Step one\ngoes here.</p>\n</li>\n<li>\n<p>Step two\ngoes here.</p>\n</li>\n</ol>\n',
        id='li_indent_one_to_three',
    ),
    pytest.param(
        '    1.  Step one\n        goes here.\n',
        '<pre><code>1.  Step one\n    goes here.\n</code></pre>\n',
        id='li_indent_four_is_code',
    ),
    pytest.param(
        '  1.  Step one\ngoes here.\n',
        '<ol>\n<li>Step one\ngoes here.</li>\n</ol>\n',
        id='li_lazy_paragraph',
    ),
    pytest.param(
        '> 1. > Quoted\nand lazy.\n',
        '<blockquote>\n<ol>\n<li>\n<blockquote>\n<p>Quoted\nand lazy.</p>\n</blockquote>\n</li>\n</ol>\n</blockquote>\n',
        id='li_lazy_in_nested_quote',
    ),
    pytest.param(
        '- foo\n  - bar\n    - baz\n      - boo\n',
        '<ul>\n<li>foo\n<ul>\n<li>bar\n<ul>\n<li>baz\n<ul>\n<li>boo</li>\n</ul>\n</li>\n</ul>\n</li>\n</ul>\n</li>\n</ul>\n',
        id='li_nesting_by_indent',
    ),
    pytest.param(
        '- foo\n - bar\n  - baz\n   - boo\n',
        '<ul>\n<li>foo</li>\n<li>bar</li>\n<li>baz</li>\n<li>boo</li>\n</ul>\n',
        id='li_not_enough_for_nesting',
    ),
    pytest.param(
        '10) foo\n    - bar\n',
        '<ol start="10">\n<li>foo\n<ul>\n<li>bar</li>\n</ul>\n</li>\n</ol>\n',
        id='li_wide_marker_nests_at_four',
    ),
    pytest.param(
        '10) foo\n   - bar\n',
        '<ol start="10">\n<li>foo</li>\n</ol>\n<ul>\n<li>bar</li>\n</ul>\n',
        id='li_wide_marker_three_not_nested',
    ),
    pytest.param(
        '10. a\n\n   b\n',
        '<ol start="10">\n<li>a</li>\n</ol>\n<p>b</p>\n',
        id='li_wide_marker_paragraph_needs_four',
    ),
    pytest.param(
        '10. a\n\n    b\n',
        '<ol start="10">\n<li>\n<p>a</p>\n<p>b</p>\n</li>\n</ol>\n',
        id='li_wide_marker_paragraph_four',
    ),
    pytest.param(
        '- - foo\n',
        '<ul>\n<li>\n<ul>\n<li>foo</li>\n</ul>\n</li>\n</ul>\n',
        id='li_list_in_list_same_line',
    ),
    pytest.param(
        '1. - 2. foo\n',
        '<ol>\n<li>\n<ul>\n<li>\n<ol start="2">\n<li>foo</li>\n</ol>\n</li>\n</ul>\n</li>\n</ol>\n',
        id='li_three_levels_same_line',
    ),
    pytest.param(
        '- # Foo\n- Bar\n  ---\n  baz\n',
        '<ul>\n<li>\n<h1>Foo</h1>\n</li>\n<li>\n<h2>Bar</h2>\nbaz</li>\n</ul>\n',
        id='li_headings_inside',
    ),
    pytest.param(
        '- foo\n- bar\n+ baz\n',
        '<ul>\n<li>foo</li>\n<li>bar</li>\n</ul>\n<ul>\n<li>baz</li>\n</ul>\n',
        id='li_change_bullet',
    ),
    pytest.param(
        '1. foo\n2. bar\n3) baz\n',
        '<ol>\n<li>foo</li>\n<li>bar</li>\n</ol>\n<ol start="3">\n<li>baz</li>\n</ol>\n',
        id='li_change_delimiter',
    ),
    pytest.param(
        '- a\n* b\n+ c\n',
        '<ul>\n<li>a</li>\n</ul>\n<ul>\n<li>b</li>\n</ul>\n<ul>\n<li>c</li>\n</ul>\n',
        id='li_three_bullets_three_lists',
    ),
    pytest.param(
        'Foo\n- bar\n- baz\n',
        '<p>Foo</p>\n<ul>\n<li>bar</li>\n<li>baz</li>\n</ul>\n',
        id='li_interrupts_paragraph',
    ),
    pytest.param(
        'I counted the chairs and got\n14.  Then I counted the tables.\n',
        '<p>I counted the chairs and got\n14.  Then I counted the tables.</p>\n',
        id='li_ordered_not_one_no_interrupt',
    ),
    pytest.param(
        'I counted the chairs and got\n1.  Then I counted the tables.\n',
        '<p>I counted the chairs and got</p>\n<ol>\n<li>Then I counted the tables.</li>\n</ol>\n',
        id='li_ordered_one_interrupts',
    ),
    pytest.param(
        '- a\n - b\n  - c\n   - d\n  - e\n - f\n- g\n',
        '<ul>\n<li>a</li>\n<li>b</li>\n<li>c</li>\n<li>d</li>\n<li>e</li>\n<li>f</li>\n<li>g</li>\n</ul>\n',
        id='li_siblings_varied_indent',
    ),
    pytest.param(
        '- a\n - b\n  - c\n   - d\n    - e\n',
        '<ul>\n<li>a</li>\n<li>b</li>\n<li>c</li>\n<li>d\n- e</li>\n</ul>\n',
        id='li_four_spaces_is_lazy_text',
    ),
    pytest.param(
        '1. a\n\n  2. b\n\n    3. c\n',
        '<ol>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n</ol>\n<pre><code>3. c\n</code></pre>\n',
        id='li_ordered_four_spaces_code',
    ),
    pytest.param(
        '9. a\n10. b\n11. c\n',
        '<ol start="9">\n<li>a</li>\n<li>b</li>\n<li>c</li>\n</ol>\n',
        id='li_start_number_kept',
    ),
    pytest.param(
        '1) a\n2) b\n',
        '<ol>\n<li>a</li>\n<li>b</li>\n</ol>\n',
        id='li_paren_delimiter',
    ),
    pytest.param(
        '- ```\n  code\n  ```\n- b\n',
        '<ul>\n<li>\n<pre><code>code\n</code></pre>\n</li>\n<li>b</li>\n</ul>\n',
        id='li_fence_inside',
    ),
    pytest.param(
        '- a\n  > b\n- c\n',
        '<ul>\n<li>a\n<blockquote>\n<p>b</p>\n</blockquote>\n</li>\n<li>c</li>\n</ul>\n',
        id='li_quote_inside',
    ),
    pytest.param(
        '- a\nb\n',
        '<ul>\n<li>a\nb</li>\n</ul>\n',
        id='li_lazy_continuation',
    ),
    pytest.param(
        '- a\n\nb\n',
        '<ul>\n<li>a</li>\n</ul>\n<p>b</p>\n',
        id='li_blank_ends_lazy',
    ),
    pytest.param(
        '1. a\n   b\nc\n',
        '<ol>\n<li>a\nb\nc</li>\n</ol>\n',
        id='li_ordered_lazy',
    ),
    pytest.param(
        '- a\n  b\n    c\n',
        '<ul>\n<li>a\nb\nc</li>\n</ul>\n',
        id='li_continuation_various_indent',
    ),
    pytest.param(
        '- a\\\n  b\n',
        '<ul>\n<li>a<br />\nb</li>\n</ul>\n',
        id='li_hard_break_inside',
    ),
    pytest.param(
        '- foo\n\n- bar\n\n\n- baz\n',
        '<ul>\n<li>\n<p>foo</p>\n</li>\n<li>\n<p>bar</p>\n</li>\n<li>\n<p>baz</p>\n</li>\n</ul>\n',
        id='loose_blank_between_items',
    ),
    pytest.param(
        '- foo\n  - bar\n    - baz\n\n\n      bim\n',
        '<ul>\n<li>foo\n<ul>\n<li>bar\n<ul>\n<li>\n<p>baz</p>\n<p>bim</p>\n</li>\n</ul>\n</li>\n</ul>\n</li>\n</ul>\n',
        id='loose_inner_only',
    ),
    pytest.param(
        '1. a\n\n  2. b\n\n   3. c\n',
        '<ol>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n<li>\n<p>c</p>\n</li>\n</ol>\n',
        id='loose_ordered_varied_indent',
    ),
    pytest.param(
        '- a\n- b\n\n- c\n',
        '<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n<li>\n<p>c</p>\n</li>\n</ul>\n',
        id='loose_one_blank',
    ),
    pytest.param(
        '* a\n*\n\n* c\n',
        '<ul>\n<li>\n<p>a</p>\n</li>\n<li></li>\n<li>\n<p>c</p>\n</li>\n</ul>\n',
        id='loose_with_empty_item',
    ),
    pytest.param(
        '- a\n- b\n\n  c\n- d\n',
        '<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n<p>c</p>\n</li>\n<li>\n<p>d</p>\n</li>\n</ul>\n',
        id='loose_blank_inside_item',
    ),
    pytest.param(
        '- a\n- b\n\n  [ref]: /url\n- d\n',
        '<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n<li>\n<p>d</p>\n</li>\n</ul>\n',
        id='loose_reference_definition',
    ),
    pytest.param(
        '- a\n- ```\n  b\n\n\n  ```\n- c\n',
        '<ul>\n<li>a</li>\n<li>\n<pre><code>b\n\n\n</code></pre>\n</li>\n<li>c</li>\n</ul>\n',
        id='tight_blank_in_fence',
    ),
    pytest.param(
        '- a\n  - b\n\n    c\n- d\n',
        '<ul>\n<li>a\n<ul>\n<li>\n<p>b</p>\n<p>c</p>\n</li>\n</ul>\n</li>\n<li>d</li>\n</ul>\n',
        id='tight_outer_loose_inner',
    ),
    pytest.param(
        '* a\n  > b\n  >\n* c\n',
        '<ul>\n<li>a\n<blockquote>\n<p>b</p>\n</blockquote>\n</li>\n<li>c</li>\n</ul>\n',
        id='tight_quote_with_blank',
    ),
    pytest.param(
        '- a\n  > b\n  ```\n  c\n  ```\n- d\n',
        '<ul>\n<li>a\n<blockquote>\n<p>b</p>\n</blockquote>\n<pre><code>c\n</code></pre>\n</li>\n<li>d</li>\n</ul>\n',
        id='tight_quote_and_fence',
    ),
    pytest.param(
        '- a\n',
        '<ul>\n<li>a</li>\n</ul>\n',
        id='tight_single',
    ),
    pytest.param(
        '- a\n  - b\n',
        '<ul>\n<li>a\n<ul>\n<li>b</li>\n</ul>\n</li>\n</ul>\n',
        id='tight_nested',
    ),
    pytest.param(
        '1. ```\n   foo\n   ```\n\n   bar\n',
        '<ol>\n<li>\n<pre><code>foo\n</code></pre>\n<p>bar</p>\n</li>\n</ol>\n',
        id='loose_fence_then_paragraph',
    ),
    pytest.param(
        '* foo\n  * bar\n\n  baz\n',
        '<ul>\n<li>\n<p>foo</p>\n<ul>\n<li>bar</li>\n</ul>\n<p>baz</p>\n</li>\n</ul>\n',
        id='loose_outer_blank_before_child',
    ),
    pytest.param(
        '- a\n  - b\n  - c\n\n- d\n  - e\n  - f\n',
        '<ul>\n<li>\n<p>a</p>\n<ul>\n<li>b</li>\n<li>c</li>\n</ul>\n</li>\n<li>\n<p>d</p>\n<ul>\n<li>e</li>\n<li>f</li>\n</ul>\n</li>\n</ul>\n',
        id='loose_outer_tight_inner',
    ),
    pytest.param(
        '- a\n- b\n\n\n',
        '<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n',
        id='tight_trailing_blank_lines',
    ),
    pytest.param(
        '- a\n- b\n\nparagraph\n',
        '<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<p>paragraph</p>\n',
        id='tight_then_paragraph',
    ),
    pytest.param(
        '2. a\n\n3. b\n',
        '<ol start="2">\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n</ol>\n',
        id='loose_ordered_start',
    ),
    pytest.param(
        '- a\n  - b\n\n- c\n',
        '<ul>\n<li>\n<p>a</p>\n<ul>\n<li>b</li>\n</ul>\n</li>\n<li>\n<p>c</p>\n</li>\n</ul>\n',
        id='loose_nested_blank_after_sublist',
    ),
    pytest.param(
        '- # a\n- b\n',
        '<ul>\n<li>\n<h1>a</h1>\n</li>\n<li>b</li>\n</ul>\n',
        id='tight_heading_item',
    ),
    pytest.param(
        '- foo\n\n- bar\n  baz\n',
        '<ul>\n<li>\n<p>foo</p>\n</li>\n<li>\n<p>bar\nbaz</p>\n</li>\n</ul>\n',
        id='loose_second_item_continuation',
    ),
    pytest.param(
        '1. a\n2. b\n\n10. c\n',
        '<ol>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n<li>\n<p>c</p>\n</li>\n</ol>\n',
        id='loose_start_kept_with_wide_number',
    ),
    pytest.param(
        '- a\n\n  b\n- c\n',
        '<ul>\n<li>\n<p>a</p>\n<p>b</p>\n</li>\n<li>\n<p>c</p>\n</li>\n</ul>\n',
        id='loose_two_paragraphs_first_item',
    ),
]


@pytest.mark.parametrize("src, expected", CASES)
def test_containers(src, expected):
    assert render(src) == expected
