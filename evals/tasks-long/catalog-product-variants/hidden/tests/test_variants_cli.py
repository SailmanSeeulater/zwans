import csv
import io


def setup_shop(cli) -> None:
    for argv in (
        ("warehouse", "add", "MAIN", "Main warehouse"),
        ("warehouse", "add", "WEST", "West store", "--priority", "1"),
        ("product", "add", "MUG-01", "Blue mug", "--price", "12.50", "--barcode", "5012345678900"),
        ("product", "add", "TEA-07", "Green tea", "--price", "4.50", "--tax-class", "reduced"),
        ("receive", "MUG-01", "8", "--warehouse", "MAIN"),
    ):
        code, out, err = cli(*argv)
        assert code == 0, err


def add_tee(cli) -> None:
    for argv in (
        ("category", "add", "clothing", "Clothing"),
        ("product", "add", "TEE-01", "Logo tee", "--price", "15.00", "--category", "clothing"),
        ("variant", "add", "TEE-01", "TEE-01-M", "--option", "size=M", "--option", "colour=red"),
        (
            "variant", "add", "TEE-01", "TEE-01-L", "--option", "size=L", "--option", "colour=red",
            "--price", "16.50", "--barcode", "8712345000097",
        ),
        ("variant", "remove", "TEE-01"),
        ("receive", "TEE-01-M", "5", "-w", "MAIN"),
        ("receive", "TEE-01-L", "2", "-w", "WEST"),
    ):
        code, out, err = cli(*argv)
        assert code == 0, (argv, err)


def test_variants_from_the_command_line(cli) -> None:
    setup_shop(cli)
    add_tee(cli)
    cli("cart", "new")
    assert cli("cart", "add", "C0001", "TEE-01-L", "2")[0] == 0
    assert cli("cart", "add", "C0001", "TEE-01-M")[0] == 0
    code, out, _ = cli("cart", "show", "C0001")
    assert "Logo tee (colour: red, size: L)" in out and "total 48.00 GBP" in out
    code, out, err = cli("checkout", "C0001", "--customer", "Ann")
    assert code == 0, err
    code, out, _ = cli("stock", "TEE-01-L")
    assert out.split()[-1] == "0"
    code, out, _ = cli("barcode", "8712345000097")
    assert out.strip() == "TEE-01-L"


def test_product_show_lists_the_variants(cli) -> None:
    setup_shop(cli)
    add_tee(cli)
    code, out, _ = cli("product", "show", "TEE-01")
    lines = out.splitlines()
    medium = next(line for line in lines if "TEE-01-M" in line)
    large = next(line for line in lines if "TEE-01-L" in line)
    assert "size" in medium and "15.00" in medium and "5" in medium.split("15.00", 1)[1]
    assert "size" in large and "16.50" in large and "2" in large.split("16.50", 1)[1]
    assert "M" in medium.replace("TEE-01-M", "") and "L" in large.replace("TEE-01-L", "")


def test_the_product_sku_is_not_sellable_from_the_command_line(cli) -> None:
    setup_shop(cli)
    add_tee(cli)
    code, out, err = cli("receive", "TEE-01", "1", "-w", "MAIN")
    assert code == 1 and err.startswith("error:")
    cli("cart", "new")
    assert cli("cart", "add", "C0001", "TEE-01")[0] == 1


def test_removing_a_variant_from_the_command_line(cli) -> None:
    setup_shop(cli)
    add_tee(cli)
    assert cli("variant", "remove", "TEE-01-M")[0] == 1  # it has stock
    cli("adjust", "TEE-01-M", "-5", "-w", "MAIN")
    assert cli("variant", "remove", "TEE-01-M")[0] == 0
    assert "TEE-01-M" not in cli("product", "show", "TEE-01")[1]


def test_reports_and_search_from_the_command_line(cli) -> None:
    setup_shop(cli)
    add_tee(cli)
    cli("cart", "new")
    cli("cart", "add", "C0001", "TEE-01-L", "1")
    cli("cart", "add", "C0001", "TEE-01-M", "2")
    cli("checkout", "C0001", "--customer", "Ann")
    code, out, _ = cli("report", "sales", "--csv")
    assert list(csv.reader(io.StringIO(out)))[1] == ["TEE-01", "Logo tee", "3", "46.50", "1"]
    code, out, _ = cli("report", "sales", "--by-variant", "--csv")
    assert list(csv.reader(io.StringIO(out)))[1:] == [
        ["TEE-01-M", "Logo tee (colour: red, size: M)", "2", "30.00", "1"],
        ["TEE-01-L", "Logo tee (colour: red, size: L)", "1", "16.50", "1"],
    ]
    code, out, _ = cli("search", "--option", "size=L")
    assert out.splitlines()[0].startswith("TEE-01") and "1 found" in out
    code, out, _ = cli("search", "--option", "size=S")
    assert "0 found" in out
    code, out, _ = cli("feed", "csv")
    ids = [row["id"] for row in csv.DictReader(io.StringIO(out))]
    assert ids == ["MUG-01", "TEA-07", "TEE-01-M", "TEE-01-L"]
