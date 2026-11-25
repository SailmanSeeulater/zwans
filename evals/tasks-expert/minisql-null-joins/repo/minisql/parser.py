"""A recursive-descent parser for the SQL minisql understands.

Operator precedence follows SQLite, loosest first: OR, AND, NOT, the equality group
(= == != <> IS IN BETWEEN), the ordering comparisons (< <= > >=), + -, * /, ||, unary -.
"""

from minisql.errors import SQLError
from minisql.nodes import (
    Between,
    Binary,
    Call,
    Case,
    Column,
    CreateTable,
    Delete,
    DropTable,
    Explain,
    Expr,
    InList,
    Insert,
    IsNull,
    JoinClause,
    Literal,
    OrderItem,
    Select,
    SelectItem,
    Statement,
    TableRef,
    Unary,
    Update,
)
from minisql.tokenizer import Token, tokenize

COLUMN_TYPES = ("integer", "int", "text")


def parse(text: str) -> list[Statement]:
    """Every statement in `text`, separated by semicolons."""
    return Parser(tokenize(text)).statements()


def parse_one(text: str) -> Statement:
    statements = parse(text)
    if len(statements) != 1:
        raise SQLError(f"expected one statement, found {len(statements)}")
    return statements[0]


def parse_expression(text: str) -> Expr:
    parser = Parser(tokenize(text))
    expr = parser.expression()
    parser.expect_end()
    return expr


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    # -- token helpers

    @property
    def token(self) -> Token:
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        token = self.token
        if token.kind != "end":
            self.pos += 1
        return token

    def accept_keyword(self, *words: str) -> bool:
        if self.token.is_keyword(*words):
            self.advance()
            return True
        return False

    def accept_op(self, *ops: str) -> bool:
        if self.token.is_op(*ops):
            self.advance()
            return True
        return False

    def expect_keyword(self, word: str) -> None:
        if not self.accept_keyword(word):
            self.fail(f"expected {word}")

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            self.fail(f"expected '{op}'")

    def expect_name(self) -> str:
        if self.token.kind != "name":
            self.fail("expected a name")
        return str(self.advance().value)

    def expect_end(self) -> None:
        if self.token.kind != "end":
            self.fail("expected end of input")

    def fail(self, message: str):
        token = self.token
        raise SQLError(f"{message} near {token.describe()} (position {token.position})")

    # -- statements

    def statements(self) -> list[Statement]:
        found: list[Statement] = []
        while True:
            while self.accept_op(";"):
                pass
            if self.token.kind == "end":
                return found
            found.append(self.statement())
            if self.token.kind != "end" and not self.token.is_op(";"):
                self.fail("expected ';'")

    def statement(self) -> Statement:
        token = self.token
        if token.is_keyword("SELECT"):
            return self.select()
        if token.is_keyword("CREATE"):
            return self.create_table()
        if token.is_keyword("DROP"):
            return self.drop_table()
        if token.is_keyword("INSERT"):
            return self.insert()
        if token.is_keyword("DELETE"):
            return self.delete()
        if token.is_keyword("UPDATE"):
            return self.update()
        if token.is_keyword("EXPLAIN"):
            self.advance()
            if not self.token.is_keyword("SELECT"):
                self.fail("EXPLAIN works on SELECT only")
            return Explain(self.select())
        self.fail("expected a statement")

    def create_table(self) -> CreateTable:
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        if_not_exists = False
        if self.accept_keyword("IF"):
            self.expect_keyword("NOT")
            self.expect_keyword("EXISTS")
            if_not_exists = True
        name = self.expect_name()
        self.expect_op("(")
        columns: list[tuple[str, str]] = []
        while True:
            column = self.expect_name()
            kind = self.expect_name()
            if kind not in COLUMN_TYPES:
                raise SQLError(f"unknown column type {kind!r} (use INTEGER or TEXT)")
            columns.append((column, "text" if kind == "text" else "integer"))
            if not self.accept_op(","):
                break
        self.expect_op(")")
        return CreateTable(name, columns, if_not_exists)

    def drop_table(self) -> DropTable:
        self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        if_exists = False
        if self.accept_keyword("IF"):
            self.expect_keyword("EXISTS")
            if_exists = True
        return DropTable(self.expect_name(), if_exists)

    def insert(self) -> Insert:
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.expect_name()
        columns = None
        if self.accept_op("("):
            columns = [self.expect_name()]
            while self.accept_op(","):
                columns.append(self.expect_name())
            self.expect_op(")")
        self.expect_keyword("VALUES")
        rows = [self.value_row()]
        while self.accept_op(","):
            rows.append(self.value_row())
        return Insert(table, columns, rows)

    def value_row(self) -> list[Expr]:
        self.expect_op("(")
        row = [self.expression()]
        while self.accept_op(","):
            row.append(self.expression())
        self.expect_op(")")
        return row

    def delete(self) -> Delete:
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.expect_name()
        where = self.expression() if self.accept_keyword("WHERE") else None
        return Delete(table, where)

    def update(self) -> Update:
        self.expect_keyword("UPDATE")
        table = self.expect_name()
        self.expect_keyword("SET")
        assignments = []
        while True:
            column = self.expect_name()
            self.expect_op("=")
            assignments.append((column, self.expression()))
            if not self.accept_op(","):
                break
        where = self.expression() if self.accept_keyword("WHERE") else None
        return Update(table, assignments, where)

    def select(self) -> Select:
        self.expect_keyword("SELECT")
        distinct = self.accept_keyword("DISTINCT")
        if not distinct:
            self.accept_keyword("ALL")
        items = [self.select_item()]
        while self.accept_op(","):
            items.append(self.select_item())
        select = Select(items, distinct=distinct)
        if self.accept_keyword("FROM"):
            select.source = self.table_ref()
            while True:
                join = self.join_clause()
                if join is None:
                    break
                select.joins.append(join)
        if self.accept_keyword("WHERE"):
            select.where = self.expression()
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            select.group_by = [self.expression()]
            while self.accept_op(","):
                select.group_by.append(self.expression())
        if self.accept_keyword("HAVING"):
            select.having = self.expression()
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            select.order_by = [self.order_item()]
            while self.accept_op(","):
                select.order_by.append(self.order_item())
        if self.accept_keyword("LIMIT"):
            select.limit = self.expression()
            if self.accept_keyword("OFFSET"):
                select.offset = self.expression()
            elif self.accept_op(","):
                # LIMIT skip, count
                select.offset, select.limit = select.limit, self.expression()
        return select

    def select_item(self) -> SelectItem:
        if self.accept_op("*"):
            return SelectItem(None)
        if self.token.kind == "name" and self.peek().is_op(".") and self.peek(2).is_op("*"):
            table = self.expect_name()
            self.advance()
            self.advance()
            return SelectItem(None, star_table=table)
        expr = self.expression()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_name()
        elif self.token.kind == "name":
            alias = self.expect_name()
        return SelectItem(expr, alias)

    def table_ref(self) -> TableRef:
        name = self.expect_name()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_name()
        elif self.token.kind == "name":
            alias = self.expect_name()
        return TableRef(name, alias)

    def join_clause(self) -> JoinClause | None:
        if self.accept_op(","):
            return JoinClause("cross", self.table_ref(), None)
        if self.accept_keyword("CROSS"):
            self.expect_keyword("JOIN")
            return JoinClause("cross", self.table_ref(), None)
        if self.accept_keyword("LEFT"):
            self.accept_keyword("OUTER")
            kind = "left"
        elif self.accept_keyword("INNER"):
            kind = "inner"
        elif self.token.is_keyword("JOIN"):
            kind = "inner"
        else:
            return None
        self.expect_keyword("JOIN")
        table = self.table_ref()
        if self.accept_keyword("ON"):
            return JoinClause(kind, table, self.expression())
        if kind == "left":
            self.fail("LEFT JOIN needs ON")
        return JoinClause("cross", table, None)

    def order_item(self) -> OrderItem:
        expr = self.expression()
        descending = False
        if self.accept_keyword("DESC"):
            descending = True
        else:
            self.accept_keyword("ASC")
        nulls = None
        if self.accept_keyword("NULLS"):
            if self.accept_keyword("FIRST"):
                nulls = "first"
            elif self.accept_keyword("LAST"):
                nulls = "last"
            else:
                self.fail("expected FIRST or LAST")
        return OrderItem(expr, descending, nulls)

    # -- expressions, loosest binding first

    def expression(self) -> Expr:
        return self.or_expr()

    def or_expr(self) -> Expr:
        left = self.and_expr()
        while self.accept_keyword("OR"):
            left = Binary("OR", left, self.and_expr())
        return left

    def and_expr(self) -> Expr:
        left = self.not_expr()
        while self.accept_keyword("AND"):
            left = Binary("AND", left, self.not_expr())
        return left

    def not_expr(self) -> Expr:
        if self.accept_keyword("NOT"):
            return Unary("NOT", self.not_expr())
        return self.equality()

    def equality(self) -> Expr:
        left = self.relational()
        while True:
            if self.token.is_op("=", "==", "!=", "<>"):
                op = str(self.advance().value)
                op = {"==": "=", "!=": "<>"}.get(op, op)
                left = Binary(op, left, self.relational())
            elif self.accept_keyword("IS"):
                negated = self.accept_keyword("NOT")
                right = self.relational()
                if isinstance(right, Literal) and right.value is None:
                    left = IsNull(left, negated)
                else:
                    left = Binary("IS NOT" if negated else "IS", left, right)
            elif self.token.is_keyword("NOT") and self.peek().is_keyword("IN", "BETWEEN"):
                self.advance()
                left = self.in_or_between(left, negated=True)
            elif self.token.is_keyword("IN", "BETWEEN"):
                left = self.in_or_between(left, negated=False)
            else:
                return left

    def in_or_between(self, operand: Expr, negated: bool) -> Expr:
        if self.accept_keyword("IN"):
            self.expect_op("(")
            if self.token.is_op(")"):
                self.fail("IN needs at least one value")
            items = [self.expression()]
            while self.accept_op(","):
                items.append(self.expression())
            self.expect_op(")")
            return InList(operand, tuple(items), negated)
        self.expect_keyword("BETWEEN")
        low = self.relational()
        self.expect_keyword("AND")
        high = self.relational()
        return Between(operand, low, high, negated)

    def relational(self) -> Expr:
        left = self.additive()
        while self.token.is_op("<", "<=", ">", ">="):
            op = str(self.advance().value)
            left = Binary(op, left, self.additive())
        return left

    def additive(self) -> Expr:
        left = self.multiplicative()
        while self.token.is_op("+", "-"):
            op = str(self.advance().value)
            left = Binary(op, left, self.multiplicative())
        return left

    def multiplicative(self) -> Expr:
        left = self.concat()
        while self.token.is_op("*", "/"):
            op = str(self.advance().value)
            left = Binary(op, left, self.concat())
        return left

    def concat(self) -> Expr:
        left = self.unary()
        while self.accept_op("||"):
            left = Binary("||", left, self.unary())
        return left

    def unary(self) -> Expr:
        if self.accept_op("-"):
            operand = self.unary()
            if isinstance(operand, Literal) and isinstance(operand.value, int):
                return Literal(-operand.value)
            return Unary("-", operand)
        if self.accept_op("+"):
            return self.unary()
        return self.primary()

    def primary(self) -> Expr:
        token = self.token
        if token.kind == "integer":
            self.advance()
            return Literal(token.value)
        if token.kind == "string":
            self.advance()
            return Literal(token.value)
        if token.is_keyword("NULL"):
            self.advance()
            return Literal(None)
        if token.is_keyword("CASE"):
            return self.case()
        if self.accept_op("("):
            expr = self.expression()
            self.expect_op(")")
            return expr
        if token.kind == "name":
            name = self.expect_name()
            if self.accept_op("("):
                return self.call(name.upper())
            if self.accept_op("."):
                return Column(name, self.expect_name())
            return Column(None, name)
        self.fail("expected an expression")

    def call(self, name: str) -> Call:
        if self.accept_op("*"):
            self.expect_op(")")
            if name != "COUNT":
                raise SQLError(f"{name}(*) is not allowed; only COUNT(*)")
            return Call(name, (), star=True)
        distinct = self.accept_keyword("DISTINCT")
        args: list[Expr] = []
        if not self.token.is_op(")"):
            args.append(self.expression())
            while self.accept_op(","):
                args.append(self.expression())
        self.expect_op(")")
        return Call(name, tuple(args), distinct=distinct)

    def case(self) -> Case:
        self.expect_keyword("CASE")
        operand = None
        if not self.token.is_keyword("WHEN"):
            operand = self.expression()
        whens = []
        while self.accept_keyword("WHEN"):
            condition = self.expression()
            self.expect_keyword("THEN")
            whens.append((condition, self.expression()))
        if not whens:
            self.fail("CASE needs at least one WHEN")
        default = self.expression() if self.accept_keyword("ELSE") else None
        self.expect_keyword("END")
        return Case(operand, tuple(whens), default)
