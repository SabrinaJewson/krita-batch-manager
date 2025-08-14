from krita import Krita
from PyQt5.QtWidgets import *
import importlib
import krita
import os
import sys

from . import widget

class DockWidget(krita.DockWidget):
	w: widget.Widget | None
	kr: Krita

	def __init__(self) -> None:
		super().__init__()
		if (kr := Krita.instance()) is None: return
		self.kr = kr

		self.setWindowTitle("Batch Manager")
		self.w = widget.Widget(self.kr)

		if os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dev_mode")):
			container = QWidget()
			layout = QVBoxLayout(container)

			reload_btn = QPushButton("Reload")
			reload_btn.clicked.connect(lambda: self.reload(layout))
			layout.addWidget(reload_btn)

			layout.addWidget(self.w)

			self.setWidget(container)
		else:
			self.setWidget(self.w)

	def canvasChanged(self, canvas: krita.Canvas | None) -> None:
		if self.w is not None: self.w.canvas_changed(canvas)

	def reload(self, layout: QVBoxLayout) -> None:
		for m in list(m for n, m in sys.modules.items() if n.startswith(f"{__name__}.")):
			importlib.reload(m)
		if self.w is not None: self.w.setParent(None) # type: ignore[call-overload]
		self.w = None
		self.w = widget.Widget(self.kr)
		layout.addWidget(self.w)

if (kr := Krita.instance()) is not None:
	pos = krita.DockWidgetFactoryBase.DockPosition.DockRight
	kr.addDockWidgetFactory(krita.DockWidgetFactory("Batch Manager", pos, DockWidget))
