from krita import Krita
from PyQt5.QtWidgets import *
import importlib
import krita
import os
import sys

from . import docker

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

		if os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_mode")):
			container = QWidget()
			layout = QVBoxLayout(container)
			layout.setContentsMargins(0, 0, 0, 0)

			hlayout = QHBoxLayout(container)

			self.reload_btn = QPushButton("Reload")
			self.reload_btn.clicked.connect(lambda: self.reload(layout))
			hlayout.addWidget(self.reload_btn, 1)

			self.close_btn = QPushButton("×")
			self.close_btn.clicked.connect(self.close_it)
			hlayout.addWidget(self.close_btn)

			layout.addLayout(hlayout)
			layout.addWidget(self.w)

			self.setWidget(container)
		else:
			self.setWidget(self.w)

	def close_it(self) -> None:
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

if (kr := Krita.instance()) is not None:
	pos = krita.DockWidgetFactoryBase.DockPosition.DockRight
	kr.addDockWidgetFactory(krita.DockWidgetFactory("Batch Manager", pos, DockWidget))
