from __future__ import annotations
from typing import Never, Iterator, Callable, Type, Tuple
from enum import Enum
import enum
from pathlib import Path
import json
import unittest

type Value = dict[str, Value] | list[Value] | str | int | float | bool | None


class Any:
	path: list[str | int]
	value: Value

	def __init__(self, value: Value, path: list[str | int] | None = None) -> None:
		self.path = [] if path is None else path
		self.value = value

	@staticmethod
	def from_json(input: str | bytes | bytearray) -> "Any":
		return Any(json.loads(input))

	@staticmethod
	def from_file(path: str | Path) -> "Any":
		with open(path, "r") as f:
			return Any(json.load(f))

	def error(self, msg: str) -> Never:
		if len(self.path) == 0:
			path = "root"
		else:
			path = ""
			for component in self.path:
				if isinstance(component, str):
					path += f".{component}"
				else:
					path += f"[{component}]"
		raise Exception(f"error at {path}: {msg}")

	def object(self) -> "Object":
		if not isinstance(self.value, dict):
			self.error("expected object")
		return Object(self.value, path=self.path)

	def list(self) -> "List":
		if not isinstance(self.value, list):
			self.error("expected list")
		return List(self.value, path=self.path)

	def str(self) -> "Str":
		if not isinstance(self.value, str):
			self.error("expected str")
		return Str(self.value, path=self.path)

	def int(self) -> "Int":
		if not isinstance(self.value, int):
			self.error("expected integer")
		return Int(self.value, path=self.path)

	def float(self) -> "Float":
		if not isinstance(self.value, float):
			self.error("expected floating-point number")
		return Float(self.value, path=self.path)

	def bool(self) -> bool:
		if not isinstance(self.value, bool):
			self.error("expected boolean")
		return self.value

	def null(self) -> None:
		if self.value is not None:
			self.error("expected null")

	def enum[T: Enum](self, enum: Type[T]) -> T:
		if not isinstance(self.value, str) or self.value not in enum.__members__:
			self.error(f"expected one of {', '.join(enum.__members__.keys())}")
		return enum[self.value]


class Object(Any):
	value: dict[str, Value]

	def get(self, key: str) -> Any:
		if key not in self.value:
			self.error(f"expected key {key}")
		value = self.value[key]
		del self.value[key]
		return Any(value, path=[*self.path, key])

	def deny_unknown(self) -> None:
		if len(self.value) == 0:
			return
		self.error(f"unexpected key {next(self.value.__iter__())}")


class List(Any):
	value: list[Value]

	def __iter__(self) -> Iterator[Any]:
		for i in range(len(self.value)):
			yield self.get(i)

	def nonempty(self) -> "List":
		self.get(0)
		return self

	def get(self, i: int) -> Any:
		if i < 0:
			raise Exception("attempted to index with negative integer")
		if i >= len(self.value):
			self.error(f"expected at least {i + 1} element(s)")
		return Any(self.value[i], path=[*self.path, i])


class Str(Any):
	value: str

	def nonempty(self) -> str:
		if len(self.value) == 0:
			self.error(f"expected nonempty string")
		return self.value


class Int(Any):
	value: int

	def at_least(self, min: int) -> int:
		if self.value < min:
			self.error(f"expected integer that is at least {min}; found {self.value}")
		return self.value

	def between(self, min: int, max: int) -> int:
		if self.value < min or self.value > max:
			self.error(f"expected integer between {min} and {max}; found {self.value}")
		return self.value


class Float(Any):
	value: float


# This can’t actually be tested from within the workspace because unit tester tries to run
# `__init__.py`. So you have to symlink to this file from elsewhere and do it that way.
class Tests(unittest.TestCase):
	def error(self, json: str, f: Callable[[Any], object]) -> str:
		try:
			f(Any.from_json(json))
		except Exception as e:
			return str(e)
		raise Exception("unexpectedly succeeded")

	def test_root(self):
		self.assertEqual(
			self.error("[]", lambda c: c.object()), "error at root: expected object"
		)
		self.assertEqual(
			self.error("5", lambda c: c.object()), "error at root: expected object"
		)
		self.assertEqual(
			self.error("5.1", lambda c: c.int()), "error at root: expected integer"
		)

	def test_nested(self):
		self.assertEqual(
			self.error("[2, 3]", lambda c: c.list().get(0).float()),
			"error at [0]: expected floating-point number",
		)
		self.assertEqual(
			self.error('{"a":true}', lambda c: c.object().get("a").null()),
			"error at .a: expected null",
		)

	def test_deny_unknown(self):
		self.assertEqual(
			self.error('{"a":true}', lambda c: c.object().deny_unknown()),
			"error at root: unexpected key a",
		)

	def test_works(self):
		self.assertEqual(Any.from_json("[1, 2]").list().get(0).int().between(0, 4), 1)

	def test_enum(self):
		class Color(Enum):
			RED = enum.auto()
			GREEN = enum.auto()
			BLUE = enum.auto()

		self.assertEqual(Any.from_json('"RED"').enum(Color), Color.RED)


if __name__ == "__main__":
	unittest.main()
