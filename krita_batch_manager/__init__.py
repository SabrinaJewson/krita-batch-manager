from krita import Krita
from PyQt5.QtWidgets import *
import importlib
import krita
import os
import sys

from . import docker
from . import open_rucksack

class DockWidget(krita.DockWidget):
	w: docker.Widget | None
	kr: Krita
	reload_btn: QPushButton
	close_btn: QPushButton

	def __init__(self) -> None:
		super().__init__()
		if (kr := Krita.instance()) is None: return
		self.kr = kr

		self.setWindowTitle("Batch Manager")
		self.w = docker.Widget(self.kr)

		if dev_mode:
			container = QWidget()
			layout = QVBoxLayout(container)
			layout.setContentsMargins(0, 0, 0, 0)

			hlayout = QHBoxLayout(container)

			self.reload_btn = QPushButton("Reload")
			self.reload_btn.clicked.connect(lambda: self.reload(layout))
			hlayout.addWidget(self.reload_btn, 2)

			self.close_btn = QPushButton("×")
			self.close_btn.clicked.connect(self.end_dev_mode)
			hlayout.addWidget(self.close_btn)

			layout.addLayout(hlayout)
			layout.addWidget(self.w)

			self.setWidget(container)
		else:
			self.setWidget(self.w)

	def end_dev_mode(self) -> None:
		dev_mode = False
		self.reload_btn.deleteLater()
		self.close_btn.deleteLater()

	def canvasChanged(self, canvas: krita.Canvas | None) -> None:
		if self.w is not None: self.w.canvas_changed(canvas)

	def reload(self, layout: QVBoxLayout) -> None:
		for m in list(m for n, m in sys.modules.items() if n.startswith(f"{__name__}.")):
			importlib.reload(m)
		if self.w is not None: self.w.setParent(None) # type: ignore[call-overload]
		self.w = None
		self.w = docker.Widget(self.kr)
		layout.addWidget(self.w)

class Extension(krita.Extension):
	kr: Krita

	def __init__(self, kr: Krita) -> None:
		super().__init__()
		self.kr = kr

	def setup(self) -> None:
		pass

	def createActions(self, window: krita.Window | None) -> None:
		if window is None: return
		if (action := window.createAction("open_rucksack", "Open Rucksack", "tools/scripts")) is None: return
		action.triggered.connect(self.open_rucksack)

	def open_rucksack(self) -> None:
		if dev_mode:
			for m in list(m for n, m in sys.modules.items() if n.startswith(f"{__name__}.")):
				importlib.reload(m)
		open_rucksack.run(self.kr)

if (kr := Krita.instance()) is not None:
	dev_mode = os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_mode"))

	pos = krita.DockWidgetFactoryBase.DockPosition.DockRight
	kr.addDockWidgetFactory(krita.DockWidgetFactory("Batch Manager", pos, DockWidget))
	kr.addExtension(Extension(kr))
