from pathlib import Path

import pytest
import strata


def files(tmp_path: Path, **texts: str) -> Path:
    """Write each keyword as a file (`a_st` -> `a.st`, `sub__b_st` -> `sub/b.st`); return main.st."""
    for key, text in texts.items():
        name = key.replace("__", "/").replace("_st", ".st")
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path / "main.st"


def load(tmp_path: Path, text: str, env: dict | None = None, **others: str) -> dict:
    return strata.load(files(tmp_path, main_st=text, **others), env=env or {})


def fails(tmp_path: Path, text: str, env: dict | None = None, **others: str) -> strata.ConfigError:
    with pytest.raises(strata.ConfigError) as caught:
        load(tmp_path, text, env, **others)
    return caught.value


def same(a: object, b: Path) -> bool:
    return a is not None and Path(a).resolve() == b.resolve()


# -- bare values ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("0", 0),
        ("-0", 0),
        ("-12", -12),
        ("1_000_000", 1000000),
        ("007", "007"),
        ("-05", "-05"),
        ("1_", "1_"),
        ("_1", "_1"),
        ("1__0", "1__0"),
        ("+5", "+5"),
        ("1.5", "1.5"),
        ("true", True),
        ("false", False),
        ("True", "True"),
        ("FALSE", "FALSE"),
        ("", ""),
        ("hello world", "hello world"),
        ("it's", "it's"),
    ],
)
def test_bare_value_types(tmp_path: Path, text: str, value: object) -> None:
    result = load(tmp_path, f"v = {text}\n")["v"]
    assert result == value
    assert type(result) is type(value)


# -- quoted strings ---------------------------------------------------------------------------


def test_double_quoted_values_are_always_strings(tmp_path: Path) -> None:
    config = load(tmp_path, 'a = "42"\nb = "true"\nc = ""\n')
    assert config == {"a": "42", "b": "true", "c": ""}


def test_double_quoted_escapes(tmp_path: Path) -> None:
    config = load(tmp_path, r'v = "a\"b\\c\nd\te"' + "\n")
    assert config["v"] == 'a"b\\c\nd\te'


def test_escaped_dollar_never_starts_a_reference(tmp_path: Path) -> None:
    config = load(tmp_path, r'a = "cost: \$5"' + "\n" + r'b = "\${x}"' + "\n")
    assert config == {"a": "cost: $5", "b": "${x}"}


def test_unknown_escape_is_an_error(tmp_path: Path) -> None:
    fails(tmp_path, r'v = "a\qb"' + "\n")


def test_single_quotes_are_literal(tmp_path: Path) -> None:
    config = load(tmp_path, r"v = '${nothing} \n $$ # not a comment'" + "\n")
    assert config["v"] == r"${nothing} \n $$ # not a comment"


def test_text_after_a_closing_quote_is_an_error(tmp_path: Path) -> None:
    fails(tmp_path, 'v = "a" b\n')


# -- trailing comments ------------------------------------------------------------------------


def test_trailing_comment_after_whitespace(tmp_path: Path) -> None:
    config = load(tmp_path, "a = hello # greeting\nb = x\t# tab before\n")
    assert config == {"a": "hello", "b": "x"}


def test_hash_without_whitespace_is_literal(tmp_path: Path) -> None:
    config = load(tmp_path, "color = a#b\nurl = http://x/#frag\n")
    assert config == {"color": "a#b", "url": "http://x/#frag"}


def test_hash_inside_quotes_is_literal(tmp_path: Path) -> None:
    config = load(tmp_path, "a = \"x # y\" # real comment\nb = 'p # q'\n")
    assert config == {"a": "x # y", "b": "p # q"}


def test_hash_right_after_a_closing_quote_is_an_error(tmp_path: Path) -> None:
    fails(tmp_path, 'v = "a"#b\n')


def test_comments_after_headers_lists_and_directives(tmp_path: Path) -> None:
    text = "[srv] # main\nv = [a#b, c] # list\nw = 1\n@unset w # gone\n"
    assert load(tmp_path, text) == {"srv": {"v": ["a#b", "c"]}}


def test_semicolon_comment_lines(tmp_path: Path) -> None:
    assert load(tmp_path, "; a comment\n  # another\nv = 1\n") == {"v": 1}


# -- lists ------------------------------------------------------------------------------------


def test_list_items(tmp_path: Path) -> None:
    config = load(tmp_path, """v = [a, "b, c", 'd]e', 3, true, 007]\n""")
    assert config["v"] == ["a", "b, c", "d]e", 3, True, "007"]


def test_trailing_comma_and_empty_list(tmp_path: Path) -> None:
    config = load(tmp_path, "a = [x, y,]\nb = []\nc = [ ]\n")
    assert config == {"a": ["x", "y"], "b": [], "c": []}


@pytest.mark.parametrize("text", ["[a,,b]", "[,]", "[a, [b]]", "[a, b", "[a] x", "[a, b,,]"])
def test_bad_lists(tmp_path: Path, text: str) -> None:
    fails(tmp_path, f"v = {text}\n")


# -- assignments ------------------------------------------------------------------------------


def test_whitespace_around_operators_is_optional(tmp_path: Path) -> None:
    config = load(tmp_path, "a=1\nb+=x\nc?=y\n")
    assert config == {"a": 1, "b": ["x"], "c": "y"}


def test_append_to_unset_target(tmp_path: Path) -> None:
    config = load(tmp_path, "a += x\nb += [x, y]\n")
    assert config == {"a": ["x"], "b": ["x", "y"]}


def test_append_to_a_list(tmp_path: Path) -> None:
    config = load(tmp_path, "a = [x]\na += y\na += [z, w]\na += 3\n")
    assert config["a"] == ["x", "y", "z", "w", 3]


def test_append_to_a_scalar_is_an_error(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = x\n\na += y\n")
    assert error.line == 3


def test_append_a_reference_to_a_string(tmp_path: Path) -> None:
    config = load(tmp_path, "name = web\ntags += ${name}\ntags += svc-${name}\n")
    assert config["tags"] == ["web", "svc-web"]


def test_set_if_unset(tmp_path: Path) -> None:
    config = load(tmp_path, "a = 1\na ?= 2\nb ?= 3\nb = 4\nc ?= 5\nc ?= 6\n")
    assert config == {"a": 1, "b": 4, "c": 5}


def test_set_if_unset_after_unset(tmp_path: Path) -> None:
    assert load(tmp_path, "a = 1\n@unset a\na ?= 2\n") == {"a": 2}


def test_dotted_targets_are_relative_to_the_section(tmp_path: Path) -> None:
    config = load(tmp_path, "[server]\ntls.port = 443\ntls.on = true\n")
    assert config == {"server": {"tls": {"port": 443, "on": True}}}


def test_a_value_cannot_become_a_table(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = 1\na.b = 2\n")
    assert error.line == 2


def test_a_value_cannot_be_a_section(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = 1\n[a.b]\n")
    assert error.line == 2


def test_a_table_cannot_become_a_value(tmp_path: Path) -> None:
    error = fails(tmp_path, "[server]\nport = 1\n[]\nserver = 2\n")
    assert error.line == 4


@pytest.mark.parametrize("line", ["2abc = 1", "a..b = 1", "a. b = 1", "[a b]", "[a.]", "= 1", "a"])
def test_bad_names(tmp_path: Path, line: str) -> None:
    error = fails(tmp_path, f"ok = 1\n{line}\n")
    assert error.line == 2


# -- sections ---------------------------------------------------------------------------------


def test_sections(tmp_path: Path) -> None:
    text = "top = 1\n[ server.tls ]\non = true\n[empty]\n[]\nback = 2\n[server]\nport = 80\n"
    assert load(tmp_path, text) == {
        "top": 1,
        "server": {"tls": {"on": True}, "port": 80},
        "empty": {},
        "back": 2,
    }


# -- interpolation ----------------------------------------------------------------------------


def test_references_see_final_values(tmp_path: Path) -> None:
    text = "[paths]\nroot = /srv\nlogs = ${.root}/logs\n[paths]\nroot = /opt\n"
    assert load(tmp_path, text)["paths"] == {"root": "/opt", "logs": "/opt/logs"}


def test_relative_reference_is_relative_to_the_current_section(tmp_path: Path) -> None:
    text = "[server]\nhost = h1\ntls.host = h2\ntls.url = ${.host}\n"
    assert load(tmp_path, text)["server"]["tls"]["url"] == "h1"


def test_whole_reference_keeps_the_type(tmp_path: Path) -> None:
    text = "[d]\nport = 8080\non = true\ntags = [a, b]\n[s]\nport = ${d.port}\non = ${d.on}\ntags = ${d.tags}\n"
    assert load(tmp_path, text)["s"] == {"port": 8080, "on": True, "tags": ["a", "b"]}


def test_whole_reference_copies_a_list(tmp_path: Path) -> None:
    config = load(tmp_path, "a = [x]\nb = ${a}\n")
    config["b"].append("y")
    assert config["a"] == ["x"]


def test_whole_reference_to_a_table(tmp_path: Path) -> None:
    text = "[base]\nport = 1\nurl = u${.port}\n[]\ncopy = ${base}\n"
    assert load(tmp_path, text)["copy"] == {"port": 1, "url": "u1"}


def test_quoted_reference_is_a_string(tmp_path: Path) -> None:
    config = load(tmp_path, 'port = 8080\nv = "${port}"\n')
    assert config["v"] == "8080"


def test_splicing_into_text(tmp_path: Path) -> None:
    text = "port = 8080\non = false\nname = web\nv = ${name}:${port}:${on}\n"
    assert load(tmp_path, text)["v"] == "web:8080:false"


def test_splicing_a_list_is_an_error(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = [x]\n\nb = see ${a}\n")
    assert error.line == 3


def test_splicing_a_table_is_an_error(tmp_path: Path) -> None:
    fails(tmp_path, "[t]\nx = 1\n[]\nb = see ${t}\n")


def test_references_resolve_through_chains(tmp_path: Path) -> None:
    text = "a = ${b}/a\nb = ${c}/b\nc = root\n"
    assert load(tmp_path, text)["a"] == "root/b/a"


def test_reference_cycle(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = ${b}\nb = x${c}\nc = ${a}\n")
    assert "cycle" in str(error)


def test_self_reference_is_a_cycle(tmp_path: Path) -> None:
    assert "cycle" in str(fails(tmp_path, "[s]\na = ${.a}x\n"))


def test_missing_reference_points_at_its_assignment(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = 1\n\nb = ${nope}\n")
    assert error.line == 3
    assert same(error.file, tmp_path / "main.st")


def test_error_in_a_referenced_value_points_at_that_value(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = x-${b}\nb = ${missing}\n")
    assert error.line == 2


def test_dollar_rules(tmp_path: Path) -> None:
    text = 'a = $$5\nb = 5$\nc = $x\nd = "$${y}"\ne = a$$$$b\n'
    assert load(tmp_path, text) == {"a": "$5", "b": "5$", "c": "$x", "d": "${y}", "e": "a$$b"}


def test_unterminated_reference(tmp_path: Path) -> None:
    error = fails(tmp_path, "a = 1\nb = ${a\n")
    assert error.line == 2


def test_environment_references(tmp_path: Path) -> None:
    text = "a = ${env:HOME_DIR}/x\nb = ${env:NOPE:-fallback}\nc = ${env:NOPE:-}\nd = ${env:HOME_DIR:-other}\n"
    config = load(tmp_path, text, env={"HOME_DIR": "/home/me"})
    assert config == {"a": "/home/me/x", "b": "fallback", "c": "", "d": "/home/me"}


def test_environment_value_is_a_string(tmp_path: Path) -> None:
    assert load(tmp_path, "n = ${env:N}\n", env={"N": "5"})["n"] == "5"


def test_missing_environment_variable(tmp_path: Path) -> None:
    error = fails(tmp_path, "\na = ${env:NOPE}\n")
    assert error.line == 2


def test_os_environ_is_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRATA_TEST_VALUE", "from-os")
    path = files(tmp_path, main_st="v = ${env:STRATA_TEST_VALUE}\n")
    assert strata.load(path)["v"] == "from-os"


def test_references_in_list_items(tmp_path: Path) -> None:
    text = "port = 80\nname = web\nv = [${port}, x-${name}, \"${port}\", '${port}']\n"
    assert load(tmp_path, text)["v"] == [80, "x-web", "80", "${port}"]


def test_list_item_cannot_be_a_list(tmp_path: Path) -> None:
    fails(tmp_path, "a = [x]\nb = [${a}]\n")


# -- includes ---------------------------------------------------------------------------------


def test_include_is_read_in_place(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        'a = 1\nb = 1\n@include "inc.st"\nb = 3\n',
        inc_st="a = 2\nb = 2\nc = 2\n",
    )
    assert config == {"a": 2, "b": 3, "c": 2}


def test_include_paths_are_relative_to_the_including_file(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        '@include "conf/one.st"\n',
        conf__one_st='one = 1\n@include "two.st"\n',
        conf__two_st="two = 2\n",
        two_st="wrong = 1\n",
    )
    assert config == {"one": 1, "two": 2}


def test_included_file_starts_in_the_current_section(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        '[storage]\n@include "inc.st"\n',
        inc_st="driver = s3\n[retention]\ndays = 30\n[]\nregion = eu\n",
    )
    assert config == {"storage": {"driver": "s3", "retention": {"days": 30}, "region": "eu"}}


def test_section_is_restored_after_an_include(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        '[app]\n@include "inc.st"\nname = web\n',
        inc_st="[db]\nhost = h\n",
    )
    assert config == {"app": {"db": {"host": "h"}, "name": "web"}}


def test_relative_references_in_an_included_file(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        '[svc]\n@include "inc.st"\n',
        inc_st="host = h\n[tls]\nhost = t\nurl = https://${.host}/\n[]\nurl = http://${.host}/\n",
    )
    assert config["svc"]["tls"]["url"] == "https://t/"
    assert config["svc"]["url"] == "http://h/"


def test_absolute_references_in_an_included_file_start_at_the_root(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        'host = top\n[svc]\nhost = inner\n@include "inc.st"\n',
        inc_st="url = ${host}\n",
    )
    assert config["svc"]["url"] == "top"


def test_including_the_same_file_twice(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        '[a]\n@include "common.st"\n[b]\n@include "common.st"\n',
        common_st="x += 1\n",
    )
    assert config == {"a": {"x": [1]}, "b": {"x": [1]}}


def test_optional_include_of_a_missing_file(tmp_path: Path) -> None:
    assert load(tmp_path, 'a = 1\n@include? "nope.st"\nb = 2\n') == {"a": 1, "b": 2}


def test_optional_include_still_reports_errors(tmp_path: Path) -> None:
    fails(tmp_path, '@include? "bad.st"\n', bad_st="this is bad\n")


def test_missing_include_points_at_the_include_line(tmp_path: Path) -> None:
    error = fails(tmp_path, 'a = 1\n@include "nope.st"\n')
    assert error.line == 2
    assert same(error.file, tmp_path / "main.st")


def test_include_cycle(tmp_path: Path) -> None:
    error = fails(tmp_path, '@include "a.st"\n', a_st='@include "b.st"\n', b_st='@include "a.st"\n')
    assert "cycle" in str(error)


def test_file_including_itself(tmp_path: Path) -> None:
    assert "cycle" in str(fails(tmp_path, 'a = 1\n@include "main.st"\n'))


def test_include_needs_a_double_quoted_name(tmp_path: Path) -> None:
    fails(tmp_path, "@include inc.st\n", inc_st="a = 1\n")


def test_syntax_error_in_an_included_file(tmp_path: Path) -> None:
    error = fails(
        tmp_path, 'a = 1\n@include "sub/inc.st"\n', sub__inc_st="ok = 1\n\n# fine\n?? = 2\n"
    )
    assert same(error.file, tmp_path / "sub" / "inc.st")
    assert error.line == 4


def test_reference_error_in_an_included_file(tmp_path: Path) -> None:
    error = fails(tmp_path, '[s]\n@include "inc.st"\n', inc_st="a = 1\nb = ${.missing}\n")
    assert same(error.file, tmp_path / "inc.st")
    assert error.line == 2


# -- @unset and other directives --------------------------------------------------------------


def test_unset(tmp_path: Path) -> None:
    text = "[s]\na = 1\nb = 2\n[s.t]\nx = 1\n[s]\n@unset a\n@unset t\n@unset nothing\n"
    assert load(tmp_path, text) == {"s": {"b": 2}}


def test_unset_value_cannot_be_referenced(tmp_path: Path) -> None:
    fails(tmp_path, "a = 1\nb = ${a}\n@unset a\n")


def test_unknown_directive(tmp_path: Path) -> None:
    error = fails(tmp_path, 'a = 1\n@import "x.st"\n')
    assert error.line == 2


# -- loading ----------------------------------------------------------------------------------


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(strata.ConfigError) as caught:
        strata.load(tmp_path / "nope.st")
    assert caught.value.line is None


def test_config_error_is_an_exception() -> None:
    assert issubclass(strata.ConfigError, Exception)
