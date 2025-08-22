from __future__ import annotations

import asyncio
import enum
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import krita
from krita import Krita
from PyQt5.QtCore import QPoint, Qt, pyqtSignal, qInfo, qWarning
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import (
	QAbstractItemView,
	QCheckBox,
	QComboBox,
	QDialog,
	QDialogButtonBox,
	QFileDialog,
	QFormLayout,
	QHBoxLayout,
	QInputDialog,
	QLineEdit,
	QListWidget,
	QListWidgetItem,
	QMenu,
	QMessageBox,
	QPushButton,
	QSpinBox,
	QToolButton,
	QVBoxLayout,
	QWidget,
)

from . import async_hack, json_cursor


class Format(Enum):
	PNG = enum.auto()
	WEBP_LOSSLESS = enum.auto()
	WEBP_LOSSY = enum.auto()

	def display_name(self) -> str:
		if self == Format.PNG:
			return "PNG"
		elif self == Format.WEBP_LOSSLESS:
			return "WebP (Lossless)"
		elif self == Format.WEBP_LOSSY:
			return "WebP (Lossy)"


@dataclass
class ExportSettings:
	export_path: str = ""
	format: Format = Format.PNG
	png_compression: int = 9
	oxipng: bool = False
	webp_method: int = 5

	def export_opts(self) -> tuple[str, krita.InfoObject]:
		config = krita.InfoObject()
		if self.format == Format.PNG:
			config.setProperty(
				"compression", self.png_compression if not self.oxipng else 1
			)
			return ("png", config)
		elif self.format == Format.WEBP_LOSSLESS:
			# https://github.com/KDE/krita/blob/93c4f746da3a7f2c56e3110c457684ff05175024/plugins/impex/webp/kis_wdg_options_webp.cpp#L172
			config.setProperty("lossless", True)
			config.setProperty("method", self.webp_method)
			return ("webp", config)
		elif self.format == Format.WEBP_LOSSY:
			config.setProperty("lossless", False)
			config.setProperty("method", self.webp_method)
			return ("webp", config)

	@staticmethod
	def from_json(path: Path) -> ExportSettings:
		root = json_cursor.Any.from_file(path).object()
		self = ExportSettings(
			export_path=root.get("export_path").str().nonempty(),
			format=root.get("format").enum(Format),
			png_compression=root.get("png_compression").int().between(1, 9),
			oxipng=root.get("oxipng").bool(),
			webp_method=root.get("webp_method").int().between(0, 6),
		)
		root.deny_unknown()
		return self

	def to_json(self, path: Path) -> None:
		data = {
			"export_path": self.export_path,
			"format": self.format.name,
			"png_compression": self.png_compression,
			"oxipng": self.oxipng,
			"webp_method": self.webp_method,
		}
		with open(path, "w") as f:
			json.dump(data, f)


class Widget(QWidget):
	kr: Krita

	file_list: QListWidget
	current_dir: Path | None = None
	active_file: QListWidgetItem | None = None

	prev_btn: QPushButton
	next_btn: QPushButton
	import_btn: QPushButton

	export_path_edit: QLineEdit
	export_btn: QPushButton
	export_settings_btn: QToolButton
	export_in_progress: bool = False

	tasks = async_hack.TaskSet()

	def __init__(self, kr: Krita) -> None:
		super().__init__()
		self.kr = kr

		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)

		nav_layout = QHBoxLayout()
		self.prev_btn = PushButtonCaptureAlt("←")
		self.next_btn = PushButtonCaptureAlt("→")
		self.import_btn = QPushButton("+")
		refresh_btn = QPushButton("⟳")
		select_btn = QPushButton()
		select_btn.setIcon(self.kr.icon("folder"))
		self.prev_btn.clicked.connect(lambda: self.go(-1, False))
		self.next_btn.clicked.connect(lambda: self.go(1, False))
		self.prev_btn.clicked_alt.connect(lambda: self.go(-1, True))
		self.next_btn.clicked_alt.connect(lambda: self.go(1, True))
		self.import_btn.clicked.connect(self.import_images)
		refresh_btn.clicked.connect(self.refresh)
		select_btn.clicked.connect(self.select_dir)
		self.prev_btn.setToolTip("Go to previous file")
		self.next_btn.setToolTip("Go to next file")
		self.import_btn.setToolTip("Import files as .kra files")
		refresh_btn.setToolTip("Refresh file list")
		select_btn.setToolTip("Select folder")
		for btn in [
			self.prev_btn,
			self.next_btn,
			self.import_btn,
			refresh_btn,
			select_btn,
		]:
			btn.setStyleSheet("margin:0px;padding:0px")
			nav_layout.addWidget(btn)
		layout.addLayout(nav_layout)

		self.file_list = QListWidget()
		self.file_list.setSortingEnabled(True)
		self.file_list.itemDoubleClicked.connect(self.open_file)
		self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
		self.file_list.customContextMenuRequested.connect(self.show_context_menu)
		self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
		layout.addWidget(self.file_list, 1)

		export_layout = QHBoxLayout()

		self.export_path_edit = QLineEdit()
		self.export_path_edit.setPlaceholderText("Export to…")
		self.export_path_edit.textChanged.connect(self.update_export_state)
		browse_btn = QPushButton()
		browse_btn.setIcon(self.kr.icon("folder"))
		browse_btn.setFixedWidth(30)
		browse_btn.clicked.connect(self.choose_export_path)
		export_layout.addWidget(self.export_path_edit, 3)
		export_layout.addWidget(browse_btn, 1)

		self.export_btn = QPushButton()
		self.export_btn.clicked.connect(lambda: self.export_files(self.listed_files()))

		self.export_settings_btn = QToolButton()
		self.export_settings_btn.setIcon(self.kr.icon("configure"))
		self.export_settings_btn.setToolTip("Export Settings")
		self.export_settings_btn.clicked.connect(self.open_settings)

		export_btns_layout = QHBoxLayout()
		export_btns_layout.addWidget(self.export_btn)
		export_btns_layout.addWidget(self.export_settings_btn)

		export_layout.addLayout(export_btns_layout, 2)
		layout.addLayout(export_layout)

		self.refresh()
		self.update_export_state()

	def canvas_changed(self, canvas: krita.Canvas | None) -> None:
		if canvas is not None:
			if (view := canvas.view()) is not None:
				self.document_changed(view.document())
				return
		self.document_changed(None)

	def refresh(self) -> None:
		self.document_changed(self.kr.activeDocument())

	def document_changed(self, doc: object) -> None:
		if isinstance(doc, krita.Document):
			if doc.fileName():
				self.set_current_dir(Path(doc.fileName()).parent)
				return
		self.set_current_dir(None)

	def set_current_dir(self, current_dir: Path | None) -> None:
		self.current_dir = current_dir
		self.update_file_list()
		export_settings = self.load_export_settings()
		self.export_path_edit.setText(export_settings.export_path)
		self.import_btn.setEnabled(current_dir is not None)

	def update_file_list(self) -> None:
		self.file_list.clear()
		self.active_file = None

		active_file_name = None
		if (doc := self.kr.activeDocument()) is not None:
			if doc.fileName():
				active_file_name = Path(doc.fileName())

		files = []
		if self.current_dir is not None:
			try:
				files = sorted(
					[
						f
						for f in os.listdir(self.current_dir)
						if Path(f).suffix in image_formats
					],
					key=lambda s: s.lower(),
				)
			except Exception as e:
				self.error(f"error reading directory: {str(e)}")
				files = []

			for fname in files:
				item = QListWidgetItem(fname)
				item.setData(Qt.UserRole, self.current_dir / fname)
				self.file_list.addItem(item)

				if self.current_dir / fname == active_file_name:
					self.file_list.scrollTo(self.file_list.indexFromItem(item))
					self.file_list.setCurrentItem(item)
					self.active_file = item

		self.prev_btn.setEnabled(self.active_file is not None)
		self.next_btn.setEnabled(self.active_file is not None)

	def update_export_state(self) -> None:
		valid = self.current_dir is not None and bool(
			self.export_path_edit.text().strip()
		)
		if self.export_in_progress:
			self.export_btn.setEnabled(False)
			self.export_btn.setText("Exporting…")
		else:
			self.export_btn.setEnabled(valid)
			self.export_btn.setToolTip(
				"Export all KRA files" if valid else "Select export directory first"
			)
			self.export_btn.setText("Export")
		self.export_settings_btn.setEnabled(valid)
		if valid:
			settings = self.load_export_settings()
			if settings.export_path != self.export_path_edit.text().strip():
				settings.export_path = self.export_path_edit.text().strip()
				self.save_export_settings(settings)

	def select_dir(self) -> None:
		path = QFileDialog.getExistingDirectory(self, "Select Directory")
		if path:
			self.set_current_dir(Path(path))

	def show_context_menu(self, position: QPoint) -> None:
		items = self.file_list.selectedItems()
		file_paths: list[Path] = [item.data(Qt.UserRole) for item in items]
		if not file_paths:
			return

		menu = QMenu()
		open_action = menu.addAction("Open")
		delete_action = menu.addAction("Delete")
		rename_action = menu.addAction("Rename")
		export_action = menu.addAction("Export")
		distribute_action = menu.addAction("Copy current layer to file(s)")
		export_action.setEnabled(bool(self.export_path_edit.text().strip()))

		action = menu.exec_(self.file_list.mapToGlobal(position))
		if action == open_action:
			self.open_file(items[0])
		elif action == delete_action:
			self.delete_file(file_paths)
		elif action == rename_action:
			self.rename_file(file_paths[0])
		elif action == export_action:
			self.export_files(file_paths, force=True)
		elif action == distribute_action:
			self.distribute(file_paths)

	def open_file(self, item: QListWidgetItem) -> None:
		if (win := self.kr.activeWindow()) is None:
			qWarning("no active window")
			return
		target_path = str(item.data(Qt.UserRole))
		doc, _, _ = self.open_or_reuse(target_path)
		try:
			v = next(v for v in win.views() if v.document() == doc)
			v.setVisible()
		except StopIteration:
			win.addView(doc)

	# returns (document, opened new, should save)
	def open_or_reuse(self, path: str) -> tuple[krita.Document | None, bool, bool]:
		try:
			doc = next(d for d in self.kr.documents() if d.fileName() == path)
			return (doc, False, not doc.modified())
		except StopIteration:
			return (self.kr.openDocument(path), True, True)

	def go(self, offset: int, keep_current: bool) -> None:
		current_doc = self.kr.activeDocument()

		if self.active_file is None:
			return
		new = (self.file_list.row(self.active_file) + offset) % self.file_list.count()
		item = self.file_list.item(new)
		assert item is not None
		self.open_file(item)

		if not keep_current and current_doc is not None and not current_doc.modified():
			current_doc.close()

	def import_images(self) -> None:
		if self.current_dir is None:
			return
		current_doc = self.kr.activeDocument()

		title = "Select Images to Import"
		image_format_list = " ".join(f"*{ext}" for ext in image_formats)
		files, _ = QFileDialog.getOpenFileNames(
			self, title, "", f"Images ({image_format_list})"
		)
		if not files:
			return

		options_dialog = QDialog(self)
		options_dialog.setWindowTitle("Import Settings")
		layout = QFormLayout(options_dialog)

		dpi_spin = QSpinBox()
		dpi_spin.setRange(72, 600)
		dpi_spin.setValue(72)
		layout.addRow("DPI:", dpi_spin)

		with_existing = QComboBox()
		with_existing.addItem("Skip")
		with_existing.addItem("Overwrite")
		with_existing.addItem("Add as layer")
		with_existing.setCurrentIndex(0)
		layout.addRow("If files already exist:", with_existing)

		copy_structure = QCheckBox()
		if current_doc is not None:
			layout.addRow(
				"Copy non-background layers from current document:", copy_structure
			)

		file_layer = QCheckBox()
		layout.addRow("Import as file layer:", file_layer)

		buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
		buttons.accepted.connect(options_dialog.accept)
		buttons.rejected.connect(options_dialog.reject)
		layout.addRow(buttons)

		if options_dialog.exec_() != QDialog.Accepted:
			return

		imported = 0
		for src_path in files:
			dst_path = self.current_dir / (Path(src_path).stem + ".kra")

			add_to_dst_as_layer = False

			if dst_path.exists():
				i = with_existing.currentIndex()
				if i == 0:
					qWarning(f"skipping {dst_path} (already exists)")
					continue
				elif i == 1:
					pass
				elif i == 2:
					add_to_dst_as_layer = True
				else:
					raise Exception

			qInfo(f"exporting {src_path} to {dst_path}")
			if (doc := self.kr.openDocument(src_path)) is None or (
				root_node := doc.rootNode()
			) is None:
				self.error(f"failed to open {src_path}")
				break

			try:
				doc.setResolution(dpi_spin.value())

				if add_to_dst_as_layer:
					dst_doc, opened_new, should_save = self.open_or_reuse(str(dst_path))
					if dst_doc is None or (dst_node := dst_doc.rootNode()) is None:
						self.error(f"failed to open {dst_path}")
						break
					try:
						dst_doc.setBatchmode(True)

						if file_layer.isChecked():
							# We don’t actually need to open `doc` in this particular case. Seems
							# hard to optimize that though.
							layer = dst_doc.createFileLayer(
								"Foreground", str(src_path), "None"
							)
							dst_node.addChildNode(layer, None)
						else:
							for node in doc.topLevelNodes():
								dst_node.addChildNode(node.clone(), None)

						if should_save and not dst_doc.save():
							self.error(f"failed to save {dst_path}")
							break
					finally:
						if opened_new:
							dst_doc.close()
						else:
							dst_doc.setBatchmode(False)
				else:
					if file_layer.isChecked():
						existing_nodes = doc.topLevelNodes()

						layer = doc.createFileLayer("Background", str(src_path), "None")
						root_node.addChildNode(layer, None)

						for node in existing_nodes:
							node.remove()

					if copy_structure.isChecked() and current_doc is not None:
						for node in current_doc.topLevelNodes():
							if node.name() == "Background":
								continue
							root_node.addChildNode(node.clone(), None)

					if not doc.saveAs(str(dst_path)):
						self.error(f"failed to save to {dst_path}")
						break

					self.update_file_list()
			finally:
				doc.close()
			imported += 1

		self.floating_message("dialog-ok", f"successfully imported {imported} files")

	def distribute(self, files: list[Path]) -> None:
		if (src_doc := self.kr.activeDocument()) is None:
			return
		if (src_node := src_doc.activeNode()) is None:
			return

		for file in files:
			if src_doc.fileName() == str(file):
				continue

			doc, opened_new, should_save = self.open_or_reuse(str(file))
			if doc is None:
				self.error(f"failed to open {file}")
				break

			try:
				doc.setBatchmode(True)

				if (root_node := doc.rootNode()) is None:
					continue
				root_node.addChildNode(src_node.clone(), None)

				if should_save and not doc.save():
					self.error(f"failed to save {file}")
					break
			finally:
				if opened_new:
					doc.close()
				else:
					doc.setBatchmode(False)

	def choose_export_path(self):
		path = QFileDialog.getExistingDirectory(self, "Select Export Directory")
		if path:
			self.export_path_edit.setText(path)
		# self.update_export_state() will be called automatically

	def listed_files(self) -> list[Path]:
		files = []
		for i in range(self.file_list.count()):
			item = self.file_list.item(i)
			assert item is not None
			files.append(item.data(Qt.UserRole))
		return files

	def export_files(self, src_paths: list[Path], force: bool = False) -> None:
		self.tasks.spawn(self.export_files_inner(src_paths, force))

	async def export_files_inner(
		self, src_paths: list[Path], force: bool = False
	) -> None:
		settings = self.load_export_settings()
		ext, export_config = settings.export_opts()

		self.export_in_progress = True
		self.update_export_state()
		compressors = []
		updated = 0

		try:
			for src_path in src_paths:
				dst_path = Path(settings.export_path) / f"{src_path.stem}.{ext}"

				try:
					if (
						not force
						and src_path.stat().st_mtime <= dst_path.stat().st_mtime
					):
						continue
				except FileNotFoundError:
					pass
				except Exception as e:
					self.error(f"could not save to {dst_path}: {str(e)}")
					return

				doc, opened_new, _ = self.open_or_reuse(str(src_path))
				if doc is None:
					self.error(f"failed to open {src_path}")
					return

				try:
					doc.setBatchmode(True)
					doc.waitForDone()

					# Sometimes layers will disappear if you export immediately. Adding this sleep
					# in improves reliability.
					# https://bugs.kde.org/show_bug.cgi?id=465691
					await async_hack.Wrap(asyncio.sleep(0.5))

					if not doc.exportImage(str(dst_path), export_config):
						self.error(
							f"Could not export {src_path}. This is sometimes a bug in Krita, and you should just try again."
						)
						return

					if settings.format == Format.PNG and settings.oxipng:
						level = str(min(6, settings.png_compression - 1))
						try:
							coro = asyncio.create_subprocess_exec(
								"oxipng.exe" if os.name == "nt" else "oxipng",
								"--opt",
								level,
								"--threads",
								"1",
								dst_path,
								"--alpha",
							)
							compressors.append(await async_hack.Wrap(coro))
						except Exception as e:
							self.error(f"could not run oxipng: {str(e)}")
							return

					updated += 1
					qInfo(f"exported to {dst_path}")
				finally:
					if opened_new:
						doc.close()
					else:
						doc.setBatchmode(False)
		finally:
			try:
				for c in compressors:
					await async_hack.Wrap(c.wait())
			finally:
				self.export_in_progress = False
				self.update_export_state()
		self.floating_message(
			"dialog-ok",
			f"successfully exported {len(src_paths)} file(s) (updated {updated})",
		)

	def delete_file(self, file_paths: list[Path]) -> None:
		if (
			QMessageBox.question(
				self,
				"Confirm Delete",
				f"Delete {', '.join(file_path.name for file_path in file_paths)}?",
				QMessageBox.Yes | QMessageBox.No,
			)
			!= QMessageBox.Yes
		):
			return

		paths_to_close = {str(file_path) for file_path in file_paths}
		for doc in self.kr.documents():
			if doc.fileName() in paths_to_close:
				doc.close()

		for file_path in file_paths:
			try:
				file_path.unlink()
			except Exception as e:
				self.error(f"could not delete {file_path}: {str(e)}")
		self.update_file_list()

	def rename_file(self, file_path: Path) -> None:
		if self.current_dir is None:
			return

		new_name, ok = QInputDialog.getText(
			self, "Rename File", "New name:", text=file_path.stem
		)
		if not ok or not new_name:
			return
		new_path = self.current_dir / f"{new_name.removesuffix('.kra')}.kra"
		try:
			if new_path.exists():
				raise Exception("target already exists")

			docs = [
				doc for doc in self.kr.documents() if doc.fileName() == str(file_path)
			]

			file_path.rename(new_path)

			for doc in docs:
				doc.setFileName(str(new_path))

			self.update_file_list()
		except Exception as e:
			self.error(f"could not rename {file_path} to {new_path}: {str(e)}")

	def open_settings(self) -> None:
		settings = self.load_export_settings()

		dialog = QDialog(self)
		dialog.setWindowTitle("Export settings")
		layout = QFormLayout(dialog)

		format_combo = QComboBox()
		for v in Format:
			format_combo.addItem(v.display_name(), v)
			if v == settings.format:
				format_combo.setCurrentIndex(format_combo.count() - 1)
		layout.addRow("Format:", format_combo)

		png_compression = QSpinBox()
		png_compression.setRange(1, 9)
		png_compression.setValue(settings.png_compression)
		layout.addRow("PNG Compression:", png_compression)

		oxipng = QCheckBox()
		oxipng.setChecked(settings.oxipng)
		layout.addRow("Use oxipng (requires oxipng installed):", oxipng)

		webp_method = QSpinBox()
		webp_method.setRange(0, 6)
		webp_method.setValue(settings.webp_method)
		layout.addRow("WebP Compression:", webp_method)

		buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
		buttons.accepted.connect(dialog.accept)
		buttons.rejected.connect(dialog.reject)
		layout.addRow(buttons)

		if dialog.exec_() == QDialog.Accepted:
			settings.format = format_combo.currentData()
			settings.png_compression = png_compression.value()
			settings.oxipng = oxipng.isChecked()
			settings.webp_method = webp_method.value()
			self.save_export_settings(settings)

	def save_export_settings(self, settings: ExportSettings) -> None:
		if self.current_dir is None:
			return
		try:
			settings.to_json(self.current_dir / "export_settings.json")
		except Exception as e:
			self.error(f"could not save settings: {str(e)}")

	def load_export_settings(self) -> ExportSettings:
		if self.current_dir is None:
			return ExportSettings()

		config_path = self.current_dir / "export_settings.json"

		try:
			if not config_path.exists():
				return ExportSettings()

			return ExportSettings.from_json(config_path)
		except Exception as e:
			qWarning(f"loading settings from {config_path}: {str(e)}")
			return ExportSettings()

	def error(self, msg: str) -> None:
		qWarning(msg)
		self.floating_message("dialog-warning", msg)

	# see https://scripting.krita.org/icon-library for the icons available
	def floating_message(self, icon: str, msg: str) -> None:
		if (win := self.kr.activeWindow()) is not None:
			if (view := win.activeView()) is not None:
				view.showFloatingMessage(msg, self.kr.icon(icon), 2000, 1)


image_formats: list[str] = [
	".avif",
	".bmp",
	".heif",
	".jpeg",
	".jpg",
	".jxl",
	".kra",
	".ora",
	".png",
	".psd",
	".tiff",
	".webp",
]


class PushButtonCaptureAlt(QPushButton):
	clicked_alt = pyqtSignal()

	def mousePressEvent(self, e: QMouseEvent) -> None:
		if bool(e.modifiers() & Qt.ShiftModifier) or e.button() == Qt.MiddleButton:
			self.clicked_alt.emit()
			return
		super().mousePressEvent(e)
