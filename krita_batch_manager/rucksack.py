from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple
from enum import Enum
from pathlib import Path
import enum
import json

from . import json_cursor

class Rucksack:
	path: Path
	json_path: Path
	items: list[Item]

	def __init__(self, path: Path) -> None:
		self.path = path
		self.json_path = self.path / "rucksack.json"
		self.items = read(self.json_path)

	def layer_path(self, i: int) -> Path:
		return self.path / f"{i}.kra"

	def gen_layer_path(self) -> Tuple[int, Path]:
		for i in range(1024):
			path = self.layer_path(i)
			if path.exists(): continue
			return i, path
		raise Exception("could not find suitable layer path")

@dataclass
class Item:
	name: str
	data: ItemData

type ItemData = Layer | Vector | Text | LayerStyle

class ItemKind(Enum):
	LAYER = enum.auto()
	VECTOR = enum.auto()
	TEXT = enum.auto()
	LAYER_STYLE = enum.auto()

@dataclass
class Layer:
	filename: int
	def kind(self) -> ItemKind: return ItemKind.LAYER

@dataclass
class Vector:
	svg: str
	def kind(self) -> ItemKind: return ItemKind.VECTOR

@dataclass
class Text:
	svg: str
	def kind(self) -> ItemKind: return ItemKind.TEXT

@dataclass
class LayerStyle:
	asl: str
	def kind(self) -> ItemKind: return ItemKind.LAYER_STYLE

def read(path: Path) -> list[Item]:
	try:
		root = json_cursor.Any.from_file(path).object()
		c_items = root.get("items").list()
		root.deny_unknown()
		return [parse_item(c_item) for c_item in c_items]
	except FileNotFoundError:
		return []
	except Exception as e:
		raise Exception(f"failed to read JSON at {path}: {str(e)}")

def write(path: Path, items: list[Item]) -> None:
	data = { "items": [{ "name": item.name, "kind": format_item_data(item.data) } for item in items] }
	path.parent.mkdir(parents=True, exist_ok=True)
	with open(path, 'w') as f:
		json.dump(data, f)

def format_item_data(item: ItemData) -> json_cursor.Value:
	match item:
		case Layer(filename):
			return { "tag": "LAYER", "filename": filename }
		case Vector(svg):
			return { "tag": "VECTOR", "svg": svg }
		case Text(svg):
			return { "tag": "TEXT", "svg": svg }
		case LayerStyle(asl):
			return { "tag": "LAYER_STYLE", "asl": asl }

def parse_item(c_item: json_cursor.Any) -> Item:
	c_item = c_item.object()
	name = c_item.get("name").str().nonempty()
	c_kind = c_item.get("kind").object()
	c_item.deny_unknown()

	match c_kind.get("tag").enum(ItemKind):
		case ItemKind.LAYER:
			filename = c_kind.get("filename").int().at_least(0)
			c_kind.deny_unknown()
			return Item(name, Layer(filename))
		case ItemKind.VECTOR:
			svg = c_kind.get("svg").str().value
			c_kind.deny_unknown()
			return Item(name, Vector(svg))
		case ItemKind.TEXT:
			svg = c_kind.get("svg").str().value
			c_kind.deny_unknown()
			return Item(name, Text(svg))
		case ItemKind.LAYER_STYLE:
			asl = c_kind.get("asl").str().value
			c_kind.deny_unknown()
			return Item(name, LayerStyle(asl))
