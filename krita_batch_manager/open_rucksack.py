from __future__ import annotations

import enum
import errno
import html
import shutil
from enum import Enum
from pathlib import Path

import krita
from krita import Krita
from PyQt5.QtCore import QPoint, QPointF, Qt, QTimer, pyqtSignal, qInfo, qWarning
from PyQt5.QtGui import (
	QKeyEvent,
	QMouseEvent,
	QPainter,
	QPaintEvent,
	QPalette,
	QTransform,
)
from PyQt5.QtWidgets import (
	QApplication,
	QDialog,
	QDockWidget,
	QHBoxLayout,
	QLabel,
	QLineEdit,
	QMainWindow,
	QMenu,
	QOpenGLWidget,
	QPushButton,
	QStyle,
	QStyleOption,
	QTabWidget,
	QTextEdit,
	QToolButton,
	QVBoxLayout,
	QWidget,
)

from . import rucksack
from .rucksack import Rucksack


def run(kr: Krita) -> None:
	try:
		Driver(kr)
	except IgnoredException:
		pass


class IgnoredException(Exception):
	pass


class Driver:
	kr: Krita
	view: krita.View
	doc: krita.Document
	active_node: krita.Node
	qwin: QMainWindow

	global_: Rucksack
	local: Rucksack | None

	possible_saves: list[tuple[rucksack.ItemData, bool]]

	dialog: Dialog

	def __init__(self, kr: Krita) -> None:
		super().__init__()

		self.kr = kr

		if (win := kr.activeWindow()) is None:
			qWarning("no active window")
			raise IgnoredException
		self.win = win

		if (view := win.activeView()) is None:
			qWarning("no active view")
			raise IgnoredException
		self.view = view

		if (doc := kr.activeDocument()) is None:
			self.error("no active document")
			raise IgnoredException
		self.doc = doc

		if (active_node := doc.activeNode()) is None:
			self.error("no active node")
			raise IgnoredException
		self.active_node = active_node

		if (qwin := win.qwindow()) is None:
			self.error("no qwin")
			raise IgnoredException
		self.qwin = qwin

		try:
			self.global_ = Rucksack(Path(kr.getAppDataLocation()) / "rucksack")
			self.local = None
			if doc.fileName():
				file_path = Path(doc.fileName())
				found = None
				for parent in file_path.parents:
					path = parent / "krita-rucksack"
					if path.exists():
						found = path
						break
				self.local = Rucksack(
					found
					if found is not None
					else (file_path.parent / "krita-rucksack")
				)
		except Exception as e:
			self.error(str(e))
			raise IgnoredException

		# `filename` is a placeholder; it will be filled in later.
		save_item_node = rucksack.Node(filename=0, kind=node_kind_of_node(active_node))
		self.possible_saves = [(save_item_node, True)]

		shapes_svg = ""
		is_text = False
		if isinstance(active_node, krita.VectorLayer):
			for shape in active_node.shapes():
				if not shape.isSelected():
					continue

				old_transform = shape.transformation()
				t = shape.absoluteTransformation()
				try:
					shape.setTransformation(t)
					svg = shape.toSvg()
				finally:
					shape.setTransformation(old_transform)

				shape_is_text = shape.type() == "KoSvgTextShapeID"
				# For some reason, `toSvg()` ignores text transforms. So we do it manually.
				# Note that this still doesn’t fix the case of text inside groups.
				# See: https://bugs.kde.org/show_bug.cgi?id=508361
				if shape_is_text:
					prefix = "<text "
					assert svg.startswith(prefix)
					new_svg = f'{prefix}transform="matrix('
					new_svg += f"{t.m11()} {t.m12()} "
					new_svg += f"{t.m21()} {t.m22()} "
					new_svg += f"{t.m31()} {t.m32()}"
					svg = new_svg + ')" ' + svg[len(prefix) :]
				is_text = not shapes_svg and shape_is_text
				shapes_svg += svg
		self.possible_saves.append(
			(rucksack.Vector(shapes_svg, is_text=False), bool(shapes_svg))
		)
		self.possible_saves.append(
			(rucksack.Vector(shapes_svg, is_text=True), bool(shapes_svg) and is_text)
		)

		layer_style = active_node.layerStyleToAsl()
		self.possible_saves.append(
			(rucksack.LayerStyle(layer_style), bool(layer_style))
		)

		self.dialog = Dialog(
			kr, allow_local=self.local is not None, possible_saves=self.possible_saves
		)
		self.update_item_list()
		self.dialog.add_new.connect(self.on_add_new)
		self.dialog.delete.connect(self.on_delete)
		self.dialog.rename.connect(self.on_rename)
		self.dialog.replace.connect(self.on_replace)
		self.dialog.refresh.connect(self.on_refresh)
		self.dialog.chosen.connect(self.on_chosen)
		self.dialog.exec()

	def update_item_list(self) -> None:
		local_items = self.local.items if self.local is not None else []
		self.dialog.set_items(self.global_.items, local_items)

	def at(self, location: Location) -> Rucksack:
		match location:
			case Location.GLOBAL:
				return self.global_
			case Location.LOCAL:
				assert self.local is not None
				return self.local

	def on_add_new(self, location: Location, name: str, save_i: int) -> bool:
		qInfo(f"adding new: {name}")

		target = self.at(location)
		data, _ = self.possible_saves[save_i]

		if isinstance(data, rucksack.Node):
			if (cloned := self.active_node.clone()) is None:
				self.error("could not clone current layer")
				return False
			node_kind = data.kind

			d = self.kr.createDocument(
				self.doc.width(),
				self.doc.height(),
				"",
				self.doc.colorModel(),
				self.doc.colorDepth(),
				self.doc.colorProfile(),
				self.doc.resolution(),
			)
			if d is None or (root_node := d.rootNode()) is None:
				self.error("could not create saved layer document")
				return False

			try:
				bg_node = d.topLevelNodes()[0]
				if not (bg_node if node_kind.is_mask() else root_node).addChildNode(
					cloned, None
				):
					self.error("could not add child node to saved layer document")
					return False
				if not node_kind.is_mask():
					bg_node.remove()
				i, path = target.gen_layer_path()
				try:
					path.parent.mkdir(parents=True, exist_ok=True)
				except Exception:
					pass
				if not d.saveAs(str(path)):
					self.error("could not save saved layer document")
					return False
				data = rucksack.Node(i, node_kind)
			finally:
				d.close()

		new_items = [*target.items, rucksack.Item(name, data)]
		try:
			rucksack.write(target.json_path, new_items)
		except Exception as e:
			self.error(str(e))
			return False
		target.items = new_items
		self.update_item_list()

		return True

	def on_delete(self, location: Location, i: int) -> None:
		target = self.at(location)
		item = target.items[i]
		qInfo(f"deleting {item.name}")

		new_items = [*target.items[:i], *target.items[i + 1 :]]
		try:
			rucksack.write(target.json_path, new_items)
		except Exception as e:
			self.error(str(e))
			return
		target.items = new_items
		self.update_item_list()

		if isinstance(item.data, rucksack.Node):
			path = target.node_path(item.data.filename)
			try:
				path.unlink(missing_ok=True)
			except Exception as e:
				self.error(str(e))
				return

	def on_rename(
		self, location: Location, i: int, new_location: Location, name: str
	) -> None:
		src_rucksack = self.at(location)
		item_data = src_rucksack.items[i].data

		qInfo(f"renaming {src_rucksack.items[i].name} to {name}")
		if location == new_location:
			new_items = [
				*src_rucksack.items[:i],
				rucksack.Item(name, item_data),
				*src_rucksack.items[i + 1 :],
			]
			try:
				rucksack.write(src_rucksack.json_path, new_items)
			except Exception as e:
				self.error(str(e))
				return
			src_rucksack.items = new_items
			self.update_item_list()
			return

		new_rucksack = self.at(new_location)

		if isinstance(item_data, rucksack.Node):
			src_path = src_rucksack.node_path(item_data.filename)
			j, dst_path = new_rucksack.gen_layer_path()
			try:
				dst_path.parent.mkdir(parents=True, exist_ok=True)
				try:
					dst_path.hardlink_to(src_path)
				except OSError as e:
					if e.errno != errno.EXDEV:
						raise e
					shutil.copy(src_path, dst_path)
			except Exception as e:
				self.error(str(e))
				return
			item_data = rucksack.Node(j, item_data.kind)

		new_items = [*new_rucksack.items, rucksack.Item(name, item_data)]
		try:
			rucksack.write(new_rucksack.json_path, new_items)
		except Exception as e:
			self.error(str(e))
			return
		new_rucksack.items = new_items

		self.on_delete(location, i)

	def on_replace(self, location: Location, i: int, save_i: int) -> None:
		name = self.at(location).items[i].name
		if self.on_add_new(location, name, save_i):
			self.on_delete(location, i)

	def on_refresh(self, location: Location) -> None:
		qInfo("refreshing")
		target = self.at(location)
		try:
			target.items = rucksack.read(target.json_path)
		except Exception as e:
			self.error(str(e))
			return
		self.update_item_list()

	def on_chosen(self, location: Location, i: int) -> None:
		target = self.at(location)
		qInfo(f"chose {target.items[i].name}")
		match target.items[i].data:
			case rucksack.Node(filename, kind):
				self.insert_node(target.node_path(filename), kind.is_mask())
			case rucksack.Vector(svg, is_text):
				self.insert_svg(svg, is_text)
			case rucksack.LayerStyle(asl):
				# docs say it returns a bool, but it appears not to…
				self.active_node.setLayerStyleFromAsl(asl)

	def insert_node(self, path: Path, is_mask: bool) -> None:
		if (doc := self.kr.openDocument(str(path))) is None:
			self.error(f"could not open {path}")
			return

		try:
			if is_mask and len(doc.topLevelNodes()) != 1:
				self.error("saved mask file had wrong number of layers")
				return
			to_copy = (
				doc.topLevelNodes()[0].childNodes() if is_mask else doc.topLevelNodes()
			)
			if not to_copy:
				self.error("found no nodes to insert")
				return

			for node in to_copy:
				if (cloned_node := node.clone()) is None:
					self.error("could not clone node")
					return
				if not self.add_node_nearby(cloned_node):
					return
		finally:
			doc.close()

	def add_node_nearby(self, node: krita.Node) -> bool:
		active_is_mask = node_kind_of_node(self.active_node).is_mask()
		node_is_mask = node_kind_of_node(node).is_mask()
		qInfo(f"{active_is_mask}, {node_is_mask}")

		cursor = self.active_node
		previous = None
		for _ in range(int(active_is_mask) - int(node_is_mask) + 1):
			if (parent := cursor.parentNode()) is None:
				self.error("node has no parent")
				return False
			cursor, previous = parent, cursor
		return cursor.addChildNode(node, previous)

	def insert_svg(self, svg: str, is_text: bool) -> None:
		made_new_layer = False

		if isinstance(self.active_node, krita.VectorLayer):
			node = self.active_node
		elif is_text and (
			(text_node := self.doc.nodeByName("text")) is not None
			and isinstance(text_node, krita.VectorLayer)
		):
			node = text_node
		else:
			if (
				new_node := self.doc.createVectorLayer(
					"text" if is_text else "Vector layer"
				)
			) is None:
				self.error("could not make vector layer")
				return
			made_new_layer = True
			if not self.add_node_nearby(new_node):
				return
			node = new_node
		self.doc.setActiveNode(node)

		shapes = node.addShapesFromSvg(f"<svg>{svg}</svg>")

		# In `addShapesFromSvg`, Krita will automatically undo the effects of DPI, treating those
		# coordinates as pixels. But we want to treat them as points, so we redo the effect.
		scale = QTransform.fromScale(
			self.doc.resolution() / 72, self.doc.resolution() / 72
		)
		for shape in shapes:
			shape.setTransformation(shape.transformation() * scale)  # type: ignore[operator]

		shapes_bounding_box = None
		for shape in shapes:
			bounding_box = shape.boundingBox()
			if shapes_bounding_box is None:
				shapes_bounding_box = bounding_box
			else:
				shapes_bounding_box = shapes_bounding_box.united(bounding_box)
		assert shapes_bounding_box is not None

		# Find the centre of the canvas in points.
		# The documentation for these methods is very confusing. AFAICT:
		# - flakeToDocumentTransform applies zoom to screen pixels.
		# - flakeToCanvasTransform converts vector coordinates into pixels, but not taking into
		#   account zoom.
		t = (
			self.view.flakeToCanvasTransform().inverted()[0]
			* self.view.flakeToDocumentTransform()  # type: ignore[operator]
		)
		canvas = unwrap(unwrap(self.qwin.centralWidget()).findChild(QOpenGLWidget))
		centre = t.map(QPointF(canvas.width(), canvas.height()) / 2)

		# Centre the shapes to the centre of the canvas.
		offset = centre - shapes_bounding_box.center()
		for shape in shapes:
			shape.setPosition(shape.position() + offset)

		for s in node.shapes():
			s.deselect()
		for shape in shapes:
			shape.update()  # makes the object actually appear on canvas

		# Somehow, it doesn’t work otherwise.
		if made_new_layer:
			QTimer.singleShot(100, lambda: self.do_select(shapes))
		else:
			self.do_select(shapes)

		if is_text:
			# Open the “Edit Text” popup.
			unwrap(self.kr.action("SvgTextTool")).trigger()
			tool_docker = unwrap(self.qwin.findChild(QDockWidget, "sharedtooldocker"))
			unwrap(tool_docker.findChild(QPushButton)).click()
			QApplication.processEvents()  # wait for the window to open

			# Find the newly-created window, enter “Rich text” mode and focus the text field
			edit_text_win = QApplication.activeWindow()
			tabs = unwrap(edit_text_win.findChild(QTabWidget))
			tabs.setCurrentIndex(0)
			unwrap(tabs.widget(0).findChild(QTextEdit)).setFocus()

			# Select the contents of the text field by going through Edit → Select all.
			edit_menu = unwrap(edit_text_win.findChild(QMenu, "edit"))
			next(
				a for a in edit_menu.actions() if a.objectName() == "edit_select_all"
			).trigger()

	def do_select(self, shapes: list[krita.Shape]) -> None:
		for shape in shapes:
			shape.select()

	def error(self, msg: str) -> None:
		qWarning(msg)
		self.view.showFloatingMessage(msg, self.kr.icon("dialog-warning"), 2000, 1)


def node_kind_of_node(node: krita.Node) -> rucksack.NodeKind:
	if isinstance(node, krita.FileLayer):
		return rucksack.NodeKind.LAYER_FILE
	if isinstance(node, krita.FillLayer):
		return rucksack.NodeKind.LAYER_FILL
	if isinstance(node, krita.FilterLayer):
		return rucksack.NodeKind.LAYER_FILTER
	if isinstance(node, krita.GroupLayer):
		return rucksack.NodeKind.LAYER_GROUP
	if isinstance(node, krita.VectorLayer):
		return rucksack.NodeKind.LAYER_VECTOR
	if isinstance(node, krita.ColorizeMask):
		return rucksack.NodeKind.MASK_COLORIZE
	if isinstance(node, krita.FilterMask):
		return rucksack.NodeKind.MASK_FILTER
	if isinstance(node, krita.SelectionMask):
		return rucksack.NodeKind.MASK_SELECTION
	if isinstance(node, krita.TransformMask):
		return rucksack.NodeKind.MASK_TRANSFORM
	if isinstance(node, krita.TransparencyMask):
		return rucksack.NodeKind.MASK_TRANSPARENCY
	return rucksack.NodeKind.LAYER


class Location(Enum):
	LOCAL = enum.auto()
	GLOBAL = enum.auto()


class Dialog(QDialog):
	add_new = pyqtSignal(Location, str, int)  # location, name, chosen save
	delete = pyqtSignal(Location, int)  # location, index
	rename = pyqtSignal(
		Location, int, Location, str
	)  # location, index, new location, new name
	replace = pyqtSignal(Location, int, int)  # location, index, chosen save
	refresh = pyqtSignal(Location)
	chosen = pyqtSignal(Location, int)  # location, index

	text_box: LineEditCaptureEscape
	entries: list[tuple[Entry, int]] = []  # entries and their original index
	no_entries_text: QLabel | None = None
	new_entry: tuple[Entry, int] | None = None  # entry, chosen save
	entry_list: QVBoxLayout
	allow_local: bool
	possible_saves: list[tuple[rucksack.ItemData, bool]]
	kr: Krita

	def __init__(
		self,
		kr: Krita,
		allow_local: bool,
		possible_saves: list[tuple[rucksack.ItemData, bool]],
	) -> None:
		super().__init__()
		self.kr = kr

		self.setWindowTitle("Rucksack")
		self.setMinimumWidth(300)

		self.allow_local = allow_local

		layout = QVBoxLayout()

		self.text_box = LineEditCaptureEscape()
		self.text_box.setPlaceholderText("Item…")
		self.text_box.textChanged.connect(self.on_text_change)
		self.text_box.escape.connect(self.reject)
		layout.addWidget(self.text_box)

		self.entry_list = QVBoxLayout()
		layout.addLayout(self.entry_list)
		layout.addStretch()

		self.possible_saves = possible_saves

		for i, (item, enabled) in enumerate(possible_saves):
			button = QPushButton(f"Save {save_desc(item)}")
			button.clicked.connect(lambda *args, i=i: self.begin_save(i))
			button.setEnabled(enabled)
			button.setAutoDefault(False)
			layout.addWidget(button)

		self.setLayout(layout)

	def set_items(
		self, global_items: list[rucksack.Item], local_items: list[rucksack.Item]
	) -> None:
		for entry, _ in self.entries:
			entry.deleteLater()
		if self.no_entries_text is not None:
			self.no_entries_text.deleteLater()
		self.no_entries_text = None

		self.text_box.setFocus()

		self.entries = [
			(
				Entry(
					self.kr,
					location,
					item,
					allow_local=self.allow_local,
					possible_saves=self.possible_saves,
				),
				i,
			)
			for location, i, item in (
				*((Location.GLOBAL, i, item) for i, item in enumerate(global_items)),
				*((Location.LOCAL, i, item) for i, item in enumerate(local_items)),
			)
		]
		self.entries.sort(key=lambda e: e[0].item.name)

		for i, (entry, orig_i) in enumerate(self.entries):
			before = self.entries[i - 1][0].item.name if 0 < i else ""
			after = (
				self.entries[i + 1][0].item.name if i + 1 < len(self.entries) else ""
			)
			prefix_len = 0
			for char_index, char in enumerate(entry.item.name):
				if (len(before) <= char_index or before[char_index] != char) and (
					len(after) <= char_index or after[char_index] != char
				):
					prefix_len = char_index + 1
					break
			entry.set_prefix_len(prefix_len)
			entry.deleted.connect(
				lambda i=orig_i, e=entry: self.delete.emit(e.location, i)
			)
			entry.renamed.connect(lambda *args, i=i: self.rename_helper(i, *args))
			entry.chosen.connect(lambda *args, i=i: self.chosen_helper(i, *args))
			entry.replaced.connect(
				lambda j, i=orig_i, e=entry: self.replace.emit(e.location, i, j)
			)
			self.entry_list.addWidget(entry)

		if not self.entries:
			self.no_entries_text = QLabel()
			self.no_entries_text.setText("Rucksack is empty…")
			self.no_entries_text.setStyleSheet("color:grey;font-style:italic")
			self.entry_list.addWidget(self.no_entries_text)

	def rename_helper(self, i: int, location: Location, new_name: str) -> None:
		if new_name:
			entry, orig_i = self.entries[i]
			self.rename.emit(entry.location, orig_i, location, new_name)
		else:
			self.refresh.emit(location)

	def chosen_helper(self, i: int, linger: bool) -> None:
		entry, orig_i = self.entries[i]
		self.chosen.emit(entry.location, orig_i)
		if not linger:
			self.accept()

	def begin_save(self, i: int) -> None:
		if self.new_entry is None:
			location = Location.LOCAL if self.allow_local else Location.GLOBAL
			item = rucksack.Item(name="", data=self.possible_saves[i][0])
			self.new_entry = (
				Entry(
					self.kr,
					location,
					item,
					allow_local=self.allow_local,
					possible_saves=[],
				),
				i,
			)
			self.new_entry[0].begin_rename()
			self.new_entry[0].renamed.connect(self.end_save)
			self.entry_list.addWidget(self.new_entry[0])
		else:
			self.new_entry[0].set_kind(self.possible_saves[i][0])
		self.new_entry[0].focus()

	def end_save(self, location: Location, new_name: str) -> None:
		assert self.new_entry is not None
		if new_name:
			self.add_new.emit(location, new_name, self.new_entry[1])
		self.new_entry[0].deleteLater()
		self.new_entry = None

	def on_text_change(self, text: str) -> None:
		text = text.strip()
		for entry, orig_i in self.entries:
			if entry.on_text_change(text):
				# If the name ends in a number, exiting immediately can cause the number to have an
				# effect like rotating the canvas. We instead approximately track if there are any
				# keys pressed, and if so wait until they’ve been released, but timing out after
				# some time.
				if self.text_box.num_pressed == 0:
					self.accept()
				else:
					self.text_box.setEnabled(False)
					QTimer.singleShot(200, lambda: self.accept())
				self.chosen.emit(entry.location, orig_i)
				break

	def keyReleaseEvent(self, e: QKeyEvent) -> None:
		if not self.text_box.isEnabled():
			self.text_box.num_pressed -= 1
			if self.text_box.num_pressed == 0:
				self.accept()
			return
		super().keyReleaseEvent(e)


class Entry(QWidget):
	deleted = pyqtSignal()
	renamed = pyqtSignal(Location, str)
	replaced = pyqtSignal(int)
	chosen = pyqtSignal(bool)
	location: Location
	item: rucksack.Item

	prefix_len: int
	layout_: QHBoxLayout
	icon: QLabel
	label: QLabel | QLineEdit
	kr: Krita
	is_global_button: QToolButton
	possible_saves: list[tuple[rucksack.ItemData, bool]]

	def __init__(
		self,
		kr: Krita,
		location: Location,
		item: rucksack.Item,
		allow_local: bool,
		possible_saves: list[tuple[rucksack.ItemData, bool]],
	) -> None:
		super().__init__()
		self.kr = kr
		self.possible_saves = possible_saves

		self.location = location
		self.layout_ = QHBoxLayout()
		self.layout_.setContentsMargins(4, 0, 0, 0)

		self.icon = QLabel()
		self.item = item
		self.set_kind(item.data)
		self.layout_.addWidget(self.icon)

		self.label = QLabel()
		self.label.setTextFormat(Qt.RichText)
		self.layout_.addWidget(self.label, 1)

		self.is_global_button = QToolButton()
		self.is_global_button.setCheckable(True)
		self.is_global_button.setEnabled(allow_local)
		self.is_global_button.setIcon(kr.icon("go-home"))
		self.is_global_button.setChecked(location == Location.GLOBAL)
		self.is_global_button.clicked.connect(self.on_global_button_click)
		self.update_global_button()
		self.layout_.addWidget(self.is_global_button)

		color = self.palette().color(QPalette.Base)
		self.setStyleSheet(f"Entry:hover {{ background: {color.name()} }}")

		self.setContextMenuPolicy(Qt.CustomContextMenu)
		self.customContextMenuRequested.connect(self.show_context_menu)

		self.setLayout(self.layout_)

	def set_kind(self, item: rucksack.ItemData) -> None:
		self.item = rucksack.Item(name=self.item.name, data=item)

		def icon(item: rucksack.ItemData) -> str:
			match item:
				case rucksack.Node(kind=kind):
					match kind:
						case rucksack.NodeKind.LAYER:
							return "paintLayer"
						case rucksack.NodeKind.LAYER_FILE:
							return "fileLayer"
						case rucksack.NodeKind.LAYER_FILL:
							return "fillLayer"
						case rucksack.NodeKind.LAYER_FILTER:
							return "filterLayer"
						case rucksack.NodeKind.LAYER_GROUP:
							return "groupLayer"
						case rucksack.NodeKind.LAYER_VECTOR:
							return "vectorLayer"
						case rucksack.NodeKind.MASK_COLORIZE:
							return "colorizeMask"
						case rucksack.NodeKind.MASK_FILTER:
							return "filterMask"
						case rucksack.NodeKind.MASK_SELECTION:
							return "selectionMask"
						case rucksack.NodeKind.MASK_TRANSFORM:
							return "transformMask"
						case rucksack.NodeKind.MASK_TRANSPARENCY:
							return "transparencyMask"
				case rucksack.Vector(is_text=is_text):
					return "draw-text" if is_text else "krita_tool_freehandvector"
				case rucksack.LayerStyle():
					return "layer-style-enabled"

		self.icon.setPixmap(self.kr.icon(icon(item)).pixmap(16))

	def on_global_button_click(self):
		self.update_global_button()
		if isinstance(self.label, QLabel):
			self.is_global_button.setEnabled(False)
			is_global = self.is_global_button.isChecked()
			self.renamed.emit(
				Location.GLOBAL if is_global else Location.LOCAL, self.item.name
			)

	def update_global_button(self):
		is_global = self.is_global_button.isChecked()
		self.is_global_button.setToolTip(
			"This item is shared across all files"
			if is_global
			else "This item is local to the folder"
		)

	def set_prefix_len(self, prefix_len: int) -> None:
		self.prefix_len = prefix_len
		name = self.item.name
		self.label.setText(
			f"<b>{html.escape(name[:prefix_len])}</b>{html.escape(name[prefix_len:])}"
		)

	def show_context_menu(self, position: QPoint) -> None:
		if isinstance(self.label, QLineEdit):
			return

		menu = QMenu()
		use_action = menu.addAction("Use")
		use_linger_action = menu.addAction("Use and stay open")
		rename_action = menu.addAction("Rename")
		delete_action = menu.addAction("Delete")
		menu.addSeparator()

		save_actions = []
		for item, enabled in self.possible_saves:
			desc = save_desc(item).replace("&", "")
			action = menu.addAction("Replace with " + desc)
			save_actions.append(action)
			action.setEnabled(enabled)

		action = menu.exec_(self.mapToGlobal(position))
		if action == use_action:
			self.chosen.emit(False)
		elif action == use_linger_action:
			self.chosen.emit(True)
		elif action == rename_action:
			self.begin_rename()
		elif action == delete_action:
			self.deleted.emit()
		else:
			try:
				i = next(i for i, a in enumerate(save_actions) if a == action)
			except StopIteration:
				return
			self.replaced.emit(i)

	def begin_rename(self) -> None:
		self.label.deleteLater()
		self.label = LineEditCaptureEscape()
		self.label.setText(self.item.name)
		self.label.returnPressed.connect(lambda: self.end_rename(cancel=False))
		self.label.escape.connect(lambda: self.end_rename(cancel=True))
		self.label.selectAll()

		# Temporarily reparent our current widgets so we can correctly reset the tab order. AFAICT
		# this is the only way to achieve this.
		# https://forum.qt.io/topic/159583/can-t-set-tab-order-after-rearranging-widgets/12
		temp_parent = QWidget()
		temp_layout = QVBoxLayout(temp_parent)
		temp_layout.addWidget(self.is_global_button)

		accept_button = QPushButton()
		cancel_button = QPushButton()
		accept_button.setIcon(self.kr.icon("dialog-ok"))
		cancel_button.setIcon(self.kr.icon("dialog-cancel"))
		accept_button.clicked.connect(lambda: self.end_rename(cancel=False))
		cancel_button.clicked.connect(lambda: self.end_rename(cancel=True))

		self.layout_.addWidget(self.label)
		self.layout_.addWidget(self.is_global_button)
		self.layout_.addWidget(accept_button)
		self.layout_.addWidget(cancel_button)

		self.focus()

	def end_rename(self, cancel: bool) -> None:
		assert isinstance(self.label, QLineEdit)
		text = self.label.text().strip() if not cancel else ""
		self.renamed.emit(
			Location.GLOBAL if self.is_global_button.isChecked() else Location.LOCAL,
			text,
		)

	def focus(self) -> None:
		assert isinstance(self.label, QLineEdit)
		self.label.setFocus()

	def on_text_change(self, text: str) -> bool:
		if isinstance(self.label, QLineEdit):
			return False
		if self.prefix_len != 0 and text == self.item.name[: self.prefix_len]:
			return True
		self.label.setEnabled(self.item.name.startswith(text))
		return False

	# Applies stylesheets to the current widget.
	def paintEvent(self, e: QPaintEvent) -> None:
		if isinstance(self.label, QLineEdit):
			return super().paintEvent(e)
		opt = QStyleOption()
		opt.initFrom(self)
		p = QPainter(self)
		self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)

	def mousePressEvent(self, event: QMouseEvent) -> None:
		if isinstance(self.label, QLabel):
			if event.button() == Qt.LeftButton:
				self.chosen.emit(bool(event.modifiers() & Qt.ShiftModifier))
				return
			elif event.button() == Qt.MiddleButton:
				self.chosen.emit(True)
				return
		super().mousePressEvent(event)


def save_desc(item: rucksack.ItemData) -> str:
	match item:
		case rucksack.Node(kind=kind):
			return "&mask" if kind.is_mask() else "&layer"
		case rucksack.Vector(is_text=is_text):
			return "&text" if is_text else "&vector"
		case rucksack.LayerStyle():
			return "layer &style"


class LineEditCaptureEscape(QLineEdit):
	escape = pyqtSignal()
	num_pressed: int = 0

	def keyPressEvent(self, e: QKeyEvent):
		self.num_pressed += 1
		if e.key() == Qt.Key_Escape:
			self.escape.emit()
		else:
			super().keyPressEvent(e)

	def keyReleaseEvent(self, e: QKeyEvent):
		self.num_pressed = max(self.num_pressed - 1, 0)
		super().keyReleaseEvent(e)


def unwrap[T](val: T | None) -> T:
	assert val is not None
	return val
