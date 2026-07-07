#!/usr/bin/env python3
"""Gulf of Mexico interpreter — a perfect programming language."""

import sys
import re
import math
import time
import random
import textwrap
import traceback
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Optional

# ============================================================
# Runtime Values
# ============================================================

UNDEFINED = object()
DELETED = object()

class GomObject:
    pass

class GomArray(list):
    pass

class GomFunction:
    def __init__(self, name, params, body, closure, func_type='function'):
        self.name = name
        self.params = params
        self.body = body
        self.closure = closure
        self.func_type = func_type

    def __call__(self, interpreter, args):
        old_env = interpreter.env
        interpreter.env = Environment(self.closure)
        for p, a in zip(self.params, args):
            interpreter.env.define(p, a, VarType.VAR_VAR, 1)
        result = None
        try:
            for stmt in self.body:
                result = interpreter.evaluate(stmt)
        except ReturnException as e:
            result = e.value
        interpreter.env = old_env
        return result if result is not None else UNDEFINED

class GomClass:
    def __init__(self, name, methods, body, interpreter):
        self.name = name
        self.methods = methods
        self.body = body
        self.interpreter = interpreter
        self.instantiated = False

    def instantiate(self):
        if self.instantiated:
            raise GomError(f"Can't have more than one '{self.name}' instance!")
        self.instantiated = True
        instance = GomObject()
        instance.__class_obj = self
        # Set up methods
        for name, method in self.methods.items():
            if isinstance(method, FuncDef):
                func = GomFunction(method.name, method.params, method.body, self.interpreter.env, method.func_type)
                setattr(instance, name, func)
            else:
                setattr(instance, name, method)
        # Run property declarations in their own env, then copy to instance
        old_env = self.interpreter.env
        self.interpreter.env = Environment(self.interpreter.env)
        for stmt in self.body:
            if not isinstance(stmt, FuncDef):
                self.interpreter.evaluate(stmt)
        for name, entry in self.interpreter.env.vars.items():
            setattr(instance, name, entry.value)
        self.interpreter.env = old_env
        return instance

class GomInstance:
    pass

class GomError(Exception):
    def __init__(self, message, line=None, col=None, source=None):
        self.message = message
        self.line = line
        self.col = col
        self.source = source
        super().__init__(self.format())

    def format(self):
        if self.line:
            loc = f" at line {self.line}"
            if self.source and 0 <= self.line - 1 < len(self.source):
                loc += f"\n  --> {self.source[self.line - 1].rstrip()}"
                if self.col:
                    loc += f"\n       {' ' * (self.col - 1)}^"
        else:
            loc = ""
        return f"GulfOfMexico.Error: {self.message}{loc}"

class ReturnException(Exception):
    def __init__(self, value):
        self.value = value

class GomInternalError(Exception):
    pass

class VarType(Enum):
    CONST_CONST = auto()
    CONST_VAR = auto()
    VAR_CONST = auto()
    VAR_VAR = auto()
    CONST_CONST_CONST = auto()


# ============================================================
# Tokenizer
# ============================================================

class TokenType(Enum):
    EOF = auto(); EOL = auto()
    NUMBER = auto(); STRING = auto(); IDENTIFIER = auto()
    PLUS = auto(); MINUS = auto(); STAR = auto(); SLASH = auto()
    PERCENT = auto(); CARET = auto(); PIPE = auto()
    PLUS_PLUS = auto(); MINUS_MINUS = auto()
    EQ = auto(); EQ2 = auto(); EQ3 = auto(); EQ4 = auto()
    BANG = auto(); QUES = auto(); INV_BANG = auto()
    LPAREN = auto(); RPAREN = auto()
    LBRACK = auto(); RBRACK = auto()
    LBRACE = auto(); RBRACE = auto()
    COMMA = auto(); DOT = auto(); COLON = auto()
    ARROW = auto(); SEMI = auto()
    LT = auto(); GT = auto(); LE = auto(); GE = auto()
    AND = auto(); OR = auto()
    CONST = auto(); VAR = auto(); IF = auto(); ELSE = auto()
    WHEN = auto(); DELETE = auto(); REVERSE = auto()
    PREVIOUS = auto(); NEXT = auto(); CURRENT = auto()
    TRUE = auto(); FALSE = auto(); MAYBE = auto()
    CLASS = auto(); NEW = auto(); RETURN = auto()
    EXPORT = auto(); IMPORT = auto(); NOOP = auto(); USE = auto()
    ASYNC = auto(); FUNC = auto(); INFINITY = auto(); UNDEFINED = auto()
    AWAIT = auto()
    FILE_SEP = auto()

KEYWORDS = {
    'const': 'CONST', 'var': 'VAR', 'if': 'IF', 'else': 'ELSE',
    'when': 'WHEN', 'delete': 'DELETE', 'reverse': 'REVERSE',
    'previous': 'PREVIOUS', 'next': 'NEXT', 'current': 'CURRENT',
    'true': 'TRUE', 'false': 'FALSE', 'maybe': 'MAYBE',
    'class': 'CLASS', 'new': 'NEW', 'return': 'RETURN',
    'export': 'EXPORT', 'import': 'IMPORT', 'noop': 'NOOP',
    'use': 'USE', 'async': 'ASYNC', 'Infinity': 'INFINITY',
    'undefined': 'UNDEFINED', 'className': 'CLASS',
    'await': 'AWAIT',
}

FUNCTION_NAMES = {'function', 'func', 'fun', 'fn', 'functi', 'funct', 'functio', 'union'}

NUMBER_NAMES = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
    'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17,
    'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30,
    'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
    'eighty': 80, 'ninety': 90, 'hundred': 100, 'thousand': 1000,
}

@dataclass
class Token:
    type: TokenType
    value: Any = None
    line: int = 0
    col: int = 0

def tokenize(text: str) -> list:
    tokens = []
    pos = 0
    line = 1
    col = 1

    def advance(n=1):
        nonlocal pos, col, line
        for _ in range(n):
            if pos < len(text) and text[pos] == '\n':
                line += 1
                col = 1
            else:
                col += 1
            pos += 1

    def peek(offset=0):
        idx = pos + offset
        return text[idx] if idx < len(text) else None

    def current():
        return text[pos] if pos < len(text) else None

    while pos < len(text):
        ch = current()

        # File separator (5+ ====)
        if ch == '=' and peek(1) == '=' and peek(2) == '=' and peek(3) == '=' and peek(4) == '=':
            start = line
            count = 0
            while current() == '=':
                count += 1; advance()
            fname = ''
            while current() in ' \t':
                advance()
            while current() is not None and current() not in '\n\r':
                fname += current(); advance()
            tokens.append(Token(TokenType.FILE_SEP, fname.strip(), start, 0))
            continue

        # Newlines
        if ch == '\n':
            advance()
            tokens.append(Token(TokenType.EOL, '\n', line - 1, 0))
            continue
        if ch == '\r':
            advance()
            continue

        # Whitespace
        if ch in ' \t':
            advance()
            continue

        # Comments
        if ch == '/' and peek(1) == '/':
            while current() is not None and current() not in '\n\r':
                advance()
            continue

        # Rich text HTML tags (<b>, </b>, <i>, <a href="...">, etc.)
        if ch == '<':
            save_pos = pos
            save_line = line
            save_col = col
            advance()
            had_slash = False
            if current() == '/':
                had_slash = True
                advance()
            tag_name = ''
            while current() is not None and current() not in '>/ \t\n\r':
                tag_name += current(); advance()
            if tag_name and current() in ('>', ' '):
                while current() is not None and current() not in '>\n\r':
                    advance()
                if current() == '>':
                    advance()
                    continue
            # Not a tag, backtrack
            pos = save_pos
            line = save_line
            col = save_col

        # Numbers
        if ch.isdigit() or (ch == '.' and peek(1) and peek(1).isdigit()):
            start = line, col
            num = ''
            is_float = False
            while current() is not None and (current().isdigit() or current() == '.'):
                if current() == '.':
                    if is_float: break
                    is_float = True
                num += current(); advance()
            tokens.append(Token(TokenType.NUMBER, float(num) if is_float else int(num), line, col))
            continue

        # Strings
        if ch in '"\'':
            q = ch
            qc = 0
            start_line = line
            while current() == q:
                qc += 1; advance()
            content = ''
            while current() is not None:
                if current() == '\n':
                    line += 1; col = 1
                if current() == q:
                    ec = 0
                    save = pos
                    while current() == q:
                        ec += 1; advance()
                    if ec == qc:
                        break
                    pos = save; col -= ec
                elif current() == '\\' and peek(1) == q:
                    advance(); content += q; advance()
                else:
                    content += current(); advance()
            tokens.append(Token(TokenType.STRING, content, start_line, col))
            continue

        # => arrow (MUST come before single = check)
        if ch == '+' and peek(1) == '+':
            advance(2); tokens.append(Token(TokenType.PLUS_PLUS, '++', line, col)); continue
        if ch == '-' and peek(1) == '-':
            advance(2); tokens.append(Token(TokenType.MINUS_MINUS, '--', line, col)); continue
        if ch == '=' and peek(1) == '>':
            advance(2); tokens.append(Token(TokenType.ARROW, '=>', line, col)); continue
        if ch == '-' and peek(1) == '>':
            advance(2); tokens.append(Token(TokenType.ARROW, '->', line, col)); continue

        # == == === ====
        if ch == '=':
            if peek(1) == '=' and peek(2) == '=' and peek(3) == '=':
                advance(4); tokens.append(Token(TokenType.EQ4, '====', line, col))
            elif peek(1) == '=' and peek(2) == '=':
                advance(3); tokens.append(Token(TokenType.EQ3, '===', line, col))
            elif peek(1) == '=':
                advance(2); tokens.append(Token(TokenType.EQ2, '==', line, col))
            else:
                advance(); tokens.append(Token(TokenType.EQ, '=', line, col))
            continue

        # ! and !!!
        if ch == '!':
            cnt = 0
            while current() == '!':
                cnt += 1; advance()
            tokens.append(Token(TokenType.BANG, cnt, line, col))
            continue

        # ?
        if ch == '?':
            advance(); tokens.append(Token(TokenType.QUES, '?', line, col)); continue

        # ¡
        if ch == '¡':
            advance(); tokens.append(Token(TokenType.INV_BANG, '¡', line, col)); continue

        # Multi-char operators
        if ch == '>' and peek(1) == '=':
            advance(2); tokens.append(Token(TokenType.GE, '>=', line, col)); continue
        if ch == '<' and peek(1) == '=':
            advance(2); tokens.append(Token(TokenType.LE, '<=', line, col)); continue
        if ch == '&' and peek(1) == '&':
            advance(2); tokens.append(Token(TokenType.AND, '&&', line, col)); continue
        if ch == '|' and peek(1) == '|':
            advance(2); tokens.append(Token(TokenType.OR, '||', line, col)); continue

        # Single char operators
        single = {
            '+': 'PLUS', '-': 'MINUS', '*': 'STAR', '/': 'SLASH',
            '%': 'PERCENT', '^': 'CARET', '|': 'PIPE',
            '(': 'LPAREN', ')': 'RPAREN', '[': 'LBRACK', ']': 'RBRACK',
            '{': 'LBRACE', '}': 'RBRACE', ',': 'COMMA', '.': 'DOT',
            ';': 'SEMI', ':': 'COLON', '<': 'LT', '>': 'GT',
        }
        if ch in single:
            tt = TokenType[single[ch]]
            tokens.append(Token(tt, ch, line, col))
            advance()
            continue

        # Identifiers, keywords, bare strings
        if ch.isalpha() or ch == '_' or ord(ch) > 127:
            start_line, start_col = line, col
            name = ''
            while current() is not None and (current().isalnum() or current() in '_' or ord(current()) > 127):
                name += current(); advance()
            if name in KEYWORDS:
                tokens.append(Token(TokenType[KEYWORDS[name]], name, start_line, start_col))
            elif name in FUNCTION_NAMES:
                tokens.append(Token(TokenType.FUNC, name, start_line, start_col))
            else:
                tokens.append(Token(TokenType.IDENTIFIER, name, start_line, start_col))
            continue

        raise SyntaxError(f"Line {line}, Col {col}: Unexpected character {ch!r}")

    tokens.append(Token(TokenType.EOF, None, line, col))
    return tokens

# ============================================================
# AST Nodes
# ============================================================

class AST:
    pass

@dataclass
class Program(AST):
    statements: list

@dataclass
class Block(AST):
    statements: list

@dataclass
class ExprStmt(AST):
    expr: object
    bang_count: int = 1

@dataclass
class DebugStmt(AST):
    expr: object

@dataclass
class Decl(AST):
    constancy: tuple  # (is_value_const, is_ref_const)
    name: str
    value: object
    bang_count: int = 1
    lifetime: object = None  # None=no limit, int=lines, float=seconds, 'Infinity'=forever

@dataclass
class Assign(AST):
    target: object
    value: object
    bang_count: int = 1

@dataclass
class BinaryOp(AST):
    op: str
    left: object
    right: object
    left_ws: bool = False
    right_ws: bool = False

@dataclass
class UnaryOp(AST):
    op: str
    operand: object

@dataclass
class Literal(AST):
    value: object

@dataclass
class Identifier(AST):
    name: str

@dataclass
class ArrayLit(AST):
    elements: list

@dataclass
class IndexExpr(AST):
    obj: object
    index: object

@dataclass
class CallExpr(AST):
    callee: object
    args: list

@dataclass
class FuncDef(AST):
    name: str
    params: list
    body: list
    func_type: str
    is_async: bool

@dataclass
class IncExpr(AST):
    name: str
    delta: int

@dataclass
class Lambda(AST):
    params: list
    body: list

@dataclass
class IfStmt(AST):
    condition: object
    then_block: object
    else_block: object = None

@dataclass
class WhenStmt(AST):
    condition: object
    body: object

@dataclass
class DeleteStmt(AST):
    target: object

@dataclass
class ReturnStmt(AST):
    value: object = None

@dataclass
class ClassDef(AST):
    name: str
    methods: list
    body: list

@dataclass
class NewExpr(AST):
    class_name: str

@dataclass
class NoopStmt(AST):
    pass

@dataclass
class ReverseStmt(AST):
    pass

@dataclass
class PreviousExpr(AST):
    expr: object

@dataclass
class NextExpr(AST):
    expr: object

@dataclass
class CurrentExpr(AST):
    expr: object

@dataclass
class AwaitExpr(AST):
    expr: object

# ============================================================
# Environment
# ============================================================

@dataclass
class VarEntry:
    type: VarType
    value: Any
    bang_count: int = 1
    watches: list = field(default_factory=list)
    lifetime: object = None  # None=no limit, int=remaining lines, float=expiry timestamp, 'Infinity'=forever

class Environment:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent
        self.pending = {}  # overloaded vars waiting for resolution

    def define(self, name, value, var_type, bang_count=1, lifetime=None):
        entry = VarEntry(var_type, value, bang_count, lifetime=lifetime)
        if name in self.vars:
            existing = self.vars[name]
            if bang_count > existing.bang_count:
                self.vars[name] = entry
            elif bang_count < existing.bang_count:
                pass
            else:
                self.vars[name] = entry
        else:
            self.vars[name] = entry
        return entry

    def lookup(self, name, check_lifetime=True):
        if name in self.vars:
            entry = self.vars[name]
            if check_lifetime and entry.lifetime is not None and entry.lifetime != 'Infinity':
                if isinstance(entry.lifetime, float) and time.time() > entry.lifetime:
                    del self.vars[name]
                    return None
            return entry
        if self.parent:
            return self.parent.lookup(name, check_lifetime)
        return None

    def get(self, name):
        entry = self.lookup(name)
        if entry is None:
            return None
        return entry.value

    def get_watch_id(self):
        if not hasattr(self, '_watch_counter'):
            self._watch_counter = 0
        self._watch_counter += 1
        return self._watch_counter

    def set(self, name, value):
        entry = self.lookup(name)
        if entry is None:
            raise GomError(f"Variable '{name}' not defined")
        if entry.type in (VarType.CONST_CONST, VarType.CONST_CONST_CONST):
            raise GomError(f"Variable '{name}' is const const (cannot be reassigned)")
        if entry.type == VarType.CONST_VAR:
            raise GomError(f"Variable '{name}' is const var (cannot be reassigned)")
        self._record_previous(name)
        old = entry.value
        entry.value = value
        for w in entry.watches:
            w(name, old, value)
        return True

    def mutate(self, name, mutator):
        entry = self.lookup(name)
        if entry is None:
            raise GomError(f"Variable '{name}' not defined")
        if entry.type in (VarType.CONST_CONST, VarType.VAR_CONST, VarType.CONST_CONST_CONST):
            raise GomError(f"Variable '{name}' cannot be mutated")
        self._record_previous(name)
        old = entry.value
        new = mutator(old)
        entry.value = new
        for w in entry.watches:
            w(name, old, new)
        return new

    def _record_previous(self, name):
        entry = self.lookup(name)
        if entry:
            if not hasattr(self, '_prev'):
                self._prev = {}
            self._prev[name] = entry.value

    def get_previous(self, name):
        prev = getattr(self, '_prev', {})
        return prev.get(name, None)

# ============================================================
# Parser
# ============================================================

class Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def peek(self, offset=0):
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else None

    def expect(self, *types):
        tok = self.current()
        if tok and tok.type in types:
            self.pos += 1
            return tok
        if tok:
            raise SyntaxError(f"Line {tok.line}: Expected {types}, got {tok.type} ({tok.value})")
        raise SyntaxError(f"Unexpected end of input, expected {types}")

    def match(self, *types):
        tok = self.current()
        if tok and tok.type in types:
            self.pos += 1
            return tok
        return None

    def match_paren(self, expected_type):
        """Match a parenthesis, allowing flipped versions: ) for ( and ( for )."""
        tok = self.current()
        if not tok:
            return None
        flipped = {TokenType.LPAREN: TokenType.RPAREN, TokenType.RPAREN: TokenType.LPAREN}
        if tok.type == expected_type or (expected_type in flipped and tok.type == flipped[expected_type]):
            self.pos += 1
            return tok
        return None

    def skip_eol(self):
        while self.current() and self.current().type == TokenType.EOL:
            self.pos += 1

    def parse_program(self):
        stmts = []
        while self.current() and self.current().type != TokenType.EOF:
            stmts.extend(self.parse_statement())
        return Program(stmts)

    def parse_statement(self):
        self.skip_eol()
        tok = self.current()
        if not tok or tok.type == TokenType.EOF:
            return []

        if tok.type == TokenType.FILE_SEP:
            self.pos += 1
            return []

        if tok.type == TokenType.CONST or tok.type == TokenType.VAR:
            return [self.parse_declaration()]

        if tok.type == TokenType.IF:
            return [self.parse_if()]

        if tok.type == TokenType.WHEN:
            return [self.parse_when()]

        if tok.type == TokenType.DELETE:
            return [self.parse_delete()]

        if tok.type == TokenType.REVERSE:
            self.pos += 1
            s = ReverseStmt()
            self.match(TokenType.BANG)
            return [s]

        if tok.type == TokenType.RETURN:
            return [self.parse_return()]

        if tok.type == TokenType.CLASS:
            return [self.parse_class()]

        if tok.type == TokenType.ASYNC:
            self.pos += 1
            # async func/fn/fun/functi/funct/functio/union ...
            if self.current() and self.current().type == TokenType.FUNC:
                func_def = self.parse_func_def()
                func_def.is_async = True
                return [func_def]
            raise SyntaxError(f"Line {tok.line}: Expected function after async")

        if tok.type == TokenType.FUNC:
            return [self.parse_func_def()]

        if tok.type == TokenType.EXPORT:
            return [self.parse_export()]

        if tok.type == TokenType.IMPORT:
            return [self.parse_import()]

        if tok.type == TokenType.NOOP:
            self.pos += 1
            self.match(TokenType.BANG)
            return [NoopStmt()]

        if tok.type == TokenType.AWAIT:
            self.pos += 1
            expr = self.parse_expression()
            return [ExprStmt(expr)]

        return [self.parse_expr_stmt()]

    def parse_declaration(self):
        constancy = []
        bang_count = 1
        
        tok1 = self.expect(TokenType.CONST, TokenType.VAR)
        constancy.append(tok1.type)
        
        tok2 = self.current()
        if tok2 and tok2.type in (TokenType.CONST, TokenType.VAR):
            constancy.append(tok2.type)
            self.pos += 1
        else:
            constancy.append(tok2.type if tok2 else TokenType.VAR)
            # Actually if only one keyword, duplicate it
            constancy.append(constancy[0])

        # Check for const const const
        tok3 = self.current()
        if len(constancy) >= 2 and constancy[0] == TokenType.CONST and constancy[1] == TokenType.CONST:
            if tok3 and tok3.type == TokenType.CONST:
                self.pos += 1
                constancy.append(TokenType.CONST)

        # Destructuring: [a, b] = expr
        if self.current() and self.current().type == TokenType.LBRACK:
            self.pos += 1
            names = []
            while self.current() and self.current().type != TokenType.RBRACK:
                ntok = self.expect(TokenType.IDENTIFIER)
                names.append(ntok.value)
                self.match(TokenType.COMMA)
            self.match(TokenType.RBRACK)
            self.match(TokenType.EQ)
            value = self.parse_expression()
            bang = self.match(TokenType.BANG)
            if len(constancy) >= 3:
                vtype = VarType.CONST_CONST_CONST
            elif constancy[0] == TokenType.CONST and constancy[1] == TokenType.CONST:
                vtype = VarType.CONST_CONST
            elif constancy[0] == TokenType.CONST and constancy[1] == TokenType.VAR:
                vtype = VarType.CONST_VAR
            elif constancy[0] == TokenType.VAR and constancy[1] == TokenType.CONST:
                vtype = VarType.VAR_CONST
            else:
                vtype = VarType.VAR_VAR
            # For destructuring, we return a Decl with the value immediately evaluated
            # and stored into each name. We use a sentinel name and handle it in evaluate.
            return Decl(vtype, '__destructure__', Literal((names, value)), bang_count or 1)

        name_tok = self.expect(TokenType.IDENTIFIER, TokenType.NUMBER, TokenType.STRING)
        name = str(name_tok.value)

        # Type annotation (optional, does nothing)
        if self.match(TokenType.COLON):
            while self.current() and self.current().type not in (TokenType.EQ, TokenType.BANG, TokenType.EOL, TokenType.EOF):
                self.pos += 1

        # Lifetime (optional, <2> or <20s> or <Infinity>)
        lifetime = None
        if self.current() and self.current().type == TokenType.LT:
            self.pos += 1
            life_parts = []
            while self.current() and self.current().type not in (TokenType.GT, TokenType.EOF):
                life_parts.append(str(self.current().value))
                self.pos += 1
            self.match(TokenType.GT)
            life_str = ''.join(life_parts)
            if life_str.lower() == 'infinity':
                lifetime = 'Infinity'
            elif life_str.endswith('s'):
                try:
                    lifetime = float(life_str[:-1])
                except ValueError:
                    lifetime = None
            else:
                try:
                    lifetime = int(life_str)
                except ValueError:
                    lifetime = None

        self.match(TokenType.EQ)

        value = self.parse_expression()

        bang = self.match(TokenType.BANG)
        if bang:
            bang_count = bang.value if isinstance(bang.value, int) else 1
        inv = self.match(TokenType.INV_BANG)
        if inv:
            bang_count = -1

        if len(constancy) >= 3:
            vtype = VarType.CONST_CONST_CONST
        elif constancy[0] == TokenType.CONST and constancy[1] == TokenType.CONST:
            vtype = VarType.CONST_CONST
        elif constancy[0] == TokenType.CONST and constancy[1] == TokenType.VAR:
            vtype = VarType.CONST_VAR
        elif constancy[0] == TokenType.VAR and constancy[1] == TokenType.CONST:
            vtype = VarType.VAR_CONST
        else:
            vtype = VarType.VAR_VAR

        return Decl(vtype, name, value, bang_count, lifetime)

    def parse_if(self):
        self.expect(TokenType.IF)
        self.match(TokenType.LPAREN)
        cond = self.parse_expression()
        self.match(TokenType.RPAREN)
        self.match(TokenType.ARROW)
        self.match(TokenType.LBRACE)
        then_block = self.parse_block_body()
        
        else_block = None
        if self.current() and self.current().type == TokenType.ELSE:
            self.pos += 1
            self.match(TokenType.LBRACE)
            else_block = self.parse_block_body()

        return IfStmt(cond, then_block, else_block)

    def parse_block_body(self):
        """Parse statements inside { } and stop at matching }."""
        stmts = []
        depth = 1
        while self.current() and depth > 0:
            self.skip_eol()
            if self.current().type == TokenType.EOF:
                break
            if self.current().type == TokenType.RBRACE:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    break
            stmts.extend(self.parse_statement())
        return stmts

    def parse_when(self):
        self.expect(TokenType.WHEN)
        self.match(TokenType.LPAREN)
        cond = self.parse_expression()
        self.match(TokenType.RPAREN)
        self.match(TokenType.LBRACE)
        body = self.parse_block_body()
        return WhenStmt(cond, body)

    def parse_delete(self):
        self.expect(TokenType.DELETE)
        if self.current() and self.current().type in (TokenType.IDENTIFIER, TokenType.NUMBER, TokenType.STRING,
                                                       TokenType.CLASS, TokenType.FUNC, TokenType.IF,
                                                       TokenType.DELETE, TokenType.CONST, TokenType.VAR):
            target = self.current().value
            self.pos += 1
        else:
            target = self.parse_expression()
        self.match(TokenType.BANG)
        return DeleteStmt(target)

    def parse_return(self):
        self.expect(TokenType.RETURN)
        val = self.parse_expression()
        self.match(TokenType.BANG)
        return ReturnStmt(val)

    def parse_class(self):
        self.expect(TokenType.CLASS)
        name_tok = self.expect(TokenType.IDENTIFIER)
        self.match(TokenType.LBRACE)
        methods = {}
        body = self.parse_block_body()
        for stmt in body:
            if isinstance(stmt, FuncDef):
                methods[stmt.name] = stmt
        return ClassDef(name_tok.value, methods, body)

    def parse_export(self):
        """export <name> to <filename>!"""
        self.expect(TokenType.EXPORT)
        name_tok = self.expect(TokenType.IDENTIFIER)
        self.match(TokenType.IDENTIFIER)  # 'to'
        fname = self.parse_expression()
        self.match(TokenType.BANG)
        return ExprStmt(Literal(('__export__', name_tok.value, fname)))

    def parse_import(self):
        """import <name>!"""
        self.expect(TokenType.IMPORT)
        name_tok = self.expect(TokenType.IDENTIFIER)
        self.match(TokenType.BANG)
        return ExprStmt(Literal(('__import__', name_tok.value)))

    def parse_func_def(self):
        is_async = False
        if self.current() and self.current().type == TokenType.ASYNC:
            self.pos += 1
            is_async = True
        func_tok = self.expect(TokenType.FUNC)
        name_tok = self.expect(TokenType.IDENTIFIER)
        self.match_paren(TokenType.LPAREN)
        params = []
        close_type = TokenType.RPAREN
        # Check if we're using flipped parens
        last_paren = self.current()
        # Look for first non-whitespace... actually just use the normal close check
        while self.current():
            if self.current().type in (TokenType.RPAREN, TokenType.LPAREN):
                break
            if self.current().type == TokenType.IDENTIFIER:
                params.append(self.current().value)
                self.pos += 1
            self.match(TokenType.COMMA)
        self.match_paren(TokenType.RPAREN)
        self.match(TokenType.ARROW)
        
        # Check if body is a block or single expression
        if self.current() and self.current().type == TokenType.LBRACE:
            self.pos += 1
            body = self.parse_block_body()
            return FuncDef(name_tok.value, params, body, func_tok.value, is_async)
        else:
            expr = self.parse_expression()
            self.match(TokenType.BANG)
            return FuncDef(name_tok.value, params, [ReturnStmt(expr)], func_tok.value, is_async)

    def parse_expr_stmt(self):
        expr = self.parse_expression()
        # Convert top-level BinaryOp(=) to Assign for assignment
        if isinstance(expr, BinaryOp) and expr.op == '=':
            if isinstance(expr.left, Identifier):
                expr = Assign(expr.left, expr.right)
            elif isinstance(expr.left, IndexExpr):
                expr = Assign(expr.left, expr.right)
        bang = self.match(TokenType.BANG)
        if bang:
            bc = bang.value if isinstance(bang.value, int) else 1
            return ExprStmt(expr, bc)
        q = self.match(TokenType.QUES)
        if q:
            return DebugStmt(expr)
        ib = self.match(TokenType.INV_BANG)
        if ib:
            return ExprStmt(expr, -1)
        return ExprStmt(expr, 0)

    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.match(TokenType.OR):
            right = self.parse_and()
            left = BinaryOp('||', left, right)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.match(TokenType.AND):
            right = self.parse_equality()
            left = BinaryOp('&&', left, right)
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        while True:
            tok = self.current()
            if tok and tok.type in (TokenType.EQ2, TokenType.EQ3, TokenType.EQ4, TokenType.EQ):
                self.pos += 1
                right = self.parse_comparison()
                op = {TokenType.EQ2: '==', TokenType.EQ3: '===', TokenType.EQ4: '====',
                      TokenType.EQ: '='}[tok.type]
                left = BinaryOp(op, left, right)
            else:
                break
        return left

    def parse_comparison(self):
        left = self.parse_addition()
        while True:
            tok = self.current()
            if tok and tok.type in (TokenType.LT, TokenType.GT, TokenType.LE, TokenType.GE):
                self.pos += 1
                right = self.parse_addition()
                left = BinaryOp(tok.value, left, right)
            else:
                break
        return left

    def parse_addition(self):
        left = self.parse_pipe()
        while True:
            tok = self.current()
            if tok and tok.type in (TokenType.PLUS, TokenType.MINUS):
                op_col = tok.col
                has_left_ws = False
                last_end = getattr(self, '_last_expr_end', 0)
                has_left_ws = op_col > last_end + 1 if last_end else True
                self.pos += 1
                right = self.parse_pipe()
                has_right_ws = False
                if hasattr(right, '_expr_start'):
                    has_right_ws = right._expr_start > op_col + 2
                left = BinaryOp(tok.value, left, right, left_ws=has_left_ws, right_ws=has_right_ws)
            else:
                break
        self._last_expr_end = getattr(tok, 'col', 0) if tok else self._last_expr_end
        return left

    def parse_pipe(self):
        left = self.parse_multiplication()
        while True:
            tok = self.current()
            if tok and tok.type == TokenType.PIPE:
                self.pos += 1
                right = self.parse_multiplication()
                left = BinaryOp('|', left, right)
            else:
                break
        return left

    def parse_multiplication(self):
        left = self.parse_power()
        while True:
            tok = self.current()
            if tok and tok.type in (TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
                op_col = tok.col
                has_left_ws = False
                last_end = getattr(self, '_last_expr_end', 0)
                has_left_ws = op_col > last_end + 1 if last_end else True
                self.pos += 1
                right = self.parse_power()
                has_right_ws = False
                if hasattr(right, '_expr_start'):
                    has_right_ws = right._expr_start > op_col + 2
                left = BinaryOp(tok.value, left, right, left_ws=has_left_ws, right_ws=has_right_ws)
            else:
                break
        self._last_expr_end = getattr(tok, 'col', 0) if tok else self._last_expr_end
        return left

    def parse_power(self):
        left = self.parse_unary()
        while True:
            tok = self.current()
            if tok and tok.type == TokenType.CARET:
                self.pos += 1
                right = self.parse_power()  # right-associative
                left = BinaryOp('^', left, right)
            else:
                break
        return left

    def parse_unary(self):
        tok = self.current()
        if tok and tok.type in (TokenType.MINUS, TokenType.SEMI):
            self.pos += 1
            if tok.type == TokenType.SEMI:
                return UnaryOp('!', self.parse_unary())
            return UnaryOp('-', self.parse_unary())
        if tok and tok.type == TokenType.PREVIOUS:
            self.pos += 1
            return PreviousExpr(self.parse_unary())
        if tok and tok.type == TokenType.NEXT:
            self.pos += 1
            return NextExpr(self.parse_unary())
        if tok and tok.type == TokenType.CURRENT:
            self.pos += 1
            return CurrentExpr(self.parse_unary())
        if tok and tok.type == TokenType.AWAIT:
            self.pos += 1
            return AwaitExpr(self.parse_unary())
        return self.parse_call()

    START_OF_EXPR = {TokenType.IDENTIFIER, TokenType.NUMBER, TokenType.STRING,
                     TokenType.TRUE, TokenType.FALSE, TokenType.MAYBE,
                     TokenType.INFINITY, TokenType.UNDEFINED,
                     TokenType.LPAREN, TokenType.LBRACK, TokenType.LBRACE,
                     TokenType.FUNC, TokenType.CLASS, TokenType.NEW,
                     TokenType.SEMI}

    def parse_flipped_arg(self):
        """Parse a simple argument in a flipped call, stopping at LPAREN or BANG."""
        tok = self.current()
        if not tok or tok.type in (TokenType.LPAREN, TokenType.BANG):
            return Literal(UNDEFINED)
        # Parse just the immediate value, not full expression chain
        val = self.parse_primary()
        # Check for binary ops that stay within the flipped args
        while self.current() and self.current().type in (TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH):
            if self.peek(1) and self.peek(1).type in (TokenType.LPAREN, TokenType.COMMA, TokenType.BANG):
                break
            op = self.current().type
            self.pos += 1
            right = self.parse_primary()
            op_str = {TokenType.PLUS: '+', TokenType.MINUS: '-', TokenType.STAR: '*', TokenType.SLASH: '/'}.get(op, '+')
            val = BinaryOp(op_str, val, right)
        return val

    def parse_call(self):
        expr = self.parse_primary()
        # Check for arrow function: () => expr or IDENTIFIER => expr
        if self.current() and self.current().type == TokenType.ARROW:
            if isinstance(expr, Identifier):
                params = [expr.name]
            elif isinstance(expr, ArrayLit) and not expr.elements:
                params = []
            else:
                params = []
            self.pos += 1  # consume =>
            if self.current() and self.current().type == TokenType.LBRACE:
                self.pos += 1
                body = self.parse_block_body()
                return Lambda(params, body)
            else:
                body_expr = self.parse_expression()
                return Lambda(params, [ReturnStmt(body_expr)])
        # Check for increment/decrement: IDENTIFIER ++ / IDENTIFIER --
        if isinstance(expr, Identifier) and self.current() and self.current().type in (TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
            inc = self.current().type == TokenType.PLUS_PLUS
            self.pos += 1
            # Create a special inc/dec expression
            delta = 1 if inc else -1
            # We'll handle this via a special IncExpr or in evaluate
            return IncExpr(expr.name, delta)
        # Check for flipped function call: IDENTIFIER ) args (
        # Only if ) is followed by a value token (not block-open or close-paren context)
        FLIPPED_START = self.START_OF_EXPR - {TokenType.LBRACE, TokenType.FUNC, TokenType.CLASS}
        if (isinstance(expr, Identifier) and self.current() and self.current().type == TokenType.RPAREN
                and self.peek(1) and self.peek(1).type in FLIPPED_START):
            self.pos += 1
            args = []
            while self.current():
                if self.current().type == TokenType.LPAREN:
                    self.pos += 1
                    break
                if self.current().type == TokenType.BANG:
                    break
                args.append(self.parse_flipped_arg())
                self.match(TokenType.COMMA)
            expr = CallExpr(expr, args)
        while True:
            tok = self.current()
            if not tok:
                break
            if tok.type == TokenType.LPAREN:
                self.pos += 1
                args = []
                while self.current() and self.current().type != TokenType.RPAREN:
                    if self.current().type == TokenType.BANG:
                        break
                    args.append(self.parse_expression())
                    self.match(TokenType.COMMA)
                if self.current() and self.current().type == TokenType.RPAREN:
                    self.pos += 1
                expr = CallExpr(expr, args)
            elif tok.type == TokenType.DOT:
                self.pos += 1
                name_tok = self.expect(TokenType.IDENTIFIER)
                expr = IndexExpr(expr, Literal(name_tok.value))
            elif tok.type == TokenType.LBRACK:
                self.pos += 1
                idx = self.parse_expression()
                self.match(TokenType.RBRACK)
                expr = IndexExpr(expr, idx)
            elif tok.type in self.START_OF_EXPR:
                # Implicit function call (no parentheses)
                args = [self.parse_expression()]
                while self.current() and self.current().type == TokenType.COMMA:
                    self.pos += 1
                    args.append(self.parse_expression())
                expr = CallExpr(expr, args)
            else:
                break
        return expr

    def parse_primary(self):
        tok = self.current()
        if not tok:
            raise SyntaxError("Unexpected end of expression")

        if tok.type == TokenType.NUMBER:
            self.pos += 1
            return Literal(tok.value)

        if tok.type == TokenType.STRING:
            self.pos += 1
            return Literal(tok.value)

        if tok.type == TokenType.TRUE:
            self.pos += 1
            return Literal(True)
        if tok.type == TokenType.FALSE:
            self.pos += 1
            return Literal(False)
        if tok.type == TokenType.MAYBE:
            self.pos += 1
            return Literal('maybe')
        if tok.type == TokenType.INFINITY:
            self.pos += 1
            return Literal(float('inf'))
        if tok.type == TokenType.UNDEFINED:
            self.pos += 1
            return Literal(UNDEFINED)

        if tok.type in (TokenType.LPAREN, TokenType.RPAREN):
            is_flipped = tok.type == TokenType.RPAREN
            close_type = TokenType.LPAREN if is_flipped else TokenType.RPAREN
            self.pos += 1
            # Handle () as empty grouping for arrow functions
            if self.current() and self.current().type == close_type:
                self.pos += 1
                return ArrayLit([])
            expr = self.parse_expression()
            self.match_paren(close_type)
            return expr  # Parentheses do nothing in GoM!

        if tok.type == TokenType.LBRACK:
            self.pos += 1
            elems = []
            while self.current() and self.current().type != TokenType.RBRACK:
                elems.append(self.parse_expression())
                self.match(TokenType.COMMA)
            self.match(TokenType.RBRACK)
            return ArrayLit(elems)

        if tok.type == TokenType.LBRACE:
            self.pos += 1
            obj = {}
            while self.current() and self.current().type != TokenType.RBRACE:
                k = self.parse_expression()
                self.match(TokenType.COLON)
                v = self.parse_expression()
                obj[k] = v
                self.match(TokenType.COMMA)
            self.match(TokenType.RBRACE)
            return Literal(obj)

        if tok.type == TokenType.NEW:
            self.pos += 1
            name_tok = self.expect(TokenType.IDENTIFIER)
            self.match(TokenType.LPAREN); self.match(TokenType.RPAREN)
            return NewExpr(name_tok.value)

        if tok.type == TokenType.USE:
            self.pos += 1
            self.match(TokenType.LPAREN)
            args = []
            if self.current() and self.current().type != TokenType.RPAREN:
                args.append(self.parse_expression())
            self.match(TokenType.RPAREN)
            return CallExpr(Identifier('use'), args)

        if tok.type == TokenType.IDENTIFIER:
            self.pos += 1
            return Identifier(tok.value)

        raise SyntaxError(f"Line {tok.line}: Unexpected token {tok.type} ({tok.value})")

# ============================================================
# Interpreter
# ============================================================

class Interpreter:
    def __init__(self, source_lines=None, filename=None):
        self.env = Environment()
        self.global_env = self.env
        self.debug_mode = False
        self.deleted = set()
        self.reverse_mode = False
        self._reversing = False
        self.when_handlers = []
        self.setup_builtins()
        self.file_sections = {}
        self.current_file = None
        self.source_lines = source_lines or []
        self.filename = filename or '<stdin>'
        self._exports = {}
        self.async_tasks = []

    def setup_builtins(self):
        builtins = {
            'print': lambda *args: sys.stdout.buffer.write(' '.join(self.gom_str(a) for a in args).encode(sys.stdout.encoding or 'utf-8', errors='replace')),
            'println': lambda *args: print(*(self.gom_str(a) for a in args)),
            'len': lambda x: len(x) if isinstance(x, (list, str, dict)) else 0,
            'push': lambda arr, val: (arr.append(val), arr)[1] if isinstance(arr, list) else None,
            'pop': lambda arr: arr.pop() if isinstance(arr, list) else None,
            'type': lambda x: type(x).__name__,
            'random': lambda: random.random(),
            'now': lambda: time.time(),
            'input': lambda prompt='': input(self.gom_str(prompt) if prompt else ''),
            'int': lambda x: int(x) if x is not None else 0,
            'str': lambda x: self.gom_str(x),
            'use': lambda initial=None: self.make_signal(initial),
        }
        for name, func in builtins.items():
            self.env.define(name, func, VarType.CONST_CONST, 1)

        # Date namespace object
        class DateObj:
            @staticmethod
            def now():
                return time.time()
        self.env.define('Date', DateObj, VarType.CONST_CONST, 1)

        # Signal state
        self.signal_counter = 0

    def make_signal(self, initial):
        value = [initial]  # box it
        def signal(*args):
            nonlocal value
            if len(args) == 1:
                value[0] = args[0]
            return value[0]
        return signal

    def check_deleted(self, val):
        if isinstance(val, (int, float)) and ('number', type(val)(val)) in self.deleted:
            raise GomError(f"{val} has been deleted")
        if isinstance(val, str) and ('string', val) in self.deleted:
            raise GomError(f"'{val}' has been deleted")
        if isinstance(val, bool) and ('bool', val) in self.deleted:
            raise GomError(f"{val} has been deleted")

    def gom_str(self, val):
        if val is UNDEFINED:
            return 'undefined'
        if val is DELETED:
            return 'deleted'
        if val is True:
            return 'true'
        if val is False:
            return 'false'
        if val == 'maybe':
            return 'maybe'
        if isinstance(val, float) and math.isinf(val):
            return 'Infinity'
        return str(val)

    def interpolate(self, s):
        """Handle ${name}, £{name}, ¥{name}, {name}€, {name$key} interpolation."""
        import re
        def repl_currency(m):
            expr = m.group(1) or m.group(2) or m.group(3)
            try:
                tokens = tokenize(expr)
                parser = Parser(tokens)
                ast = parser.parse_expression()
                val = self.evaluate(ast)
                return self.gom_str(val)
            except:
                return m.group(0)
        # ${expr} and £{expr} and ¥{expr}
        s = re.sub(r'[$£¥]\{([^}]+)\}', repl_currency, s)
        # {expr}€ (Cape Verdean escudo style)
        s = re.sub(r'\{([^}]+)\}€', repl_currency, s)
        # {name$key} style
        s = re.sub(r'\{([^}$]+)\$([^}]+)\}', repl_currency, s)
        return s

    def run(self, program):
        results = []
        stmts = program.statements if isinstance(program, Program) else program
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, ReverseStmt):
                self._reversing = True
                for prev in reversed(stmts[:i]):
                    r = self.evaluate(prev)
                    if r is not None:
                        results.append(r)
                self._reversing = False
                continue
            r = self.evaluate(stmt)
            self._expire_line_lifetimes()
            if r is not None:
                results.append(r)
        return results[-1] if results else None

    def _expire_line_lifetimes(self):
        """Decrement line-based lifetimes after each statement."""
        expired = []
        for name, entry in self.env.vars.items():
            if entry.lifetime is not None and entry.lifetime != 'Infinity':
                if isinstance(entry.lifetime, int) and entry.lifetime > 0:
                    entry.lifetime -= 1
                    if entry.lifetime <= 0:
                        expired.append(name)
        for name in expired:
            del self.env.vars[name]

    def evaluate(self, node, is_when_check=False):
        if isinstance(node, ExprStmt):
            val = self.evaluate(node.expr, is_when_check)
            # Handle export/import markers
            if isinstance(val, tuple) and len(val) >= 2:
                if val[0] == '__export__':
                    _, name, target = val
                    self._exports[name] = target
                elif val[0] == '__import__':
                    _, name = val
                    src = self._exports.get(name)
                    if src:
                        entry = self.env.lookup(name)
                        if not entry:
                            self.env.define(name, src, VarType.CONST_VAR, 1)
            if node.bang_count > 0 and val is not None:
                pass
            return val

        if isinstance(node, DebugStmt):
            val = self.evaluate(node.expr)
            print(f"[debug] {self.gom_str(val)}", file=sys.stderr)
            return val

        if isinstance(node, Decl):
            if node.name == '__destructure__':
                # Destructuring assignment
                names, expr_val = self.evaluate(node.value)
                sig_val = self.evaluate(expr_val)
                if callable(sig_val) and not isinstance(sig_val, GomFunction):
                    # Signal: split into getter/setter
                    getter = lambda: sig_val()
                    setter = lambda v: sig_val(v)
                    if len(names) >= 1:
                        self.env.define(names[0], getter, VarType.CONST_VAR, 1)
                    if len(names) >= 2:
                        self.env.define(names[1], setter, VarType.CONST_VAR, 1)
                elif isinstance(sig_val, (list, tuple)):
                    for i, n in enumerate(names):
                        if i < len(sig_val):
                            self.env.define(n, sig_val[i], node.constancy, node.bang_count)
                return sig_val
            val = self.evaluate(node.value)
            lifetime = node.lifetime
            if lifetime is not None and lifetime != 'Infinity':
                if isinstance(lifetime, (int, float)):
                    if isinstance(lifetime, float):
                        lifetime = time.time() + lifetime
            if node.constancy == VarType.CONST_CONST_CONST:
                entry = self.env.lookup(node.name)
                if entry:
                    raise GomError(f"const const const '{node.name}' already set globally!")
                self.env.define(node.name, val, node.constancy, node.bang_count, lifetime)
            else:
                self.env.define(node.name, val, node.constancy, node.bang_count, lifetime)
            return val

        if isinstance(node, Assign):
            val = self.evaluate(node.value)
            if isinstance(node.target, Identifier):
                self.env.set(node.target.name, val)
            elif isinstance(node.target, IndexExpr):
                obj = self.evaluate(node.target.obj)
                idx = self.evaluate(node.target.index)
                if isinstance(obj, list):
                    ri = self.resolve_index(obj, idx)
                    if isinstance(ri, tuple) and ri[0] == 'insert':
                        obj.insert(ri[1], val)
                    else:
                        obj[ri] = val
                elif isinstance(obj, dict):
                    obj[idx] = val
            return val

        if isinstance(node, BinaryOp):
            return self.eval_binary(node)

        if isinstance(node, UnaryOp):
            return self.eval_unary(node)

        if isinstance(node, Literal):
            val = node.value
            self.check_deleted(val)
            if isinstance(val, str) and ('${' in val or '£{' in val or '¥{' in val or '}€' in val):
                val = self.interpolate(val)
            return val

        if isinstance(node, Identifier):
            name = node.name
            # Check number names
            if name in NUMBER_NAMES:
                return NUMBER_NAMES[name]
            # Check if it's a bare string (not found in env)
            entry = self.env.lookup(name)
            if entry is None:
                return name  # zero-quote string!
            if entry.value is DELETED:
                raise GomError(f"'{name}' has been deleted")
            if entry.type == VarType.CONST_CONST_CONST:
                pass
            return entry.value

        if isinstance(node, ArrayLit):
            return GomArray(self.evaluate(e) for e in node.elements)

        if isinstance(node, IndexExpr):
            obj = self.evaluate(node.obj)
            idx = self.evaluate(node.index)
            if isinstance(idx, str):
                # Method/property access via dot
                if isinstance(obj, list):
                    if idx == 'push':
                        return lambda *a: (obj.append(a[0]), obj)[1] if a else obj
                    if idx == 'length':
                        return len(obj)
                    return getattr(obj, idx, UNDEFINED)
                if isinstance(obj, str):
                    if idx == 'push':
                        return lambda s: obj + s
                    return getattr(obj, idx, UNDEFINED)
                if isinstance(obj, dict):
                    return obj.get(idx, UNDEFINED)
                if hasattr(obj, idx):
                    return getattr(obj, idx)
                return UNDEFINED
            # Numeric index
            if isinstance(obj, list):
                return obj[self.resolve_index(obj, idx)]
            if isinstance(obj, str):
                return obj[self.resolve_index(list(range(len(obj))), idx)]
            if isinstance(obj, dict):
                return obj.get(idx, UNDEFINED)
            return getattr(obj, str(idx), UNDEFINED)

        if isinstance(node, CallExpr):
            return self.eval_call(node)

        if isinstance(node, FuncDef):
            func = GomFunction(node.name, node.params, node.body, self.env, node.func_type)
            self.env.define(node.name, func, VarType.CONST_CONST, 1)
            return func

        if isinstance(node, IncExpr):
            entry = self.env.lookup(node.name)
            if entry and entry.type in (VarType.VAR_VAR, VarType.CONST_VAR):
                self.env._record_previous(node.name)
                old = entry.value
                new = old + node.delta if isinstance(old, (int, float)) else old
                entry.value = new
                for w in entry.watches:
                    w(node.name, old, new)
                return new
            raise GomError(f"'{node.name}' cannot be incremented")

        if isinstance(node, Lambda):
            return GomFunction('', node.params, node.body, self.env, 'function')

        if isinstance(node, IfStmt):
            cond = self.evaluate(node.condition)
            if self.is_truthy(cond):
                return self.run(node.then_block)
            elif node.else_block:
                return self.run(node.else_block)
            return None

        if isinstance(node, WhenStmt):
            cond = node.condition
            body = node.body
            
            # Detect if this is a loop-style when (e.g., when (i < n))
            is_loop = False
            if isinstance(cond, BinaryOp) and cond.op in ('<', '>', '<=', '>=', '!=', '==', '===', '===='):
                is_loop = True
                # Loop-style: re-check condition in a loop
                max_iter = 10000
                iterations = 0
                while iterations < max_iter:
                    result = self.evaluate(cond)
                    if self.is_truthy(result):
                        self.run(body)
                        iterations += 1
                    else:
                        break
            
            if not is_loop:
                # Reactive watcher style
                watched_var = None
                expected_val = None
                if isinstance(cond, BinaryOp) and isinstance(cond.left, Identifier):
                    watched_var = cond.left.name
                    expected_val = self.evaluate(cond.right)
                elif isinstance(cond, Assign) and isinstance(cond.target, Identifier):
                    watched_var = cond.target.name
                    expected_val = self.evaluate(cond.value)

                if watched_var:
                    entry = self.env.lookup(watched_var)
                    if entry:
                        def handler(name, old, new):
                            try:
                                if new == expected_val:
                                    self.run(body)
                            except:
                                pass
                        entry.watches.append(handler)
            return None

        if isinstance(node, DeleteStmt):
            target = node.target
            if isinstance(target, str):
                # Delete from environment or global
                if isinstance(target, str) and target in ('class', 'function', 'if', 'else', 'while',
                    'for', 'const', 'var', 'delete', 'return', 'true', 'false', 'undefined', 'Infinity'):
                    self.deleted.add(target)
                    return None
                # Try to delete a value
                entry = self.env.lookup(target)
                if entry:
                    entry.value = DELETED
                    return None
                val = None
            else:
                val = self.evaluate(target) if not isinstance(target, (str, int, float, bool)) else target
            
            if isinstance(val, (int, float, str, bool)):
                if isinstance(val, (int, float)):
                    self.deleted.add(('number', val))
                elif isinstance(val, str):
                    self.deleted.add(('string', val))
                elif isinstance(val, bool):
                    self.deleted.add(('bool', val))
            return None

        if isinstance(node, ReturnStmt):
            val = self.evaluate(node.value) if node.value else None
            raise ReturnException(val)

        if isinstance(node, NoopStmt):
            return None

        if isinstance(node, ReverseStmt):
            return None

        if isinstance(node, ClassDef):
            cls = GomClass(node.name, node.methods, node.body, self)
            self.env.define(node.name, cls, VarType.CONST_CONST, 1)
            return cls

        if isinstance(node, NewExpr):
            entry = self.env.lookup(node.class_name)
            if entry is None:
                raise GomError(f"Class '{node.class_name}' not found")
            cls = entry.value
            if isinstance(cls, GomClass):
                instance = cls.instantiate()
                return instance
            raise GomError(f"'{node.class_name}' is not a class")

        if isinstance(node, PreviousExpr):
            expr = self.evaluate(node.expr)
            if isinstance(node.expr, Identifier):
                prev = self.env.get_previous(node.expr.name)
                return prev if prev is not None else expr
            return expr

        if isinstance(node, NextExpr):
            return UNDEFINED

        if isinstance(node, CurrentExpr):
            return self.evaluate(node.expr)

        if isinstance(node, AwaitExpr):
            return self.evaluate(node.expr)

        if isinstance(node, Block):
            return self.run(node.statements)

        raise GomError(f"Unknown node type: {type(node).__name__}")

    def evaluate_reverse(self, node):
        """Evaluate in reverse order."""
        return self.evaluate(node)  # Simplified

    def is_truthy(self, val):
        if val is UNDEFINED or val is DELETED:
            return False
        if val == 'maybe':
            return random.choice([True, False])
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return len(val) > 0
        if isinstance(val, (list, dict)):
            return len(val) > 0
        return True

    def resolve_index(self, arr, idx):
        """Gulf of Mexico array indexing: arr[-1] is first element, arr[0] is second, etc."""
        if isinstance(idx, float) and idx != int(idx):
            return ('insert', int(idx) + 1)
        if isinstance(idx, int) or (isinstance(idx, float) and idx == int(idx)):
            idx = int(idx)
            return idx + 1  # -1 -> 0, 0 -> 1, 1 -> 2, etc.
        return idx

    def eval_binary(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        self.check_deleted(left)
        self.check_deleted(right)

        result = UNDEFINED
        if node.op == '+':
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                result = left + right
            else:
                result = self.gom_str(left) + self.gom_str(right)
        elif node.op == '-':
            result = left - right
        elif node.op == '*':
            result = left * right
        elif node.op == '/':
            if isinstance(right, (int, float)) and right == 0:
                return UNDEFINED
            result = left / right
        elif node.op == '%':
            result = left % right
        elif node.op == '^':
            result = left ** right
        elif node.op == '|':
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                result = int(left) | int(right)
            else:
                result = left | right if isinstance(left, int) and isinstance(right, int) else UNDEFINED
        elif node.op == '==':
            return self.gom_str(left) == self.gom_str(right)
        elif node.op == '===':
            return left == right
        elif node.op == '====':
            return left is right
        elif node.op == '=':
            return self.is_truthy(left) == self.is_truthy(right)
        elif node.op == '>':
            result = left > right
        elif node.op == '<':
            result = left < right
        elif node.op == '>=':
            result = left >= right
        elif node.op == '<=':
            result = left <= right
        elif node.op == '&&':
            return self.is_truthy(left) and self.is_truthy(right)
        elif node.op == '||':
            return self.is_truthy(left) or self.is_truthy(right)
        
        self.check_deleted(result)
        return result

    def eval_unary(self, node):
        if node.op == '-':
            val = self.evaluate(node.operand)
            return -val if isinstance(val, (int, float)) else UNDEFINED
        if node.op == '!':
            val = self.evaluate(node.operand)
            return not self.is_truthy(val)
        return UNDEFINED

    def eval_call(self, node):
        # Detect obj.push(x) pattern for in-place mutation
        if isinstance(node.callee, IndexExpr) and isinstance(node.callee.index, Literal) and node.callee.index.value == 'push' and isinstance(node.callee.obj, Identifier):
            target_name = node.callee.obj.name
            obj = self.evaluate(node.callee.obj)
            args = [self.evaluate(a) for a in node.args]
            if isinstance(obj, str) and args:
                def mutator(old):
                    return old + str(args[0])
                self.env.mutate(target_name, mutator)
                return mutator(obj)
        callee = self.evaluate(node.callee)
        args = [self.evaluate(a) for a in node.args]

        if isinstance(callee, GomFunction):
            return callee(self, args)

        if callable(callee):
            try:
                return callee(*args)
            except Exception as e:
                import traceback
                traceback.print_exc()
                raise GomError(f"Error calling function: {e}")

        raise GomError(f"'{callee}' is not callable")

# ============================================================
# REPL
# ============================================================

def format_gom_error(e, source_lines, filename='<stdin>'):
    """Format an error as a proper GoM error message."""
    if isinstance(e, GomError):
        return str(e)
    if isinstance(e, SyntaxError):
        line = getattr(e, 'lineno', 0) or 0
        msg = str(e)
        if source_lines and 0 < line <= len(source_lines):
            return f"GulfOfMexico.SyntaxError at line {line}\n  --> {source_lines[line - 1].rstrip()}\nError: {msg}"
        return f"GulfOfMexico.SyntaxError: {msg}"
    return f"GulfOfMexico.InternalError: {e}"

def run_repl():
    interp = Interpreter(source_lines=["<REPL>"])
    print("Gulf of Mexico v1.0 — A Perfect Programming Language")
    print("Type 'exit' to quit")
    print()
    while True:
        try:
            line = input("GoM> ")
            if line.strip() == 'exit':
                break
            if not line.strip():
                continue
            tokens = tokenize(line)
            parser = Parser(tokens)
            prog = parser.parse_program()
            result = interp.run(prog)
            if result is not None:
                print(f"=> {interp.gom_str(result)}")
        except GomError as e:
            print(str(e), file=sys.stderr)
        except SyntaxError as e:
            print(f"GulfOfMexico.SyntaxError: {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print()
            break
        except EOFError:
            break
        except Exception as e:
            print(f"GulfOfMexico.InternalError: {e}", file=sys.stderr)
            if '--debug' in sys.argv:
                traceback.print_exc()

def run_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        print(f"GulfOfMexico.Error: File not found — '{filename}'", file=sys.stderr)
        sys.exit(1)

    source_lines = text.split('\n')
    
    # Handle multi-file sections
    sections = re.split(r'\n={5,}([^=\n]*)\n', text)
    interp = Interpreter(source_lines=source_lines, filename=filename)
    
    try:
        if len(sections) > 1:
            if sections[0].strip():
                tokens = tokenize(sections[0])
                parser = Parser(tokens)
                prog = parser.parse_program()
                interp.run(prog)
            for i in range(1, len(sections), 2):
                if i + 1 < len(sections):
                    fname = sections[i].strip()
                    content = sections[i + 1]
                    if content.strip():
                        tokens = tokenize(content)
                        parser = Parser(tokens)
                        prog = parser.parse_program()
                        interp.run(prog)
        else:
            tokens = tokenize(text)
            parser = Parser(tokens)
            prog = parser.parse_program()
            interp.run(prog)
    except GomError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except SyntaxError as e:
        print(f"GulfOfMexico.SyntaxError: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"GulfOfMexico.InternalError: {e}", file=sys.stderr)
        if '--debug' in sys.argv:
            traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        run_file(sys.argv[1])
    else:
        run_repl()
