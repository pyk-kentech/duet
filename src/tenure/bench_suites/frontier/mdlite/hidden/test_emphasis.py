"""mdlite 숨은 테스트 — 강조: 측면 규칙, `_` 의 단어 안 규칙, 3의 배수 규칙, 중첩과 우선순위.

기대값은 CommonMark 0.31.2 참조 구현(commonmark.js 0.31.2)의 출력을 그대로 적은 것이다.
"""

import pytest

from mdlite import render

CASES = [
    pytest.param(
        '*foo bar*\n',
        '<p><em>foo bar</em></p>\n',
        id='em_star_basic',
    ),
    pytest.param(
        'a * foo bar*\n',
        '<p>a * foo bar*</p>\n',
        id='em_star_space_after',
    ),
    pytest.param(
        'a*"foo"*\n',
        '<p>a*&quot;foo&quot;*</p>\n',
        id='em_star_punct_after_alnum_before',
    ),
    pytest.param(
        'x * a *\n',
        '<p>x * a *</p>\n',
        id='em_star_spaces_both',
    ),
    pytest.param(
        'foo*bar*\n',
        '<p>foo<em>bar</em></p>\n',
        id='em_star_intraword',
    ),
    pytest.param(
        '5*6*78\n',
        '<p>5<em>6</em>78</p>\n',
        id='em_star_digits',
    ),
    pytest.param(
        '_foo bar_\n',
        '<p><em>foo bar</em></p>\n',
        id='em_under_basic',
    ),
    pytest.param(
        '_ foo bar_\n',
        '<p>_ foo bar_</p>\n',
        id='em_under_space_after',
    ),
    pytest.param(
        'a_"foo"_\n',
        '<p>a_&quot;foo&quot;_</p>\n',
        id='em_under_punct',
    ),
    pytest.param(
        'foo_bar_\n',
        '<p>foo_bar_</p>\n',
        id='em_under_intraword',
    ),
    pytest.param(
        '5_6_78\n',
        '<p>5_6_78</p>\n',
        id='em_under_digits',
    ),
    pytest.param(
        'слово_другое_\n',
        '<p>слово_другое_</p>\n',
        id='em_under_cyrillic',
    ),
    pytest.param(
        'aa_"bb"_cc\n',
        '<p>aa_&quot;bb&quot;_cc</p>\n',
        id='em_under_both_flanking',
    ),
    pytest.param(
        'foo-_(bar)_\n',
        '<p>foo-<em>(bar)</em></p>\n',
        id='em_under_after_punct',
    ),
    pytest.param(
        '_foo*\n',
        '<p>_foo*</p>\n',
        id='em_mismatched_chars',
    ),
    pytest.param(
        '*foo bar *\n',
        '<p>*foo bar *</p>\n',
        id='em_closer_space_before',
    ),
    pytest.param(
        '*(*foo)\n',
        '<p>*(*foo)</p>\n',
        id='em_closer_punct_rule',
    ),
    pytest.param(
        '*(*foo*)*\n',
        '<p><em>(<em>foo</em>)</em></p>\n',
        id='em_nested_punct',
    ),
    pytest.param(
        '*foo*bar\n',
        '<p><em>foo</em>bar</p>\n',
        id='em_star_close_intraword',
    ),
    pytest.param(
        '_foo bar _\n',
        '<p>_foo bar _</p>\n',
        id='em_under_close_space_before',
    ),
    pytest.param(
        '_(_foo)\n',
        '<p>_(_foo)</p>\n',
        id='em_under_punct_open',
    ),
    pytest.param(
        '_(_foo_)_\n',
        '<p><em>(<em>foo</em>)</em></p>\n',
        id='em_under_nested_punct',
    ),
    pytest.param(
        '_foo_bar\n',
        '<p>_foo_bar</p>\n',
        id='em_under_close_intraword',
    ),
    pytest.param(
        '_foo_bar_baz_\n',
        '<p><em>foo_bar_baz</em></p>\n',
        id='em_under_intraword_inside',
    ),
    pytest.param(
        '_(bar)_.\n',
        '<p><em>(bar)</em>.</p>\n',
        id='em_under_then_period',
    ),
    pytest.param(
        '**foo bar**\n',
        '<p><strong>foo bar</strong></p>\n',
        id='strong_star_basic',
    ),
    pytest.param(
        '** foo bar**\n',
        '<p>** foo bar**</p>\n',
        id='strong_star_space_after',
    ),
    pytest.param(
        'a**"foo"**\n',
        '<p>a**&quot;foo&quot;**</p>\n',
        id='strong_star_punct',
    ),
    pytest.param(
        'foo**bar**\n',
        '<p>foo<strong>bar</strong></p>\n',
        id='strong_star_intraword',
    ),
    pytest.param(
        '__foo bar__\n',
        '<p><strong>foo bar</strong></p>\n',
        id='strong_under_basic',
    ),
    pytest.param(
        'foo__bar__\n',
        '<p>foo__bar__</p>\n',
        id='strong_under_intraword',
    ),
    pytest.param(
        '__red, __green__, blue__\n',
        '<p><strong>red, <strong>green</strong>, blue</strong></p>\n',
        id='strong_under_nested',
    ),
    pytest.param(
        'foo-__(bar)__\n',
        '<p>foo-<strong>(bar)</strong></p>\n',
        id='strong_under_after_punct',
    ),
    pytest.param(
        '**say "*hi*" now**\n',
        '<p><strong>say &quot;<em>hi</em>&quot; now</strong></p>\n',
        id='strong_with_quotes_em',
    ),
    pytest.param(
        '__a__b\n',
        '<p>__a__b</p>\n',
        id='strong_under_close_alnum',
    ),
    pytest.param(
        '**a**b\n',
        '<p><strong>a</strong>b</p>\n',
        id='strong_star_close_alnum',
    ),
    pytest.param(
        '*foo**bar**baz*\n',
        '<p><em>foo<strong>bar</strong>baz</em></p>\n',
        id='rule3_em_strong_em',
    ),
    pytest.param(
        '*foo**bar*\n',
        '<p><em>foo**bar</em></p>\n',
        id='rule3_em_with_double_inside',
    ),
    pytest.param(
        '***foo** bar*\n',
        '<p><em><strong>foo</strong> bar</em></p>\n',
        id='rule3_strong_first',
    ),
    pytest.param(
        '*foo **bar***\n',
        '<p><em>foo <strong>bar</strong></em></p>\n',
        id='rule3_strong_last',
    ),
    pytest.param(
        'foo***bar***baz\n',
        '<p>foo<em><strong>bar</strong></em>baz</p>\n',
        id='rule3_intraword_triple',
    ),
    pytest.param(
        'x******y*********z\n',
        '<p>x<strong><strong><strong>y</strong></strong></strong>***z</p>\n',
        id='rule3_multiples_of_three',
    ),
    pytest.param(
        '*a **b *c* d** e*\n',
        '<p><em>a <strong>b <em>c</em> d</strong> e</em></p>\n',
        id='nested_deep',
    ),
    pytest.param(
        '** is not empty\n',
        '<p>** is not empty</p>\n',
        id='empty_emphasis_literal',
    ),
    pytest.param(
        '**** nor this\n',
        '<p>**** nor this</p>\n',
        id='empty_strong_literal',
    ),
    pytest.param(
        '**foo*\n',
        '<p>*<em>foo</em></p>\n',
        id='unbalanced_open_two',
    ),
    pytest.param(
        '*foo**\n',
        '<p><em>foo</em>*</p>\n',
        id='unbalanced_close_two',
    ),
    pytest.param(
        '***foo**\n',
        '<p>*<strong>foo</strong></p>\n',
        id='unbalanced_open_three',
    ),
    pytest.param(
        '****foo*\n',
        '<p>***<em>foo</em></p>\n',
        id='unbalanced_open_four',
    ),
    pytest.param(
        '**foo***\n',
        '<p><strong>foo</strong>*</p>\n',
        id='unbalanced_close_three',
    ),
    pytest.param(
        '*foo****\n',
        '<p><em>foo</em>***</p>\n',
        id='unbalanced_close_four',
    ),
    pytest.param(
        '*a **b** c*\n',
        '<p><em>a <strong>b</strong> c</em></p>\n',
        id='em_around_strong',
    ),
    pytest.param(
        '**a*b*c**\n',
        '<p><strong>a<em>b</em>c</strong></p>\n',
        id='strong_around_em_intraword',
    ),
    pytest.param(
        '*"a"*\n',
        '<p><em>&quot;a&quot;</em></p>\n',
        id='em_quotes_inside',
    ),
    pytest.param(
        'a*"b"*\n',
        '<p>a*&quot;b&quot;*</p>\n',
        id='em_quotes_after_letter',
    ),
    pytest.param(
        'snake_case_words and __init__ and _x_\n',
        '<p>snake_case_words and <strong>init</strong> and <em>x</em></p>\n',
        id='snake_case_and_dunder',
    ),
    pytest.param(
        '*foo _bar* baz_\n',
        '<p><em>foo _bar</em> baz_</p>\n',
        id='em_overlap_first_wins',
    ),
    pytest.param(
        '*foo [bar*](/url)\n',
        '<p>*foo <a href="/url">bar*</a></p>\n',
        id='em_link_precedence_star',
    ),
    pytest.param(
        '_foo [bar_](/url)\n',
        '<p>_foo <a href="/url">bar_</a></p>\n',
        id='em_link_precedence_under',
    ),
    pytest.param(
        '*a `*`*\n',
        '<p><em>a <code>*</code></em></p>\n',
        id='em_code_inside',
    ),
    pytest.param(
        '_a `_`_\n',
        '<p><em>a <code>_</code></em></p>\n',
        id='em_under_code_inside',
    ),
    pytest.param(
        '**a<http://foo.bar/?q=**>\n',
        '<p>**a<a href="http://foo.bar/?q=**">http://foo.bar/?q=**</a></p>\n',
        id='strong_autolink_precedence',
    ),
    pytest.param(
        '**foo*bar*baz**\n',
        '<p><strong>foo<em>bar</em>baz</strong></p>\n',
        id='strong_em_inside_under',
    ),
    pytest.param(
        '***strong emph***\n',
        '<p><em><strong>strong emph</strong></em></p>\n',
        id='triple_strong_em',
    ),
    pytest.param(
        '*foo\nbar*\n',
        '<p><em>foo\nbar</em></p>\n',
        id='em_across_lines',
    ),
    pytest.param(
        '__foo_ bar_\n',
        '<p><em><em>foo</em> bar</em></p>\n',
        id='em_under_double_then_single',
    ),
    pytest.param(
        '*(**foo**)*\n',
        '<p><em>(<strong>foo</strong>)</em></p>\n',
        id='em_paren_strong',
    ),
    pytest.param(
        '_____foo_____\n',
        '<p><em><strong><strong>foo</strong></strong></em></p>\n',
        id='five_underscores',
    ),
    pytest.param(
        '*foo _bar_ baz*\n',
        '<p><em>foo <em>bar</em> baz</em></p>\n',
        id='em_mixed_chars_nested',
    ),
    pytest.param(
        'a ** b **\n',
        '<p>a ** b **</p>\n',
        id='strong_spaces_both_sides',
    ),
    pytest.param(
        '*$*one.\n\n*£*two.\n\n*€*three.\n',
        '<p>*$*one.</p>\n<p>*£*two.</p>\n<p>*€*three.</p>\n',
        id='unicode_symbol_flanking',
    ),
    pytest.param(
        '*«a»*\n',
        '<p><em>«a»</em></p>\n',
        id='unicode_punct_guillemets',
    ),
    pytest.param(
        'a*«b»*\n',
        '<p>a*«b»*</p>\n',
        id='unicode_punct_after_letter',
    ),
    pytest.param(
        'x *\xa0a*\n',
        '<p>x *\xa0a*</p>\n',
        id='unicode_nbsp_not_flanking',
    ),
    pytest.param(
        '*a**b*\n',
        '<p><em>a**b</em></p>\n',
        id='rule3_both_can_open_close',
    ),
    pytest.param(
        '**a***b*\n',
        '<p><strong>a</strong><em>b</em></p>\n',
        id='rule3_triple_closer',
    ),
    pytest.param(
        '_foo_ _bar_\n',
        '<p><em>foo</em> <em>bar</em></p>\n',
        id='em_two_separate',
    ),
    pytest.param(
        '*foo_bar_baz*\n',
        '<p><em>foo_bar_baz</em></p>\n',
        id='em_under_inside_star_word',
    ),
    pytest.param(
        '_foo __bar__ baz_\n',
        '<p><em>foo <strong>bar</strong> baz</em></p>\n',
        id='strong_inside_em_under',
    ),
    pytest.param(
        '*a* b* c*\n',
        '<p><em>a</em> b* c*</p>\n',
        id='em_multiple_closers',
    ),
    pytest.param(
        'a **b\nc** d\n',
        '<p>a <strong>b\nc</strong> d</p>\n',
        id='strong_across_lines',
    ),
    pytest.param(
        '*foo* *bar\n',
        '<p><em>foo</em> *bar</p>\n',
        id='em_then_unclosed',
    ),
]


@pytest.mark.parametrize("src, expected", CASES)
def test_emphasis(src, expected):
    assert render(src) == expected
