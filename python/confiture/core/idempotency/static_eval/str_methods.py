"""The whitelisted pure ``str`` methods and f-strings the evaluator can fold."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from confiture.core.idempotency.static_eval.scope import _Context, _Scope
from confiture.core.idempotency.static_eval.values import Refusal, Seq, Str, Unknown, Value

if TYPE_CHECKING:
    from confiture.core.idempotency.static_eval.evaluator import ModuleModel


def _apply_str_method(
    method: str, text: str, args: list[Value], kwargs: dict[str, str], count: int | None
) -> tuple[str, bool] | Unknown:
    """``text.<method>(*args, **kwargs)`` for the whitelisted methods.

    Returns:
        ``(result, any argument was an f-string)`` or the refusal.
    """
    if method == "join":
        return _join(text, args, kwargs)
    texts: list[str] = []
    fstring = False
    for value in args:
        if not isinstance(value, Str):
            return Unknown(Refusal.UNSUPPORTED_CALL, f"`.{method}()` argument is not a string")
        texts.append(value.text)
        fstring = fstring or value.is_fstring
    try:
        if method == "replace":
            if len(texts) != 2:
                return Unknown(Refusal.UNSUPPORTED_CALL, "`.replace()` takes two strings")
            result = (
                text.replace(texts[0], texts[1])
                if count is None
                else text.replace(texts[0], texts[1], count)
            )
        elif method in {"strip", "lstrip", "rstrip"}:
            if len(texts) > 1 or kwargs:
                return Unknown(Refusal.UNSUPPORTED_CALL, f"`.{method}()` takes at most one string")
            result = getattr(text, method)(*texts)
        elif method in {"upper", "lower"}:
            if texts or kwargs:
                return Unknown(Refusal.UNSUPPORTED_CALL, f"`.{method}()` takes no arguments")
            result = getattr(text, method)()
        else:  # format
            result = text.format(*texts, **kwargs)
    except (IndexError, KeyError, ValueError) as exc:
        return Unknown(
            Refusal.UNSUPPORTED_CALL, f"`.{method}()` arguments do not fit the template: {exc}"
        )
    return result, fstring


def _join(text: str, args: list[Value], kwargs: dict[str, str]) -> tuple[str, bool] | Unknown:
    if len(args) != 1 or kwargs or not isinstance(args[0], Seq):
        return Unknown(Refusal.UNSUPPORTED_CALL, "`.join()` needs one static sequence of strings")
    parts: list[str] = []
    fstring = False
    for item in args[0].items:
        if not isinstance(item, Str):
            return Unknown(Refusal.UNSUPPORTED_CALL, "`.join()` sequence holds a non-string")
        parts.append(item.text)
        fstring = fstring or item.is_fstring
    return text.join(parts), fstring


class _StrMethodsMixin:
    """Methods :class:`~confiture.core.idempotency.static_eval.evaluator.ModuleModel` mixes in."""

    def _eval_fstring(
        self: ModuleModel, node: ast.JoinedStr, scope: _Scope, ctx: _Context
    ) -> Value:
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if not isinstance(value, ast.FormattedValue):
                return Unknown(Refusal.UNSUPPORTED, "unexpected f-string part", hint="fstring")
            placeholder = ast.unparse(value.value)
            if value.conversion != -1 or value.format_spec is not None:
                conversion = f"!{chr(value.conversion)}" if value.conversion != -1 else ""
                spec = f":{ast.unparse(value.format_spec)}" if value.format_spec is not None else ""
                return Unknown(
                    Refusal.FSTRING_FORMAT,
                    f"f-string placeholder `{{{placeholder}{conversion}{spec}}}` uses a "
                    "conversion or format spec",
                    hint="fstring",
                )
            inner = self._eval(value.value, scope, ctx)
            if isinstance(inner, Unknown):
                return Unknown(
                    Refusal.FSTRING_DYNAMIC,
                    f"f-string interpolates `{placeholder}`, which is not static: {inner.reason}",
                    hint="fstring",
                )
            if not isinstance(inner, Str):
                return Unknown(
                    Refusal.FSTRING_DYNAMIC,
                    f"f-string interpolates `{placeholder}`, which is not a string",
                    hint="fstring",
                )
            parts.append(inner.text)
        return Str("".join(parts), is_fstring=True)

    def _eval_str_method(
        self: ModuleModel, node: ast.Call, func: ast.Attribute, scope: _Scope, ctx: _Context
    ) -> Value:
        """A whitelisted ``str`` method with static arguments."""
        method = func.attr
        receiver = self._eval(func.value, scope, ctx)
        if isinstance(receiver, Unknown):
            return receiver
        if not isinstance(receiver, Str):
            return Unknown(
                Refusal.UNSUPPORTED_CALL, f"`.{method}()` on something that is not a string"
            )
        arguments = self._str_method_arguments(node, method, scope, ctx)
        if isinstance(arguments, Unknown):
            return arguments
        args, kwargs, count = arguments
        applied = _apply_str_method(method, receiver.text, args, kwargs, count)
        if isinstance(applied, Unknown):
            return applied
        result, fstring = applied
        return Str(result, receiver.from_file, receiver.is_fstring or fstring)

    def _str_method_arguments(
        self: ModuleModel, node: ast.Call, method: str, scope: _Scope, ctx: _Context
    ) -> tuple[list[Value], dict[str, str], int | None] | Unknown:
        """The call's positional values (starred sequences spread), string keywords, and
        ``.replace()``'s count literal."""
        count: int | None = None
        positional = list(node.args)
        if method == "replace" and len(positional) == 3:
            third = positional.pop()
            if not (isinstance(third, ast.Constant) and isinstance(third.value, int)):
                return Unknown(Refusal.UNSUPPORTED_CALL, "`.replace()` count is not an int literal")
            count = third.value
        args: list[Value] = []
        for arg in positional:
            if isinstance(arg, ast.Starred):
                inner = self._eval(arg.value, scope, ctx)
                if isinstance(inner, Unknown):
                    return inner
                if not isinstance(inner, Seq):
                    return Unknown(Refusal.UNSUPPORTED, "`*` on something that is not a sequence")
                args.extend(inner.items)
                continue
            value = self._eval(arg, scope, ctx)
            if isinstance(value, Unknown):
                return value
            args.append(value)
        kwargs: dict[str, str] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                return Unknown(Refusal.UNSUPPORTED_CALL, f"`.{method}(**...)` is not static")
            value = self._eval(keyword.value, scope, ctx)
            if isinstance(value, Unknown):
                return value
            if not isinstance(value, Str):
                return Unknown(
                    Refusal.UNSUPPORTED_CALL,
                    f"`.{method}()` keyword `{keyword.arg}` is not a string",
                )
            kwargs[keyword.arg] = value.text
        return args, kwargs, count
