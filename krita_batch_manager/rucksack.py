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

	def node_path(self, i: int) -> Path:
		return self.path / f"{i}.kra"

	def gen_layer_path(self) -> Tuple[int, Path]:
		for i in range(1024):
			path = self.node_path(i)
			if path.exists():
				continue
			return i, path
		raise Exception("could not find suitable layer path")


@dataclass
class Item:
	name: str
	data: ItemData


type ItemData = Node | Vector | LayerStyle


@dataclass
class Node:
	filename: int
	kind: NodeKind


class NodeKind(Enum):
	LAYER = enum.auto()
	LAYER_FILE = enum.auto()
	LAYER_FILL = enum.auto()
	LAYER_FILTER = enum.auto()
	LAYER_GROUP = enum.auto()
	LAYER_VECTOR = enum.auto()
	MASK_COLORIZE = enum.auto()
	MASK_FILTER = enum.auto()
	MASK_SELECTION = enum.auto()
	MASK_TRANSFORM = enum.auto()
	MASK_TRANSPARENCY = enum.auto()

	def is_mask(self) -> bool:
		match self:
			case (
				NodeKind.LAYER
				| NodeKind.LAYER_FILE
				| NodeKind.LAYER_FILL
				| NodeKind.LAYER_FILTER
				| NodeKind.LAYER_GROUP
				| NodeKind.LAYER_VECTOR
			):
				return False
			case (
				NodeKind.MASK_COLORIZE
				| NodeKind.MASK_FILTER
				| NodeKind.MASK_SELECTION
				| NodeKind.MASK_TRANSFORM
				| NodeKind.MASK_TRANSPARENCY
			):
				return True


@dataclass
class Vector:
	svg: str
	is_text: bool


@dataclass
class LayerStyle:
	asl: str


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
	data = {
		"items": [
			{"name": item.name, "kind": format_item_data(item.data)} for item in items
		]
	}
	path.parent.mkdir(parents=True, exist_ok=True)
	with open(path, "w") as f:
		json.dump(data, f)


class ItemKind(Enum):
	NODE = enum.auto()
	VECTOR = enum.auto()
	TEXT = enum.auto()
	LAYER_STYLE = enum.auto()


def format_item_data(item: ItemData) -> json_cursor.Value:
	match item:
		case Node(filename, kind):
			return {"tag": "NODE", "kind": item.kind.name, "filename": filename}
		case Vector(svg, is_text):
			return {"tag": "TEXT" if is_text else "VECTOR", "svg": svg}
		case LayerStyle(asl):
			return {"tag": "LAYER_STYLE", "asl": asl}


def parse_item(c_item: json_cursor.Any) -> Item:
	c_item = c_item.object()
	name = c_item.get("name").str().nonempty()
	c_kind = c_item.get("kind").object()
	c_item.deny_unknown()

	match c_kind.get("tag").enum(ItemKind):
		case ItemKind.NODE:
			filename = c_kind.get("filename").int().at_least(0)
			kind = c_kind.get("kind").enum(NodeKind)
			c_kind.deny_unknown()
			return Item(name, Node(filename, kind))
		case ItemKind.VECTOR:
			svg = c_kind.get("svg").str().value
			c_kind.deny_unknown()
			return Item(name, Vector(svg, is_text=False))
		case ItemKind.TEXT:
			svg = c_kind.get("svg").str().value
			c_kind.deny_unknown()
			return Item(name, Vector(svg, is_text=True))
		case ItemKind.LAYER_STYLE:
			asl = c_kind.get("asl").str().value
			c_kind.deny_unknown()
			return Item(name, LayerStyle(asl))
